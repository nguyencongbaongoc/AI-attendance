"""
Phase 25 — Attendance Persistence Contract.

Canonical persisted attendance record derived from Phase 24 ResolvedTransition.
Preserves full provenance chain: AttendanceRecord -> ResolvedTransition -> RawInOutEvent -> CrossingEvent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from fractions import Fraction
from typing import Any, Dict, List, Optional


class AttendanceDirection(str, Enum):
    """Attendance event direction (derived from Phase 24 transition)."""
    IN = "in"
    OUT = "out"


class IdentityCertainty(str, Enum):
    """Identity certainty level (preserved from upstream)."""
    KNOWN = "known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class AttendanceRecord:
    """
    Canonical persisted attendance record.
    
    Created from a Phase 24 ResolvedTransition that represents an actual state transition.
    Preserves full provenance to answer: WHO, WHEN, WHERE, WHAT, WHY, WHICH VERSION.
    
    This is an IMMUTABLE record - after creation it MUST NOT be modified.
    """
    # Record identification (stable, deterministic)
    attendance_record_id: str
    
    # Identity reference (preserved from upstream)
    identity_certainty: IdentityCertainty = IdentityCertainty.UNKNOWN
    identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_evidence_ref: Optional[str] = None  # Legacy: Reference to GlobalObservation/IdentityEvidence
    
    # NEW: Explicit evidence references (P3.9)
    face_evidence_ref: Optional[str] = None  # identity_evidence.evidence_id for face
    body_evidence_ref: Optional[str] = None  # identity_evidence.evidence_id for body
    face_quality: float = 0.0
    body_quality: float = 0.0
    association_method: str = ""  # "fused" | "face_only" | "body_only" | "geometric"
    conflict_flag: bool = False
    provisional_person_id: Optional[str] = None
    identity_state: str = "unknown"  # "unknown" | "candidate" | "provisional" | "confirmed" | "conflict" | "reacquired"
    
    # Phase 17: Evidence storage URIs (relative paths under /static/evidence)
    snapshot_face_url: Optional[str] = None
    snapshot_scene_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    
    # Event details
    direction: AttendanceDirection = AttendanceDirection.IN
    event_timestamp: float = 0.0  # Upstream event timestamp (NOT persistence time)
    event_frame_index: int = -1
    
    # Camera and track provenance
    camera_id: str = ""
    local_track_id: str = ""
    global_observation_id: Optional[str] = None
    
    # Source references (provenance chain)
    source_raw_event_id: str = ""           # Phase 23 RawInOutEvent ID
    source_resolution_id: str = ""          # Phase 24 ResolvedTransition ID
    source_crossing_event_id: Optional[str] = None  # Phase 22 CrossingEvent ID
    
    # Geometry provenance
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    # Resolver provenance
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    
    # Derived state (from Phase 24)
    previous_state: str = "unknown"  # DerivedState value
    new_state: str = "unknown"       # DerivedState value
    
    # NEW: Metadata fields (P1.2c)
    stream_epoch: int = 0
    pts: int = 0
    time_base: Fraction = field(default_factory=lambda: Fraction(1, 90000))
    capture_timestamp: float = 0.0
    processing_timestamp: float = 0.0
    model_version: str = ""
    enrollment_version: str = ""
    
    # Versioning
    attendance_schema_version: str = "1.1"  # Updated for new fields
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Persistence metadata (separate from event timestamp)
    persisted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.attendance_record_id:
            raise ValueError("attendance_record_id is required")
        if not self.source_raw_event_id:
            raise ValueError("source_raw_event_id is required")
        if not self.source_resolution_id:
            raise ValueError("source_resolution_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
        if self.direction not in (AttendanceDirection.IN, AttendanceDirection.OUT):
            raise ValueError(f"direction must be 'in' or 'out', got {self.direction}")
        if self.event_timestamp < 0:
            raise ValueError("event_timestamp must be >= 0")
        if self.attendance_schema_version not in ("1.0", "1.1"):
            raise ValueError(f"Unsupported attendance_schema_version: {self.attendance_schema_version}")
        if self.identity_certainty not in IdentityCertainty:
            raise ValueError(f"Invalid identity_certainty: {self.identity_certainty}")
        if self.previous_state not in ("unknown", "inside", "outside"):
            raise ValueError(f"Invalid previous_state: {self.previous_state}")
        if self.new_state not in ("unknown", "inside", "outside"):
            raise ValueError(f"Invalid new_state: {self.new_state}")
        if self.identity_state not in ("unknown", "candidate", "provisional", "confirmed", "conflict", "reacquired"):
            raise ValueError(f"Invalid identity_state: {self.identity_state}")
        if self.association_method and self.association_method not in ("fused", "face_only", "body_only", "geometric"):
            raise ValueError(f"Invalid association_method: {self.association_method}")
    
    @property
    def is_in(self) -> bool:
        return self.direction == AttendanceDirection.IN
    
    @property
    def is_out(self) -> bool:
        return self.direction == AttendanceDirection.OUT
    
    @property
    def is_known_identity(self) -> bool:
        return self.identity_certainty == IdentityCertainty.KNOWN
    
    @property
    def is_unknown_identity(self) -> bool:
        return self.identity_certainty == IdentityCertainty.UNKNOWN
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "attendance_record_id": self.attendance_record_id,
            "identity_certainty": self.identity_certainty.value,
            "identity_candidate": self.identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_evidence_ref": self.identity_evidence_ref,
            # NEW: Evidence fields
            "face_evidence_ref": self.face_evidence_ref,
            "body_evidence_ref": self.body_evidence_ref,
            "face_quality": self.face_quality,
            "body_quality": self.body_quality,
            "association_method": self.association_method,
            "conflict_flag": self.conflict_flag,
            "provisional_person_id": self.provisional_person_id,
            "identity_state": self.identity_state,
            # Phase 17: Evidence storage URIs
            "snapshot_face_url": self.snapshot_face_url,
            "snapshot_scene_url": self.snapshot_scene_url,
            "video_clip_url": self.video_clip_url,
            "direction": self.direction.value,
            "event_timestamp": self.event_timestamp,
            "event_frame_index": self.event_frame_index,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "source_raw_event_id": self.source_raw_event_id,
            "source_resolution_id": self.source_resolution_id,
            "source_crossing_event_id": self.source_crossing_event_id,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
            "resolver_version": self.resolver_version,
            "resolver_config_hash": self.resolver_config_hash,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            # NEW: Metadata fields
            "stream_epoch": self.stream_epoch,
            "pts": self.pts,
            "time_base_num": self.time_base.numerator,
            "time_base_den": self.time_base.denominator,
            "capture_timestamp": self.capture_timestamp,
            "processing_timestamp": self.processing_timestamp,
            "model_version": self.model_version,
            "enrollment_version": self.enrollment_version,
            "attendance_schema_version": self.attendance_schema_version,
            "created_at": self.created_at,
            "persisted_at": self.persisted_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttendanceRecord":
        """Deserialize from dictionary."""
        # Handle time_base
        time_base = Fraction(1, 90000)
        if "time_base_num" in data and "time_base_den" in data:
            time_base = Fraction(data["time_base_num"], data["time_base_den"])
        
        return cls(
            attendance_record_id=data["attendance_record_id"],
            identity_certainty=IdentityCertainty(data.get("identity_certainty", "unknown")),
            identity_candidate=data.get("identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_evidence_ref=data.get("identity_evidence_ref"),
            # NEW: Evidence fields
            face_evidence_ref=data.get("face_evidence_ref"),
            body_evidence_ref=data.get("body_evidence_ref"),
            face_quality=data.get("face_quality", 0.0),
            body_quality=data.get("body_quality", 0.0),
            association_method=data.get("association_method", ""),
            conflict_flag=data.get("conflict_flag", False),
            provisional_person_id=data.get("provisional_person_id"),
            identity_state=data.get("identity_state", "unknown"),
            # Phase 17: Evidence storage URIs
            snapshot_face_url=data.get("snapshot_face_url"),
            snapshot_scene_url=data.get("snapshot_scene_url"),
            video_clip_url=data.get("video_clip_url"),
            direction=AttendanceDirection(data["direction"]),
            event_timestamp=data["event_timestamp"],
            event_frame_index=data.get("event_frame_index", -1),
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            source_raw_event_id=data["source_raw_event_id"],
            source_resolution_id=data["source_resolution_id"],
            source_crossing_event_id=data.get("source_crossing_event_id"),
            geometry_version=data.get("geometry_version", 0),
            geometry_config_hash=data.get("geometry_config_hash", ""),
            resolver_version=data.get("resolver_version", "1.0"),
            resolver_config_hash=data.get("resolver_config_hash", ""),
            previous_state=data.get("previous_state", "unknown"),
            new_state=data.get("new_state", "unknown"),
            # NEW: Metadata fields
            stream_epoch=data.get("stream_epoch", 0),
            pts=data.get("pts", 0),
            time_base=time_base,
            capture_timestamp=data.get("capture_timestamp", 0.0),
            processing_timestamp=data.get("processing_timestamp", 0.0),
            model_version=data.get("model_version", ""),
            enrollment_version=data.get("enrollment_version", ""),
            attendance_schema_version=data.get("attendance_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            persisted_at=data.get("persisted_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "AttendanceRecord":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class AttendanceRecordCreationResult:
    """Result of attempting to create an AttendanceRecord from a ResolvedTransition."""
    success: bool
    record: Optional[AttendanceRecord] = None
    error: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    @classmethod
    def success_result(cls, record: AttendanceRecord) -> "AttendanceRecordCreationResult":
        return cls(success=True, record=record)
    
    @classmethod
    def failure_result(cls, error: str, rejection_reason: Optional[str] = None) -> "AttendanceRecordCreationResult":
        return cls(success=False, error=error, rejection_reason=rejection_reason)


def generate_attendance_record_id(
    source_resolution_id: str,
    attendance_schema_version: str = "1.0",
) -> str:
    """
    Generate a stable, deterministic attendance record ID.
    
    Uses the source resolution ID as the primary stable identifier.
    Same source_resolution_id MUST produce the same attendance_record_id.
    """
    content = f"ATT:{source_resolution_id}:v{attendance_schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"ATT-{hash_suffix}"


def create_attendance_record_from_resolution(
    resolution: "ResolvedTransition",  # Forward reference to avoid circular import
) -> AttendanceRecordCreationResult:
    """
    Create an AttendanceRecord from a Phase 24 ResolvedTransition.
    
    Only creates a record for actual transitions (not suppressed/rejected events).
    Preserves full provenance chain.
    
    Args:
        resolution: ResolvedTransition from Phase 24 resolver
        
    Returns:
        AttendanceRecordCreationResult with the created record or error
    """
    # Only persist actual transitions (not suppressed/rejected)
    if not resolution.is_transition:
        transition_type_str = resolution.transition_type.value if hasattr(resolution.transition_type, 'value') else str(resolution.transition_type)
        return AttendanceRecordCreationResult.failure_result(
            error=f"Resolution {resolution.resolution_id} is not a transition (type: {transition_type_str})",
            rejection_reason="not_a_transition"
        )
    
    # Validate required fields
    if not resolution.resolution_id:
        return AttendanceRecordCreationResult.failure_result(
            error="Resolution missing resolution_id",
            rejection_reason="invalid_resolution"
        )
    if not resolution.source_raw_event_id:
        return AttendanceRecordCreationResult.failure_result(
            error="Resolution missing source_raw_event_id",
            rejection_reason="invalid_resolution"
        )
    if not resolution.camera_id:
        return AttendanceRecordCreationResult.failure_result(
            error="Resolution missing camera_id",
            rejection_reason="invalid_resolution"
        )
    if not resolution.local_track_id:
        return AttendanceRecordCreationResult.failure_result(
            error="Resolution missing local_track_id",
            rejection_reason="invalid_resolution"
        )
    if resolution.direction not in ("in", "out"):
        return AttendanceRecordCreationResult.failure_result(
            error=f"Invalid direction: {resolution.direction}",
            rejection_reason="invalid_resolution"
        )
    if resolution.source_timestamp < 0:
        return AttendanceRecordCreationResult.failure_result(
            error=f"Invalid source_timestamp: {resolution.source_timestamp}",
            rejection_reason="invalid_resolution"
        )
    
    # Map direction
    direction = AttendanceDirection.IN if resolution.direction == "in" else AttendanceDirection.OUT
    
    # Map derived states
    previous_state = resolution.previous_state.value if hasattr(resolution.previous_state, 'value') else resolution.previous_state
    new_state = resolution.new_state.value if hasattr(resolution.new_state, 'value') else resolution.new_state
    
    # Generate deterministic attendance record ID
    attendance_record_id = generate_attendance_record_id(
        source_resolution_id=resolution.resolution_id,
        attendance_schema_version="1.1",
    )
    
    # Extract identity info from resolution (now properly propagated)
    identity_certainty = resolution.identity_certainty
    identity_candidate = resolution.identity_candidate
    identity_confidence = resolution.identity_confidence
    identity_evidence_ref = resolution.identity_evidence_ref
    
    # NEW: Extract GIS evidence fields
    face_evidence_ref = getattr(resolution, 'face_evidence_ref', None)
    body_evidence_ref = getattr(resolution, 'body_evidence_ref', None)
    face_quality = getattr(resolution, 'face_quality', 0.0)
    body_quality = getattr(resolution, 'body_quality', 0.0)
    association_method = getattr(resolution, 'association_method', "")
    conflict_flag = getattr(resolution, 'conflict_flag', False)
    provisional_person_id = getattr(resolution, 'provisional_person_id', None)
    identity_state = getattr(resolution, 'identity_state', "unknown")
    
    # Create the attendance record
    record = AttendanceRecord(
        attendance_record_id=attendance_record_id,
        identity_certainty=identity_certainty,
        identity_candidate=identity_candidate,
        identity_confidence=identity_confidence,
        identity_evidence_ref=identity_evidence_ref,
        # NEW: GIS evidence fields
        face_evidence_ref=face_evidence_ref,
        body_evidence_ref=body_evidence_ref,
        face_quality=face_quality,
        body_quality=body_quality,
        association_method=association_method,
        conflict_flag=conflict_flag,
        provisional_person_id=provisional_person_id,
        identity_state=identity_state,
        direction=direction,
        event_timestamp=resolution.source_timestamp,
        event_frame_index=resolution.source_frame_index,
        camera_id=resolution.camera_id,
        local_track_id=resolution.local_track_id,
        global_observation_id=resolution.global_observation_id,
        source_raw_event_id=resolution.source_raw_event_id,
        source_resolution_id=resolution.resolution_id,
        source_crossing_event_id=resolution.source_crossing_event_id,
        geometry_version=resolution.geometry_version,
        geometry_config_hash=resolution.geometry_config_hash,
        resolver_version=resolution.resolver_version,
        resolver_config_hash=resolution.resolver_config_hash,
        previous_state=previous_state,
        new_state=new_state,
        attendance_schema_version="1.1",
        # NEW: Metadata fields
        stream_epoch=getattr(resolution, 'stream_epoch', 0),
        pts=getattr(resolution, 'pts', 0),
        time_base=getattr(resolution, 'time_base', Fraction(1, 90000)),
        capture_timestamp=getattr(resolution, 'capture_timestamp', 0.0),
        processing_timestamp=getattr(resolution, 'processing_timestamp', 0.0),
        model_version=getattr(resolution, 'model_version', ""),
        enrollment_version=getattr(resolution, 'enrollment_version', ""),
        # Phase 17: Evidence storage URIs (will be populated after snapshot/clip extraction)
        snapshot_face_url=None,
        snapshot_scene_url=None,
        video_clip_url=None,
    )
    
    return AttendanceRecordCreationResult.success_result(record)


def validate_attendance_record(record: AttendanceRecord) -> Optional[str]:
    """
    Validate an AttendanceRecord for persistence.
    
    Returns None if valid, error message if invalid.
    """
    if not record.attendance_record_id:
        return "attendance_record_id is required"
    if not record.source_raw_event_id:
        return "source_raw_event_id is required"
    if not record.source_resolution_id:
        return "source_resolution_id is required"
    if not record.camera_id:
        return "camera_id is required"
    if not record.local_track_id:
        return "local_track_id is required"
    if record.direction not in (AttendanceDirection.IN, AttendanceDirection.OUT):
        return f"direction must be 'in' or 'out', got {record.direction}"
    if record.event_timestamp < 0:
        return "event_timestamp must be >= 0"
    if record.attendance_schema_version not in ("1.0", "1.1"):
        return f"Unsupported attendance_schema_version: {record.attendance_schema_version}"
    if record.identity_certainty not in IdentityCertainty:
        return f"Invalid identity_certainty: {record.identity_certainty}"
    if record.previous_state not in ("unknown", "inside", "outside"):
        return f"Invalid previous_state: {record.previous_state}"
    if record.new_state not in ("unknown", "inside", "outside"):
        return f"Invalid new_state: {record.new_state}"
    if record.geometry_version < 0:
        return "geometry_version must be >= 0"
    return None