"""
Phase 23 — Raw IN/OUT Event Contract.

Canonical immutable raw event produced from a validated Phase 22 CrossingEvent.
This is the historical fact that future resolution layers will consume.

Phase 23 answers: "Did a validated crossing produce an IN or OUT raw event?"
It does NOT answer: "What is the person's current attendance state?"
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class RawEventDirection(str, Enum):
    """Raw event direction from Phase 22 crossing."""
    IN = "in"
    OUT = "out"


class RawEventType(str, Enum):
    """Type of raw event based on crossing type."""
    LINE_CROSSING = "line_crossing"
    ZONE_ENTRY = "zone_entry"
    ZONE_EXIT = "zone_exit"


class IdentityCertainty(str, Enum):
    """Identity certainty level preserved from upstream."""
    KNOWN = "known"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class RawInOutEvent:
    """
    Canonical immutable raw IN/OUT event.
    
    Generated from a validated Phase 22 CrossingEvent.
    Preserves full provenance chain for forensic reproducibility.
    
    This is a HISTORICAL FACT - after creation it MUST NOT be mutable.
    """
    # Event identification (stable, deterministic)
    event_id: str
    
    # Camera and geometry provenance
    camera_id: str
    geometry_id: str
    geometry_version: int
    geometry_config_hash: str
    
    # Track reference (camera-local identity)
    local_track_id: str
    
    # Global observation reference (if available from Phase 22)
    global_observation_id: Optional[str] = None
    
    # Event classification
    event_type: RawEventType = RawEventType.LINE_CROSSING
    direction: RawEventDirection = RawEventDirection.IN
    
    # Spatial details
    crossing_point_x: float = 0.0
    crossing_point_y: float = 0.0
    
    # Temporal details (preserved from Phase 22)
    crossing_timestamp: float = 0.0
    crossing_frame_index: int = -1
    
    # Trajectory evidence (from CrossingEvent)
    previous_position_x: Optional[float] = None
    previous_position_y: Optional[float] = None
    current_position_x: Optional[float] = None
    current_position_y: Optional[float] = None
    previous_frame_index: int = -1
    current_frame_index: int = -1
    previous_timestamp: float = 0.0
    current_timestamp: float = 0.0
    crossing_distance: float = 0.0
    side_transition: str = ""
    
    # Identity evidence reference (preserved from upstream)
    identity_certainty: IdentityCertainty = IdentityCertainty.UNKNOWN
    identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_evidence_ref: Optional[str] = None  # Reference to IdentityEvidence/Hypothesis
    
    # Source crossing event reference
    source_crossing_event_id: str = ""
    
    # Full provenance chain
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
        if not self.source_crossing_event_id:
            raise ValueError("source_crossing_event_id is required")
        if not self.geometry_id:
            raise ValueError("geometry_id is required")
        if self.geometry_version < 1:
            raise ValueError("geometry_version must be >= 1")
        if not self.geometry_config_hash:
            raise ValueError("geometry_config_hash is required")
        if self.direction not in (RawEventDirection.IN, RawEventDirection.OUT):
            raise ValueError(f"direction must be IN or OUT, got {self.direction}")
        if self.crossing_timestamp < 0:
            raise ValueError("crossing_timestamp must be >= 0")
        if self.event_schema_version != "1.0":
            raise ValueError(f"Unsupported event_schema_version: {self.event_schema_version}")
    
    @property
    def is_in(self) -> bool:
        return self.direction == RawEventDirection.IN
    
    @property
    def is_out(self) -> bool:
        return self.direction == RawEventDirection.OUT
    
    @property
    def crossing_point(self) -> Dict[str, float]:
        return {"x": self.crossing_point_x, "y": self.crossing_point_y}
    
    @property
    def previous_position(self) -> Optional[Dict[str, float]]:
        if self.previous_position_x is not None and self.previous_position_y is not None:
            return {"x": self.previous_position_x, "y": self.previous_position_y}
        return None
    
    @property
    def current_position(self) -> Optional[Dict[str, float]]:
        if self.current_position_x is not None and self.current_position_y is not None:
            return {"x": self.current_position_x, "y": self.current_position_y}
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage/transmission."""
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "geometry_id": self.geometry_id,
            "geometry_version": self.geometry_version,
            "geometry_config_hash": self.geometry_config_hash,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "event_type": self.event_type.value,
            "direction": self.direction.value,
            "crossing_point": self.crossing_point,
            "crossing_timestamp": self.crossing_timestamp,
            "crossing_frame_index": self.crossing_frame_index,
            "previous_position": self.previous_position,
            "current_position": self.current_position,
            "previous_frame_index": self.previous_frame_index,
            "current_frame_index": self.current_frame_index,
            "previous_timestamp": self.previous_timestamp,
            "current_timestamp": self.current_timestamp,
            "crossing_distance": self.crossing_distance,
            "side_transition": self.side_transition,
            "identity_certainty": self.identity_certainty.value,
            "identity_candidate": self.identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_evidence_ref": self.identity_evidence_ref,
            "source_crossing_event_id": self.source_crossing_event_id,
            "trajectory_points": self.trajectory_points,
            "config_snapshot": self.config_snapshot,
            "event_schema_version": self.event_schema_version,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RawInOutEvent":
        """Deserialize from dictionary."""
        # Handle optional position fields
        prev_pos = data.get("previous_position")
        curr_pos = data.get("current_position")
        
        return cls(
            event_id=data["event_id"],
            camera_id=data["camera_id"],
            geometry_id=data["geometry_id"],
            geometry_version=data["geometry_version"],
            geometry_config_hash=data["geometry_config_hash"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            event_type=RawEventType(data.get("event_type", "line_crossing")),
            direction=RawEventDirection(data["direction"]),
            crossing_point_x=data["crossing_point"]["x"],
            crossing_point_y=data["crossing_point"]["y"],
            crossing_timestamp=data["crossing_timestamp"],
            crossing_frame_index=data.get("crossing_frame_index", -1),
            previous_position_x=prev_pos["x"] if prev_pos else None,
            previous_position_y=prev_pos["y"] if prev_pos else None,
            current_position_x=curr_pos["x"] if curr_pos else None,
            current_position_y=curr_pos["y"] if curr_pos else None,
            previous_frame_index=data.get("previous_frame_index", -1),
            current_frame_index=data.get("current_frame_index", -1),
            previous_timestamp=data.get("previous_timestamp", 0.0),
            current_timestamp=data.get("current_timestamp", 0.0),
            crossing_distance=data.get("crossing_distance", 0.0),
            side_transition=data.get("side_transition", ""),
            identity_certainty=IdentityCertainty(data.get("identity_certainty", "unknown")),
            identity_candidate=data.get("identity_candidate"),
            identity_confidence=data.get("identity_confidence", 0.0),
            identity_evidence_ref=data.get("identity_evidence_ref"),
            source_crossing_event_id=data["source_crossing_event_id"],
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
    def from_json(cls, json_str: str) -> "RawInOutEvent":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class RawEventCreationResult:
    """Result of attempting to create a RawInOutEvent from a CrossingEvent."""
    success: bool
    event: Optional[RawInOutEvent] = None
    error: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    @classmethod
    def success_result(cls, event: RawInOutEvent) -> "RawEventCreationResult":
        return cls(success=True, event=event)
    
    @classmethod
    def failure_result(cls, error: str, rejection_reason: Optional[str] = None) -> "RawEventCreationResult":
        return cls(success=False, error=error, rejection_reason=rejection_reason)


def generate_deterministic_event_id(
    camera_id: str,
    local_track_id: str,
    source_crossing_event_id: str,
    geometry_version: int,
    geometry_config_hash: str,
) -> str:
    """
    Generate a stable, deterministic event ID.
    
    Same inputs MUST produce the same event_id.
    Uses stable source provenance to avoid collisions across cameras.
    """
    content = f"{camera_id}:{local_track_id}:{source_crossing_event_id}:v{geometry_version}:{geometry_config_hash}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"RIE-{hash_suffix}"


def validate_crossing_event_for_raw_creation(crossing_event: Any) -> Optional[str]:
    """
    Validate that a CrossingEvent is suitable for RawInOutEvent creation.
    
    Returns None if valid, error message if invalid.
    """
    # Check required fields exist
    required_fields = [
        "event_id", "camera_id", "local_track_id", "direction",
        "crossing_timestamp", "geometry_config"
    ]
    
    for field_name in required_fields:
        if not hasattr(crossing_event, field_name):
            return f"CrossingEvent missing required field: {field_name}"
        value = getattr(crossing_event, field_name)
        if value is None or (isinstance(value, str) and not value):
            return f"CrossingEvent field {field_name} is empty"
    
    # Validate direction
    if crossing_event.direction not in ("in", "out"):
        return f"Invalid direction: {crossing_event.direction}"
    
    # Validate timestamp
    if crossing_event.crossing_timestamp < 0:
        return f"Invalid crossing_timestamp: {crossing_event.crossing_timestamp}"
    
    # Validate geometry config
    geom_config = crossing_event.geometry_config
    if not hasattr(geom_config, "config_hash") or not geom_config.config_hash:
        return "CrossingEvent geometry_config missing config_hash"
    if not hasattr(geom_config, "version") or geom_config.version < 1:
        return "CrossingEvent geometry_config missing or invalid version"
    if not hasattr(geom_config, "geometry_type"):
        return "CrossingEvent geometry_config missing geometry_type"
    
    return None