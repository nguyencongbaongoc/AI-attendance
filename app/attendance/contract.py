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
    identity_evidence_ref: Optional[str] = None  # Reference to GlobalObservation/IdentityEvidence
    
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
    
    # Versioning
    attendance_schema_version: str = "1.0"
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
        if self.attendance_schema_version != "1.0":
            raise ValueError(f"Unsupported attendance_schema_version: {self.attendance_schema_version}")
        if self.identity_certainty not in IdentityCertainty:
            raise ValueError(f"Invalid identity_certainty: {self.identity_certainty}")
        if self.previous_state not in ("unknown", "inside", "outside"):
            raise ValueError(f"Invalid previous_state: {self.previous_state}")
        if self.new_state not in ("unknown", "inside", "outside"):
            raise ValueError(f"Invalid new_state: {self.new_state}")
    
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
            "attendance_schema_version": self.attendance_schema_version,
            "created_at": self.created_at,
            "persisted_at": self.persisted_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttendanceRecord":
        """Deserialize from dictionary."""
        return cls(
            attendance_record_id=data["attendance_record_id"],
            identity_certainty=IdentityCertainty(data.get("identity_certainty", "unknown")),
            identity_candidate=data.get("identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_evidence_ref=data.get("identity_evidence_ref"),
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
        attendance_schema_version="1.0",
    )
    
    # Extract identity info from resolution (preserved from raw event)
    # The resolution carries global_observation_id which links to identity evidence
    identity_certainty = IdentityCertainty.UNKNOWN
    identity_candidate = None
    identity_confidence = 0.0
    identity_evidence_ref = resolution.global_observation_id
    
    # Create the attendance record
    record = AttendanceRecord(
        attendance_record_id=attendance_record_id,
        identity_certainty=identity_certainty,
        identity_candidate=identity_candidate,
        identity_confidence=identity_confidence,
        identity_evidence_ref=identity_evidence_ref,
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
        attendance_schema_version="1.0",
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
    if record.attendance_schema_version != "1.0":
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