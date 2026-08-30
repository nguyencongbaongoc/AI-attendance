"""
Phase 24 — Repeated IN/OUT Resolver.

Resolves sequences of RawInOutEvents into deterministic derived transitions/states.
Implements explicit state machine with configurable policies.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.in_out.contract import RawInOutEvent, RawEventDirection
from app.in_out.resolver_config import (
    ResolverConfig,
    InitialOutPolicy,
    OutOfOrderPolicy,
    EqualTimestampPolicy,
)
from app.in_out.resolver_contract import (
    generate_config_hash,
)
from app.in_out.resolver_contract import (
    ResolvedTransition,
    TrackResolutionState,
    ResolutionResult,
    DerivedState,
    TransitionType,
    ResolutionStatus,
    generate_resolution_id,
)


@dataclass
class RepeatedInOutResolver:
    """
    Resolves repeated IN/OUT raw events into deterministic derived transitions.
    
    State machine:
    - UNKNOWN + IN -> INSIDE
    - UNKNOWN + OUT -> policy-defined (ACCEPT/REJECT/ACCEPT_AS_INITIAL_STATE)
    - INSIDE + OUT -> OUTSIDE
    - OUTSIDE + IN -> INSIDE
    - Repeated same-direction events -> SUPPRESSED (no new transition)
    
    Isolated by camera_id + local_track_id.
    """
    config: ResolverConfig
    
    # Internal state: (camera_id, local_track_id) -> TrackResolutionState
    _track_states: Dict[Tuple[str, str], TrackResolutionState] = field(default_factory=dict)
    
    # Processed raw event IDs for idempotency
    _processed_raw_event_ids: set = field(default_factory=set)
    
    # Generated transitions
    _transitions: List[ResolvedTransition] = field(default_factory=list)
    
    # Statistics
    _stats = {
        "total_raw_events": 0,
        "accepted_transitions": 0,
        "suppressed_events": 0,
        "rejected_events": 0,
        "out_of_order_events": 0,
    }
    
    def __post_init__(self):
        self._config_hash = generate_config_hash(self.config)
    
    def resolve_events(self, raw_events: List[RawInOutEvent]) -> ResolutionResult:
        """
        Resolve a sequence of raw events into derived transitions.
        
        Args:
            raw_events: List of RawInOutEvent from Phase 23
            
        Returns:
            ResolutionResult with all derived transitions and final states
        """
        # Reset state for new resolution
        self._reset()
        
        # Handle out-of-order events according to policy
        processed_events = self._handle_ordering(raw_events)
        
        # Update total raw events count
        self._stats["total_raw_events"] = len(processed_events)
        
        # Process each event
        for event in processed_events:
            self._process_raw_event(event)
        
        # Build result
        return self._build_result()
    
    def resolve_single(self, raw_event: RawInOutEvent) -> ResolvedTransition:
        """
        Resolve a single raw event (incremental processing).
        
        Args:
            raw_event: Single RawInOutEvent
            
        Returns:
            ResolvedTransition for this event
        """
        # Check for duplicate
        if raw_event.event_id in self._processed_raw_event_ids:
            # Return existing transition for this event
            existing = next((t for t in self._transitions if t.source_raw_event_id == raw_event.event_id), None)
            if existing:
                return existing
            # Should not happen, but fallback
            return self._create_suppressed_transition(raw_event, "duplicate_event_id")
        
        self._stats["total_raw_events"] += 1
        self._processed_raw_event_ids.add(raw_event.event_id)
        
        return self._resolve_event_internal(raw_event)
    
    def _reset(self) -> None:
        """Reset resolver state for new resolution."""
        self._track_states.clear()
        self._processed_raw_event_ids.clear()
        self._transitions.clear()
        for key in self._stats:
            self._stats[key] = 0
    
    def _handle_ordering(self, raw_events: List[RawInOutEvent]) -> List[RawInOutEvent]:
        """Handle event ordering according to policy."""
        if not raw_events:
            return []
        
        # Check if already sorted (including tie-breaker)
        def sort_key(event: RawInOutEvent) -> Tuple:
            if self.config.equal_timestamp_policy == EqualTimestampPolicy.EVENT_ID:
                return (event.crossing_timestamp, event.event_id)
            elif self.config.equal_timestamp_policy == EqualTimestampPolicy.CAMERA_ID_THEN_EVENT_ID:
                return (event.crossing_timestamp, event.camera_id, event.event_id)
            elif self.config.equal_timestamp_policy == EqualTimestampPolicy.TRACK_ID_THEN_EVENT_ID:
                return (event.crossing_timestamp, event.local_track_id, event.event_id)
            return (event.crossing_timestamp, event.event_id)
        
        is_sorted = all(
            sort_key(raw_events[i]) <= sort_key(raw_events[i + 1])
            for i in range(len(raw_events) - 1)
        )
        
        if is_sorted:
            return raw_events
        
        # Apply out-of-order policy
        if self.config.out_of_order_policy == OutOfOrderPolicy.SORT:
            return self._sort_events(raw_events)
        elif self.config.out_of_order_policy == OutOfOrderPolicy.REJECT:
            # Mark out-of-order events as rejected
            self._stats["out_of_order_events"] = len(raw_events) - 1  # Approximate
            return self._sort_events(raw_events)  # Still sort for deterministic processing
        elif self.config.out_of_order_policy == OutOfOrderPolicy.ACCEPT_IF_SAFE:
            # For now, sort but track out-of-order
            self._stats["out_of_order_events"] = len(raw_events) - 1
            return self._sort_events(raw_events)
        
        return raw_events
    
    def _sort_events(self, raw_events: List[RawInOutEvent]) -> List[RawInOutEvent]:
        """Sort events by timestamp with deterministic tie-breaking."""
        def sort_key(event: RawInOutEvent) -> Tuple:
            if self.config.equal_timestamp_policy == EqualTimestampPolicy.EVENT_ID:
                return (event.crossing_timestamp, event.event_id)
            elif self.config.equal_timestamp_policy == EqualTimestampPolicy.CAMERA_ID_THEN_EVENT_ID:
                return (event.crossing_timestamp, event.camera_id, event.event_id)
            elif self.config.equal_timestamp_policy == EqualTimestampPolicy.TRACK_ID_THEN_EVENT_ID:
                return (event.crossing_timestamp, event.local_track_id, event.event_id)
            return (event.crossing_timestamp, event.event_id)
        
        return sorted(raw_events, key=sort_key)
    
    def _process_raw_event(self, raw_event: RawInOutEvent) -> None:
        """Process a single raw event and record transition."""
        transition = self._resolve_event_internal(raw_event)
        self._transitions.append(transition)
        
        # Update statistics
        if transition.resolution_status == ResolutionStatus.ACCEPTED:
            self._stats["accepted_transitions"] += 1
        elif transition.resolution_status == ResolutionStatus.SUPPRESSED:
            self._stats["suppressed_events"] += 1
        elif transition.resolution_status == ResolutionStatus.REJECTED:
            self._stats["rejected_events"] += 1
        elif transition.resolution_status == ResolutionStatus.OUT_OF_ORDER:
            self._stats["out_of_order_events"] += 1
    
    def _resolve_event_internal(self, raw_event: RawInOutEvent) -> ResolvedTransition:
        """Internal resolution logic for a single event."""
        # Get or create track state
        track_key = (raw_event.camera_id, raw_event.local_track_id)
        track_state = self._track_states.get(track_key)
        
        if track_state is None:
            track_state = TrackResolutionState(
                camera_id=raw_event.camera_id,
                local_track_id=raw_event.local_track_id,
            )
            self._track_states[track_key] = track_state
        
        # Check minimum transition interval if enabled
        if (self.config.enable_rapid_reversal_protection and 
            self.config.min_transition_interval_seconds > 0 and
            track_state.last_transition_timestamp > 0):
            
            time_since_last = raw_event.crossing_timestamp - track_state.last_transition_timestamp
            if time_since_last < self.config.min_transition_interval_seconds:
                # Too rapid - suppress
                return self._create_suppressed_transition(
                    raw_event, 
                    "rapid_reversal_protection",
                    track_state.current_state
                )
        
        # Determine direction
        is_in = raw_event.direction == RawEventDirection.IN
        direction_str = "in" if is_in else "out"
        
        # Apply state machine
        previous_state = track_state.current_state
        new_state, transition_type, status = self._apply_state_machine(
            track_state.current_state,
            is_in,
            raw_event,
        )
        
        # Create resolution
        resolution_id = generate_resolution_id(
            camera_id=raw_event.camera_id,
            local_track_id=raw_event.local_track_id,
            source_raw_event_id=raw_event.event_id,
            resolver_version=self.config.resolver_version,
            resolver_config_hash=self._config_hash,
        )
        
        transition = ResolvedTransition(
            resolution_id=resolution_id,
            source_raw_event_id=raw_event.event_id,
            camera_id=raw_event.camera_id,
            local_track_id=raw_event.local_track_id,
            global_observation_id=raw_event.global_observation_id,
            direction=direction_str,
            transition_type=transition_type,
            previous_state=previous_state,
            new_state=new_state,
            source_timestamp=raw_event.crossing_timestamp,
            source_frame_index=raw_event.crossing_frame_index,
            resolver_version=self.config.resolver_version,
            resolver_config_hash=self._config_hash,
            resolution_status=status,
            source_crossing_event_id=raw_event.source_crossing_event_id,
            geometry_version=raw_event.geometry_version,
            geometry_config_hash=raw_event.geometry_config_hash,
        )
        
        # Update track state if transition occurred
        if transition_type != TransitionType.NONE:
            # Create new track state (immutable)
            updated_state = TrackResolutionState(
                camera_id=track_state.camera_id,
                local_track_id=track_state.local_track_id,
                current_state=new_state,
                last_transition_timestamp=raw_event.crossing_timestamp,
                last_transition_resolution_id=resolution_id,
                last_processed_raw_event_id=raw_event.event_id,
                transition_count=track_state.transition_count + 1,
                in_count=track_state.in_count + (1 if transition_type == TransitionType.IN else 0),
                out_count=track_state.out_count + (1 if transition_type == TransitionType.OUT else 0),
            )
            self._track_states[track_key] = updated_state
        else:
            # Just update last processed event ID
            updated_state = TrackResolutionState(
                camera_id=track_state.camera_id,
                local_track_id=track_state.local_track_id,
                current_state=track_state.current_state,
                last_transition_timestamp=track_state.last_transition_timestamp,
                last_transition_resolution_id=track_state.last_transition_resolution_id,
                last_processed_raw_event_id=raw_event.event_id,
                transition_count=track_state.transition_count,
                in_count=track_state.in_count,
                out_count=track_state.out_count,
            )
            self._track_states[track_key] = updated_state
        
        return transition
    
    def _apply_state_machine(
        self,
        current_state: DerivedState,
        is_in: bool,
        raw_event: RawInOutEvent,
    ) -> Tuple[DerivedState, TransitionType, ResolutionStatus]:
        """
        Apply the explicit state machine.
        
        Returns:
            Tuple of (new_state, transition_type, resolution_status)
        """
        # UNKNOWN state
        if current_state == DerivedState.UNKNOWN:
            if is_in:
                return DerivedState.INSIDE, TransitionType.IN, ResolutionStatus.ACCEPTED
            else:
                # OUT from UNKNOWN - apply policy
                if self.config.initial_out_policy == InitialOutPolicy.ACCEPT:
                    return DerivedState.OUTSIDE, TransitionType.OUT, ResolutionStatus.ACCEPTED
                elif self.config.initial_out_policy == InitialOutPolicy.REJECT:
                    return DerivedState.UNKNOWN, TransitionType.NONE, ResolutionStatus.REJECTED
                elif self.config.initial_out_policy == InitialOutPolicy.ACCEPT_AS_INITIAL_STATE:
                    return DerivedState.OUTSIDE, TransitionType.OUT, ResolutionStatus.ACCEPTED
        
        # INSIDE state
        elif current_state == DerivedState.INSIDE:
            if is_in:
                # Repeated IN - suppress
                return DerivedState.INSIDE, TransitionType.NONE, ResolutionStatus.SUPPRESSED
            else:
                # OUT from INSIDE -> OUTSIDE
                return DerivedState.OUTSIDE, TransitionType.OUT, ResolutionStatus.ACCEPTED
        
        # OUTSIDE state
        elif current_state == DerivedState.OUTSIDE:
            if is_in:
                # IN from OUTSIDE -> INSIDE
                return DerivedState.INSIDE, TransitionType.IN, ResolutionStatus.ACCEPTED
            else:
                # Repeated OUT - suppress
                return DerivedState.OUTSIDE, TransitionType.NONE, ResolutionStatus.SUPPRESSED
        
        # Should not reach here
        return current_state, TransitionType.NONE, ResolutionStatus.REJECTED
    
    def _create_suppressed_transition(
        self,
        raw_event: RawInOutEvent,
        reason: str,
        current_state: DerivedState = DerivedState.UNKNOWN,
    ) -> ResolvedTransition:
        """Create a suppressed transition (no state change)."""
        resolution_id = generate_resolution_id(
            camera_id=raw_event.camera_id,
            local_track_id=raw_event.local_track_id,
            source_raw_event_id=raw_event.event_id,
            resolver_version=self.config.resolver_version,
            resolver_config_hash=self._config_hash,
        )
        
        direction_str = "in" if raw_event.direction == RawEventDirection.IN else "out"
        
        return ResolvedTransition(
            resolution_id=resolution_id,
            source_raw_event_id=raw_event.event_id,
            camera_id=raw_event.camera_id,
            local_track_id=raw_event.local_track_id,
            global_observation_id=raw_event.global_observation_id,
            direction=direction_str,
            transition_type=TransitionType.NONE,
            previous_state=current_state,
            new_state=current_state,
            source_timestamp=raw_event.crossing_timestamp,
            source_frame_index=raw_event.crossing_frame_index,
            resolver_version=self.config.resolver_version,
            resolver_config_hash=self._config_hash,
            resolution_status=ResolutionStatus.SUPPRESSED,
            source_crossing_event_id=raw_event.source_crossing_event_id,
            geometry_version=raw_event.geometry_version,
            geometry_config_hash=raw_event.geometry_config_hash,
        )
    
    def _build_result(self) -> ResolutionResult:
        """Build final resolution result."""
        # Convert tuple keys to string keys for JSON serialization
        final_states_str = {f"{k[0]}:{k[1]}": v for k, v in self._track_states.items()}
        return ResolutionResult(
            transitions=self._transitions,
            final_states=final_states_str,
            total_raw_events=self._stats["total_raw_events"],
            accepted_transitions=self._stats["accepted_transitions"],
            suppressed_events=self._stats["suppressed_events"],
            rejected_events=self._stats["rejected_events"],
            out_of_order_events=self._stats["out_of_order_events"],
            resolver_version=self.config.resolver_version,
            resolver_config_hash=self._config_hash,
        )
    
    def get_track_state(self, camera_id: str, local_track_id: str) -> Optional[TrackResolutionState]:
        """Get current derived state for a track."""
        return self._track_states.get((camera_id, local_track_id))
    
    def get_all_track_states(self) -> Dict[Tuple[str, str], TrackResolutionState]:
        """Get all track states."""
        return dict(self._track_states)
    
    def get_transitions(self) -> List[ResolvedTransition]:
        """Get all derived transitions."""
        return list(self._transitions)
    
    def get_stats(self) -> Dict[str, int]:
        """Get resolver statistics."""
        return dict(self._stats)
    
    def clear(self) -> None:
        """Clear all resolver state."""
        self._reset()


def create_repeated_in_out_resolver(config: Optional[ResolverConfig] = None) -> RepeatedInOutResolver:
    """Factory function to create a RepeatedInOutResolver."""
    if config is None:
        config = ResolverConfig()
    return RepeatedInOutResolver(config=config)


def resolve_raw_events(
    raw_events: List[RawInOutEvent],
    config: Optional[ResolverConfig] = None,
) -> ResolutionResult:
    """
    Convenience function to resolve raw events.
    
    Args:
        raw_events: List of RawInOutEvent from Phase 23
        config: Optional resolver configuration
        
    Returns:
        ResolutionResult with derived transitions and states
    """
    resolver = create_repeated_in_out_resolver(config)
    return resolver.resolve_events(raw_events)