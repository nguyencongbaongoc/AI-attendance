"""
Unit tests for Phase 26 Attendance Policy.
"""

import pytest
from datetime import datetime
from app.attendance.policy import (
    AttendancePolicy,
    AttendanceDecision,
    DecisionReason,
    IdentityHandlingPolicy,
    DuplicateDecisionPolicy,
    SessionFinalizationPolicy,
    generate_decision_id,
    validate_attendance_decision,
)


class TestAttendancePolicy:
    """Test AttendancePolicy class."""
    
    def test_create_policy(self):
        """Test creating a basic attendance policy."""
        policy = AttendancePolicy(
            policy_id="test-policy-1",
            policy_version="1.0",
            unknown_identity_policy=IdentityHandlingPolicy.UNRESOLVED,
            duplicate_decision_policy=DuplicateDecisionPolicy.IGNORE,
            session_finalization_policy=SessionFinalizationPolicy.EVENT_BASED,
        )
        
        assert policy.policy_id == "test-policy-1"
        assert policy.policy_version == "1.0"
        assert policy.unknown_identity_policy == IdentityHandlingPolicy.UNRESOLVED
        assert policy.duplicate_decision_policy == DuplicateDecisionPolicy.IGNORE
        assert policy.session_finalization_policy == SessionFinalizationPolicy.EVENT_BASED
    
    def test_policy_defaults(self):
        """Test that policy has correct defaults."""
        policy = AttendancePolicy(policy_id="test-policy-2")
        
        assert policy.default_entry_window_seconds == 300
        assert policy.default_late_tolerance_seconds == 600
        assert policy.default_exit_window_seconds == 300
        assert policy.geometry_version == 0
        assert policy.geometry_config_hash == ""
    
    def test_policy_validation(self):
        """Test policy validation."""
        # Valid policy
        policy = AttendancePolicy(
            policy_id="test-policy-3",
            default_entry_window_seconds=300,
            default_late_tolerance_seconds=600,
            default_exit_window_seconds=300,
        )
        assert policy is not None
        
        # Invalid policy (missing policy_id)
        with pytest.raises(ValueError, match="policy_id is required"):
            AttendancePolicy(policy_id="")
    
    def test_policy_serialization(self):
        """Test policy serialization/deserialization."""
        policy = AttendancePolicy(
            policy_id="test-policy-4",
            policy_version="1.0",
            unknown_identity_policy=IdentityHandlingPolicy.UNKNOWN_PERSON,
            duplicate_decision_policy=DuplicateDecisionPolicy.OVERRIDE,
            session_finalization_policy=SessionFinalizationPolicy.TIME_BASED,
            default_entry_window_seconds=600,
            default_late_tolerance_seconds=900,
            default_exit_window_seconds=600,
            geometry_version=1,
            geometry_config_hash="abc123",
        )
        
        # Serialize to dict
        policy_dict = policy.to_dict()
        assert policy_dict["policy_id"] == "test-policy-4"
        assert policy_dict["policy_version"] == "1.0"
        assert policy_dict["unknown_identity_policy"] == "unknown_person"
        assert policy_dict["duplicate_decision_policy"] == "override"
        assert policy_dict["session_finalization_policy"] == "time_based"
        assert policy_dict["default_entry_window_seconds"] == 600
        assert policy_dict["default_late_tolerance_seconds"] == 900
        assert policy_dict["default_exit_window_seconds"] == 600
        assert policy_dict["geometry_version"] == 1
        assert policy_dict["geometry_config_hash"] == "abc123"
        
        # Deserialize from dict
        policy_restored = AttendancePolicy.from_dict(policy_dict)
        assert policy_restored.policy_id == policy.policy_id
        assert policy_restored.policy_version == policy.policy_version
        assert policy_restored.unknown_identity_policy == policy.unknown_identity_policy
        assert policy_restored.duplicate_decision_policy == policy.duplicate_decision_policy
        assert policy_restored.session_finalization_policy == policy.session_finalization_policy
        assert policy_restored.default_entry_window_seconds == policy.default_entry_window_seconds
        assert policy_restored.default_late_tolerance_seconds == policy.default_late_tolerance_seconds
        assert policy_restored.default_exit_window_seconds == policy.default_exit_window_seconds
        assert policy_restored.geometry_version == policy.geometry_version
        assert policy_restored.geometry_config_hash == policy.geometry_config_hash
    
    def test_policy_json_roundtrip(self):
        """Test policy JSON serialization/deserialization."""
        policy = AttendancePolicy(
            policy_id="test-policy-5",
            unknown_identity_policy=IdentityHandlingPolicy.PENDING_REVIEW,
        )
        
        # Serialize to JSON
        policy_json = policy.to_json()
        assert isinstance(policy_json, str)
        
        # Deserialize from JSON
        policy_restored = AttendancePolicy.from_json(policy_json)
        assert policy_restored.policy_id == policy.policy_id
        assert policy_restored.unknown_identity_policy == policy.unknown_identity_policy


