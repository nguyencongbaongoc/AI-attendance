"""
Phase 37B — Attendance Policy Engine.

Canonical policy decision layer that evaluates attendance state against timetable
and produces PolicyEvents for notification routing.

Architecture:
    Timetable + DailyExpectedResolver + Attendance State + Raw/Resolved IN/OUT evidence
        ↓
    Attendance Policy Engine
        ↓
    Canonical Policy Event
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    AttendanceState,
)
from app.attendance.calendar import CalendarEngine, CalendarDay, DayType
from app.attendance.daily_resolver import (
    DailyExpectedResolver,
    ExpectedStudent,
    ExpectedSession,
    ExpectedStatus,
)
from app.attendance.engine import AttendanceEngine, AttendanceDecisionContext
from app.attendance.policy import AttendancePolicy
from app.attendance.policy_engine.contract import (
    PolicyEvent,
    PolicyType,
    PolicyEventState,
    generate_policy_event_id,
    validate_policy_event,
)
from app.attendance.policy_engine.exit_session import ExitSessionStore, create_exit_session_store_from_settings
from app.attendance.session_context import SessionContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyEngineConfig:
    """
    Configuration for the Attendance Policy Engine.
    
    All thresholds are configurable - no hardcoded values.
    """
    # Morning absence check time (seconds from midnight)
    # Default: 07:30 = 27000 seconds
    morning_absence_check_seconds: int = 27000
    
    # Exit threshold for LONG_EXIT (seconds)
    # Default: 30 minutes = 1800 seconds
    exit_threshold_seconds: int = 1800
    
    # Default expected departure time (seconds from midnight)
    # Default: 17:30 = 63000 seconds
    default_departure_check_seconds: int = 63000
    
    # Timezone for time calculations
    timezone: str = "Asia/Bangkok"
    
    def __post_init__(self):
        if self.morning_absence_check_seconds < 0 or self.morning_absence_check_seconds >= 86400:
            raise ValueError("morning_absence_check_seconds must be in [0, 86400)")
        if self.exit_threshold_seconds < 0:
            raise ValueError("exit_threshold_seconds must be >= 0")
        if self.default_departure_check_seconds < 0 or self.default_departure_check_seconds >= 86400:
            raise ValueError("default_departure_check_seconds must be in [0, 86400)")
        try:
            pytz.timezone(self.timezone)
        except pytz.UnknownTimeZoneError:
            raise ValueError(f"Unknown timezone: {self.timezone}")


DEFAULT_POLICY_CONFIG = PolicyEngineConfig()


@dataclass
class AttendanceStateSnapshot:
    """
    Snapshot of a student's attendance state for a given day.
    
    This is built from AttendanceDecision records and used by the policy engine.
    """
    student_id: str
    date: datetime.date
    
    # IN events (chronological)
    in_events: List[AttendanceDecisionContext] = field(default_factory=list)
    
    # OUT events (chronological)
    out_events: List[AttendanceDecisionContext] = field(default_factory=list)
    
    # Current derived state
    current_state: AttendanceState = AttendanceState.UNKNOWN
    
    # Last known IN event (for exit duration calculation)
    last_in_event: Optional[AttendanceDecisionContext] = None
    
    # Last known OUT event
    last_out_event: Optional[AttendanceDecisionContext] = None
    
    # Timetable entry for the day
    timetable_entry: Optional[TimetableEntry] = None
    
    # Expected student info
    expected_student: Optional[ExpectedStudent] = None
    
    # Active exit session (OUT without matching IN)
    active_exit_session: Optional[Dict[str, Any]] = None


class AttendancePolicyEngine:
    """
    Canonical Attendance Policy Engine.
    
    Evaluates attendance state against timetable and produces PolicyEvents.
    This is the SINGLE source of policy decisions - Telegram and Excel are consumers only.
    
    Policies implemented:
    1. Morning Absence: Check at configured time (default 07:30) if expected student has valid IN
    2. 30-minute Exit: Track OUT events, alert if no IN within threshold
    3. Expected Departure: Check at departure time (timetable-derived or default 17:30) for missing OUT
    """
    
    def __init__(
        self,
        timetable: Timetable,
        calendar_engine: CalendarEngine,
        daily_resolver: DailyExpectedResolver,
        attendance_engine: AttendanceEngine,
        config: PolicyEngineConfig = DEFAULT_POLICY_CONFIG,
    ):
        self.timetable = timetable
        self.calendar_engine = calendar_engine
        self.daily_resolver = daily_resolver
        self.attendance_engine = attendance_engine
        self.config = config
        self.timezone = pytz.timezone(config.timezone)
        
        # In-memory state for exit session tracking
        # In production, this would be persisted
        self._exit_sessions: Dict[str, Dict[str, Any]] = {}  # student_id -> session info
        
        # Track processed policy events for deduplication
        self._processed_events: Dict[str, PolicyEvent] = {}  # idempotency_key -> PolicyEvent
    
    def evaluate_morning_absence(
        self,
        target_date: datetime.date,
        student_id: str,
        check_timestamp: Optional[float] = None,
    ) -> List[PolicyEvent]:
        """
        Policy #1: Morning Absence Check.
        
        At the configured check time (default 07:30), verify if expected students have a valid IN.
        
        Flow:
            date → DailyExpectedResolver → expected student?
                ├── NO → ignore
                └── YES
                    ↓
                exception?
                    ├── YES → ignore
                    └── NO
                        ↓
                     valid IN?
                        ├── YES → PRESENT (no event)
                        └── NO → MORNING_ABSENCE → Notification Event
        
        Args:
            target_date: Date to check
            student_id: Student to check
            check_timestamp: Optional timestamp to use as check time (for testing)
            
        Returns:
            List of PolicyEvents (0 or 1)
        """
        events = []
        
        # Get expected student for this date
        expected_student = self.daily_resolver.get_expected_student(target_date, student_id)
        if not expected_student:
            logger.debug(f"Student {student_id} not found in expected students for {target_date}")
            return events
        
        # Check if student is expected (scheduled, later_start, earlier_departure)
        if not expected_student.is_expected:
            logger.debug(f"Student {student_id} not expected on {target_date}: {expected_student.status}")
            return events
        
        # Check for exceptions that would cancel the morning check
        if expected_student.status in (ExpectedStatus.HOLIDAY, ExpectedStatus.CANCELLED, ExpectedStatus.NOT_SCHEDULED):
            logger.debug(f"Student {student_id} has exception status: {expected_student.status}")
            return events
        
        # Determine check time
        if check_timestamp is None:
            # Use configured morning check time
            check_time_sfm = self.config.morning_absence_check_seconds
            # Convert to timestamp for the target date
            check_dt = self.timezone.localize(
                datetime.combine(target_date, time.min)
            ) + timedelta(seconds=check_time_sfm)
            check_timestamp = check_dt.timestamp()
        else:
            check_time_sfm = self._timestamp_to_seconds_from_midnight(check_timestamp)
        
        # Check if student has a session that starts at or before check time
        has_early_session = False
        earliest_entry_time = None
        
        for session in expected_student.sessions:
            if session.is_cancelled:
                continue
            if earliest_entry_time is None or session.effective_entry_time < earliest_entry_time:
                earliest_entry_time = session.effective_entry_time
            if session.effective_entry_time <= check_time_sfm:
                has_early_session = True
        
        # If student's earliest session starts AFTER the check time, don't report absence
        # (e.g., student starts at 08:30, check is at 07:30)
        if earliest_entry_time is not None and earliest_entry_time > check_time_sfm:
            logger.debug(f"Student {student_id} starts at {earliest_entry_time}s, after check time {check_time_sfm}s")
            return events
        
        # Check if student has a valid IN event before check time
        has_valid_in = self._has_valid_in_before(student_id, target_date, check_time_sfm)
        
        if not has_valid_in:
            # Create MORNING_ABSENCE policy event
            event = self._create_policy_event(
                student_id=student_id,
                policy_type=PolicyType.MORNING_ABSENCE,
                occurred_at=check_timestamp,
                source_attendance_event_id="",  # No source event for absence
                evidence={
                    "check_time": self._format_seconds(check_time_sfm),
                    "expected_entry_time": self._format_seconds(earliest_entry_time) if earliest_entry_time else "N/A",
                    "status": "ABSENT",
                    "expected_sessions": [
                        {
                            "session_id": s.session_id,
                            "class_name": s.class_name,
                            "entry_time": self._format_seconds(s.effective_entry_time),
                        }
                        for s in expected_student.sessions if not s.is_cancelled
                    ],
                },
            )
            events.append(event)
            logger.info(f"MORNING_ABSENCE: {student_id} on {target_date} at {self._format_seconds(check_time_sfm)}")
        
        return events
    
    def evaluate_exit_policy(
        self,
        student_id: str,
        out_event: ResolvedTransition,
        target_date: datetime.date,
    ) -> List[PolicyEvent]:
        """
        Policy #2: 30-Minute Exit Policy with Semantic Context (Phase 37D).
        
        When a valid OUT event occurs, check semantic context first:
        - If outside_allowed=True (BREAK, OUTSIDE_LESSON, LAB with outside_allowed) → EXPECTED_OUTSIDE, no exit session
        - If outside_allowed=False (CLASSROOM, OTHER) → start exit session timer
        
        If exit session started:
        - If no IN event within threshold → LONG_EXIT notification
        - If IN event within threshold → SHORT_EXIT (filtered, no notification)
        
        Args:
            student_id: Student who exited
            out_event: The OUT ResolvedTransition
            target_date: Date of the event
            
        Returns:
            List of PolicyEvents (0 or 1 for LONG_EXIT start, SHORT_EXIT doesn't create event)
        """
        events = []
        
        # Get expected student to verify they should be in school
        expected_student = self.daily_resolver.get_expected_student(target_date, student_id)
        if not expected_student or not expected_student.is_expected:
            logger.debug(f"Student {student_id} not expected on {target_date}, ignoring exit")
            return events
        
        out_time_sfm = out_event.source_timestamp
        out_timestamp = self._seconds_from_midnight_to_timestamp(target_date, out_time_sfm)
        
        # Phase 37D: Get semantic context for this OUT event
        session_context = self.daily_resolver.get_session_context(target_date, student_id, out_time_sfm)
        
        # Semantic suppression: if outside is allowed, this is EXPECTED_OUTSIDE
        if session_context and session_context.outside_allowed:
            logger.info(f"EXPECTED_OUTSIDE: {student_id} at {self._format_seconds(out_time_sfm)} "
                       f"(session_type={session_context.session_type.value}, "
                       f"subject={session_context.subject}, location={session_context.location})")
            # Create EXPECTED_OUTSIDE policy event for audit trail (not for notification)
            event = self._create_policy_event(
                student_id=student_id,
                policy_type=PolicyType.SHORT_EXIT,  # Reuse SHORT_EXIT type for audit
                occurred_at=out_timestamp,
                source_attendance_event_id=out_event.resolution_id,
                evidence={
                    "out_time": self._format_seconds(out_time_sfm),
                    "session_type": session_context.session_type.value,
                    "subject": session_context.subject,
                    "location": session_context.location,
                    "expected_location": session_context.expected_location,
                    "outside_allowed": True,
                    "semantic_state": "EXPECTED_OUTSIDE",
                    "status": "SEMANTIC_SUPPRESSION",
                },
            )
            event = event.__class__(
                **{**event.to_dict(), "state": PolicyEventState.IGNORED}
            )
            events.append(event)
            return events
        
        # Check if there's already an active exit session for this student
        session_key = f"{student_id}:{target_date.isoformat()}"
        
        if session_key in self._exit_sessions:
            # Already have an active exit session - this is a duplicate OUT
            logger.debug(f"Duplicate OUT for {student_id} on {target_date}, ignoring")
            return events
        
        # Create exit session (only for CLASSROOM/OTHER where outside_allowed=False)
        self._exit_sessions[session_key] = {
            "student_id": student_id,
            "date": target_date,
            "out_time_sfm": out_time_sfm,
            "out_timestamp": out_timestamp,
            "out_event_id": out_event.resolution_id,
            "out_decision_id": out_event.resolution_id,
            "started_at": datetime.utcnow().timestamp(),
            "threshold_seconds": self.config.exit_threshold_seconds,
            "notified": False,
            # Store semantic context for later evaluation
            "session_context": session_context.to_dict() if session_context else None,
        }
        
        logger.info(f"Exit session started for {student_id} at {self._format_seconds(out_time_sfm)} "
                   f"(session_type={session_context.session_type.value if session_context else 'unknown'})")
        
        # Note: We don't create a LONG_EXIT event immediately.
        # The LONG_EXIT event is created when the threshold is exceeded (checked periodically)
        # or when an IN event arrives (which creates SHORT_EXIT or cancels the session).
        
        return events
    
    def evaluate_in_after_exit(
        self,
        student_id: str,
        in_event: ResolvedTransition,
        target_date: datetime.date,
    ) -> List[PolicyEvent]:
        """
        Evaluate IN event that may close an exit session.
        
        If IN arrives within threshold → SHORT_EXIT (no notification)
        If IN arrives after threshold → LONG_EXIT already notified, session closes
        
        Args:
            student_id: Student who entered
            in_event: The IN ResolvedTransition
            target_date: Date of the event
            
        Returns:
            List of PolicyEvents (SHORT_EXIT if within threshold)
        """
        events = []
        
        session_key = f"{student_id}:{target_date.isoformat()}"
        
        if session_key not in self._exit_sessions:
            # No active exit session - normal entry
            return events
        
        session = self._exit_sessions[session_key]
        in_time_sfm = in_event.source_timestamp
        in_timestamp = self._seconds_from_midnight_to_timestamp(target_date, in_time_sfm)
        
        # Calculate duration
        duration_seconds = in_timestamp - session["out_timestamp"]
        
        if duration_seconds <= self.config.exit_threshold_seconds:
            # SHORT_EXIT - within threshold, no notification needed
            logger.info(f"SHORT_EXIT: {student_id} returned after {duration_seconds}s (threshold: {self.config.exit_threshold_seconds}s)")
            
            # Create SHORT_EXIT policy event for audit trail (but not for notification)
            event = self._create_policy_event(
                student_id=student_id,
                policy_type=PolicyType.SHORT_EXIT,
                occurred_at=in_timestamp,
                source_attendance_event_id=in_event.resolution_id,
                evidence={
                    "out_time": self._format_seconds(session["out_time_sfm"]),
                    "in_time": self._format_seconds(in_time_sfm),
                    "duration_seconds": duration_seconds,
                    "threshold_seconds": self.config.exit_threshold_seconds,
                    "status": "RETURNED_WITHIN_THRESHOLD",
                },
            )
            event = event.__class__(
                **{**event.to_dict(), "state": PolicyEventState.IGNORED}
            )
            events.append(event)
        else:
            # LONG_EXIT - threshold already exceeded
            # If not already notified, create LONG_EXIT event
            if not session["notified"]:
                event = self._create_policy_event(
                    student_id=student_id,
                    policy_type=PolicyType.LONG_EXIT,
                    occurred_at=session["out_timestamp"] + self.config.exit_threshold_seconds,
                    source_attendance_event_id=session["out_decision_id"],
                    evidence={
                        "out_time": self._format_seconds(session["out_time_sfm"]),
                        "in_time": self._format_seconds(in_time_sfm),
                        "duration_seconds": duration_seconds,
                        "threshold_seconds": self.config.exit_threshold_seconds,
                        "status": "EXCEEDED_THRESHOLD",
                    },
                )
                events.append(event)
                logger.warning(f"LONG_EXIT: {student_id} exceeded threshold ({duration_seconds}s > {self.config.exit_threshold_seconds}s)")
        
        # Close the exit session
        del self._exit_sessions[session_key]
        
        return events
    
    def check_exit_sessions(self, current_timestamp: float) -> List[PolicyEvent]:
        """
        Periodically check active exit sessions for threshold exceedance.
        
        This should be called regularly (e.g., every minute) to detect LONG_EXIT.
        
        Args:
            current_timestamp: Current Unix timestamp
            
        Returns:
            List of LONG_EXIT PolicyEvents for sessions that exceeded threshold
        """
        events = []
        current_dt = datetime.fromtimestamp(current_timestamp, self.timezone)
        current_date = current_dt.date()
        current_time_sfm = current_dt.hour * 3600 + current_dt.minute * 60 + current_dt.second
        
        sessions_to_remove = []
        
        for session_key, session in self._exit_sessions.items():
            # Check if session is for today
            if session["date"] != current_date:
                # Session from previous day - clean up
                sessions_to_remove.append(session_key)
                continue
            
            # Calculate elapsed time since OUT
            elapsed = current_timestamp - session["out_timestamp"]
            
            if elapsed >= self.config.exit_threshold_seconds and not session["notified"]:
                # Threshold exceeded - create LONG_EXIT event
                event = self._create_policy_event(
                    student_id=session["student_id"],
                    policy_type=PolicyType.LONG_EXIT,
                    occurred_at=session["out_timestamp"] + self.config.exit_threshold_seconds,
                    source_attendance_event_id=session["out_decision_id"],
                    evidence={
                        "out_time": self._format_seconds(session["out_time_sfm"]),
                        "elapsed_seconds": elapsed,
                        "threshold_seconds": self.config.exit_threshold_seconds,
                        "status": "THRESHOLD_EXCEEDED_NO_RETURN",
                    },
                )
                events.append(event)
                session["notified"] = True
                logger.warning(f"LONG_EXIT detected for {session['student_id']} after {elapsed}s")
        
        # Clean up old sessions
        for key in sessions_to_remove:
            del self._exit_sessions[key]
        
        return events
    
    def evaluate_missing_checkout(
        self,
        target_date: datetime.date,
        student_id: str,
        check_timestamp: Optional[float] = None,
    ) -> List[PolicyEvent]:
        """
        Policy #3: Expected Departure / Missing Checkout.
        
        At the expected departure time (timetable-derived or default 17:30),
        check if expected student has a valid OUT.
        
        Flow:
            expected student
                ↓
            applicable departure time
                ↓
            valid OUT?
               ┌─┴─┐
              YES  NO
               │    │
               ▼    ▼
             ignore
                    ↓
              exception?
                ├── YES → ignore
                └── NO
                     ↓
               MISSING_CHECKOUT
                     ↓
               Notification Event
        
        Args:
            target_date: Date to check
            student_id: Student to check
            check_timestamp: Optional timestamp to use as check time (for testing)
            
        Returns:
            List of PolicyEvents (0 or 1)
        """
        events = []
        
        # Get expected student for this date
        expected_student = self.daily_resolver.get_expected_student(target_date, student_id)
        if not expected_student or not expected_student.is_expected:
            return events
        
        # Check for exceptions
        if expected_student.status in (ExpectedStatus.HOLIDAY, ExpectedStatus.CANCELLED, ExpectedStatus.NOT_SCHEDULED):
            return events
        
        # Determine departure check time
        # Priority: timetable-derived departure time > configured default
        departure_time_sfm = self.config.default_departure_check_seconds
        
        for session in expected_student.sessions:
            if session.is_cancelled:
                continue
            # Use the latest exit time from all sessions
            if session.effective_exit_time > departure_time_sfm:
                departure_time_sfm = session.effective_exit_time
        
        if check_timestamp is None:
            check_dt = self.timezone.localize(
                datetime.combine(target_date, time.min)
            ) + timedelta(seconds=departure_time_sfm)
            check_timestamp = check_dt.timestamp()
        else:
            departure_time_sfm = self._timestamp_to_seconds_from_midnight(check_timestamp)
        
        # Check if student has a valid OUT event
        has_valid_out = self._has_valid_out_after(student_id, target_date, departure_time_sfm)
        
        if not has_valid_out:
            # Check if there's an active exit session (student already checked out)
            session_key = f"{student_id}:{target_date.isoformat()}"
            if session_key in self._exit_sessions:
                logger.debug(f"Student {student_id} has active exit session, not reporting missing checkout")
                return events
            
            # Create MISSING_CHECKOUT policy event
            event = self._create_policy_event(
                student_id=student_id,
                policy_type=PolicyType.MISSING_CHECKOUT,
                occurred_at=check_timestamp,
                source_attendance_event_id="",  # No source event for missing checkout
                evidence={
                    "expected_departure_time": self._format_seconds(departure_time_sfm),
                    "status": "MISSING_CHECKOUT",
                    "expected_sessions": [
                        {
                            "session_id": s.session_id,
                            "class_name": s.class_name,
                            "exit_time": self._format_seconds(s.effective_exit_time),
                        }
                        for s in expected_student.sessions if not s.is_cancelled
                    ],
                },
            )
            events.append(event)
            logger.info(f"MISSING_CHECKOUT: {student_id} on {target_date} at {self._format_seconds(departure_time_sfm)}")
        
        return events
    
    def evaluate_all_policies(
        self,
        target_date: datetime.date,
        current_timestamp: Optional[float] = None,
    ) -> List[PolicyEvent]:
        """
        Evaluate all policies for all expected students on a given date.
        
        This is the main entry point for scheduled policy evaluation.
        
        Args:
            target_date: Date to evaluate
            current_timestamp: Current time (defaults to now)
            
        Returns:
            List of all PolicyEvents generated
        """
        all_events = []
        
        if current_timestamp is None:
            current_timestamp = datetime.utcnow().timestamp()
        
        # Get all expected students for the date
        expected_result = self.daily_resolver.resolve_for_date(target_date)
        
        for expected_student in expected_result.expected_students:
            student_id = expected_student.student_id
            
            # Skip if not expected
            if not expected_student.is_expected:
                continue
            
            # Policy 1: Morning Absence (only if check time has passed)
            current_time_sfm = self._timestamp_to_seconds_from_midnight(current_timestamp)
            if current_time_sfm >= self.config.morning_absence_check_seconds:
                events = self.evaluate_morning_absence(target_date, student_id, current_timestamp)
                all_events.extend(events)
            
            # Policy 3: Missing Checkout (only if departure time has passed)
            # Find latest departure time
            latest_departure = self.config.default_departure_check_seconds
            for session in expected_student.sessions:
                if not session.is_cancelled and session.effective_exit_time > latest_departure:
                    latest_departure = session.effective_exit_time
            
            if current_time_sfm >= latest_departure:
                events = self.evaluate_missing_checkout(target_date, student_id, current_timestamp)
                all_events.extend(events)
        
        # Policy 2: Check exit sessions for threshold exceedance
        exit_events = self.check_exit_sessions(current_timestamp)
        all_events.extend(exit_events)
        
        return all_events
    
    def process_attendance_decision(
        self,
        decision_context: AttendanceDecisionContext,
        target_date: datetime.date,
    ) -> List[PolicyEvent]:
        """
        Process a single attendance decision and evaluate relevant policies.
        
        This is called in real-time when an AttendanceDecision is made.
        
        Args:
            decision_context: The AttendanceDecisionContext from the engine
            target_date: Date of the event
            
        Returns:
            List of PolicyEvents generated
        """
        events = []
        
        # Extract student_id from context
        student_id = decision_context.person_id_override
        if not student_id:
            # Try to get from global observation
            # This would require access to the global observation
            logger.warning("No student_id in decision context, cannot evaluate policies")
            return events
        
        direction = decision_context.resolved_transition.direction
        
        if direction == "out":
            # OUT event - start exit session tracking
            events = self.evaluate_exit_policy(student_id, decision_context, target_date)
        elif direction == "in":
            # IN event - check if it closes an exit session
            events = self.evaluate_in_after_exit(student_id, decision_context, target_date)
        
        return events
    
    def _has_valid_in_before(
        self,
        student_id: str,
        target_date: datetime.date,
        check_time_sfm: int,
    ) -> bool:
        """Check if student has a valid IN event before the check time."""
        # Query attendance records for the date
        tz = self.timezone
        date_start = tz.localize(datetime.combine(target_date, time.min))
        date_end = tz.localize(datetime.combine(target_date, time.max))
        start_ts = date_start.astimezone(pytz.UTC).timestamp()
        end_ts = date_end.astimezone(pytz.UTC).timestamp()
        
        records = self.attendance_engine.repository.query_by_time_range(
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )
        
        # Filter for this student's IN events
        for record in records:
            if record.identity_candidate == student_id and record.direction == "in":
                record_time_sfm = self._timestamp_to_seconds_from_midnight(record.event_timestamp)
                if record_time_sfm <= check_time_sfm:
                    # Check if it's a valid attendance state (PRESENT or LATE)
                    if record.new_attendance_state in ("present", "late"):
                        return True
        
        return False
    
    def _has_valid_out_after(
        self,
        student_id: str,
        target_date: datetime.date,
        check_time_sfm: int,
    ) -> bool:
        """Check if student has a valid OUT event after the check time."""
        tz = self.timezone
        date_start = tz.localize(datetime.combine(target_date, time.min))
        date_end = tz.localize(datetime.combine(target_date, time.max))
        start_ts = date_start.astimezone(pytz.UTC).timestamp()
        end_ts = date_end.astimezone(pytz.UTC).timestamp()
        
        records = self.attendance_engine.repository.query_by_time_range(
            start_timestamp=start_ts,
            end_timestamp=end_ts,
        )
        
        for record in records:
            if record.identity_candidate == student_id and record.direction == "out":
                record_time_sfm = self._timestamp_to_seconds_from_midnight(record.event_timestamp)
                if record_time_sfm >= check_time_sfm:
                    if record.new_attendance_state in ("left", "present"):
                        return True
        
        return False
    
    def _create_policy_event(
        self,
        student_id: str,
        policy_type: PolicyType,
        occurred_at: float,
        source_attendance_event_id: str,
        evidence: Dict[str, Any],
    ) -> PolicyEvent:
        """Create a PolicyEvent with deduplication check."""
        # Create temporary event to get idempotency key
        temp_event = PolicyEvent(
            event_id="temp",
            student_id=student_id,
            policy_type=policy_type,
            occurred_at=occurred_at,
            effective_at=occurred_at,
            source_attendance_event_id=source_attendance_event_id,
            evidence=evidence,
        )
        
        idempotency_key = temp_event.idempotency_key
        
        # Check if already processed
        if idempotency_key in self._processed_events:
            existing = self._processed_events[idempotency_key]
            logger.debug(f"Deduplicated policy event: {idempotency_key}")
            return existing.__class__(**{**existing.to_dict(), "state": PolicyEventState.DEDUPLICATED})
        
        # Generate event ID
        event_id = generate_policy_event_id(
            student_id=student_id,
            policy_type=policy_type,
            occurred_at=occurred_at,
            source_attendance_event_id=source_attendance_event_id,
        )
        
        event = PolicyEvent(
            event_id=event_id,
            student_id=student_id,
            policy_type=policy_type,
            occurred_at=occurred_at,
            effective_at=occurred_at,
            source_attendance_event_id=source_attendance_event_id,
            evidence=evidence,
        )
        
        # Store for deduplication
        self._processed_events[idempotency_key] = event
        
        return event
    
    def _timestamp_to_seconds_from_midnight(self, timestamp: float) -> int:
        """Convert Unix timestamp to seconds from midnight in configured timezone."""
        dt_utc = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
        dt_local = dt_utc.astimezone(self.timezone)
        return dt_local.hour * 3600 + dt_local.minute * 60 + dt_local.second
    
    def _seconds_from_midnight_to_timestamp(self, date: datetime.date, seconds: int) -> float:
        """Convert seconds from midnight to Unix timestamp in configured timezone."""
        dt_local = self.timezone.localize(
            datetime.combine(date, time.min)
        ) + timedelta(seconds=seconds)
        return dt_local.astimezone(pytz.UTC).timestamp()
    
    def _format_seconds(self, seconds: int) -> str:
        """Format seconds from midnight as HH:MM:SS."""
        if seconds <= 0:
            return "N/A"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    def is_duplicate_policy_event(self, event: PolicyEvent) -> bool:
        """Check if a policy event is a duplicate."""
        return event.idempotency_key in self._processed_events
    
    def mark_event_notified(self, event: PolicyEvent) -> PolicyEvent:
        """Mark a policy event as notified."""
        return event.__class__(**{**event.to_dict(), "state": PolicyEventState.NOTIFICATION_SENT})
    
    def mark_event_failed(self, event: PolicyEvent, error: str) -> PolicyEvent:
        """Mark a policy event as failed."""
        evidence = event.evidence.copy()
        evidence["last_error"] = error
        return event.__class__(**{**event.to_dict(), "state": PolicyEventState.NOTIFICATION_FAILED, "evidence": evidence})


def create_attendance_policy_engine(
    timetable: Timetable,
    calendar_engine: CalendarEngine,
    daily_resolver: DailyExpectedResolver,
    attendance_engine: AttendanceEngine,
    config: Optional[PolicyEngineConfig] = None,
) -> AttendancePolicyEngine:
    """Factory function to create AttendancePolicyEngine."""
    return AttendancePolicyEngine(
        timetable=timetable,
        calendar_engine=calendar_engine,
        daily_resolver=daily_resolver,
        attendance_engine=attendance_engine,
        config=config or DEFAULT_POLICY_CONFIG,
    )