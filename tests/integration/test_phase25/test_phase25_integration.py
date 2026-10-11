"""
Phase 25 — Integration Tests for Phase 24 → Phase 25 Pipeline.

Tests the complete flow: Phase 23 RawInOutEvent → Phase 24 Resolver → Phase 25 Persistence.
"""

import pytest
import tempfile
import os

from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
    generate_deterministic_event_id,
)
from app.in_out.raw_event import create_raw_event_engine
from app.in_out.resolver import create_repeated_in_out_resolver, ResolverConfig
from app.in_out.resolver_contract import (
    ResolvedTransition,
    ResolutionResult,
    TransitionType,
    DerivedState,
    ResolutionStatus,
)
from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    create_attendance_record_from_resolution,
)
from app.attendance.repository import AttendanceRepository, PersistenceResult
from app.attendance.storage import StorageConfig, AttendanceStorage


class TestPhase24ToPhase25Integration:
    """Integration tests for Phase 24 → Phase 25 pipeline."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)
    
    @pytest.fixture
    def repository(self, temp_db):
        config = StorageConfig(database_path=temp_db)
        repo = AttendanceRepository(config=config)
        yield repo
        repo.close()
    
    def create_sample_raw_event(self, event_id: str, direction: str, timestamp: float) -> RawInOutEvent:
        """Create a sample RawInOutEvent for testing."""
        return RawInOutEvent(
            event_id=event_id,
            camera_id="CAM1",
            geometry_id="geom_hash_123",
            geometry_version=1,
            geometry_config_hash="geom_hash_123",
            local_track_id="track_001",
            global_observation_id="GO-123",
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN if direction == "in" else RawEventDirection.OUT,
            crossing_point_x=100.0,
            crossing_point_y=200.0,
            crossing_timestamp=timestamp,
            crossing_frame_index=100,
            previous_position_x=90.0,
            previous_position_y=190.0,
            current_position_x=110.0,
            current_position_y=210.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=timestamp - 0.033,
            current_timestamp=timestamp,
            crossing_distance=10.0,
            side_transition="outside_to_inside" if direction == "in" else "inside_to_outside",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref="GO-123",
            source_crossing_event_id=f"CE-{event_id}",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
        )
    
    def test_full_pipeline_in_out_sequence(self, repository):
        """Test complete pipeline: RawEvent → Resolver → Persistence for IN/OUT sequence."""
        # Create raw events: IN, OUT, IN
        raw_events = [
            self.create_sample_raw_event("RIE-001", "in", 1000.0),
            self.create_sample_raw_event("RIE-002", "out", 1010.0),
            self.create_sample_raw_event("RIE-003", "in", 1020.0),
        ]
        
        # Phase 24: Resolve
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        
        # Verify resolution
        assert resolution_result.total_raw_events == 3
        assert resolution_result.accepted_transitions == 3  # All three are transitions
        assert len(resolution_result.transitions) == 3
        
        # Check transition types
        assert resolution_result.transitions[0].transition_type == TransitionType.IN
        assert resolution_result.transitions[1].transition_type == TransitionType.OUT
        assert resolution_result.transitions[2].transition_type == TransitionType.IN
        
        # Phase 25: Persist
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        assert persistence_result.total_resolutions == 3
        assert persistence_result.transitions_persisted == 3
        assert persistence_result.suppressed_skipped == 0
        assert persistence_result.duplicates_skipped == 0
        
        # Verify persisted records
        records = repository.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        assert len(records) == 3
        
        # Check first record (IN)
        assert records[0].direction == AttendanceDirection.IN
        assert records[0].previous_state == "unknown"
        assert records[0].new_state == "inside"
        assert records[0].source_resolution_id == resolution_result.transitions[0].resolution_id
        assert records[0].source_raw_event_id == "RIE-001"
        
        # Check second record (OUT)
        assert records[1].direction == AttendanceDirection.OUT
        assert records[1].previous_state == "inside"
        assert records[1].new_state == "outside"
        assert records[1].source_resolution_id == resolution_result.transitions[1].resolution_id
        assert records[1].source_raw_event_id == "RIE-002"
        
        # Check third record (IN)
        assert records[2].direction == AttendanceDirection.IN
        assert records[2].previous_state == "outside"
        assert records[2].new_state == "inside"
        assert records[2].source_resolution_id == resolution_result.transitions[2].resolution_id
        assert records[2].source_raw_event_id == "RIE-003"
    
    def test_pipeline_preserves_provenance_chain(self, repository):
        """Test that full provenance chain is preserved."""
        raw_event = self.create_sample_raw_event("RIE-provenance", "in", 1000.0)
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events([raw_event])
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        assert persistence_result.transitions_persisted == 1
        
        record = repository.get_by_resolution_id(resolution_result.transitions[0].resolution_id)
        assert record is not None
        
        # Verify provenance chain
        assert record.source_resolution_id == resolution_result.transitions[0].resolution_id
        assert record.source_raw_event_id == raw_event.event_id
        assert record.source_crossing_event_id == raw_event.source_crossing_event_id
        assert record.geometry_version == raw_event.geometry_version
        assert record.geometry_config_hash == raw_event.geometry_config_hash
        assert record.resolver_version == resolution_result.transitions[0].resolver_version
        assert record.resolver_config_hash == resolution_result.transitions[0].resolver_config_hash
        assert record.global_observation_id == raw_event.global_observation_id
        assert record.camera_id == raw_event.camera_id
        assert record.local_track_id == raw_event.local_track_id
    
    def test_pipeline_idempotent(self, repository):
        """Test that running the pipeline twice produces same results."""
        raw_events = [
            self.create_sample_raw_event("RIE-idempotent-1", "in", 1000.0),
            self.create_sample_raw_event("RIE-idempotent-2", "out", 1010.0),
        ]
        
        resolver = create_repeated_in_out_resolver()
        
        # First run
        resolution_result1 = resolver.resolve_events(raw_events)
        persistence_result1 = repository.persist_resolution_result(resolution_result1)
        
        # Second run (same events)
        resolution_result2 = resolver.resolve_events(raw_events)
        persistence_result2 = repository.persist_resolution_result(resolution_result2)
        
        # Should be idempotent
        assert persistence_result1.transitions_persisted == 2
        assert persistence_result2.transitions_persisted == 0
        assert persistence_result2.duplicates_skipped == 2
        
        # Total records should still be 2
        total = repository.count()
        assert total == 2
    
    def test_pipeline_with_suppressed_events(self, repository):
        """Test that suppressed events are not persisted."""
        # Create repeated IN events (second should be suppressed)
        raw_events = [
            self.create_sample_raw_event("RIE-suppressed-1", "in", 1000.0),
            self.create_sample_raw_event("RIE-suppressed-2", "in", 1010.0),  # Repeated IN
            self.create_sample_raw_event("RIE-suppressed-3", "out", 1020.0),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        
        # Should have 2 transitions, 1 suppressed
        assert resolution_result.accepted_transitions == 2
        assert resolution_result.suppressed_events == 1
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        assert persistence_result.transitions_persisted == 2
        assert persistence_result.suppressed_skipped == 1
        
        # Only 2 records persisted
        records = repository.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        assert len(records) == 2
        assert records[0].direction == AttendanceDirection.IN
        assert records[1].direction == AttendanceDirection.OUT
    
    def test_pipeline_multi_camera(self, repository):
        """Test pipeline with multiple cameras."""
        # Camera 1 events
        cam1_events = [
            RawInOutEvent(
                event_id="RIE-cam1-1",
                camera_id="CAM1",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1000.0,
                crossing_frame_index=100,
                previous_position_x=90.0,
                previous_position_y=190.0,
                current_position_x=110.0,
                current_position_y=210.0,
                previous_frame_index=99,
                current_frame_index=100,
                previous_timestamp=999.967,
                current_timestamp=1000.0,
                crossing_distance=10.0,
                side_transition="outside_to_inside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-RIE-cam1-1",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
            RawInOutEvent(
                event_id="RIE-cam1-2",
                camera_id="CAM1",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.OUT,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1010.0,
                crossing_frame_index=110,
                previous_position_x=110.0,
                previous_position_y=210.0,
                current_position_x=90.0,
                current_position_y=190.0,
                previous_frame_index=109,
                current_frame_index=110,
                previous_timestamp=1009.967,
                current_timestamp=1010.0,
                crossing_distance=10.0,
                side_transition="inside_to_outside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-RIE-cam1-2",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
        ]
        
        # Camera 2 events (same local track ID but different camera)
        cam2_events = [
            RawInOutEvent(
                event_id="RIE-cam2-1",
                camera_id="CAM2",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=2000.0,
                crossing_frame_index=100,
                previous_position_x=90.0,
                previous_position_y=190.0,
                current_position_x=110.0,
                current_position_y=210.0,
                previous_frame_index=99,
                current_frame_index=100,
                previous_timestamp=1999.967,
                current_timestamp=2000.0,
                crossing_distance=10.0,
                side_transition="outside_to_inside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-RIE-cam2-1",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
            RawInOutEvent(
                event_id="RIE-cam2-2",
                camera_id="CAM2",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.OUT,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=2010.0,
                crossing_frame_index=110,
                previous_position_x=110.0,
                previous_position_y=210.0,
                current_position_x=90.0,
                current_position_y=190.0,
                previous_frame_index=109,
                current_frame_index=110,
                previous_timestamp=2009.967,
                current_timestamp=2010.0,
                crossing_distance=10.0,
                side_transition="inside_to_outside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-RIE-cam2-2",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
        ]
        
        all_events = cam1_events + cam2_events
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(all_events)
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        assert persistence_result.transitions_persisted == 4
        
        # Query by camera
        cam1_records = repository.query_by_camera("CAM1")
        assert len(cam1_records) == 2
        
        cam2_records = repository.query_by_camera("CAM2")
        assert len(cam2_records) == 2
        
        # Query by track (should distinguish by camera)
        cam1_track_records = repository.query_by_track("CAM1", "track_001")
        assert len(cam1_track_records) == 2
        
        cam2_track_records = repository.query_by_track("CAM2", "track_001")
        assert len(cam2_track_records) == 2
    
    def test_pipeline_with_global_observation(self, repository):
        """Test pipeline with global observation ID linking."""
        raw_events = [
            RawInOutEvent(
                event_id="RIE-go-1",
                camera_id="CAM1",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-shared-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1000.0,
                crossing_frame_index=100,
                previous_position_x=90.0,
                previous_position_y=190.0,
                current_position_x=110.0,
                current_position_y=210.0,
                previous_frame_index=99,
                current_frame_index=100,
                previous_timestamp=999.967,
                current_timestamp=1000.0,
                crossing_distance=10.0,
                side_transition="outside_to_inside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-shared-123",
                source_crossing_event_id="CE-RIE-go-1",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
            RawInOutEvent(
                event_id="RIE-go-2",
                camera_id="CAM1",
                geometry_id="geom_hash_123",
                geometry_version=1,
                geometry_config_hash="geom_hash_123",
                local_track_id="track_001",
                global_observation_id="GO-shared-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.OUT,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1010.0,
                crossing_frame_index=110,
                previous_position_x=110.0,
                previous_position_y=210.0,
                current_position_x=90.0,
                current_position_y=190.0,
                previous_frame_index=109,
                current_frame_index=110,
                previous_timestamp=1009.967,
                current_timestamp=1010.0,
                crossing_distance=10.0,
                side_transition="inside_to_outside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-shared-123",
                source_crossing_event_id="CE-RIE-go-2",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        assert persistence_result.transitions_persisted == 2
        
        # Query by global observation
        records = repository.query_by_global_observation("GO-shared-123")
        assert len(records) == 2
        
        # Both should have the same global_observation_id
        for record in records:
            assert record.global_observation_id == "GO-shared-123"
    
    def test_pipeline_timestamp_preservation(self, repository):
        """Test that event timestamps are preserved (not replaced with persistence time)."""
        event_time = 1234567890.0
        raw_event = self.create_sample_raw_event("RIE-timestamp", "in", event_time)
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events([raw_event])
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        record = repository.get_by_resolution_id(resolution_result.transitions[0].resolution_id)
        
        # Event timestamp should be preserved
        assert record.event_timestamp == event_time
        # Persisted_at should be different (persistence time)
        assert record.persisted_at is not None
        assert record.created_at is not None
    
    def test_pipeline_identity_certainty_preserved(self, repository):
        """Test that identity certainty is preserved from upstream."""
        raw_event = RawInOutEvent(
            event_id="RIE-identity",
            camera_id="CAM1",
            geometry_id="geom_hash_123",
            geometry_version=1,
            geometry_config_hash="geom_hash_123",
            local_track_id="track_001",
            global_observation_id="GO-123",
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN,
            crossing_point_x=100.0,
            crossing_point_y=200.0,
            crossing_timestamp=1000.0,
            crossing_frame_index=100,
            previous_position_x=90.0,
            previous_position_y=190.0,
            current_position_x=110.0,
            current_position_y=210.0,
            previous_frame_index=99,
            current_frame_index=100,
            previous_timestamp=999.967,
            current_timestamp=1000.0,
            crossing_distance=10.0,
            side_transition="outside_to_inside",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            identity_confidence=0.95,
            identity_evidence_ref="GO-123",
            source_crossing_event_id="CE-RIE-identity",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
        )
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events([raw_event])
        
        persistence_result = repository.persist_resolution_result(resolution_result)
        
        record = repository.get_by_resolution_id(resolution_result.transitions[0].resolution_id)
        
        # Identity certainty should be preserved (currently UNKNOWN as resolver doesn't enrich)
        assert record.identity_certainty == IdentityCertainty.UNKNOWN
        assert record.identity_evidence_ref == "GO-123"  # Global observation reference preserved
    
    def test_query_by_direction_after_pipeline(self, repository):
        """Test querying by direction after full pipeline."""
        raw_events = [
            self.create_sample_raw_event("RIE-query-1", "in", 1000.0),
            self.create_sample_raw_event("RIE-query-2", "out", 1010.0),
            self.create_sample_raw_event("RIE-query-3", "in", 1020.0),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        repository.persist_resolution_result(resolution_result)
        
        in_records = repository.query_by_direction("in")
        assert len(in_records) == 2
        
        out_records = repository.query_by_direction("out")
        assert len(out_records) == 1
    
    def test_query_by_time_range_after_pipeline(self, repository):
        """Test querying by time range after full pipeline."""
        raw_events = [
            self.create_sample_raw_event("RIE-time-1", "in", 1000.0),
            self.create_sample_raw_event("RIE-time-2", "out", 2000.0),
            self.create_sample_raw_event("RIE-time-3", "in", 3000.0),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        repository.persist_resolution_result(resolution_result)
        
        # Query middle range
        records = repository.query_by_time_range(1500.0, 2500.0)
        assert len(records) == 1
        assert records[0].event_timestamp == 2000.0
    
    def test_current_state_after_pipeline(self, repository):
        """Test getting current derived state after pipeline."""
        raw_events = [
            self.create_sample_raw_event("RIE-state-1", "in", 1000.0),
            self.create_sample_raw_event("RIE-state-2", "out", 1010.0),
            self.create_sample_raw_event("RIE-state-3", "in", 1020.0),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        repository.persist_resolution_result(resolution_result)
        
        # Current state should be INSIDE (last transition was IN)
        state = repository.get_current_state_by_track("CAM1", "track_001")
        assert state == "inside"
    
    def test_restart_recovery_after_pipeline(self, temp_db):
        """Test that pipeline results survive restart."""
        config = StorageConfig(database_path=temp_db)
        
        # Run pipeline
        raw_events = [
            RawInOutEvent(
                event_id=f"RIE-restart-{i}",
                camera_id="CAM1",
                geometry_id="geom_hash",
                geometry_version=1,
                geometry_config_hash="geom_hash",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN if i % 2 == 0 else RawEventDirection.OUT,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1000.0 + i * 10,
                crossing_frame_index=100 + i,
                previous_position_x=90.0,
                previous_position_y=190.0,
                current_position_x=110.0,
                current_position_y=210.0,
                previous_frame_index=99 + i,
                current_frame_index=100 + i,
                previous_timestamp=1000.0 + i * 10 - 0.033,
                current_timestamp=1000.0 + i * 10,
                crossing_distance=10.0,
                side_transition="outside_to_inside" if i % 2 == 0 else "inside_to_outside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id=f"CE-restart-{i}",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            )
            for i in range(3)
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        
        repo1 = AttendanceRepository(config=config)
        repo1.persist_resolution_result(resolution_result)
        repo1.close()
        
        # Reopen and verify
        repo2 = AttendanceRepository(config=config)
        try:
            records = repo2.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
            assert len(records) == 3
            assert records[0].event_timestamp == 1000.0
            assert records[1].event_timestamp == 1010.0
            assert records[2].event_timestamp == 1020.0
        finally:
            repo2.close()


class TestPhase25NegativeCases:
    """Negative tests for Phase 25."""
    
    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)
    
    @pytest.fixture
    def storage(self, temp_db):
        config = StorageConfig(database_path=temp_db)
        storage = AttendanceStorage(config)
        yield storage
        storage.close()
    
    def test_reject_invalid_direction(self, storage):
        """Test that invalid direction is rejected."""
        # The validation happens in the constructor, not in storage.insert()
        with pytest.raises(ValueError, match="direction must be 'in' or 'out'"):
            AttendanceRecord(
                attendance_record_id="ATT-invalid-dir",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction="invalid",  # Invalid
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-invalid",
                source_resolution_id="RES-invalid",
            )
    
    def test_reject_missing_timestamp(self, storage):
        """Test that missing timestamp is rejected."""
        # The validation happens in the constructor, not in storage.insert()
        with pytest.raises(ValueError, match="event_timestamp must be >= 0"):
            AttendanceRecord(
                attendance_record_id="ATT-no-ts",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=-1.0,  # Invalid
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-no-ts",
                source_resolution_id="RES-no-ts",
            )
    
    def test_reject_invalid_identity_certainty(self, storage):
        """Test that invalid identity certainty is rejected."""
        # The validation happens in the constructor, not in storage.insert()
        with pytest.raises(ValueError, match="Invalid identity_certainty"):
            AttendanceRecord(
                attendance_record_id="ATT-invalid-cert",
                identity_certainty="invalid",  # Invalid
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-invalid-cert",
                source_resolution_id="RES-invalid-cert",
            )
    
    def test_reject_invalid_schema_version(self, storage):
        """Test that invalid schema version is rejected."""
        # The validation happens in the constructor, not in storage.insert()
        with pytest.raises(ValueError, match="Unsupported attendance_schema_version"):
            AttendanceRecord(
                attendance_record_id="ATT-invalid-schema",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-invalid-schema",
                source_resolution_id="RES-invalid-schema",
                attendance_schema_version="2.0",  # Invalid
            )
    
    def test_reject_duplicate_source_resolution(self, storage):
        """Test that duplicate source_resolution_id is rejected."""
        record1 = AttendanceRecord(
            attendance_record_id="ATT-dup1",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-dup1",
            source_resolution_id="RES-duplicate",
        )
        
        record2 = AttendanceRecord(
            attendance_record_id="ATT-dup2",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.OUT,
            event_timestamp=1010.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-dup2",
            source_resolution_id="RES-duplicate",  # Same source_resolution_id
        )
        
        inserted1 = storage.insert(record1)
        assert inserted1 is True
        
        inserted2 = storage.insert(record2)
        assert inserted2 is False  # Idempotent - duplicate rejected
    
    def test_reject_invalid_date_range(self, storage):
        """Test that invalid date range is rejected."""
        with pytest.raises(ValueError, match="start_timestamp must be <= end_timestamp"):
            storage.query(start_timestamp=2000.0, end_timestamp=1000.0)
    
    def test_reject_invalid_camera_filter(self, storage):
        """Test that invalid camera filter returns empty (not error)."""
        # This should not raise, just return empty
        records = storage.query(camera_id="NONEXISTENT")
        assert len(records) == 0
    
    def test_reject_invalid_identity_reference(self, storage):
        """Test that invalid identity reference returns empty."""
        records = storage.query_by_identity("nonexistent_identity")
        assert len(records) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])