class TestAttendanceDecision:
    """Test AttendanceDecision class."""
    
    def test_create_decision(self):
        """Test creating a basic attendance decision."""
        decision = AttendanceDecision(
            decision_id="test-decision-1",
            identity_certainty="known",
            identity_candidate="person-123",
            identity_confidence=0.95,
            identity_evidence_ref="global-obs-1",
            direction="in",
            event_timestamp=36000,  # 10:00 AM
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="track-1",
            global_observation_id="global-obs-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
            source_crossing_event_id="cross-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
            resolver_version="1.0",
            resolver_config_hash="res-1",
            timetable_id="ttb-1",
            timetable_version="1.0",
            session_id="session-1",
            day="monday",
            previous_attendance_state="unknown",
            new_attendance_state="present",
            decision_reason="within_entry_window",
            attendance_policy_id="policy-1",
            attendance_policy_version="1.0",
        )
        
        assert decision.decision_id == "test-decision-1"
        assert decision.identity_certainty == "known"
        assert decision.identity_candidate == "person-123"
        assert decision.identity_confidence == 0.95
        assert decision.direction == "in"
        assert decision.event_timestamp == 36000
        assert decision.camera_id == "CAM1"
        assert decision.local_track_id == "track-1"
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "present"
        assert decision.decision_reason == "within_entry_window"
    
    def test_decision_properties(self):
        """Test decision properties."""
        decision = AttendanceDecision(
            decision_id="test-decision-2",
            direction="in",
            event_timestamp=36000,
            camera_id="CAM1",
            local_track_id="track-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
        )
        
        assert decision.is_in is True
        assert decision.is_out is False
        assert decision.is_known_identity is False
        assert decision.is_unknown_identity is True
        assert decision.is_ambiguous_identity is False
    
    def test_decision_validation(self):
        """Test decision validation."""
        # Valid decision
        decision = AttendanceDecision(
            decision_id="test-decision-3",
            direction="in",
            event_timestamp=36000,
            camera_id="CAM1",
            local_track_id="track-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
        )
        assert validate_attendance_decision(decision) is None
        
        # Invalid decision (missing decision_id) - validation happens in __post_init__
        with pytest.raises(ValueError, match="decision_id is required"):
            AttendanceDecision(
                decision_id="",
                direction="in",
                event_timestamp=36000,
                camera_id="CAM1",
                local_track_id="track-1",
                source_raw_event_id="raw-1",
                source_resolution_id="res-1",
            )
        
        # Invalid decision (invalid direction) - validation happens in __post_init__
        with pytest.raises(ValueError, match="direction must be 'in' or 'out', got invalid"):
            AttendanceDecision(
                decision_id="test-decision-4",
                direction="invalid",
                event_timestamp=36000,
                camera_id="CAM1",
                local_track_id="track-1",
                source_raw_event_id="raw-1",
                source_resolution_id="res-1",
            )
        
        # Invalid decision (invalid previous_attendance_state) - validation happens in __post_init__
        with pytest.raises(ValueError, match="Invalid previous_attendance_state: invalid_state"):
            AttendanceDecision(
                decision_id="test-decision-5",
                direction="in",
                event_timestamp=36000,
                camera_id="CAM1",
                local_track_id="track-1",
                source_raw_event_id="raw-1",
                source_resolution_id="res-1",
                previous_attendance_state="invalid_state",
            )
        
        # Invalid decision (invalid decision_reason) - validation happens in __post_init__
        with pytest.raises(ValueError, match="Invalid decision_reason: invalid_reason"):
            AttendanceDecision(
                decision_id="test-decision-6",
                direction="in",
                event_timestamp=36000,
                camera_id="CAM1",
                local_track_id="track-1",
                source_raw_event_id="raw-1",
                source_resolution_id="res-1",
                decision_reason="invalid_reason",
            )
    
    def test_decision_serialization(self):
        """Test decision serialization/deserialization."""
        decision = AttendanceDecision(
            decision_id="test-decision-7",
            identity_certainty="known",
            identity_candidate="person-123",
            identity_confidence=0.95,
            direction="in",
            event_timestamp=36000,
            camera_id="CAM1",
            local_track_id="track-1",
            global_observation_id="global-obs-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
            source_crossing_event_id="cross-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
            resolver_version="1.0",
            resolver_config_hash="res-1",
            timetable_id="ttb-1",
            timetable_version="1.0",
            session_id="session-1",
            day="monday",
            previous_attendance_state="unknown",
            new_attendance_state="present",
            decision_reason="within_entry_window",
            attendance_policy_id="policy-1",
            attendance_policy_version="1.0",
        )
        
        # Serialize to dict
        decision_dict = decision.to_dict()
        assert decision_dict["decision_id"] == "test-decision-7"
        assert decision_dict["identity_certainty"] == "known"
        assert decision_dict["identity_candidate"] == "person-123"
        assert decision_dict["identity_confidence"] == 0.95
        assert decision_dict["direction"] == "in"
        assert decision_dict["event_timestamp"] == 36000
        assert decision_dict["camera_id"] == "CAM1"
        assert decision_dict["local_track_id"] == "track-1"
        assert decision_dict["previous_attendance_state"] == "unknown"
        assert decision_dict["new_attendance_state"] == "present"
        assert decision_dict["decision_reason"] == "within_entry_window"
        
        # Deserialize from dict
        decision_restored = AttendanceDecision.from_dict(decision_dict)
        assert decision_restored.decision_id == decision.decision_id
        assert decision_restored.identity_certainty == decision.identity_certainty
        assert decision_restored.identity_candidate == decision.identity_candidate
        assert decision_restored.identity_confidence == decision.identity_confidence
        assert decision_restored.direction == decision.direction
        assert decision_restored.event_timestamp == decision.event_timestamp
        assert decision_restored.camera_id == decision.camera_id
        assert decision_restored.local_track_id == decision.local_track_id
        assert decision_restored.previous_attendance_state == decision.previous_attendance_state
        assert decision_restored.new_attendance_state == decision.new_attendance_state
        assert decision_restored.decision_reason == decision.decision_reason
    
    def test_decision_json_roundtrip(self):
        """Test decision JSON serialization/deserialization."""
        decision = AttendanceDecision(
            decision_id="test-decision-8",
            direction="out",
            event_timestamp=72000,  # 20:00 PM
            camera_id="CAM1",
            local_track_id="track-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
            new_attendance_state="left",
            decision_reason="exit_recorded",
        )
        
        # Serialize to JSON
        decision_json = decision.to_json()
        assert isinstance(decision_json, str)
        
        # Deserialize from JSON
        decision_restored = AttendanceDecision.from_json(decision_json)
        assert decision_restored.decision_id == decision.decision_id
        assert decision_restored.direction == decision.direction
        assert decision_restored.event_timestamp == decision.event_timestamp
        assert decision_restored.new_attendance_state == decision.new_attendance_state
        assert decision_restored.decision_reason == decision.decision_reason


