"""
Phase 7 — Canonical Face Sample Object.

This module defines the canonical face sample result that combines:
- Detection info
- Crop info
- Landmark info
- Quality assessment
- Full provenance chain

This is the output of Phase 7 that Phase 8 will consume for ArcFace embedding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.detection import FaceDetection
from app.vision.crop import FaceCrop
from app.vision.landmarks import LandmarkResult
from app.vision.quality import FaceQuality, QualityDecision


@dataclass
class FaceSample:
    """
    Canonical face sample result.
    
    This object represents a complete face processing result with full provenance.
    It is immutable where practical and contains all information needed for
    downstream identity recognition (Phase 8).
    """
    
    # Unique sample identifier
    sample_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    # Source provenance
    source_type: str = ""  # "image" or "video"
    source_id: str = ""    # File path
    frame_index: int = 0
    timestamp: Optional[float] = None
    
    # Detection provenance
    detection_id: str = ""
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)  # x1, y1, x2, y2 in original frame
    confidence: float = 0.0
    
    # Crop provenance
    crop_id: str = ""
    crop_width: int = 0
    crop_height: int = 0
    crop_data: Optional[np.ndarray] = None  # HWC RGB
    
    # Landmark provenance
    landmarks: Optional[List[Tuple[float, float, float]]] = None  # 68 3D landmarks
    landmark_coordinate_space: str = "model_input_relative"
    landmark_model_id: str = "landmark_1k3d68"
    landmark_model_sha256: str = ""
    
    # Quality assessment
    quality: Optional[FaceQuality] = None
    quality_status: QualityDecision = QualityDecision.INSUFFICIENT_DATA
    
    # Model identities and hashes
    detection_model_id: str = "scrfd"
    detection_model_sha256: str = ""
    landmark_model_id_used: str = "landmark_1k3d68"
    landmark_model_sha256_used: str = ""
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Additional metadata
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate face sample."""
        # Validate bbox
        x1, y1, x2, y2 = self.bbox
        if x1 >= x2 or y1 >= y2:
            raise ValueError(f"Invalid bbox: ({x1}, {y1}, {x2}, {y2})")
        
        # Validate confidence
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid confidence: {self.confidence}")
        
        # Validate landmarks if present
        if self.landmarks is not None:
            if len(self.landmarks) != 68:
                raise ValueError(f"Expected 68 landmarks, got {len(self.landmarks)}")
            for i, (x, y, z) in enumerate(self.landmarks):
                if not (np.isfinite(x) and np.isfinite(y) and np.isfinite(z)):
                    raise ValueError(f"Landmark {i} has non-finite coordinates")
    
    @property
    def has_landmarks(self) -> bool:
        """Check if landmarks are available."""
        return self.landmarks is not None and len(self.landmarks) == 68
    
    @property
    def has_crop_data(self) -> bool:
        """Check if crop data is available."""
        return self.crop_data is not None and self.crop_data.size > 0
    
    @property
    def crop_area(self) -> int:
        """Get crop area in pixels."""
        return self.crop_width * self.crop_height
    
    @property
    def crop_aspect_ratio(self) -> float:
        """Get crop aspect ratio."""
        return self.crop_width / self.crop_height if self.crop_height > 0 else 0.0
    
    @property
    def is_acceptable(self) -> bool:
        """Check if sample passed quality assessment."""
        return self.quality_status == QualityDecision.ACCEPTABLE
    
    def to_dict(self, include_crop_data: bool = False) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "sample_id": self.sample_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "detection_id": self.detection_id,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "crop_id": self.crop_id,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "crop_area": self.crop_area,
            "crop_aspect_ratio": self.crop_aspect_ratio,
            "landmark_coordinate_space": self.landmark_coordinate_space,
            "landmark_model_id": self.landmark_model_id,
            "landmark_model_sha256": self.landmark_model_sha256,
            "quality_status": self.quality_status.value,
            "detection_model_id": self.detection_model_id,
            "detection_model_sha256": self.detection_model_sha256,
            "landmark_model_id_used": self.landmark_model_id_used,
            "landmark_model_sha256_used": self.landmark_model_sha256_used,
            "created_at": self.created_at,
            "has_landmarks": self.has_landmarks,
            "has_crop_data": self.has_crop_data,
            "extra": self.extra,
        }
        
        if self.quality:
            result["quality"] = self.quality.to_dict()
        
        if self.landmarks:
            result["landmarks"] = self.landmarks
        
        if include_crop_data and self.crop_data is not None:
            result["crop_data_shape"] = list(self.crop_data.shape)
            result["crop_data_dtype"] = str(self.crop_data.dtype)
        
        return result
    
    def get_provenance_chain(self) -> List[Dict[str, Any]]:
        """Get the full provenance chain as a list of steps."""
        return [
            {
                "step": "source",
                "type": self.source_type,
                "id": self.source_id,
                "frame_index": self.frame_index,
                "timestamp": self.timestamp,
            },
            {
                "step": "detection",
                "model_id": self.detection_model_id,
                "model_sha256": self.detection_model_sha256,
                "detection_id": self.detection_id,
                "bbox": list(self.bbox),
                "confidence": self.confidence,
            },
            {
                "step": "crop",
                "crop_id": self.crop_id,
                "width": self.crop_width,
                "height": self.crop_height,
                "bbox": list(self.bbox),
            },
            {
                "step": "landmarks",
                "model_id": self.landmark_model_id_used,
                "model_sha256": self.landmark_model_sha256_used,
                "coordinate_space": self.landmark_coordinate_space,
                "num_landmarks": len(self.landmarks) if self.landmarks else 0,
            },
            {
                "step": "quality",
                "status": self.quality_status.value,
                "metrics": self.quality.metrics if self.quality else [],
            },
        ]


