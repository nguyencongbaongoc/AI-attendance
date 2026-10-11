"""
Phase 29 — Unit Tests for ImmediateEvent Contract.

Tests:
- ImmediateEvent contract validation
- Serialization/deserialization
- Deterministic ID generation
- Versioning
- Validation
"""

import pytest
from datetime import datetime

from app.output.contract import (
    ImmediateEvent,
    ImmediateEventType,
    ImmediateEventDirection,
    IdentityCertainty,
    EventDeliveryStatus,
    generate_immediate_event_id,
    validate_immediate_event,
    ImmediateEventCreationResult,
)


class TestImmediateEventContract:
    """Tests for ImmediateEvent contract."""
    
    def test_create_valid_attendance_in_event(self):
        """Test creating a valid ATTENDANCE_IN event."""
        event = ImmediateEvent(
            event_id="IEV-test123",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            source_crossing_event_id="CE-001",
            source_attendance_decision_id="DEC-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            attendance_policy_id="policy_default",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown",
            new_attendance_state="present",
            decision_reason="within_entry_window",
            timetable_id="timetable_2024",
            timetable_version="1.0",
            session_id="morning",
            day="monday",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
        )
        
        assert event.event_id == "IEV-test123"
        assert event.event_type == ImmediateEventType.ATTENDANCE_IN
        assert event.direction == ImmediateEventDirection.IN
        assert event.identity_certainty == IdentityCertainty.KNOWN
        assert event.is_in is True
        assert event.is_out is False
        assert event.is_known_identity is True
        assert event.is_attendance_event is True
    
    def test_create_valid_attendance_out_event(self):
        """Test creating a valid ATTENDANCE_OUT event."""
        event = ImmediateEvent(
            event_id="IEV-test456",
            event_type=ImmediateEventType.ATTENDANCE_OUT,
            direction=ImmediateEventDirection.OUT,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700003600.0,
            event_frame_index=200,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-002",
            source_resolution_id="RES-002",
            source_crossing_event_id="CE-002",
            source_attendance_decision_id="DEC-002",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            attendance_policy_id="policy_default",
            attendance_policy_version="1.0",
            previous_attendance_state="present",
            new_attendance_state="left",
            decision_reason="exit_recorded",
            timetable_id="timetable_2024",
            timetable_version="1.0",
            session_id="morning",
            day="monday",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=2,
        )
        
        assert event.event_type == ImmediateEventType.ATTENDANCE_OUT
        assert event.direction == ImmediateEventDirection.OUT
        assert event.is_out is True
        assert event.new_attendance_state == "left"
    
    def test_create_event_with_unknown_identity(self):
        """Test creating event with UNKNOWN identity."""
        event = ImmediateEvent(
            event_id="IEV-test789",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.UNKNOWN,
            identity_candidate=None,
            identity_confidence=0.0,
            identity_evidence_ref=None,
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-003",
            source_resolution_id="RES-003",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=3,
        )
        
        assert event.identity_certainty == IdentityCertainty.UNKNOWN
        assert event.is_unknown_identity is True
        assert event.identity_candidate is None
        assert event.identity_confidence == 0.0
    
    def test_create_event_with_ambiguous_identity(self):
        """Test creating event with AMBIGUOUS identity."""
        event = ImmediateEvent(
            event_id="IEV-test999",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.AMBIGUOUS,
            identity_candidate="HS008",
            identity_confidence=0.612,
            identity_evidence_ref="GO-008",
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A19",
            source_raw_event_id="RIE-004",
            source_resolution_id="RES-004",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=4,
        )
        
        assert event.identity_certainty == IdentityCertainty.AMBIGUOUS
        assert event.is_ambiguous_identity is True
        assert event.identity_confidence == 0.612
    
    def test_create_historical_event(self):
        """Test creating a HISTORICAL delivery status event."""
        event = ImmediateEvent(
            event_id="IEV-hist001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            source_attendance_record_id="ATT-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.HISTORICAL,
            delivery_sequence=5,
        )
        
        assert event.delivery_status == EventDeliveryStatus.HISTORICAL
    
    def test_validation_requires_event_id(self):
        """Test that event_id is required."""
        with pytest.raises(ValueError, match="event_id is required"):
            ImmediateEvent(
                event_id="",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
            )
    
    def test_validation_requires_camera_id(self):
        """Test that camera_id is required."""
        with pytest.raises(ValueError, match="camera_id is required"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
            )
    
    def test_validation_requires_local_track_id(self):
        """Test that local_track_id is required."""
        with pytest.raises(ValueError, match="local_track_id is required"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
            )
    
    def test_validation_requires_source_raw_event_id(self):
        """Test that source_raw_event_id is required."""
        with pytest.raises(ValueError, match="source_raw_event_id is required"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="",
                source_resolution_id="RES-001",
            )
    
    def test_validation_requires_source_resolution_id(self):
        """Test that source_resolution_id is required."""
        with pytest.raises(ValueError, match="source_resolution_id is required"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="",
            )
    
    def test_validation_invalid_direction(self):
        """Test that invalid direction raises error."""
        with pytest.raises(ValueError, match="direction must be IN or OUT"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction="invalid",  # type: ignore
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
            )
    
    def test_validation_negative_timestamp(self):
        """Test that negative timestamp raises error."""
        with pytest.raises(ValueError, match="event_timestamp must be >= 0"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
                event_timestamp=-1.0,
            )
    
    def test_validation_invalid_schema_version(self):
        """Test that invalid schema version raises error."""
        with pytest.raises(ValueError, match="Unsupported event_schema_version"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
                event_schema_version="2.0",
            )
    
    def test_validation_invalid_identity_certainty(self):
        """Test that invalid identity certainty raises error."""
        with pytest.raises(ValueError, match="Invalid identity_certainty"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
                identity_certainty="invalid",  # type: ignore
            )
    
    def test_validation_invalid_delivery_status(self):
        """Test that invalid delivery status raises error."""
        with pytest.raises(ValueError, match="Invalid delivery_status"):
            ImmediateEvent(
                event_id="IEV-test",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                camera_id="CAM1",
                local_track_id="A17",
                source_raw_event_id="RIE-001",
                source_resolution_id="RES-001",
                delivery_status="invalid",  # type: ignore
            )


