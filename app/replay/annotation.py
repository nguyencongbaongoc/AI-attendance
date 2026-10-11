"""
Phase 27 — Annotated Dual-Camera Replay Contracts.

Provides annotation contracts for offline forensic replay.
Annotations are overlays on ORIGINAL_FRAME - never modify the source frame.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class IdentityDisplayState(str, Enum):
    """Explicit identity display states for annotations."""
    KNOWN = "known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


class AttendanceDisplayState(str, Enum):
    """Attendance states for display."""
    PRESENT = "present"
    LATE = "late"
    LEFT = "left"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class EventDisplayType(str, Enum):
    """Event types for display."""
    IN = "in"
    OUT = "out"
    CROSSING = "crossing"


@dataclass(frozen=True)
class BoundingBox:
    """Bounding box in ORIGINAL_FRAME coordinates."""
    x: float
    y: float
    width: float
    height: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        return cls(
            x=data["x"],
            y=data["y"],
            width=data["width"],
            height=data["height"],
        )


@dataclass(frozen=True)
class PersonAnnotation:
    """
    Annotation for a detected person in a frame.
    
    All coordinates are in ORIGINAL_FRAME space.
    """
    # Person bounding box in original frame
    bbox: BoundingBox
    
    # Local track ID (camera-specific)
    local_track_id: str
    
    # Global observation ID when available (from Phase 21)
    global_observation_id: Optional[str] = None
    
    # Identity information
    identity_candidate: Optional[str] = None
    identity_certainty: IdentityDisplayState = IdentityDisplayState.UNKNOWN
    identity_confidence: float = 0.0
    similarity: Optional[float] = None
    
    # Face information (when available)
    face_bbox: Optional[BoundingBox] = None
    face_quality_class: Optional[str] = None
    face_quality_score: Optional[float] = None
    face_quality_reasons: Tuple[str, ...] = ()
    
    # Pose state (when available)
    pose_state: Optional[str] = None
    pose_angles: Optional[Tuple[float, float, float]] = None  # yaw, pitch, roll
    
    # Attendance state (when available from Phase 26)
    attendance_state: Optional[AttendanceDisplayState] = None
    attendance_decision_id: Optional[str] = None
    
    # Provenance
    detection_id: Optional[str] = None
    face_crop_id: Optional[str] = None
    track_provenance: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "bbox": self.bbox.to_dict(),
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "identity_candidate": self.identity_candidate,
            "identity_certainty": self.identity_certainty.value,
            "identity_confidence": self.identity_confidence,
            "similarity": self.similarity,
            "face_bbox": self.face_bbox.to_dict() if self.face_bbox else None,
            "face_quality_class": self.face_quality_class,
            "face_quality_score": self.face_quality_score,
            "face_quality_reasons": list(self.face_quality_reasons),
            "pose_state": self.pose_state,
            "pose_angles": list(self.pose_angles) if self.pose_angles else None,
            "attendance_state": self.attendance_state.value if self.attendance_state else None,
            "attendance_decision_id": self.attendance_decision_id,
            "detection_id": self.detection_id,
            "face_crop_id": self.face_crop_id,
            "track_provenance": self.track_provenance,
        }
        # Include all fields, even None values, for explicit contract representation
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonAnnotation":
        return cls(
            bbox=BoundingBox.from_dict(data["bbox"]),
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            identity_candidate=data.get("identity_candidate"),
            identity_certainty=IdentityDisplayState(data.get("identity_certainty", "unknown")),
            identity_confidence=data.get("identity_confidence", 0.0),
            similarity=data.get("similarity"),
            face_bbox=BoundingBox.from_dict(data["face_bbox"]) if data.get("face_bbox") else None,
            face_quality_class=data.get("face_quality_class"),
            face_quality_score=data.get("face_quality_score"),
            face_quality_reasons=tuple(data.get("face_quality_reasons", [])),
            pose_state=data.get("pose_state"),
            pose_angles=tuple(data["pose_angles"]) if data.get("pose_angles") else None,
            attendance_state=AttendanceDisplayState(data["attendance_state"]) if data.get("attendance_state") else None,
            attendance_decision_id=data.get("attendance_decision_id"),
            detection_id=data.get("detection_id"),
            face_crop_id=data.get("face_crop_id"),
            track_provenance=data.get("track_provenance", {}),
        )


@dataclass(frozen=True)
class FaceAnnotation:
    """
    Face annotation preserving Phase 16/17 semantics.
    
    Coordinates are in ORIGINAL_FRAME space.
    """
    # Face bounding box in original frame
    bbox: BoundingBox
    
    # Quality assessment
    quality_class: Optional[str] = None
    quality_score: Optional[float] = None
    quality_reasons: Tuple[str, ...] = ()
    
    # Pose
    pose_state: Optional[str] = None
    pose_angles: Optional[Tuple[float, float, float]] = None
    
    # Identity similarity (when available)
    identity_similarity: Optional[float] = None
    identity_candidate: Optional[str] = None
    
    # Provenance
    detection_id: Optional[str] = None
    face_crop_id: Optional[str] = None
    local_track_id: Optional[str] = None
    global_observation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "bbox": self.bbox.to_dict(),
            "quality_class": self.quality_class,
            "quality_score": self.quality_score,
            "quality_reasons": list(self.quality_reasons),
            "pose_state": self.pose_state,
            "pose_angles": list(self.pose_angles) if self.pose_angles else None,
            "identity_similarity": self.identity_similarity,
            "identity_candidate": self.identity_candidate,
            "detection_id": self.detection_id,
            "face_crop_id": self.face_crop_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
        }
        return {k: v for k, v in result.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FaceAnnotation":
        return cls(
            bbox=BoundingBox.from_dict(data["bbox"]),
            quality_class=data.get("quality_class"),
            quality_score=data.get("quality_score"),
            quality_reasons=tuple(data.get("quality_reasons", [])),
            pose_state=data.get("pose_state"),
            pose_angles=tuple(data["pose_angles"]) if data.get("pose_angles") else None,
            identity_similarity=data.get("identity_similarity"),
            identity_candidate=data.get("identity_candidate"),
            detection_id=data.get("detection_id"),
            face_crop_id=data.get("face_crop_id"),
            local_track_id=data.get("local_track_id"),
            global_observation_id=data.get("global_observation_id"),
        )


@dataclass(frozen=True)
class EventAnnotation:
    """
    Event annotation from Phase 22/23/24.
    
    Does NOT recompute crossing semantics - only displays upstream events.
    """
    event_type: EventDisplayType
    event_id: str
    direction: str  # "in", "out", "enter", "exit"
    timestamp: float
    camera_id: str
    local_track_id: str
    global_observation_id: Optional[str] = None
    
    # Phase 22: Crossing event reference
    crossing_event_id: Optional[str] = None
    crossing_direction: Optional[str] = None
    geometry_version: Optional[int] = None
    geometry_config_hash: Optional[str] = None
    
    # Phase 23: Raw IN/OUT event reference
    raw_event_id: Optional[str] = None
    
    # Phase 24: Resolved transition reference
    resolution_id: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    resolver_version: Optional[str] = None
    resolver_config_hash: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "event_type": self.event_type.value,
            "event_id": self.event_id,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "crossing_event_id": self.crossing_event_id,
            "crossing_direction": self.crossing_direction,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
            "raw_event_id": self.raw_event_id,
            "resolution_id": self.resolution_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "resolver_version": self.resolver_version,
            "resolver_config_hash": self.resolver_config_hash,
        }
        return {k: v for k, v in result.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventAnnotation":
        return cls(
            event_type=EventDisplayType(data["event_type"]),
            event_id=data["event_id"],
            direction=data["direction"],
            timestamp=data["timestamp"],
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            crossing_event_id=data.get("crossing_event_id"),
            crossing_direction=data.get("crossing_direction"),
            geometry_version=data.get("geometry_version"),
            geometry_config_hash=data.get("geometry_config_hash"),
            raw_event_id=data.get("raw_event_id"),
            resolution_id=data.get("resolution_id"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            resolver_version=data.get("resolver_version"),
            resolver_config_hash=data.get("resolver_config_hash"),
        )


@dataclass(frozen=True)
class AttendanceAnnotation:
    """
    Attendance annotation from Phase 26.
    
    Consumes AttendanceDecision - does NOT re-run AttendanceEngine.
    """
    attendance_state: AttendanceDisplayState
    decision_reason: str
    person_identity: Optional[str] = None
    identity_certainty: IdentityDisplayState = IdentityDisplayState.UNKNOWN
    identity_confidence: float = 0.0
    timetable_id: Optional[str] = None
    session_id: Optional[str] = None
    day: Optional[str] = None
    event_timestamp: float = 0.0
    camera_id: str = ""
    local_track_id: str = ""
    global_observation_id: Optional[str] = None
    attendance_decision_id: Optional[str] = None
    attendance_policy_id: Optional[str] = None
    attendance_policy_version: Optional[str] = None
    previous_attendance_state: Optional[str] = None
    new_attendance_state: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "attendance_state": self.attendance_state.value,
            "decision_reason": self.decision_reason,
            "person_identity": self.person_identity,
            "identity_certainty": self.identity_certainty.value,
            "identity_confidence": self.identity_confidence,
            "timetable_id": self.timetable_id,
            "session_id": self.session_id,
            "day": self.day,
            "event_timestamp": self.event_timestamp,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "attendance_decision_id": self.attendance_decision_id,
            "attendance_policy_id": self.attendance_policy_id,
            "attendance_policy_version": self.attendance_policy_version,
            "previous_attendance_state": self.previous_attendance_state,
            "new_attendance_state": self.new_attendance_state,
        }
        return {k: v for k, v in result.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttendanceAnnotation":
        return cls(
            attendance_state=AttendanceDisplayState(data["attendance_state"]),
            decision_reason=data["decision_reason"],
            person_identity=data.get("person_identity"),
            identity_certainty=IdentityDisplayState(data.get("identity_certainty", "unknown")),
            identity_confidence=data.get("identity_confidence", 0.0),
            timetable_id=data.get("timetable_id"),
            session_id=data.get("session_id"),
            day=data.get("day"),
            event_timestamp=data.get("event_timestamp", 0.0),
            camera_id=data.get("camera_id", ""),
            local_track_id=data.get("local_track_id", ""),
            global_observation_id=data.get("global_observation_id"),
            attendance_decision_id=data.get("attendance_decision_id"),
            attendance_policy_id=data.get("attendance_policy_id"),
            attendance_policy_version=data.get("attendance_policy_version"),
            previous_attendance_state=data.get("previous_attendance_state"),
            new_attendance_state=data.get("new_attendance_state"),
        )


@dataclass(frozen=True)
class GlobalObservationReference:
    """
    Reference to a GlobalObservation from Phase 21.
    
    Preserves camera-local track IDs and global observation ID.
    """
    global_observation_id: str
    association_state: str  # "associated", "not_associated", "ambiguous", "insufficient_evidence"
    camera_ids: Tuple[str, ...]
    local_track_ids: Tuple[str, ...]  # Format: "CAM1:track_A17"
    temporal_start: float
    temporal_end: float
    temporal_span: float
    primary_identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_state: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_observation_id": self.global_observation_id,
            "association_state": self.association_state,
            "camera_ids": list(self.camera_ids),
            "local_track_ids": list(self.local_track_ids),
            "temporal_start": self.temporal_start,
            "temporal_end": self.temporal_end,
            "temporal_span": self.temporal_span,
            "primary_identity_candidate": self.primary_identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_state": self.identity_state,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalObservationReference":
        return cls(
            global_observation_id=data["global_observation_id"],
            association_state=data["association_state"],
            camera_ids=tuple(data["camera_ids"]),
            local_track_ids=tuple(data["local_track_ids"]),
            temporal_start=data["temporal_start"],
            temporal_end=data["temporal_end"],
            temporal_span=data["temporal_span"],
            primary_identity_candidate=data.get("primary_identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_state=data.get("identity_state"),
        )


@dataclass(frozen=True)
class AnnotationProvenance:
    """Provenance information for an annotated frame."""
    source_video_id: str
    camera_id: str
    source_frame_index: int
    source_timestamp: float
    annotation_schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_video_id": self.source_video_id,
            "camera_id": self.camera_id,
            "source_frame_index": self.source_frame_index,
            "source_timestamp": self.source_timestamp,
            "annotation_schema_version": self.annotation_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnnotationProvenance":
        return cls(
            source_video_id=data["source_video_id"],
            camera_id=data["camera_id"],
            source_frame_index=data["source_frame_index"],
            source_timestamp=data["source_timestamp"],
            annotation_schema_version=data.get("annotation_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )


@dataclass(frozen=True)
class AnnotationFrame:
    """
    Complete annotated frame for replay.
    
    ORIGINAL_FRAME remains the source of truth.
    Annotations are overlays only.
    """
    # Frame identification
    camera_id: str
    frame_index: int
    timestamp: float
    timestamp_source: str  # "pts", "frame_index_fps", "not_available"
    
    # Source frame reference (not the frame data itself)
    source_frame_reference: str  # e.g., "video_id:frame_index"
    
    # Annotations (all optional and composable)
    person_annotations: Tuple[PersonAnnotation, ...] = ()
    face_annotations: Tuple[FaceAnnotation, ...] = ()
    event_annotations: Tuple[EventAnnotation, ...] = ()
    attendance_annotations: Tuple[AttendanceAnnotation, ...] = ()
    global_observation_references: Tuple[GlobalObservationReference, ...] = ()
    
    # Provenance
    provenance: AnnotationProvenance = field(default_factory=lambda: AnnotationProvenance(
        source_video_id="",
        camera_id="",
        source_frame_index=0,
        source_timestamp=0.0,
    ))
    
    # Schema version
    annotation_schema_version: str = "1.0"
    
    def __post_init__(self):
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if self.frame_index < 0:
            raise ValueError("frame_index must be >= 0")
        if self.timestamp < 0:
            raise ValueError("timestamp must be >= 0")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "timestamp_source": self.timestamp_source,
            "source_frame_reference": self.source_frame_reference,
            "person_annotations": [p.to_dict() for p in self.person_annotations],
            "face_annotations": [f.to_dict() for f in self.face_annotations],
            "event_annotations": [e.to_dict() for e in self.event_annotations],
            "attendance_annotations": [a.to_dict() for a in self.attendance_annotations],
            "global_observation_references": [g.to_dict() for g in self.global_observation_references],
            "provenance": self.provenance.to_dict(),
            "annotation_schema_version": self.annotation_schema_version,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnnotationFrame":
        return cls(
            camera_id=data["camera_id"],
            frame_index=data["frame_index"],
            timestamp=data["timestamp"],
            timestamp_source=data["timestamp_source"],
            source_frame_reference=data["source_frame_reference"],
            person_annotations=tuple(PersonAnnotation.from_dict(p) for p in data.get("person_annotations", [])),
            face_annotations=tuple(FaceAnnotation.from_dict(f) for f in data.get("face_annotations", [])),
            event_annotations=tuple(EventAnnotation.from_dict(e) for e in data.get("event_annotations", [])),
            attendance_annotations=tuple(AttendanceAnnotation.from_dict(a) for a in data.get("attendance_annotations", [])),
            global_observation_references=tuple(GlobalObservationReference.from_dict(g) for g in data.get("global_observation_references", [])),
            provenance=AnnotationProvenance.from_dict(data["provenance"]),
            annotation_schema_version=data.get("annotation_schema_version", "1.0"),
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "AnnotationFrame":
        return cls.from_dict(json.loads(json_str))


def generate_annotation_frame_id(
    camera_id: str,
    frame_index: int,
    source_video_id: str,
    annotation_schema_version: str = "1.0",
) -> str:
    """Generate deterministic annotation frame ID."""
    content = f"ANN:{source_video_id}:{camera_id}:f{frame_index}:v{annotation_schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"ANN-{hash_suffix}"