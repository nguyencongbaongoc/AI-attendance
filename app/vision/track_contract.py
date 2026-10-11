"""
Phase 11 — Person/Face Tracking Contract.

This module defines the model-independent tracking contract for temporal
person tracking on top of Phase 9 + Phase 10 contracts.

All coordinates operate in ORIGINAL_FRAME space (3840x2160).

CRITICAL:
- track_id is NOT identity. It means "same observed person across frames".
- No ArcFace, no 1K3D68, no identity recognition, no attendance, no IN/OUT.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.vision.association_contract import PersonFaceAssociation
from app.vision.detector_contract import DetectorProvenance, FaceDetectionContract


class TrackLifecycleState(str, Enum):
    """
    Track lifecycle states.
    
    NEW      -> First frame track is created (unconfirmed)
    ACTIVE   -> Track confirmed, regularly updated
    LOST     -> Track not updated for N frames (within tolerance)
    CLOSED   -> Track terminated (exceeded tolerance or explicit close)
    """
    
    NEW = "new"
    ACTIVE = "active"
    LOST = "lost"
    CLOSED = "closed"


def _generate_deterministic_track_id(bbox: Tuple[float, float, float, float], frame_index: int) -> str:
    """Generate a deterministic track ID from bbox and frame index."""
    # Use bbox coordinates to create a stable hash
    bbox_str = f"{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f},{frame_index}"
    hash_suffix = hashlib.md5(bbox_str.encode()).hexdigest()[:12]
    return f"trk_{hash_suffix}"


@dataclass(frozen=True)
class Track:
    """
    Model-independent person track.
    
    Represents a single person tracked across consecutive frames.
    All coordinates in ORIGINAL_FRAME space (3840x2160).
    
    This contract is independent of:
    - ArcFace
    - 1K3D68
    - Identity recognition
    - Attendance
    - IN/OUT logic
    """
    
    # Track identity (NOT human identity) - deterministic from bbox
    track_id: str = ""
    
    # Source frame reference (frame where track was created)
    source_frame_id: str = ""
    frame_index: int = 0
    timestamp: Optional[float] = None
    
    # Current person bbox in ORIGINAL_FRAME coordinates
    bbox_original_frame: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    
    # Current detection confidence
    confidence: float = 0.0
    
    # Lifecycle
    lifecycle_state: TrackLifecycleState = TrackLifecycleState.NEW
    age: int = 0                    # Total frames since creation
    hits: int = 0                   # Frames with successful update
    missed_frames: int = 0          # Consecutive frames without update
    last_seen: int = 0              # Frame index of last update
    
    # Face attachment (from Phase 10 association)
    face_detection_id: str = ""
    face_bbox: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    face_confidence: float = 0.0
    face_landmarks5: List[Tuple[float, float]] = field(default_factory=list)
    face_model_id: str = ""
    face_model_sha256: str = ""
    
    # Provenance
    person_provenance: Optional[DetectorProvenance] = None
    face_provenance: Optional[DetectorProvenance] = None
    
    # Coordinate space (always ORIGINAL_FRAME)
    coordinate_space: str = "original_frame"
    
    def __post_init__(self):
        """Validate track data."""
        # Validate coordinate space
        if self.coordinate_space != "original_frame":
            raise ValueError(
                f"Track must be in 'original_frame' space, "
                f"got '{self.coordinate_space}'"
            )
        
        # Validate bbox is finite
        if not all(np.isfinite(self.bbox_original_frame)):
            raise ValueError(f"Invalid bbox: non-finite coordinates {self.bbox_original_frame}")
        
        # Validate confidence range
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid confidence: {self.confidence}")
        
        # Validate face confidence range
        if not (0.0 <= self.face_confidence <= 1.0):
            raise ValueError(f"Invalid face_confidence: {self.face_confidence}")
        
        # Validate face landmarks
        if self.face_landmarks5 and len(self.face_landmarks5) != 5:
            raise ValueError(
                f"Expected 5 face landmarks, got {len(self.face_landmarks5)}"
            )
        
        # Validate lifecycle state
        if not isinstance(self.lifecycle_state, TrackLifecycleState):
            raise ValueError(f"Invalid lifecycle_state: {self.lifecycle_state}")
        
        # Validate non-negative counters
        if self.age < 0:
            raise ValueError(f"age must be >= 0, got {self.age}")
        if self.hits < 0:
            raise ValueError(f"hits must be >= 0, got {self.hits}")
        if self.missed_frames < 0:
            raise ValueError(f"missed_frames must be >= 0, got {self.missed_frames}")
        if self.last_seen < 0:
            raise ValueError(f"last_seen must be >= 0, got {self.last_seen}")
        
        # Validate bbox within 4K boundaries (skip empty bboxes)
        x1, y1, x2, y2 = self.bbox_original_frame
        if not (x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0):
            if x1 < 0 or y1 < 0 or x2 > 3840 or y2 > 2160:
                raise ValueError(
                    f"bbox {self.bbox_original_frame} exceeds 4K boundaries (3840x2160)"
                )
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"bbox {self.bbox_original_frame} has zero or negative area")
        
        # Validate face bbox if present
        fx1, fy1, fx2, fy2 = self.face_bbox
        if not (fx1 == 0 and fy1 == 0 and fx2 == 0 and fy2 == 0):
            if fx1 < 0 or fy1 < 0 or fx2 > 3840 or fy2 > 2160:
                raise ValueError(
                    f"face_bbox {self.face_bbox} exceeds 4K boundaries (3840x2160)"
                )
            if fx2 <= fx1 or fy2 <= fy1:
                raise ValueError(f"face_bbox {self.face_bbox} has zero or negative area")
    
    @property
    def width(self) -> float:
        return self.bbox_original_frame[2] - self.bbox_original_frame[0]
    
    @property
    def height(self) -> float:
        return self.bbox_original_frame[3] - self.bbox_original_frame[1]
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_original_frame
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
    
    @property
    def has_face(self) -> bool:
        """Check if track has an attached face."""
        return self.face_detection_id != "" and self.face_confidence > 0.0
    
    @property
    def is_active(self) -> bool:
        """Check if track is in ACTIVE state."""
        return self.lifecycle_state == TrackLifecycleState.ACTIVE
    
    @property
    def is_lost(self) -> bool:
        """Check if track is in LOST state."""
        return self.lifecycle_state == TrackLifecycleState.LOST
    
    @property
    def is_closed(self) -> bool:
        """Check if track is in CLOSED state."""
        return self.lifecycle_state == TrackLifecycleState.CLOSED
    
    @property
    def is_new(self) -> bool:
        """Check if track is in NEW state."""
        return self.lifecycle_state == TrackLifecycleState.NEW
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "track_id": self.track_id,
            "source_frame_id": self.source_frame_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "bbox_original_frame": list(self.bbox_original_frame),
            "confidence": self.confidence,
            "lifecycle_state": self.lifecycle_state.value,
            "age": self.age,
            "hits": self.hits,
            "missed_frames": self.missed_frames,
            "last_seen": self.last_seen,
            "face_detection_id": self.face_detection_id,
            "face_bbox": list(self.face_bbox),
            "face_confidence": self.face_confidence,
            "face_landmarks5": self.face_landmarks5,
            "face_model_id": self.face_model_id,
            "face_model_sha256": self.face_model_sha256,
            "coordinate_space": self.coordinate_space,
            "person_provenance": self.person_provenance.to_dict() if self.person_provenance else None,
            "face_provenance": self.face_provenance.to_dict() if self.face_provenance else None,
            "width": self.width,
            "height": self.height,
            "area": self.area,
            "has_face": self.has_face,
        }


@dataclass
class TrackerConfig:
    """Configuration for tracker behavior."""
    
    # Association thresholds
    min_iou_threshold: float = 0.3
    min_center_distance_threshold: float = 100.0  # pixels in 4K
    
    # Lifecycle thresholds
    new_to_active_hits: int = 2          # Hits required to go NEW -> ACTIVE
    active_to_lost_missed: int = 5       # Missed frames to go ACTIVE -> LOST
    lost_to_active_hits: int = 1         # Hits required to go LOST -> ACTIVE
    lost_to_closed_missed: int = 10      # Missed frames to go LOST -> CLOSED
    
    # Face attachment
    require_face_for_active: bool = False  # Don't require face to stay active
    
    # Determinism
    deterministic_ordering: bool = True
    
    # Memory bounds
    max_active_tracks: int = 100
    max_lost_tracks: int = 50
    
    def __post_init__(self):
        """Validate configuration."""
        if not (0.0 <= self.min_iou_threshold <= 1.0):
            raise ValueError(f"min_iou_threshold must be in [0, 1], got {self.min_iou_threshold}")
        if self.min_center_distance_threshold < 0:
            raise ValueError(f"min_center_distance_threshold must be >= 0")
        if self.new_to_active_hits < 1:
            raise ValueError(f"new_to_active_hits must be >= 1")
        if self.active_to_lost_missed < 1:
            raise ValueError(f"active_to_lost_missed must be >= 1")
        if self.lost_to_active_hits < 1:
            raise ValueError(f"lost_to_active_hits must be >= 1")
        if self.lost_to_closed_missed < 1:
            raise ValueError(f"lost_to_closed_missed must be >= 1")
        if self.max_active_tracks < 1:
            raise ValueError(f"max_active_tracks must be >= 1")
        if self.max_lost_tracks < 1:
            raise ValueError(f"max_lost_tracks must be >= 1")


@dataclass
class TrackingResult:
    """
    Complete tracking result for a single frame.
    
    Contains all tracks (active, lost, newly created) for traceability.
    """
    
    # Source frame reference
    source_frame_id: str
    frame_index: int
    timestamp: Optional[float] = None
    
    # All tracks after update
    tracks: List[Track] = field(default_factory=list)
    
    # Newly created tracks this frame
    new_tracks: List[Track] = field(default_factory=list)
    
    # Tracks that transitioned to CLOSED this frame
    closed_tracks: List[Track] = field(default_factory=list)
    
    # Summary statistics
    active_count: int = 0
    lost_count: int = 0
    new_count: int = 0
    closed_count: int = 0
    tracks_with_face: int = 0
    
    def __post_init__(self):
        """Calculate summary statistics."""
        self.active_count = len([t for t in self.tracks if t.is_active])
        self.lost_count = len([t for t in self.tracks if t.is_lost])
        self.new_count = len([t for t in self.tracks if t.is_new])
        self.closed_count = len([t for t in self.tracks if t.is_closed])
        self.tracks_with_face = len([t for t in self.tracks if t.has_face])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_frame_id": self.source_frame_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "tracks": [t.to_dict() for t in self.tracks],
            "new_tracks": [t.to_dict() for t in self.new_tracks],
            "closed_tracks": [t.to_dict() for t in self.closed_tracks],
            "summary": {
                "active": self.active_count,
                "lost": self.lost_count,
                "new": self.new_count,
                "closed": self.closed_count,
                "with_face": self.tracks_with_face,
                "total": len(self.tracks),
            },
        }


def create_track_from_person_detection(
    person_detection: Any,  # PersonDetectionContract or compatible
    frame: CanonicalFrame,
    association: Optional[PersonFaceAssociation] = None,
) -> Track:
    """
    Create a new Track from a person detection and optional face association.
    
    Args:
        person_detection: Person detection with bbox, confidence, model info
        frame: Source canonical frame
        association: Optional PersonFaceAssociation from Phase 10
        
    Returns:
        Track instance in NEW state
    """
    # Extract person info
    person_bbox = person_detection.bbox
    person_confidence = person_detection.confidence
    person_detection_id = getattr(person_detection, 'detection_id', '')
    person_model_id = getattr(person_detection, 'model_id', '')
    person_model_sha256 = getattr(person_detection, 'model_sha256', '')
    person_provenance = getattr(person_detection, 'provenance', None)
    
    # Extract face info from association if available
    if association and association.association_status.value == "associated":
        face_detection_id = association.face_detection_id
        face_bbox = association.face_bbox
        face_confidence = association.face_confidence
        face_landmarks5 = association.face_landmarks5
        face_model_id = association.face_model_id
        face_model_sha256 = association.face_model_sha256
        face_provenance = association.face_provenance
    else:
        face_detection_id = ""
        face_bbox = (0.0, 0.0, 0.0, 0.0)
        face_confidence = 0.0
        face_landmarks5 = []
        face_model_id = ""
        face_model_sha256 = ""
        face_provenance = None
    
    # Generate deterministic track ID from bbox
    track_id = _generate_deterministic_track_id(person_bbox, frame.metadata.frame_index)
    
    return Track(
        track_id=track_id,
        source_frame_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        bbox_original_frame=person_bbox,
        confidence=person_confidence,
        lifecycle_state=TrackLifecycleState.NEW,
        age=1,
        hits=1,
        missed_frames=0,
        last_seen=frame.metadata.frame_index,
        face_detection_id=face_detection_id,
        face_bbox=face_bbox,
        face_confidence=face_confidence,
        face_landmarks5=face_landmarks5,
        face_model_id=face_model_id,
        face_model_sha256=face_model_sha256,
        person_provenance=person_provenance,
        face_provenance=face_provenance,
        coordinate_space="original_frame",
    )


def update_track_from_person_detection(
    track: Track,
    person_detection: Any,  # PersonDetectionContract or compatible
    frame: CanonicalFrame,
    association: Optional[PersonFaceAssociation] = None,
) -> Track:
    """
    Update an existing track with a new person detection and optional face association.
    
    Returns a new Track instance (immutable update).
    """
    # Extract person info
    person_bbox = person_detection.bbox
    person_confidence = person_detection.confidence
    person_detection_id = getattr(person_detection, 'detection_id', '')
    person_model_id = getattr(person_detection, 'model_id', '')
    person_model_sha256 = getattr(person_detection, 'model_sha256', '')
    person_provenance = getattr(person_detection, 'provenance', None)
    
    # Extract face info from association if available
    if association and association.association_status.value == "associated":
        face_detection_id = association.face_detection_id
        face_bbox = association.face_bbox
        face_confidence = association.face_confidence
        face_landmarks5 = association.face_landmarks5
        face_model_id = association.face_model_id
        face_model_sha256 = association.face_model_sha256
        face_provenance = association.face_provenance
    else:
        # Keep existing face info if no new association
        face_detection_id = track.face_detection_id
        face_bbox = track.face_bbox
        face_confidence = track.face_confidence
        face_landmarks5 = track.face_landmarks5
        face_model_id = track.face_model_id
        face_model_sha256 = track.face_model_sha256
        face_provenance = track.face_provenance
    
    # Determine new lifecycle state
    new_age = track.age + 1
    new_hits = track.hits + 1
    new_missed = 0
    new_last_seen = frame.metadata.frame_index
    
    # State transitions
    if track.lifecycle_state == TrackLifecycleState.NEW:
        if new_hits >= 2:  # Default threshold (config.new_to_active_hits)
            new_state = TrackLifecycleState.ACTIVE
        else:
            new_state = TrackLifecycleState.NEW
    elif track.lifecycle_state == TrackLifecycleState.ACTIVE:
        new_state = TrackLifecycleState.ACTIVE
    elif track.lifecycle_state == TrackLifecycleState.LOST:
        if new_hits - track.hits >= 1:  # Got a hit
            new_state = TrackLifecycleState.ACTIVE
        else:
            new_state = TrackLifecycleState.LOST
    else:  # CLOSED
        new_state = TrackLifecycleState.CLOSED
    
    return Track(
        track_id=track.track_id,
        source_frame_id=track.source_frame_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        bbox_original_frame=person_bbox,
        confidence=person_confidence,
        lifecycle_state=new_state,
        age=new_age,
        hits=new_hits,
        missed_frames=new_missed,
        last_seen=new_last_seen,
        face_detection_id=face_detection_id,
        face_bbox=face_bbox,
        face_confidence=face_confidence,
        face_landmarks5=face_landmarks5,
        face_model_id=face_model_id,
        face_model_sha256=face_model_sha256,
        person_provenance=person_provenance,
        face_provenance=face_provenance,
        coordinate_space="original_frame",
    )


def age_track_without_detection(
    track: Track,
    frame: CanonicalFrame,
    config: TrackerConfig,
) -> Track:
    """
    Age a track that didn't get a detection this frame.
    
    Returns a new Track instance with incremented missed_frames.
    """
    new_age = track.age + 1
    new_missed = track.missed_frames + 1
    new_hits = track.hits
    
    # State transitions based on missed frames
    if track.lifecycle_state == TrackLifecycleState.NEW:
        # NEW tracks that miss immediately go to LOST
        new_state = TrackLifecycleState.LOST
    elif track.lifecycle_state == TrackLifecycleState.ACTIVE:
        if new_missed >= config.active_to_lost_missed:
            new_state = TrackLifecycleState.LOST
        else:
            new_state = TrackLifecycleState.ACTIVE
    elif track.lifecycle_state == TrackLifecycleState.LOST:
        if new_missed >= config.lost_to_closed_missed:
            new_state = TrackLifecycleState.CLOSED
        else:
            new_state = TrackLifecycleState.LOST
    else:  # CLOSED
        new_state = TrackLifecycleState.CLOSED
    
    return Track(
        track_id=track.track_id,
        source_frame_id=track.source_frame_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        bbox_original_frame=track.bbox_original_frame,  # Keep last known bbox
        confidence=track.confidence,
        lifecycle_state=new_state,
        age=new_age,
        hits=new_hits,
        missed_frames=new_missed,
        last_seen=track.last_seen,
        face_detection_id=track.face_detection_id,
        face_bbox=track.face_bbox,
        face_confidence=track.face_confidence,
        face_landmarks5=track.face_landmarks5,
        face_model_id=track.face_model_id,
        face_model_sha256=track.face_model_sha256,
        person_provenance=track.person_provenance,
        face_provenance=track.face_provenance,
        coordinate_space="original_frame",
    )