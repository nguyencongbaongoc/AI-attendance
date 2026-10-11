"""
Phase 24 — Integration Tests for Repeated IN/OUT Resolver.

Tests end-to-end integration with Phase 22 CrossingEngine and Phase 23 RawEventEngine.
"""

import pytest
from typing import List

from app.geometry.contract import (
    CameraGeometryConfig,
    DirectionSemantics,
    GeometryType,
    Point2D,
    create_line_geometry,
    create_zone_geometry,
)
from app.geometry.crossing import (
    CrossingDirection,
    CrossingEvent,
    CrossingEventType,
    CrossingEngine,
    TrajectoryPoint,
    create_crossing_engine,
    process_tracks_for_crossings,
)
from app.geometry.contract import GeometryConfigSnapshot
from app.replay.fusion import (
    GlobalObservation,
    LocalObservationRef,
    AssociationState,
    AssociationEvidence,
    ReplayTimestamp,
    CrossCameraFusionEngine,
    FusionConfig,
    create_fusion_engine,
)
from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
)
from app.in_out.raw_event import (
    RawEventEngine,
    create_raw_event_engine,
    create_raw_in_out_event,
)
from app.in_out.factory import (
    create_integrated_pipeline,
    process_tracks_through_pipeline,
)
from app.in_out.resolver import (
    RepeatedInOutResolver,
    create_repeated_in_out_resolver,
    resolve_raw_events,
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
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def line_geometry_config() -> CameraGeometryConfig:
    """Create a line geometry configuration for testing."""
    return create_line_geometry(
        camera_id="CAM1",
        frame_width=1920,
        frame_height=1080,
        p1=(100, 500),
        p2=(1820, 500),
        direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        version=1,
    )


@pytest.fixture
def zone_geometry_config() -> CameraGeometryConfig:
    """Create a zone geometry configuration for testing."""
    return create_zone_geometry(
        camera_id="CAM2",
        frame_width=1920,
        frame_height=1080,
        vertices=[(100, 100), (500, 100), (500, 500), (100, 500)],
        direction_semantics=DirectionSemantics.OUTSIDE_TO_INSIDE_IN,
        version=1,
    )


@pytest.fixture
def crossing_engine(line_geometry_config: CameraGeometryConfig) -> CrossingEngine:
    """Create a CrossingEngine for testing."""
    return create_crossing_engine(line_geometry_config)


@pytest.fixture
def raw_engine() -> RawEventEngine:
    """Create a RawEventEngine for testing."""
    return create_raw_event_engine()


@pytest.fixture
def resolver() -> RepeatedInOutResolver:
    """Create a RepeatedInOutResolver for testing."""
    return create_repeated_in_out_resolver(create_default_resolver_config())


@pytest.fixture
def sample_global_observation() -> GlobalObservation:
    """Create a sample GlobalObservation for testing."""
    obs1 = LocalObservationRef(
        camera_id="CAM1",
        local_track_id="track_001",
        observation_id="CAM1_track_001_f100",
        frame_index=100,
        timestamp=ReplayTimestamp(value=1234567890.5, source="frame_metadata"),
        detection_id="det_001",
        face_crop_id="crop_001",
        quality_class="GOOD",
    )
    obs2 = LocalObservationRef(
        camera_id="CAM2",
        local_track_id="track_002",
        observation_id="CAM2_track_002_f100",
        frame_index=100,
        timestamp=ReplayTimestamp(value=1234567890.6, source="frame_metadata"),
        detection_id="det_002",
        face_crop_id="crop_002",
        quality_class="GOOD",
    )
    
    evidence = AssociationEvidence(
        timestamp_delta=0.1,
        timestamp_compatible=True,
        timestamp_tolerance=1.0,
        camera_ids=("CAM1", "CAM2"),
    )
    
    return GlobalObservation(
        global_observation_id="GO-INTEGRATION-123",
        observations=(obs1, obs2),
        association_state=AssociationState.ASSOCIATED,
        association_evidence=evidence,
        temporal_start=ReplayTimestamp(value=1234567890.5, source="fusion_min"),
        temporal_end=ReplayTimestamp(value=1234567890.6, source="fusion_max"),
        temporal_span=0.1,
        camera_ids=("CAM1", "CAM2"),
        local_track_ids=("CAM1:track_001", "CAM2:track_002"),
        primary_identity_candidate="person_123",
        identity_confidence=0.85,
        config_snapshot={},
        model_versions={},
    )


# =============================================================================
# PHASE 22 → 23 → 24 INTEGRATION TESTS
# =============================================================================

class TestPhase22To24Integration:
    """Integration tests for Phase 22 → 23 → 24 pipeline."""
    
    def test_crossing_engine_to_raw_engine_to_resolver(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver
    ):
        """Test full pipeline: CrossingEngine → RawEventEngine → RepeatedInOutResolver."""
        # Create a crossing event manually (simulating Phase 22 output)
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-INTEGRATION-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id="GO-123",
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1234567890.5,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=1234567889.5,
            current_timestamp=1234567890.5,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot=line_geometry_config.crossing_policy.to_dict(),
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23: Convert to RawInOutEvent
        raw_result = raw_engine.process_crossing_event(crossing_event)
        assert raw_result.success
        raw_event = raw_result.event
        
        # Phase 24: Resolve to derived transition
        result = resolver.resolve_events([raw_event])
        
        assert result.total_raw_events == 1
        assert result.accepted_transitions == 1
        assert len(result.transitions) == 1
        
        transition = result.transitions[0]
        assert transition.previous_state == DerivedState.UNKNOWN
        assert transition.new_state == DerivedState.INSIDE
        assert transition.transition_type == TransitionType.IN
        assert transition.resolution_status == ResolutionStatus.ACCEPTED
        
        # Verify provenance chain
        assert transition.source_raw_event_id == raw_event.event_id
        assert transition.source_crossing_event_id == "CE-INTEGRATION-001"
        assert transition.global_observation_id == "GO-123"
        assert transition.geometry_version == 1
        assert transition.resolver_version == "1.0"
    
    def test_in_out_sequence_through_full_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver
    ):
        """Test IN → OUT sequence through full pipeline."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Create IN crossing event
        in_crossing = CrossingEvent(
            event_id="CE-IN-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id="GO-1",
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Create OUT crossing event
        out_crossing = CrossingEvent(
            event_id="CE-OUT-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id="GO-2",
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.OUT,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=2000.0,
            previous_position=Point2D(960, 520),
            current_position=Point2D(960, 480),
            previous_frame_index=200,
            current_frame_index=201,
            previous_timestamp=1999.0,
            current_timestamp=2000.0,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23: Convert both
        raw_in = raw_engine.process_crossing_event(in_crossing)
        raw_out = raw_engine.process_crossing_event(out_crossing)
        
        assert raw_in.success and raw_out.success
        
        # Phase 24: Resolve sequence
        result = resolver.resolve_events([raw_in.event, raw_out.event])
        
        assert result.total_raw_events == 2
        assert result.accepted_transitions == 2
        assert result.suppressed_events == 0
        
        # Check transitions
        t1, t2 = result.transitions
        assert t1.transition_type == TransitionType.IN
        assert t1.new_state == DerivedState.INSIDE
        assert t2.transition_type == TransitionType.OUT
        assert t2.new_state == DerivedState.OUTSIDE
        
        # Final state
        track_key = "CAM1:track_001"
        assert result.final_states[track_key].current_state == DerivedState.OUTSIDE
    
    def test_repeated_events_suppressed_in_resolver(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver
    ):
        """Test that repeated raw events are suppressed in resolver."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Create multiple IN crossing events (simulating jitter)
        crossing_events = []
        for i in range(3):
            crossing = CrossingEvent(
                event_id=f"CE-IN-{i}",
                camera_id="CAM1",
                geometry_config=geom_snapshot,
                local_track_id="track_001",
                global_observation_id=f"GO-{i}",
                event_type=CrossingEventType.LINE_CROSSING,
                direction=CrossingDirection.IN,
                crossing_point=Point2D(960, 500),
                crossing_timestamp=1000.0 + i,
                previous_position=Point2D(960, 480),
                current_position=Point2D(960, 520),
                previous_frame_index=100 + i,
                current_frame_index=101 + i,
                previous_timestamp=999.0 + i,
                current_timestamp=1000.0 + i,
                crossing_distance=40.0,
                side_transition="SIDE_A->SIDE_B",
                trajectory_points=[],
                config_snapshot={},
                created_at="2026-01-01T00:00:00Z",
                version="1.0",
            )
            crossing_events.append(crossing)
        
        # Phase 23: Convert all
        raw_results = raw_engine.process_crossing_events(crossing_events)
        raw_events = [r.event for r in raw_results if r.success]
        
        assert len(raw_events) == 3  # All raw events preserved
        
        # Phase 24: Resolve - should suppress repeated IN
        result = resolver.resolve_events(raw_events)
        
        assert result.total_raw_events == 3
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 2
        
        # Only first event produces transition
        assert result.transitions[0].transition_type == TransitionType.IN
        assert result.transitions[1].transition_type == TransitionType.NONE
        assert result.transitions[2].transition_type == TransitionType.NONE
        
        # Final state still INSIDE
        track_key = "CAM1:track_001"
        assert result.final_states[track_key].current_state == DerivedState.INSIDE
    
    def test_multi_camera_isolation_through_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig,
        zone_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver
    ):
        """Test multi-camera isolation through full pipeline."""
        geom_snapshot_1 = GeometryConfigSnapshot.from_config(line_geometry_config)
        geom_snapshot_2 = GeometryConfigSnapshot.from_config(zone_geometry_config)
        
        # Create crossing events from different cameras
        cam1_crossing = CrossingEvent(
            event_id="CE-CAM1-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot_1,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        cam2_crossing = CrossingEvent(
            event_id="CE-CAM2-001",
            camera_id="CAM2",
            geometry_config=geom_snapshot_2,
            local_track_id="track_001",  # Same local track ID, different camera
            global_observation_id=None,
            event_type=CrossingEventType.ZONE_ENTRY,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(300, 100),
            crossing_timestamp=1000.0,
            previous_position=Point2D(300, 80),
            current_position=Point2D(300, 120),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="OUTSIDE->INSIDE",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23: Convert both
        raw_cam1 = raw_engine.process_crossing_event(cam1_crossing)
        raw_cam2 = raw_engine.process_crossing_event(cam2_crossing)
        
        assert raw_cam1.success and raw_cam2.success
        
        # Phase 24: Resolve - should remain independent
        result = resolver.resolve_events([raw_cam1.event, raw_cam2.event])
        
        assert result.total_raw_events == 2
        assert result.accepted_transitions == 2
        
        # Both tracks should be INSIDE independently
        cam1_state = result.final_states["CAM1:track_001"]
        cam2_state = result.final_states["CAM2:track_001"]
        
        assert cam1_state.current_state == DerivedState.INSIDE
        assert cam2_state.current_state == DerivedState.INSIDE
        assert cam1_state.transition_count == 1
        assert cam2_state.transition_count == 1
    
    def test_global_observation_id_preserved_through_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver,
        sample_global_observation: GlobalObservation
    ):
        """Test that GlobalObservation ID is preserved through full pipeline."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-GO-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=sample_global_observation.global_observation_id,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1234567890.5,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=1234567889.5,
            current_timestamp=1234567890.5,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23
        raw_result = raw_engine.process_crossing_event(crossing_event)
        assert raw_result.success
        assert raw_result.event.global_observation_id == sample_global_observation.global_observation_id
        
        # Phase 24
        result = resolver.resolve_events([raw_result.event])
        
        assert result.accepted_transitions == 1
        assert result.transitions[0].global_observation_id == sample_global_observation.global_observation_id
    
    def test_unknown_identity_supported_through_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver
    ):
        """Test that UNKNOWN identity works through full pipeline."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-UNKNOWN-001",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=None,  # No global observation
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23
        raw_result = raw_engine.process_crossing_event(crossing_event)
        assert raw_result.success
        assert raw_result.event.identity_certainty == IdentityCertainty.UNKNOWN
        assert raw_result.event.global_observation_id is None
        
        # Phase 24
        result = resolver.resolve_events([raw_result.event])
        
        assert result.accepted_transitions == 1
        assert result.transitions[0].global_observation_id is None
        assert result.final_states["CAM1:track_001"].current_state == DerivedState.INSIDE
    
    def test_no_rerun_of_phase21_fusion(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        resolver: RepeatedInOutResolver,
        sample_global_observation: GlobalObservation
    ):
        """Test that Phase 24 does NOT rerun Phase 21 fusion."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-NO-RERUN",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=sample_global_observation.global_observation_id,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Phase 23
        raw_result = raw_engine.process_crossing_event(crossing_event)
        assert raw_result.success
        
        # Phase 24
        result = resolver.resolve_events([raw_result.event])
        
        assert result.accepted_transitions == 1
        # Global observation ID preserved as reference, not re-fused
        assert result.transitions[0].global_observation_id == sample_global_observation.global_observation_id
        # No new GlobalObservation created
        assert not hasattr(result.transitions[0], 'association_state')
        assert not hasattr(result.transitions[0], 'association_evidence')


# =============================================================================
# RESOLVER CONFIGURATION TESTS
# =============================================================================

class TestResolverConfiguration:
    """Tests for resolver configuration options."""
    
    def test_initial_out_policy_accept(self):
        """Test ACCEPT policy for initial OUT."""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.ACCEPT)
        resolver = create_repeated_in_out_resolver(config)
        
        # Create raw OUT event
        raw_event = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.OUT,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=520.0,
            current_position_x=960.0,
            current_position_y=480.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([raw_event])
        
        assert result.accepted_transitions == 1
        assert result.rejected_events == 0
        assert result.transitions[0].new_state == DerivedState.OUTSIDE
    
    def test_initial_out_policy_reject(self):
        """Test REJECT policy for initial OUT."""
        config = ResolverConfig(initial_out_policy=InitialOutPolicy.REJECT)
        resolver = create_repeated_in_out_resolver(config)
        
        raw_event = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.OUT,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=520.0,
            current_position_x=960.0,
            current_position_y=480.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([raw_event])
        
        assert result.accepted_transitions == 0
        assert result.rejected_events == 1
        assert result.transitions[0].resolution_status == ResolutionStatus.REJECTED
        assert result.transitions[0].new_state == DerivedState.UNKNOWN
        
        # Final state should be UNKNOWN
        track_key = "CAM1:track_001"
        assert result.final_states[track_key].current_state == DerivedState.UNKNOWN
    
    def test_out_of_order_sort_policy(self):
        """Test SORT policy for out-of-order events."""
        config = ResolverConfig(out_of_order_policy=OutOfOrderPolicy.SORT)
        resolver = create_repeated_in_out_resolver(config)
        
        # Create events out of order
        event_late = RawInOutEvent(
            event_id="RIE-003",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=3000.0,
            crossing_frame_index=300,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=299,
            current_frame_index=300,
            previous_timestamp=2999.0,
            current_timestamp=3000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        event_early = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        # Process out of order
        result = resolver.resolve_events([event_late, event_early])
        
        # Should be sorted chronologically
        timestamps = [t.source_timestamp for t in result.transitions]
        assert timestamps == [1000.0, 3000.0]
    
    def test_equal_timestamp_tiebreak_event_id(self):
        """Test EVENT_ID tie-breaking for equal timestamps."""
        config = ResolverConfig(equal_timestamp_policy=EqualTimestampPolicy.EVENT_ID)
        resolver = create_repeated_in_out_resolver(config)
        
        event_b = RawInOutEvent(
            event_id="RIE-B",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        event_a = RawInOutEvent(
            event_id="RIE-A",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.OUT,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=520.0,
            current_position_x=960.0,
            current_position_y=480.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([event_b, event_a])
        
        # RIE-A should come first (lexicographically smaller)
        event_ids = [t.source_raw_event_id for t in result.transitions]
        assert event_ids == ["RIE-A", "RIE-B"]
    
    def test_rapid_reversal_protection(self):
        """Test rapid reversal protection when enabled."""
        config = ResolverConfig(
            enable_rapid_reversal_protection=True,
            min_transition_interval_seconds=1.0,
        )
        resolver = create_repeated_in_out_resolver(config)
        
        # Create IN then rapid OUT (0.5s later)
        event_in = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        event_out = RawInOutEvent(
            event_id="RIE-002",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.OUT,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.5,  # 0.5s later
            crossing_frame_index=101,
            previous_position_x=960.0,
            previous_position_y=520.0,
            current_position_x=960.0,
            current_position_y=480.0,
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=1000.0,
            current_timestamp=1000.5,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([event_in, event_out])
        
        # Second event should be suppressed due to rapid reversal protection
        assert result.accepted_transitions == 1
        assert result.suppressed_events == 1
        assert result.transitions[1].resolution_status == ResolutionStatus.SUPPRESSED
    
    def test_rapid_reversal_disabled_by_default(self):
        """Test rapid reversal protection is disabled by default."""
        resolver = create_repeated_in_out_resolver(create_default_resolver_config())
        
        # Create IN then rapid OUT (1ms later)
        event_in = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        event_out = RawInOutEvent(
            event_id="RIE-002",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.OUT,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.001,  # 1ms later
            crossing_frame_index=101,
            previous_position_x=960.0,
            previous_position_y=520.0,
            current_position_x=960.0,
            current_position_y=480.0,
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=1000.0,
            current_timestamp=1000.001,
            crossing_distance=40.0,
            side_transition="SIDE_B->SIDE_A",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([event_in, event_out])
        
        # Should not be suppressed (protection disabled)
        assert result.accepted_transitions == 2
        assert result.suppressed_events == 0


# =============================================================================
# DETERMINISM AND SERIALIZATION TESTS
# =============================================================================

class TestDeterminismAndSerialization:
    """Tests for determinism and serialization."""
    
    def test_deterministic_resolution_ids(self):
        """Test that resolution IDs are deterministic."""
        resolver = create_repeated_in_out_resolver(create_default_resolver_config())
        
        raw_event = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        ids = set()
        for _ in range(10):
            resolver.clear()
            result = resolver.resolve_events([raw_event])
            ids.add(result.transitions[0].resolution_id)
        
        # All should be identical
        assert len(ids) == 1
    
    def test_resolver_config_serialization(self):
        """Test ResolverConfig serialization round-trip."""
        config = create_default_resolver_config()
        
        json_str = config.to_json()
        restored = ResolverConfig.from_json(json_str)
        
        assert restored.resolver_version == config.resolver_version
        assert restored.initial_out_policy == config.initial_out_policy
        assert restored.out_of_order_policy == config.out_of_order_policy
        assert restored.equal_timestamp_policy == config.equal_timestamp_policy
        assert restored.min_transition_interval_seconds == config.min_transition_interval_seconds
        assert restored.max_state_history_per_track == config.max_state_history_per_track
        assert restored.enable_rapid_reversal_protection == config.enable_rapid_reversal_protection
    
    def test_resolution_result_serialization(self, resolver: RepeatedInOutResolver):
        """Test ResolutionResult serialization round-trip."""
        raw_event = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([raw_event])
        
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
    
    def test_resolved_transition_serialization(self, resolver: RepeatedInOutResolver):
        """Test ResolvedTransition serialization round-trip."""
        raw_event = RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="hash123",
            geometry_version=1,
            geometry_config_hash="hash123",
            local_track_id="track_001",
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=960.0,
            crossing_point_y=500.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=960.0,
            previous_position_y=480.0,
            current_position_x=960.0,
            current_position_y=520.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.0,
            current_timestamp=1000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            source_crossing_event_id="CE-123",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
        )
        
        result = resolver.resolve_events([raw_event])
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


# =============================================================================
# BOUNDED MEMORY TESTS
# =============================================================================

class TestBoundedMemory:
    """Tests for bounded memory usage."""
    
    def test_track_states_bounded(self, resolver: RepeatedInOutResolver):
        """Test that track states don't grow unbounded."""
        # Process many events for many tracks
        for i in range(100):
            raw_event = RawInOutEvent(
                event_id=f"RIE-{i}",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id=f"track_{i}",
                global_observation_id=None,
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=960.0,
                crossing_point_y=500.0,
                crossing_timestamp=1000.0 + i,
                crossing_frame_index=100 + i,
                previous_position_x=960.0,
                previous_position_y=480.0,
                current_position_x=960.0,
                current_position_y=520.0,
                previous_frame_index=99 + i,
                current_frame_index=100 + i,
                previous_timestamp=999.0 + i,
                current_timestamp=1000.0 + i,
                crossing_distance=40.0,
                side_transition="SIDE_A->SIDE_B",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref=None,
                source_crossing_event_id=f"CE-{i}",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
                created_at="2026-01-01T00:00:00Z",
            )
            resolver.resolve_single(raw_event)
        
        # Should have 100 track states
        assert len(resolver.get_all_track_states()) == 100
        
        # Clear should work
        resolver.clear()
        assert len(resolver.get_all_track_states()) == 0
    
    def test_processed_event_ids_bounded(self, resolver: RepeatedInOutResolver):
        """Test that processed event IDs set is bounded by unique events."""
        for i in range(100):
            raw_event = RawInOutEvent(
                event_id=f"RIE-{i}",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                global_observation_id=None,
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=960.0,
                crossing_point_y=500.0,
                crossing_timestamp=1000.0 + i,
                crossing_frame_index=100 + i,
                previous_position_x=960.0,
                previous_position_y=480.0,
                current_position_x=960.0,
                current_position_y=520.0,
                previous_frame_index=99 + i,
                current_frame_index=100 + i,
                previous_timestamp=999.0 + i,
                current_timestamp=1000.0 + i,
                crossing_distance=40.0,
                side_transition="SIDE_A->SIDE_B",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref=None,
                source_crossing_event_id=f"CE-{i}",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
                created_at="2026-01-01T00:00:00Z",
            )
            resolver.resolve_single(raw_event)
        
        assert len(resolver._processed_raw_event_ids) == 100
        
        resolver.clear()
        assert len(resolver._processed_raw_event_ids) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])