class TestImmediateEventSerialization:
    """Tests for ImmediateEvent serialization/deserialization."""
    
    def create_sample_event(self) -> ImmediateEvent:
        """Create a sample event for testing."""
        return ImmediateEvent(
            event_id="IEV-serial001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            source_crossing_event_id="CE-001",
            source_attendance_decision_id="DEC-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            attendance_policy_id="policy_default",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown",
            new_attendance_state="present",
            decision_reason="within_entry_window",
            timetable_id="timetable_2024",
            timetable_version="1.0",
            session_id="morning",
            day="monday",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
            trajectory_points=[{"x": 100, "y": 200, "t": 1700000000.0}],
            config_snapshot={"key": "value"},
        )
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        event = self.create_sample_event()
        data = event.to_dict()
        
        assert data["event_id"] == "IEV-serial001"
        assert data["event_type"] == "attendance_in"
        assert data["direction"] == "in"
        assert data["identity_certainty"] == "known"
        assert data["identity_candidate"] == "HS001"
        assert data["identity_confidence"] == 0.987
        assert data["camera_id"] == "CAM1"
        assert data["local_track_id"] == "A17"
        assert data["delivery_status"] == "new"
        assert data["delivery_sequence"] == 1
        assert data["trajectory_points"] == [{"x": 100, "y": 200, "t": 1700000000.0}]
        assert data["config_snapshot"] == {"key": "value"}
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        event = self.create_sample_event()
        data = event.to_dict()
        restored = ImmediateEvent.from_dict(data)
        
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type
        assert restored.direction == event.direction
        assert restored.identity_certainty == event.identity_certainty
        assert restored.identity_candidate == event.identity_candidate
        assert restored.identity_confidence == event.identity_confidence
        assert restored.camera_id == event.camera_id
        assert restored.local_track_id == event.local_track_id
        assert restored.delivery_status == event.delivery_status
        assert restored.delivery_sequence == event.delivery_sequence
        assert restored.trajectory_points == event.trajectory_points
        assert restored.config_snapshot == event.config_snapshot
    
    def test_to_json(self):
        """Test serialization to JSON string."""
        event = self.create_sample_event()
        json_str = event.to_json()
        
        assert isinstance(json_str, str)
        assert "IEV-serial001" in json_str
        assert "attendance_in" in json_str
        assert "HS001" in json_str
    
    def test_from_json(self):
        """Test deserialization from JSON string."""
        event = self.create_sample_event()
        json_str = event.to_json()
        restored = ImmediateEvent.from_json(json_str)
        
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type
        assert restored.direction == event.direction
        assert restored.identity_certainty == event.identity_certainty
    
    def test_round_trip_dict(self):
        """Test round-trip: object -> dict -> object."""
        event = self.create_sample_event()
        data = event.to_dict()
        restored = ImmediateEvent.from_dict(data)
        data2 = restored.to_dict()
        
        assert data == data2
    
    def test_round_trip_json(self):
        """Test round-trip: object -> json -> object."""
        event = self.create_sample_event()
        json_str = event.to_json()
        restored = ImmediateEvent.from_json(json_str)
        json_str2 = restored.to_json()
        
        assert json_str == json_str2


