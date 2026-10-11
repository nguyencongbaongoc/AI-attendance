"""
Phase 37B — Integration Tests for Production Attendance Policy + Telegram + Excel.

Tests the complete pipeline:
    Timetable + DailyExpectedResolver + Attendance State + Raw/Resolved IN/OUT evidence
        ↓
    Attendance Policy Engine
        ↓
    Canonical Policy Event
        ↓
    Notification Queue
        ↓
    Telegram Worker (mocked)
        ↓
    Parent Registry
        ↓
    telegram_chat_id
"""

from __future__ import annotations

import pytest
from datetime import datetime, date, time, timedelta
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    SessionType,
    AttendanceState,
)
from app.attendance.calendar import CalendarEngine, CalendarConfig
from app.attendance.daily_resolver import DailyExpectedResolver
from app.attendance.engine import AttendanceEngine, AttendanceDecisionContext
from app.attendance.policy import AttendancePolicy
from app.attendance.policy_engine.engine import (
    AttendancePolicyEngine,
    PolicyEngineConfig,
)
from app.attendance.policy_engine.contract import (
    PolicyEvent,
    PolicyType,
    PolicyEventState,
)
from app.attendance.policy_engine.parent_registry import (
    ParentRegistry,
    NotificationPreference,
)
from app.attendance.policy_engine.telegram_bot import (
    TelegramBot,
    NotificationQueue,
    NotificationRecord,
    TelegramSendStatus,
)
from app.attendance.policy_engine.templates import create_notification_message
from app.in_out.resolver_contract import (
    ResolvedTransition,
    DerivedState,
    TransitionType,
    ResolutionStatus,
)


