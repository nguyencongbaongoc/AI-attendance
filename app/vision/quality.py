"""
Phase 7 — Face Quality Assessment.

This module provides deterministic face quality assessment based on measurable
signals from the face crop and landmarks. No trained quality model is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.crop import FaceCrop
from app.vision.landmarks import LandmarkResult, LandmarkCoordinateSpace


class QualityDecision(str, Enum):
    """Final quality decision."""
    
    ACCEPTABLE = "acceptable"
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class QualityMetric:
    """Individual quality metric result."""
    
    name: str
    measurement: float
    threshold: float
    passed: bool
    reason: str
    unit: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "measurement": self.measurement,
            "threshold": self.threshold,
            "passed": self.passed,
            "reason": self.reason,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class FaceQuality:
    """
    Complete face quality assessment result.
    
    Every quality component has:
    - metric name
    - measurement value
    - threshold
    - pass/fail
    - reason
    
    Final decision is derived from all metrics.
    """
    
    # Individual metrics
    metrics: List[QualityMetric]
    
    # Final decision
    decision: QualityDecision
    
    # Summary
    passed_count: int
    failed_count: int
    total_count: int
    
    # Reference info
    crop_id: str = ""
    frame_index: int = 0
    source_id: str = ""
    
    def __post_init__(self):
        """Validate quality result."""
        if self.passed_count + self.failed_count != self.total_count:
            raise ValueError("Passed + failed must equal total")
    
    @property
    def pass_rate(self) -> float:
        """Get pass rate."""
        return self.passed_count / self.total_count if self.total_count > 0 else 0.0
    
    def get_metric(self, name: str) -> Optional[QualityMetric]:
        """Get a specific metric by name."""
        for m in self.metrics:
            if m.name == name:
                return m
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision": self.decision.value,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
            "pass_rate": self.pass_rate,
            "crop_id": self.crop_id,
            "frame_index": self.frame_index,
            "source_id": self.source_id,
            "metrics": [m.to_dict() for m in self.metrics],
        }


class QualityAssessor:
    """
    Deterministic face quality assessor.
    
    Evaluates measurable quality signals:
    - Face size (crop dimensions)
    - Detection confidence
    - Landmark validity
    - Blur/sharpness (Laplacian variance)
    - Brightness/exposure (mean intensity)
    - Optional pose/orientation (from landmarks)
    
    Does NOT use a trained quality model.
    All thresholds are configurable engineering heuristics.
    """
    
    def __init__(
        self,
        min_face_size: int = 64,
        min_detection_confidence: float = 0.55,
        min_sharpness: float = 100.0,
        brightness_range: Tuple[float, float] = (30.0, 220.0),
        min_landmark_validity: float = 0.8,
        max_pose_angle: float = 45.0,
    ):
        """
        Initialize the quality assessor.
        
        Args:
            min_face_size: Minimum face crop dimension (pixels).
            min_detection_confidence: Minimum detection confidence.
            min_sharpness: Minimum Laplacian variance for sharpness.
            brightness_range: Acceptable mean brightness range (0-255).
            min_landmark_validity: Minimum fraction of valid landmarks.
            max_pose_angle: Maximum estimated pose angle (degrees).
        """
        self.min_face_size = min_face_size
        self.min_detection_confidence = min_detection_confidence
        self.min_sharpness = min_sharpness
        self.brightness_range = brightness_range
        self.min_landmark_validity = min_landmark_validity
        self.max_pose_angle = max_pose_angle
    
    def assess(
        self,
        crop: FaceCrop,
        detection_confidence: float,
        landmarks: Optional[LandmarkResult] = None,
    ) -> FaceQuality:
        """
        Assess face quality from crop, detection confidence, and landmarks.
        
        Args:
            crop: Face crop to assess.
            detection_confidence: Detection confidence from SCRFD.
            landmarks: Optional landmark result for additional metrics.
            
        Returns:
            FaceQuality with all metrics and final decision.
        """
        metrics = []
        
        # 1. Face size metric
        face_size_metric = self._assess_face_size(crop)
        metrics.append(face_size_metric)
        
        # 2. Detection confidence metric
        confidence_metric = self._assess_detection_confidence(detection_confidence)
        metrics.append(confidence_metric)
        
        # 3. Sharpness/blur metric
        sharpness_metric = self._assess_sharpness(crop)
        metrics.append(sharpness_metric)
        
        # 4. Brightness/exposure metric
        brightness_metric = self._assess_brightness(crop)
        metrics.append(brightness_metric)
        
        # 5. Landmark validity metric (if landmarks provided)
        if landmarks is not None:
            landmark_metric = self._assess_landmark_validity(landmarks)
            metrics.append(landmark_metric)
            
            # 6. Pose/orientation metric (if landmarks provided)
            pose_metric = self._assess_pose(landmarks, crop)
            metrics.append(pose_metric)
        
        # Determine final decision
        passed = sum(1 for m in metrics if m.passed)
        failed = sum(1 for m in metrics if not m.passed)
        total = len(metrics)
        
        # Decision logic
        if total == 0:
            decision = QualityDecision.INSUFFICIENT_DATA
        elif failed == 0:
            decision = QualityDecision.ACCEPTABLE
        else:
            decision = QualityDecision.REJECTED
        
        return FaceQuality(
            metrics=metrics,
            decision=decision,
            passed_count=passed,
            failed_count=failed,
            total_count=total,
            crop_id=crop.crop_id,
            frame_index=crop.frame_index,
            source_id=crop.source_id,
        )
    
    def _assess_face_size(self, crop: FaceCrop) -> QualityMetric:
        """Assess face crop size."""
        min_dim = min(crop.crop_width, crop.crop_height)
        passed = min_dim >= self.min_face_size
        
        return QualityMetric(
            name="face_size",
            measurement=float(min_dim),
            threshold=float(self.min_face_size),
            passed=passed,
            reason=f"Face crop {crop.crop_width}x{crop.crop_height}, min dimension {min_dim}px",
            unit="pixels",
        )
    
    def _assess_detection_confidence(self, confidence: float) -> QualityMetric:
        """Assess detection confidence."""
        passed = confidence >= self.min_detection_confidence
        
        return QualityMetric(
            name="detection_confidence",
            measurement=confidence,
            threshold=self.min_detection_confidence,
            passed=passed,
            reason=f"SCRFD confidence {confidence:.3f}",
            unit="",
        )
    
    def _assess_sharpness(self, crop: FaceCrop) -> QualityMetric:
        """
        Assess image sharpness using Laplacian variance.
        
        Higher variance = sharper image.
        This is a standard no-reference blur metric.
        """
        # Convert to grayscale if needed
        if crop.data.ndim == 3:
            if crop.pixel_format.value in ("rgb", "bgr"):
                # Simple luminance conversion
                gray = np.mean(crop.data, axis=2).astype(np.uint8)
            else:
                gray = crop.data[:, :, 0].astype(np.uint8)
        else:
            gray = crop.data.astype(np.uint8)
        
        # Compute Laplacian variance
        import cv2
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(laplacian.var())
        
        passed = variance >= self.min_sharpness
        
        return QualityMetric(
            name="sharpness",
            measurement=variance,
            threshold=self.min_sharpness,
            passed=passed,
            reason=f"Laplacian variance {variance:.1f}",
            unit="variance",
        )
    
    def _assess_brightness(self, crop: FaceCrop) -> QualityMetric:
        """
        Assess image brightness/exposure using mean intensity.
        
        Values in [0, 255] range for uint8 images.
        """
        # Convert to grayscale if needed
        if crop.data.ndim == 3:
            if crop.pixel_format.value in ("rgb", "bgr"):
                gray = np.mean(crop.data, axis=2)
            else:
                gray = crop.data[:, :, 0]
        else:
            gray = crop.data
        
        mean_brightness = float(np.mean(gray))
        min_bright, max_bright = self.brightness_range
        passed = min_bright <= mean_brightness <= max_bright
        
        return QualityMetric(
            name="brightness",
            measurement=mean_brightness,
            threshold=max_bright,  # Report upper threshold
            passed=passed,
            reason=f"Mean brightness {mean_brightness:.1f} (range {min_bright}-{max_bright})",
            unit="intensity (0-255)",
        )
    
    def _assess_landmark_validity(self, landmarks: LandmarkResult) -> QualityMetric:
        """
        Assess landmark validity.
        
        Checks that all 68 landmarks are finite and within reasonable bounds.
        """
        valid_count = 0
        total_count = len(landmarks.landmarks)
        
        for x, y, z in landmarks.landmarks:
            if np.isfinite(x) and np.isfinite(y) and np.isfinite(z):
                # Check reasonable bounds based on coordinate space
                if landmarks.coordinate_space == LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE:
                    if 0 <= x <= 192 and 0 <= y <= 192:
                        valid_count += 1
                elif landmarks.coordinate_space == LandmarkCoordinateSpace.CROP_RELATIVE:
                    # Normalized 0-1
                    if 0 <= x <= 1 and 0 <= y <= 1:
                        valid_count += 1
                else:
                    valid_count += 1
        
        validity_ratio = valid_count / total_count if total_count > 0 else 0.0
        passed = validity_ratio >= self.min_landmark_validity
        
        return QualityMetric(
            name="landmark_validity",
            measurement=validity_ratio,
            threshold=self.min_landmark_validity,
            passed=passed,
            reason=f"{valid_count}/{total_count} landmarks valid",
            unit="ratio",
        )
    
    def _assess_pose(self, landmarks: LandmarkResult, crop: FaceCrop) -> QualityMetric:
        """
        Assess face pose/orientation from landmarks.
        
        Estimates yaw/pitch/roll from 3D landmarks.
        This is a heuristic, not a trained pose estimator.
        """
        # Use 2D landmarks for pose estimation
        lm_2d = landmarks.landmarks_xy
        
        if len(lm_2d) < 68:
            return QualityMetric(
                name="pose",
                measurement=0.0,
                threshold=self.max_pose_angle,
                passed=False,
                reason="Insufficient landmarks for pose estimation",
                unit="degrees",
            )
        
        # Key landmark indices for 1K3D68 (standard 68-point model)
        # Nose tip: 30, Chin: 8, Left eye: 36, Right eye: 45
        # Left mouth: 48, Right mouth: 54
        
        try:
            nose_tip = np.array(lm_2d[30])
            chin = np.array(lm_2d[8])
            left_eye = np.array(lm_2d[36])
            right_eye = np.array(lm_2d[45])
            left_mouth = np.array(lm_2d[48])
            right_mouth = np.array(lm_2d[54])
            
            # Estimate yaw from eye-mouth alignment
            eye_center = (left_eye + right_eye) / 2
            mouth_center = (left_mouth + right_mouth) / 2
            
            # Vector from eye center to mouth center
            vertical_vec = mouth_center - eye_center
            # Vector from eye center to nose tip
            nose_vec = nose_tip - eye_center
            
            # Estimate yaw from horizontal offset of nose
            eye_width = np.linalg.norm(right_eye - left_eye)
            if eye_width > 0:
                nose_offset_x = nose_vec[0]
                yaw_estimate = np.degrees(np.arcsin(np.clip(nose_offset_x / eye_width, -1, 1)))
            else:
                yaw_estimate = 0.0
            
            # Estimate pitch from vertical alignment
            vertical_len = np.linalg.norm(vertical_vec)
            if vertical_len > 0:
                pitch_estimate = np.degrees(np.arcsin(np.clip(vertical_vec[0] / vertical_len, -1, 1)))
            else:
                pitch_estimate = 0.0
            
            # Estimate roll from eye line angle
            eye_angle = np.degrees(np.arctan2(right_eye[1] - left_eye[1], right_eye[0] - left_eye[0]))
            roll_estimate = eye_angle
            
            # Combined pose magnitude
            pose_magnitude = np.sqrt(yaw_estimate**2 + pitch_estimate**2 + roll_estimate**2)
            
            passed = pose_magnitude <= self.max_pose_angle
            
            return QualityMetric(
                name="pose",
                measurement=pose_magnitude,
                threshold=self.max_pose_angle,
                passed=passed,
                reason=f"Estimated pose: yaw={yaw_estimate:.1f}°, pitch={pitch_estimate:.1f}°, roll={roll_estimate:.1f}°",
                unit="degrees",
            )
            
        except Exception as e:
            return QualityMetric(
                name="pose",
                measurement=0.0,
                threshold=self.max_pose_angle,
                passed=False,
                reason=f"Pose estimation failed: {e}",
                unit="degrees",
            )


def create_quality_assessor(
    min_face_size: int = 64,
    min_detection_confidence: float = 0.55,
    min_sharpness: float = 100.0,
    brightness_range: Tuple[float, float] = (30.0, 220.0),
    min_landmark_validity: float = 0.8,
    max_pose_angle: float = 45.0,
) -> QualityAssessor:
    """
    Factory function to create a QualityAssessor.
    
    Args:
        min_face_size: Minimum face crop dimension.
        min_detection_confidence: Minimum detection confidence.
        min_sharpness: Minimum sharpness threshold.
        brightness_range: Acceptable brightness range.
        min_landmark_validity: Minimum landmark validity ratio.
        max_pose_angle: Maximum pose angle.
        
    Returns:
        QualityAssessor instance.
    """
    return QualityAssessor(
        min_face_size=min_face_size,
        min_detection_confidence=min_detection_confidence,
        min_sharpness=min_sharpness,
        brightness_range=brightness_range,
        min_landmark_validity=min_landmark_validity,
        max_pose_angle=max_pose_angle,
    )