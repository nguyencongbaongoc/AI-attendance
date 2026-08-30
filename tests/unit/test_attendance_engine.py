"""
Unit tests for Phase 26 Attendance Decision Engine.
"""

import pytest
from datetime import datetime
from app.attendance.engine import (
    AttendanceEngine,
    AttendanceDecisionContext,
    AttendanceEngineError,
    TimetableNotFoundError,
    InvalidTimetableError,
    InvalidPolicyError,
    IdentityResolutionError,
)
from app.attendance.policy import AttendancePolicy, AttendanceDecision, DecisionReason
from app.attendance.timetable import Timetable, TimetableEntry, SessionDay, AttendanceState
from app.in_out.resolver_contract import (
    ResolvedTransition,
    DerivedState,
    ResolutionStatus,
)


class TestAttendanceDecisionContext:
    """Test AttendanceDecisionContext class."""
    
    def test_create_context(self):
        """Test creating a basic decision context."""
        # Create a mock resolved transition
        resolved_transition = ResolvedTransition(
            resolution_id="res-1",
            source_raw_event_id="raw-1",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create a mock timetable
        timetable = Timetable(
            timetable_id="ttb-1",
            timetable_version="1.0",
        )
        
        # Create a mock policy
        policy = AttendancePolicy(
            policy_id="policy-1",
            policy_version="1.0",
        )
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
        )
        
        assert context.resolved_transition == resolved_transition
        assert context.timetable == timetable
        assert context.attendance_policy == policy
        assert context.person_id_override is None
        assert context.day_override is None
        assert context.session_id_override is None


