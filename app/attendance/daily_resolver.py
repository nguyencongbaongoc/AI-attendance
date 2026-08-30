"""
Phase 37A — Daily Expected-Student Resolver.

Resolves expected students for a given date based on timetable, calendar, and enrollment.
Provides automatic person_id resolution from GlobalObservation and automatic day resolution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    SessionType,
    AttendanceState,
)
from app.attendance.calendar import (
    CalendarEngine,
    CalendarDay,
    DayType,
    ScheduleException,
    ExceptionType,
)
from app.attendance.session_context import (
    SessionContext,
    create_session_context,
)
from app.replay.fusion import GlobalObservation

logger = logging.getLogger(__name__)


# =============================================================================
# RESOLVER TYPES
# =============================================================================

class ExpectedStatus(str, Enum):
    """Expected attendance status for a student on a given day."""
    SCHEDULED = "scheduled"           # Student has a session today
    NOT_SCHEDULED = "not_scheduled"   # Student has no session today
    HOLIDAY = "holiday"               # Today is a holiday
    EXCEPTION = "exception"           # Today has schedule exceptions
    LATER_START = "later_start"       # Student starts later today
    EARLIER_DEPARTURE = "earlier_departure"  # Student leaves earlier today
    CANCELLED = "cancelled"           # Student's session cancelled


@dataclass(frozen=True)
class ExpectedStudent:
    """Expected student information for a specific date."""
    student_id: str
    person_name: Optional[str]
    date: date
    session_day: SessionDay
    status: ExpectedStatus
    sessions: List["ExpectedSession"] = field(default_factory=list)
    exceptions: List[ScheduleException] = field(default_factory=list)
    
    @property
    def is_expected(self) -> bool:
        return self.status in (
            ExpectedStatus.SCHEDULED,
            ExpectedStatus.LATER_START,
            ExpectedStatus.EARLIER_DEPARTURE,
        )
    
    @property
    def has_sessions(self) -> bool:
        return len(self.sessions) > 0


@dataclass(frozen=True)
class ExpectedSession:
    """Expected session for a student on a specific date."""
    session_id: str
    class_name: str
    session_type: SessionType
    entry_time: int
    exit_time: int
    entry_window_start: int
    entry_window_end: int
    late_tolerance: int
    exit_window_start: int
    exit_window_end: int
    exception: Optional[ScheduleException] = None
    
    @property
    def is_cancelled(self) -> bool:
        return self.exception is not None and self.exception.exception_type == ExceptionType.CANCELLED
    
    @property
    def effective_entry_time(self) -> int:
        if self.exception and self.exception.new_entry_time is not None:
            return self.exception.new_entry_time
        return self.entry_time
    
    @property
    def effective_exit_time(self) -> int:
        if self.exception and self.exception.new_exit_time is not None:
            return self.exception.new_exit_time
        return self.exit_time


@dataclass(frozen=True)
class DailyExpectedResult:
    """Result of daily expected student resolution."""
    date: date
    session_day: SessionDay
    day_type: DayType
    expected_students: List[ExpectedStudent]
    total_scheduled: int
    total_not_scheduled: int
    calendar_day: CalendarDay


# =============================================================================
# IDENTITY RESOLUTION
# =============================================================================

@dataclass(frozen=True)
class IdentityResolution:
    """Result of resolving identity from GlobalObservation."""
    person_id: Optional[str]
    student_id: Optional[str]
    identity_confidence: float
    identity_certainty: str  # "known", "unknown", "ambiguous", "insufficient"
    resolution_method: str
    global_observation_id: str
    enrollment_index: Optional[int] = None


class IdentityResolver:
    """
    Resolves person_id and student_id from GlobalObservation.
    
    Uses the existing enrollment database and cross-camera fusion identity evidence.
    """
    
    def __init__(
        self,
        enrollment_person_ids: List[str],
        enrollment_embeddings: Optional[Any] = None,  # numpy array
        enrollment_metadata: Optional[Dict[str, Any]] = None,
    ):
        self.enrollment_person_ids = set(enrollment_person_ids)
        self.enrollment_embeddings = enrollment_embeddings
        self.enrollment_metadata = enrollment_metadata or {}
        
        # Build person_id -> enrollment_index mapping
        self._person_to_index: Dict[str, int] = {}
        if enrollment_metadata and "sample_provenance" in enrollment_metadata:
            for idx, prov in enumerate(enrollment_metadata["sample_provenance"]):
                person_id = prov.get("person_id")
                if person_id and person_id not in self._person_to_index:
                    self._person_to_index[person_id] = idx
    
    def resolve_from_global_observation(
        self,
        global_observation: GlobalObservation,
    ) -> IdentityResolution:
        """
        Resolve person_id and student_id from GlobalObservation.
        
        Uses the primary_identity_candidate from cross-camera fusion.
        """
        go_id = global_observation.global_observation_id
        
        # Check if GlobalObservation has a primary identity candidate
        primary_candidate = global_observation.primary_identity_candidate
        identity_confidence = global_observation.identity_confidence
        identity_state = global_observation.identity_state
        
        if primary_candidate and primary_candidate in self.enrollment_person_ids:
            # Known identity from enrollment
            enrollment_index = self._person_to_index.get(primary_candidate)
            return IdentityResolution(
                person_id=primary_candidate,
                student_id=primary_candidate,  # student_id == person_id in our model
                identity_confidence=identity_confidence,
                identity_certainty="known",
                resolution_method="global_observation_primary_candidate",
                global_observation_id=go_id,
                enrollment_index=enrollment_index,
            )
        
        # Check identity hypotheses from contributing observations
        for obs in global_observation.observations:
            if obs.identity_hypothesis and obs.identity_hypothesis.candidate_identity:
                candidate = obs.identity_hypothesis.candidate_identity
                if candidate in self.enrollment_person_ids:
                    enrollment_index = self._person_to_index.get(candidate)
                    return IdentityResolution(
                        person_id=candidate,
                        student_id=candidate,
                        identity_confidence=obs.identity_hypothesis.weighted_score / 10.0,
                        identity_certainty="known",
                        resolution_method="local_observation_hypothesis",
                        global_observation_id=go_id,
                        enrollment_index=enrollment_index,
                    )
        
        # Check identity evidence
        for obs in global_observation.observations:
            if obs.identity_evidence and obs.identity_evidence.best_match:
                candidate = obs.identity_evidence.best_match
                if candidate in self.enrollment_person_ids:
                    enrollment_index = self._person_to_index.get(candidate)
                    return IdentityResolution(
                        person_id=candidate,
                        student_id=candidate,
                        identity_confidence=obs.identity_evidence.best_similarity,
                        identity_certainty="known",
                        resolution_method="identity_evidence_best_match",
                        global_observation_id=go_id,
                        enrollment_index=enrollment_index,
                    )
        
        # No known identity found
        if primary_candidate:
            return IdentityResolution(
                person_id=primary_candidate,
                student_id=None,  # Not in enrollment
                identity_confidence=identity_confidence,
                identity_certainty="unknown",
                resolution_method="global_observation_unknown_candidate",
                global_observation_id=go_id,
            )
        
        return IdentityResolution(
            person_id=None,
            student_id=None,
            identity_confidence=0.0,
            identity_certainty="insufficient",
            resolution_method="no_identity_evidence",
            global_observation_id=go_id,
        )


# =============================================================================
# DAY RESOLUTION
# =============================================================================

class DayResolver:
    """
    Resolves SessionDay from event timestamp using configured timezone.
    
    Eliminates the need for manual day_override in AttendanceEngine.
    """
    
    def __init__(self, calendar_engine: CalendarEngine):
        self.calendar_engine = calendar_engine
    
    def resolve_day(self, timestamp: float) -> SessionDay:
        """
        Resolve SessionDay from UTC timestamp.
        
        Uses the calendar engine's configured timezone for deterministic conversion.
        """
        return self.calendar_engine.get_session_day_enum_from_timestamp(timestamp)
    
    def resolve_date(self, timestamp: float) -> date:
        """Resolve local date from UTC timestamp."""
        return self.calendar_engine.get_date_from_timestamp(timestamp)
    
    def resolve_calendar_day(self, timestamp: float) -> CalendarDay:
        """Resolve full CalendarDay from UTC timestamp."""
        target_date = self.resolve_date(timestamp)
        return self.calendar_engine.get_day(target_date)


# =============================================================================
# DAILY EXPECTED-STUDENT RESOLVER
# =============================================================================

class DailyExpectedResolver:
    """
    Resolves expected students for a given date.
    
    Combines timetable, calendar, and enrollment to determine:
    - Which students are scheduled today
    - Their expected arrival/departure times
    - Any exceptions or overrides
    """
    
    def __init__(
        self,
        timetable: Timetable,
        calendar_engine: CalendarEngine,
        enrollment_person_ids: Optional[List[str]] = None,
    ):
        self.timetable = timetable
        self.calendar_engine = calendar_engine
        self.enrollment_person_ids = set(enrollment_person_ids) if enrollment_person_ids else None
    
    def resolve_for_date(self, target_date: date) -> DailyExpectedResult:
        """
        Resolve expected students for a specific date.
        
        Args:
            target_date: Date to resolve for
            
        Returns:
            DailyExpectedResult with all expected students
        """
        calendar_day = self.calendar_engine.get_day(target_date)
        session_day = calendar_day.get_session_day()
        
        # Get all timetable entries for this day
        day_entries = [
            entry for entry in self.timetable.entries
            if entry.day == session_day
        ]
        
        # Group by student_id
        student_sessions: Dict[str, List[TimetableEntry]] = {}
        for entry in day_entries:
            if entry.person_id not in student_sessions:
                student_sessions[entry.person_id] = []
            student_sessions[entry.person_id].append(entry)
        
        # Build expected students
        expected_students = []
        all_student_ids = set(student_sessions.keys())
        
        # Add enrolled students who might not have sessions today
        if self.enrollment_person_ids:
            all_student_ids.update(self.enrollment_person_ids)
        
        for student_id in sorted(all_student_ids):
            sessions = student_sessions.get(student_id, [])
            person_name = None
            if sessions:
                person_name = sessions[0].person_name
            
            # Determine status
            if calendar_day.is_holiday:
                status = ExpectedStatus.HOLIDAY
            elif not sessions:
                status = ExpectedStatus.NOT_SCHEDULED
            else:
                # Check for exceptions on sessions
                has_exception = False
                has_later_start = False
                has_earlier_departure = False
                has_cancelled = False
                
                for session in sessions:
                    exc = self.calendar_engine.get_applicable_exception(
                        target_date, session.session_id, student_id, session.class_name
                    )
                    if exc:
                        has_exception = True
                        if exc.exception_type == ExceptionType.CANCELLED:
                            has_cancelled = True
                        elif exc.exception_type == ExceptionType.LATE_START:
                            has_later_start = True
                        elif exc.exception_type == ExceptionType.EARLY_DISMISSAL:
                            has_earlier_departure = True
                
                if has_cancelled:
                    status = ExpectedStatus.CANCELLED
                elif has_later_start:
                    status = ExpectedStatus.LATER_START
                elif has_earlier_departure:
                    status = ExpectedStatus.EARLIER_DEPARTURE
                elif has_exception:
                    status = ExpectedStatus.EXCEPTION
                else:
                    status = ExpectedStatus.SCHEDULED
                
                # If day is exception but no session-specific exceptions, keep as SCHEDULED
                if calendar_day.is_exception and not has_exception:
                    status = ExpectedStatus.SCHEDULED
            
            # Build expected sessions with resolved times
            expected_sessions = []
            exceptions = []
            
            for entry in sessions:
                exc = self.calendar_engine.get_applicable_exception(
                    target_date, entry.session_id, student_id, entry.class_name
                )
                
                if exc:
                    exceptions.append(exc)
                
                # Resolve times with exceptions
                resolved_times = self.calendar_engine.resolve_session_times(
                    target_date=target_date,
                    session_id=entry.session_id,
                    base_entry_time=entry.entry_time,
                    base_exit_time=entry.exit_time,
                    base_entry_window_start=entry.entry_window_start,
                    base_entry_window_end=entry.entry_window_end,
                    base_late_tolerance=entry.late_tolerance,
                    base_exit_window_start=entry.exit_window_start,
                    base_exit_window_end=entry.exit_window_end,
                    student_id=student_id,
                    class_name=entry.class_name,
                )
                
                expected_session = ExpectedSession(
                    session_id=entry.session_id,
                    class_name=entry.class_name,
                    session_type=entry.session_type,
                    entry_time=resolved_times[0],
                    exit_time=resolved_times[1],
                    entry_window_start=resolved_times[2],
                    entry_window_end=resolved_times[3],
                    late_tolerance=resolved_times[4],
                    exit_window_start=resolved_times[5],
                    exit_window_end=resolved_times[6],
                    exception=exc,
                )
                expected_sessions.append(expected_session)
            
            expected_student = ExpectedStudent(
                student_id=student_id,
                person_name=person_name,
                date=target_date,
                session_day=session_day,
                status=status,
                sessions=expected_sessions,
                exceptions=exceptions,
            )
            expected_students.append(expected_student)
        
        # Count statistics
        total_scheduled = sum(1 for s in expected_students if s.is_expected)
        total_not_scheduled = sum(1 for s in expected_students if not s.is_expected)
        
        return DailyExpectedResult(
            date=target_date,
            session_day=session_day,
            day_type=calendar_day.day_type,
            expected_students=expected_students,
            total_scheduled=total_scheduled,
            total_not_scheduled=total_not_scheduled,
            calendar_day=calendar_day,
        )
    
    def get_expected_student(self, target_date: date, student_id: str) -> Optional[ExpectedStudent]:
        """Get expected student for a specific date and student_id."""
        result = self.resolve_for_date(target_date)
        for student in result.expected_students:
            if student.student_id == student_id:
                return student
        return None
    
    def is_student_expected_at(
        self,
        target_date: date,
        student_id: str,
        timestamp: float,
    ) -> Tuple[bool, Optional[ExpectedSession], Optional[str]]:
        """
        Check if a student is expected to be present at a specific timestamp.
        
        Returns:
            (is_expected, session, reason)
        """
        student = self.get_expected_student(target_date, student_id)
        if not student or not student.is_expected:
            return False, None, f"Student {student_id} not expected on {target_date}"
        
        # Check each session
        for session in student.sessions:
            if session.is_cancelled:
                continue
            
            # Check if timestamp falls within session window
            if session.entry_window_start <= timestamp <= session.exit_window_end:
                return True, session, "within_session_window"
            
            # Check if timestamp is before entry window (early)
            if timestamp < session.entry_window_start:
                return True, session, "before_entry_window"
            
            # Check if timestamp is after exit window (late departure)
            if timestamp > session.exit_window_end:
                return True, session, "after_exit_window"
        
        return False, None, "no_matching_session"
    
    def get_session_context(
        self,
        target_date: date,
        student_id: str,
        timestamp_sfm: int,  # seconds from midnight
    ) -> Optional[SessionContext]:
        """
        Get the SessionContext for a student at a specific timestamp.
        
        This is the Phase 37D canonical method for semantic context resolution.
        
        Args:
            target_date: The date to check
            student_id: Student identifier
            timestamp_sfm: Timestamp in seconds from midnight
            
        Returns:
            SessionContext if found, None otherwise
        """
        student = self.get_expected_student(target_date, student_id)
        if not student or not student.is_expected:
            return None
        
        # Find the session that contains this timestamp
        for session in student.sessions:
            if session.is_cancelled:
                continue
            
            if session.entry_window_start <= timestamp_sfm <= session.exit_window_end:
                # Find the original timetable entry to get semantic fields
                day_entries = [
                    entry for entry in self.timetable.entries
                    if entry.person_id == student_id and entry.day == student.session_day
                ]
                
                for entry in day_entries:
                    if entry.session_id == session.session_id:
                        # Determine period (simplified)
                        period = 1
                        return create_session_context(entry, target_date, period)
        
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_daily_resolver(
    timetable: Timetable,
    calendar_engine: CalendarEngine,
    enrollment_person_ids: Optional[List[str]] = None,
) -> DailyExpectedResolver:
    """Create a DailyExpectedResolver."""
    return DailyExpectedResolver(timetable, calendar_engine, enrollment_person_ids)


def create_identity_resolver(
    enrollment_person_ids: List[str],
    enrollment_embeddings: Optional[Any] = None,
    enrollment_metadata: Optional[Dict[str, Any]] = None,
) -> IdentityResolver:
    """Create an IdentityResolver."""
    return IdentityResolver(enrollment_person_ids, enrollment_embeddings, enrollment_metadata)


def create_day_resolver(calendar_engine: CalendarEngine) -> DayResolver:
    """Create a DayResolver."""
    return DayResolver(calendar_engine)