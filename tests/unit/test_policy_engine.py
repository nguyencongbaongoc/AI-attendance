"""
Phase 37B — Unit Tests for Attendance Policy Engine.
"""

from __future__ import annotations

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import Mock, MagicMock, patch

from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    SessionType,
    AttendanceState,
)
from app.attendance.calendar import CalendarEngine, CalendarConfig, DayType
from app.attendance.daily_resolver import (
    DailyExpectedResolver,
    ExpectedStudent,
    ExpectedSession,
    ExpectedStatus,
)
from app.attendance.engine import AttendanceEngine, AttendanceDecisionContext
from app.attendance.policy import AttendancePolicy
from app.attendance.policy_engine.engine import (
    AttendancePolicyEngine,
    PolicyEngineConfig,
    create_attendance_policy_engine,
)
from app.attendance.policy_engine.contract import (
    PolicyEvent,
    PolicyType,
    PolicyEventState,
    generate_policy_event_id,
    validate_policy_event,
)
from app.in_out.resolver_contract import (
    ResolvedTransition,
    DerivedState,
    TransitionType,
    ResolutionStatus,
)


class TestPolicyEngineConfig:
    """Tests for PolicyEngineConfig."""
    
    def test_default_config(self):
        config = PolicyEngineConfig()
        assert config.morning_absence_check_seconds == 27000  # 07:30
        assert config.exit_threshold_seconds == 1800  # 30 minutes
        assert config.default_departure_check_seconds == 63000  # 17:30
        assert config.timezone == "Asia/Bangkok"
    
    def test_custom_config(self):
        config = PolicyEngineConfig(
            morning_absence_check_seconds=28800,  # 08:00
            exit_threshold_seconds=900,  # 15 minutes
            default_departure_check_seconds=54000,  # 15:00
            timezone="UTC",
        )
        assert config.morning_absence_check_seconds == 28800
        assert config.exit_threshold_seconds == 900
        assert config.default_departure_check_seconds == 54000
        assert config.timezone == "UTC"
    
    def test_invalid_morning_check(self):
        with pytest.raises(ValueError):
            PolicyEngineConfig(morning_absence_check_seconds=-1)
        with pytest.raises(ValueError):
            PolicyEngineConfig(morning_absence_check_seconds=86400)
    
    def test_invalid_exit_threshold(self):
        with pytest.raises(ValueError):
            PolicyEngineConfig(exit_threshold_seconds=-1)
    
    def test_invalid_departure_check(self):
        with pytest.raises(ValueError):
            PolicyEngineConfig(default_departure_check_seconds=-1)
        with pytest.raises(ValueError):
            PolicyEngineConfig(default_departure_check_seconds=86400)
    
    def test_invalid_timezone(self):
        with pytest.raises(ValueError):
            PolicyEngineConfig(timezone="Invalid/Timezone")


class TestPolicyEventContract:
    """Tests for PolicyEvent contract."""
    
    def test_create_policy_event(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1700000000.0,
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
            evidence={"check_time": "07:30:00", "status": "ABSENT"},
        )
        assert event.event_id == "PEV-test123"
        assert event.student_id == "HS001"
        assert event.policy_type == PolicyType.MORNING_ABSENCE
        assert event.is_notification_type is True
    
    def test_short_exit_not_notification_type(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.SHORT_EXIT,
            occurred_at=1700000000.0,
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
        )
        assert event.is_notification_type is False
    
    def test_idempotency_key_morning_absence(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1700000000.0,  # 2023-11-15
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
        )
        key = event.idempotency_key
        assert key == "2023-11-15:HS001:morning_absence"
    
    def test_idempotency_key_long_exit_with_out_time(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.LONG_EXIT,
            occurred_at=1700000000.0,
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
            evidence={"out_time": "14:00:00"},
        )
        key = event.idempotency_key
        assert key == "2023-11-15:HS001:long_exit:14:00:00"
    
    def test_serialization_roundtrip(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1700000000.0,
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
            evidence={"check_time": "07:30:00"},
            state=PolicyEventState.NEW,
        )
        
        # Serialize
        data = event.to_dict()
        json_str = event.to_json()
        
        # Deserialize
        event2 = PolicyEvent.from_dict(data)
        event3 = PolicyEvent.from_json(json_str)
        
        assert event2.event_id == event.event_id
        assert event2.student_id == event.student_id
        assert event2.policy_type == event.policy_type
        assert event3.event_id == event.event_id
    
    def test_generate_policy_event_id(self):
        id1 = generate_policy_event_id("HS001", PolicyType.MORNING_ABSENCE, 1700000000.0, "DEC-test")
        id2 = generate_policy_event_id("HS001", PolicyType.MORNING_ABSENCE, 1700000000.0, "DEC-test")
        id3 = generate_policy_event_id("HS002", PolicyType.MORNING_ABSENCE, 1700000000.0, "DEC-test")
        
        assert id1 == id2  # Deterministic
        assert id1 != id3  # Different student
        assert id1.startswith("PEV-")
    
    def test_validate_policy_event(self):
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1700000000.0,
            effective_at=1700000000.0,
            source_attendance_event_id="DEC-test456",
        )
        assert validate_policy_event(event) is None
        
        # validate_policy_event checks the same things as __post_init__
        # So we just verify it returns None for valid events
        # and would return error for invalid ones (but those fail in __post_init__)


