"""
Phase 26 — Timetable/Schedule Contract.

Canonical timetable for attendance decision making.
Defines entry/exit times, attendance windows, and session boundaries.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionDay(str, Enum):
    """Day of week for session."""
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class SessionType(str, Enum):
    """Type of session - semantic session types for Phase 37D."""
    CLASSROOM = "classroom"
    BREAK = "break"
    OUTSIDE_LESSON = "outside_lesson"
    LAB = "lab"
    OTHER = "other"
    # Legacy compatibility
    MORNING = "morning"
    AFTERNOON = "afternoon"
    FULL_DAY = "full_day"
    EVENING = "evening"


class AttendanceState(str, Enum):
    """Attendance state for decision making."""
    UNKNOWN = "unknown"
    EXPECTED = "expected"
    PRESENT = "present"
    LATE = "late"
    LEFT = "left"
    ABSENT = "absent"


@dataclass(frozen=True)
class TimetableEntry:
    """
    Single entry in the timetable.
    
    Defines when a person/student is expected to be present.
    Phase 37D adds semantic fields for session context.
    """
    # Entry identification
    entry_id: str
    
    # Person/student reference
    person_id: str
    session_id: str
    
    # Session details
    session_type: SessionType = SessionType.FULL_DAY
    day: SessionDay = SessionDay.MONDAY
    class_name: Optional[str] = None
    person_name: Optional[str] = None
    
    # Semantic fields (Phase 37D)
    subject: Optional[str] = None
    location: Optional[str] = None
    expected_location: Optional[str] = None
    outside_allowed: bool = False
    
    # Time boundaries (in seconds from midnight)
    entry_time: int = 0  # Expected entry time
    exit_time: int = 0   # Expected exit time
    
    # Attendance window (in seconds)
    # Entry is considered valid within this window
    entry_window_start: int = 0
    entry_window_end: int = 0
    
    # Late tolerance (in seconds)
    # After entry_time, how late is acceptable
    late_tolerance: int = 0
    
    # Exit window (in seconds)
    # After exit_time, how long to allow for exit
    exit_window_start: int = 0
    exit_window_end: int = 0
    
    # Versioning
    timetable_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.entry_id:
            raise ValueError("entry_id is required")
        if not self.person_id:
            raise ValueError("person_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.entry_time < 0:
            raise ValueError("entry_time must be >= 0")
        if self.exit_time < 0:
            raise ValueError("exit_time must be >= 0")
        if self.entry_window_start < 0:
            raise ValueError("entry_window_start must be >= 0")
        if self.entry_window_end < 0:
            raise ValueError("entry_window_end must be >= 0")
        if self.late_tolerance < 0:
            raise ValueError("late_tolerance must be >= 0")
        if self.exit_window_start < 0:
            raise ValueError("exit_window_start must be >= 0")
        if self.exit_window_end < 0:
            raise ValueError("exit_window_end must be >= 0")
        if self.entry_window_start > self.entry_window_end:
            raise ValueError("entry_window_start must be <= entry_window_end")
        if self.exit_window_start > self.exit_window_end:
            raise ValueError("exit_window_start must be <= exit_window_end")
    
    @property
    def entry_time_dt(self) -> time:
        """Entry time as datetime.time."""
        return time(hour=self.entry_time // 3600, minute=(self.entry_time // 60) % 60, second=self.entry_time % 60)
    
    @property
    def exit_time_dt(self) -> time:
        """Exit time as datetime.time."""
        return time(hour=self.exit_time // 3600, minute=(self.exit_time // 60) % 60, second=self.exit_time % 60)
    
    @property
    def entry_window_start_dt(self) -> time:
        """Entry window start as datetime.time."""
        return time(hour=self.entry_window_start // 3600, minute=(self.entry_window_start // 60) % 60, second=self.entry_window_start % 60)
    
    @property
    def entry_window_end_dt(self) -> time:
        """Entry window end as datetime.time."""
        return time(hour=self.entry_window_end // 3600, minute=(self.entry_window_end // 60) % 60, second=self.entry_window_end % 60)
    
    @property
    def exit_window_start_dt(self) -> time:
        """Exit window start as datetime.time."""
        return time(hour=self.exit_window_start // 3600, minute=(self.exit_window_start // 60) % 60, second=self.exit_window_start % 60)
    
    @property
    def exit_window_end_dt(self) -> time:
        """Exit window end as datetime.time."""
        return time(hour=self.exit_window_end // 3600, minute=(self.exit_window_end // 60) % 60, second=self.exit_window_end % 60)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "entry_id": self.entry_id,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "session_id": self.session_id,
            "session_type": self.session_type.value,
            "day": self.day.value,
            "class_name": self.class_name,
            # Semantic fields (Phase 37D)
            "subject": self.subject,
            "location": self.location,
            "expected_location": self.expected_location,
            "outside_allowed": self.outside_allowed,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_window_start": self.entry_window_start,
            "entry_window_end": self.entry_window_end,
            "late_tolerance": self.late_tolerance,
            "exit_window_start": self.exit_window_start,
            "exit_window_end": self.exit_window_end,
            "timetable_version": self.timetable_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimetableEntry":
        """Deserialize from dictionary."""
        return cls(
            entry_id=data["entry_id"],
            person_id=data["person_id"],
            person_name=data.get("person_name"),
            session_id=data["session_id"],
            session_type=SessionType(data.get("session_type", "full_day")),
            day=SessionDay(data.get("day", "monday")),
            class_name=data.get("class_name"),
            # Semantic fields (Phase 37D)
            subject=data.get("subject"),
            location=data.get("location"),
            expected_location=data.get("expected_location"),
            outside_allowed=data.get("outside_allowed", False),
            entry_time=data["entry_time"],
            exit_time=data["exit_time"],
            entry_window_start=data["entry_window_start"],
            entry_window_end=data["entry_window_end"],
            late_tolerance=data.get("late_tolerance", 0),
            exit_window_start=data.get("exit_window_start", 0),
            exit_window_end=data.get("exit_window_end", 0),
            timetable_version=data.get("timetable_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "TimetableEntry":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class Timetable:
    """
    Complete timetable for attendance decision making.
    
    Contains all entries for a specific timetable version.
    """
    # Timetable identification
    timetable_id: str
    
    # Versioning
    timetable_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Entries
    entries: List[TimetableEntry] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate required fields."""
        if not self.timetable_id:
            raise ValueError("timetable_id is required")
        if self.timetable_version != "1.0":
            raise ValueError(f"Unsupported timetable_version: {self.timetable_version}")
    
    def get_entry(self, person_id: str, day: SessionDay) -> Optional[TimetableEntry]:
        """
        Get timetable entry for a person on a specific day.
        
        Args:
            person_id: Person/student ID
            day: Day of week
            
        Returns:
            TimetableEntry if found, None otherwise
        """
        for entry in self.entries:
            if entry.person_id == person_id and entry.day == day:
                return entry
        return None
    
    def get_entries_for_session(self, session_id: str) -> List[TimetableEntry]:
        """
        Get all entries for a specific session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of TimetableEntry objects
        """
        return [entry for entry in self.entries if entry.session_id == session_id]
    
    def get_entries_for_person(self, person_id: str) -> List[TimetableEntry]:
        """
        Get all entries for a specific person.
        
        Args:
            person_id: Person/student ID
            
        Returns:
            List of TimetableEntry objects
        """
        return [entry for entry in self.entries if entry.person_id == person_id]
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timetable_id": self.timetable_id,
            "timetable_version": self.timetable_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Timetable":
        """Deserialize from dictionary."""
        return cls(
            timetable_id=data["timetable_id"],
            timetable_version=data.get("timetable_version", "1.0"),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z"),
            entries=[TimetableEntry.from_dict(entry) for entry in data.get("entries", [])],
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "Timetable":
        """Deserialize from JSON string."""
        import json
        return cls.from_dict(json.loads(json_str))


def generate_timetable_id(timetable_version: str = "1.0") -> str:
    """
    Generate a stable, deterministic timetable ID.
    
    Args:
        timetable_version: Version of the timetable
        
    Returns:
        Timetable ID string
    """
    content = f"TTB:{timetable_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"TTB-v{timetable_version}-{hash_suffix}"


def validate_timetable_entry(entry: TimetableEntry) -> Optional[str]:
    """
    Validate a TimetableEntry.
    
    Args:
        entry: TimetableEntry to validate
        
    Returns:
        None if valid, error message if invalid
    """
    if not entry.entry_id:
        return "entry_id is required"
    if not entry.person_id:
        return "person_id is required"
    if not entry.session_id:
        return "session_id is required"
    if entry.entry_time < 0:
        return "entry_time must be >= 0"
    if entry.exit_time < 0:
        return "exit_time must be >= 0"
    if entry.entry_window_start < 0:
        return "entry_window_start must be >= 0"
    if entry.entry_window_end < 0:
        return "entry_window_end must be >= 0"
    if entry.late_tolerance < 0:
        return "late_tolerance must be >= 0"
    if entry.exit_window_start < 0:
        return "exit_window_start must be >= 0"
    if entry.exit_window_end < 0:
        return "exit_window_end must be >= 0"
    if entry.entry_window_start > entry.entry_window_end:
        return "entry_window_start must be <= entry_window_end"
    if entry.exit_window_start > entry.exit_window_end:
        return "exit_window_start must be <= exit_window_end"
    return None