class TestPhase37BIntegration:
    """Integration tests for Phase 37B complete pipeline."""
    
    @pytest.fixture
    def setup_full_stack(self, tmp_path):
        """Create complete Phase 37B stack with temporary databases."""
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
            entry_time=25200,  # 07:00
            exit_time=54000,   # 15:00
            entry_window_start=27000,  # 07:30
            entry_window_end=29700,    # 08:15
            late_tolerance=600,
            exit_window_start=53100,   # 14:45
            exit_window_end=55800,     # 15:30
        )
        timetable.entries.append(entry)
        
        # Add second student for multi-student tests
        entry2 = TimetableEntry(
            entry_id="entry2",
            person_id="HS002",
            person_name="Another Student",
            day=SessionDay.MONDAY,
            session_type=SessionType.FULL_DAY,
            class_name="Physics 101",
            session_id="PHYS101_MON",
            entry_time=28800,  # 08:00
            exit_time=57600,   # 16:00
            entry_window_start=30600,  # 08:30
            entry_window_end=33300,    # 09:15
            late_tolerance=600,
            exit_window_start=56700,   # 15:45
            exit_window_end=59400,     # 16:30
        )
        timetable.entries.append(entry2)
        
        # Create calendar engine
        calendar_config = CalendarConfig(
            timezone="Asia/Bangkok",
            default_school_days=(0, 1, 2, 3, 4),
        )
        calendar_engine = CalendarEngine(calendar_config)
        
        # Create daily resolver
        daily_resolver = DailyExpectedResolver(
            timetable=timetable,
            calendar_engine=calendar_engine,
            enrollment_person_ids=["HS001", "HS002"],
        )
        
        # Create attendance policy
        policy = AttendancePolicy(policy_id="test-policy")
        
        # Create attendance engine
        attendance_engine = AttendanceEngine(policy)
        attendance_engine.repository = Mock()
        
        # Create policy engine
        config = PolicyEngineConfig(
            morning_absence_check_seconds=27000,  # 07:30
            exit_threshold_seconds=1800,  # 30 minutes
            default_departure_check_seconds=63000,  # 17:30
        )
        
        policy_engine = AttendancePolicyEngine(
            timetable=timetable,
            calendar_engine=calendar_engine,
            daily_resolver=daily_resolver,
            attendance_engine=attendance_engine,
            config=config,
        )
        
        # Create parent registry with temp database
        parent_db = tmp_path / "parent_registry.db"
        parent_registry = ParentRegistry(str(parent_db))
        
        # Create parents
        parent1 = parent_registry.create_parent(
            parent_name="Parent of HS001",
            telegram_chat_id="111111111",
            notification_preferences=NotificationPreference.ALL,
        )
        parent2 = parent_registry.create_parent(
            parent_name="Parent of HS002",
            telegram_chat_id="222222222",
            notification_preferences=NotificationPreference.MORNING_ABSENCE_ONLY,
        )
        
        # Link students to parents
        parent_registry.link_student_parent("HS001", parent1.parent_id, is_primary=True)
        parent_registry.link_student_parent("HS002", parent2.parent_id, is_primary=True)
        
        # Create Telegram bot (mocked)
        telegram_bot = TelegramBot(bot_token="test_token")
        telegram_bot.send_message = AsyncMock(return_value=(True, None))
        
        # Create notification queue
        queue_db = tmp_path / "notification_queue.db"
        notification_queue = NotificationQueue(
            parent_registry=parent_registry,
            telegram_bot=telegram_bot,
            db_path=str(queue_db),
        )
        
        return {
            "timetable": timetable,
            "calendar_engine": calendar_engine,
            "daily_resolver": daily_resolver,
            "attendance_engine": attendance_engine,
            "policy_engine": policy_engine,
            "parent_registry": parent_registry,
            "telegram_bot": telegram_bot,
            "notification_queue": notification_queue,
            "parent1": parent1,
            "parent2": parent2,
        }
    
    def test_morning_absence_policy_creates_event(self, setup_full_stack):
        """Test that morning absence policy creates MORNING_ABSENCE event for absent student."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        # Mock repository to return no IN records (student absent)
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)  # Monday
        events = policy_engine.evaluate_morning_absence(target_date, "HS001")
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.MORNING_ABSENCE
        assert events[0].student_id == "HS001"
        assert events[0].evidence["status"] == "ABSENT"
        assert events[0].is_notification_type is True
    
    def test_morning_absence_no_event_for_present_student(self, setup_full_stack):
        """Test that no event is created when student has valid IN before check time."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        # Mock repository to return valid IN record before 07:30
        mock_record = Mock()
        mock_record.identity_candidate = "HS001"
        mock_record.direction = "in"
        mock_record.event_timestamp = 1767572000.0  # 07:13:20 on 2026-01-05
        mock_record.new_attendance_state = "present"
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = [mock_record]
        
        target_date = date(2026, 1, 5)
        events = policy_engine.evaluate_morning_absence(target_date, "HS001")
        
        assert len(events) == 0
    
    def test_morning_absence_no_event_for_later_start_student(self, setup_full_stack):
        """Test that student starting at 08:00 is not marked absent at 07:30."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)
        events = policy_engine.evaluate_morning_absence(target_date, "HS002")
        
        assert len(events) == 0
    
    def test_exit_policy_creates_session(self, setup_full_stack):
        """Test that OUT event creates exit session."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        # Create mock OUT decision context
        mock_transition = Mock(spec=ResolvedTransition)
        mock_transition.resolution_id = "RES-test123"
        mock_transition.source_timestamp = 43200  # 12:00
        mock_transition.direction = "out"
        
        mock_context = Mock(spec=AttendanceDecisionContext)
        mock_context.resolved_transition = mock_transition
        mock_context.person_id_override = "HS001"
        
        events = policy_engine.evaluate_exit_policy("HS001", mock_context, date(2026, 1, 5))
        
        # Should not create event immediately, just start session
        assert len(events) == 0
        assert "HS001:2026-01-05" in policy_engine._exit_sessions
    
    def test_short_exit_filtered_no_notification(self, setup_full_stack):
        """Test that IN within 30 minutes creates SHORT_EXIT (ignored, no notification)."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        # Create exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 43200  # 12:00
        mock_out_transition.direction = "out"
        
        mock_out_context = Mock(spec=AttendanceDecisionContext)
        mock_out_context.resolved_transition = mock_out_transition
        mock_out_context.person_id_override = "HS001"
        
        policy_engine.evaluate_exit_policy("HS001", mock_out_context, date(2026, 1, 5))
        
        # IN event within threshold (15 minutes)
        mock_in_transition = Mock(spec=ResolvedTransition)
        mock_in_transition.resolution_id = "RES-in123"
        mock_in_transition.source_timestamp = 44100  # 12:15
        mock_in_transition.direction = "in"
        
        mock_in_context = Mock(spec=AttendanceDecisionContext)
        mock_in_context.resolved_transition = mock_in_transition
        mock_in_context.person_id_override = "HS001"
        
        events = policy_engine.evaluate_in_after_exit("HS001", mock_in_context, date(2026, 1, 5))
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.SHORT_EXIT
        assert events[0].state == PolicyEventState.IGNORED
        assert events[0].is_notification_type is False
    
    def test_long_exit_creates_notification(self, setup_full_stack):
        """Test that IN after 30 minutes creates LONG_EXIT notification."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        # Create exit session
        mock_out_transition = Mock(spec=ResolvedTransition)
        mock_out_transition.resolution_id = "RES-out123"
        mock_out_transition.source_timestamp = 43200  # 12:00
        mock_out_transition.direction = "out"
        
        mock_out_context = Mock(spec=AttendanceDecisionContext)
        mock_out_context.resolved_transition = mock_out_transition
        mock_out_context.person_id_override = "HS001"
        
        policy_engine.evaluate_exit_policy("HS001", mock_out_context, date(2026, 1, 5))
        
        # IN event after threshold (45 minutes)
        mock_in_transition = Mock(spec=ResolvedTransition)
        mock_in_transition.resolution_id = "RES-in123"
        mock_in_transition.source_timestamp = 45900  # 12:45
        mock_in_transition.direction = "in"
        
        mock_in_context = Mock(spec=AttendanceDecisionContext)
        mock_in_context.resolved_transition = mock_in_transition
        mock_in_context.person_id_override = "HS001"
        
        events = policy_engine.evaluate_in_after_exit("HS001", mock_in_context, date(2026, 1, 5))
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.LONG_EXIT
        assert events[0].is_notification_type is True
    
    def test_missing_checkout_creates_event(self, setup_full_stack):
        """Test that missing checkout creates MISSING_CHECKOUT event."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)
        events = policy_engine.evaluate_missing_checkout(target_date, "HS001")
        
        assert len(events) == 1
        assert events[0].policy_type == PolicyType.MISSING_CHECKOUT
        assert events[0].evidence["status"] == "MISSING_CHECKOUT"
        assert events[0].is_notification_type is True
    
    def test_deduplication_prevents_duplicate_events(self, setup_full_stack):
        """Test that repeated evaluation doesn't create duplicate events."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)
        
        # First evaluation
        events1 = policy_engine.evaluate_morning_absence(target_date, "HS001")
        assert len(events1) == 1
        
        # Second evaluation - should be deduplicated
        events2 = policy_engine.evaluate_morning_absence(target_date, "HS001")
        assert len(events2) == 1
        assert events2[0].state == PolicyEventState.DEDUPLICATED
    
    def test_notification_queue_enqueues_for_correct_recipients(self, setup_full_stack):
        """Test that notifications are enqueued only for correct parent recipients."""
        stack = setup_full_stack
        notification_queue = stack["notification_queue"]
        parent_registry = stack["parent_registry"]
        
        # Create a MORNING_ABSENCE event for HS001
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1767573000.0,  # 07:30 on 2026-01-05
            effective_at=1767573000.0,
            source_attendance_event_id="",
            evidence={
                "check_time": "07:30:00",
                "expected_entry_time": "07:00:00",
                "status": "ABSENT",
                "expected_sessions": [{"session_id": "MATH101_MON", "class_name": "Math 101", "entry_time": "07:00:00"}],
            },
        )
        
        # Create message
        message = create_notification_message(
            policy_type="morning_absence",
            student_name="Test Student",
            student_id="HS001",
            date="2026-01-05",
            evidence=event.evidence,
        )
        
        # Enqueue notification
        notification = notification_queue.enqueue_notification(event, stack["parent1"], message)
        
        assert notification is not None
        assert notification.student_id == "HS001"
        assert notification.parent_id == stack["parent1"].parent_id
        assert notification.telegram_chat_id == "111111111"
        assert notification.notification_type == "morning_absence"
    
    def test_notification_queue_respects_preferences(self, setup_full_stack):
        """Test that notification preferences are respected (parent2 only gets morning absence)."""
        stack = setup_full_stack
        notification_queue = stack["notification_queue"]
        
        # Create a LONG_EXIT event for HS002
        event = PolicyEvent(
            event_id="PEV-test456",
            student_id="HS002",
            policy_type=PolicyType.LONG_EXIT,
            occurred_at=1767573000.0,
            effective_at=1767573000.0,
            source_attendance_event_id="",
            evidence={
                "out_time": "12:00:00",
                "elapsed_minutes": 45,
                "threshold_minutes": 30,
                "status": "EXCEEDED_THRESHOLD",
            },
        )
        
        message = create_notification_message(
            policy_type="long_exit",
            student_name="Another Student",
            student_id="HS002",
            date="2026-01-05",
            evidence=event.evidence,
        )
        
        # Parent2 has MORNING_ABSENCE_ONLY preference, should NOT receive LONG_EXIT
        notification = notification_queue.enqueue_notification(event, stack["parent2"], message)
        
        assert notification is None  # Should be None because parent2 doesn't want LONG_EXIT
    
    def test_notification_queue_deduplication(self, setup_full_stack):
        """Test that duplicate notifications are deduplicated by idempotency key."""
        stack = setup_full_stack
        notification_queue = stack["notification_queue"]
        
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="HS001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=1767573000.0,
            effective_at=1767573000.0,
            source_attendance_event_id="",
            evidence={"check_time": "07:30:00", "status": "ABSENT"},
        )
        
        message = create_notification_message(
            policy_type="morning_absence",
            student_name="Test Student",
            student_id="HS001",
            date="2026-01-05",
            evidence=event.evidence,
        )
        
        # First enqueue
        notif1 = notification_queue.enqueue_notification(event, stack["parent1"], message)
        assert notif1 is not None
        
        # Second enqueue with same idempotency key
        notif2 = notification_queue.enqueue_notification(event, stack["parent1"], message)
        assert notif2 is not None
        assert notif2.notification_id == notif1.notification_id  # Same record returned
    
    def test_parent_linking_flow(self, setup_full_stack):
        """Test the complete parent linking flow via link codes."""
        stack = setup_full_stack
        parent_registry = stack["parent_registry"]
        
        # Create link code for HS001
        link_code = parent_registry.create_link_code("HS001", expires_in_hours=24)
        
        assert link_code.code is not None
        assert link_code.student_id == "HS001"
        assert link_code.status.value == "active"
        
        # Simulate parent scanning code and sending /start
        validated = parent_registry.validate_link_code(link_code.code, "333333333")
        
        assert validated is not None
        assert validated.status.value == "used"
        assert validated.used_by_chat_id == "333333333"
        
        # Verify parent now has chat_id (in real flow, this would update parent record)
        # For this test, we just verify the link code was consumed
        retrieved = parent_registry.get_link_code(link_code.code)
        assert retrieved.status.value == "used"
    
    def test_cross_parent_isolation(self, setup_full_stack):
        """Test that HS001 notifications go only to parent1, HS002 to parent2."""
        stack = setup_full_stack
        parent_registry = stack["parent_registry"]
        
        # Get chat IDs for HS001 morning absence
        chat_ids_1 = parent_registry.get_chat_id_for_student_policy("HS001", "morning_absence")
        assert chat_ids_1 == ["111111111"]
        
        # Get chat IDs for HS002 morning absence
        chat_ids_2 = parent_registry.get_chat_id_for_student_policy("HS002", "morning_absence")
        assert chat_ids_2 == ["222222222"]
        
        # Get chat IDs for HS001 long_exit (parent1 has ALL, parent2 has MORNING_ONLY)
        chat_ids_1_long = parent_registry.get_chat_id_for_student_policy("HS001", "long_exit")
        assert chat_ids_1_long == ["111111111"]
        
        chat_ids_2_long = parent_registry.get_chat_id_for_student_policy("HS002", "long_exit")
        assert chat_ids_2_long == []  # parent2 doesn't want LONG_EXIT
    
    def test_evaluate_all_policies(self, setup_full_stack):
        """Test evaluating all policies at once."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)
        current_time = datetime(2026, 1, 5, 18, 0, 0).timestamp()
        
        events = policy_engine.evaluate_all_policies(target_date, current_time)
        
        # Should have events for both students
        student_ids = {e.student_id for e in events}
        assert "HS001" in student_ids
        assert "HS002" in student_ids
        
        # Should have morning absence and missing checkout
        types = {e.policy_type for e in events}
        assert PolicyType.MORNING_ABSENCE in types
        assert PolicyType.MISSING_CHECKOUT in types
    
    def test_canonical_student_id_preserved(self, setup_full_stack):
        """Test that student_id is preserved throughout the pipeline."""
        stack = setup_full_stack
        policy_engine = stack["policy_engine"]
        
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        
        target_date = date(2026, 1, 5)
        events = policy_engine.evaluate_morning_absence(target_date, "HS001")
        
        assert len(events) == 1
        assert events[0].student_id == "HS001"
        
        # Verify idempotency key contains student_id
        assert "HS001" in events[0].idempotency_key
        assert "morning_absence" in events[0].idempotency_key
    
    def test_no_cross_parent_delivery(self, setup_full_stack):
        """Test that notifications for HS001 never go to HS002's parent."""
        stack = setup_full_stack
        parent_registry = stack["parent_registry"]
        
        # HS001's parent should only be parent1
        recipients_1 = parent_registry.get_notification_recipients("HS001", "morning_absence")
        assert len(recipients_1) == 1
        assert recipients_1[0].parent_id == stack["parent1"].parent_id
        
        # HS002's parent should only be parent2
        recipients_2 = parent_registry.get_notification_recipients("HS002", "morning_absence")
        assert len(recipients_2) == 1
        assert recipients_2[0].parent_id == stack["parent2"].parent_id
        
        # Verify no overlap
        assert recipients_1[0].parent_id != recipients_2[0].parent_id


