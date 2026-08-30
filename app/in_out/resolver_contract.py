"""
Phase 24 — Repeated IN/OUT Resolver Contract.

Derived result types for the resolver state machine.
Immutable, serializable, preserves full provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class DerivedState(str, Enum):
    """Derived attendance state after resolution."""
    UNKNOWN = "unknown"
    INSIDE = "inside"
    OUTSIDE = "outside"


class TransitionType(str, Enum):
    """Type of derived transition."""
    IN = "in"           # Logical IN transition (UNKNOWN -> INSIDE, OUTSIDE -> INSIDE)
    OUT = "out"         # Logical OUT transition (INSIDE -> OUTSIDE)
    NONE = "none"       # No state change (repeated same-direction event)


class ResolutionStatus(str, Enum):
    """Status of resolution for a raw event."""
    ACCEPTED = "accepted"           # Event produced a derived transition
    SUPPRESSED = "suppressed"       # Event was repeated same-direction, no new transition
    REJECTED = "rejected"           # Event was rejected (e.g., initial OUT with REJECT policy)
    OUT_OF_ORDER = "out_of_order"   # Event was out of order (depends on policy)


@dataclass(frozen=True)
class ResolvedTransition:
    """
    Immutable derived transition result.
    
    Preserves full provenance to answer: "Which raw event caused this derived transition?"
    """
    # Resolution identification
    resolution_id: str
    
    # Source raw event reference (MUST be preserved)
    source_raw_event_id: str
    
    # Camera and track identification
    camera_id: str
    local_track_id: str
    global_observation_id: Optional[str] = None
    
    # Transition details
    direction: str = ""  # "in" or "out" from raw event
    transition_type: TransitionType = TransitionType.NONE
    previous_state: DerivedState = DerivedState.UNKNOWN
    new_state: DerivedState = DerivedState.UNKNOWN
    
    # Temporal details
    source_timestamp: float = 0.0
    source_frame_index: int = -1
    
    # Resolution metadata
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.ACCEPTED
    
    # Provenance
    source_crossing_event_id: Optional[str] = None
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    # Versioning
    resolution_schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        if not self.resolution_id:
            raise ValueError("resolution_id is required")
        if not self.source_raw_event_id:
            raise ValueError("source_raw_event_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
        if self.direction not in ("in", "out"):
            raise ValueError(f"direction must be 'in' or 'out', got {self.direction}")
        if self.source_timestamp < 0:
            raise ValueError("source_timestamp must be >= 0")
        if self.resolution_schema_version != "1.0":
            raise ValueError(f"Unsupported resolution_schema_version: {self.resolution_schema_version}")
    
    @property
    def is_transition(self) -> bool:
        """Whether this represents an actual state transition."""
        return self.transition_type != TransitionType.NONE
    
    @property
    def is_in_transition(self) -> bool:
        return self.transition_type == TransitionType.IN
    
    @property
    def is_out_transition(self) -> bool:
        return self.transition_type == TransitionType.OUT
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "resolution_id": self.resolution_id,
            "source_raw_event_id": self.source_raw_event_id,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "direction": self.direction,
            "transition_type": self.transition_type.value,
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "source_timestamp": self.source_timestamp,
            "source_frame_index": self.source_frame_index,
            "resolver_version": self.resolver_version,
            "resolver_config_hash": self.resolver_config_hash,
            "resolution_status": self.resolution_status.value,
            "source_crossing_event_id": self.source_crossing_event_id,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
            "resolution_schema_version": self.resolution_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolvedTransition":
        """Deserialize from dictionary."""
        return cls(
            resolution_id=data["resolution_id"],
            source_raw_event_id=data["source_raw_event_id"],
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            direction=data["direction"],
            transition_type=TransitionType(data.get("transition_type", "none")),
            previous_state=DerivedState(data.get("previous_state", "unknown")),
            new_state=DerivedState(data.get("new_state", "unknown")),
            source_timestamp=data["source_timestamp"],
            source_frame_index=data.get("source_frame_index", -1),
            resolver_version=data.get("resolver_version", "1.0"),
            resolver_config_hash=data.get("resolver_config_hash", ""),
            resolution_status=ResolutionStatus(data.get("resolution_status", "accepted")),
            source_crossing_event_id=data.get("source_crossing_event_id"),
            geometry_version=data.get("geometry_version", 0),
            geometry_config_hash=data.get("geometry_config_hash", ""),
            resolution_schema_version=data.get("resolution_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ResolvedTransition":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class TrackResolutionState:
    """
    Current derived state for a single track.
    
    This is the resolver's internal state - NOT the raw event history.
    """
    camera_id: str
    local_track_id: str
    current_state: DerivedState = DerivedState.UNKNOWN
    last_transition_timestamp: float = 0.0
    last_transition_resolution_id: Optional[str] = None
    last_processed_raw_event_id: Optional[str] = None
    transition_count: int = 0
    in_count: int = 0
    out_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "current_state": self.current_state.value,
            "last_transition_timestamp": self.last_transition_timestamp,
            "last_transition_resolution_id": self.last_transition_resolution_id,
            "last_processed_raw_event_id": self.last_processed_raw_event_id,
            "transition_count": self.transition_count,
            "in_count": self.in_count,
            "out_count": self.out_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackResolutionState":
        return cls(
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            current_state=DerivedState(data.get("current_state", "unknown")),
            last_transition_timestamp=data.get("last_transition_timestamp", 0.0),
            last_transition_resolution_id=data.get("last_transition_resolution_id"),
            last_processed_raw_event_id=data.get("last_processed_raw_event_id"),
            transition_count=data.get("transition_count", 0),
            in_count=data.get("in_count", 0),
            out_count=data.get("out_count", 0),
        )


@dataclass(frozen=True)
class ResolutionResult:
    """
    Complete result of resolving a sequence of raw events.
    
    Contains all derived transitions and final states.
    """
    # All derived transitions (chronological order)
    transitions: List[ResolvedTransition] = field(default_factory=list)
    
    # Final state per track
    final_states: Dict[str, TrackResolutionState] = field(default_factory=dict)
    
    # Statistics
    total_raw_events: int = 0
    accepted_transitions: int = 0
    suppressed_events: int = 0
    rejected_events: int = 0
    out_of_order_events: int = 0
    
    # Resolver metadata
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    resolution_schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transitions": [t.to_dict() for t in self.transitions],
            "final_states": {f"{k[0]}:{k[1]}": v.to_dict() for k, v in self.final_states.items()},
            "total_raw_events": self.total_raw_events,
            "accepted_transitions": self.accepted_transitions,
            "suppressed_events": self.suppressed_events,
            "rejected_events": self.rejected_events,
            "out_of_order_events": self.out_of_order_events,
            "resolver_version": self.resolver_version,
            "resolver_config_hash": self.resolver_config_hash,
            "resolution_schema_version": self.resolution_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolutionResult":
        return cls(
            transitions=[ResolvedTransition.from_dict(t) for t in data.get("transitions", [])],
            final_states={k: TrackResolutionState.from_dict(v) for k, v in data.get("final_states", {}).items()},
            total_raw_events=data.get("total_raw_events", 0),
            accepted_transitions=data.get("accepted_transitions", 0),
            suppressed_events=data.get("suppressed_events", 0),
            rejected_events=data.get("rejected_events", 0),
            out_of_order_events=data.get("out_of_order_events", 0),
            resolver_version=data.get("resolver_version", "1.0"),
            resolver_config_hash=data.get("resolver_config_hash", ""),
            resolution_schema_version=data.get("resolution_schema_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ResolutionResult":
        import json
        return cls.from_dict(json.loads(json_str))


def generate_resolution_id(
    camera_id: str,
    local_track_id: str,
    source_raw_event_id: str,
    resolver_version: str,
    resolver_config_hash: str,
) -> str:
    """Generate a stable, deterministic resolution ID."""
    import hashlib
    content = f"{camera_id}:{local_track_id}:{source_raw_event_id}:v{resolver_version}:{resolver_config_hash}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"RES-{hash_suffix}"


def generate_config_hash(config: Any) -> str:
    """Generate deterministic hash of resolver configuration."""
    import hashlib
    import json
    if hasattr(config, 'to_dict'):
        content = json.dumps(config.to_dict(), sort_keys=True)
    else:
        content = str(config)
    return hashlib.sha256(content.encode()).hexdigest()[:16]