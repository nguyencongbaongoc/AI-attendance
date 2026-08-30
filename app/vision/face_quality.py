"""
Phase 17 — Adaptive Face Quality Assessment.

This module provides deterministic face quality assessment for the adaptive pipeline.
It evaluates measurable quality signals from face crops and metadata to classify
faces as GOOD, MARGINAL, or UNUSABLE for identity evidence eligibility.

CRITICAL ARCHITECTURE RULES:
- Quality is assessed on face crop / geometry / metadata with provenance to ORIGINAL_FRAME
- Does NOT replace detector, crop, tracking, ArcFace, identity matching, or attendance
- UNUSABLE only excludes from identity evidence, does NOT delete person or kill track
- Consumes Phase 15 pose information (NORMAL/HARD_POSE) instead of duplicating pose inference
- Preserves full provenance chain for Phase 18 temporal evidence compatibility
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.adaptive_crop import AdaptiveCropResult, CropProvenance
from app.vision.hardpose_contract import PoseState

logger = logging.getLogger(__name__)


# =============================================================================
# QUALITY ENUM AND METRICS
# =============================================================================

class QualityClass(str, Enum):
    """Final quality classification for identity evidence eligibility."""
    
    GOOD = "good"           # Sufficient for high-confidence identity evidence
    MARGINAL = "marginal"   # May contribute to temporal evidence with policy
    UNUSABLE = "unusable"   # Exclude from identity evidence


class MetricStatus(str, Enum):
    """Status of a quality metric measurement."""
    
    PASSED = "passed"
    FAILED = "failed"
    NOT_AVAILABLE = "not_available"  # Metric could not be computed


@dataclass(frozen=True)
class QualityMetric:
    """Individual quality metric result with explicit status and reason."""
    
    name: str
    measurement: float
    threshold: float
    status: MetricStatus
    reason: str
    unit: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "measurement": self.measurement,
            "threshold": self.threshold,
            "status": self.status.value,
            "reason": self.reason,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class QualityThresholds:
    """
    Centralized, configurable quality thresholds.
    
    These are engineering heuristics, not production accuracy claims.
    All thresholds must be validated with real data before production use.
    """
    
    # Face size thresholds (pixels in face crop)
    min_face_width: int = 64
    min_face_height: int = 64
    min_face_area: int = 4096  # 64x64
    min_inter_eye_distance: float = 15.0  # pixels in 112x112 aligned space
    
    # Detection confidence
    min_detection_confidence: float = 0.55
    
    # Sharpness (Laplacian variance)
    min_sharpness: float = 100.0
    
    # Brightness/exposure (mean intensity 0-255)
    brightness_min: float = 30.0
    brightness_max: float = 220.0
    
    # Boundary contact (fraction of face bbox touching frame edge)
    max_boundary_contact_ratio: float = 0.15
    
    # Pose (consumed from Phase 15)
    # NORMAL pose -> no penalty
    # HARD_POSE -> MARGINAL if other metrics pass
    # INVALID pose -> UNUSABLE
    
    # Occlusion
    max_occlusion_ratio: float = 0.3  # If occlusion detection available
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_face_width": self.min_face_width,
            "min_face_height": self.min_face_height,
            "min_face_area": self.min_face_area,
            "min_inter_eye_distance": self.min_inter_eye_distance,
            "min_detection_confidence": self.min_detection_confidence,
            "min_sharpness": self.min_sharpness,
            "brightness_min": self.brightness_min,
            "brightness_max": self.brightness_max,
            "max_boundary_contact_ratio": self.max_boundary_contact_ratio,
            "max_occlusion_ratio": self.max_occlusion_ratio,
        }


DEFAULT_QUALITY_THRESHOLDS = QualityThresholds()


# =============================================================================
# QUALITY RESULT WITH PROVENANCE
# =============================================================================

@dataclass(frozen=True)
class FaceQualityResult:
    """
    Complete face quality assessment result with full provenance.
    
    This is the canonical output of Phase 17 quality assessment.
    Downstream (Phase 18 temporal evidence) depends on this contract.
    """
    
    # Quality classification
    quality_class: QualityClass
    
    # Individual metrics
    metrics: List[QualityMetric]
    
    # Explainable reasons for classification
    reasons: List[str]
    
    # Evidence eligibility
    evidence_eligible: bool
    
    # Provenance chain
    provenance: "QualityProvenance"
    
    # Configuration used
    thresholds_used: QualityThresholds
    
    def __post_init__(self):
        """Validate quality result."""
        if not isinstance(self.quality_class, QualityClass):
            raise ValueError(f"quality_class must be QualityClass, got {type(self.quality_class)}")
        if not isinstance(self.evidence_eligible, bool):
            raise ValueError("evidence_eligible must be bool")
        if not isinstance(self.metrics, list):
            raise ValueError("metrics must be list")
        if not isinstance(self.reasons, list):
            raise ValueError("reasons must be list")
    
    @property
    def passed_metrics(self) -> List[QualityMetric]:
        """Get metrics that passed."""
        return [m for m in self.metrics if m.status == MetricStatus.PASSED]
    
    @property
    def failed_metrics(self) -> List[QualityMetric]:
        """Get metrics that failed."""
        return [m for m in self.metrics if m.status == MetricStatus.FAILED]
    
    @property
    def unavailable_metrics(self) -> List[QualityMetric]:
        """Get metrics that were not available."""
        return [m for m in self.metrics if m.status == MetricStatus.NOT_AVAILABLE]
    
    def get_metric(self, name: str) -> Optional[QualityMetric]:
        """Get a specific metric by name."""
        for m in self.metrics:
            if m.name == name:
                return m
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "quality_class": self.quality_class.value,
            "evidence_eligible": self.evidence_eligible,
            "reasons": self.reasons,
            "metrics": [m.to_dict() for m in self.metrics],
            "provenance": self.provenance.to_dict(),
            "thresholds_used": self.thresholds_used.to_dict(),
        }


@dataclass(frozen=True)
class QualityProvenance:
    """
    Complete provenance chain for quality assessment.
    
    Tracks: source frame → person crop → face crop → quality assessment
    """
    
    # Source frame identification
    source_type: str
    source_id: str
    frame_index: int
    timestamp: Optional[float]
    original_frame_width: int
    original_frame_height: int
    
    # Person crop provenance
    person_crop_id: str
    person_detection_id: str
    person_detection_confidence: float
    person_bbox_original: Tuple[float, float, float, float]
    
    # Face crop provenance
    face_crop_id: str
    face_detection_id: Optional[str] = None
    face_detection_confidence: Optional[float] = None
    face_bbox_original: Tuple[float, float, float, float] = (0, 0, 0, 0)
    face_bbox_person_crop: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    # Model information
    person_model_id: str = "yolo_person"
    face_model_id: str = "scrfd"
    quality_assessor_version: str = "1.0"
    
    # Quality assessment identification
    quality_id: str = field(default_factory=lambda: f"qual_{uuid.uuid4().hex[:8]}")
    
    # Pose information from Phase 15
    pose_state: Optional[str] = None  # NORMAL, HARD_POSE, INVALID
    pose_yaw: Optional[float] = None
    pose_pitch: Optional[float] = None
    pose_roll: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "original_frame_width": self.original_frame_width,
            "original_frame_height": self.original_frame_height,
            "person_crop_id": self.person_crop_id,
            "person_detection_id": self.person_detection_id,
            "person_detection_confidence": self.person_detection_confidence,
            "person_bbox_original": list(self.person_bbox_original),
            "face_crop_id": self.face_crop_id,
            "face_detection_id": self.face_detection_id,
            "face_detection_confidence": self.face_detection_confidence,
            "face_bbox_original": list(self.face_bbox_original),
            "face_bbox_person_crop": list(self.face_bbox_person_crop),
            "person_model_id": self.person_model_id,
            "face_model_id": self.face_model_id,
            "quality_assessor_version": self.quality_assessor_version,
            "quality_id": self.quality_id,
            "pose_state": self.pose_state,
            "pose_yaw": self.pose_yaw,
            "pose_pitch": self.pose_pitch,
            "pose_roll": self.pose_roll,
        }


# =============================================================================
# QUALITY ASSESSOR
# =============================================================================

class FaceQualityAssessor:
    """
    Deterministic face quality assessor for adaptive pipeline.
    
    Evaluates measurable quality signals:
    - Face geometry (width, height, area, inter-eye distance)
    - Detection confidence (from SCRFD contract)
    - Sharpness (Laplacian variance)
    - Brightness/exposure (mean intensity)
    - Boundary contact (from ORIGINAL_FRAME coordinates)
    - Occlusion (explicit NOT_AVAILABLE if no model)
    - Pose (consumed from Phase 15 PoseState)
    
    Maps metrics → GOOD / MARGINAL / UNUSABLE with explainable reasons.
    """
    
    def __init__(
        self,
        thresholds: QualityThresholds = DEFAULT_QUALITY_THRESHOLDS,
    ):
        """
        Initialize the quality assessor.
        
        Args:
            thresholds: Configurable quality thresholds.
        """
        self.thresholds = thresholds
    
    def assess(
        self,
        face_crop: AdaptiveCropResult,
        detection_confidence: float,
        pose_state: Optional[PoseState] = None,
        pose_angles: Optional[Tuple[float, float, float]] = None,  # (yaw, pitch, roll)
        landmarks_5pt: Optional[List[Tuple[float, float]]] = None,  # In face crop coordinates
        occlusion_ratio: Optional[float] = None,  # If occlusion model available
    ) -> FaceQualityResult:
        """
        Assess face quality from crop, detection confidence, and metadata.
        
        Args:
            face_crop: Face crop from adaptive pipeline (has provenance to ORIGINAL_FRAME).
            detection_confidence: Face detection confidence from SCRFD.
            pose_state: Pose classification from Phase 15 (NORMAL/HARD_POSE/INVALID).
            pose_angles: Optional (yaw, pitch, roll) in degrees from Phase 15.
            landmarks_5pt: Optional 5-point landmarks in face crop coordinates.
            occlusion_ratio: Optional occlusion ratio [0,1] if model available.
            
        Returns:
            FaceQualityResult with all metrics, classification, and provenance.
        """
        metrics = []
        reasons = []
        
        # 1. Face geometry metrics
        geometry_metrics = self._assess_face_geometry(face_crop, landmarks_5pt)
        metrics.extend(geometry_metrics)
        
        # 2. Detection confidence
        confidence_metric = self._assess_detection_confidence(detection_confidence)
        metrics.append(confidence_metric)
        
        # 3. Sharpness
        sharpness_metric = self._assess_sharpness(face_crop)
        metrics.append(sharpness_metric)
        
        # 4. Brightness/exposure
        brightness_metric = self._assess_brightness(face_crop)
        metrics.append(brightness_metric)
        
        # 5. Boundary contact (from ORIGINAL_FRAME provenance)
        boundary_metric = self._assess_boundary_contact(face_crop)
        metrics.append(boundary_metric)
        
        # 6. Occlusion
        occlusion_metric = self._assess_occlusion(occlusion_ratio)
        metrics.append(occlusion_metric)
        
        # 7. Pose (consume from Phase 15)
        pose_metric = self._assess_pose(pose_state, pose_angles)
        metrics.append(pose_metric)
        
        # Classify quality
        quality_class, class_reasons = self._classify_quality(metrics, pose_state)
        reasons.extend(class_reasons)
        
        # Evidence eligibility
        evidence_eligible = self._determine_evidence_eligibility(quality_class)
        
        # Build provenance
        provenance = self._build_provenance(
            face_crop=face_crop,
            detection_confidence=detection_confidence,
            pose_state=pose_state,
            pose_angles=pose_angles,
        )
        
        return FaceQualityResult(
            quality_class=quality_class,
            metrics=metrics,
            reasons=reasons,
            evidence_eligible=evidence_eligible,
            provenance=provenance,
            thresholds_used=self.thresholds,
        )
    
    def _assess_face_geometry(
        self,
        face_crop: AdaptiveCropResult,
        landmarks_5pt: Optional[List[Tuple[float, float]]] = None,
    ) -> List[QualityMetric]:
        """Assess face geometry metrics."""
        metrics = []
        
        # Face width
        width = face_crop.crop_width
        passed = width >= self.thresholds.min_face_width
        metrics.append(QualityMetric(
            name="face_width",
            measurement=float(width),
            threshold=float(self.thresholds.min_face_width),
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"Face crop width {width}px",
            unit="pixels",
        ))
        
        # Face height
        height = face_crop.crop_height
        passed = height >= self.thresholds.min_face_height
        metrics.append(QualityMetric(
            name="face_height",
            measurement=float(height),
            threshold=float(self.thresholds.min_face_height),
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"Face crop height {height}px",
            unit="pixels",
        ))
        
        # Face area
        area = face_crop.area
        passed = area >= self.thresholds.min_face_area
        metrics.append(QualityMetric(
            name="face_area",
            measurement=float(area),
            threshold=float(self.thresholds.min_face_area),
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"Face crop area {area}px²",
            unit="pixels²",
        ))
        
        # Inter-eye distance (if landmarks available)
        if landmarks_5pt is not None and len(landmarks_5pt) >= 2:
            # Landmarks 0 and 1 are typically left and right eye centers
            left_eye = np.array(landmarks_5pt[0])
            right_eye = np.array(landmarks_5pt[1])
            inter_eye_dist = float(np.linalg.norm(right_eye - left_eye))
            passed = inter_eye_dist >= self.thresholds.min_inter_eye_distance
            metrics.append(QualityMetric(
                name="inter_eye_distance",
                measurement=inter_eye_dist,
                threshold=self.thresholds.min_inter_eye_distance,
                status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
                reason=f"Inter-eye distance {inter_eye_dist:.1f}px",
                unit="pixels",
            ))
        else:
            metrics.append(QualityMetric(
                name="inter_eye_distance",
                measurement=0.0,
                threshold=self.thresholds.min_inter_eye_distance,
                status=MetricStatus.NOT_AVAILABLE,
                reason="5-point landmarks not available",
                unit="pixels",
            ))
        
        return metrics
    
    def _assess_detection_confidence(self, confidence: float) -> QualityMetric:
        """Assess face detection confidence."""
        passed = confidence >= self.thresholds.min_detection_confidence
        return QualityMetric(
            name="detection_confidence",
            measurement=confidence,
            threshold=self.thresholds.min_detection_confidence,
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"SCRFD confidence {confidence:.3f}",
            unit="",
        )
    
    def _assess_sharpness(self, face_crop: AdaptiveCropResult) -> QualityMetric:
        """
        Assess image sharpness using Laplacian variance.
        
        Higher variance = sharper image.
        Standard no-reference blur metric.
        """
        # Convert to grayscale
        if face_crop.data.ndim == 3:
            # Assume RGB format from adaptive crop
            gray = np.mean(face_crop.data, axis=2).astype(np.uint8)
        else:
            gray = face_crop.data.astype(np.uint8)
        
        # Compute Laplacian variance
        import cv2
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(laplacian.var())
        
        passed = variance >= self.thresholds.min_sharpness
        
        return QualityMetric(
            name="sharpness",
            measurement=variance,
            threshold=self.thresholds.min_sharpness,
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"Laplacian variance {variance:.1f}",
            unit="variance",
        )
    
    def _assess_brightness(self, face_crop: AdaptiveCropResult) -> QualityMetric:
        """
        Assess image brightness/exposure using mean intensity.
        
        Values in [0, 255] range for uint8 images.
        """
        # Convert to grayscale
        if face_crop.data.ndim == 3:
            gray = np.mean(face_crop.data, axis=2)
        else:
            gray = face_crop.data
        
        mean_brightness = float(np.mean(gray))
        min_bright, max_bright = self.thresholds.brightness_min, self.thresholds.brightness_max
        passed = min_bright <= mean_brightness <= max_bright
        
        return QualityMetric(
            name="brightness",
            measurement=mean_brightness,
            threshold=max_bright,
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=f"Mean brightness {mean_brightness:.1f} (range {min_bright}-{max_bright})",
            unit="intensity (0-255)",
        )
    
    def _assess_boundary_contact(self, face_crop: AdaptiveCropResult) -> QualityMetric:
        """
        Assess boundary contact from ORIGINAL_FRAME coordinates.
        
        Checks if face bbox touches or is near frame edges.
        """
        # Get face bbox in original frame from provenance
        fx1, fy1, fx2, fy2 = face_crop.provenance.face_bbox_original
        frame_w = face_crop.provenance.original_frame_width
        frame_h = face_crop.provenance.original_frame_height
        
        face_width = fx2 - fx1
        face_height = fy2 - fy1
        
        # Check distance to each boundary
        dist_left = fx1
        dist_right = frame_w - fx2
        dist_top = fy1
        dist_bottom = frame_h - fy2
        
        # Boundary contact if any distance is very small (within 1 pixel)
        contact_threshold = 1.0
        contacts = []
        if dist_left <= contact_threshold:
            contacts.append("left")
        if dist_right <= contact_threshold:
            contacts.append("right")
        if dist_top <= contact_threshold:
            contacts.append("top")
        if dist_bottom <= contact_threshold:
            contacts.append("bottom")
        
        # Compute contact ratio (fraction of perimeter touching boundary)
        perimeter = 2 * (face_width + face_height)
        contact_length = 0.0
        if dist_left <= contact_threshold:
            contact_length += face_height
        if dist_right <= contact_threshold:
            contact_length += face_height
        if dist_top <= contact_threshold:
            contact_length += face_width
        if dist_bottom <= contact_threshold:
            contact_length += face_width
        
        contact_ratio = contact_length / perimeter if perimeter > 0 else 0.0
        passed = contact_ratio <= self.thresholds.max_boundary_contact_ratio
        
        reason = f"Boundary contact ratio {contact_ratio:.3f}"
        if contacts:
            reason += f" (touching: {', '.join(contacts)})"
        
        return QualityMetric(
            name="boundary_contact",
            measurement=contact_ratio,
            threshold=self.thresholds.max_boundary_contact_ratio,
            status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
            reason=reason,
            unit="ratio",
        )
    
    def _assess_occlusion(self, occlusion_ratio: Optional[float]) -> QualityMetric:
        """Assess occlusion if model available, otherwise NOT_AVAILABLE."""
        if occlusion_ratio is not None:
            passed = occlusion_ratio <= self.thresholds.max_occlusion_ratio
            return QualityMetric(
                name="occlusion",
                measurement=occlusion_ratio,
                threshold=self.thresholds.max_occlusion_ratio,
                status=MetricStatus.PASSED if passed else MetricStatus.FAILED,
                reason=f"Occlusion ratio {occlusion_ratio:.3f}",
                unit="ratio",
            )
        else:
            return QualityMetric(
                name="occlusion",
                measurement=0.0,
                threshold=self.thresholds.max_occlusion_ratio,
                status=MetricStatus.NOT_AVAILABLE,
                reason="Occlusion model not available",
                unit="ratio",
            )
    
    def _assess_pose(
        self,
        pose_state: Optional[PoseState],
        pose_angles: Optional[Tuple[float, float, float]],
    ) -> QualityMetric:
        """Assess pose by consuming Phase 15 result."""
        if pose_state is None:
            return QualityMetric(
                name="pose",
                measurement=0.0,
                threshold=0.0,
                status=MetricStatus.NOT_AVAILABLE,
                reason="Pose state not provided from Phase 15",
                unit="degrees",
            )
        
        if pose_state == PoseState.INVALID:
            return QualityMetric(
                name="pose",
                measurement=999.0,
                threshold=0.0,
                status=MetricStatus.FAILED,
                reason=f"Pose INVALID (yaw={pose_angles[0] if pose_angles else 'N/A'}, "
                       f"pitch={pose_angles[1] if pose_angles else 'N/A'}, "
                       f"roll={pose_angles[2] if pose_angles else 'N/A'})",
                unit="degrees",
            )
        elif pose_state == PoseState.HARD_POSE:
            return QualityMetric(
                name="pose",
                measurement=1.0,  # Indicator for HARD_POSE
                threshold=0.5,
                status=MetricStatus.FAILED,  # HARD_POSE counts as failed for GOOD classification
                reason=f"Pose HARD_POSE (yaw={pose_angles[0] if pose_angles else 'N/A'}, "
                       f"pitch={pose_angles[1] if pose_angles else 'N/A'}, "
                       f"roll={pose_angles[2] if pose_angles else 'N/A'})",
                unit="degrees",
            )
        else:  # NORMAL
            return QualityMetric(
                name="pose",
                measurement=0.0,
                threshold=0.5,
                status=MetricStatus.PASSED,
                reason=f"Pose NORMAL (yaw={pose_angles[0] if pose_angles else 'N/A'}, "
                       f"pitch={pose_angles[1] if pose_angles else 'N/A'}, "
                       f"roll={pose_angles[2] if pose_angles else 'N/A'})",
                unit="degrees",
            )
    
    def _classify_quality(
        self,
        metrics: List[QualityMetric],
        pose_state: Optional[PoseState],
    ) -> Tuple[QualityClass, List[str]]:
        """
        Classify quality based on all metrics.
        
        Rules:
        - GOOD: All available metrics PASSED, pose NORMAL
        - MARGINAL: Some metrics FAILED but not critical, or pose HARD_POSE
        - UNUSABLE: Critical metrics FAILED (pose INVALID, zero-size, etc.)
        """
        reasons = []
        
        # Check for critical failures (UNUSABLE)
        critical_failures = []
        
        # Pose INVALID is critical
        pose_metric = next((m for m in metrics if m.name == "pose"), None)
        if pose_metric and pose_metric.status == MetricStatus.FAILED:
            if pose_state == PoseState.INVALID:
                critical_failures.append("pose_invalid")
        
        # Zero or negative geometry is critical
        for metric in metrics:
            if metric.name in ("face_width", "face_height", "face_area"):
                if metric.measurement <= 0:
                    critical_failures.append(f"{metric.name}_zero_or_negative")
        
        if critical_failures:
            return QualityClass.UNUSABLE, [f"critical_failure: {cf}" for cf in critical_failures]
        
        # Count failed metrics (excluding NOT_AVAILABLE)
        available_metrics = [m for m in metrics if m.status != MetricStatus.NOT_AVAILABLE]
        failed_metrics = [m for m in available_metrics if m.status == MetricStatus.FAILED]
        failed_count = len(failed_metrics)
        
        # Check for HARD_POSE
        is_hard_pose = pose_state == PoseState.HARD_POSE
        
        if failed_count == 0 and not is_hard_pose:
            # All available metrics passed, pose is NORMAL
            return QualityClass.GOOD, ["all_metrics_passed"]
        elif is_hard_pose and failed_count <= 2:
            # HARD_POSE with few other failures -> MARGINAL
            reasons.append("hard_pose")
            for m in failed_metrics:
                if m.name != "pose":
                    reasons.append(f"{m.name}_failed")
            return QualityClass.MARGINAL, reasons
        elif failed_count <= 2:
            # Few non-critical failures -> MARGINAL
            for m in failed_metrics:
                reasons.append(f"{m.name}_failed")
            return QualityClass.MARGINAL, reasons
        else:
            # Many failures -> UNUSABLE
            for m in failed_metrics:
                reasons.append(f"{m.name}_failed")
            return QualityClass.UNUSABLE, reasons
    
    def _determine_evidence_eligibility(self, quality_class: QualityClass) -> bool:
        """
        Determine if face is eligible for identity evidence.
        
        Policy:
        - GOOD -> eligible
        - MARGINAL -> configurable (default: not eligible for single-frame, eligible for temporal)
        - UNUSABLE -> not eligible
        """
        if quality_class == QualityClass.GOOD:
            return True
        elif quality_class == QualityClass.MARGINAL:
            # MARGINAL faces are not eligible for single-frame evidence
            # but can contribute to temporal aggregation in Phase 18
            return False
        else:  # UNUSABLE
            return False
    
    def _build_provenance(
        self,
        face_crop: AdaptiveCropResult,
        detection_confidence: float,
        pose_state: Optional[PoseState],
        pose_angles: Optional[Tuple[float, float, float]],
    ) -> QualityProvenance:
        """Build complete provenance chain for quality assessment."""
        prov = face_crop.provenance
        
        return QualityProvenance(
            source_type=prov.source_type,
            source_id=prov.source_id,
            frame_index=prov.frame_index,
            timestamp=prov.timestamp,
            original_frame_width=prov.original_frame_width,
            original_frame_height=prov.original_frame_height,
            person_crop_id=prov.crop_id,
            person_detection_id=prov.person_detection_id,
            person_detection_confidence=prov.person_detection_confidence,
            person_bbox_original=prov.person_bbox_original,
            face_crop_id=face_crop.provenance.crop_id,
            face_detection_id=prov.face_detection_id,
            face_detection_confidence=detection_confidence,
            face_bbox_original=prov.face_bbox_original if hasattr(prov, 'face_bbox_original') else (0, 0, 0, 0),
            face_bbox_person_crop=prov.face_bbox_person_crop if hasattr(prov, 'face_bbox_person_crop') else (0, 0, 0, 0),
            person_model_id=prov.person_model_id,
            face_model_id=prov.face_model_id,
            pose_state=pose_state.value if pose_state else None,
            pose_yaw=pose_angles[0] if pose_angles else None,
            pose_pitch=pose_angles[1] if pose_angles else None,
            pose_roll=pose_angles[2] if pose_angles else None,
        )


def create_quality_assessor(
    thresholds: Optional[QualityThresholds] = None,
) -> FaceQualityAssessor:
    """
    Factory function to create a FaceQualityAssessor.
    
    Args:
        thresholds: Optional custom thresholds (uses defaults if None).
        
    Returns:
        FaceQualityAssessor instance.
    """
    if thresholds is None:
        thresholds = DEFAULT_QUALITY_THRESHOLDS
    return FaceQualityAssessor(thresholds=thresholds)