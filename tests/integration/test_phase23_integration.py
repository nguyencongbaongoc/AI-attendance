"""
Phase 23 — Integration Tests for Raw IN/OUT Event Engine.

Tests end-to-end integration with Phase 22 CrossingEngine and Phase 21 GlobalObservation.
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
# PHASE 22 INTEGRATION TESTS
# =============================================================================

class TestPhase22Integration:
    """Integration tests with Phase 22 CrossingEngine."""
    
    def test_crossing_engine_produces_events_convertible_to_raw(
        self, 
        crossing_engine: CrossingEngine, 
        raw_engine: RawEventEngine
    ):
        """Test that CrossingEngine events can be converted to RawInOutEvents."""
        # Get events from crossing engine (empty initially)
        crossing_events = crossing_engine.get_events()
        assert crossing_events == []
        
        # Convert to raw events
        raw_events = raw_engine.process_crossing_events(crossing_events)
        assert raw_events == []
    
    def test_manual_crossing_event_conversion(
        self, 
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test manual conversion of CrossingEvent to RawInOutEvent."""
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        event = result.event
        assert event.camera_id == "CAM1"
        assert event.local_track_id == "track_001"
        assert event.direction == RawEventDirection.IN
        assert event.global_observation_id == "GO-123"
        assert event.source_crossing_event_id == "CE-INTEGRATION-001"
        assert event.geometry_version == 1
    
    def test_multiple_cameras_independent_raw_events(
        self,
        line_geometry_config: CameraGeometryConfig,
        zone_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that events from different cameras remain independent."""
        geom_snapshot_1 = GeometryConfigSnapshot.from_config(line_geometry_config)
        geom_snapshot_2 = GeometryConfigSnapshot.from_config(zone_geometry_config)
        
        # Create crossing events from different cameras
        event1 = CrossingEvent(
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
        
        event2 = CrossingEvent(
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
        
        raw_engine.process_crossing_event(event1)
        raw_engine.process_crossing_event(event2)
        
        events = raw_engine.get_events()
        assert len(events) == 2
        
        # Both should be preserved independently
        cam1_events = raw_engine.get_events_by_camera("CAM1")
        cam2_events = raw_engine.get_events_by_camera("CAM2")
        
        assert len(cam1_events) == 1
        assert len(cam2_events) == 1
        assert cam1_events[0].local_track_id == "track_001"
        assert cam2_events[0].local_track_id == "track_001"
        assert cam1_events[0].event_id != cam2_events[0].event_id  # Different event IDs
    
    def test_direction_preserved_from_phase22(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that IN/OUT direction is preserved exactly from Phase 22."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Test IN
        in_event = CrossingEvent(
            event_id="CE-IN",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
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
        
        # Test OUT
        out_event = CrossingEvent(
            event_id="CE-OUT",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_002",
            global_observation_id=None,
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
        
        raw_engine.process_crossing_event(in_event)
        raw_engine.process_crossing_event(out_event)
        
        events = raw_engine.get_events()
        assert len(events) == 2
        assert events[0].direction == RawEventDirection.IN
        assert events[1].direction == RawEventDirection.OUT
    
    def test_timestamp_preserved_from_phase22(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that crossing_timestamp is preserved (not replaced with wall-clock)."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        original_timestamp = 1234567890.123456
        
        crossing_event = CrossingEvent(
            event_id="CE-TIMESTAMP",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=original_timestamp,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=100,
            current_frame_index=101,
            previous_timestamp=original_timestamp - 1.0,
            current_timestamp=original_timestamp,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        assert result.event.crossing_timestamp == original_timestamp
        # created_at should be from crossing event, not wall-clock
        assert result.event.created_at == "2026-01-01T00:00:00Z"
    
    def test_geometry_version_preserved_from_phase22(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that geometry_version is preserved from Phase 22."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-GEOM",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        assert result.event.geometry_version == line_geometry_config.version
        assert result.event.geometry_config_hash == line_geometry_config.config_hash
        assert result.event.geometry_id == line_geometry_config.config_hash
    
    def test_source_crossing_event_id_preserved(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that source_crossing_event_id is preserved."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-SOURCE-123",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        assert result.event.source_crossing_event_id == "CE-SOURCE-123"
    
    def test_provenance_chain_preserved(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test full provenance chain is preserved."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        traj_point = TrajectoryPoint(
            track_id="track_001",
            frame_index=100,
            timestamp=1234567890.5,
            position=Point2D(960, 480),
            bbox=(900, 400, 1020, 560),
            camera_id="CAM1",
            global_observation_id="GO-123",
        )
        
        crossing_event = CrossingEvent(
            event_id="CE-PROVENANCE",
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
            trajectory_points=[traj_point],
            config_snapshot=line_geometry_config.crossing_policy.to_dict(),
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        event = result.event
        
        # Check trajectory points preserved
        assert len(event.trajectory_points) == 1
        assert event.trajectory_points[0]["track_id"] == "track_001"
        assert event.trajectory_points[0]["global_observation_id"] == "GO-123"
        assert "position" in event.trajectory_points[0]
        assert "bbox" in event.trajectory_points[0]
        
        # Check config snapshot preserved
        assert event.config_snapshot == line_geometry_config.crossing_policy.to_dict()
        
        # Check identity evidence ref preserved
        assert event.identity_evidence_ref == "GO-123"


# =============================================================================
# PHASE 21 INTEGRATION TESTS
# =============================================================================

class TestPhase21Integration:
    """Integration tests with Phase 21 GlobalObservation."""
    
    def test_global_observation_id_preserved(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        sample_global_observation: GlobalObservation
    ):
        """Test that GlobalObservation ID is preserved when available."""
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        assert result.event.global_observation_id == sample_global_observation.global_observation_id
        assert result.event.identity_evidence_ref == sample_global_observation.global_observation_id
    
    def test_unknown_identity_supported(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that UNKNOWN identity is supported (no global observation)."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        crossing_event = CrossingEvent(
            event_id="CE-UNKNOWN",
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        assert result.event.identity_certainty == IdentityCertainty.UNKNOWN
        assert result.event.identity_candidate is None
        assert result.event.identity_confidence == 0.0
        assert result.event.identity_evidence_ref is None
    
    def test_ambiguous_identity_supported(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that AMBIGUOUS identity can be represented."""
        # The current implementation defaults to UNKNOWN
        # But the contract supports AMBIGUOUS - this test verifies the enum exists
        assert IdentityCertainty.AMBIGUOUS in IdentityCertainty
        assert IdentityCertainty.INSUFFICIENT in IdentityCertainty
    
    def test_no_rerun_of_phase21_fusion(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine,
        sample_global_observation: GlobalObservation
    ):
        """Test that Phase 23 does NOT rerun Phase 21 fusion."""
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
        
        result = raw_engine.process_crossing_event(crossing_event)
        
        assert result.success
        # Global observation ID is preserved as reference, not re-fused
        assert result.event.global_observation_id == sample_global_observation.global_observation_id
        # No new GlobalObservation is created
        assert not hasattr(result.event, 'association_state')
        assert not hasattr(result.event, 'association_evidence')


# =============================================================================
# FACTORY INTEGRATION TESTS
# =============================================================================

class TestFactoryIntegration:
    """Tests for factory integration functions."""
    
    def test_create_integrated_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig
    ):
        """Test creating integrated Phase 22 + Phase 23 pipeline."""
        crossing_engine, raw_engine = create_integrated_pipeline(line_geometry_config)
        
        assert isinstance(crossing_engine, CrossingEngine)
        assert isinstance(raw_engine, RawEventEngine)
        assert crossing_engine.geometry_config.camera_id == "CAM1"
    
    def test_process_tracks_through_pipeline(
        self,
        line_geometry_config: CameraGeometryConfig
    ):
        """Test complete pipeline function (tracks -> raw events)."""
        # This function requires Track objects which we can't easily create
        # without the vision module. Test that it doesn't crash with empty list.
        raw_events = process_tracks_through_pipeline(
            tracks=[],
            geometry_config=line_geometry_config,
            frame_index=0,
            timestamp=1000.0,
        )
        
        assert raw_events == []


