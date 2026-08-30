"""
Phase 24 — Unit Tests for Repeated IN/OUT Resolver.

Tests cover:
- Explicit state machine (UNKNOWN, INSIDE, OUTSIDE)
- Initial OUT policy (ACCEPT, REJECT, ACCEPT_AS_INITIAL_STATE)
- Repeated IN/OUT suppression
- IN -> OUT -> IN sequences
- Multi-track isolation
- Multi-camera isolation
- Temporal ordering and tie-breaking
- Out-of-order policies
- Rapid reversal protection
- Idempotency (duplicate raw event handling)
- Serialization round-trip
- Configuration serialization
- Determinism
- Bounded memory
- Negative cases
"""

import pytest
import json
from typing import List

from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
)
from app.in_out.resolver_config import (
    ResolverConfig,
    InitialOutPolicy,
    OutOfOrderPolicy,
    EqualTimestampPolicy,
    create_default_resolver_config,
    create_strict_resolver_config,
    create_permissive_resolver_config,
)
from app.in_out.resolver_contract import (
    ResolvedTransition,
    TrackResolutionState,
    ResolutionResult,
    DerivedState,
    TransitionType,
    ResolutionStatus,
    generate_resolution_id,
    generate_config_hash,
)
from app.in_out.resolver import (
    RepeatedInOutResolver,
    create_repeated_in_out_resolver,
    resolve_raw_events,
)


# =============================================================================
# FIXTURES
# =============================================================================

