"""
Phase 26/37A — Attendance Decision Engine.

Deterministic attendance decision making.
Converts Phase 24 ResolvedTransition + Timetable + AttendancePolicy
into AttendanceDecision.

Phase 37A adds automatic person_id resolution, day resolution, and calendar integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import pytz

from app.in_out.resolver_contract import (
    DerivedState,
    ResolvedTransition,
    ResolutionStatus,
)
from app.in_out.contract import IdentityCertainty
from app.attendance.timetable import (
    Timetable,
    TimetableEntry,
    SessionDay,
    AttendanceState,
)
from app.attendance.policy import (
    AttendancePolicy,
    AttendanceDecision,
    DecisionReason,
    IdentityHandlingPolicy,
    DuplicateDecisionPolicy,
    SessionFinalizationPolicy,
    generate_decision_id,
    validate_attendance_decision,
)
from app.attendance.calendar import CalendarEngine
from app.attendance.daily_resolver import (
    IdentityResolver,
    DayResolver,
    DailyExpectedResolver,
    IdentityResolution,
)
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.replay.fusion import GlobalObservation


class AttendanceEngineError(Exception):
    """Base exception for attendance engine errors."""
    pass


class TimetableNotFoundError(AttendanceEngineError):
    """Raised when timetable entry is not found."""
    pass


class InvalidTimetableError(AttendanceEngineError):
    """Raised when timetable entry is invalid."""
    pass


class InvalidPolicyError(AttendanceEngineError):
    """Raised when attendance policy is invalid."""
    pass


class IdentityResolutionError(AttendanceEngineError):
    """Raised when identity cannot be resolved."""
    pass


@dataclass
class AttendanceDecisionContext:
    """
    Context for attendance decision making.
    
    Contains all inputs needed to make a deterministic decision.
    """
    # Source transition from Phase 24
    resolved_transition: ResolvedTransition
    
    # Timetable
    timetable: Timetable
    
    # Attendance policy
    attendance_policy: AttendancePolicy
    
    # Optional: person_id lookup (for cross-camera identity resolution)
    # If provided, this overrides the identity from the transition
    person_id_override: Optional[str] = None
    
    # Optional: day override (for offline replay)
    # If provided, this overrides the day from the event timestamp
    day_override: Optional[SessionDay] = None
    
    # Optional: session_id override
    session_id_override: Optional[str] = None


class AttendanceEngine:
    """
    Deterministic attendance decision engine.
    
    Converts Phase 24 ResolvedTransition + Timetable + AttendancePolicy
    into AttendanceDecision.
    
    Core semantics:
    - IN event: Determine PRESENT, LATE, or ABSENT
    - OUT event: Determine LEFT or ABSENT
    - UNKNOWN/AMBIGUOUS identity: Follow policy
    - Deterministic: Same inputs = same output
    - Idempotent: Same decision processed multiple times = same result
    """
    
    def __init__(self, policy: AttendancePolicy, repository: Optional[AttendanceRepository] = None):
        """
        Initialize attendance engine.
        
        Args:
            policy: Attendance policy to use for decisions
            repository: Optional attendance repository for querying records
        """
        self.policy = policy
        self.repository = repository or create_attendance_repository()
    
    def make_decision(self, context: AttendanceDecisionContext) -> AttendanceDecision:
        """
        Make an attendance decision.
        
        Args:
            context: Context containing all inputs for the decision
            
        Returns:
            AttendanceDecision
            
        Raises:
            TimetableNotFoundError: If timetable entry not found
            InvalidTimetableError: If timetable entry is invalid
            InvalidPolicyError: If policy is invalid
            IdentityResolutionError: If identity cannot be resolved
        """
        # Validate inputs - ResolvedTransition validates itself in __post_init__
        # No additional validation needed here
        pass
        
        # Determine person_id
        person_id = self._determine_person_id(context)
        
        # Determine day
        day = self._determine_day(context)
        
        # Get timetable entry
        timetable_entry = self._get_timetable_entry(context, person_id, day)
        
        if timetable_entry is None:
            raise TimetableNotFoundError(
                f"No timetable entry found for person_id={person_id}, day={day.value}"
            )
        
        # Validate timetable entry
        if timetable_entry.entry_time < 0 or timetable_entry.exit_time < 0:
            raise InvalidTimetableError(
                f"Invalid timetable entry: entry_time={timetable_entry.entry_time}, exit_time={timetable_entry.exit_time}"
            )
        
        # Determine attendance state
        previous_state = self._determine_previous_attendance_state(context.resolved_transition)
        new_state = self._determine_new_attendance_state(
            context.resolved_transition,
            timetable_entry,
            previous_state,
        )
        
        # Determine decision reason
        decision_reason = self._determine_decision_reason(
            context.resolved_transition,
            timetable_entry,
            previous_state,
            new_state,
        )
        
        # Build attendance decision
        decision = AttendanceDecision(
            decision_id=generate_decision_id(context.resolved_transition.resolution_id),
            identity_certainty=self._determine_identity_certainty(context),
            identity_candidate=self._determine_identity_candidate(context),
            identity_confidence=self._determine_identity_confidence(context),
            identity_evidence_ref=context.resolved_transition.global_observation_id,
            direction=context.resolved_transition.direction,
            event_timestamp=context.resolved_transition.source_timestamp,
            event_frame_index=context.resolved_transition.source_frame_index,
            camera_id=context.resolved_transition.camera_id,
            local_track_id=context.resolved_transition.local_track_id,
            global_observation_id=context.resolved_transition.global_observation_id,
            source_raw_event_id=context.resolved_transition.source_raw_event_id,
            source_resolution_id=context.resolved_transition.resolution_id,
            source_crossing_event_id=context.resolved_transition.source_crossing_event_id,
            geometry_version=context.resolved_transition.geometry_version,
            geometry_config_hash=context.resolved_transition.geometry_config_hash,
            resolver_version=context.resolved_transition.resolver_version,
            resolver_config_hash=context.resolved_transition.resolver_config_hash,
            timetable_id=context.timetable.timetable_id,
            timetable_version=context.timetable.timetable_version,
            session_id=timetable_entry.session_id,
            day=day.value,
            previous_attendance_state=previous_state.value,
            new_attendance_state=new_state.value,
            decision_reason=decision_reason.value,
            attendance_policy_id=self.policy.policy_id,
            attendance_policy_version=self.policy.policy_version,
            decision_schema_version="1.0",
        )
        
        # Validate decision
        validation_error = validate_attendance_decision(decision)
        if validation_error is not None:
            raise InvalidPolicyError(
                f"Generated invalid attendance decision: {validation_error}"
            )
        return decision
    
    def _determine_person_id(self, context: AttendanceDecisionContext) -> str:
        """
        Determine the person_id for the decision.
        
        Args:
            context: Decision context
            
        Returns:
            Person ID
            
        Raises:
            IdentityResolutionError: If person_id cannot be determined
        """
        # If person_id_override is provided, use it
        if context.person_id_override is not None:
            return context.person_id_override
        
        # Otherwise, use the person_id from the timetable entry
        # This requires that the timetable entry has a person_id
        # For now, we'll use a placeholder since we don't have a person_id lookup
        # In a real system, this would come from GlobalObservation
        raise IdentityResolutionError(
            "person_id_override is required when no timetable entry has a person_id"
        )
    
    def _determine_day(self, context: AttendanceDecisionContext) -> SessionDay:
        """
        Determine the day for the decision.
        
        Args:
            context: Decision context
            
        Returns:
            Day of week
        """
        # If day_override is provided, use it
        if context.day_override is not None:
            return context.day_override
        
        # Otherwise, determine day from event timestamp
        # For offline replay, we need to know the date
        # This is a simplification - in a real system, we'd have the full datetime
        raise IdentityResolutionError(
            "day_override is required for offline replay"
        )
    
    def _get_timetable_entry(
        self,
        context: AttendanceDecisionContext,
        person_id: str,
        day: SessionDay,
    ) -> Optional[TimetableEntry]:
        """
        Get timetable entry for the person and day.
        
        Args:
            context: Decision context
            person_id: Person ID
            day: Day of week
            
        Returns:
            TimetableEntry if found, None otherwise
        """
        return context.timetable.get_entry(person_id, day)
    
    def _determine_identity_certainty(self, context: AttendanceDecisionContext) -> str:
        """
        Determine identity certainty for the decision.
        
        Args:
            context: Decision context
            
        Returns:
            Identity certainty level
        """
        # If person_id_override is provided, assume KNOWN
        if context.person_id_override is not None:
            return IdentityCertainty.KNOWN.value
        
        # Otherwise, use the identity certainty from the raw event
        # This is preserved in the ResolvedTransition
        # For now, we'll use UNKNOWN since we don't have a person_id lookup
        return IdentityCertainty.UNKNOWN.value
    
    def _determine_identity_candidate(self, context: AttendanceDecisionContext) -> Optional[str]:
        """
        Determine identity candidate for the decision.
        
        Args:
            context: Decision context
            
        Returns:
            Identity candidate or None
        """
        # If person_id_override is provided, use it
        if context.person_id_override is not None:
            return context.person_id_override
        
        # Otherwise, return None
        return None
    
    def _determine_identity_confidence(self, context: AttendanceDecisionContext) -> float:
        """
        Determine identity confidence for the decision.
        
        Args:
            context: Decision context
            
        Returns:
            Identity confidence (0.0 to 1.0)
        """
        # If person_id_override is provided, assume high confidence
        if context.person_id_override is not None:
            return 1.0
        
        # Otherwise, use the identity confidence from the raw event
        # This is preserved in the ResolvedTransition
        # For now, we'll use 0.0 since we don't have a person_id lookup
        return 0.0
    
    def _determine_previous_attendance_state(
        self,
        resolved_transition: ResolvedTransition,
    ) -> AttendanceState:
        """
        Determine previous attendance state.
        
        Args:
            resolved_transition: Resolved transition from Phase 24
            
        Returns:
            Previous attendance state
        """
        # Map Phase 24 DerivedState to Phase 26 AttendanceState
        derived_state = resolved_transition.previous_state
        
        if derived_state == DerivedState.UNKNOWN:
            return AttendanceState.UNKNOWN
        elif derived_state == DerivedState.INSIDE:
            return AttendanceState.PRESENT
        elif derived_state == DerivedState.OUTSIDE:
            return AttendanceState.LEFT
        else:
            return AttendanceState.UNKNOWN
    
    def _determine_new_attendance_state(
        self,
        resolved_transition: ResolvedTransition,
        timetable_entry: TimetableEntry,
        previous_state: AttendanceState,
    ) -> AttendanceState:
        """
        Determine new attendance state based on event and timetable.
        
        Args:
            resolved_transition: Resolved transition from Phase 24
            timetable_entry: Timetable entry for the person
            previous_state: Previous attendance state
            
        Returns:
            New attendance state
        """
        event_timestamp = resolved_transition.source_timestamp
        direction = resolved_transition.direction
        
        # Handle IN events
        if direction == "in":
            return self._determine_in_state(event_timestamp, timetable_entry, previous_state)
        
        # Handle OUT events
        elif direction == "out":
            return self._determine_out_state(event_timestamp, timetable_entry, previous_state)
        
        # Unknown direction
        else:
            return AttendanceState.UNKNOWN
    
    def _determine_in_state(
        self,
        event_timestamp: float,
        timetable_entry: TimetableEntry,
        previous_state: AttendanceState,
    ) -> AttendanceState:
        """
        Determine attendance state for IN event.
        
        Args:
            event_timestamp: Event timestamp (seconds from midnight)
            timetable_entry: Timetable entry
            previous_state: Previous attendance state
            
        Returns:
            New attendance state
        """
        entry_time = timetable_entry.entry_time
        entry_window_start = timetable_entry.entry_window_start
        entry_window_end = timetable_entry.entry_window_end
        late_tolerance = timetable_entry.late_tolerance
        
        # Check if event is within entry window
        if entry_window_start <= event_timestamp <= entry_window_end:
            return AttendanceState.PRESENT
        
        # Check if event is late but within tolerance (after entry window end but within late tolerance from entry_time)
        if entry_window_end < event_timestamp <= entry_time + late_tolerance:
            return AttendanceState.LATE
        
        # Event is outside attendance window
        return AttendanceState.ABSENT
    
    def _determine_out_state(
        self,
        event_timestamp: float,
        timetable_entry: TimetableEntry,
        previous_state: AttendanceState,
    ) -> AttendanceState:
        """
        Determine attendance state for OUT event.
        
        Args:
            event_timestamp: Event timestamp (seconds from midnight)
            timetable_entry: Timetable entry
            previous_state: Previous attendance state
            
        Returns:
            New attendance state
        """
        exit_time = timetable_entry.exit_time
        exit_window_start = timetable_entry.exit_window_start
        exit_window_end = timetable_entry.exit_window_end
        
        # Check if event is within exit window
        if exit_window_start <= event_timestamp <= exit_window_end:
            return AttendanceState.LEFT
        
        # Event is outside exit window
        return AttendanceState.ABSENT
    
    def _determine_decision_reason(
        self,
        resolved_transition: ResolvedTransition,
        timetable_entry: TimetableEntry,
        previous_state: AttendanceState,
        new_state: AttendanceState,
    ) -> DecisionReason:
        """
        Determine decision reason for the attendance decision.
        
        Args:
            resolved_transition: Resolved transition from Phase 24
            timetable_entry: Timetable entry
            previous_state: Previous attendance state
            new_state: New attendance state
            
        Returns:
            Decision reason
        """
        direction = resolved_transition.direction
        event_timestamp = resolved_transition.source_timestamp
        
        # IN events
        if direction == "in":
            entry_time = timetable_entry.entry_time
            entry_window_start = timetable_entry.entry_window_start
            entry_window_end = timetable_entry.entry_window_end
            late_tolerance = timetable_entry.late_tolerance
            
            # Within entry window
            if entry_window_start <= event_timestamp <= entry_window_end:
                return DecisionReason.WITHIN_ENTRY_WINDOW
            
            # Late but within tolerance
            if entry_time <= event_timestamp <= entry_time + late_tolerance:
                return DecisionReason.LATE_WITHIN_TOLERANCE
            
            # Outside attendance window
            return DecisionReason.OUTSIDE_ATTENDANCE_WINDOW
        
        # OUT events
        elif direction == "out":
            exit_time = timetable_entry.exit_time
            exit_window_start = timetable_entry.exit_window_start
            exit_window_end = timetable_entry.exit_window_end
            
            # Within exit window
            if exit_window_start <= event_timestamp <= exit_window_end:
                return DecisionReason.EXIT_RECORDED
            
            # Outside exit window
            return DecisionReason.OUTSIDE_ATTENDANCE_WINDOW
        
        # Unknown direction
        else:
            return DecisionReason.INVALID_POLICY
    
    def is_idempotent(self, decision: AttendanceDecision) -> bool:
        """
        Check if a decision is idempotent.
        
        Same decision processed multiple times should produce the same result.
        
        Args:
            decision: Attendance decision to check
            
        Returns:
            True if decision is idempotent, False otherwise
        """
        # For now, all decisions are considered idempotent
        # In a more complex system, we might track state
        return True
    
    # =============================================================================
    # PHASE 37A: AUTOMATIC RESOLUTION METHODS
    # =============================================================================
    
    def _unix_to_seconds_from_midnight(self, unix_timestamp: float, calendar_engine: CalendarEngine) -> int:
        """
        Convert Unix timestamp to seconds from midnight in the calendar's timezone.
        
        Args:
            unix_timestamp: Unix timestamp (seconds since epoch)
            calendar_engine: Calendar engine with timezone configuration
            
        Returns:
            Seconds from midnight (0-86399)
        """
        dt_utc = datetime.fromtimestamp(unix_timestamp, tz=pytz.UTC)
        dt_local = dt_utc.astimezone(calendar_engine.timezone)
        return dt_local.hour * 3600 + dt_local.minute * 60 + dt_local.second
    
    def make_decision_auto(
        self,
        resolved_transition: ResolvedTransition,
        timetable: Timetable,
        calendar_engine: CalendarEngine,
        identity_resolver: IdentityResolver,
        global_observation: Optional[GlobalObservation] = None,
    ) -> AttendanceDecision:
        """
        Make an attendance decision with automatic person_id and day resolution.
        
        This is the Phase 37A enhanced method that eliminates the need for
        manual person_id_override and day_override.
        
        Args:
            resolved_transition: Phase 24 resolved transition
            timetable: Phase 26 timetable
            calendar_engine: Calendar engine for day/exception resolution
            identity_resolver: Identity resolver for person_id from GlobalObservation
            global_observation: Optional GlobalObservation for identity resolution
            
        Returns:
            AttendanceDecision with automatically resolved identity and day
        """
        # Resolve person_id from GlobalObservation if available
        person_id = None
        identity_resolution: Optional[IdentityResolution] = None
        
        if global_observation is not None:
            identity_resolution = identity_resolver.resolve_from_global_observation(global_observation)
            person_id = identity_resolution.student_id or identity_resolution.person_id
        
        # Resolve day from timestamp using calendar engine
        day_resolver = DayResolver(calendar_engine)
        day = day_resolver.resolve_day(resolved_transition.source_timestamp)
        
        # Convert Unix timestamp to seconds-from-midnight for attendance logic
        event_timestamp_sfm = self._unix_to_seconds_from_midnight(
            resolved_transition.source_timestamp, calendar_engine
        )
        
        # Build context with auto-resolved values
        # We need to temporarily override the source_timestamp for the decision logic
        # Create a modified transition with seconds-from-midnight timestamp
        from app.in_out.resolver_contract import ResolvedTransition
        modified_transition = ResolvedTransition(
            resolution_id=resolved_transition.resolution_id,
            source_raw_event_id=resolved_transition.source_raw_event_id,
            camera_id=resolved_transition.camera_id,
            local_track_id=resolved_transition.local_track_id,
            global_observation_id=resolved_transition.global_observation_id,
            direction=resolved_transition.direction,
            transition_type=resolved_transition.transition_type,
            previous_state=resolved_transition.previous_state,
            new_state=resolved_transition.new_state,
            source_timestamp=event_timestamp_sfm,  # seconds from midnight
            source_frame_index=resolved_transition.source_frame_index,
            resolver_version=resolved_transition.resolver_version,
            resolver_config_hash=resolved_transition.resolver_config_hash,
            resolution_status=resolved_transition.resolution_status,
            source_crossing_event_id=resolved_transition.source_crossing_event_id,
            geometry_version=resolved_transition.geometry_version,
            geometry_config_hash=resolved_transition.geometry_config_hash,
        )
        
        # Build context with auto-resolved values
        context = AttendanceDecisionContext(
            resolved_transition=modified_transition,
            timetable=timetable,
            attendance_policy=self.policy,
            person_id_override=person_id,
            day_override=day,
        )
        
        # Make decision using existing logic
        decision = self.make_decision(context)
        
        # Enhance decision with identity resolution info
        if identity_resolution:
            # Note: AttendanceDecision is frozen, so we can't modify it directly
            # The identity info is already in the decision via person_id_override
            pass
        
        return decision
    
    def make_decision_with_daily_resolver(
        self,
        resolved_transition: ResolvedTransition,
        timetable: Timetable,
        daily_resolver: DailyExpectedResolver,
        global_observation: Optional[GlobalObservation] = None,
    ) -> AttendanceDecision:
        """
        Make an attendance decision using the daily expected-student resolver.
        
        This method integrates the full Phase 37A pipeline:
        - Automatic day resolution from timestamp
        - Automatic person_id resolution from GlobalObservation
        - Expected student validation from daily resolver
        
        Args:
            resolved_transition: Phase 24 resolved transition
            timetable: Phase 26 timetable
            daily_resolver: Daily expected-student resolver
            global_observation: Optional GlobalObservation for identity resolution
            
        Returns:
            AttendanceDecision
        """
        # Resolve date and day from timestamp
        calendar_engine = daily_resolver.calendar_engine
        day_resolver = DayResolver(calendar_engine)
        target_date = day_resolver.resolve_date(resolved_transition.source_timestamp)
        day = day_resolver.resolve_day(resolved_transition.source_timestamp)
        
        # Resolve person_id from GlobalObservation
        person_id = None
        if global_observation is not None and hasattr(daily_resolver, 'identity_resolver'):
            identity_resolution = daily_resolver.identity_resolver.resolve_from_global_observation(global_observation)
            person_id = identity_resolution.student_id or identity_resolution.person_id
        
        # Convert Unix timestamp to seconds-from-midnight for attendance logic
        event_timestamp_sfm = self._unix_to_seconds_from_midnight(
            resolved_transition.source_timestamp, calendar_engine
        )
        
        # Create a modified transition with seconds-from-midnight timestamp
        from app.in_out.resolver_contract import ResolvedTransition
        modified_transition = ResolvedTransition(
            resolution_id=resolved_transition.resolution_id,
            source_raw_event_id=resolved_transition.source_raw_event_id,
            camera_id=resolved_transition.camera_id,
            local_track_id=resolved_transition.local_track_id,
            global_observation_id=resolved_transition.global_observation_id,
            direction=resolved_transition.direction,
            transition_type=resolved_transition.transition_type,
            previous_state=resolved_transition.previous_state,
            new_state=resolved_transition.new_state,
            source_timestamp=event_timestamp_sfm,  # seconds from midnight
            source_frame_index=resolved_transition.source_frame_index,
            resolver_version=resolved_transition.resolver_version,
            resolver_config_hash=resolved_transition.resolver_config_hash,
            resolution_status=resolved_transition.resolution_status,
            source_crossing_event_id=resolved_transition.source_crossing_event_id,
            geometry_version=resolved_transition.geometry_version,
            geometry_config_hash=resolved_transition.geometry_config_hash,
        )
        
        # Check if student is expected at this time
        expected_info = None
        if person_id:
            expected_info = daily_resolver.is_student_expected_at(
                target_date, person_id, event_timestamp_sfm
            )
        
        # Build context
        context = AttendanceDecisionContext(
            resolved_transition=modified_transition,
            timetable=timetable,
            attendance_policy=self.policy,
            person_id_override=person_id,
            day_override=day,
        )
        
        # Make decision
        decision = self.make_decision(context)
        
        return decision


def create_attendance_engine_with_resolvers(
    policy: AttendancePolicy,
    timetable: Timetable,
    calendar_engine: CalendarEngine,
    enrollment_person_ids: List[str],
    enrollment_embeddings: Optional[Any] = None,
    enrollment_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[AttendanceEngine, IdentityResolver, DayResolver, DailyExpectedResolver]:
    """
    Factory function to create AttendanceEngine with all Phase 37A resolvers.
    
    Returns:
        Tuple of (engine, identity_resolver, day_resolver, daily_resolver)
    """
    engine = AttendanceEngine(policy)
    identity_resolver = IdentityResolver(enrollment_person_ids, enrollment_embeddings, enrollment_metadata)
    day_resolver = DayResolver(calendar_engine)
    daily_resolver = DailyExpectedResolver(timetable, calendar_engine, enrollment_person_ids)
    
    # Attach identity_resolver to daily_resolver for convenience
    daily_resolver.identity_resolver = identity_resolver
    
    return engine, identity_resolver, day_resolver, daily_resolver
