"""
Phase 25 — Unit Tests for Attendance Repository and Storage.

Tests for persistence, idempotency, queries, and restart/recovery.
"""

import pytest
import tempfile
import os
import time

from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    IdentityCertainty,
)
from app.attendance.storage import AttendanceStorage, StorageConfig
from app.attendance.repository import AttendanceRepository, PersistenceResult
from app.in_out.resolver_contract import (
    ResolvedTransition,
    TrackResolutionState,
    ResolutionResult,
    TransitionType,
    DerivedState,
    ResolutionStatus,
    generate_resolution_id,
    generate_config_hash,
)
from app.in_out.resolver_config import ResolverConfig


class TestAttendanceStorage:
    """Tests for AttendanceStorage."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)
        # Also cleanup WAL files
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)
    
    @pytest.fixture
    def storage(self, temp_db):
        """Create storage with temp database."""
        config = StorageConfig(database_path=temp_db)
        storage = AttendanceStorage(config)
        yield storage
        storage.close()
    
    @pytest.fixture
    def sample_record(self):
        """Create a sample attendance record."""
        return AttendanceRecord(
            attendance_record_id="ATT-test123",
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref="GO-123",
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-123",
            source_raw_event_id="RIE-abc123",
            source_resolution_id="RES-xyz789",
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_123",
            resolver_version="1.0",
            resolver_config_hash="config_hash_456",
            previous_state="unknown",
            new_state="inside",
            attendance_schema_version="1.0",
            created_at="2026-01-01T00:00:00Z",
            persisted_at="2026-01-01T00:00:00Z",
        )
    
    def test_insert_and_get(self, storage, sample_record):
        """Test basic insert and retrieval."""
        inserted = storage.insert(sample_record)
        assert inserted is True
        
        retrieved = storage.get_by_id("ATT-test123")
        assert retrieved is not None
        assert retrieved.attendance_record_id == "ATT-test123"
        assert retrieved.camera_id == "CAM1"
        assert retrieved.direction == AttendanceDirection.IN
        assert retrieved.event_timestamp == 1000.0
    
    def test_idempotent_insert_by_source_resolution_id(self, storage, sample_record):
        """Test that duplicate source_resolution_id is rejected (idempotent)."""
        # First insert
        inserted1 = storage.insert(sample_record)
        assert inserted1 is True
        
        # Second insert with same source_resolution_id but different attendance_record_id
        duplicate_record = AttendanceRecord(
            **{**sample_record.to_dict(), "attendance_record_id": "ATT-different456"}
        )
        inserted2 = storage.insert(duplicate_record)
        assert inserted2 is False  # Should be idempotent
        
        # Should still have only one record
        retrieved = storage.get_by_source_resolution_id("RES-xyz789")
        assert retrieved is not None
        assert retrieved.attendance_record_id == "ATT-test123"  # Original preserved
    
    def test_idempotent_insert_by_attendance_record_id(self, storage, sample_record):
        """Test that duplicate attendance_record_id is rejected."""
        inserted1 = storage.insert(sample_record)
        assert inserted1 is True
        
        # Try to insert same record again
        inserted2 = storage.insert(sample_record)
        assert inserted2 is False
    
    def test_insert_many(self, storage):
        """Test batch insert."""
        records = []
        for i in range(5):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-batch{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i % 2 == 0 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-batch{i}",
                source_resolution_id=f"RES-batch{i}",
            )
            records.append(record)
        
        inserted, duplicates = storage.insert_many(records)
        assert inserted == 5
        assert duplicates == 0
        
        # Insert again - all should be duplicates
        inserted2, duplicates2 = storage.insert_many(records)
        assert inserted2 == 0
        assert duplicates2 == 5
    
    def test_query_by_camera(self, storage):
        """Test query by camera."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-cam{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-cam{i}",
                source_resolution_id=f"RES-cam{i}",
            )
            storage.insert(record)
        
        # Add record for different camera
        record2 = AttendanceRecord(
            attendance_record_id="ATT-cam2-other",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=2000.0,
            camera_id="CAM2",
            local_track_id="track_other",
            source_raw_event_id="RIE-other",
            source_resolution_id="RES-other",
        )
        storage.insert(record2)
        
        cam1_records = storage.query(camera_id="CAM1")
        assert len(cam1_records) == 3
        
        cam2_records = storage.query(camera_id="CAM2")
        assert len(cam2_records) == 1
    
    def test_query_by_track(self, storage):
        """Test query by camera and local track."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-track{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i % 2 == 0 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id=f"RIE-track{i}",
                source_resolution_id=f"RES-track{i}",
            )
            storage.insert(record)
        
        records = storage.query(camera_id="CAM1", local_track_id="track_001")
        assert len(records) == 3
        # Should be ordered by timestamp
        assert records[0].event_timestamp == 1000.0
        assert records[1].event_timestamp == 1010.0
        assert records[2].event_timestamp == 1020.0
    
    def test_query_by_global_observation(self, storage):
        """Test query by global observation ID."""
        for i in range(2):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-go{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                global_observation_id="GO-shared",
                source_raw_event_id=f"RIE-go{i}",
                source_resolution_id=f"RES-go{i}",
            )
            storage.insert(record)
        
        records = storage.query(global_observation_id="GO-shared")
        assert len(records) == 2
    
    def test_query_by_direction(self, storage):
        """Test query by direction."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-dir{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i < 2 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-dir{i}",
                source_resolution_id=f"RES-dir{i}",
            )
            storage.insert(record)
        
        in_records = storage.query(direction="in")
        assert len(in_records) == 2
        
        out_records = storage.query(direction="out")
        assert len(out_records) == 1
    
    def test_query_by_time_range(self, storage):
        """Test query by time range [start, end)."""
        base_time = 1000.0
        for i in range(5):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-time{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=base_time + i * 100,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-time{i}",
                source_resolution_id=f"RES-time{i}",
            )
            storage.insert(record)
        
        # Query [1100, 1300) - should get records at 1100, 1200
        records = storage.query(start_timestamp=1100.0, end_timestamp=1300.0)
        assert len(records) == 2
        assert records[0].event_timestamp == 1100.0
        assert records[1].event_timestamp == 1200.0
        
        # Query [1000, 1000) - empty range
        records = storage.query(start_timestamp=1000.0, end_timestamp=1000.0)
        assert len(records) == 0
    
    def test_query_invalid_time_range_raises(self, storage):
        """Test that invalid time range raises error."""
        with pytest.raises(ValueError, match="start_timestamp must be <= end_timestamp"):
            storage.query(start_timestamp=2000.0, end_timestamp=1000.0)
    
    def test_query_with_limit_and_offset(self, storage):
        """Test pagination with limit and offset."""
        for i in range(10):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-page{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-page{i}",
                source_resolution_id=f"RES-page{i}",
            )
            storage.insert(record)
        
        # First page
        page1 = storage.query(limit=3, offset=0)
        assert len(page1) == 3
        assert page1[0].event_timestamp == 1000.0
        
        # Second page
        page2 = storage.query(limit=3, offset=3)
        assert len(page2) == 3
        assert page2[0].event_timestamp == 1030.0
    
    def test_query_ordering_deterministic(self, storage):
        """Test that ordering is deterministic for equal timestamps."""
        # Insert records with same timestamp but different IDs
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-order{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,  # Same timestamp
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-order{i}",
                source_resolution_id=f"RES-order{i}",
            )
            storage.insert(record)
        
        records = storage.query(order_by="event_timestamp")
        assert len(records) == 3
        # Should be ordered by attendance_record_id as secondary key
        assert records[0].attendance_record_id == "ATT-order0"
        assert records[1].attendance_record_id == "ATT-order1"
        assert records[2].attendance_record_id == "ATT-order2"
    
    def test_get_chronological_history(self, storage):
        """Test chronological history retrieval."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-hist{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i % 2 == 0 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id=f"RIE-hist{i}",
                source_resolution_id=f"RES-hist{i}",
            )
            storage.insert(record)
        
        history = storage.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        assert len(history) == 3
        assert history[0].event_timestamp == 1000.0
        assert history[1].event_timestamp == 1010.0
        assert history[2].event_timestamp == 1020.0
    
    def test_get_latest_by_track(self, storage):
        """Test getting latest record for a track."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-latest{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i % 2 == 0 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id=f"RIE-latest{i}",
                source_resolution_id=f"RES-latest{i}",
            )
            storage.insert(record)
        
        latest = storage.get_latest_by_track("CAM1", "track_001")
        assert latest is not None
        assert latest.event_timestamp == 1020.0
        assert latest.attendance_record_id == "ATT-latest2"
    
    def test_count(self, storage):
        """Test counting records."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-count{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-count{i}",
                source_resolution_id=f"RES-count{i}",
            )
            storage.insert(record)
        
        total = storage.count()
        assert total == 3
        
        cam1_count = storage.count(camera_id="CAM1")
        assert cam1_count == 3
        
        cam2_count = storage.count(camera_id="CAM2")
        assert cam2_count == 0
    
    def test_get_stats(self, storage):
        """Test storage statistics."""
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-stats{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN if i < 2 else AttendanceDirection.OUT,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1" if i < 2 else "CAM2",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-stats{i}",
                source_resolution_id=f"RES-stats{i}",
            )
            storage.insert(record)
        
        stats = storage.get_stats()
        assert stats["total_records"] == 3
        assert stats["by_direction"]["in"] == 2
        assert stats["by_direction"]["out"] == 1
        assert stats["by_camera"]["CAM1"] == 2
        assert stats["by_camera"]["CAM2"] == 1
        assert stats["event_timestamp_range"]["min"] == 1000.0
        assert stats["event_timestamp_range"]["max"] == 1020.0
    
    def test_restart_recovery(self, temp_db):
        """Test that records survive database restart."""
        config = StorageConfig(database_path=temp_db)
        
        # Create storage and insert records
        storage1 = AttendanceStorage(config)
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-restart{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-restart{i}",
                source_resolution_id=f"RES-restart{i}",
            )
            storage1.insert(record)
        storage1.close()
        
        # Reopen storage
        storage2 = AttendanceStorage(config)
        try:
            count = storage2.count()
            assert count == 3
            
            for i in range(3):
                retrieved = storage2.get_by_id(f"ATT-restart{i}")
                assert retrieved is not None
                assert retrieved.event_timestamp == 1000.0 + i * 10
        finally:
            storage2.close()
    
    def test_exists_by_source_resolution_id(self, storage, sample_record):
        """Test checking existence by source resolution ID."""
        assert storage.exists_by_source_resolution_id("RES-xyz789") is False
        
        storage.insert(sample_record)
        
        assert storage.exists_by_source_resolution_id("RES-xyz789") is True
        assert storage.exists_by_source_resolution_id("RES-nonexistent") is False
    
    def test_invalid_record_rejected(self, storage):
        """Test that invalid records are rejected."""
        # The validation happens in the constructor, not in storage.insert()
        with pytest.raises(ValueError, match="event_timestamp must be >= 0"):
            AttendanceRecord(
                attendance_record_id="ATT-invalid",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=-1.0,  # Invalid
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-invalid",
                source_resolution_id="RES-invalid",
            )


class TestAttendanceRepository:
    """Tests for AttendanceRepository."""
    
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
    
    def create_sample_resolution(self, resolution_id: str, transition_type: TransitionType = TransitionType.IN) -> ResolvedTransition:
        """Create a sample ResolvedTransition."""
        return ResolvedTransition(
            resolution_id=resolution_id,
            source_raw_event_id=f"RIE-{resolution_id}",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-123",
            direction="in" if transition_type == TransitionType.IN else "out",
            transition_type=transition_type,
            previous_state=DerivedState.UNKNOWN if transition_type == TransitionType.IN else DerivedState.INSIDE,
            new_state=DerivedState.INSIDE if transition_type == TransitionType.IN else DerivedState.OUTSIDE,
            source_timestamp=1000.0,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config_hash",
            resolution_status=ResolutionStatus.ACCEPTED,
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash",
        )
    
    def test_persist_resolution_result(self, repository):
        """Test persisting a ResolutionResult."""
        transitions = [
            self.create_sample_resolution("RES-001", TransitionType.IN),
            self.create_sample_resolution("RES-002", TransitionType.OUT),
            self.create_sample_resolution("RES-003", TransitionType.NONE),  # Suppressed
        ]
        
        # Create a resolution with suppressed transition
        suppressed = ResolvedTransition(
            **{**transitions[2].to_dict(), "resolution_status": "suppressed"}
        )
        transitions[2] = suppressed
        
        result = ResolutionResult(
            transitions=transitions,
            total_raw_events=3,
            accepted_transitions=2,
            suppressed_events=1,
        )
        
        persistence_result = repository.persist_resolution_result(result)
        
        assert persistence_result.total_resolutions == 3
        assert persistence_result.transitions_persisted == 2
        assert persistence_result.suppressed_skipped == 1
        assert persistence_result.duplicates_skipped == 0
    
    def test_persist_single_resolution(self, repository):
        """Test persisting a single resolution."""
        transition = self.create_sample_resolution("RES-single", TransitionType.IN)
        
        result = repository.persist_single_resolution(transition)
        
        assert result.success is True
        assert result.record is not None
        assert result.record.source_resolution_id == "RES-single"
        assert result.record.direction == AttendanceDirection.IN
    
    def test_idempotent_persist_single(self, repository):
        """Test that persisting same resolution twice is idempotent."""
        transition = self.create_sample_resolution("RES-idempotent", TransitionType.IN)
        
        result1 = repository.persist_single_resolution(transition)
        result2 = repository.persist_single_resolution(transition)
        
        assert result1.success is True
        assert result2.success is True
        assert result1.record.attendance_record_id == result2.record.attendance_record_id
    
    def test_get_by_resolution_id(self, repository):
        """Test getting record by resolution ID."""
        transition = self.create_sample_resolution("RES-get", TransitionType.IN)
        repository.persist_single_resolution(transition)
        
        record = repository.get_by_resolution_id("RES-get")
        assert record is not None
        assert record.source_resolution_id == "RES-get"
        
        # Non-existent
        record = repository.get_by_resolution_id("RES-nonexistent")
        assert record is None
    
    def test_exists_by_resolution_id(self, repository):
        """Test checking existence by resolution ID."""
        assert repository.exists_by_resolution_id("RES-exists") is False
        
        transition = self.create_sample_resolution("RES-exists", TransitionType.IN)
        repository.persist_single_resolution(transition)
        
        assert repository.exists_by_resolution_id("RES-exists") is True
    
    def test_query_by_camera(self, repository):
        """Test query by camera."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-cam{i}", TransitionType.IN)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "camera_id": "CAM1", "local_track_id": f"track_{i:03d}"}
            )
            repository.persist_single_resolution(transition)
        
        # Different camera
        transition = self.create_sample_resolution("RES-cam-other", TransitionType.IN)
        transition = ResolvedTransition(
            **{**transition.to_dict(), "camera_id": "CAM2", "local_track_id": "track_other"}
        )
        repository.persist_single_resolution(transition)
        
        records = repository.query_by_camera("CAM1")
        assert len(records) == 3
    
    def test_query_by_track(self, repository):
        """Test query by camera and track."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-track{i}", TransitionType.IN if i % 2 == 0 else TransitionType.OUT)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "camera_id": "CAM1", "local_track_id": "track_001"}
            )
            repository.persist_single_resolution(transition)
        
        records = repository.query_by_track("CAM1", "track_001")
        assert len(records) == 3
    
    def test_query_by_global_observation(self, repository):
        """Test query by global observation."""
        for i in range(2):
            transition = self.create_sample_resolution(f"RES-go{i}", TransitionType.IN)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "global_observation_id": "GO-shared"}
            )
            repository.persist_single_resolution(transition)
        
        records = repository.query_by_global_observation("GO-shared")
        assert len(records) == 2
    
    def test_query_by_direction(self, repository):
        """Test query by direction."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-dir{i}", TransitionType.IN if i < 2 else TransitionType.OUT)
            repository.persist_single_resolution(transition)
        
        in_records = repository.query_by_direction("in")
        assert len(in_records) == 2
        
        out_records = repository.query_by_direction("out")
        assert len(out_records) == 1
    
    def test_query_by_time_range(self, repository):
        """Test query by time range."""
        base_time = 1000.0
        for i in range(5):
            transition = self.create_sample_resolution(f"RES-time{i}", TransitionType.IN)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "source_timestamp": base_time + i * 100}
            )
            repository.persist_single_resolution(transition)
        
        records = repository.query_by_time_range(1100.0, 1300.0)
        assert len(records) == 2
    
    def test_get_chronological_history(self, repository):
        """Test chronological history."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-hist{i}", TransitionType.IN if i % 2 == 0 else TransitionType.OUT)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "source_timestamp": 1000.0 + i * 10}
            )
            repository.persist_single_resolution(transition)
        
        history = repository.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        assert len(history) == 3
        assert history[0].event_timestamp == 1000.0
        assert history[2].event_timestamp == 1020.0
    
    def test_get_latest_by_track(self, repository):
        """Test getting latest by track."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-latest{i}", TransitionType.IN)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "source_timestamp": 1000.0 + i * 10}
            )
            repository.persist_single_resolution(transition)
        
        latest = repository.get_latest_by_track("CAM1", "track_001")
        assert latest is not None
        assert latest.event_timestamp == 1020.0
    
    def test_get_current_state_by_track(self, repository):
        """Test getting current derived state by track."""
        # No records yet
        state = repository.get_current_state_by_track("CAM1", "track_001")
        assert state is None
        
        # Add IN transition
        transition = self.create_sample_resolution("RES-state1", TransitionType.IN)
        repository.persist_single_resolution(transition)
        
        state = repository.get_current_state_by_track("CAM1", "track_001")
        assert state == "inside"
        
        # Add OUT transition
        transition = self.create_sample_resolution("RES-state2", TransitionType.OUT)
        transition = ResolvedTransition(
            **{**transition.to_dict(), "previous_state": "inside", "new_state": "outside", "source_timestamp": 1010.0}
        )
        repository.persist_single_resolution(transition)
        
        state = repository.get_current_state_by_track("CAM1", "track_001")
        assert state == "outside"
    
    def test_count(self, repository):
        """Test counting records."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-count{i}", TransitionType.IN)
            repository.persist_single_resolution(transition)
        
        count = repository.count()
        assert count == 3
    
    def test_get_stats(self, repository):
        """Test repository statistics."""
        for i in range(3):
            transition = self.create_sample_resolution(f"RES-stats{i}", TransitionType.IN if i < 2 else TransitionType.OUT)
            transition = ResolvedTransition(
                **{**transition.to_dict(), "camera_id": "CAM1" if i < 2 else "CAM2"}
            )
            repository.persist_single_resolution(transition)
        
        stats = repository.get_stats()
        assert stats["total_records"] == 3
        assert stats["by_direction"]["in"] == 2
        assert stats["by_direction"]["out"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])