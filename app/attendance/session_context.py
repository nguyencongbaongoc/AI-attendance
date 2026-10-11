"""
Phase 37D — Session Context.

Canonical semantic context for attendance policy evaluation.
Combines timestamp, class, student_id, and timetable into a deterministic context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.attendance.timetable import TimetableEntry, SessionDay, SessionType


@dataclass(frozen=True)
class SessionContext:
    """
    Canonical session context for policy evaluation.
    
    Conceptually:
        timestamp + class + student_id + timetable → SessionContext
    
    Same timestamp/student/timetable → same semantic context (deterministic).
    """
    # Date and day
    date: date
    day: SessionDay
    
    # Class and student
    class_id: str
    student_id: str
    
    # Period and timing
    period: int
    subject: Optional[str] = None
    session_type: SessionType = SessionType.FULL_DAY
    start_time: int = 0  # seconds from midnight
    end_time: int = 0    # seconds from midnight
    
    # Semantic properties
    expected_location: Optional[str] = None
    outside_allowed: bool = False
    location: Optional[str] = None
    
    # Timetable reference
    timetable_entry_id: Optional[str] = None
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.class_id:
            raise ValueError("class_id is required")
        if not self.student_id:
            raise ValueError("student_id is required")
        if self.period < 0:
            raise ValueError("period must be >= 0")
        if self.start_time < 0:
            raise ValueError("start_time must be >= 0")
        if self.end_time < 0:
            raise ValueError("end_time must be >= 0")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be < end_time")
    
    @property
    def is_classroom(self) -> bool:
        """Check if this is a CLASSROOM session (outside not allowed by default)."""
        return self.session_type == SessionType.CLASSROOM
    
    @property
    def is_break(self) -> bool:
        """Check if this is a BREAK session (outside allowed)."""
        return self.session_type == SessionType.BREAK
    
    @property
    def is_outside_lesson(self) -> bool:
        """Check if this is an OUTSIDE_LESSON session (outside allowed)."""
        return self.session_type == SessionType.OUTSIDE_LESSON
    
    @property
    def is_lab(self) -> bool:
        """Check if this is a LAB session (configurable outside_allowed)."""
        return self.session_type == SessionType.LAB
    
    @property
    def is_other(self) -> bool:
        """Check if this is an OTHER session (safe default: outside not allowed)."""
        return self.session_type == SessionType.OTHER
    
    @property
    def semantic_state(self) -> str:
        """
        Get the semantic state for policy evaluation.
        
        Returns:
            "EXPECTED_INSIDE" - student should be in classroom
            "EXPECTED_OUTSIDE" - student is allowed/expected outside
        """
        if self.outside_allowed:
            return "EXPECTED_OUTSIDE"
        return "EXPECTED_INSIDE"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "date": self.date.isoformat(),
            "day": self.day.value,
            "class_id": self.class_id,
            "student_id": self.student_id,
            "period": self.period,
            "subject": self.subject,
            "session_type": self.session_type.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "expected_location": self.expected_location,
            "outside_allowed": self.outside_allowed,
            "location": self.location,
            "timetable_entry_id": self.timetable_entry_id,
            "semantic_state": self.semantic_state,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        """Deserialize from dictionary."""
        return cls(
            date=date.fromisoformat(data["date"]),
            day=SessionDay(data["day"]),
            class_id=data["class_id"],
            student_id=data["student_id"],
            period=data["period"],
            subject=data.get("subject"),
            session_type=SessionType(data.get("session_type", "full_day")),
            start_time=data["start_time"],
            end_time=data["end_time"],
            expected_location=data.get("expected_location"),
            outside_allowed=data.get("outside_allowed", False),
            location=data.get("location"),
            timetable_entry_id=data.get("timetable_entry_id"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "SessionContext":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


def create_session_context(
    timetable_entry: TimetableEntry,
    target_date: date,
    period: int,
) -> SessionContext:
    """
    Create a SessionContext from a TimetableEntry.
    
    Args:
        timetable_entry: The timetable entry
        target_date: The date for this session
        period: The period number
        
    Returns:
        SessionContext with all semantic fields populated
    """
    return SessionContext(
        date=target_date,
        day=timetable_entry.day,
        class_id=timetable_entry.class_name or "",
        student_id=timetable_entry.person_id,
        period=period,
        subject=timetable_entry.subject,
        session_type=timetable_entry.session_type,
        start_time=timetable_entry.entry_time,
        end_time=timetable_entry.exit_time,
        expected_location=timetable_entry.expected_location,
        outside_allowed=timetable_entry.outside_allowed,
        location=timetable_entry.location,
        timetable_entry_id=timetable_entry.entry_id,
    )


def get_session_context_for_timestamp(
    timetable_entries: List[TimetableEntry],
    target_date: date,
    student_id: str,
    timestamp_sfm: int,  # seconds from midnight
) -> Optional[SessionContext]:
    """
    Get the SessionContext for a specific timestamp.
    
    Finds the timetable entry that contains the timestamp.
    
    Args:
        timetable_entries: All timetable entries for the student
        target_date: The date to check
        student_id: Student identifier
        timestamp_sfm: Timestamp in seconds from midnight
        
    Returns:
        SessionContext if found, None otherwise
    """
    # Filter entries for this student and date
    day = target_date.weekday()
    day_map = {
        0: SessionDay.MONDAY,
        1: SessionDay.TUESDAY,
        2: SessionDay.WEDNESDAY,
        3: SessionDay.THURSDAY,
        4: SessionDay.FRIDAY,
        5: SessionDay.SATURDAY,
        6: SessionDay.SUNDAY,
    }
    session_day = day_map[day]
    
    student_entries = [
        e for e in timetable_entries
        if e.person_id == student_id and e.day == session_day
    ]
    
    # Find the entry that contains this timestamp
    for entry in student_entries:
        if entry.entry_window_start <= timestamp_sfm <= entry.exit_window_end:
            # Determine period (simplified - could be enhanced)
            period = 1  # Would need period mapping
            return create_session_context(entry, target_date, period)
    
    return None