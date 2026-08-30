"""
Phase 25 — Unit Tests for Attendance Contract.

Tests for AttendanceRecord contract, creation, validation, and serialization.
"""

import pytest
from datetime import datetime

from app.attendance.contract import (
    AttendanceRecord,
    AttendanceRecordCreationResult,
    AttendanceDirection,
    IdentityCertainty,
    generate_attendance_record_id,
    create_attendance_record_from_resolution,
    validate_attendance_record,
)
from app.in_out.resolver_contract import (
    ResolvedTransition,
    TransitionType,
    DerivedState,
    ResolutionStatus,
    generate_resolution_id,
)


class TestAttendanceDirection:
    """Tests for AttendanceDirection enum."""
    
    def test_in_value(self):
        assert AttendanceDirection.IN.value == "in"
    
    def test_out_value(self):
        assert AttendanceDirection.OUT.value == "out"


class TestIdentityCertainty:
    """Tests for IdentityCertainty enum."""
    
    def test_values(self):
        assert IdentityCertainty.KNOWN.value == "known"
        assert IdentityCertainty.UNKNOWN.value == "unknown"
        assert IdentityCertainty.AMBIGUOUS.value == "ambiguous"
        assert IdentityCertainty.INSUFFICIENT.value == "insufficient"


class TestAttendanceRecord:
    """Tests for AttendanceRecord dataclass."""
    
    def create_valid_record(self) -> AttendanceRecord:
        """Create a valid attendance record for testing."""
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
    
    def test_valid_record_creation(self):
        record = self.create_valid_record()
        assert record.attendance_record_id == "ATT-test123"
        assert record.direction == AttendanceDirection.IN
        assert record.identity_certainty == IdentityCertainty.UNKNOWN
        assert record.camera_id == "CAM1"
        assert record.local_track_id == "track_001"
        assert record.is_in is True
        assert record.is_out is False
        assert record.is_unknown_identity is True
        assert record.is_known_identity is False
    
    def test_out_direction(self):
        record = self.create_valid_record()
        record = AttendanceRecord(
            **{**record.to_dict(), "direction": "out"}
        )
        assert record.is_in is False
        assert record.is_out is True
    
    def test_known_identity(self):
        record = self.create_valid_record()
        record = AttendanceRecord(
            **{**record.to_dict(), "identity_certainty": "known", "identity_candidate": "student_001", "identity_confidence": 0.95}
        )
        assert record.is_known_identity is True
        assert record.is_unknown_identity is False
    
    def test_missing_attendance_record_id_raises(self):
        with pytest.raises(ValueError, match="attendance_record_id is required"):
            AttendanceRecord(
                attendance_record_id="",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_missing_source_raw_event_id_raises(self):
        with pytest.raises(ValueError, match="source_raw_event_id is required"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="",
                source_resolution_id="RES-xyz789",
            )
    
    def test_missing_source_resolution_id_raises(self):
        with pytest.raises(ValueError, match="source_resolution_id is required"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="",
            )
    
    def test_missing_camera_id_raises(self):
        with pytest.raises(ValueError, match="camera_id is required"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_missing_local_track_id_raises(self):
        with pytest.raises(ValueError, match="local_track_id is required"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="direction must be 'in' or 'out'"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction="invalid",
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_negative_timestamp_raises(self):
        with pytest.raises(ValueError, match="event_timestamp must be >= 0"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=-1.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_invalid_schema_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported attendance_schema_version"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
                attendance_schema_version="2.0",
            )
    
    def test_invalid_identity_certainty_raises(self):
        with pytest.raises(ValueError, match="Invalid identity_certainty"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty="invalid",
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )
    
    def test_invalid_previous_state_raises(self):
        with pytest.raises(ValueError, match="Invalid previous_state"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
                previous_state="invalid",
            )
    
    def test_invalid_new_state_raises(self):
        with pytest.raises(ValueError, match="Invalid new_state"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
                new_state="invalid",
            )
    
    def test_to_dict_serialization(self):
        record = self.create_valid_record()
        data = record.to_dict()
        
        assert data["attendance_record_id"] == "ATT-test123"
        assert data["direction"] == "in"
        assert data["identity_certainty"] == "unknown"
        assert data["camera_id"] == "CAM1"
        assert data["event_timestamp"] == 1000.0
        assert "created_at" in data
        assert "persisted_at" in data
    
    def test_from_dict_deserialization(self):
        record = self.create_valid_record()
        data = record.to_dict()
        restored = AttendanceRecord.from_dict(data)
        
        assert restored.attendance_record_id == record.attendance_record_id
        assert restored.direction == record.direction
        assert restored.identity_certainty == record.identity_certainty
        assert restored.camera_id == record.camera_id
        assert restored.event_timestamp == record.event_timestamp
    
    def test_json_roundtrip(self):
        record = self.create_valid_record()
        json_str = record.to_json()
        restored = AttendanceRecord.from_json(json_str)
        
        assert restored.attendance_record_id == record.attendance_record_id
        assert restored.direction == record.direction
        assert restored.identity_certainty == record.identity_certainty
        assert restored.camera_id == record.camera_id
        assert restored.event_timestamp == record.event_timestamp


class TestGenerateAttendanceRecordId:
    """Tests for deterministic attendance record ID generation."""
    
    def test_deterministic(self):
        id1 = generate_attendance_record_id("RES-abc123", "1.0")
        id2 = generate_attendance_record_id("RES-abc123", "1.0")
        assert id1 == id2
    
    def test_different_resolution_id_produces_different_id(self):
        id1 = generate_attendance_record_id("RES-abc123", "1.0")
        id2 = generate_attendance_record_id("RES-def456", "1.0")
        assert id1 != id2
    
    def test_format(self):
        id1 = generate_attendance_record_id("RES-abc123", "1.0")
        assert id1.startswith("ATT-")
        assert len(id1) == 20  # "ATT-" + 16 hex chars


class TestValidateAttendanceRecord:
    """Tests for attendance record validation."""

    def test_valid_record_passes(self):
        record = AttendanceRecord(
            attendance_record_id="ATT-test123",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-abc123",
            source_resolution_id="RES-xyz789",
        )
        error = validate_attendance_record(record)
        assert error is None

    def test_missing_attendance_record_id_fails(self):
        with pytest.raises(ValueError, match="attendance_record_id is required"):
            AttendanceRecord(
                attendance_record_id="",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )

    def test_negative_timestamp_fails(self):
        with pytest.raises(ValueError, match="event_timestamp must be >= 0"):
            AttendanceRecord(
                attendance_record_id="ATT-test123",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=-1.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-abc123",
                source_resolution_id="RES-xyz789",
            )


class TestCreateAttendanceRecordFromResolution:
    """Tests for creating AttendanceRecord from Phase 24 ResolvedTransition."""
    
    def create_sample_resolution(self, transition_type: TransitionType = TransitionType.IN) -> ResolvedTransition:
        """Create a sample ResolvedTransition for testing."""
        if transition_type == TransitionType.IN:
            previous_state = DerivedState.UNKNOWN
            new_state = DerivedState.INSIDE
        elif transition_type == TransitionType.OUT:
            previous_state = DerivedState.INSIDE
            new_state = DerivedState.OUTSIDE
        else:
            previous_state = DerivedState.UNKNOWN
            new_state = DerivedState.UNKNOWN
        
        return ResolvedTransition(
            resolution_id="RES-test123",
            source_raw_event_id="RIE-abc123",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-123",
            direction="in" if transition_type == TransitionType.IN else "out",
            transition_type=transition_type,
            previous_state=previous_state,
            new_state=new_state,
            source_timestamp=1000.0,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config_hash",
            resolution_status=ResolutionStatus.ACCEPTED,
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash",
        )
    
    def test_creates_record_for_in_transition(self):
        resolution = self.create_sample_resolution(TransitionType.IN)
        result = create_attendance_record_from_resolution(resolution)
        
        assert result.success is True
        assert result.record is not None
        assert result.record.direction == AttendanceDirection.IN
        assert result.record.previous_state == "unknown"
        assert result.record.new_state == "inside"
        assert result.record.source_resolution_id == "RES-test123"
        assert result.record.source_raw_event_id == "RIE-abc123"
        assert result.record.camera_id == "CAM1"
        assert result.record.local_track_id == "track_001"
        assert result.record.global_observation_id == "GO-123"
    
    def test_creates_record_for_out_transition(self):
        resolution = self.create_sample_resolution(TransitionType.OUT)
        result = create_attendance_record_from_resolution(resolution)
        
        assert result.success is True
        assert result.record.direction == AttendanceDirection.OUT
        assert result.record.previous_state == "inside"
        assert result.record.new_state == "outside"
    
    def test_rejects_suppressed_transition(self):
        resolution = self.create_sample_resolution(TransitionType.NONE)
        resolution = ResolvedTransition(
            **{**resolution.to_dict(), "transition_type": "none", "resolution_status": "suppressed"}
        )
        result = create_attendance_record_from_resolution(resolution)
        
        assert result.success is False
        assert result.rejection_reason == "not_a_transition"
    
    def test_rejects_rejected_transition(self):
        resolution = self.create_sample_resolution(TransitionType.NONE)
        resolution = ResolvedTransition(
            **{**resolution.to_dict(), "transition_type": "none", "resolution_status": "rejected"}
        )
        result = create_attendance_record_from_resolution(resolution)
        
        assert result.success is False
        assert result.rejection_reason == "not_a_transition"
    
    def test_preserves_provenance_chain(self):
        resolution = self.create_sample_resolution(TransitionType.IN)
        result = create_attendance_record_from_resolution(resolution)
        
        assert result.success is True
        record = result.record
        assert record.source_resolution_id == resolution.resolution_id
        assert record.source_raw_event_id == resolution.source_raw_event_id
        assert record.source_crossing_event_id == resolution.source_crossing_event_id
        assert record.geometry_version == resolution.geometry_version
        assert record.geometry_config_hash == resolution.geometry_config_hash
        assert record.resolver_version == resolution.resolver_version
        assert record.resolver_config_hash == resolution.resolver_config_hash
    
    def test_deterministic_record_id(self):
        resolution = self.create_sample_resolution(TransitionType.IN)
        result1 = create_attendance_record_from_resolution(resolution)
        result2 = create_attendance_record_from_resolution(resolution)
        
        assert result1.success is True
        assert result2.success is True
        assert result1.record.attendance_record_id == result2.record.attendance_record_id


class TestAttendanceRecordCreationResult:
    """Tests for AttendanceRecordCreationResult."""
    
    def test_success_result(self):
        record = AttendanceRecord(
            attendance_record_id="ATT-test123",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-abc123",
            source_resolution_id="RES-xyz789",
        )
        result = AttendanceRecordCreationResult.success_result(record)
        
        assert result.success is True
        assert result.record == record
        assert result.error is None
        assert result.rejection_reason is None
    
    def test_failure_result(self):
        result = AttendanceRecordCreationResult.failure_result("Test error", "test_reason")
        
        assert result.success is False
        assert result.record is None
        assert result.error == "Test error"
        assert result.rejection_reason == "test_reason"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])