class TestDeterministicEventId:
    """Tests for deterministic event ID generation."""
    
    def test_same_inputs_produce_same_id(self):
        """Test that same inputs produce the same event ID."""
        id1 = generate_immediate_event_id(
            source_resolution_id="RES-001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
        )
        id2 = generate_immediate_event_id(
            source_resolution_id="RES-001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
        )
        
        assert id1 == id2
        assert id1.startswith("IEV-")
    
    def test_different_resolution_id_produces_different_id(self):
        """Test that different resolution IDs produce different event IDs."""
        id1 = generate_immediate_event_id(
            source_resolution_id="RES-001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
        )
        id2 = generate_immediate_event_id(
            source_resolution_id="RES-002",
            event_type=ImmediateEventType.ATTENDANCE_IN,
        )
        
        assert id1 != id2
    
    def test_different_event_type_produces_different_id(self):
        """Test that different event types produce different event IDs."""
        id1 = generate_immediate_event_id(
            source_resolution_id="RES-001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
        )
        id2 = generate_immediate_event_id(
            source_resolution_id="RES-001",
            event_type=ImmediateEventType.ATTENDANCE_OUT,
        )
        
        assert id1 != id2
    
    def test_deterministic_across_calls(self):
        """Test that IDs are deterministic across multiple calls."""
        ids = []
        for _ in range(10):
            id_val = generate_immediate_event_id(
                source_resolution_id="RES-STABLE",
                event_type=ImmediateEventType.RESOLUTION_IN,
            )
            ids.append(id_val)
        
        # All should be identical
        assert len(set(ids)) == 1


