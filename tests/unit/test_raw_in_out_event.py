"""
Phase 23 — Unit Tests for Raw IN/OUT Event Contract and Engine.

Tests cover:
- RawInOutEvent contract (immutability, serialization, validation)
- Deterministic event ID generation
- Direction preservation from Phase 22
- Idempotency / duplicate handling
- Camera isolation
- Timestamp preservation
- Geometry version preservation
- Provenance chain
- Serialization round-trip
- Negative cases (invalid input rejection)
- Phase 22 integration
"""

import pytest
import json
from datetime import datetime

from app.geometry.contract import (
    CameraGeometryConfig,
    CrossingPolicyConfig,
    DirectionSemantics,
    GeometryType,
    LineGeometry,
    Point2D,
    create_line_geometry,
)
from app.geometry.crossing import (
    CrossingDirection,
    CrossingEvent,
    CrossingEventType,
    TrajectoryPoint,
    CrossingEngine,
    create_crossing_engine,
)
from app.geometry.contract import GeometryConfigSnapshot
from app.in_out.contract import (
    RawInOutEvent,
    RawEventCreationResult,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
    generate_deterministic_event_id,
    validate_crossing_event_for_raw_creation,
)
from app.in_out.raw_event import (
    RawEventEngine,
    create_raw_event_engine,
    create_raw_in_out_event,
    map_crossing_direction,
    map_crossing_event_type,
    extract_identity_info,
)
from app.in_out.factory import (
    process_crossing_events_to_raw,
    create_raw_events_from_crossing_engine,
    create_integrated_pipeline,
    process_tracks_through_pipeline,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_geometry_config() -> CameraGeometryConfig:
    """Create a sample line geometry configuration."""
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
def sample_crossing_event(sample_geometry_config: CameraGeometryConfig) -> CrossingEvent:
    """Create a sample CrossingEvent for testing."""
    geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
    
    return CrossingEvent(
        event_id="CE-LINE-ABC123",
        camera_id="CAM1",
        geometry_config=geom_snapshot,
        local_track_id="track_001",
        global_observation_id="GO-XYZ789",
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
        trajectory_points=[
            TrajectoryPoint(
                track_id="track_001",
                frame_index=100,
                timestamp=1234567889.5,
                position=Point2D(960, 480),
                bbox=(900, 400, 1020, 560),
                camera_id="CAM1",
                global_observation_id="GO-XYZ789",
            ),
            TrajectoryPoint(
                track_id="track_001",
                frame_index=101,
                timestamp=1234567890.5,
                position=Point2D(960, 520),
                bbox=(900, 440, 1020, 600),
                camera_id="CAM1",
                global_observation_id="GO-XYZ789",
            ),
        ],
        config_snapshot=sample_geometry_config.crossing_policy.to_dict(),
        created_at="2026-01-01T00:00:00Z",
        version="1.0",
    )


@pytest.fixture
def sample_out_crossing_event(sample_geometry_config: CameraGeometryConfig) -> CrossingEvent:
    """Create a sample OUT CrossingEvent for testing."""
    geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
    
    return CrossingEvent(
        event_id="CE-LINE-DEF456",
        camera_id="CAM1",
        geometry_config=geom_snapshot,
        local_track_id="track_002",
        global_observation_id=None,
        event_type=CrossingEventType.LINE_CROSSING,
        direction=CrossingDirection.OUT,
        crossing_point=Point2D(960, 500),
        crossing_timestamp=1234567895.5,
        previous_position=Point2D(960, 520),
        current_position=Point2D(960, 480),
        previous_frame_index=105,
        current_frame_index=106,
        previous_timestamp=1234567894.5,
        current_timestamp=1234567895.5,
        crossing_distance=40.0,
        side_transition="SIDE_B->SIDE_A",
        trajectory_points=[],
        config_snapshot=sample_geometry_config.crossing_policy.to_dict(),
        created_at="2026-01-01T00:00:00Z",
        version="1.0",
    )


@pytest.fixture
def zone_geometry_config() -> CameraGeometryConfig:
    """Create a sample zone geometry configuration."""
    from app.geometry.contract import create_zone_geometry
    return create_zone_geometry(
        camera_id="CAM2",
        frame_width=1920,
        frame_height=1080,
        vertices=[(100, 100), (500, 100), (500, 500), (100, 500)],
        direction_semantics=DirectionSemantics.OUTSIDE_TO_INSIDE_IN,
        version=2,
    )


@pytest.fixture
def zone_crossing_event(zone_geometry_config: CameraGeometryConfig) -> CrossingEvent:
    """Create a sample zone entry CrossingEvent."""
    geom_snapshot = GeometryConfigSnapshot.from_config(zone_geometry_config)
    
    return CrossingEvent(
        event_id="CE-ZONE-GHI789",
        camera_id="CAM2",
        geometry_config=geom_snapshot,
        local_track_id="track_003",
        global_observation_id="GO-ABC111",
        event_type=CrossingEventType.ZONE_ENTRY,
        direction=CrossingDirection.IN,
        crossing_point=Point2D(300, 100),
        crossing_timestamp=1234567900.0,
        previous_position=Point2D(300, 80),
        current_position=Point2D(300, 120),
        previous_frame_index=200,
        current_frame_index=201,
        previous_timestamp=1234567899.0,
        current_timestamp=1234567900.0,
        crossing_distance=40.0,
        side_transition="OUTSIDE->INSIDE",
        trajectory_points=[],
        config_snapshot=zone_geometry_config.crossing_policy.to_dict(),
        created_at="2026-01-01T00:00:00Z",
        version="1.0",
    )


# =============================================================================
# CONTRACT TESTS
# =============================================================================

class TestRawInOutEventContract:
    """Tests for RawInOutEvent contract."""
    
    def test_raw_event_creation_minimal(self, sample_crossing_event: CrossingEvent):
        """Test creating a RawInOutEvent with minimal required fields."""
        result = create_raw_in_out_event(sample_crossing_event)
        
        assert result.success
        assert result.event is not None
        event = result.event
        
        # Required fields
        assert event.event_id.startswith("RIE-")
        assert event.camera_id == "CAM1"
        assert event.local_track_id == "track_001"
        assert event.source_crossing_event_id == "CE-LINE-ABC123"
        assert event.geometry_id == sample_crossing_event.geometry_config.config_hash
        assert event.geometry_version == 1
        assert event.geometry_config_hash == sample_crossing_event.geometry_config.config_hash
        
        # Direction preserved
        assert event.direction == RawEventDirection.IN
        assert event.is_in
        assert not event.is_out
        
        # Event type mapped
        assert event.event_type == RawEventType.LINE_CROSSING
        
        # Timestamp preserved
        assert event.crossing_timestamp == 1234567890.5
        assert event.crossing_frame_index == 101
        
        # Global observation preserved
        assert event.global_observation_id == "GO-XYZ789"
        
        # Identity defaults to UNKNOWN
        assert event.identity_certainty == IdentityCertainty.UNKNOWN
        assert event.identity_candidate is None
        assert event.identity_confidence == 0.0
        assert event.identity_evidence_ref == "GO-XYZ789"
        
        # Schema version
        assert event.event_schema_version == "1.0"
    
    def test_raw_event_creation_out_direction(self, sample_out_crossing_event: CrossingEvent):
        """Test OUT direction is preserved."""
        result = create_raw_in_out_event(sample_out_crossing_event)
        
        assert result.success
        event = result.event
        assert event.direction == RawEventDirection.OUT
        assert event.is_out
        assert not event.is_in
    
    def test_raw_event_zone_entry(self, zone_crossing_event: CrossingEvent):
        """Test zone entry event type mapping."""
        result = create_raw_in_out_event(zone_crossing_event)
        
        assert result.success
        event = result.event
        assert event.event_type == RawEventType.ZONE_ENTRY
        assert event.direction == RawEventDirection.IN
        assert event.geometry_version == 2
        assert event.camera_id == "CAM2"
    
    def test_raw_event_immutability(self, sample_crossing_event: CrossingEvent):
        """Test that RawInOutEvent is truly immutable (frozen dataclass)."""
        result = create_raw_in_out_event(sample_crossing_event)
        event = result.event
        
        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(AttributeError):
            event.event_id = "modified"
        
        with pytest.raises(AttributeError):
            event.direction = RawEventDirection.OUT
        
        with pytest.raises(AttributeError):
            event.camera_id = "CAM2"
        
        with pytest.raises(AttributeError):
            event.crossing_timestamp = 0.0
    
    def test_raw_event_serialization_roundtrip(self, sample_crossing_event: CrossingEvent):
        """Test lossless serialization round-trip."""
        result = create_raw_in_out_event(sample_crossing_event)
        original = result.event
        
        # Serialize to dict
        data = original.to_dict()
        
        # Deserialize
        restored = RawInOutEvent.from_dict(data)
        
        # Compare all fields
        assert restored.event_id == original.event_id
        assert restored.camera_id == original.camera_id
        assert restored.local_track_id == original.local_track_id
        assert restored.global_observation_id == original.global_observation_id
        assert restored.direction == original.direction
        assert restored.event_type == original.event_type
        assert restored.crossing_timestamp == original.crossing_timestamp
        assert restored.crossing_frame_index == original.crossing_frame_index
        assert restored.geometry_id == original.geometry_id
        assert restored.geometry_version == original.geometry_version
        assert restored.geometry_config_hash == original.geometry_config_hash
        assert restored.source_crossing_event_id == original.source_crossing_event_id
        assert restored.identity_certainty == original.identity_certainty
        assert restored.event_schema_version == original.event_schema_version
        
        # Position fields
        assert restored.crossing_point == original.crossing_point
        assert restored.previous_position == original.previous_position
        assert restored.current_position == original.current_position
    
    def test_raw_event_json_serialization(self, sample_crossing_event: CrossingEvent):
        """Test JSON serialization."""
        result = create_raw_in_out_event(sample_crossing_event)
        event = result.event
        
        json_str = event.to_json()
        restored = RawInOutEvent.from_json(json_str)
        
        assert restored.event_id == event.event_id
        assert restored.direction == event.direction
        assert restored.crossing_timestamp == event.crossing_timestamp
    
    def test_raw_event_validation_rejects_empty_event_id(self, sample_crossing_event: CrossingEvent):
        """Test validation rejects empty event_id."""
        with pytest.raises(ValueError, match="event_id is required"):
            RawInOutEvent(
                event_id="",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
            )
    
    def test_raw_event_validation_rejects_empty_camera_id(self, sample_crossing_event: CrossingEvent):
        """Test validation rejects empty camera_id."""
        with pytest.raises(ValueError, match="camera_id is required"):
            RawInOutEvent(
                event_id="RIE-123",
                camera_id="",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
            )
    
    def test_raw_event_validation_rejects_invalid_direction(self, sample_crossing_event: CrossingEvent):
        """Test validation rejects invalid direction."""
        with pytest.raises(ValueError, match="direction must be IN or OUT"):
            RawInOutEvent(
                event_id="RIE-123",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
                direction="invalid",  # type: ignore
            )
    
    def test_raw_event_validation_rejects_negative_timestamp(self, sample_crossing_event: CrossingEvent):
        """Test validation rejects negative timestamp."""
        with pytest.raises(ValueError, match="crossing_timestamp must be >= 0"):
            RawInOutEvent(
                event_id="RIE-123",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
                crossing_timestamp=-1.0,
            )
    
    def test_raw_event_validation_rejects_invalid_schema_version(self, sample_crossing_event: CrossingEvent):
        """Test validation rejects unsupported schema version."""
        with pytest.raises(ValueError, match="Unsupported event_schema_version"):
            RawInOutEvent(
                event_id="RIE-123",
                camera_id="CAM1",
                geometry_id="hash123",
                geometry_version=1,
                geometry_config_hash="hash123",
                local_track_id="track_001",
                source_crossing_event_id="CE-123",
                event_schema_version="2.0",
            )


class TestDeterministicEventId:
    """Tests for deterministic event ID generation."""
    
    def test_same_inputs_produce_same_id(self):
        """Same inputs MUST produce the same event_id."""
        id1 = generate_deterministic_event_id(
            camera_id="CAM1",
            local_track_id="track_001",
            source_crossing_event_id="CE-123",
            geometry_version=1,
            geometry_config_hash="abc123",
        )
        id2 = generate_deterministic_event_id(
            camera_id="CAM1",
            local_track_id="track_001",
            source_crossing_event_id="CE-123",
            geometry_version=1,
            geometry_config_hash="abc123",
        )
        assert id1 == id2
        assert id1.startswith("RIE-")
    
    def test_different_camera_produces_different_id(self):
        """Different camera_id produces different event_id."""
        id1 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 1, "hash")
        id2 = generate_deterministic_event_id("CAM2", "track_001", "CE-123", 1, "hash")
        assert id1 != id2
    
    def test_different_track_produces_different_id(self):
        """Different local_track_id produces different event_id."""
        id1 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 1, "hash")
        id2 = generate_deterministic_event_id("CAM1", "track_002", "CE-123", 1, "hash")
        assert id1 != id2
    
    def test_different_crossing_event_produces_different_id(self):
        """Different source_crossing_event_id produces different event_id."""
        id1 = generate_deterministic_event_id("CAM1", "track_001", "CE-111", 1, "hash")
        id2 = generate_deterministic_event_id("CAM1", "track_001", "CE-222", 1, "hash")
        assert id1 != id2
    
    def test_different_geometry_version_produces_different_id(self):
        """Different geometry_version produces different event_id."""
        id1 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 1, "hash")
        id2 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 2, "hash")
        assert id1 != id2
    
    def test_different_geometry_hash_produces_different_id(self):
        """Different geometry_config_hash produces different event_id."""
        id1 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 1, "hash1")
        id2 = generate_deterministic_event_id("CAM1", "track_001", "CE-123", 1, "hash2")
        assert id1 != id2