class TestDecisionReason:
    """Test DecisionReason enum."""
    
    def test_decision_reason_values(self):
        """Test that all decision reasons are valid."""
        valid_reasons = [
            "within_entry_window",
            "late_within_tolerance",
            "exit_recorded",
            "unknown_identity",
            "ambiguous_identity",
            "outside_attendance_window",
            "session_finalized",
            "no_entry_event",
            "no_exit_event",
            "invalid_timetable",
            "invalid_policy",
            "duplicate_resolution",
        ]
        
        for reason in valid_reasons:
            assert reason in [r.value for r in DecisionReason]
    
    def test_decision_reason_enum(self):
        """Test DecisionReason enum access."""
        assert DecisionReason.WITHIN_ENTRY_WINDOW.value == "within_entry_window"
        assert DecisionReason.LATE_WITHIN_TOLERANCE.value == "late_within_tolerance"
        assert DecisionReason.EXIT_RECORDED.value == "exit_recorded"


class TestIdentityHandlingPolicy:
    """Test IdentityHandlingPolicy enum."""
    
    def test_identity_handling_policy_values(self):
        """Test that all identity handling policies are valid."""
        valid_policies = [
            "unresolved",
            "unknown_person",
            "pending_review",
        ]
        
        for policy in valid_policies:
            assert policy in [p.value for p in IdentityHandlingPolicy]


class TestDuplicateDecisionPolicy:
    """Test DuplicateDecisionPolicy enum."""
    
    def test_duplicate_decision_policy_values(self):
        """Test that all duplicate decision policies are valid."""
        valid_policies = [
            "ignore",
            "override",
            "warn",
        ]
        
        for policy in valid_policies:
            assert policy in [p.value for p in DuplicateDecisionPolicy]


class TestSessionFinalizationPolicy:
    """Test SessionFinalizationPolicy enum."""
    
    def test_session_finalization_policy_values(self):
        """Test that all session finalization policies are valid."""
        valid_policies = [
            "event_based",
            "time_based",
            "manual",
        ]
        
        for policy in valid_policies:
            assert policy in [p.value for p in SessionFinalizationPolicy]


class TestGenerateDecisionId:
    """Test decision ID generation."""
    
    def test_generate_decision_id(self):
        """Test deterministic decision ID generation."""
        resolution_id = "res-123"
        schema_version = "1.0"
        
        decision_id_1 = generate_decision_id(resolution_id, schema_version)
        decision_id_2 = generate_decision_id(resolution_id, schema_version)
        
        assert decision_id_1 == decision_id_2
        assert decision_id_1.startswith("DEC-")
        assert "res-123" in decision_id_1
        assert "v1.0" in decision_id_1
    
    def test_generate_decision_id_different_resolution(self):
        """Test that different resolution IDs produce different decision IDs."""
        decision_id_1 = generate_decision_id("res-123", "1.0")
        decision_id_2 = generate_decision_id("res-456", "1.0")
        
        assert decision_id_1 != decision_id_2