class TestValidateImmediateEvent:
    """Tests for validate_immediate_event function."""
    
    def test_valid_event_passes(self):
        """Test that a valid event passes validation."""
        event = ImmediateEvent(
            event_id="IEV-valid",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
        )
        
        error = validate_immediate_event(event)
        assert error is None
    
    def test_missing_event_id_fails(self):
        """Test that missing event_id fails validation."""
        # Create a mock object with the required attributes
        class MockEvent:
            def __init__(self):
                self.event_id = ""
                self.event_type = ImmediateEventType.ATTENDANCE_IN
                self.direction = ImmediateEventDirection.IN
                self.camera_id = "CAM1"
                self.local_track_id = "A17"
                self.source_raw_event_id = "RIE-001"
                self.source_resolution_id = "RES-001"
                self.identity_certainty = IdentityCertainty.UNKNOWN
                self.identity_candidate = None
                self.identity_confidence = 0.0
                self.identity_evidence_ref = None
                self.event_timestamp = 1700000000.0
                self.event_frame_index = -1
                self.global_observation_id = None
                self.source_crossing_event_id = None
                self.source_attendance_decision_id = None
                self.source_attendance_record_id = None
                self.geometry_version = 0
                self.geometry_config_hash = ""
                self.resolver_version = "1.0"
                self.resolver_config_hash = ""
                self.attendance_policy_id = None
                self.attendance_policy_version = None
                self.previous_attendance_state = None
                self.new_attendance_state = None
                self.decision_reason = None
                self.timetable_id = None
                self.timetable_version = None
                self.session_id = None
                self.day = None
                self.delivery_status = EventDeliveryStatus.NEW
                self.delivery_timestamp = "2024-01-01T00:00:00Z"
                self.delivery_sequence = 0
                self.trajectory_points = []
                self.config_snapshot = {}
                self.event_schema_version = "1.0"
                self.created_at = "2024-01-01T00:00:00Z"
        
        invalid_event = MockEvent()
        error = validate_immediate_event(invalid_event)
        assert error == "event_id is required"
    
    def test_missing_camera_id_fails(self):
        """Test that missing camera_id fails validation."""
        class MockEvent:
            def __init__(self):
                self.event_id = "IEV-valid"
                self.event_type = ImmediateEventType.ATTENDANCE_IN
                self.direction = ImmediateEventDirection.IN
                self.camera_id = ""
                self.local_track_id = "A17"
                self.source_raw_event_id = "RIE-001"
                self.source_resolution_id = "RES-001"
                self.identity_certainty = IdentityCertainty.UNKNOWN
                self.identity_candidate = None
                self.identity_confidence = 0.0
                self.identity_evidence_ref = None
                self.event_timestamp = 1700000000.0
                self.event_frame_index = -1
                self.global_observation_id = None
                self.source_crossing_event_id = None
                self.source_attendance_decision_id = None
                self.source_attendance_record_id = None
                self.geometry_version = 0
                self.geometry_config_hash = ""
                self.resolver_version = "1.0"
                self.resolver_config_hash = ""
                self.attendance_policy_id = None
                self.attendance_policy_version = None
                self.previous_attendance_state = None
                self.new_attendance_state = None
                self.decision_reason = None
                self.timetable_id = None
                self.timetable_version = None
                self.session_id = None
                self.day = None
                self.delivery_status = EventDeliveryStatus.NEW
                self.delivery_timestamp = "2024-01-01T00:00:00Z"
                self.delivery_sequence = 0
                self.trajectory_points = []
                self.config_snapshot = {}
                self.event_schema_version = "1.0"
                self.created_at = "2024-01-01T00:00:00Z"
        
        invalid_event = MockEvent()
        error = validate_immediate_event(invalid_event)
        assert error == "camera_id is required"
    
    def test_negative_timestamp_fails(self):
        """Test that negative timestamp fails validation."""
        class MockEvent:
            def __init__(self):
                self.event_id = "IEV-valid"
                self.event_type = ImmediateEventType.ATTENDANCE_IN
                self.direction = ImmediateEventDirection.IN
                self.camera_id = "CAM1"
                self.local_track_id = "A17"
                self.source_raw_event_id = "RIE-001"
                self.source_resolution_id = "RES-001"
                self.identity_certainty = IdentityCertainty.UNKNOWN
                self.identity_candidate = None
                self.identity_confidence = 0.0
                self.identity_evidence_ref = None
                self.event_timestamp = -1.0
                self.event_frame_index = -1
                self.global_observation_id = None
                self.source_crossing_event_id = None
                self.source_attendance_decision_id = None
                self.source_attendance_record_id = None
                self.geometry_version = 0
                self.geometry_config_hash = ""
                self.resolver_version = "1.0"
                self.resolver_config_hash = ""
                self.attendance_policy_id = None
                self.attendance_policy_version = None
                self.previous_attendance_state = None
                self.new_attendance_state = None
                self.decision_reason = None
                self.timetable_id = None
                self.timetable_version = None
                self.session_id = None
                self.day = None
                self.delivery_status = EventDeliveryStatus.NEW
                self.delivery_timestamp = "2024-01-01T00:00:00Z"
                self.delivery_sequence = 0
                self.trajectory_points = []
                self.config_snapshot = {}
                self.event_schema_version = "1.0"
                self.created_at = "2024-01-01T00:00:00Z"
        
        invalid_event = MockEvent()
        error = validate_immediate_event(invalid_event)
        assert error == "event_timestamp must be >= 0"


