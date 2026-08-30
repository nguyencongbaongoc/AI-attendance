"""
Phase 29 — Immediate Event Output Contract.

Canonical immediate-event delivery contract that exposes new attendance/IN/OUT events
to the UI and downstream consumers without changing existing event-generation
or attendance logic.

Preserves full provenance chain: source video -> camera -> frame -> timestamp -> track ->
global observation -> crossing event -> raw event -> resolution -> attendance decision -> immediate output
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ImmediateEventType(str, Enum):
    """Type of immediate event based on upstream source."""
    ATTENDANCE_IN = "attendance_in"      # From Phase 26 AttendanceDecision (IN)
    ATTENDANCE_OUT = "attendance_out"    # From Phase 26 AttendanceDecision (OUT)
    RESOLUTION_IN = "resolution_in"      # From Phase 24 ResolvedTransition (IN transition)
    RESOLUTION_OUT = "resolution_out"    # From Phase 24 ResolvedTransition (OUT transition)
    RAW_IN = "raw_in"                    # From Phase 23 RawInOutEvent (IN)
    RAW_OUT = "raw_out"                  # From Phase 23 RawInOutEvent (OUT)


class ImmediateEventDirection(str, Enum):
    """Event direction."""
    IN = "in"
    OUT = "out"


class IdentityCertainty(str, Enum):
    """Identity certainty level preserved from upstream."""
    KNOWN = "known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


class EventDeliveryStatus(str, Enum):
    """Delivery status of the immediate event."""
    NEW = "new"                    # Newly emitted event
    HISTORICAL = "historical"      # Historical event from persistence
    DUPLICATE = "duplicate"        # Duplicate of already emitted event
    INVALID = "invalid"            # Invalid event (should not be delivered)


@dataclass(frozen=True)
class ImmediateEvent:
    """
    Canonical immediate event for real-time delivery.
    
    Preserves full provenance chain for forensic reproducibility.
    Immutable after creation.
    
    This is the OUTPUT layer - it does NOT recompute:
    - identity
    - crossing
    - IN/OUT
    - repeated-event resolution
    - attendance state
    - attendance persistence
    
    It ONLY exposes already-derived events from Phase 24/26.
    """
    # Event identification (stable, deterministic)
    event_id: str
    
    # Event classification
    event_type: ImmediateEventType
    direction: ImmediateEventDirection
    
    # Identity reference (preserved from upstream)
    identity_certainty: IdentityCertainty = IdentityCertainty.UNKNOWN
    identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_evidence_ref: Optional[str] = None  # Reference to GlobalObservation/IdentityEvidence
    
    # Event details
    event_timestamp: float = 0.0  # Upstream event timestamp (NOT delivery time)
    event_frame_index: int = -1
    
    # Camera and track provenance
    camera_id: str = ""
    local_track_id: str = ""
    global_observation_id: Optional[str] = None
    
    # Source references (provenance chain)
    source_raw_event_id: str = ""           # Phase 23 RawInOutEvent ID
    source_resolution_id: str = ""          # Phase 24 ResolvedTransition ID
    source_crossing_event_id: Optional[str] = None  # Phase 22 CrossingEvent ID
    source_attendance_decision_id: Optional[str] = None  # Phase 26 AttendanceDecision ID
    source_attendance_record_id: Optional[str] = None  # Phase 25 AttendanceRecord ID
    
    # Geometry provenance
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    # Resolver provenance
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    
    # Attendance provenance (from Phase 26)
    attendance_policy_id: Optional[str] = None
    attendance_policy_version: Optional[str] = None
    previous_attendance_state: Optional[str] = None
    new_attendance_state: Optional[str] = None
    decision_reason: Optional[str] = None
    
    # Timetable reference (from Phase 26)
    timetable_id: Optional[str] = None
    timetable_version: Optional[str] = None
    session_id: Optional[str] = None
    day: Optional[str] = None
    
    # Delivery metadata
    delivery_status: EventDeliveryStatus = EventDeliveryStatus.NEW
    delivery_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    delivery_sequence: int = 0  # Monotonic sequence for ordering
    
    # Full provenance chain (optional, for debugging)
    trajectory_points: List[Dict[str, Any]] = field(default_factory=list)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    # Versioning
    event_schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
        if not self.source_raw_event_id:
            raise ValueError("source_raw_event_id is required")
        if not self.source_resolution_id:
            raise ValueError("source_resolution_id is required")
        if self.direction not in (ImmediateEventDirection.IN, ImmediateEventDirection.OUT):
            raise ValueError(f"direction must be IN or OUT, got {self.direction}")
        if self.event_timestamp < 0:
            raise ValueError("event_timestamp must be >= 0")
        if self.event_schema_version != "1.0":
            raise ValueError(f"Unsupported event_schema_version: {self.event_schema_version}")
        if not isinstance(self.identity_certainty, IdentityCertainty):
            raise ValueError(f"Invalid identity_certainty: {self.identity_certainty}")
        if not isinstance(self.delivery_status, EventDeliveryStatus):
            raise ValueError(f"Invalid delivery_status: {self.delivery_status}")
    
    @property
    def is_in(self) -> bool:
        return self.direction == ImmediateEventDirection.IN
    
    @property
    def is_out(self) -> bool:
        return self.direction == ImmediateEventDirection.OUT
    
    @property
    def is_known_identity(self) -> bool:
        return self.identity_certainty == IdentityCertainty.KNOWN
    
    @property
    def is_unknown_identity(self) -> bool:
        return self.identity_certainty == IdentityCertainty.UNKNOWN
    
    @property
    def is_ambiguous_identity(self) -> bool:
        return self.identity_certainty == IdentityCertainty.AMBIGUOUS
    
    @property
    def is_attendance_event(self) -> bool:
        """Whether this event originated from Phase 26 attendance decision."""
        return self.event_type in (ImmediateEventType.ATTENDANCE_IN, ImmediateEventType.ATTENDANCE_OUT)
    
    @property
    def is_resolution_event(self) -> bool:
        """Whether this event originated from Phase 24 resolution."""
        return self.event_type in (ImmediateEventType.RESOLUTION_IN, ImmediateEventType.RESOLUTION_OUT)
    
    @property
    def is_raw_event(self) -> bool:
        """Whether this event originated from Phase 23 raw event."""
        return self.event_type in (ImmediateEventType.RAW_IN, ImmediateEventType.RAW_OUT)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "direction": self.direction.value,
            "identity_certainty": self.identity_certainty.value,
            "identity_candidate": self.identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_evidence_ref": self.identity_evidence_ref,
            "event_timestamp": self.event_timestamp,
            "event_frame_index": self.event_frame_index,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "source_raw_event_id": self.source_raw_event_id,
            "source_resolution_id": self.source_resolution_id,
            "source_crossing_event_id": self.source_crossing_event_id,
            "source_attendance_decision_id": self.source_attendance_decision_id,
            "source_attendance_record_id": self.source_attendance_record_id,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
            "resolver_version": self.resolver_version,
            "resolver_config_hash": self.resolver_config_hash,
            "attendance_policy_id": self.attendance_policy_id,
            "attendance_policy_version": self.attendance_policy_version,
            "previous_attendance_state": self.previous_attendance_state,
            "new_attendance_state": self.new_attendance_state,
            "decision_reason": self.decision_reason,
            "timetable_id": self.timetable_id,
            "timetable_version": self.timetable_version,
            "session_id": self.session_id,
            "day": self.day,
            "delivery_status": self.delivery_status.value,
            "delivery_timestamp": self.delivery_timestamp,
            "delivery_sequence": self.delivery_sequence,
            "trajectory_points": self.trajectory_points,
            "config_snapshot": self.config_snapshot,
            "event_schema_version": self.event_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImmediateEvent":
        """Deserialize from dictionary."""
        # Handle enum fields that may be strings
        identity_certainty = data.get("identity_certainty", "unknown")
        if isinstance(identity_certainty, str):
            identity_certainty = IdentityCertainty(identity_certainty)
        
        delivery_status = data.get("delivery_status", "new")
        if isinstance(delivery_status, str):
            delivery_status = EventDeliveryStatus(delivery_status)
        
        event_type = data["event_type"]
        if isinstance(event_type, str):
            event_type = ImmediateEventType(event_type)
        
        direction = data["direction"]
        if isinstance(direction, str):
            direction = ImmediateEventDirection(direction)
        
        return cls(
            event_id=data["event_id"],
            event_type=event_type,
            direction=direction,
            identity_certainty=identity_certainty,
            identity_candidate=data.get("identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_evidence_ref=data.get("identity_evidence_ref"),
            event_timestamp=data["event_timestamp"],
            event_frame_index=data.get("event_frame_index", -1),
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            source_raw_event_id=data["source_raw_event_id"],
            source_resolution_id=data["source_resolution_id"],
            source_crossing_event_id=data.get("source_crossing_event_id"),
            source_attendance_decision_id=data.get("source_attendance_decision_id"),
            source_attendance_record_id=data.get("source_attendance_record_id"),
            geometry_version=data.get("geometry_version", 0),
            geometry_config_hash=data.get("geometry_config_hash", ""),
            resolver_version=data.get("resolver_version", "1.0"),
            resolver_config_hash=data.get("resolver_config_hash", ""),
            attendance_policy_id=data.get("attendance_policy_id"),
            attendance_policy_version=data.get("attendance_policy_version"),
            previous_attendance_state=data.get("previous_attendance_state"),
            new_attendance_state=data.get("new_attendance_state"),
            decision_reason=data.get("decision_reason"),
            timetable_id=data.get("timetable_id"),
            timetable_version=data.get("timetable_version"),
            session_id=data.get("session_id"),
            day=data.get("day"),
            delivery_status=delivery_status,
            delivery_timestamp=data.get("delivery_timestamp", datetime.utcnow().isoformat() + "Z"),
            delivery_sequence=data.get("delivery_sequence", 0),
            trajectory_points=data.get("trajectory_points", []),
            config_snapshot=data.get("config_snapshot", {}),
            event_schema_version=data.get("event_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ImmediateEvent":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class ImmediateEventCreationResult:
    """Result of attempting to create an ImmediateEvent."""
    success: bool
    event: Optional[ImmediateEvent] = None
    error: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    @classmethod
    def success_result(cls, event: ImmediateEvent) -> "ImmediateEventCreationResult":
        return cls(success=True, event=event)
    
    @classmethod
    def failure_result(cls, error: str, rejection_reason: Optional[str] = None) -> "ImmediateEventCreationResult":
        return cls(success=False, error=error, rejection_reason=rejection_reason)


def generate_immediate_event_id(
    source_resolution_id: str,
    event_type: ImmediateEventType,
    event_schema_version: str = "1.0",
) -> str:
    """
    Generate a stable, deterministic immediate event ID.
    
    Uses the source resolution ID as the primary stable identifier.
    Same source_resolution_id + event_type MUST produce the same event_id.
    
    This ensures idempotency: repeated input produces the same output ID.
    """
    content = f"IEV:{source_resolution_id}:{event_type.value}:v{event_schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"IEV-{hash_suffix}"


def validate_immediate_event(event: ImmediateEvent) -> Optional[str]:
    """
    Validate an ImmediateEvent for delivery.
    
    Returns None if valid, error message if invalid.
    """
    if not event.event_id:
        return "event_id is required"
    if not event.camera_id:
        return "camera_id is required"
    if not event.local_track_id:
        return "local_track_id is required"
    if not event.source_raw_event_id:
        return "source_raw_event_id is required"
    if not event.source_resolution_id:
        return "source_resolution_id is required"
    if event.direction not in (ImmediateEventDirection.IN, ImmediateEventDirection.OUT):
        return f"direction must be 'in' or 'out', got {event.direction}"
    if event.event_timestamp < 0:
        return "event_timestamp must be >= 0"
    if event.event_schema_version != "1.0":
        return f"Unsupported event_schema_version: {event.event_schema_version}"
    if event.identity_certainty not in IdentityCertainty:
        return f"Invalid identity_certainty: {event.identity_certainty}"
    if event.delivery_status not in EventDeliveryStatus:
        return f"Invalid delivery_status: {event.delivery_status}"
    if event.geometry_version < 0:
        return "geometry_version must be >= 0"
    return None