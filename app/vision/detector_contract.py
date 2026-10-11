"""
Phase 8 — Model-Independent Face Detector Contract.

This module defines the stable, model-independent face detector contract
that allows SCRFD, RetinaFace, or future detectors to be swapped without
changing downstream code.

Key types:
- FaceDetectionContract: Model-independent detection result
- FaceDetectorInterface: Abstract base class for all face detectors
- DetectorModelId: Enum of supported detector backends

CRITICAL RULES:
- Downstream code depends on FaceDetectorInterface, NOT SCRFD-specific classes.
- Each detector adapter owns its own preprocessing contract.
- All detector outputs are expressed in a clearly defined coordinate space.
- No detector-specific output (tensor names, decoding logic) leaks downstream.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.data.contracts import ModelPreprocessingContract


class DetectorModelId(str, Enum):
    """Supported detector backend identifiers."""
    
    SCRFD = "scrfd"
    RETINAFACE = "retinaface"
    
    def __str__(self) -> str:
        return self.value


class DetectorStatus(str, Enum):
    """Status of a detector implementation."""
    
    ACTIVE = "active"           # Fully implemented and operational
    NOT_IMPLEMENTED = "not_implemented"  # Placeholder, not yet built
    DISABLED = "disabled"       # Explicitly disabled
    
    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class DetectorProvenance:
    """
    Provenance metadata for a face detection.
    
    Records the complete chain: source frame → detector model → detection.
    """
    
    # Source frame reference
    source_type: str
    source_id: str
    frame_index: int
    timestamp: Optional[float]
    
    # Detector model identity
    detector_model_id: str
    detector_model_version: str
    detector_model_sha256: str
    
    # Detection metadata
    detection_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "detector_model_id": self.detector_model_id,
            "detector_model_version": self.detector_model_version,
            "detector_model_sha256": self.detector_model_sha256,
            "detection_id": self.detection_id,
        }


@dataclass(frozen=True)
class FaceDetectionContract:
    """
    Model-independent face detection result.
    
    This is the canonical output of any FaceDetector implementation.
    Downstream code (crop, landmarks, quality, ArcFace) depends on this
    contract, NOT on SCRFD-specific FaceDetection.
    
    All coordinates are in ORIGINAL_FRAME space.
    """
    
    # Bounding box (x1, y1, x2, y2) in original frame coordinates
    bbox: Tuple[float, float, float, float]
    
    # Detection confidence [0.0, 1.0]
    confidence: float
    
    # 5 facial landmarks [(x, y), ...] in original frame coordinates
    landmarks5: List[Tuple[float, float]]
    
    # Coordinate space (always ORIGINAL_FRAME for detector output)
    coordinate_space: str = "original_frame"
    
    # Source frame reference
    source_frame_id: str = ""
    
    # Detector model identity
    detector_model_id: str = ""
    detector_model_version: str = ""
    detector_model_sha256: str = ""
    
    # Provenance
    provenance: Optional[DetectorProvenance] = None
    
    # Unique detection ID
    detection_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    def __post_init__(self):
        """Validate detection data."""
        x1, y1, x2, y2 = self.bbox
        
        # Validate bbox coordinates are finite
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise ValueError(
                f"Invalid bbox: non-finite coordinates ({x1}, {y1}, {x2}, {y2})"
            )
        
        # Validate confidence range
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid confidence: {self.confidence}")
        
        # Validate landmarks count
        if len(self.landmarks5) != 5:
            raise ValueError(
                f"Expected 5 landmarks, got {len(self.landmarks5)}"
            )
        
        # Validate landmark coordinates are finite
        for i, (lx, ly) in enumerate(self.landmarks5):
            if not (np.isfinite(lx) and np.isfinite(ly)):
                raise ValueError(
                    f"Landmark {i} has non-finite coordinates: ({lx}, {ly})"
                )
        
        # Validate coordinate space
        if self.coordinate_space != "original_frame":
            raise ValueError(
                f"Detector output must be in 'original_frame' space, "
                f"got '{self.coordinate_space}'"
            )
        
        # Validate detector model identity is present
        if not self.detector_model_id:
            raise ValueError("detector_model_id is required")
        
        if not self.detector_model_sha256:
            raise ValueError("detector_model_sha256 is required")
    
    @property
    def width(self) -> float:
        """Get bbox width."""
        return self.bbox[2] - self.bbox[0]
    
    @property
    def height(self) -> float:
        """Get bbox height."""
        return self.bbox[3] - self.bbox[1]
    
    @property
    def area(self) -> float:
        """Get bbox area."""
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        """Get bbox center."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "landmarks5": self.landmarks5,
            "coordinate_space": self.coordinate_space,
            "source_frame_id": self.source_frame_id,
            "detector_model_id": self.detector_model_id,
            "detector_model_version": self.detector_model_version,
            "detector_model_sha256": self.detector_model_sha256,
            "detection_id": self.detection_id,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "width": self.width,
            "height": self.height,
            "area": self.area,
        }


class FaceDetectorInterface(ABC):
    """
    Abstract interface for face detectors.
    
    All face detector implementations (SCRFD, RetinaFace, future) must
    inherit from this class and implement the required methods.
    
    Downstream code depends on this interface, NOT on specific implementations.
    """
    
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Get the detector model identifier."""
        ...
    
    @property
    @abstractmethod
    def model_version(self) -> str:
        """Get the detector model version."""
        ...
    
    @property
    @abstractmethod
    def model_sha256(self) -> str:
        """Get the detector model SHA256 hash."""
        ...
    
    @property
    @abstractmethod
    def status(self) -> DetectorStatus:
        """Get the detector implementation status."""
        ...
    
    @property
    @abstractmethod
    def preprocessing_contract(self) -> ModelPreprocessingContract:
        """Get the model-specific preprocessing contract."""
        ...
    
    @abstractmethod
    def detect(self, frame: CanonicalFrame) -> List[FaceDetectionContract]:
        """
        Detect faces in a canonical frame.
        
        Args:
            frame: CanonicalFrame to process.
            
        Returns:
            List of FaceDetectionContract objects in ORIGINAL_FRAME coordinates.
            
        Raises:
            Exception: If detection fails.
        """
        ...
    
    @abstractmethod
    def cleanup(self) -> None:
        """Release detector resources (ONNX sessions, etc.)."""
        ...
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.cleanup()
        return False


def create_detector_provenance(
    frame: CanonicalFrame,
    detector_model_id: str,
    detector_model_version: str,
    detector_model_sha256: str,
    detection_id: str,
) -> DetectorProvenance:
    """
    Create provenance metadata from a frame and detector info.
    
    Args:
        frame: Source canonical frame.
        detector_model_id: Detector model identifier.
        detector_model_version: Detector model version.
        detector_model_sha256: Detector model SHA256 hash.
        detection_id: Unique detection ID.
        
    Returns:
        DetectorProvenance instance.
    """
    return DetectorProvenance(
        source_type=frame.metadata.source_type.value,
        source_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        detector_model_id=detector_model_id,
        detector_model_version=detector_model_version,
        detector_model_sha256=detector_model_sha256,
        detection_id=detection_id,
    )