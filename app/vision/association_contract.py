"""
Phase 10 — Person ↔ Face Association Contract.

This module defines the model-independent association contract between
YOLO11n person detections and face detector detections.

All coordinates operate in ORIGINAL_FRAME space (3840x2160).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.vision.detector_contract import FaceDetectionContract, DetectorProvenance


class AssociationStatus(str, Enum):
    """Association status between person and face detections."""
    
    ASSOCIATED = "associated"              # Face successfully associated with person
    UNASSOCIATED_FACE = "unassociated_face"  # Face has no matching person
    UNASSOCIATED_PERSON = "unassociated_person"  # Person has no matching face
    AMBIGUOUS = "ambiguous"                # Multiple valid associations, cannot determine


@dataclass(frozen=True)
class PersonFaceAssociation:
    """
    Model-independent person-face association result.
    
    This is the canonical output of the association layer.
    Downstream code (tracking, identity, attendance) depends on this contract.
    
    All coordinates are in ORIGINAL_FRAME space (3840x2160).
    """
    
    # Association identity
    association_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    
    # Source frame reference
    source_frame_id: str = ""
    frame_index: int = 0
    
    # Person detection reference
    person_detection_id: str = ""
    person_bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    person_confidence: float = 0.0
    person_model_id: str = ""
    person_model_sha256: str = ""
    
    # Face detection reference
    face_detection_id: str = ""
    face_bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    face_confidence: float = 0.0
    face_landmarks5: List[Tuple[float, float]] = field(default_factory=list)
    face_model_id: str = ""
    face_model_sha256: str = ""
    
    # Association result
    association_status: AssociationStatus = AssociationStatus.UNASSOCIATED_FACE
    association_score: float = 0.0
    geometry_reason: str = ""
    
    # Coordinate space (always ORIGINAL_FRAME)
    coordinate_space: str = "original_frame"
    
    # Provenance
    person_provenance: Optional[DetectorProvenance] = None
    face_provenance: Optional[DetectorProvenance] = None
    
    def __post_init__(self):
        """Validate association data."""
        # Validate coordinate space
        if self.coordinate_space != "original_frame":
            raise ValueError(
                f"Association must be in 'original_frame' space, "
                f"got '{self.coordinate_space}'"
            )
        
        # Validate bboxes are finite
        for bbox, name in [
            (self.person_bbox, "person_bbox"),
            (self.face_bbox, "face_bbox"),
        ]:
            if not all(np.isfinite(bbox)):
                raise ValueError(f"Invalid {name}: non-finite coordinates {bbox}")
        
        # Validate confidence ranges
        if not (0.0 <= self.person_confidence <= 1.0):
            raise ValueError(f"Invalid person_confidence: {self.person_confidence}")
        if not (0.0 <= self.face_confidence <= 1.0):
            raise ValueError(f"Invalid face_confidence: {self.face_confidence}")
        
        # Validate association score
        if not (0.0 <= self.association_score <= 1.0):
            raise ValueError(f"Invalid association_score: {self.association_score}")
        
        # Validate face landmarks
        if self.face_landmarks5 and len(self.face_landmarks5) != 5:
            raise ValueError(
                f"Expected 5 face landmarks, got {len(self.face_landmarks5)}"
            )
        
        # Validate model identities (required for associated/ambiguous, optional for unassociated)
        if self.association_status in (AssociationStatus.ASSOCIATED, AssociationStatus.AMBIGUOUS):
            if not self.person_model_id:
                raise ValueError("person_model_id is required for associated/ambiguous status")
            if not self.person_model_sha256:
                raise ValueError("person_model_sha256 is required for associated/ambiguous status")
            if not self.face_model_id:
                raise ValueError("face_model_id is required for associated/ambiguous status")
            if not self.face_model_sha256:
                raise ValueError("face_model_sha256 is required for associated/ambiguous status")
        elif self.association_status == AssociationStatus.UNASSOCIATED_FACE:
            # For unassociated face, face model identity is required, person is empty
            if not self.face_model_id:
                raise ValueError("face_model_id is required")
            if not self.face_model_sha256:
                raise ValueError("face_model_sha256 is required")
        elif self.association_status == AssociationStatus.UNASSOCIATED_PERSON:
            # For unassociated person, person model identity is required, face is empty
            if not self.person_model_id:
                raise ValueError("person_model_id is required")
            if not self.person_model_sha256:
                raise ValueError("person_model_sha256 is required")
        
        # Validate bboxes within 4K boundaries (skip empty bboxes for unassociated)
        for bbox, name in [
            (self.person_bbox, "person_bbox"),
            (self.face_bbox, "face_bbox"),
        ]:
            x1, y1, x2, y2 = bbox
            # Skip validation for empty bboxes (unassociated detections)
            if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                continue
            if x1 < 0 or y1 < 0 or x2 > 3840 or y2 > 2160:
                raise ValueError(
                    f"{name} {bbox} exceeds 4K boundaries (3840x2160)"
                )
            # Validate non-zero area for associated/ambiguous
            if self.association_status in (AssociationStatus.ASSOCIATED, AssociationStatus.AMBIGUOUS):
                if x2 <= x1 or y2 <= y1:
                    raise ValueError(f"{name} {bbox} has zero or negative area")
    
    @property
    def person_width(self) -> float:
        return self.person_bbox[2] - self.person_bbox[0]
    
    @property
    def person_height(self) -> float:
        return self.person_bbox[3] - self.person_bbox[1]
    
    @property
    def person_area(self) -> float:
        return self.person_width * self.person_height
    
    @property
    def person_center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.person_bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    @property
    def face_width(self) -> float:
        return self.face_bbox[2] - self.face_bbox[0]
    
    @property
    def face_height(self) -> float:
        return self.face_bbox[3] - self.face_bbox[1]
    
    @property
    def face_area(self) -> float:
        return self.face_width * self.face_height
    
    @property
    def face_center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.face_bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "association_id": self.association_id,
            "source_frame_id": self.source_frame_id,
            "frame_index": self.frame_index,
            "person_detection_id": self.person_detection_id,
            "person_bbox": list(self.person_bbox),
            "person_confidence": self.person_confidence,
            "person_model_id": self.person_model_id,
            "person_model_sha256": self.person_model_sha256,
            "face_detection_id": self.face_detection_id,
            "face_bbox": list(self.face_bbox),
            "face_confidence": self.face_confidence,
            "face_landmarks5": self.face_landmarks5,
            "face_model_id": self.face_model_id,
            "face_model_sha256": self.face_model_sha256,
            "association_status": self.association_status.value,
            "association_score": self.association_score,
            "geometry_reason": self.geometry_reason,
            "coordinate_space": self.coordinate_space,
            "person_provenance": self.person_provenance.to_dict() if self.person_provenance else None,
            "face_provenance": self.face_provenance.to_dict() if self.face_provenance else None,
            "person_width": self.person_width,
            "person_height": self.person_height,
            "person_area": self.person_area,
            "face_width": self.face_width,
            "face_height": self.face_height,
            "face_area": self.face_area,
        }


@dataclass
class AssociationResult:
    """
    Complete association result for a single frame.
    
    Contains all associations (matched and unmatched) for traceability.
    """
    
    # Source frame reference
    source_frame_id: str
    frame_index: int
    
    # All associations (including unmatched)
    associations: List[PersonFaceAssociation]
    
    # Unmatched detections preserved
    unmatched_persons: List[Dict[str, Any]] = field(default_factory=list)
    unmatched_faces: List[Dict[str, Any]] = field(default_factory=list)
    
    # Summary statistics
    total_persons: int = 0
    total_faces: int = 0
    associated_count: int = 0
    ambiguous_count: int = 0
    unassociated_person_count: int = 0
    unassociated_face_count: int = 0
    
    def __post_init__(self):
        """Calculate summary statistics."""
        self.total_persons = len(self.associations) + len(self.unmatched_persons)
        self.total_faces = len([a for a in self.associations if a.association_status != AssociationStatus.UNASSOCIATED_PERSON]) + len(self.unmatched_faces)
        self.associated_count = len([a for a in self.associations if a.association_status == AssociationStatus.ASSOCIATED])
        self.ambiguous_count = len([a for a in self.associations if a.association_status == AssociationStatus.AMBIGUOUS])
        self.unassociated_person_count = len([a for a in self.associations if a.association_status == AssociationStatus.UNASSOCIATED_PERSON]) + len(self.unmatched_persons)
        self.unassociated_face_count = len([a for a in self.associations if a.association_status == AssociationStatus.UNASSOCIATED_FACE]) + len(self.unmatched_faces)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_frame_id": self.source_frame_id,
            "frame_index": self.frame_index,
            "associations": [a.to_dict() for a in self.associations],
            "unmatched_persons": self.unmatched_persons,
            "unmatched_faces": self.unmatched_faces,
            "summary": {
                "total_persons": self.total_persons,
                "total_faces": self.total_faces,
                "associated": self.associated_count,
                "ambiguous": self.ambiguous_count,
                "unassociated_person": self.unassociated_person_count,
                "unassociated_face": self.unassociated_face_count,
            },
        }


def create_association_from_detections(
    person_detection: Any,  # PersonDetectionContract or None
    face_detection: FaceDetectionContract,
    frame: CanonicalFrame,
    association_status: AssociationStatus,
    association_score: float,
    geometry_reason: str,
) -> PersonFaceAssociation:
    """
    Create a PersonFaceAssociation from person and face detections.
    
    Args:
        person_detection: Person detection with bbox, confidence, model info (or None for unassociated face)
        face_detection: Face detection contract
        frame: Source canonical frame
        association_status: Association status
        association_score: Association confidence score [0, 1]
        geometry_reason: Human-readable reason for association decision
        
    Returns:
        PersonFaceAssociation instance
    """
    if person_detection is None:
        # Unassociated face - create association with empty person fields
        return PersonFaceAssociation(
            source_frame_id=frame.metadata.source_id,
            frame_index=frame.metadata.frame_index,
            person_detection_id="",
            person_bbox=(0.0, 0.0, 0.0, 0.0),
            person_confidence=0.0,
            person_model_id="",
            person_model_sha256="",
            face_detection_id=face_detection.detection_id,
            face_bbox=face_detection.bbox,
            face_confidence=face_detection.confidence,
            face_landmarks5=face_detection.landmarks5,
            face_model_id=face_detection.detector_model_id,
            face_model_sha256=face_detection.detector_model_sha256,
            association_status=association_status,
            association_score=association_score,
            geometry_reason=geometry_reason,
            coordinate_space="original_frame",
            person_provenance=None,
            face_provenance=face_detection.provenance,
        )
    
    return PersonFaceAssociation(
        source_frame_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        person_detection_id=getattr(person_detection, 'detection_id', ''),
        person_bbox=person_detection.bbox,
        person_confidence=person_detection.confidence,
        person_model_id=person_detection.model_id,
        person_model_sha256=person_detection.model_sha256,
        face_detection_id=face_detection.detection_id,
        face_bbox=face_detection.bbox,
        face_confidence=face_detection.confidence,
        face_landmarks5=face_detection.landmarks5,
        face_model_id=face_detection.detector_model_id,
        face_model_sha256=face_detection.detector_model_sha256,
        association_status=association_status,
        association_score=association_score,
        geometry_reason=geometry_reason,
        coordinate_space="original_frame",
        person_provenance=getattr(person_detection, 'provenance', None),
        face_provenance=face_detection.provenance,
    )
