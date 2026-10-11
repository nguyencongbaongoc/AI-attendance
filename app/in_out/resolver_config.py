"""
Phase 24 — Repeated IN/OUT Resolver Configuration.

Explicit, serializable, deterministic configuration for the resolver state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class InitialOutPolicy(str, Enum):
    """Policy for handling the first event when it is OUT."""
    ACCEPT = "accept"                    # Accept OUT as valid, transition UNKNOWN -> OUTSIDE
    REJECT = "reject"                    # Reject initial OUT, stay in UNKNOWN
    ACCEPT_AS_INITIAL_STATE = "accept_as_initial_state"  # Accept OUT, set initial state to OUTSIDE


class OutOfOrderPolicy(str, Enum):
    """Policy for handling out-of-order events."""
    SORT = "sort"                        # Sort events by timestamp before processing
    REJECT = "reject"                    # Reject events that arrive out of order
    ACCEPT_IF_SAFE = "accept_if_safe"    # Accept if it doesn't violate state machine logic


class EqualTimestampPolicy(str, Enum):
    """Policy for handling events with equal timestamps."""
    EVENT_ID = "event_id"                # Tie-break by event_id (deterministic)
    CAMERA_ID_THEN_EVENT_ID = "camera_id_then_event_id"  # Tie-break by camera_id then event_id
    TRACK_ID_THEN_EVENT_ID = "track_id_then_event_id"    # Tie-break by track_id then event_id


@dataclass(frozen=True)
class ResolverConfig:
    """
    Configuration for RepeatedInOutResolver.
    
    All policies are explicit, serializable, and deterministic.
    """
    # Resolver version
    resolver_version: str = "1.0"
    
    # Initial state policy
    initial_out_policy: InitialOutPolicy = InitialOutPolicy.ACCEPT_AS_INITIAL_STATE
    
    # Out-of-order event policy
    out_of_order_policy: OutOfOrderPolicy = OutOfOrderPolicy.SORT
    
    # Equal timestamp tie-breaking policy
    equal_timestamp_policy: EqualTimestampPolicy = EqualTimestampPolicy.EVENT_ID
    
    # Minimum transition interval (optional protection from pathological sequences)
    # Set to 0 to disable
    min_transition_interval_seconds: float = 0.0
    
    # Maximum state history to retain per track (for bounded memory)
    max_state_history_per_track: int = 100
    
    # Whether to enable rapid reversal protection
    enable_rapid_reversal_protection: bool = False
    
    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        if self.min_transition_interval_seconds < 0:
            raise ValueError("min_transition_interval_seconds must be >= 0")
        if self.max_state_history_per_track < 1:
            raise ValueError("max_state_history_per_track must be >= 1")
        if self.resolver_version != "1.0":
            raise ValueError(f"Unsupported resolver_version: {self.resolver_version}")
        # Validate enum values
        if not isinstance(self.initial_out_policy, InitialOutPolicy):
            raise ValueError(f"Invalid initial_out_policy: {self.initial_out_policy}")
        if not isinstance(self.out_of_order_policy, OutOfOrderPolicy):
            raise ValueError(f"Invalid out_of_order_policy: {self.out_of_order_policy}")
        if not isinstance(self.equal_timestamp_policy, EqualTimestampPolicy):
            raise ValueError(f"Invalid equal_timestamp_policy: {self.equal_timestamp_policy}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "resolver_version": self.resolver_version,
            "initial_out_policy": self.initial_out_policy.value,
            "out_of_order_policy": self.out_of_order_policy.value,
            "equal_timestamp_policy": self.equal_timestamp_policy.value,
            "min_transition_interval_seconds": self.min_transition_interval_seconds,
            "max_state_history_per_track": self.max_state_history_per_track,
            "enable_rapid_reversal_protection": self.enable_rapid_reversal_protection,
            "description": self.description,
            "tags": self.tags,
            # Exclude created_at from config hash - it's metadata, not configuration
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolverConfig":
        """Deserialize from dictionary."""
        return cls(
            resolver_version=data.get("resolver_version", "1.0"),
            initial_out_policy=InitialOutPolicy(data.get("initial_out_policy", "accept_as_initial_state")),
            out_of_order_policy=OutOfOrderPolicy(data.get("out_of_order_policy", "sort")),
            equal_timestamp_policy=EqualTimestampPolicy(data.get("equal_timestamp_policy", "event_id")),
            min_transition_interval_seconds=data.get("min_transition_interval_seconds", 0.0),
            max_state_history_per_track=data.get("max_state_history_per_track", 100),
            enable_rapid_reversal_protection=data.get("enable_rapid_reversal_protection", False),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ResolverConfig":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


def create_default_resolver_config() -> ResolverConfig:
    """Create a default resolver configuration."""
    return ResolverConfig()


def create_strict_resolver_config() -> ResolverConfig:
    """Create a strict resolver configuration (rejects initial OUT, rejects out-of-order)."""
    return ResolverConfig(
        initial_out_policy=InitialOutPolicy.REJECT,
        out_of_order_policy=OutOfOrderPolicy.REJECT,
        min_transition_interval_seconds=1.0,
        enable_rapid_reversal_protection=True,
    )


def create_permissive_resolver_config() -> ResolverConfig:
    """Create a permissive resolver configuration (accepts all, sorts out-of-order)."""
    return ResolverConfig(
        initial_out_policy=InitialOutPolicy.ACCEPT,
        out_of_order_policy=OutOfOrderPolicy.SORT,
        min_transition_interval_seconds=0.0,
        enable_rapid_reversal_protection=False,
    )