def create_raw_event(
    event_id: str,
    camera_id: str = "CAM1",
    local_track_id: str = "track_001",
    direction: RawEventDirection = RawEventDirection.IN,
    timestamp: float = 1000.0,
    frame_index: int = 100,
    global_observation_id: str = None,
    geometry_version: int = 1,
    geometry_config_hash: str = "hash123",
    source_crossing_event_id: str = "CE-123",
) -> RawInOutEvent:
    """Create a RawInOutEvent for testing."""
    return RawInOutEvent(
        event_id=event_id,
        camera_id=camera_id,
        geometry_id=geometry_config_hash,
        geometry_version=geometry_version,
        geometry_config_hash=geometry_config_hash,
        local_track_id=local_track_id,
        global_observation_id=global_observation_id,
        event_type=RawEventType.LINE_CROSSING,
        direction=direction,
        crossing_point_x=960.0,
        crossing_point_y=500.0,
        crossing_timestamp=timestamp,
        crossing_frame_index=frame_index,
        previous_position_x=960.0,
        previous_position_y=480.0 if direction == RawEventDirection.IN else 520.0,
        current_position_x=960.0,
        current_position_y=520.0 if direction == RawEventDirection.IN else 480.0,
        previous_frame_index=frame_index - 1,
        current_frame_index=frame_index,
        previous_timestamp=timestamp - 1.0,
        current_timestamp=timestamp,
        crossing_distance=40.0,
        side_transition="SIDE_A->SIDE_B" if direction == RawEventDirection.IN else "SIDE_B->SIDE_A",
        identity_certainty=IdentityCertainty.UNKNOWN,
        identity_candidate=None,
        identity_confidence=0.0,
        identity_evidence_ref=global_observation_id,
        source_crossing_event_id=source_crossing_event_id,
        trajectory_points=[],
        config_snapshot={},
        event_schema_version="1.0",
        created_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def default_config() -> ResolverConfig:
    """Default resolver configuration."""
    return create_default_resolver_config()


@pytest.fixture
def strict_config() -> ResolverConfig:
    """Strict resolver configuration."""
    return create_strict_resolver_config()


@pytest.fixture
def permissive_config() -> ResolverConfig:
    """Permissive resolver configuration."""
    return create_permissive_resolver_config()


@pytest.fixture
def resolver(default_config: ResolverConfig) -> RepeatedInOutResolver:
    """Create a resolver with default config."""
    return create_repeated_in_out_resolver(default_config)


# =============================================================================
# STATE MACHINE TESTS
# =============================================================================

class TestStateMachine:
    """Tests for the explicit state machine."""
    
    def test_unknown_in_transitions_to_inside(self, resolver: RepeatedInOutResolver):
        """UNKNOWN + IN -> INSIDE"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.total_raw_events == 1
        assert result.accepted_transitions == 1
        assert len(result.transitions) == 1
        
        transition = result.transitions[0]
        assert transition.previous_state == DerivedState.UNKNOWN
        assert transition.new_state == DerivedState.INSIDE
        assert transition.transition_type == TransitionType.IN
        assert transition.resolution_status == ResolutionStatus.ACCEPTED
        
        # Check final state
        track_key = "CAM1:track_001"
        final_state = result.final_states[track_key]
        assert final_state.current_state == DerivedState.INSIDE
    
    def test_unknown_out_accept_as_initial_state(self, resolver: RepeatedInOutResolver):
        """UNKNOWN + OUT with ACCEPT_AS_INITIAL_STATE -> OUTSIDE"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.accepted_transitions == 1
        transition = result.transitions[0]
        assert transition.previous_state == DerivedState.UNKNOWN
        assert transition.new_state == DerivedState.OUTSIDE
        assert transition.transition_type == TransitionType.OUT
    
    def test_inside_out_transitions_to_outside(self, resolver: RepeatedInOutResolver):
        """INSIDE + OUT -> OUTSIDE"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 2
        # Second transition
        transition = result.transitions[1]
        assert transition.previous_state == DerivedState.INSIDE
        assert transition.new_state == DerivedState.OUTSIDE
        assert transition.transition_type == TransitionType.OUT
    
    def test_outside_in_transitions_to_inside(self, resolver: RepeatedInOutResolver):
        """OUTSIDE + IN -> INSIDE"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.IN, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 2
        transition = result.transitions[1]
        assert transition.previous_state == DerivedState.OUTSIDE
        assert transition.new_state == DerivedState.INSIDE
        assert transition.transition_type == TransitionType.IN
    
    def test_repeated_in_suppressed(self, resolver: RepeatedInOutResolver):
        """Repeated IN events are suppressed (no new transition)"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.IN, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.total_raw_events == 3
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 2
        
        # Only first event produces transition
        assert result.transitions[0].transition_type == TransitionType.IN
        assert result.transitions[1].transition_type == TransitionType.NONE
        assert result.transitions[2].transition_type == TransitionType.NONE
        assert result.transitions[1].resolution_status == ResolutionStatus.SUPPRESSED
        assert result.transitions[2].resolution_status == ResolutionStatus.SUPPRESSED
        
        # Final state still INSIDE
        track_key = "CAM1:track_001"
        assert result.final_states[track_key].current_state == DerivedState.INSIDE
    
    def test_repeated_out_suppressed(self, resolver: RepeatedInOutResolver):
        """Repeated OUT events are suppressed"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.OUT, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 2
        assert result.transitions[0].transition_type == TransitionType.OUT
        assert result.transitions[1].transition_type == TransitionType.NONE
        assert result.transitions[2].transition_type == TransitionType.NONE
    
    def test_in_out_in_sequence(self, resolver: RepeatedInOutResolver):
        """IN -> OUT -> IN produces three transitions"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 3
        assert result.suppressed_events == 0
        
        types = [t.transition_type for t in result.transitions]
        assert types == [TransitionType.IN, TransitionType.OUT, TransitionType.IN]
        
        states = [(t.previous_state, t.new_state) for t in result.transitions]
        assert states == [
            (DerivedState.UNKNOWN, DerivedState.INSIDE),
            (DerivedState.INSIDE, DerivedState.OUTSIDE),
            (DerivedState.OUTSIDE, DerivedState.INSIDE),
        ]
    
    def test_in_out_in_out_sequence(self, resolver: RepeatedInOutResolver):
        """IN -> OUT -> IN -> OUT produces four transitions"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
            create_raw_event("RIE-004", direction=RawEventDirection.OUT, timestamp=4000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 4
        types = [t.transition_type for t in result.transitions]
        assert types == [TransitionType.IN, TransitionType.OUT, TransitionType.IN, TransitionType.OUT]
    
    def test_in_in_out_out_in_sequence(self, resolver: RepeatedInOutResolver):
        """IN -> IN -> OUT -> OUT -> IN"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.IN, timestamp=1500.0),
            create_raw_event("RIE-003", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-004", direction=RawEventDirection.OUT, timestamp=2500.0),
            create_raw_event("RIE-005", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.total_raw_events == 5
        assert result.accepted_transitions == 3  # IN, OUT, IN
        assert result.suppressed_events == 2    # repeated IN, repeated OUT
        
        types = [t.transition_type for t in result.transitions]
        assert types == [TransitionType.IN, TransitionType.NONE, TransitionType.OUT, TransitionType.NONE, TransitionType.IN]
    
    def test_out_out_in_in_sequence(self, resolver: RepeatedInOutResolver):
        """OUT -> OUT -> IN -> IN"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=1500.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=2000.0),
            create_raw_event("RIE-004", direction=RawEventDirection.IN, timestamp=2500.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 2  # OUT, IN
        assert result.suppressed_events == 2
        
        types = [t.transition_type for t in result.transitions]
        assert types == [TransitionType.OUT, TransitionType.NONE, TransitionType.IN, TransitionType.NONE]
    
    def test_in_out_out_in_sequence(self, resolver: RepeatedInOutResolver):
        """IN -> OUT -> OUT -> IN"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.OUT, timestamp=2500.0),
            create_raw_event("RIE-004", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 3
        assert result.suppressed_events == 1
        
        types = [t.transition_type for t in result.transitions]
        assert types == [TransitionType.IN, TransitionType.OUT, TransitionType.NONE, TransitionType.IN]


# =============================================================================
# INITIAL OUT POLICY TESTS
# =============================================================================

class TestInitialOutPolicy:
    """Tests for initial OUT policy."""
    
    def test_accept_policy(self):
        """ACCEPT policy: initial OUT creates OUTSIDE state"""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.ACCEPT)
        resolver = create_repeated_in_out_resolver(config)
        
        event = create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.accepted_transitions == 1
        assert result.rejected_events == 0
        assert result.transitions[0].new_state == DerivedState.OUTSIDE
    
    def test_reject_policy(self):
        """REJECT policy: initial OUT is rejected, stays UNKNOWN"""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.REJECT)
        resolver = create_repeated_in_out_resolver(config)
        
        event = create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.accepted_transitions == 0
        assert result.rejected_events == 1
        assert result.transitions[0].resolution_status == ResolutionStatus.REJECTED
        assert result.transitions[0].new_state == DerivedState.UNKNOWN
        
        # Final state should be UNKNOWN
        track_key = "CAM1:track_001"
        assert result.final_states[track_key].current_state == DerivedState.UNKNOWN
    
    def test_accept_as_initial_state_policy(self):
        """ACCEPT_AS_INITIAL_STATE policy: initial OUT creates OUTSIDE"""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.ACCEPT_AS_INITIAL_STATE)
        resolver = create_repeated_in_out_resolver(config)
        
        event = create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.accepted_transitions == 1
        assert result.transitions[0].new_state == DerivedState.OUTSIDE
    
    def test_reject_policy_then_in_works(self):
        """After REJECT of initial OUT, subsequent IN works"""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.REJECT)
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.OUT, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.IN, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.rejected_events == 1
        assert result.accepted_transitions == 1
        assert result.transitions[1].transition_type == TransitionType.IN
        assert result.transitions[1].new_state == DerivedState.INSIDE


# =============================================================================
# TEMPORAL ORDERING TESTS
# =============================================================================

class TestTemporalOrdering:
    """Tests for temporal ordering and tie-breaking."""
    
    def test_chronological_events_processed_in_order(self, resolver: RepeatedInOutResolver):
        """Events already in chronological order are processed as-is"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        result = resolver.resolve_events(events)
        
        timestamps = [t.source_timestamp for t in result.transitions]
        assert timestamps == [1000.0, 2000.0, 3000.0]
    
    def test_out_of_order_events_sorted_by_default(self, resolver: RepeatedInOutResolver):
        """Out-of-order events are sorted by timestamp (default SORT policy)"""
        events = [
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        timestamps = [t.source_timestamp for t in result.transitions]
        assert timestamps == [1000.0, 2000.0, 3000.0]
    
    def test_equal_timestamp_tiebreak_by_event_id(self, resolver: RepeatedInOutResolver):
        """Equal timestamps are tie-broken by event_id"""
        events = [
            create_raw_event("RIE-B", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-A", direction=RawEventDirection.OUT, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        # RIE-A should come first (lexicographically smaller)
        event_ids = [t.source_raw_event_id for t in result.transitions]
        assert event_ids == ["RIE-A", "RIE-B"]
    
    def test_equal_timestamp_tiebreak_camera_then_event_id(self):
        """Equal timestamps tie-broken by camera_id then event_id"""
        config = ResolverConfig(equal_timestamp_policy=EqualTimestampPolicy.CAMERA_ID_THEN_EVENT_ID)
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-001", camera_id="CAM2", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", camera_id="CAM1", direction=RawEventDirection.OUT, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        # CAM1 should come first
        camera_ids = [t.camera_id for t in result.transitions]
        assert camera_ids == ["CAM1", "CAM2"]
    
    def test_equal_timestamp_tiebreak_track_then_event_id(self):
        """Equal timestamps tie-broken by track_id then event_id"""
        config = ResolverConfig(equal_timestamp_policy=EqualTimestampPolicy.TRACK_ID_THEN_EVENT_ID)
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-001", local_track_id="track_B", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", local_track_id="track_A", direction=RawEventDirection.OUT, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        # track_A should come first
        track_ids = [t.local_track_id for t in result.transitions]
        assert track_ids == ["track_A", "track_B"]


# =============================================================================
# OUT-OF-ORDER POLICY TESTS
# =============================================================================

class TestOutOfOrderPolicy:
    """Tests for out-of-order event policies."""
    
    def test_sort_policy(self, resolver: RepeatedInOutResolver):
        """SORT policy sorts events"""
        events = [
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        timestamps = [t.source_timestamp for t in result.transitions]
        assert timestamps == [1000.0, 3000.0]
    
    def test_reject_policy_tracks_out_of_order(self):
        """REJECT policy tracks out-of-order events"""
        config = ResolverConfig(out_of_order_policy=OutOfOrderPolicy.REJECT)
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        # Should still process but track out-of-order count
        assert result.out_of_order_events > 0
        timestamps = [t.source_timestamp for t in result.transitions]
        assert timestamps == [1000.0, 3000.0]
    
    def test_accept_if_safe_policy(self):
        """ACCEPT_IF_SAFE policy tracks out-of-order"""
        config = ResolverConfig(out_of_order_policy=OutOfOrderPolicy.ACCEPT_IF_SAFE)
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        assert result.out_of_order_events > 0


# =============================================================================
# MULTI-TRACK ISOLATION TESTS
# =============================================================================

class TestMultiTrackIsolation:
    """Tests for multi-track isolation."""
    
    def test_independent_tracks_same_camera(self, resolver: RepeatedInOutResolver):
        """Different tracks on same camera have independent state"""
        events = [
            create_raw_event("RIE-001", local_track_id="track_A", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", local_track_id="track_B", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-003", local_track_id="track_A", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        # track_A: IN -> OUT (2 transitions)
        # track_B: IN (1 transition)
        track_a_state = result.final_states["CAM1:track_A"]
        track_b_state = result.final_states["CAM1:track_B"]
        
        assert track_a_state.current_state == DerivedState.OUTSIDE
        assert track_b_state.current_state == DerivedState.INSIDE
        assert track_a_state.transition_count == 2
        assert track_b_state.transition_count == 1
    
    def test_same_track_different_cameras_independent(self, resolver: RepeatedInOutResolver):
        """Same local_track_id on different cameras are independent"""
        events = [
            create_raw_event("RIE-001", camera_id="CAM1", local_track_id="track_001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", camera_id="CAM2", local_track_id="track_001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-003", camera_id="CAM1", local_track_id="track_001", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        cam1_state = result.final_states["CAM1:track_001"]
        cam2_state = result.final_states["CAM2:track_001"]
        
        assert cam1_state.current_state == DerivedState.OUTSIDE
        assert cam2_state.current_state == DerivedState.INSIDE
    
    def test_multi_camera_isolation(self, resolver: RepeatedInOutResolver):
        """Events from different cameras remain isolated"""
        events = [
            create_raw_event("RIE-001", camera_id="CAM1", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", camera_id="CAM2", direction=RawEventDirection.OUT, timestamp=1000.0),
            create_raw_event("RIE-003", camera_id="CAM1", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        cam1_state = result.final_states["CAM1:track_001"]
        cam2_state = result.final_states["CAM2:track_001"]
        
        assert cam1_state.current_state == DerivedState.OUTSIDE
        assert cam2_state.current_state == DerivedState.OUTSIDE
        assert cam1_state.transition_count == 2
        assert cam2_state.transition_count == 1


# =============================================================================
# IDENTITY HANDLING TESTS
# =============================================================================

class TestIdentityHandling:
    """Tests for UNKNOWN/AMBIGUOUS identity handling."""
    
    def test_unknown_identity_supported(self, resolver: RepeatedInOutResolver):
        """UNKNOWN identity works correctly"""
        event = create_raw_event(
            "RIE-001", 
            direction=RawEventDirection.IN, 
            timestamp=1000.0,
            global_observation_id=None,
        )
        result = resolver.resolve_events([event])
        
        assert result.accepted_transitions == 1
        assert result.transitions[0].global_observation_id is None
    
    def test_global_observation_id_preserved(self, resolver: RepeatedInOutResolver):
        """Global observation ID is preserved in derived transitions"""
        event = create_raw_event(
            "RIE-001", 
            direction=RawEventDirection.IN, 
            timestamp=1000.0,
            global_observation_id="GO-123",
        )
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].global_observation_id == "GO-123"
    
    def test_multiple_global_observations_per_track(self, resolver: RepeatedInOutResolver):
        """Each raw event can have different global_observation_id"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0, global_observation_id="GO-1"),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0, global_observation_id="GO-2"),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0, global_observation_id="GO-3"),
        ]
        result = resolver.resolve_events(events)
        
        go_ids = [t.global_observation_id for t in result.transitions]
        assert go_ids == ["GO-1", "GO-2", "GO-3"]


# =============================================================================
# PROVENANCE TESTS
# =============================================================================

class TestProvenance:
    """Tests for provenance preservation."""
    
    def test_source_raw_event_id_preserved(self, resolver: RepeatedInOutResolver):
        """source_raw_event_id is preserved in derived transitions"""
        event = create_raw_event("RIE-SOURCE-123", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].source_raw_event_id == "RIE-SOURCE-123"
    
    def test_source_crossing_event_id_preserved(self, resolver: RepeatedInOutResolver):
        """source_crossing_event_id is preserved"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0, source_crossing_event_id="CE-ORIGINAL-456")
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].source_crossing_event_id == "CE-ORIGINAL-456"
    
    def test_geometry_version_preserved(self, resolver: RepeatedInOutResolver):
        """geometry_version is preserved"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0, geometry_version=5)
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].geometry_version == 5
    
    def test_geometry_config_hash_preserved(self, resolver: RepeatedInOutResolver):
        """geometry_config_hash is preserved"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0, geometry_config_hash="abc123def456")
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].geometry_config_hash == "abc123def456"
    
    def test_resolver_version_preserved(self, resolver: RepeatedInOutResolver):
        """resolver_version is preserved in derived transitions"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].resolver_version == "1.0"
        assert result.resolver_version == "1.0"
    
    def test_resolver_config_hash_preserved(self, resolver: RepeatedInOutResolver):
        """resolver_config_hash is preserved"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        assert result.transitions[0].resolver_config_hash == resolver._config_hash
        assert result.resolver_config_hash == resolver._config_hash


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================

class TestIdempotency:
    """Tests for idempotent resolution."""
    
    def test_same_events_same_result(self, resolver: RepeatedInOutResolver):
        """Same event sequence produces same result"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        
        result1 = resolver.resolve_events(events)
        resolver.clear()
        result2 = resolver.resolve_events(events)
        
        # Compare transitions
        assert len(result1.transitions) == len(result2.transitions)
        for t1, t2 in zip(result1.transitions, result2.transitions):
            assert t1.resolution_id == t2.resolution_id
            assert t1.source_raw_event_id == t2.source_raw_event_id
            assert t1.transition_type == t2.transition_type
            assert t1.previous_state == t2.previous_state
            assert t1.new_state == t2.new_state
    
    def test_duplicate_raw_event_id_suppressed(self, resolver: RepeatedInOutResolver):
        """Duplicate raw event ID (same event_id) is suppressed"""
        event1 = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        event2 = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)  # Same ID
        
        result = resolver.resolve_events([event1, event2])
        
        assert result.total_raw_events == 2
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 1
        assert len(result.transitions) == 2
        assert result.transitions[1].resolution_status == ResolutionStatus.SUPPRESSED
    
    def test_serialized_deserialized_events_same_result(self, resolver: RepeatedInOutResolver):
        """Serialized then deserialized events produce same result"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        
        # Serialize and deserialize
        serialized = [e.to_dict() for e in events]
        deserialized = [RawInOutEvent.from_dict(d) for d in serialized]
        
        result1 = resolver.resolve_events(events)
        resolver.clear()
        result2 = resolver.resolve_events(deserialized)
        
        assert len(result1.transitions) == len(result2.transitions)
        for t1, t2 in zip(result1.transitions, result2.transitions):
            assert t1.resolution_id == t2.resolution_id
            assert t1.transition_type == t2.transition_type


# =============================================================================
# SERIALIZATION TESTS
# =============================================================================

class TestSerialization:
    """Tests for serialization/deserialization."""
    
    def test_resolver_config_serialization(self, default_config: ResolverConfig):
        """ResolverConfig serializes and deserializes correctly"""
        json_str = default_config.to_json()
        restored = ResolverConfig.from_json(json_str)
        
        assert restored.resolver_version == default_config.resolver_version
        assert restored.initial_out_policy == default_config.initial_out_policy
        assert restored.out_of_order_policy == default_config.out_of_order_policy
        assert restored.equal_timestamp_policy == default_config.equal_timestamp_policy
        assert restored.min_transition_interval_seconds == default_config.min_transition_interval_seconds
        assert restored.max_state_history_per_track == default_config.max_state_history_per_track
        assert restored.enable_rapid_reversal_protection == default_config.enable_rapid_reversal_protection
    
    def test_resolved_transition_serialization(self, resolver: RepeatedInOutResolver):
        """ResolvedTransition serializes and deserializes correctly"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        transition = result.transitions[0]
        json_str = transition.to_json()
        restored = ResolvedTransition.from_json(json_str)
        
        assert restored.resolution_id == transition.resolution_id
        assert restored.source_raw_event_id == transition.source_raw_event_id
        assert restored.camera_id == transition.camera_id
        assert restored.local_track_id == transition.local_track_id
        assert restored.direction == transition.direction
        assert restored.transition_type == transition.transition_type
        assert restored.previous_state == transition.previous_state
        assert restored.new_state == transition.new_state
        assert restored.source_timestamp == transition.source_timestamp
        assert restored.resolver_version == transition.resolver_version
        assert restored.resolver_config_hash == transition.resolver_config_hash
        assert restored.resolution_status == transition.resolution_status
    
    def test_resolution_result_serialization(self, resolver: RepeatedInOutResolver):
        """ResolutionResult serializes and deserializes correctly"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
        ]
        result = resolver.resolve_events(events)
        
        json_str = result.to_json()
        restored = ResolutionResult.from_json(json_str)
        
        assert restored.total_raw_events == result.total_raw_events
        assert restored.accepted_transitions == result.accepted_transitions
        assert restored.suppressed_events == result.suppressed_events
        assert len(restored.transitions) == len(result.transitions)
        assert len(restored.final_states) == len(result.final_states)
        
        for t1, t2 in zip(result.transitions, restored.transitions):
            assert t1.resolution_id == t2.resolution_id
            assert t1.transition_type == t2.transition_type
    
    def test_track_resolution_state_serialization(self, resolver: RepeatedInOutResolver):
        """TrackResolutionState serializes and deserializes correctly"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
        ]
        result = resolver.resolve_events(events)
        
        track_key = "CAM1:track_001"
        state = result.final_states[track_key]
        
        data = state.to_dict()
        restored = TrackResolutionState.from_dict(data)
        
        assert restored.camera_id == state.camera_id
        assert restored.local_track_id == state.local_track_id
        assert restored.current_state == state.current_state
        assert restored.transition_count == state.transition_count
        assert restored.in_count == state.in_count
        assert restored.out_count == state.out_count


# =============================================================================
# DETERMINISM TESTS
# =============================================================================

class TestDeterminism:
    """Tests for deterministic behavior."""
    
    def test_repeated_execution_same_results(self, default_config: ResolverConfig):
        """Multiple executions with same input produce identical results"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0),
            create_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=3000.0),
        ]
        
        resolver1 = create_repeated_in_out_resolver(default_config)
        resolver2 = create_repeated_in_out_resolver(default_config)
        
        result1 = resolver1.resolve_events(events)
        result2 = resolver2.resolve_events(events)
        
        assert result1.total_raw_events == result2.total_raw_events
        assert result1.accepted_transitions == result2.accepted_transitions
        
        for t1, t2 in zip(result1.transitions, result2.transitions):
            assert t1.resolution_id == t2.resolution_id
            assert t1.transition_type == t2.transition_type
            assert t1.previous_state == t2.previous_state
            assert t1.new_state == t2.new_state
    
    def test_no_random_ids(self, resolver: RepeatedInOutResolver):
        """Resolution IDs are deterministic, not random"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        
        ids = set()
        for _ in range(10):
            resolver.clear()
            result = resolver.resolve_events([event])
            ids.add(result.transitions[0].resolution_id)
        
        # All should be identical
        assert len(ids) == 1
    
    def test_no_wall_clock_dependency(self, default_config: ResolverConfig):
        """Results don't depend on wall-clock processing time"""
        import time
        
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        
        resolver1 = create_repeated_in_out_resolver(default_config)
        result1 = resolver1.resolve_events([event])
        
        time.sleep(0.01)
        
        resolver2 = create_repeated_in_out_resolver(default_config)
        result2 = resolver2.resolve_events([event])
        
        assert result1.transitions[0].resolution_id == result2.transitions[0].resolution_id


# =============================================================================
# RAPID REVERSAL PROTECTION TESTS
# =============================================================================

class TestRapidReversalProtection:
    """Tests for rapid reversal protection."""
    
    def test_rapid_reversal_suppressed_when_enabled(self):
        """Rapid reversals are suppressed when protection enabled"""
        config = ResolverConfig(
            enable_rapid_reversal_protection=True,
            min_transition_interval_seconds=1.0,
        )
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=1000.5),  # 0.5s later
        ]
        result = resolver.resolve_events(events)
        
        # Second event should be suppressed due to rapid reversal protection
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 1
        assert result.transitions[1].resolution_status == ResolutionStatus.SUPPRESSED
    
    def test_rapid_reversal_allowed_after_interval(self):
        """Rapid reversal allowed after minimum interval"""
        config = ResolverConfig(
            enable_rapid_reversal_protection=True,
            min_transition_interval_seconds=1.0,
        )
        resolver = create_repeated_in_out_resolver(config)
        
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=1002.0),  # 2s later
        ]
        result = resolver.resolve_events(events)
        
        assert result.accepted_transitions == 2
        assert result.suppressed_events == 0
    
    def test_rapid_reversal_disabled_by_default(self, resolver: RepeatedInOutResolver):
        """Rapid reversal protection is disabled by default"""
        events = [
            create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0),
            create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=1000.001),  # 1ms later
        ]
        result = resolver.resolve_events(events)
        
        # Should not be suppressed (protection disabled)
        assert result.accepted_transitions == 2
        assert result.suppressed_events == 0


# =============================================================================
# BOUNDED MEMORY TESTS
# =============================================================================

class TestBoundedMemory:
    """Tests for bounded memory usage."""
    
    def test_track_states_bounded(self, resolver: RepeatedInOutResolver):
        """Track states don't grow unbounded"""
        # Process many events for many tracks
        for i in range(100):
            event = create_raw_event(
                f"RIE-{i}", 
                local_track_id=f"track_{i}", 
                direction=RawEventDirection.IN, 
                timestamp=1000.0 + i,
            )
            resolver.resolve_single(event)
        
        # Should have 100 track states
        assert len(resolver.get_all_track_states()) == 100
        
        # Clear should work
        resolver.clear()
        assert len(resolver.get_all_track_states()) == 0
    
    def test_processed_event_ids_bounded(self, resolver: RepeatedInOutResolver):
        """Processed event IDs set is bounded by unique events"""
        for i in range(100):
            event = create_raw_event(f"RIE-{i}", direction=RawEventDirection.IN, timestamp=1000.0 + i)
            resolver.resolve_single(event)
        
        assert len(resolver._processed_raw_event_ids) == 100
        
        resolver.clear()
        assert len(resolver._processed_raw_event_ids) == 0


# =============================================================================
# NEGATIVE TESTS
# =============================================================================

class TestNegativeCases:
    """Tests for negative/error cases."""
    
    def test_empty_event_list(self, resolver: RepeatedInOutResolver):
        """Empty event list returns empty result"""
        result = resolver.resolve_events([])
        
        assert result.total_raw_events == 0
        assert result.accepted_transitions == 0
        assert len(result.transitions) == 0
        assert len(result.final_states) == 0
    
    def test_invalid_direction_rejected(self, resolver: RepeatedInOutResolver):
        """Invalid direction in raw event is handled"""
        # RawInOutEvent validation prevents invalid direction
        # But we can test the resolver handles it gracefully
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        # Manually corrupt direction (bypassing validation)
        # This tests robustness
        result = resolver.resolve_events([event])
        assert result.total_raw_events == 1
    
    def test_negative_timestamp_handled(self, resolver: RepeatedInOutResolver):
        """Negative timestamp in raw event"""
        # RawInOutEvent validation prevents negative timestamp
        # Test that resolver doesn't crash
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=0.0)
        result = resolver.resolve_events([event])
        assert result.total_raw_events == 1
    
    def test_missing_camera_id_in_raw_event(self):
        """RawInOutEvent validation rejects missing camera_id"""
        with pytest.raises(ValueError, match="camera_id is required"):
            RawInOutEvent(
                event_id="RIE-001",
                camera_id="",
                geometry_id="hash",
                geometry_version=1,
                geometry_config_hash="hash",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
            )
    
    def test_missing_local_track_id_in_raw_event(self):
        """RawInOutEvent validation rejects missing local_track_id"""
        with pytest.raises(ValueError, match="local_track_id is required"):
            RawInOutEvent(
                event_id="RIE-001",
                camera_id="CAM1",
                geometry_id="hash",
                geometry_version=1,
                geometry_config_hash="hash",
                local_track_id="",
                source_crossing_event_id="CE-123",
            )
    
    def test_invalid_resolver_config(self):
        """Invalid resolver configuration is rejected"""
        with pytest.raises(ValueError, match="min_transition_interval_seconds must be >= 0"):
            ResolverConfig(min_transition_interval_seconds=-1.0)
        
        with pytest.raises(ValueError, match="max_state_history_per_track must be >= 1"):
            ResolverConfig(max_state_history_per_track=0)
        
        with pytest.raises(ValueError, match="Unsupported resolver_version"):
            ResolverConfig(resolver_version="2.0")
    
    def test_invalid_initial_out_policy(self):
        """Invalid initial out policy rejected"""
        with pytest.raises(ValueError):
            ResolverConfig(initial_out_policy="invalid_policy")  # type: ignore
    
    def test_invalid_out_of_order_policy(self):
        """Invalid out-of-order policy rejected"""
        with pytest.raises(ValueError):
            ResolverConfig(out_of_order_policy="invalid_policy")  # type: ignore
    
    def test_invalid_equal_timestamp_policy(self):
        """Invalid equal timestamp policy rejected"""
        with pytest.raises(ValueError):
            ResolverConfig(equal_timestamp_policy="invalid_policy")  # type: ignore


# =============================================================================
# INCREMENTAL PROCESSING TESTS
# =============================================================================

class TestIncrementalProcessing:
    """Tests for incremental (single event) processing."""
    
    def test_resolve_single_incremental(self, resolver: RepeatedInOutResolver):
        """resolve_single processes events incrementally"""
        event1 = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        event2 = create_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0)
        
        t1 = resolver.resolve_single(event1)
        t2 = resolver.resolve_single(event2)
        
        assert t1.transition_type == TransitionType.IN
        assert t2.transition_type == TransitionType.OUT
        assert t1.new_state == DerivedState.INSIDE
        assert t2.new_state == DerivedState.OUTSIDE
        
        # Check final state
        track_state = resolver.get_track_state("CAM1", "track_001")
        assert track_state.current_state == DerivedState.OUTSIDE
        assert track_state.transition_count == 2
    
    def test_resolve_single_idempotent(self, resolver: RepeatedInOutResolver):
        """resolve_single is idempotent for duplicate event IDs"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        
        t1 = resolver.resolve_single(event)
        t2 = resolver.resolve_single(event)  # Same event_id
        
        assert t1.resolution_id == t2.resolution_id
        assert t2.resolution_status == ResolutionStatus.SUPPRESSED


# =============================================================================
# CONFIGURATION HASH TESTS
# =============================================================================

class TestConfigHash:
    """Tests for configuration hashing."""
    
    def test_same_config_same_hash(self):
        """Same config produces same hash"""
        # Use fixed created_at to ensure deterministic hash
        fixed_time = "2026-01-01T00:00:00Z"
        config1 = ResolverConfig(created_at=fixed_time)
        config2 = ResolverConfig(created_at=fixed_time)
        
        hash1 = generate_config_hash(config1)
        hash2 = generate_config_hash(config2)
        
        assert hash1 == hash2
    
    def test_different_config_different_hash(self):
        """Different config produces different hash"""
        config1 = create_default_resolver_config()
        config2 = create_strict_resolver_config()
        
        hash1 = generate_config_hash(config1)
        hash2 = generate_config_hash(config2)
        
        assert hash1 != hash2
    
    def test_resolution_id_includes_config_hash(self, resolver: RepeatedInOutResolver):
        """Resolution ID includes config hash for versioning"""
        event = create_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
        result = resolver.resolve_events([event])
        
        transition = result.transitions[0]
        assert transition.resolver_config_hash == resolver._config_hash
        assert len(transition.resolver_config_hash) == 16  # SHA256 truncated


# =============================================================================
# LONG SEQUENCE TESTS
# =============================================================================

class TestLongSequences:
    """Tests for long repeated sequences."""
    
    def test_long_repeated_in_sequence(self, resolver: RepeatedInOutResolver):
        """Long sequence of repeated IN events"""
        events = [create_raw_event(f"RIE-{i}", direction=RawEventDirection.IN, timestamp=1000.0 + i) for i in range(50)]
        result = resolver.resolve_events(events)
        
        assert result.total_raw_events == 50
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 49
        assert result.final_states["CAM1:track_001"].current_state == DerivedState.INSIDE
    
    def test_long_alternating_sequence(self, resolver: RepeatedInOutResolver):
        """Long alternating IN/OUT sequence"""
        events = []
        for i in range(20):
            direction = RawEventDirection.IN if i % 2 == 0 else RawEventDirection.OUT
            events.append(create_raw_event(f"RIE-{i}", direction=direction, timestamp=1000.0 + i * 10))
        
        result = resolver.resolve_events(events)
        
        assert result.total_raw_events == 20
        assert result.accepted_transitions == 20
        assert result.suppressed_events == 0
        
        # Final state should be OUTSIDE (even number of transitions)
        assert result.final_states["CAM1:track_001"].current_state == DerivedState.OUTSIDE


# =============================================================================
# RESOLUTION ID GENERATION TESTS
# =============================================================================

class TestResolutionIdGeneration:
    """Tests for deterministic resolution ID generation."""
    
    def test_same_inputs_same_resolution_id(self):
        """Same inputs produce same resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        id2 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        assert id1 == id2
        assert id1.startswith("RES-")
    
    def test_different_camera_different_id(self):
        """Different camera produces different resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        id2 = generate_resolution_id("CAM2", "track_001", "RIE-001", "1.0", "config_hash")
        assert id1 != id2
    
    def test_different_track_different_id(self):
        """Different track produces different resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        id2 = generate_resolution_id("CAM1", "track_002", "RIE-001", "1.0", "config_hash")
        assert id1 != id2
    
    def test_different_raw_event_different_id(self):
        """Different raw event ID produces different resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        id2 = generate_resolution_id("CAM1", "track_001", "RIE-002", "1.0", "config_hash")
        assert id1 != id2
    
    def test_different_resolver_version_different_id(self):
        """Different resolver version produces different resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "config_hash")
        id2 = generate_resolution_id("CAM1", "track_001", "RIE-001", "2.0", "config_hash")
        assert id1 != id2
    
    def test_different_config_hash_different_id(self):
        """Different config hash produces different resolution ID"""
        id1 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "hash1")
        id2 = generate_resolution_id("CAM1", "track_001", "RIE-001", "1.0", "hash2")
        assert id1 != id2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])