@dataclass
class FaceSampleCollection:
    """
    Collection of face samples from a single frame or video.
    
    This is the output of the face pipeline for a frame/video.
    Multiple faces are preserved - no silent selection of "best" face.
    """
    
    # Source info
    source_type: str = ""
    source_id: str = ""
    frame_index: int = 0
    timestamp: Optional[float] = None
    
    # Samples
    samples: List[FaceSample] = field(default_factory=list)
    
    # Processing metadata
    processing_time_ms: float = 0.0
    detector_model_id: str = "scrfd"
    landmark_model_id: str = "landmark_1k3d68"
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __iter__(self):
        return iter(self.samples)
    
    def __getitem__(self, index: int) -> FaceSample:
        return self.samples[index]
    
    def add_sample(self, sample: FaceSample) -> None:
        """Add a face sample to the collection."""
        self.samples.append(sample)
    
    def get_acceptable_samples(self) -> List[FaceSample]:
        """Get only samples that passed quality assessment."""
        return [s for s in self.samples if s.is_acceptable]
    
    def get_rejected_samples(self) -> List[FaceSample]:
        """Get only samples that failed quality assessment."""
        return [s for s in self.samples if s.quality_status == QualityDecision.REJECTED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "num_faces": len(self.samples),
            "num_acceptable": len(self.get_acceptable_samples()),
            "num_rejected": len(self.get_rejected_samples()),
            "processing_time_ms": self.processing_time_ms,
            "detector_model_id": self.detector_model_id,
            "landmark_model_id": self.landmark_model_id,
            "samples": [s.to_dict() for s in self.samples],
        }


def create_face_sample_from_pipeline(
    frame: "CanonicalFrame",
    detection: FaceDetection,
    crop: FaceCrop,
    landmarks: Optional[LandmarkResult] = None,
    quality: Optional[FaceQuality] = None,
) -> FaceSample:
    """
    Create a FaceSample from pipeline components.
    
    This is the main factory function for creating FaceSample objects
    after running the full face processing pipeline.
    """
    # Determine quality status
    quality_status = quality.decision if quality else QualityDecision.INSUFFICIENT_DATA
    
    # Extract landmarks list
    landmarks_list = landmarks.landmarks if landmarks else None
    landmark_space = landmarks.coordinate_space.value if landmarks else "model_input_relative"
    landmark_model_id = landmarks.model_id if landmarks else "landmark_1k3d68"
    landmark_model_sha256 = landmarks.model_sha256 if landmarks else ""
    
    return FaceSample(
        source_type=frame.metadata.source_type.value,
        source_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        detection_id=detection.detection_id,
        bbox=detection.bbox,
        confidence=detection.confidence,
        crop_id=crop.crop_id,
        crop_width=crop.crop_width,
        crop_height=crop.crop_height,
        crop_data=crop.data,
        landmarks=landmarks_list,
        landmark_coordinate_space=landmark_space,
        landmark_model_id=landmark_model_id,
        landmark_model_sha256=landmark_model_sha256,
        quality=quality,
        quality_status=quality_status,
        detection_model_id=detection.model_id,
        detection_model_sha256=detection.model_sha256,
        landmark_model_id_used=landmark_model_id,
        landmark_model_sha256_used=landmark_model_sha256,
    )


def create_face_sample_collection(
    frame: "CanonicalFrame",
    detections: List[FaceDetection],
    crops: List[FaceCrop],
    landmarks_list: List[Optional[LandmarkResult]],
    qualities: List[Optional[FaceQuality]],
    processing_time_ms: float = 0.0,
) -> FaceSampleCollection:
    """
    Create a FaceSampleCollection from pipeline results for multiple faces.
    
    Args:
        frame: Source frame.
        detections: List of face detections.
        crops: List of face crops (same order as detections).
        landmarks_list: List of landmark results (same order, None if failed).
        qualities: List of quality assessments (same order, None if failed).
        processing_time_ms: Total processing time.
        
    Returns:
        FaceSampleCollection with all face samples.
    """
    collection = FaceSampleCollection(
        source_type=frame.metadata.source_type.value,
        source_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        processing_time_ms=processing_time_ms,
    )
    
    for i, detection in enumerate(detections):
        crop = crops[i] if i < len(crops) else None
        landmarks = landmarks_list[i] if i < len(landmarks_list) else None
        quality = qualities[i] if i < len(qualities) else None
        
        if crop is None:
            # Skip if crop failed
            continue
        
        sample = create_face_sample_from_pipeline(
            frame=frame,
            detection=detection,
            crop=crop,
            landmarks=landmarks,
            quality=quality,
        )
        
        collection.add_sample(sample)
    
    return collection