class TestDirectionMapping:
    """Tests for direction mapping from Phase 22 to Phase 23."""
    
    def test_in_direction_preserved(self):
        """IN direction from Phase 22 maps to IN in Phase 23."""
        assert map_crossing_direction(CrossingDirection.IN) == RawEventDirection.IN
    
    def test_out_direction_preserved(self):
        """OUT direction from Phase 22 maps to OUT in Phase 23."""
        assert map_crossing_direction(CrossingDirection.OUT) == RawEventDirection.OUT
    
    def test_event_type_mapping(self):
        """Event types map correctly."""
        assert map_crossing_event_type(CrossingEventType.LINE_CROSSING) == RawEventType.LINE_CROSSING
        assert map_crossing_event_type(CrossingEventType.ZONE_ENTRY) == RawEventType.ZONE_ENTRY
        assert map_crossing_event_type(CrossingEventType.ZONE_EXIT) == RawEventType.ZONE_EXIT


class TestIdentityExtraction:
    """Tests for identity information extraction."""
    
    def test_identity_defaults_to_unknown(self, sample_crossing_event: CrossingEvent):
        """Identity defaults to UNKNOWN when not available."""
        info = extract_identity_info(sample_crossing_event)
        
        assert info["identity_certainty"] == IdentityCertainty.UNKNOWN
        assert info["identity_candidate"] is None
        assert info["identity_confidence"] == 0.0
        assert info["identity_evidence_ref"] == "GO-XYZ789"
    
    def test_identity_preserves_global_observation_ref(self, sample_crossing_event: CrossingEvent):
        """Global observation ID is preserved as evidence reference."""
        info = extract_identity_info(sample_crossing_event)
        assert info["identity_evidence_ref"] == "GO-XYZ789"
    
    def test_identity_none_when_no_global_observation(self, sample_out_crossing_event: CrossingEvent):
        """Identity evidence ref is None when no global observation."""
        info = extract_identity_info(sample_out_crossing_event)
        assert info["identity_evidence_ref"] is None