class TestAttendancePolicyEngine:
    """Tests for AttendancePolicyEngine."""
    
    @pytest.fixture
    def setup_engine(self):
        """Create a test policy engine with mocked dependencies."""
        # Create timetable
        timetable = Timetable(timetable_id="test-timetable")
        entry = TimetableEntry(
            entry_id="entry1",
            person_id="HS001",
            person_name="Test Student",
            day=SessionDay.MONDAY,
            session_type=SessionType.FULL_DAY,
            class_name="Math 101",
            session_id="MATH101_MON",
            entry_time=25200,  # 07:00 (before 07:30 check)
            exit_time=54000,   # 15:00
            entry_window_start=27000,  # 07:30
            entry_window_end=29700,    # 08:15
            late_tolerance=600,        # 10 minutes
            exit_window_start=53100,   # 14:45
            exit_window_end=55800,     # 15:30
        )
        timetable.entries.append(entry)
        
        # Create calendar engine
        calendar_config = CalendarConfig(
            timezone="Asia/Bangkok",
            default_school_days=(0, 1, 2, 3, 4),  # Mon-Fri
        )
        calendar_engine = CalendarEngine(calendar_config)
        
        # Create daily resolver
        daily_resolver = DailyExpectedResolver(
            timetable=timetable,
            calendar_engine=calendar_engine,
            enrollment_person_ids=["HS001"],
        )
        
        # Create attendance policy
        policy = AttendancePolicy(policy_id="test-policy")
        
        # Create attendance engine
        attendance_engine = AttendanceEngine(policy)
        
        # Mock repository
        attendance_engine.repository = Mock()
        
        # Create policy engine
        config = PolicyEngineConfig(
            morning_absence_check_seconds=27000,  # 07:30
            exit_threshold_seconds=1800,  # 30 minutes
            default_departure_check_seconds=63000,  # 17:30
        )
        
        engine = AttendancePolicyEngine(
            timetable=timetable,
            calendar_engine=calendar_engine,
            daily_resolver=daily_resolver,
            attendance_engine=attendance_engine,
            config=config,
        )
        
        return engine, timetable, calendar_engine, daily_resolver
    
    def test_morning_absence_student_not_expected(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Student not in enrollment
        events = engine.evaluate_morning_absence(date(2026, 1, 5), "HS999")
        assert len(events) == 0
    
    def test_morning_absence_student_expected_present(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository to return a valid IN record BEFORE check time (07:30 = 27000)
        # Need to use Unix timestamp, not seconds from midnight
        # 07:13:20 on 2026-01-05 in Asia/Bangkok = 1767572000.0
        mock_record = Mock()
        mock_record.identity_candidate = "HS001"
        mock_record.direction = "in"
        mock_record.event_timestamp = 1767572000.0  # 07:13:20 (before 07:30)
        mock_record.new_attendance_state = "present"
        
        engine.attendance_engine.repository.query_by_time_range.return_value = [mock_record]
        
        events = engine.evaluate_morning_absence(date(2026, 1, 5), "HS001")
        assert len(events) == 0  # No absence event
    
    def test_morning_absence_student_expected_absent(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository to return no IN records
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        events = engine.evaluate_morning_absence(date(2026, 1, 5), "HS001")
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.MORNING_ABSENCE
        assert events[0].student_id == "HS001"
        assert events[0].evidence["status"] == "ABSENT"
    
    def test_morning_absence_later_start_student(self, setup_engine):
        engine, timetable, _, _ = setup_engine
        
        # Add a later session for the student
        late_entry = TimetableEntry(
            entry_id="entry2",
            person_id="HS002",
            person_name="Late Student",
            day=SessionDay.MONDAY,
            session_type=SessionType.FULL_DAY,
            class_name="Physics 101",
            session_id="PHYS101_MON",
            entry_time=32400,  # 09:00
            exit_time=57600,   # 16:00
            entry_window_start=30600,  # 08:30
            entry_window_end=33300,    # 09:15
            late_tolerance=600,
            exit_window_start=56700,   # 15:45
            exit_window_end=59400,     # 16:30
        )
        timetable.entries.append(late_entry)
        
        # Mock repository
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        # Check at 07:30 - student starts at 09:00, so should not be marked absent
        events = engine.evaluate_morning_absence(date(2026, 1, 5), "HS002")
        assert len(events) == 0
    
    def test_exit_policy_creates_session(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Create mock OUT transition (ResolvedTransition)
        mock_transition = Mock(spec=ResolvedTransition)
        mock_transition.resolution_id = "RES-test123"
        mock_transition.source_timestamp = 43200  # 12:00
        mock_transition.direction = "out"
        
        events = engine.evaluate_exit_policy("HS001", mock_transition, date(2026, 1, 5))
        
        # Should not create event immediately, just start session
        assert len(events) == 0
        assert "HS001:2026-01-05" in engine._exit_sessions
    
    def test_in_after_exit_short_exit(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # First create exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 43200  # 12:00
        mock_out_transition.direction = "out"
        
        engine.evaluate_exit_policy("HS001", mock_out_transition, date(2026, 1, 5))
        
        # Now IN event within threshold (15 minutes)
        mock_in_transition = Mock(spec=ResolvedTransition)
        mock_in_transition.resolution_id = "RES-in123"
        mock_in_transition.source_timestamp = 44100  # 12:15 (15 minutes later)
        mock_in_transition.direction = "in"
        
        events = engine.evaluate_in_after_exit("HS001", mock_in_transition, date(2026, 1, 5))
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.SHORT_EXIT
        assert events[0].state == PolicyEventState.IGNORED
        assert events[0].evidence["duration_seconds"] == 900  # 15 minutes
    
    def test_in_after_exit_long_exit(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # First create exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 43200  # 12:00
        mock_out_transition.direction = "out"
        
        engine.evaluate_exit_policy("HS001", mock_out_transition, date(2026, 1, 5))
        
        # Now IN event after threshold (45 minutes)
        mock_in_transition = Mock(spec=ResolvedTransition)
        mock_in_transition.resolution_id = "RES-in123"
        mock_in_transition.source_timestamp = 45900  # 12:45 (45 minutes later)
        mock_in_transition.direction = "in"
        
        events = engine.evaluate_in_after_exit("HS001", mock_in_transition, date(2026, 1, 5))
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.LONG_EXIT
        assert events[0].evidence["duration_seconds"] == 2700  # 45 minutes
    
    def test_check_exit_sessions_threshold_exceeded(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Create exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 43200  # 12:00
        mock_out_transition.direction = "out"
        
        engine.evaluate_exit_policy("HS001", mock_out_transition, date(2026, 1, 5))
        
        # Check at 12:31 (31 minutes later, threshold is 30 minutes)
        check_time = datetime(2026, 1, 5, 12, 31, 0).timestamp()
        
        events = engine.check_exit_sessions(check_time)
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.LONG_EXIT
        assert events[0].evidence["status"] == "THRESHOLD_EXCEEDED_NO_RETURN"
    
    def test_missing_checkout_no_out_record(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository to return no OUT records
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        events = engine.evaluate_missing_checkout(date(2026, 1, 5), "HS001")
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.MISSING_CHECKOUT
        assert events[0].evidence["status"] == "MISSING_CHECKOUT"
    
    def test_missing_checkout_has_out_record(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository to return a valid OUT record
        mock_record = Mock()
        mock_record.identity_candidate = "HS001"
        mock_record.direction = "out"
        mock_record.event_timestamp = 54000  # 15:00
        mock_record.new_attendance_state = "left"
        
        engine.attendance_engine.repository.query_by_time_range.return_value = [mock_record]
        
        events = engine.evaluate_missing_checkout(date(2026, 1, 5), "HS001")
        
        assert len(events) == 0  # No missing checkout
    
    def test_missing_checkout_active_exit_session(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Create active exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 54000  # 15:00
        mock_out_transition.direction = "out"
        
        engine.evaluate_exit_policy("HS001", mock_out_transition, date(2026, 1, 5))
        
        # Check missing checkout - should not create event because exit session exists
        # Need to mock the repository to return empty for the missing checkout check
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        events = engine.evaluate_missing_checkout(date(2026, 1, 5), "HS001")
        
        assert len(events) == 0
    
    def test_deduplication(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        # First evaluation
        events1 = engine.evaluate_morning_absence(date(2026, 1, 5), "HS001")
        assert len(events1) == 1
        
        # Second evaluation - should be deduplicated
        events2 = engine.evaluate_morning_absence(date(2026, 1, 5), "HS001")
        assert len(events2) == 1
        assert events2[0].state == PolicyEventState.DEDUPLICATED
    
    def test_evaluate_all_policies(self, setup_engine):
        engine, _, _, _ = setup_engine
        
        # Mock repository
        engine.attendance_engine.repository.query_by_time_range.return_value = []
        
        # Set time to after all check times
        current_time = datetime(2026, 1, 5, 18, 0, 0).timestamp()
        
        events = engine.evaluate_all_policies(date(2026, 1, 5), current_time)
        
        # Should have morning absence and missing checkout for HS001
        assert len(events) >= 2
        types = {e.policy_type for e in events}
        assert PolicyType.MORNING_ABSENCE in types
        assert PolicyType.MISSING_CHECKOUT in types


class TestPolicyEngineFactory:
    """Tests for factory functions."""
    
    def test_create_attendance_policy_engine(self):
        timetable = Timetable(timetable_id="test")
        calendar_engine = CalendarEngine()
        daily_resolver = DailyExpectedResolver(timetable, calendar_engine)
        policy = AttendancePolicy(policy_id="test")
        attendance_engine = AttendanceEngine(policy)
        attendance_engine.repository = Mock()
        
        engine = create_attendance_policy_engine(
            timetable=timetable,
            calendar_engine=calendar_engine,
            daily_resolver=daily_resolver,
            attendance_engine=attendance_engine,
        )
        
        assert isinstance(engine, AttendancePolicyEngine)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])