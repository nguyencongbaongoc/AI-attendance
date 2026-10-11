"""
Phase 37A — Calendar and Exception Foundation.

Minimum calendar abstraction required by the existing timetable contract.
Supports school days, holidays, exceptions, and student/class schedule overrides.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytz

from app.attendance.timetable import SessionDay

logger = logging.getLogger(__name__)


# =============================================================================
# CALENDAR TYPES
# =============================================================================

class DayType(str, Enum):
    """Type of day in the calendar."""
    SCHOOL_DAY = "school_day"
    HOLIDAY = "holiday"
    EXCEPTION = "exception"  # Special schedule day


class ExceptionType(str, Enum):
    """Type of schedule exception."""
    CANCELLED = "cancelled"           # Session cancelled
    RESCHEDULED = "rescheduled"       # Session moved to different time
    EARLY_DISMISSAL = "early_dismissal"  # Early exit
    LATE_START = "late_start"         # Late entry
    CUSTOM = "custom"                 # Custom schedule


@dataclass(frozen=True)
class CalendarDay:
    """Represents a single day in the calendar."""
    date: date
    day_type: DayType = DayType.SCHOOL_DAY
    description: str = ""
    exceptions: List["ScheduleException"] = field(default_factory=list)
    
    @property
    def is_school_day(self) -> bool:
        return self.day_type == DayType.SCHOOL_DAY
    
    @property
    def is_holiday(self) -> bool:
        return self.day_type == DayType.HOLIDAY
    
    @property
    def is_exception(self) -> bool:
        return self.day_type == DayType.EXCEPTION
    
    def get_session_day(self) -> SessionDay:
        """Get SessionDay enum from date."""
        weekday_map = {
            0: SessionDay.MONDAY,
            1: SessionDay.TUESDAY,
            2: SessionDay.WEDNESDAY,
            3: SessionDay.THURSDAY,
            4: SessionDay.FRIDAY,
            5: SessionDay.SATURDAY,
            6: SessionDay.SUNDAY,
        }
        return weekday_map[self.date.weekday()]


@dataclass(frozen=True)
class ScheduleException:
    """Schedule exception for a specific session on a specific day."""
    exception_id: str
    date: date
    session_id: str
    exception_type: ExceptionType
    description: str = ""
    
    # For rescheduled sessions
    new_entry_time: Optional[int] = None      # Seconds from midnight
    new_exit_time: Optional[int] = None       # Seconds from midnight
    new_entry_window_start: Optional[int] = None
    new_entry_window_end: Optional[int] = None
    new_late_tolerance: Optional[int] = None
    new_exit_window_start: Optional[int] = None
    new_exit_window_end: Optional[int] = None
    
    # For student/class specific overrides
    student_id: Optional[str] = None
    class_name: Optional[str] = None
    
    def applies_to(self, student_id: Optional[str], class_name: Optional[str], session_id: str) -> bool:
        """Check if this exception applies to the given student/class/session."""
        if self.session_id != session_id:
            return False
        if self.student_id is not None and self.student_id != student_id:
            return False
        if self.class_name is not None and self.class_name != class_name:
            return False
        return True


# =============================================================================
# CALENDAR CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class CalendarConfig:
    """Configuration for the calendar."""
    # Timezone for date/day calculations
    timezone: str = "Asia/Bangkok"
    
    # Default school days (Monday-Friday)
    default_school_days: Tuple[int, ...] = (0, 1, 2, 3, 4)  # Mon-Fri
    
    # Holiday dates (YYYY-MM-DD format)
    holidays: Tuple[str, ...] = ()
    
    # Exception definitions
    exceptions: Tuple[Dict[str, Any], ...] = ()
    
    def __post_init__(self):
        # Validate timezone
        try:
            pytz.timezone(self.timezone)
        except pytz.UnknownTimeZoneError:
            raise ValueError(f"Unknown timezone: {self.timezone}")
        
        # Validate holidays format
        for holiday in self.holidays:
            try:
                datetime.strptime(holiday, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(f"Invalid holiday date format: {holiday}. Use YYYY-MM-DD")


DEFAULT_CALENDAR_CONFIG = CalendarConfig()


# =============================================================================
# CALENDAR ENGINE
# =============================================================================

class CalendarEngine:
    """
    Calendar engine for determining day types and schedule exceptions.
    
    Provides:
    - Day type lookup (school day, holiday, exception)
    - Schedule exception resolution
    - Timezone-aware date handling
    """
    
    def __init__(self, config: CalendarConfig = DEFAULT_CALENDAR_CONFIG):
        self.config = config
        self.timezone = pytz.timezone(config.timezone)
        self._calendar_cache: Dict[date, CalendarDay] = {}
        self._exceptions_by_date: Dict[date, List[ScheduleException]] = {}
        self._initialize_calendar()
    
    def _initialize_calendar(self) -> None:
        """Initialize calendar with holidays and exceptions."""
        # Parse holidays
        for holiday_str in self.config.holidays:
            holiday_date = datetime.strptime(holiday_str, "%Y-%m-%d").date()
            self._calendar_cache[holiday_date] = CalendarDay(
                date=holiday_date,
                day_type=DayType.HOLIDAY,
                description=f"Holiday: {holiday_str}"
            )
        
        # Parse exceptions
        for exc_data in self.config.exceptions:
            exc = self._parse_exception(exc_data)
            if exc.date not in self._exceptions_by_date:
                self._exceptions_by_date[exc.date] = []
            self._exceptions_by_date[exc.date].append(exc)
            
            # Mark day as exception type if not already holiday
            if exc.date not in self._calendar_cache:
                self._calendar_cache[exc.date] = CalendarDay(
                    date=exc.date,
                    day_type=DayType.EXCEPTION,
                    description=f"Exception: {exc.description}",
                    exceptions=[exc]
                )
            else:
                cal_day = self._calendar_cache[exc.date]
                if cal_day.day_type != DayType.HOLIDAY:
                    # Update with exception
                    self._calendar_cache[exc.date] = CalendarDay(
                        date=cal_day.date,
                        day_type=DayType.EXCEPTION,
                        description=cal_day.description,
                        exceptions=cal_day.exceptions + [exc]
                    )
    
    def _parse_exception(self, data: Dict[str, Any]) -> ScheduleException:
        """Parse exception data from config."""
        exc_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        exception_type = ExceptionType(data.get("exception_type", "custom"))
        
        return ScheduleException(
            exception_id=data.get("exception_id", f"EXC-{exc_date.isoformat()}"),
            date=exc_date,
            session_id=data["session_id"],
            exception_type=exception_type,
            description=data.get("description", ""),
            new_entry_time=data.get("new_entry_time"),
            new_exit_time=data.get("new_exit_time"),
            new_entry_window_start=data.get("new_entry_window_start"),
            new_entry_window_end=data.get("new_entry_window_end"),
            new_late_tolerance=data.get("new_late_tolerance"),
            new_exit_window_start=data.get("new_exit_window_start"),
            new_exit_window_end=data.get("new_exit_window_end"),
            student_id=data.get("student_id"),
            class_name=data.get("class_name"),
        )
    
    def get_day(self, target_date: date) -> CalendarDay:
        """Get calendar day for a specific date."""
        if target_date in self._calendar_cache:
            return self._calendar_cache[target_date]
        
        # Check if default school day
        if target_date.weekday() in self.config.default_school_days:
            return CalendarDay(date=target_date, day_type=DayType.SCHOOL_DAY)
        
        # Weekend or non-school day
        return CalendarDay(date=target_date, day_type=DayType.HOLIDAY, description="Weekend")
    
    def is_school_day(self, target_date: date) -> bool:
        """Check if a date is a school day."""
        return self.get_day(target_date).is_school_day
    
    def get_exceptions_for_date(self, target_date: date) -> List[ScheduleException]:
        """Get all exceptions for a specific date."""
        return self._exceptions_by_date.get(target_date, [])
    
    def get_applicable_exception(
        self,
        target_date: date,
        session_id: str,
        student_id: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> Optional[ScheduleException]:
        """Get the applicable exception for a session on a date."""
        exceptions = self.get_exceptions_for_date(target_date)
        
        for exc in exceptions:
            if exc.applies_to(student_id, class_name, session_id):
                return exc
        
        return None
    
    def resolve_session_times(
        self,
        target_date: date,
        session_id: str,
        base_entry_time: int,
        base_exit_time: int,
        base_entry_window_start: int,
        base_entry_window_end: int,
        base_late_tolerance: int,
        base_exit_window_start: int,
        base_exit_window_end: int,
        student_id: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> Tuple[int, int, int, int, int, int, int]:
        """
        Resolve session times for a specific date, applying exceptions.
        
        Returns:
            (entry_time, exit_time, entry_window_start, entry_window_end, 
             late_tolerance, exit_window_start, exit_window_end)
        """
        exc = self.get_applicable_exception(target_date, session_id, student_id, class_name)
        
        if exc is None:
            return (
                base_entry_time, base_exit_time,
                base_entry_window_start, base_entry_window_end,
                base_late_tolerance,
                base_exit_window_start, base_exit_window_end
            )
        
        # Apply exception
        if exc.exception_type == ExceptionType.CANCELLED:
            # Return zeros to indicate cancelled
            return (0, 0, 0, 0, 0, 0, 0)
        
        entry_time = exc.new_entry_time if exc.new_entry_time is not None else base_entry_time
        exit_time = exc.new_exit_time if exc.new_exit_time is not None else base_exit_time
        entry_window_start = exc.new_entry_window_start if exc.new_entry_window_start is not None else base_entry_window_start
        entry_window_end = exc.new_entry_window_end if exc.new_entry_window_end is not None else base_entry_window_end
        late_tolerance = exc.new_late_tolerance if exc.new_late_tolerance is not None else base_late_tolerance
        exit_window_start = exc.new_exit_window_start if exc.new_exit_window_start is not None else base_exit_window_start
        exit_window_end = exc.new_exit_window_end if exc.new_exit_window_end is not None else base_exit_window_end
        
        return (
            entry_time, exit_time,
            entry_window_start, entry_window_end,
            late_tolerance,
            exit_window_start, exit_window_end
        )
    
    def get_date_from_timestamp(self, timestamp: float) -> date:
        """Convert UTC timestamp to local date using configured timezone."""
        dt_utc = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
        dt_local = dt_utc.astimezone(self.timezone)
        return dt_local.date()
    
    def get_session_day_from_timestamp(self, timestamp: float) -> SessionDay:
        """Get SessionDay from UTC timestamp using configured timezone."""
        target_date = self.get_date_from_timestamp(timestamp)
        return target_date.weekday()  # This returns 0-6, need to map
    
    def get_session_day_enum_from_timestamp(self, timestamp: float) -> SessionDay:
        """Get SessionDay enum from UTC timestamp using configured timezone."""
        target_date = self.get_date_from_timestamp(timestamp)
        weekday_map = {
            0: SessionDay.MONDAY,
            1: SessionDay.TUESDAY,
            2: SessionDay.WEDNESDAY,
            3: SessionDay.THURSDAY,
            4: SessionDay.FRIDAY,
            5: SessionDay.SATURDAY,
            6: SessionDay.SUNDAY,
        }
        return weekday_map[target_date.weekday()]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_calendar_engine(
    timezone: str = "Asia/Bangkok",
    holidays: Optional[List[str]] = None,
    exceptions: Optional[List[Dict[str, Any]]] = None,
) -> CalendarEngine:
    """Create a CalendarEngine with custom configuration."""
    config = CalendarConfig(
        timezone=timezone,
        holidays=tuple(holidays) if holidays else (),
        exceptions=tuple(exceptions) if exceptions else (),
    )
    return CalendarEngine(config)


def create_sample_calendar_config(output_path: str) -> None:
    """Create a sample calendar configuration JSON file."""
    import json
    
    config = {
        "timezone": "Asia/Bangkok",
        "default_school_days": [0, 1, 2, 3, 4],  # Mon-Fri
        "holidays": [
            "2026-01-01",  # New Year
            "2026-12-25",  # Christmas
        ],
        "exceptions": [
            {
                "exception_id": "EXC-2026-02-14",
                "date": "2026-02-14",
                "session_id": "MATH101_MON",
                "exception_type": "late_start",
                "description": "Late start due to assembly",
                "new_entry_time": 28800,  # 08:00:00
                "new_entry_window_start": 28500,  # 07:55:00
                "new_entry_window_end": 29100,    # 08:05:00
                "student_id": "HS001",
            },
            {
                "exception_id": "EXC-2026-03-01",
                "date": "2026-03-01",
                "session_id": "PHYS101_MON",
                "exception_type": "early_dismissal",
                "description": "Early dismissal for staff meeting",
                "new_exit_time": 43200,  # 12:00:00
                "new_exit_window_start": 42900,  # 11:55:00
                "new_exit_window_end": 43500,    # 12:05:00
            },
        ],
    }
    
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"Sample calendar config created at {output_path}")