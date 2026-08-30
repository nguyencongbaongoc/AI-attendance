"""
Integration tests for Phase 26 Attendance System.

Tests the complete flow from Phase 24 ResolvedTransition through Phase 26
Attendance Decision Engine to AttendanceDecision.
"""

import pytest
from app.attendance.engine import AttendanceEngine, AttendanceDecisionContext
from app.attendance.policy import AttendancePolicy
from app.attendance.timetable import Timetable, TimetableEntry, SessionDay
from app.in_out.resolver_contract import ResolvedTransition, DerivedState


class TestAttendanceIntegration:
    """Integration tests for attendance decision making."""
    
    def test_complete_attendance_flow(self):
        """
        Test complete attendance flow:
        1. Create ResolvedTransition (Phase 24)
        2. Create TimetableEntry
        3. Create Timetable
        4. Create AttendancePolicy
        5. Create AttendanceEngine
        6. Make decision
        7. Verify result
        """
        # Step 1: Create ResolvedTransition (Phase 24)
        resolved_transition = ResolvedTransition(
            resolution_id="res-integration-1",
            source_raw_event_id="raw-integration-1",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,  # 10:00 AM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-integration-1",
            geometry_version=1,
            geometry_config_hash="geom-integration-1",
        )
        
        # Step 2: Create TimetableEntry
        timetable_entry = TimetableEntry(
            entry_id="entry-integration-1",
            person_id="person-integration-1",
            session_id="session-integration-1",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36600,  # 10:10 AM
            late_tolerance=600,  # 10 minutes
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Step 3: Create Timetable
        timetable = Timetable(
            timetable_id="ttb-integration-1",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Step 4: Create AttendancePolicy
        policy = AttendancePolicy(
            policy_id="policy-integration-1",
            policy_version="1.0",
            unknown_identity_policy="unresolved",
            duplicate_decision_policy="ignore",
            session_finalization_policy="event_based",
        )
        
        # Step 5: Create AttendanceEngine
        engine = AttendanceEngine(policy)
        
        # Step 6: Make decision
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-1",
            day_override=SessionDay.MONDAY,
        )
        
        decision = engine.make_decision(context)
        
        # Step 7: Verify result
        assert decision.decision_id is not None
        assert decision.decision_id.startswith("DEC-")
        assert decision.direction == "in"
        assert decision.event_timestamp == 36000
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "present"
        assert decision.decision_reason == "within_entry_window"
        assert decision.is_in is True
        assert decision.is_out is False
        assert decision.identity_certainty == "known"  # person_id_override provided
        assert decision.identity_candidate == "person-integration-1"
        assert decision.identity_confidence == 1.0
        assert decision.timetable_id == "ttb-integration-1"
        assert decision.session_id == "session-integration-1"
        assert decision.day == "monday"
        
        # Verify provenance chain
        assert decision.source_raw_event_id == "raw-integration-1"
        assert decision.source_resolution_id == "res-integration-1"
        assert decision.camera_id == "CAM1"
        assert decision.local_track_id == "track-1"
        assert decision.geometry_version == 1
        assert decision.geometry_config_hash == "geom-integration-1"
        assert decision.resolver_version == "1.0"
        assert decision.resolver_config_hash == "config-integration-1"
    
    def test_complete_attendance_flow_with_exit(self):
        """
        Test complete attendance flow with exit event.
        """
        # Step 1: Create ResolvedTransition for exit (Phase 24)
        resolved_transition = ResolvedTransition(
            resolution_id="res-integration-2",
            source_raw_event_id="raw-integration-2",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="out",
            transition_type=DerivedState.OUTSIDE,
            previous_state=DerivedState.INSIDE,
            new_state=DerivedState.OUTSIDE,
            source_timestamp=72000,  # 20:00 PM
            source_frame_index=200,
            resolver_version="1.0",
            resolver_config_hash="config-integration-2",
            geometry_version=1,
            geometry_config_hash="geom-integration-2",
        )
        
        # Step 2: Create TimetableEntry
        timetable_entry = TimetableEntry(
            entry_id="entry-integration-2",
            person_id="person-integration-2",
            session_id="session-integration-2",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36600,  # 10:10 AM
            late_tolerance=600,  # 10 minutes
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Step 3: Create Timetable
        timetable = Timetable(
            timetable_id="ttb-integration-2",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Step 4: Create AttendancePolicy
        policy = AttendancePolicy(
            policy_id="policy-integration-2",
            policy_version="1.0",
        )
        
        # Step 5: Create AttendanceEngine
        engine = AttendanceEngine(policy)
        
        # Step 6: Make decision
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-2",
            day_override=SessionDay.MONDAY,
        )
        
        decision = engine.make_decision(context)
        
        # Step 7: Verify result
        assert decision.decision_id is not None
        assert decision.direction == "out"
        assert decision.event_timestamp == 72000
        assert decision.previous_attendance_state == "present"
        assert decision.new_attendance_state == "left"
        assert decision.decision_reason == "exit_recorded"
        assert decision.is_in is False
        assert decision.is_out is True
    
    def test_complete_attendance_flow_late_entry(self):
        """
        Test complete attendance flow with late entry.
        """
        # Step 1: Create ResolvedTransition for late entry (Phase 24)
        resolved_transition = ResolvedTransition(
            resolution_id="res-integration-3",
            source_raw_event_id="raw-integration-3",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36900,  # 10:15 AM (15 minutes late)
            source_frame_index=150,
            resolver_version="1.0",
            resolver_config_hash="config-integration-3",
            geometry_version=1,
            geometry_config_hash="geom-integration-3",
        )
        
        # Step 2: Create TimetableEntry with 20-minute tolerance (entry window ends at 10:00 AM)
        timetable_entry = TimetableEntry(
            entry_id="entry-integration-3",
            person_id="person-integration-3",
            session_id="session-integration-3",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36000,  # 10:00 AM (entry window ends at entry time)
            late_tolerance=1200,  # 20 minutes (extends to 10:20 AM)
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Step 3: Create Timetable
        timetable = Timetable(
            timetable_id="ttb-integration-3",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Step 4: Create AttendancePolicy
        policy = AttendancePolicy(
            policy_id="policy-integration-3",
            policy_version="1.0",
        )
        
        # Step 5: Create AttendanceEngine
        engine = AttendanceEngine(policy)
        
        # Step 6: Make decision
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-3",
            day_override=SessionDay.MONDAY,
        )
        
        decision = engine.make_decision(context)
        
        # Step 7: Verify result
        assert decision.decision_id is not None
        assert decision.direction == "in"
        assert decision.event_timestamp == 36900
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "late"
        assert decision.decision_reason == "late_within_tolerance"
        assert decision.is_in is True
        assert decision.is_out is False
    
    def test_complete_attendance_flow_outside_window(self):
        """
        Test complete attendance flow with entry outside attendance window.
        """
        # Step 1: Create ResolvedTransition for entry outside window (Phase 24)
        resolved_transition = ResolvedTransition(
            resolution_id="res-integration-4",
            source_raw_event_id="raw-integration-4",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=39600,  # 11:00 AM (60 minutes late)
            source_frame_index=180,
            resolver_version="1.0",
            resolver_config_hash="config-integration-4",
            geometry_version=1,
            geometry_config_hash="geom-integration-4",
        )
        
        # Step 2: Create TimetableEntry with 10-minute tolerance
        timetable_entry = TimetableEntry(
            entry_id="entry-integration-4",
            person_id="person-integration-4",
            session_id="session-integration-4",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36600,  # 10:10 AM
            late_tolerance=600,  # 10 minutes
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Step 3: Create Timetable
        timetable = Timetable(
            timetable_id="ttb-integration-4",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Step 4: Create AttendancePolicy
        policy = AttendancePolicy(
            policy_id="policy-integration-4",
            policy_version="1.0",
        )
        
        # Step 5: Create AttendanceEngine
        engine = AttendanceEngine(policy)
        
        # Step 6: Make decision
        context = AttendanceDecisionContext(
            resolved_transition=resolved_transition,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-4",
            day_override=SessionDay.MONDAY,
        )
        
        decision = engine.make_decision(context)
        
        # Step 7: Verify result
        assert decision.decision_id is not None
        assert decision.direction == "in"
        assert decision.event_timestamp == 39600
        assert decision.previous_attendance_state == "unknown"
        assert decision.new_attendance_state == "absent"
        assert decision.decision_reason == "outside_attendance_window"
        assert decision.is_in is True
        assert decision.is_out is False
    
    def test_multiple_entries_same_person(self):
        """
        Test attendance flow for multiple entries of the same person.
        """
        # Step 1: Create ResolvedTransition for first entry (Phase 24)
        resolved_transition_1 = ResolvedTransition(
            resolution_id="res-integration-5-1",
            source_raw_event_id="raw-integration-5-1",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="in",
            transition_type=DerivedState.INSIDE,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE,
            source_timestamp=36000,  # 10:00 AM
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="config-integration-5-1",
            geometry_version=1,
            geometry_config_hash="geom-integration-5-1",
        )
        
        # Step 2: Create TimetableEntry
        timetable_entry = TimetableEntry(
            entry_id="entry-integration-5",
            person_id="person-integration-5",
            session_id="session-integration-5",
            day=SessionDay.MONDAY,
            entry_time=36000,  # 10:00 AM
            exit_time=72000,  # 20:00 PM
            entry_window_start=35400,  # 9:50 AM
            entry_window_end=36600,  # 10:10 AM
            late_tolerance=600,  # 10 minutes
            exit_window_start=71400,  # 19:50 PM
            exit_window_end=72600,  # 20:10 PM
        )
        
        # Step 3: Create Timetable
        timetable = Timetable(
            timetable_id="ttb-integration-5",
            timetable_version="1.0",
        )
        timetable.entries.append(timetable_entry)
        
        # Step 4: Create AttendancePolicy
        policy = AttendancePolicy(
            policy_id="policy-integration-5",
            policy_version="1.0",
        )
        
        # Step 5: Create AttendanceEngine
        engine = AttendanceEngine(policy)
        
        # Step 6: Make first decision
        context_1 = AttendanceDecisionContext(
            resolved_transition=resolved_transition_1,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-5",
            day_override=SessionDay.MONDAY,
        )
        
        decision_1 = engine.make_decision(context_1)
        
        # Step 7: Verify first decision
        assert decision_1.decision_id is not None
        assert decision_1.direction == "in"
        assert decision_1.new_attendance_state == "present"
        assert decision_1.decision_reason == "within_entry_window"
        
        # Step 8: Create ResolvedTransition for exit (Phase 24)
        resolved_transition_2 = ResolvedTransition(
            resolution_id="res-integration-5-2",
            source_raw_event_id="raw-integration-5-2",
            camera_id="CAM1",
            local_track_id="track-1",
            direction="out",
            transition_type=DerivedState.OUTSIDE,
            previous_state=DerivedState.INSIDE,
            new_state=DerivedState.OUTSIDE,
            source_timestamp=72000,  # 20:00 PM
            source_frame_index=200,
            resolver_version="1.0",
            resolver_config_hash="config-integration-5-2",
            geometry_version=1,
            geometry_config_hash="geom-integration-5-2",
        )
        
        # Step 9: Make second decision (exit)
        context_2 = AttendanceDecisionContext(
            resolved_transition=resolved_transition_2,
            timetable=timetable,
            attendance_policy=policy,
            person_id_override="person-integration-5",
            day_override=SessionDay.MONDAY,
        )
        
        decision_2 = engine.make_decision(context_2)
        
        # Step 10: Verify second decision
        assert decision_2.decision_id is not None
        assert decision_2.direction == "out"
        assert decision_2.previous_attendance_state == "present"
        assert decision_2.new_attendance_state == "left"
        assert decision_2.decision_reason == "exit_recorded"
        
        # Verify both decisions are different
        assert decision_1.decision_id != decision_2.decision_id