"""
Unit tests for Phase 26 Attendance Timetable.
"""

import pytest
from datetime import datetime
from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    SessionType,
    AttendanceState,
    generate_timetable_id,
    validate_timetable_entry,
)


class TestTimetableEntry:
    """Test TimetableEntry class."""
    
    def test_create_entry(self):
        """Test creating a basic timetable entry."""
        entry = TimetableEntry(
            entry_id="entry-1",
            person_id="person-123",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36600,  # 10:10 AM
            late_tolerance=600,  # 10 minutes
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        assert entry.entry_id == "entry-1"
        assert entry.person_id == "person-123"
        assert entry.session_id == "session-1"
        assert entry.day == SessionDay.MONDAY
        assert entry.entry_time == 36000
        assert entry.exit_time == 72000
        assert entry.entry_window_start == 35400
        assert entry.entry_window_end == 36600
        assert entry.late_tolerance == 600
        assert entry.exit_window_start == 71400
        assert entry.exit_window_end == 72600
    
    def test_entry_properties(self):
        """Test timetable entry properties."""
        entry = TimetableEntry(
            entry_id="entry-2",
            person_id="person-456",
            session_id="session-2",
            day=SessionDay.TUESDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        assert entry.entry_time_dt.hour == 10
        assert entry.entry_time_dt.minute == 0
        assert entry.entry_time_dt.second == 0
        assert entry.exit_time_dt.hour == 20
        assert entry.exit_time_dt.minute == 0
        assert entry.exit_time_dt.second == 0
    
    def test_entry_validation(self):
        """Test timetable entry validation."""
        # Valid entry
        entry = TimetableEntry(
            entry_id="entry-3",
            person_id="person-789",
            session_id="session-3",
            day=SessionDay.WEDNESDAY,
            entry_time=36000,
            exit_time=72000,
            entry_window_start=35400,
            entry_window_end=36600,
            late_tolerance=600,
            exit_window_start=71400,
            exit_window_end=72600,
        )
        assert validate_timetable_entry(entry) is None
        
        # Invalid entry (missing entry_id) - validation happens in __post_init__
        with pytest.raises(ValueError, match="entry_id is required"):
            TimetableEntry(
                entry_id="",
                person_id="person-1",
                session_id="session-1",
                day=SessionDay.MONDAY,
                entry_time=36000,
                exit_time=72000,
            )
        
        # Invalid entry (missing person_id) - validation happens in __post_init__
        with pytest.raises(ValueError, match="person_id is required"):
            TimetableEntry(
                entry_id="entry-4",
                person_id="",
                session_id="session-1",
                day=SessionDay.MONDAY,
                entry_time=36000,
                exit_time=72000,
            )
        
        # Invalid entry (missing session_id) - validation happens in __post_init__
        with pytest.raises(ValueError, match="session_id is required"):
            TimetableEntry(
                entry_id="entry-5",
                person_id="person-1",
                session_id="",
                day=SessionDay.MONDAY,
                entry_time=36000,
                exit_time=72000,
            )
        
        # Invalid entry (negative entry_time) - validation happens in __post_init__
        with pytest.raises(ValueError, match="entry_time must be >= 0"):
            TimetableEntry(
                entry_id="entry-6",
                person_id="person-1",
                session_id="session-1",
                day=SessionDay.MONDAY,
                entry_time=-1,
                exit_time=72000,
            )
        
        # Invalid entry (entry_window_start > entry_window_end) - validation happens in __post_init__
        with pytest.raises(ValueError, match="entry_window_start must be <= entry_window_end"):
            TimetableEntry(
                entry_id="entry-7",
                person_id="person-1",
                session_id="session-1",
                day=SessionDay.MONDAY,
                entry_time=36000,
                exit_time=72000,
                entry_window_start=36600,
                entry_window_end=35400,
            )
    
    def test_entry_serialization(self):
        """Test timetable entry serialization/deserialization."""
        entry = TimetableEntry(
            entry_id="entry-8",
            person_id="person-123",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
            entry_window_start=35400,
            entry_window_end=36600,
            late_tolerance=600,
            exit_window_start=71400,
            exit_window_end=72600,
            class_name="Class A",
            session_type=SessionType.MORNING,
        )
        
        # Serialize to dict
        entry_dict = entry.to_dict()
        assert entry_dict["entry_id"] == "entry-8"
        assert entry_dict["person_id"] == "person-123"
        assert entry_dict["session_id"] == "session-1"
        assert entry_dict["day"] == "monday"
        assert entry_dict["entry_time"] == 36000
        assert entry_dict["exit_time"] == 72000
        assert entry_dict["entry_window_start"] == 35400
        assert entry_dict["entry_window_end"] == 36600
        assert entry_dict["late_tolerance"] == 600
        assert entry_dict["exit_window_start"] == 71400
        assert entry_dict["exit_window_end"] == 72600
        assert entry_dict["class_name"] == "Class A"
        assert entry_dict["session_type"] == "morning"
        
        # Deserialize from dict
        entry_restored = TimetableEntry.from_dict(entry_dict)
        assert entry_restored.entry_id == entry.entry_id
        assert entry_restored.person_id == entry.person_id
        assert entry_restored.session_id == entry.session_id
        assert entry_restored.day == entry.day
        assert entry_restored.entry_time == entry.entry_time
        assert entry_restored.exit_time == entry.exit_time
        assert entry_restored.entry_window_start == entry.entry_window_start
        assert entry_restored.entry_window_end == entry.entry_window_end
        assert entry_restored.late_tolerance == entry.late_tolerance
        assert entry_restored.exit_window_start == entry.exit_window_start
        assert entry_restored.exit_window_end == entry.exit_window_end
        assert entry_restored.class_name == entry.class_name
        assert entry_restored.session_type == entry.session_type
    
    def test_entry_json_roundtrip(self):
        """Test timetable entry JSON serialization/deserialization."""
        entry = TimetableEntry(
            entry_id="entry-9",
            person_id="person-456",
            session_id="session-2",
            day=SessionDay.TUESDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        # Serialize to JSON
        entry_json = entry.to_json()
        assert isinstance(entry_json, str)
        
        # Deserialize from JSON
        entry_restored = TimetableEntry.from_json(entry_json)
        assert entry_restored.entry_id == entry.entry_id
        assert entry_restored.person_id == entry.person_id
        assert entry_restored.session_id == entry.session_id
        assert entry_restored.day == entry.day
        assert entry_restored.entry_time == entry.entry_time
        assert entry_restored.exit_time == entry.exit_time


class TestTimetable:
    """Test Timetable class."""
    
    def test_create_timetable(self):
        """Test creating a basic timetable."""
        timetable = Timetable(
            timetable_id="ttb-1",
            timetable_version="1.0",
        )
        
        assert timetable.timetable_id == "ttb-1"
        assert timetable.timetable_version == "1.0"
        assert len(timetable.entries) == 0
    
    def test_add_entry(self):
        """Test adding entries to timetable."""
        timetable = Timetable(
            timetable_id="ttb-2",
            timetable_version="1.0",
        )
        
        entry1 = TimetableEntry(
            entry_id="entry-1",
            person_id="person-1",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry2 = TimetableEntry(
            entry_id="entry-2",
            person_id="person-2",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        timetable.entries.append(entry1)
        timetable.entries.append(entry2)
        
        assert len(timetable.entries) == 2
        assert timetable.get_entry("person-1", SessionDay.MONDAY) == entry1
        assert timetable.get_entry("person-2", SessionDay.MONDAY) == entry2
        assert timetable.get_entry("person-3", SessionDay.MONDAY) is None
    
    def test_get_entries_for_session(self):
        """Test getting entries for a specific session."""
        timetable = Timetable(
            timetable_id="ttb-3",
            timetable_version="1.0",
        )
        
        entry1 = TimetableEntry(
            entry_id="entry-1",
            person_id="person-1",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry2 = TimetableEntry(
            entry_id="entry-2",
            person_id="person-2",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry3 = TimetableEntry(
            entry_id="entry-3",
            person_id="person-3",
            session_id="session-2",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        timetable.entries.append(entry1)
        timetable.entries.append(entry2)
        timetable.entries.append(entry3)
        
        session1_entries = timetable.get_entries_for_session("session-1")
        assert len(session1_entries) == 2
        assert entry1 in session1_entries
        assert entry2 in session1_entries
        
        session2_entries = timetable.get_entries_for_session("session-2")
        assert len(session2_entries) == 1
        assert entry3 in session2_entries
    
    def test_get_entries_for_person(self):
        """Test getting entries for a specific person."""
        timetable = Timetable(
            timetable_id="ttb-4",
            timetable_version="1.0",
        )
        
        entry1 = TimetableEntry(
            entry_id="entry-1",
            person_id="person-1",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry2 = TimetableEntry(
            entry_id="entry-2",
            person_id="person-1",
            session_id="session-2",
            day=SessionDay.TUESDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry3 = TimetableEntry(
            entry_id="entry-3",
            person_id="person-2",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        timetable.entries.append(entry1)
        timetable.entries.append(entry2)
        timetable.entries.append(entry3)
        
        person1_entries = timetable.get_entries_for_person("person-1")
        assert len(person1_entries) == 2
        assert entry1 in person1_entries
        assert entry2 in person1_entries
        
        person2_entries = timetable.get_entries_for_person("person-2")
        assert len(person2_entries) == 1
        assert entry3 in person2_entries
    
    def test_timetable_validation(self):
        """Test timetable validation."""
        # Valid timetable
        timetable = Timetable(
            timetable_id="ttb-5",
            timetable_version="1.0",
        )
        assert timetable.timetable_id == "ttb-5"
        assert timetable.timetable_version == "1.0"
        
        # Invalid timetable (missing timetable_id)
        with pytest.raises(ValueError, match="timetable_id is required"):
            Timetable(timetable_id="")
    
    def test_timetable_serialization(self):
        """Test timetable serialization/deserialization."""
        timetable = Timetable(
            timetable_id="ttb-6",
            timetable_version="1.0",
        )
        
        entry1 = TimetableEntry(
            entry_id="entry-1",
            person_id="person-1",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        entry2 = TimetableEntry(
            entry_id="entry-2",
            person_id="person-2",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        timetable.entries.append(entry1)
        timetable.entries.append(entry2)
        
        # Serialize to dict
        timetable_dict = timetable.to_dict()
        assert timetable_dict["timetable_id"] == "ttb-6"
        assert timetable_dict["timetable_version"] == "1.0"
        assert len(timetable_dict["entries"]) == 2
        
        # Deserialize from dict
        timetable_restored = Timetable.from_dict(timetable_dict)
        assert timetable_restored.timetable_id == timetable.timetable_id
        assert timetable_restored.timetable_version == timetable.timetable_version
        assert len(timetable_restored.entries) == len(timetable.entries)
    
    def test_timetable_json_roundtrip(self):
        """Test timetable JSON serialization/deserialization."""
        timetable = Timetable(
            timetable_id="ttb-7",
            timetable_version="1.0",
        )
        
        entry = TimetableEntry(
            entry_id="entry-1",
            person_id="person-1",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,
            exit_time=72000,
        )
        
        timetable.entries.append(entry)
        
        # Serialize to JSON
        timetable_json = timetable.to_json()
        assert isinstance(timetable_json, str)
        
        # Deserialize from JSON
        timetable_restored = Timetable.from_json(timetable_json)
        assert timetable_restored.timetable_id == timetable.timetable_id
        assert timetable_restored.timetable_version == timetable.timetable_version
        assert len(timetable_restored.entries) == len(timetable.entries)


class TestSessionDay:
    """Test SessionDay enum."""
    
    def test_session_day_values(self):
        """Test that all session days are valid."""
        valid_days = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        
        for day in valid_days:
            assert day in [d.value for d in SessionDay]
    
    def test_session_day_enum(self):
        """Test SessionDay enum access."""
        assert SessionDay.MONDAY.value == "monday"
        assert SessionDay.TUESDAY.value == "tuesday"
        assert SessionDay.WEDNESDAY.value == "wednesday"


class TestSessionType:
    """Test SessionType enum."""
    
    def test_session_type_values(self):
        """Test that all session types are valid."""
        valid_types = [
            "morning",
            "afternoon",
            "full_day",
            "evening",
        ]
        
        for session_type in valid_types:
            assert session_type in [s.value for s in SessionType]
    
    def test_session_type_enum(self):
        """Test SessionType enum access."""
        assert SessionType.MORNING.value == "morning"
        assert SessionType.AFTERNOON.value == "afternoon"
        assert SessionType.FULL_DAY.value == "full_day"
        assert SessionType.EVENING.value == "evening"


class TestAttendanceState:
    """Test AttendanceState enum."""
    
    def test_attendance_state_values(self):
        """Test that all attendance states are valid."""
        valid_states = [
            "unknown",
            "expected",
            "present",
            "late",
            "left",
            "absent",
        ]
        
        for state in valid_states:
            assert state in [s.value for s in AttendanceState]
    
    def test_attendance_state_enum(self):
        """Test AttendanceState enum access."""
        assert AttendanceState.UNKNOWN.value == "unknown"
        assert AttendanceState.EXPECTED.value == "expected"
        assert AttendanceState.PRESENT.value == "present"
        assert AttendanceState.LATE.value == "late"
        assert AttendanceState.LEFT.value == "left"
        assert AttendanceState.ABSENT.value == "absent"


class TestGenerateTimetableId:
    """Test timetable ID generation."""
    
    def test_generate_timetable_id(self):
        """Test deterministic timetable ID generation."""
        timetable_version = "1.0"
        
        timetable_id_1 = generate_timetable_id(timetable_version)
        timetable_id_2 = generate_timetable_id(timetable_version)
        
        assert timetable_id_1 == timetable_id_2
        assert timetable_id_1.startswith("TTB-")
        assert "v1.0" in timetable_id_1