# =============================================================================
# END-TO-END SCENARIO TESTS
# =============================================================================

class TestEndToEndScenarios:
    """End-to-end scenario tests."""
    
    def test_in_out_sequence_preserved(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that IN -> OUT -> IN sequence preserves all events independently."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Create sequence of crossing events
        events = [
            CrossingEvent(
                event_id="CE-SEQ-1",
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
            ),
            CrossingEvent(
                event_id="CE-SEQ-2",
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
            ),
            CrossingEvent(
                event_id="CE-SEQ-3",
                camera_id="CAM1",
                geometry_config=geom_snapshot,
                local_track_id="track_001",
                global_observation_id="GO-3",
                event_type=CrossingEventType.LINE_CROSSING,
                direction=CrossingDirection.IN,
                crossing_point=Point2D(960, 500),
                crossing_timestamp=3000.0,
                previous_position=Point2D(960, 480),
                current_position=Point2D(960, 520),
                previous_frame_index=300,
                current_frame_index=301,
                previous_timestamp=2999.0,
                current_timestamp=3000.0,
                crossing_distance=40.0,
                side_transition="SIDE_A->SIDE_B",
                trajectory_points=[],
                config_snapshot={},
                created_at="2026-01-01T00:00:00Z",
                version="1.0",
            ),
        ]
        
        for event in events:
            result = raw_engine.process_crossing_event(event)
            assert result.success
        
        raw_events = raw_engine.get_events()
        assert len(raw_events) == 3
        
        # All three preserved independently - no collapsing to current state
        directions = [e.direction for e in raw_events]
        assert directions == [RawEventDirection.IN, RawEventDirection.OUT, RawEventDirection.IN]
        
        timestamps = [e.crossing_timestamp for e in raw_events]
        assert timestamps == [1000.0, 2000.0, 3000.0]
        
        # Each has its own global_observation_id
        go_ids = [e.global_observation_id for e in raw_events]
        assert go_ids == ["GO-1", "GO-2", "GO-3"]
    
    def test_out_of_order_input_handled(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that out-of-order input is handled correctly."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Create events with timestamps out of order
        event_late = CrossingEvent(
            event_id="CE-LATE",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=3000.0,  # Latest
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=300,
            current_frame_index=301,
            previous_timestamp=2999.0,
            current_timestamp=3000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        event_early = CrossingEvent(
            event_id="CE-EARLY",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,  # Earliest
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
        
        event_middle = CrossingEvent(
            event_id="CE-MIDDLE",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=2000.0,  # Middle
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=200,
            current_frame_index=201,
            previous_timestamp=1999.0,
            current_timestamp=2000.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        # Process in random order
        raw_engine.process_crossing_event(event_late)
        raw_engine.process_crossing_event(event_early)
        raw_engine.process_crossing_event(event_middle)
        
        raw_events = raw_engine.get_events()
        assert len(raw_events) == 3
        
        # Should be sorted chronologically
        timestamps = [e.crossing_timestamp for e in raw_events]
        assert timestamps == [1000.0, 2000.0, 3000.0]
    
    def test_equal_timestamp_deterministic_ordering(
        self,
        line_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test deterministic ordering for equal timestamps."""
        geom_snapshot = GeometryConfigSnapshot.from_config(line_geometry_config)
        
        # Two events with same timestamp, different tracks
        event_a = CrossingEvent(
            event_id="CE-A",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_A",
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
        
        event_b = CrossingEvent(
            event_id="CE-B",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_B",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1000.0,  # Same timestamp
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
        
        raw_engine.process_crossing_event(event_a)
        raw_engine.process_crossing_event(event_b)
        
        raw_events = raw_engine.get_events()
        assert len(raw_events) == 2
        
        # Should have deterministic tie-breaking (by event_id)
        event_ids = [e.event_id for e in raw_events]
        assert event_ids == sorted(event_ids)  # Deterministic order
    
    def test_zone_and_line_events_coexist(
        self,
        line_geometry_config: CameraGeometryConfig,
        zone_geometry_config: CameraGeometryConfig,
        raw_engine: RawEventEngine
    ):
        """Test that LINE and ZONE events coexist in raw event history."""
        geom_snapshot_line = GeometryConfigSnapshot.from_config(line_geometry_config)
        geom_snapshot_zone = GeometryConfigSnapshot.from_config(zone_geometry_config)
        
        line_event = CrossingEvent(
            event_id="CE-LINE",
            camera_id="CAM1",
            geometry_config=geom_snapshot_line,
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
        
        zone_event = CrossingEvent(
            event_id="CE-ZONE",
            camera_id="CAM2",
            geometry_config=geom_snapshot_zone,
            local_track_id="track_002",
            global_observation_id=None,
            event_type=CrossingEventType.ZONE_ENTRY,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(300, 100),
            crossing_timestamp=2000.0,
            previous_position=Point2D(300, 80),
            current_position=Point2D(300, 120),
            previous_frame_index=200,
            current_frame_index=201,
            previous_timestamp=1999.0,
            current_timestamp=2000.0,
            crossing_distance=40.0,
            side_transition="OUTSIDE->INSIDE",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        raw_engine.process_crossing_event(line_event)
        raw_engine.process_crossing_event(zone_event)
        
        raw_events = raw_engine.get_events()
        assert len(raw_events) == 2
        
        event_types = [e.event_type for e in raw_events]
        assert RawEventType.LINE_CROSSING in event_types
        assert RawEventType.ZONE_ENTRY in event_types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])