class TestImmediateEventCreationResult:
    """Tests for ImmediateEventCreationResult."""
    
    def test_success_result(self):
        """Test creating a success result."""
        event = ImmediateEvent(
            event_id="IEV-test",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
        )
        
        result = ImmediateEventCreationResult.success_result(event)
        
        assert result.success is True
        assert result.event == event
        assert result.error is None
        assert result.rejection_reason is None
    
    def test_failure_result(self):
        """Test creating a failure result."""
        result = ImmediateEventCreationResult.failure_result(
            error="Validation failed",
            rejection_reason="invalid_field"
        )
        
        assert result.success is False
        assert result.event is None
        assert result.error == "Validation failed"
        assert result.rejection_reason == "invalid_field"


class TestEventTypeProperties:
    """Tests for event type property helpers."""
    
    def test_is_attendance_event(self):
        """Test is_attendance_event property."""
        event_in = ImmediateEvent(
            event_id="IEV-1",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
        )
        event_out = ImmediateEvent(
            event_id="IEV-2",
            event_type=ImmediateEventType.ATTENDANCE_OUT,
            direction=ImmediateEventDirection.OUT,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-002",
            source_resolution_id="RES-002",
        )
        event_res = ImmediateEvent(
            event_id="IEV-3",
            event_type=ImmediateEventType.RESOLUTION_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-003",
            source_resolution_id="RES-003",
        )
        event_raw = ImmediateEvent(
            event_id="IEV-4",
            event_type=ImmediateEventType.RAW_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-004",
            source_resolution_id="RES-004",
        )
        
        assert event_in.is_attendance_event is True
        assert event_out.is_attendance_event is True
        assert event_res.is_attendance_event is False
        assert event_raw.is_attendance_event is False
    
    def test_is_resolution_event(self):
        """Test is_resolution_event property."""
        event_res_in = ImmediateEvent(
            event_id="IEV-1",
            event_type=ImmediateEventType.RESOLUTION_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
        )
        event_res_out = ImmediateEvent(
            event_id="IEV-2",
            event_type=ImmediateEventType.RESOLUTION_OUT,
            direction=ImmediateEventDirection.OUT,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-002",
            source_resolution_id="RES-002",
        )
        event_att = ImmediateEvent(
            event_id="IEV-3",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-003",
            source_resolution_id="RES-003",
        )
        
        assert event_res_in.is_resolution_event is True
        assert event_res_out.is_resolution_event is True
        assert event_att.is_resolution_event is False
    
    def test_is_raw_event(self):
        """Test is_raw_event property."""
        event_raw_in = ImmediateEvent(
            event_id="IEV-1",
            event_type=ImmediateEventType.RAW_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
        )
        event_raw_out = ImmediateEvent(
            event_id="IEV-2",
            event_type=ImmediateEventType.RAW_OUT,
            direction=ImmediateEventDirection.OUT,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-002",
            source_resolution_id="RES-002",
        )
        event_att = ImmediateEvent(
            event_id="IEV-3",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            camera_id="CAM1",
            local_track_id="A17",
            source_raw_event_id="RIE-003",
            source_resolution_id="RES-003",
        )
        
        assert event_raw_in.is_raw_event is True
        assert event_raw_out.is_raw_event is True
        assert event_att.is_raw_event is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])