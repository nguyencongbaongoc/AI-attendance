"""
Phase 37B — Policy Event Contract.

Canonical policy event produced by the Attendance Policy Engine.
This is the single source of truth for policy decisions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class PolicyType(str, Enum):
    """Types of policy events."""
    MORNING_ABSENCE = "morning_absence"
    SHORT_EXIT = "short_exit"
    LONG_EXIT = "long_exit"
    MISSING_CHECKOUT = "missing_checkout"


class PolicyEventState(str, Enum):
    """State of the policy event."""
    NEW = "new"
    NOTIFICATION_QUEUED = "notification_queued"
    NOTIFICATION_SENT = "notification_sent"
    NOTIFICATION_FAILED = "notification_failed"
    DEDUPLICATED = "deduplicated"
    IGNORED = "ignored"


@dataclass(frozen=True)
class PolicyEvent:
    """
    Immutable canonical policy event.
    
    Represents a policy decision that may trigger parent notification.
    Preserves full provenance for forensic reproducibility.
    """
    # Event identification
    event_id: str
    
    # Student reference
    student_id: str
    
    # Policy details
    policy_type: PolicyType
    occurred_at: float  # Unix timestamp when the policy condition was met
    effective_at: float  # Unix timestamp when the policy takes effect (same as occurred_at for now)
    
    # Source evidence
    source_attendance_event_id: str  # AttendanceDecision.decision_id
    source_global_observation_id: Optional[str] = None
    
    # Evidence/provenance
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    # State
    state: PolicyEventState = PolicyEventState.NEW
    
    # Versioning
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    schema_version: str = "1.0"
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.student_id:
            raise ValueError("student_id is required")
        if self.policy_type not in PolicyType:
            raise ValueError(f"Invalid policy_type: {self.policy_type}")
        if self.occurred_at < 0:
            raise ValueError("occurred_at must be >= 0")
        if self.effective_at < 0:
            raise ValueError("effective_at must be >= 0")
        # source_attendance_event_id is optional for policies without source event (e.g., MORNING_ABSENCE, MISSING_CHECKOUT)
        if self.schema_version != "1.0":
            raise ValueError(f"Unsupported schema_version: {self.schema_version}")
    
    @property
    def is_notification_type(self) -> bool:
        """Whether this policy type should generate a parent notification."""
        return self.policy_type in (
            PolicyType.MORNING_ABSENCE,
            PolicyType.LONG_EXIT,
            PolicyType.MISSING_CHECKOUT,
        )
    
    @property
    def idempotency_key(self) -> str:
        """Generate idempotency key for deduplication."""
        # Format: YYYY-MM-DD:student_id:policy_type[:extra]
        from datetime import datetime
        dt = datetime.fromtimestamp(self.occurred_at)
        date_str = dt.strftime("%Y-%m-%d")
        
        if self.policy_type == PolicyType.LONG_EXIT:
            # Include OUT time for LONG_EXIT to distinguish multiple exits per day
            out_time = self.evidence.get("out_time", "")
            if out_time:
                return f"{date_str}:{self.student_id}:{self.policy_type.value}:{out_time}"
        return f"{date_str}:{self.student_id}:{self.policy_type.value}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "event_id": self.event_id,
            "student_id": self.student_id,
            "policy_type": self.policy_type.value,
            "occurred_at": self.occurred_at,
            "effective_at": self.effective_at,
            "source_attendance_event_id": self.source_attendance_event_id,
            "source_global_observation_id": self.source_global_observation_id,
            "evidence": self.evidence,
            "state": self.state.value,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyEvent":
        """Deserialize from dictionary."""
        return cls(
            event_id=data["event_id"],
            student_id=data["student_id"],
            policy_type=PolicyType(data["policy_type"]),
            occurred_at=data["occurred_at"],
            effective_at=data["effective_at"],
            source_attendance_event_id=data["source_attendance_event_id"],
            source_global_observation_id=data.get("source_global_observation_id"),
            evidence=data.get("evidence", {}),
            state=PolicyEventState(data.get("state", "new")),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            schema_version=data.get("schema_version", "1.0"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "PolicyEvent":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


def generate_policy_event_id(
    student_id: str,
    policy_type: PolicyType,
    occurred_at: float,
    source_attendance_event_id: str,
) -> str:
    """
    Generate a stable, deterministic policy event ID.
    
    Same inputs MUST produce the same event_id.
    """
    content = f"PEV:{student_id}:{policy_type.value}:{occurred_at}:{source_attendance_event_id}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"PEV-{hash_suffix}"


def validate_policy_event(event: PolicyEvent) -> Optional[str]:
    """
    Validate a PolicyEvent.
    
    Returns None if valid, error message if invalid.
    """
    if not event.event_id:
        return "event_id is required"
    if not event.student_id:
        return "student_id is required"
    if event.policy_type not in PolicyType:
        return f"Invalid policy_type: {event.policy_type}"
    if event.occurred_at < 0:
        return "occurred_at must be >= 0"
    if event.effective_at < 0:
        return "effective_at must be >= 0"
    if not event.source_attendance_event_id:
        return "source_attendance_event_id is required"
    if event.schema_version != "1.0":
        return f"Unsupported schema_version: {event.schema_version}"
    return None