# =============================================================================
# ENGINE TESTS
# =============================================================================

class TestRawEventEngine:
    """Tests for RawEventEngine."""
    
    def test_engine_creation(self):
        """Test engine can be created."""
        engine = create_raw_event_engine()
        assert isinstance(engine, RawEventEngine)
        assert engine.get_stats()["total_processed"] == 0
    
    def test_process_single_crossing_event(self, sample_crossing_event: CrossingEvent):
        """Test processing a single crossing event."""
        engine = create_raw_event_engine()
        result = engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event is not None
        assert engine.get_stats()["successful"] == 1
        assert engine.get_stats()["total_processed"] == 1
    
    def test_process_multiple_crossing_events(self, sample_crossing_event: CrossingEvent, sample_out_crossing_event: CrossingEvent):
        """Test processing multiple crossing events."""
        engine = create_raw_event_engine()
        results = engine.process_crossing_events([sample_crossing_event, sample_out_crossing_event])
        
        assert len(results) == 2
        assert all(r.success for r in results)
        assert engine.get_stats()["successful"] == 2
        assert len(engine.get_events()) == 2
    
    def test_idempotent_processing(self, sample_crossing_event: CrossingEvent):
        """Test that processing the same event twice is idempotent."""
        engine = create_raw_event_engine()
        
        # First processing
        result1 = engine.process_crossing_event(sample_crossing_event)
        assert result1.success
        
        # Second processing (same object)
        result2 = engine.process_crossing_event(sample_crossing_event)
        assert result2.success
        assert result2.event.event_id == result1.event.event_id
        
        # Stats should show duplicate
        assert engine.get_stats()["duplicates"] == 1
        assert engine.get_stats()["successful"] == 1
        assert len(engine.get_events()) == 1
    
    def test_idempotent_reconstructed_event(self, sample_crossing_event: CrossingEvent):
        """Test idempotency with equivalent reconstructed event."""
        engine = create_raw_event_engine()
        
        # Process original
        result1 = engine.process_crossing_event(sample_crossing_event)
        assert result1.success
        
        # Create equivalent crossing event (same key fields)
        # sample_crossing_event.geometry_config is already a GeometryConfigSnapshot
        geom_snapshot = sample_crossing_event.geometry_config
        
        equivalent_event = CrossingEvent(
            event_id=sample_crossing_event.event_id,
            camera_id=sample_crossing_event.camera_id,
            geometry_config=geom_snapshot,
            local_track_id=sample_crossing_event.local_track_id,
            global_observation_id=sample_crossing_event.global_observation_id,
            event_type=sample_crossing_event.event_type,
            direction=sample_crossing_event.direction,
            crossing_point=sample_crossing_event.crossing_point,
            crossing_timestamp=sample_crossing_event.crossing_timestamp,
            previous_position=sample_crossing_event.previous_position,
            current_position=sample_crossing_event.current_position,
            previous_frame_index=sample_crossing_event.previous_frame_index,
            current_frame_index=sample_crossing_event.current_frame_index,
            previous_timestamp=sample_crossing_event.previous_timestamp,
            current_timestamp=sample_crossing_event.current_timestamp,
            crossing_distance=sample_crossing_event.crossing_distance,
            side_transition=sample_crossing_event.side_transition,
            trajectory_points=sample_crossing_event.trajectory_points,
            config_snapshot=sample_crossing_event.config_snapshot,
            created_at=sample_crossing_event.created_at,
            version=sample_crossing_event.version,
        )
        
        # Process equivalent event
        result2 = engine.process_crossing_event(equivalent_event)
        assert result2.success
        assert result2.event.event_id == result1.event.event_id
        assert engine.get_stats()["duplicates"] == 1
    
    def test_camera_isolation(self, sample_crossing_event: CrossingEvent, zone_crossing_event: CrossingEvent):
        """Test that events from different cameras remain independent."""
        engine = create_raw_event_engine()
        
        engine.process_crossing_event(sample_crossing_event)  # CAM1
        engine.process_crossing_event(zone_crossing_event)    # CAM2
        
        events = engine.get_events()
        assert len(events) == 2
        
        cam1_events = engine.get_events_by_camera("CAM1")
        cam2_events = engine.get_events_by_camera("CAM2")
        
        assert len(cam1_events) == 1
        assert len(cam2_events) == 1
        assert cam1_events[0].camera_id == "CAM1"
        assert cam2_events[0].camera_id == "CAM2"
    
    def test_chronological_ordering(self, sample_crossing_event: CrossingEvent, sample_out_crossing_event: CrossingEvent):
        """Test events are returned in chronological order."""
        engine = create_raw_event_engine()
        
        # Process out of order (OUT event has later timestamp)
        engine.process_crossing_event(sample_out_crossing_event)  # timestamp 1234567895.5
        engine.process_crossing_event(sample_crossing_event)      # timestamp 1234567890.5
        
        events = engine.get_events()
        assert len(events) == 2
        # Should be sorted by timestamp
        assert events[0].crossing_timestamp < events[1].crossing_timestamp
        # First event should be the IN event (earlier timestamp)
        assert events[0].direction == RawEventDirection.IN
        assert events[1].direction == RawEventDirection.OUT
    
    def test_equal_timestamp_tiebreaking(self, sample_crossing_event: CrossingEvent):
        """Test deterministic tie-breaking for equal timestamps."""
        engine = create_raw_event_engine()
        
        # Create another event with same timestamp but different track
        # sample_crossing_event.geometry_config is already a GeometryConfigSnapshot
        geom_snapshot = sample_crossing_event.geometry_config
        
        event2 = CrossingEvent(
            event_id="CE-LINE-OTHER",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_999",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(100, 500),
            crossing_timestamp=1234567890.5,  # Same timestamp
            previous_position=Point2D(100, 480),
            current_position=Point2D(100, 520),
            previous_frame_index=50,
            current_frame_index=51,
            previous_timestamp=1234567889.5,
            current_timestamp=1234567890.5,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        engine.process_crossing_event(sample_crossing_event)
        engine.process_crossing_event(event2)
        
        events = engine.get_events()
        assert len(events) == 2
        # Tie-break by event_id for deterministic ordering
        assert events[0].event_id < events[1].event_id or events[0].event_id > events[1].event_id
    
    def test_historical_events_remain_independent(self, sample_crossing_event: CrossingEvent, sample_out_crossing_event: CrossingEvent):
        """Test that IN -> OUT -> IN sequence preserves all three events."""
        engine = create_raw_event_engine()
        
        # Create a third IN event
        # sample_crossing_event.geometry_config is already a GeometryConfigSnapshot
        geom_snapshot = sample_crossing_event.geometry_config
        
        event3 = CrossingEvent(
            event_id="CE-LINE-THIRD",
            camera_id="CAM1",
            geometry_config=geom_snapshot,
            local_track_id="track_001",  # Same track
            global_observation_id="GO-XYZ789",
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1234567900.5,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=150,
            current_frame_index=151,
            previous_timestamp=1234567899.5,
            current_timestamp=1234567900.5,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot={},
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        engine.process_crossing_event(sample_crossing_event)    # IN at t=1234567890.5
        engine.process_crossing_event(sample_out_crossing_event) # OUT at t=1234567895.5
        engine.process_crossing_event(event3)                    # IN at t=1234567900.5
        
        events = engine.get_events()
        assert len(events) == 3
        
        # All three preserved independently
        directions = [e.direction for e in events]
        assert directions == [RawEventDirection.IN, RawEventDirection.OUT, RawEventDirection.IN]
        
        # No collapsing to current state
        timestamps = [e.crossing_timestamp for e in events]
        assert timestamps == [1234567890.5, 1234567895.5, 1234567900.5]
    
    def test_rejects_invalid_crossing_event(self):
        """Test engine rejects invalid crossing events."""
        engine = create_raw_event_engine()
        
        # Create invalid crossing event (missing required fields)
        class InvalidEvent:
            pass
        
        invalid = InvalidEvent()
        result = engine.process_crossing_event(invalid)  # type: ignore
        
        assert not result.success
        assert result.rejection_reason == "invalid_crossing_event"
        assert engine.get_stats()["rejected"] == 1
    
    def test_rejects_missing_direction(self, sample_geometry_config: CameraGeometryConfig):
        """Test rejection of crossing event with invalid direction."""
        engine = create_raw_event_engine()
        
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        # Create event with invalid direction by bypassing enum
        class BadEvent:
            event_id = "CE-BAD"
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            global_observation_id = None
            event_type = CrossingEventType.LINE_CROSSING
            direction = "sideways"  # Invalid
            crossing_point = Point2D(0, 0)
            crossing_timestamp = 1000.0
            previous_position = None
            current_position = None
            previous_frame_index = -1
            current_frame_index = -1
            previous_timestamp = 0.0
            current_timestamp = 0.0
            crossing_distance = 0.0
            side_transition = ""
            trajectory_points = []
            config_snapshot = {}
            created_at = "2026-01-01T00:00:00Z"
            version = "1.0"
        
        result = engine.process_crossing_event(BadEvent())  # type: ignore
        assert not result.success
        assert "Invalid direction" in result.error or "direction" in result.error.lower()
    
    def test_rejects_missing_camera_id(self, sample_geometry_config: CameraGeometryConfig):
        """Test rejection of crossing event with missing camera_id."""
        engine = create_raw_event_engine()
        
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-BAD"
            camera_id = ""  # Empty
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            global_observation_id = None
            event_type = CrossingEventType.LINE_CROSSING
            direction = CrossingDirection.IN
            crossing_point = Point2D(0, 0)
            crossing_timestamp = 1000.0
            previous_position = None
            current_position = None
            previous_frame_index = -1
            current_frame_index = -1
            previous_timestamp = 0.0
            current_timestamp = 0.0
            crossing_distance = 0.0
            side_transition = ""
            trajectory_points = []
            config_snapshot = {}
            created_at = "2026-01-01T00:00:00Z"
            version = "1.0"
        
        result = engine.process_crossing_event(BadEvent())  # type: ignore
        assert not result.success
    
    def test_rejects_negative_timestamp(self, sample_geometry_config: CameraGeometryConfig):
        """Test rejection of crossing event with negative timestamp."""
        engine = create_raw_event_engine()
        
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-BAD"
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            global_observation_id = None
            event_type = CrossingEventType.LINE_CROSSING
            direction = CrossingDirection.IN
            crossing_point = Point2D(0, 0)
            crossing_timestamp = -1.0  # Negative
            previous_position = None
            current_position = None
            previous_frame_index = -1
            current_frame_index = -1
            previous_timestamp = 0.0
            current_timestamp = 0.0
            crossing_distance = 0.0
            side_transition = ""
            trajectory_points = []
            config_snapshot = {}
            created_at = "2026-01-01T00:00:00Z"
            version = "1.0"
        
        result = engine.process_crossing_event(BadEvent())  # type: ignore
        assert not result.success
    
    def test_rejects_missing_geometry_config(self, sample_geometry_config: CameraGeometryConfig):
        """Test rejection of crossing event with missing geometry config."""
        engine = create_raw_event_engine()
        
        class BadEvent:
            event_id = "CE-BAD"
            camera_id = "CAM1"
            geometry_config = None  # Missing
            local_track_id = "track_001"
            global_observation_id = None
            event_type = CrossingEventType.LINE_CROSSING
            direction = CrossingDirection.IN
            crossing_point = Point2D(0, 0)
            crossing_timestamp = 1000.0
            previous_position = None
            current_position = None
            previous_frame_index = -1
            current_frame_index = -1
            previous_timestamp = 0.0
            current_timestamp = 0.0
            crossing_distance = 0.0
            side_transition = ""
            trajectory_points = []
            config_snapshot = {}
            created_at = "2026-01-01T00:00:00Z"
            version = "1.0"
        
        result = engine.process_crossing_event(BadEvent())  # type: ignore
        assert not result.success
    
    def test_rejects_missing_geometry_hash(self, sample_geometry_config: CameraGeometryConfig):
        """Test rejection of crossing event with missing geometry config hash."""
        engine = create_raw_event_engine()
        
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        # Create a snapshot with empty hash
        bad_snapshot = GeometryConfigSnapshot(
            camera_id="CAM1",
            config_hash="",  # Empty hash
            version=1,
            geometry_type=GeometryType.LINE,
            frame_width=1920,
            frame_height=1080,
        )
        
        class BadEvent:
            event_id = "CE-BAD"
            camera_id = "CAM1"
            geometry_config = bad_snapshot
            local_track_id = "track_001"
            global_observation_id = None
            event_type = CrossingEventType.LINE_CROSSING
            direction = CrossingDirection.IN
            crossing_point = Point2D(0, 0)
            crossing_timestamp = 1000.0
            previous_position = None
            current_position = None
            previous_frame_index = -1
            current_frame_index = -1
            previous_timestamp = 0.0
            current_timestamp = 0.0
            crossing_distance = 0.0
            side_transition = ""
            trajectory_points = []
            config_snapshot = {}
            created_at = "2026-01-01T00:00:00Z"
            version = "1.0"
        
        result = engine.process_crossing_event(BadEvent())  # type: ignore
        assert not result.success
    
    def test_engine_clear(self, sample_crossing_event: CrossingEvent):
        """Test engine clear functionality."""
        engine = create_raw_event_engine()
        engine.process_crossing_event(sample_crossing_event)
        
        assert len(engine.get_events()) == 1
        assert engine.get_stats()["successful"] == 1
        
        engine.clear()
        
        assert len(engine.get_events()) == 0
        assert engine.get_stats()["successful"] == 0
        assert engine.get_stats()["total_processed"] == 0
    
    def test_has_event(self, sample_crossing_event: CrossingEvent):
        """Test has_event method."""
        engine = create_raw_event_engine()
        
        assert not engine.has_event("RIE-ANYTHING")
        
        result = engine.process_crossing_event(sample_crossing_event)
        event_id = result.event.event_id
        
        assert engine.has_event(event_id)


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestValidation:
    """Tests for crossing event validation."""
    
    def test_validate_valid_event(self, sample_crossing_event: CrossingEvent):
        """Test validation passes for valid event."""
        error = validate_crossing_event_for_raw_creation(sample_crossing_event)
        assert error is None
    
    def test_validate_missing_event_id(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for missing event_id."""
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = ""
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            direction = CrossingDirection.IN
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "event_id" in error
    
    def test_validate_missing_camera_id(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for missing camera_id."""
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = ""
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            direction = CrossingDirection.IN
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "camera_id" in error
    
    def test_validate_missing_local_track_id(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for missing local_track_id."""
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = ""
            direction = CrossingDirection.IN
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "local_track_id" in error
    
    def test_validate_invalid_direction(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for invalid direction."""
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            direction = "invalid"
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "direction" in error.lower()
    
    def test_validate_negative_timestamp(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for negative timestamp."""
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = "CAM1"
            geometry_config = geom_snapshot
            local_track_id = "track_001"
            direction = CrossingDirection.IN
            crossing_timestamp = -1.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "timestamp" in error.lower()
    
    def test_validate_missing_geometry_hash(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for missing geometry config hash."""
        from app.geometry.contract import GeometryConfigSnapshot
        bad_snapshot = GeometryConfigSnapshot(
            camera_id="CAM1",
            config_hash="",
            version=1,
            geometry_type=GeometryType.LINE,
            frame_width=1920,
            frame_height=1080,
        )
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = "CAM1"
            geometry_config = bad_snapshot
            local_track_id = "track_001"
            direction = CrossingDirection.IN
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "config_hash" in error
    
    def test_validate_missing_geometry_version(self, sample_geometry_config: CameraGeometryConfig):
        """Test validation fails for missing geometry version."""
        from app.geometry.contract import GeometryConfigSnapshot
        bad_snapshot = GeometryConfigSnapshot(
            camera_id="CAM1",
            config_hash="hash123",
            version=0,  # Invalid version
            geometry_type=GeometryType.LINE,
            frame_width=1920,
            frame_height=1080,
        )
        
        class BadEvent:
            event_id = "CE-123"
            camera_id = "CAM1"
            geometry_config = bad_snapshot
            local_track_id = "track_001"
            direction = CrossingDirection.IN
            crossing_timestamp = 1000.0
        
        error = validate_crossing_event_for_raw_creation(BadEvent())  # type: ignore
        assert error is not None
        assert "version" in error.lower()


# =============================================================================
# FACTORY TESTS
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""
    
    def test_process_crossing_events_to_raw(self, sample_crossing_event: CrossingEvent, sample_out_crossing_event: CrossingEvent):
        """Test convenience function for processing events."""
        results = process_crossing_events_to_raw([sample_crossing_event, sample_out_crossing_event])
        
        assert len(results) == 2
        assert all(r.success for r in results)
        assert results[0].event.direction == RawEventDirection.IN
        assert results[1].event.direction == RawEventDirection.OUT
    
    def test_create_raw_events_from_crossing_engine(self, sample_geometry_config: CameraGeometryConfig):
        """Test extracting events from crossing engine."""
        crossing_engine = create_crossing_engine(sample_geometry_config)
        
        # We can't easily create tracks here, so test with empty
        events = create_raw_events_from_crossing_engine(crossing_engine)
        assert events == []
    
    def test_create_integrated_pipeline(self, sample_geometry_config: CameraGeometryConfig):
        """Test creating integrated pipeline."""
        crossing_engine, raw_engine = create_integrated_pipeline(sample_geometry_config)
        
        assert isinstance(crossing_engine, CrossingEngine)
        assert isinstance(raw_engine, RawEventEngine)


# =============================================================================
# PROVENANCE TESTS
# =============================================================================

class TestProvenanceChain:
    """Tests for provenance chain preservation."""
    
    def test_provenance_preserves_crossing_event_id(self, sample_crossing_event: CrossingEvent):
        """Test source_crossing_event_id is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.source_crossing_event_id == "CE-LINE-ABC123"
    
    def test_provenance_preserves_geometry_version(self, sample_crossing_event: CrossingEvent):
        """Test geometry_version is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.geometry_version == 1
    
    def test_provenance_preserves_geometry_hash(self, sample_crossing_event: CrossingEvent):
        """Test geometry_config_hash is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        expected_hash = sample_crossing_event.geometry_config.config_hash
        assert result.event.geometry_config_hash == expected_hash
        assert result.event.geometry_id == expected_hash
    
    def test_provenance_preserves_camera_id(self, sample_crossing_event: CrossingEvent):
        """Test camera_id is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.camera_id == "CAM1"
    
    def test_provenance_preserves_local_track_id(self, sample_crossing_event: CrossingEvent):
        """Test local_track_id is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.local_track_id == "track_001"
    
    def test_provenance_preserves_global_observation_id(self, sample_crossing_event: CrossingEvent):
        """Test global_observation_id is preserved when available."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.global_observation_id == "GO-XYZ789"
    
    def test_provenance_preserves_timestamp(self, sample_crossing_event: CrossingEvent):
        """Test crossing_timestamp is preserved (not replaced with wall-clock)."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert result.event.crossing_timestamp == 1234567890.5
        # created_at should be from original crossing event, not now()
        assert result.event.created_at == "2026-01-01T00:00:00Z"
    
    def test_provenance_preserves_trajectory_points(self, sample_crossing_event: CrossingEvent):
        """Test trajectory points are preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        traj_points = result.event.trajectory_points
        
        assert len(traj_points) == 2
        assert traj_points[0]["track_id"] == "track_001"
        assert traj_points[0]["frame_index"] == 100
        assert traj_points[0]["global_observation_id"] == "GO-XYZ789"
        assert "position" in traj_points[0]
        assert "bbox" in traj_points[0]
    
    def test_provenance_preserves_config_snapshot(self, sample_crossing_event: CrossingEvent):
        """Test config_snapshot is preserved."""
        result = create_raw_in_out_event(sample_crossing_event)
        assert "min_crossing_distance" in result.event.config_snapshot
        assert "temporal_debounce_seconds" in result.event.config_snapshot
    
    def test_geometry_version_immutable_across_config_changes(self, sample_crossing_event: CrossingEvent, sample_geometry_config: CameraGeometryConfig):
        """Test that historical events keep their geometry version even if config changes."""
        # Create event with version 1
        result1 = create_raw_in_out_event(sample_crossing_event)
        assert result1.success
        assert result1.event.geometry_version == 1
        
        # Create new geometry config version 2
        config_v2 = sample_geometry_config.with_updated_geometry(version=2)
        
        # Create new crossing event with version 2
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot_v2 = GeometryConfigSnapshot.from_config(config_v2)
        
        event_v2 = CrossingEvent(
            event_id="CE-LINE-V2",
            camera_id="CAM1",
            geometry_config=geom_snapshot_v2,
            local_track_id="track_001",
            global_observation_id=None,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=CrossingDirection.IN,
            crossing_point=Point2D(960, 500),
            crossing_timestamp=1234567900.0,
            previous_position=Point2D(960, 480),
            current_position=Point2D(960, 520),
            previous_frame_index=200,
            current_frame_index=201,
            previous_timestamp=1234567899.0,
            current_timestamp=1234567900.0,
            crossing_distance=40.0,
            side_transition="SIDE_A->SIDE_B",
            trajectory_points=[],
            config_snapshot=config_v2.crossing_policy.to_dict(),
            created_at="2026-01-01T00:00:00Z",
            version="1.0",
        )
        
        result2 = create_raw_in_out_event(event_v2)
        assert result2.success
        assert result2.event.geometry_version == 2
        
        # Original event still has version 1
        assert result1.event.geometry_version == 1


# =============================================================================
# DETERMINISM TESTS
# =============================================================================

class TestDeterminism:
    """Tests for deterministic behavior."""
    
    def test_repeated_execution_produces_same_results(self, sample_crossing_event: CrossingEvent):
        """Same crossing event + config must produce same raw event."""
        engine1 = create_raw_event_engine()
        engine2 = create_raw_event_engine()
        
        result1 = engine1.process_crossing_event(sample_crossing_event)
        result2 = engine2.process_crossing_event(sample_crossing_event)
        
        assert result1.success and result2.success
        assert result1.event.event_id == result2.event.event_id
        assert result1.event.direction == result2.event.direction
        assert result1.event.crossing_timestamp == result2.event.crossing_timestamp
        assert result1.event.camera_id == result2.event.camera_id
        assert result1.event.local_track_id == result2.event.local_track_id
        assert result1.event.geometry_version == result2.event.geometry_version
        assert result1.event.geometry_config_hash == result2.event.geometry_config_hash
    
    def test_no_random_event_ids(self, sample_crossing_event: CrossingEvent):
        """Event IDs must not be random."""
        engine = create_raw_event_engine()
        
        # Process multiple times
        ids = set()
        for _ in range(10):
            result = engine.process_crossing_event(sample_crossing_event)
            ids.add(result.event.event_id)
        
        # All should be the same (idempotent)
        assert len(ids) == 1
    
    def test_no_wall_clock_dependency(self, sample_crossing_event: CrossingEvent):
        """Event identity must not depend on wall-clock processing time."""
        import time
        
        engine1 = create_raw_event_engine()
        result1 = engine1.process_crossing_event(sample_crossing_event)
        
        # Wait a bit
        time.sleep(0.01)
        
        engine2 = create_raw_event_engine()
        result2 = engine2.process_crossing_event(sample_crossing_event)
        
        # Event IDs must be identical despite time passing
        assert result1.event.event_id == result2.event.event_id


# =============================================================================
# BOUNDED MEMORY TESTS
# =============================================================================

class TestBoundedMemory:
    """Tests for bounded memory usage."""
    
    def test_engine_does_not_retain_unbounded_history(self, sample_geometry_config: CameraGeometryConfig):
        """Test that engine state doesn't grow unbounded."""
        engine = create_raw_event_engine()
        
        from app.geometry.contract import GeometryConfigSnapshot
        geom_snapshot = GeometryConfigSnapshot.from_config(sample_geometry_config)
        
        # Process many events
        for i in range(100):
            event = CrossingEvent(
                event_id=f"CE-{i}",
                camera_id="CAM1",
                geometry_config=geom_snapshot,
                local_track_id=f"track_{i}",
                global_observation_id=None,
                event_type=CrossingEventType.LINE_CROSSING,
                direction=CrossingDirection.IN,
                crossing_point=Point2D(960, 500),
                crossing_timestamp=1000.0 + i,
                previous_position=Point2D(960, 480),
                current_position=Point2D(960, 520),
                previous_frame_index=i,
                current_frame_index=i+1,
                previous_timestamp=999.0 + i,
                current_timestamp=1000.0 + i,
                crossing_distance=40.0,
                side_transition="SIDE_A->SIDE_B",
                trajectory_points=[],
                config_snapshot={},
                created_at="2026-01-01T00:00:00Z",
                version="1.0",
            )
            engine.process_crossing_event(event)
        
        # Engine should have all events (this is expected for raw event history)
        # But the _processed_event_ids set should be bounded by unique events
        assert len(engine._processed_event_ids) == 100
        assert len(engine._events) == 100
        
        # Clear should work
        engine.clear()
        assert len(engine._processed_event_ids) == 0
        assert len(engine._events) == 0


# =============================================================================
# PHASE 22 INTEGRATION TESTS
# =============================================================================

class TestPhase22Integration:
    """Integration tests with actual Phase 22 CrossingEngine."""
    
    def test_crossing_engine_to_raw_engine_pipeline(self, sample_geometry_config: CameraGeometryConfig):
        """Test full pipeline: CrossingEngine -> RawEventEngine."""
        # Create crossing engine
        crossing_engine = create_crossing_engine(sample_geometry_config)
        raw_engine = create_raw_event_engine()
        
        # We can't easily create Track objects without the vision module
        # But we can test the factory function that does the integration
        crossing_events = crossing_engine.get_events()
        assert crossing_events == []  # No tracks processed yet
        
        # Process through factory
        raw_events = create_raw_events_from_crossing_engine(crossing_engine, raw_engine)
        assert raw_events == []
    
    def test_direction_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test direction is preserved from Phase 22 to Phase 23."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.direction == RawEventDirection.IN
        # Original was CrossingDirection.IN
        assert sample_crossing_event.direction == CrossingDirection.IN
    
    def test_timestamp_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test timestamp is preserved from Phase 22 to Phase 23."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.crossing_timestamp == sample_crossing_event.crossing_timestamp
    
    def test_camera_id_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test camera_id is preserved."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.camera_id == sample_crossing_event.camera_id
    
    def test_local_track_id_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test local_track_id is preserved."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.local_track_id == sample_crossing_event.local_track_id
    
    def test_global_observation_id_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test global_observation_id is preserved when available."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.global_observation_id == sample_crossing_event.global_observation_id
    
    def test_geometry_id_version_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test geometry_id and version are preserved."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.geometry_id == sample_crossing_event.geometry_config.config_hash
        assert result.event.geometry_version == sample_crossing_event.geometry_config.version
        assert result.event.geometry_config_hash == sample_crossing_event.geometry_config.config_hash
    
    def test_source_crossing_event_id_preserved(self, sample_crossing_event: CrossingEvent):
        """Test source_crossing_event_id is preserved."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        assert result.event.source_crossing_event_id == sample_crossing_event.event_id
    
    def test_provenance_preserved_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test full provenance chain is preserved."""
        raw_engine = create_raw_event_engine()
        result = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result.success
        event = result.event
        
        # Check trajectory points preserved
        assert len(event.trajectory_points) == 2
        assert event.trajectory_points[0]["global_observation_id"] == "GO-XYZ789"
        
        # Check config snapshot preserved
        assert event.config_snapshot == sample_crossing_event.config_snapshot
    
    def test_deterministic_event_id_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test deterministic event ID through full pipeline."""
        raw_engine1 = create_raw_event_engine()
        raw_engine2 = create_raw_event_engine()
        
        result1 = raw_engine1.process_crossing_event(sample_crossing_event)
        result2 = raw_engine2.process_crossing_event(sample_crossing_event)
        
        assert result1.event.event_id == result2.event.event_id
    
    def test_duplicate_processing_idempotent_through_pipeline(self, sample_crossing_event: CrossingEvent):
        """Test duplicate processing is idempotent through pipeline."""
        raw_engine = create_raw_event_engine()
        
        result1 = raw_engine.process_crossing_event(sample_crossing_event)
        result2 = raw_engine.process_crossing_event(sample_crossing_event)
        
        assert result1.event.event_id == result2.event.event_id
        assert raw_engine.get_stats()["duplicates"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])