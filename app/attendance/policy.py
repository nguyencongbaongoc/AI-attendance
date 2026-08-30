"""
Phase 26 — Attendance Policy Contract.

Configurable policy for attendance decision making.
Defines business rules for IN/OUT semantics, identity handling, and session finalization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DecisionReason(str, Enum):
    """Reason codes for attendance decisions."""
    WITHIN_ENTRY_WINDOW = "within_entry_window"
    LATE_WITHIN_TOLERANCE = "late_within_tolerance"
    EXIT_RECORDED = "exit_recorded"
    UNKNOWN_IDENTITY = "unknown_identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    OUTSIDE_ATTENDANCE_WINDOW = "outside_attendance_window"
    SESSION_FINALIZED = "session_finalized"
    NO_ENTRY_EVENT = "no_entry_event"
    NO_EXIT_EVENT = "no_exit_event"
    INVALID_TIMETABLE = "invalid_timetable"
    INVALID_POLICY = "invalid_policy"
    DUPLICATE_RESOLUTION = "duplicate_resolution"


class IdentityHandlingPolicy(str, Enum):
    """Policy for handling unknown/ambiguous identities."""
    UNRESOLVED = "unresolved"  # Do not create attendance record
    UNKNOWN_PERSON = "unknown_person"  # Create record with unknown identity
    PENDING_REVIEW = "pending_review"  # Create record for manual review


class DuplicateDecisionPolicy(str, Enum):
    """Policy for handling duplicate resolutions."""
    IGNORE = "ignore"  # Ignore duplicate decisions
    OVERRIDE = "override"  # Override previous decision
    WARN = "warn"  # Log warning but keep first decision


class SessionFinalizationPolicy(str, Enum):
    """Policy for session finalization."""
    EVENT_BASED = "event_based"  # Finalize when exit event recorded
    TIME_BASED = "time_based"  # Finalize based on exit time window
    MANUAL = "manual"  # Requires manual finalization


@dataclass(frozen=True)
class AttendancePolicy:
    """
    Configurable attendance policy.
    
    Defines business rules for attendance decision making.
    All values are explicit, serializable, and deterministic.
    """
    # Policy identification
    policy_id: str
    
    # Versioning
    policy_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Identity handling
    unknown_identity_policy: IdentityHandlingPolicy = IdentityHandlingPolicy.UNRESOLVED
    ambiguous_identity_policy: IdentityHandlingPolicy = IdentityHandlingPolicy.PENDING_REVIEW
    
    # Duplicate decision handling
    duplicate_decision_policy: DuplicateDecisionPolicy = DuplicateDecisionPolicy.IGNORE
    
    # Session finalization
    session_finalization_policy: SessionFinalizationPolicy = SessionFinalizationPolicy.EVENT_BASED
    
    # Default values (used when timetable doesn't specify)
    default_entry_window_seconds: int = 300  # 5 minutes
    default_late_tolerance_seconds: int = 600  # 10 minutes
    default_exit_window_seconds: int = 300  # 5 minutes
    
    # Provenance
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.policy_id:
            raise ValueError("policy_id is required")
        if self.policy_version != "1.0":
            raise ValueError(f"Unsupported policy_version: {self.policy_version}")
        if self.default_entry_window_seconds < 0:
            raise ValueError("default_entry_window_seconds must be >= 0")
        if self.default_late_tolerance_seconds < 0:
            raise ValueError("default_late_tolerance_seconds must be >= 0")
        if self.default_exit_window_seconds < 0:
            raise ValueError("default_exit_window_seconds must be >= 0")
        if self.geometry_version < 0:
            raise ValueError("geometry_version must be >= 0")
    
    @property
    def entry_window_seconds(self) -> int:
        """Entry window in seconds."""
        return self.default_entry_window_seconds
    
    @property
    def late_tolerance_seconds(self) -> int:
        """Late tolerance in seconds."""
        return self.default_late_tolerance_seconds
    
    @property
    def exit_window_seconds(self) -> int:
        """Exit window in seconds."""
        return self.default_exit_window_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "unknown_identity_policy": self.unknown_identity_policy.value,
            "ambiguous_identity_policy": self.ambiguous_identity_policy.value,
            "duplicate_decision_policy": self.duplicate_decision_policy.value,
            "session_finalization_policy": self.session_finalization_policy.value,
            "default_entry_window_seconds": self.default_entry_window_seconds,
            "default_late_tolerance_seconds": self.default_late_tolerance_seconds,
            "default_exit_window_seconds": self.default_exit_window_seconds,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttendancePolicy":
        """Deserialize from dictionary."""
        return cls(
            policy_id=data["policy_id"],
            policy_version=data.get("policy_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z"),
            unknown_identity_policy=IdentityHandlingPolicy(data.get("unknown_identity_policy", "unresolved")),
            ambiguous_identity_policy=IdentityHandlingPolicy(data.get("ambiguous_identity_policy", "pending_review")),
            duplicate_decision_policy=DuplicateDecisionPolicy(data.get("duplicate_decision_policy", "ignore")),
            session_finalization_policy=SessionFinalizationPolicy(data.get("session_finalization_policy", "event_based")),
            default_entry_window_seconds=data.get("default_entry_window_seconds", 300),
            default_late_tolerance_seconds=data.get("default_late_tolerance_seconds", 600),
            default_exit_window_seconds=data.get("default_exit_window_seconds", 300),
            geometry_version=data.get("geometry_version", 0),
            geometry_config_hash=data.get("geometry_config_hash", ""),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "AttendancePolicy":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class AttendanceDecision:
    """
    Immutable attendance decision.
    
    Represents the result of applying attendance policy to a ResolvedTransition.
    Preserves full provenance for forensic reproducibility.
    """
    # Decision identification
    decision_id: str
    
    # Identity reference
    identity_certainty: str = "unknown"
    identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_evidence_ref: Optional[str] = None
    
    # Event details
    direction: str = ""  # "in" or "out"
    event_timestamp: float = 0.0
    event_frame_index: int = -1
    
    # Camera and track provenance
    camera_id: str = ""
    local_track_id: str = ""
    global_observation_id: Optional[str] = None
    
    # Source references (provenance chain)
    source_raw_event_id: str = ""
    source_resolution_id: str = ""
    source_crossing_event_id: Optional[str] = None
    
    # Geometry provenance
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    # Resolver provenance
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    
    # Timetable reference
    timetable_id: str = ""
    timetable_version: str = "1.0"
    session_id: Optional[str] = None
    day: Optional[str] = None
    
    # Attendance state
    previous_attendance_state: str = "unknown"
    new_attendance_state: str = "unknown"
    
    # Decision reason
    decision_reason: str = "within_entry_window"
    
    # Policy reference
    attendance_policy_id: str = ""
    attendance_policy_version: str = "1.0"
    
    # Versioning
    decision_schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if not self.source_raw_event_id:
            raise ValueError("source_raw_event_id is required")
        if not self.source_resolution_id:
            raise ValueError("source_resolution_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
        if self.direction not in ("in", "out"):
            raise ValueError(f"direction must be 'in' or 'out', got {self.direction}")
        if self.event_timestamp < 0:
            raise ValueError("event_timestamp must be >= 0")
        if self.decision_schema_version != "1.0":
            raise ValueError(f"Unsupported decision_schema_version: {self.decision_schema_version}")
        if self.previous_attendance_state not in ("unknown", "expected", "present", "late", "left", "absent"):
            raise ValueError(f"Invalid previous_attendance_state: {self.previous_attendance_state}")
        if self.new_attendance_state not in ("unknown", "expected", "present", "late", "left", "absent"):
            raise ValueError(f"Invalid new_attendance_state: {self.new_attendance_state}")
        if self.decision_reason not in [r.value for r in DecisionReason]:
            raise ValueError(f"Invalid decision_reason: {self.decision_reason}")
    
    @property
    def is_in(self) -> bool:
        return self.direction == "in"
    
    @property
    def is_out(self) -> bool:
        return self.direction == "out"
    
    @property
    def is_known_identity(self) -> bool:
        return self.identity_certainty == "known"
    
    @property
    def is_unknown_identity(self) -> bool:
        return self.identity_certainty == "unknown"
    
    @property
    def is_ambiguous_identity(self) -> bool:
        return self.identity_certainty == "ambiguous"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "decision_id": self.decision_id,
            "identity_certainty": self.identity_certainty,
            "identity_candidate": self.identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_evidence_ref": self.identity_evidence_ref,
            "direction": self.direction,
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
            "timetable_id": self.timetable_id,
            "timetable_version": self.timetable_version,
            "session_id": self.session_id,
            "day": self.day,
            "previous_attendance_state": self.previous_attendance_state,
            "new_attendance_state": self.new_attendance_state,
            "decision_reason": self.decision_reason,
            "attendance_policy_id": self.attendance_policy_id,
            "attendance_policy_version": self.attendance_policy_version,
            "decision_schema_version": self.decision_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AttendanceDecision":
        """Deserialize from dictionary."""
        return cls(
            decision_id=data["decision_id"],
            identity_certainty=data.get("identity_certainty", "unknown"),
            identity_candidate=data.get("identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_evidence_ref=data.get("identity_evidence_ref"),
            direction=data["direction"],
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
            timetable_id=data.get("timetable_id", ""),
            timetable_version=data.get("timetable_version", "1.0"),
            session_id=data.get("session_id"),
            day=data.get("day"),
            previous_attendance_state=data.get("previous_attendance_state", "unknown"),
            new_attendance_state=data.get("new_attendance_state", "unknown"),
            decision_reason=data.get("decision_reason", ""),
            attendance_policy_id=data.get("attendance_policy_id", ""),
            attendance_policy_version=data.get("attendance_policy_version", "1.0"),
            decision_schema_version=data.get("decision_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "AttendanceDecision":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


def generate_decision_id(
    source_resolution_id: str,
    decision_schema_version: str = "1.0",
) -> str:
    """
    Generate a stable, deterministic decision ID.
    
    Args:
        source_resolution_id: Phase 24 resolution ID
        decision_schema_version: Schema version
        
    Returns:
        Decision ID string
    """
    import hashlib
    content = f"DEC:{source_resolution_id}:v{decision_schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"DEC-{source_resolution_id}-v{decision_schema_version}-{hash_suffix}"


def validate_attendance_decision(decision: AttendanceDecision) -> Optional[str]:
    """
    Validate an AttendanceDecision.
    
    Args:
        decision: AttendanceDecision to validate
        
    Returns:
        None if valid, error message if invalid
    """
    if not decision.decision_id:
        return "decision_id is required"
    if not decision.source_raw_event_id:
        return "source_raw_event_id is required"
    if not decision.source_resolution_id:
        return "source_resolution_id is required"
    if not decision.camera_id:
        return "camera_id is required"
    if not decision.local_track_id:
        return "local_track_id is required"
    if decision.direction not in ("in", "out"):
        return f"direction must be 'in' or 'out', got {decision.direction}"
    if decision.event_timestamp < 0:
        return "event_timestamp must be >= 0"
    if decision.decision_schema_version != "1.0":
        return f"Unsupported decision_schema_version: {decision.decision_schema_version}"
    if decision.previous_attendance_state not in ("unknown", "expected", "present", "late", "left", "absent"):
        return f"Invalid previous_attendance_state: {decision.previous_attendance_state}"
    if decision.new_attendance_state not in ("unknown", "expected", "present", "late", "left", "absent"):
        return f"Invalid new_attendance_state: {decision.new_attendance_state}"
    if decision.decision_reason not in [r.value for r in DecisionReason]:
        return f"Invalid decision_reason: {decision.decision_reason}"
    return None