class TestAttendanceEngine:
    """Test AttendanceEngine class."""
    
    def test_create_engine(self):
        """Test creating an attendance engine."""
        policy = AttendancePolicy(
            policy_id="policy-1",
            policy_version="1.0",
        )
        
        engine = AttendanceEngine(policy)
        
        assert engine.policy == policy
    
    def test_make_decision_within_entry_window(self):
        """Test making a decision for an IN event within entry window."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-1",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition (IN event at 10:00 AM)
        resolved_transition = ResolvedTransition(
            resolution_id="res-1",
            source_raw_event_id="raw-1",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,  # 10:00 AM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable entry (entry at 10:00 AM, window 9:50-10:10)
        timetable_entry = TimetableEntry(
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
        
        # Create timetable
        timetable = Timetable(
            timetable_id="ttb-1",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision
        decision = engine.make_decision(context)
        
        # Verify decision
        assert decision.decision_id is not None
        assert decision.direction == "in"
        assert decision.event_timestamp == 36000
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "present"
        assert decision.decision_reason == "within_entry_window"
        assert decision.is_in is True
        assert decision.is_out is False
    
    def test_make_decision_late_within_tolerance(self):
        """Test making a decision for a late IN event within tolerance."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-2",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition (IN event at 10:15 AM, 15 minutes late - after entry window but within 20 min tolerance)
        resolved_transition = ResolvedTransition(
            resolution_id="res-2",
            source_raw_event_id="raw-2",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36900,  # 10:15 AM (15 minutes late, after entry window end at 10:00)
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable entry (entry at 10:00 AM, entry window ends at 10:00, tolerance 20 minutes)
        timetable_entry = TimetableEntry(
            entry_id="entry-2",
            person_id="person-123",
            session_id="session-1",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36000,  # 10:00 AM (entry window ends at entry time)
            late_tolerance=1200,  # 20 minutes (extends to 10:20 AM)
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Create timetable
        timetable = Timetable(
            timetable_id="ttb-2",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision
        decision = engine.make_decision(context)
        
        # Verify decision
        assert decision.decision_id is not None
        assert decision.direction == "in"
        assert decision.event_timestamp == 36900
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "late"
        assert decision.decision_reason == "late_within_tolerance"
        assert decision.is_in is True
        assert decision.is_out is False
    
    def test_make_decision_outside_attendance_window(self):
        """Test making a decision for an IN event outside attendance window."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-3",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition (IN event at 11:00 AM, 60 minutes late)
        resolved_transition = ResolvedTransition(
            resolution_id="res-3",
            source_raw_event_id="raw-3",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=39600,  # 11:00 AM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable entry (entry at 10:00 AM, tolerance 10 minutes)
        timetable_entry = TimetableEntry(
            entry_id="entry-3",
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
        
        # Create timetable
        timetable = Timetable(
            timetable_id="ttb-3",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision
        decision = engine.make_decision(context)
        
        # Verify decision
        assert decision.decision_id is not None
        assert decision.direction == "in"
        assert decision.event_timestamp == 39600
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "absent"
        assert decision.decision_reason == "outside_attendance_window"
        assert decision.is_in is True
        assert decision.is_out is False
    
    def test_make_decision_exit_recorded(self):
        """Test making a decision for an OUT event within exit window."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-4",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition (OUT event at 20:00 PM)
        resolved_transition = ResolvedTransition(
            resolution_id="res-4",
            source_raw_event_id="raw-4",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="out",
            transition_type=DerivedState.OUTSIDE,
            previous_state=DerivedState.INSIDE,
            new_state=DerivedState.OUTSIDE,
            source_timestamp=72000,  # 20:00 PM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable entry (exit at 20:00 PM, window 19:50-20:10)
        timetable_entry = TimetableEntry(
            entry_id="entry-4",
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
        
        # Create timetable
        timetable = Timetable(
            timetable_id="ttb-4",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision
        decision = engine.make_decision(context)
        
        # Verify decision
        assert decision.decision_id is not None
        assert decision.direction == "out"
        assert decision.event_timestamp == 72000
        assert decision.previous_attendance_state == "present"
        assert decision.new_attendance_state == "left"
        assert decision.decision_reason == "exit_recorded"
        assert decision.is_in is False
        assert decision.is_out is True
    
    def test_make_decision_outside_exit_window(self):
        """Test making a decision for an OUT event outside exit window."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-5",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition (OUT event at 21:00 PM, 60 minutes late)
        resolved_transition = ResolvedTransition(
            resolution_id="res-5",
            source_raw_event_id="raw-5",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="out",
            transition_type=DerivedState.OUTSIDE,
            previous_state=DerivedState.INSIDE,
            new_state=DerivedState.OUTSIDE,
            source_timestamp=75600,  # 21:00 PM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable entry (exit at 20:00 PM, window 19:50-20:10)
        timetable_entry = TimetableEntry(
            entry_id="entry-5",
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
        
        # Create timetable
        timetable = Timetable(
            timetable_id="ttb-5",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision
        decision = engine.make_decision(context)
        
        # Verify decision
        assert decision.decision_id is not None
        assert decision.direction == "out"
        assert decision.event_timestamp == 75600
        assert decision.previous_attendance_state == "present"
        assert decision.new_attendance_state == "absent"
        assert decision.decision_reason == "outside_attendance_window"
        assert decision.is_in is False
        assert decision.is_out is True
    
    def test_make_decision_timetable_not_found(self):
        """Test that engine raises TimetableNotFoundError when timetable entry not found."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-6",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition
        resolved_transition = ResolvedTransition(
            resolution_id="res-6",
            source_raw_event_id="raw-6",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable with NO entry for person-123
        timetable = Timetable(
            timetable_id="ttb-6",
            timetable_version="1.0",
        )
        
        # Create context
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-123",
            day_override=SessionDay.MONDAY,
        )
        
        # Make decision should raise TimetableNotFoundError
        with pytest.raises(TimetableNotFoundError):
            engine.make_decision(context)
    
    def test_make_decision_invalid_transition(self):
        """Test that engine raises InvalidPolicyError for invalid transition."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-7",
            policy_version="1.0",
        )

        # Create engine
        engine = AttendanceEngine(policy)

        # Create resolved transition with invalid direction - validation happens in __post_init__
        with pytest.raises(ValueError, match="direction must be 'in' or 'out', got invalid"):
            ResolvedTransition(
                resolution_id="res-7",
                source_raw_event_id="raw-7",
                camera_id="CAM1",
                local_track_id="track-1",
                direction="invalid",  # Invalid direction
                transition_type=DerivedState.INSIDE,
                previous_state=DerivedState.UNKNOWN,
                new_state=DerivedState.INSIDE,
                source_timestamp=36000,
                source_frame_index=100,
                resolver_version="1.0",
                resolver_config_hash="config-1",
                geometry_version=1,
                geometry_config_hash="geom-1",
            )
    
    def test_make_decision_invalid_timetable_entry(self):
        """Test that engine raises InvalidTimetableError for invalid timetable entry."""
        # Create policy
        policy = AttendancePolicy(
            policy_id="policy-8",
            policy_version="1.0",
        )
        
        # Create engine
        engine = AttendanceEngine(policy)
        
        # Create resolved transition
        resolved_transition = ResolvedTransition(
            resolution_id="res-8",
            source_raw_event_id="raw-8",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        # Create timetable with invalid entry (negative entry_time)
        # The validation happens in TimetableEntry.__post_init__, so we expect ValueError
        with pytest.raises(ValueError, match="entry_time must be >= 0"):
            TimetableEntry(
                entry_id="entry-8",
                person_id="person-123",
                session_id="session-1",
                day=SessionDay.MONDAY,
                entry_time=-1,  # Invalid
                exit_time=72000,
            )
    
    def test_determine_previous_attendance_state(self):
        """Test previous attendance state determination."""
        policy = AttendancePolicy(policy_id="policy-9", policy_version="1.0")
        engine = AttendanceEngine(policy)
        
        # Test UNKNOWN state
        resolved_transition = ResolvedTransition(
            resolution_id="res-9",
            source_raw_event_id="raw-9",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        previous_state = engine._determine_previous_attendance_state(resolved_transition)
        assert previous_state == AttendanceState.UNKNOWN
        
        # Test INSIDE state
        resolved_transition = ResolvedTransition(
            resolution_id="res-10",
            source_raw_event_id="raw-10",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.INSIDE,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        previous_state = engine._determine_previous_attendance_state(resolved_transition)
        assert previous_state == AttendanceState.PRESENT
        
        # Test OUTSIDE state
        resolved_transition = ResolvedTransition(
            resolution_id="res-11",
            source_raw_event_id="raw-11",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.OUTSIDE,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-1",
            geometry_version=1,
            geometry_config_hash="geom-1",
        )
        
        previous_state = engine._determine_previous_attendance_state(resolved_transition)
        assert previous_state == AttendanceState.LEFT
    
    def test_is_idempotent(self):
        """Test idempotency check."""
        policy = AttendancePolicy(policy_id="policy-12", policy_version="1.0")
        engine = AttendanceEngine(policy)
        
        # Create a decision
        decision = AttendanceDecision(
            decision_id="dec-1",
            direction="in",
            event_timestamp=36000,
            camera_id="CAM1",
            local_track_id="track-1",
            source_raw_event_id="raw-1",
            source_resolution_id="res-1",
        )
        
        # Check idempotency
        assert engine.is_idempotent(decision) is True