class TestPhase37BExcelIntegration:
    """Tests for Excel output with policy events."""
    
    @pytest.fixture
    def setup_excel_stack(self, tmp_path):
        """Create stack with Excel exporter."""
        from app.attendance.policy_engine.excel_integration import PolicyExcelExporter, PolicyExcelExporterConfig
        from app.attendance.repository import AttendanceRepository
        
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
            entry_time=25200,
            exit_time=54000,
            entry_window_start=27000,
            entry_window_end=29700,
            late_tolerance=600,
            exit_window_start=53100,
            exit_window_end=55800,
        )
        timetable.entries.append(entry)
        
        # Create calendar engine
        calendar_config = CalendarConfig(timezone="Asia/Bangkok")
        calendar_engine = CalendarEngine(calendar_config)
        
        # Create daily resolver
        daily_resolver = DailyExpectedResolver(timetable, calendar_engine, ["HS001"])
        
        # Create attendance engine
        policy = AttendancePolicy(policy_id="test-policy")
        attendance_engine = AttendanceEngine(policy)
        attendance_engine.repository = Mock()
        
        # Create policy engine
        config = PolicyEngineConfig()
        policy_engine = AttendancePolicyEngine(
            timetable=timetable,
            calendar_engine=calendar_engine,
            daily_resolver=daily_resolver,
            attendance_engine=attendance_engine,
            config=config,
        )
        
        # Create Excel exporter
        repo = AttendanceRepository()
        excel_config = PolicyExcelExporterConfig()
        excel_exporter = PolicyExcelExporter(repo, excel_config)
        
        return {
            "timetable": timetable,
            "policy_engine": policy_engine,
            "excel_exporter": excel_exporter,
            "attendance_engine": attendance_engine,
        }
    
    def test_excel_includes_policy_events_sheet(self, setup_excel_stack, tmp_path):
        """Test that Excel export includes POLICY_EVENTS sheet."""
        stack = setup_excel_stack
        excel_exporter = stack["excel_exporter"]
        policy_engine = stack["policy_engine"]
        
        # Generate some policy events
        stack["attendance_engine"].repository.query_by_time_range.return_value = []
        target_date = date(2026, 1, 5)
        events = policy_engine.evaluate_morning_absence(target_date, "HS001")
        
        # Export
        output_path = tmp_path / "test_attendance.xlsx"
        from app.attendance.daily_excel import DailyExportRequest
        
        request = DailyExportRequest(
            date=target_date,
            output_path=str(output_path),
            timetable=stack["timetable"],
        )
        
        # Mock notification records
        notification_records = []
        
        result = excel_exporter.export_daily_with_policy(
            request=request,
            policy_events=events,
            notification_records=notification_records,
        )
        
        assert result.success is True
        assert "POLICY_EVENTS" in result.sheets_created
        assert "POLICY_SUMMARY" in result.sheets_created
    
    def test_excel_includes_notification_status_sheet(self, setup_excel_stack, tmp_path):
        """Test that Excel export includes NOTIFICATION_STATUS sheet."""
        stack = setup_excel_stack
        excel_exporter = stack["excel_exporter"]
        
        output_path = tmp_path / "test_attendance2.xlsx"
        from app.attendance.daily_excel import DailyExportRequest
        
        request = DailyExportRequest(
            date=date(2026, 1, 5),
            output_path=str(output_path),
            timetable=stack["timetable"],
        )
        
        # Mock notification records
        notification_records = [{
            "notification_id": "NOTIF-test123",
            "idempotency_key": "2026-01-05:HS001:morning_absence",
            "event_id": "PEV-test123",
            "student_id": "HS001",
            "parent_id": "PAR-test123",
            "telegram_chat_id": "111111111",
            "notification_type": "morning_absence",
            "message": "Test message",
            "status": "sent",
            "attempts": 1,
            "max_attempts": 3,
            "created_at": "2026-01-05T07:30:00Z",
            "sent_at": "2026-01-05T07:30:05Z",
            "last_error": None,
            "last_attempt_at": "2026-01-05T07:30:05Z",
        }]
        
        result = excel_exporter.export_daily_with_policy(
            request=request,
            policy_events=[],
            notification_records=notification_records,
        )
        
        assert result.success is True
        assert "NOTIFICATION_STATUS" in result.sheets_created


if __name__ == "__main__":
    pytest.main([__file__, "-v"])