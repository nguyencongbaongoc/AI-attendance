"""
Phase 29 — Immediate Event Adapters.

Adapters that convert upstream events (Phase 24 ResolvedTransition, Phase 26 AttendanceDecision)
into ImmediateEvent for delivery.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.in_out.resolver_contract import (
    ResolvedTransition,
    TransitionType,
    ResolutionStatus,
)
from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    IdentityCertainty as RawIdentityCertainty,
)
from app.attendance.policy import (
    AttendanceDecision,
    DecisionReason,
)
from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    IdentityCertainty as AttendanceIdentityCertainty,
)
from app.output.contract import (
    ImmediateEvent,
    ImmediateEventType,
    ImmediateEventDirection,
    IdentityCertainty,
    EventDeliveryStatus,
    generate_immediate_event_id,
    validate_immediate_event,
    ImmediateEventCreationResult,
)
from app.output.publisher import (
    EventPublisher,
    CallbackEventBus,
    SubscriberConfig,
    BackpressurePolicy,
)

logger = logging.getLogger(__name__)


class ImmediateEventAdapter(ABC):
    """Abstract base class for immediate event adapters."""
    
    @abstractmethod
    def convert(self, source_event: Any) -> ImmediateEventCreationResult:
        """Convert a source event to an ImmediateEvent."""
        pass
    
    @abstractmethod
    def get_source_type(self) -> str:
        """Get the source event type this adapter handles."""
        pass


class Phase24ToImmediateEventAdapter(ImmediateEventAdapter):
    """
    Adapter that converts Phase 24 ResolvedTransition to ImmediateEvent.
    
    Only emits events for actual transitions (not suppressed/rejected).
    """
    
    def __init__(self, publisher: EventPublisher):
        self._publisher = publisher
    
    def get_source_type(self) -> str:
        return "ResolvedTransition"
    
    def convert(self, resolution: ResolvedTransition) -> ImmediateEventCreationResult:
        """
        Convert a ResolvedTransition to an ImmediateEvent.
        
        Only creates events for actual transitions (ACCEPTED with IN/OUT transition).
        Suppressed/rejected events are not emitted as immediate events.
        """
        # Only emit for actual transitions
        if not resolution.is_transition:
            return ImmediateEventCreationResult.failure_result(
                error=f"Resolution {resolution.resolution_id} is not a transition (type: {resolution.transition_type.value})",
                rejection_reason="not_a_transition"
            )
        
        # Only emit ACCEPTED resolutions
        if resolution.resolution_status != ResolutionStatus.ACCEPTED:
            return ImmediateEventCreationResult.failure_result(
                error=f"Resolution {resolution.resolution_id} has status {resolution.resolution_status.value}",
                rejection_reason="not_accepted"
            )
        
        # Map direction
        direction = ImmediateEventDirection.IN if resolution.direction == "in" else ImmediateEventDirection.OUT
        
        # Map event type
        event_type = ImmediateEventType.RESOLUTION_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.RESOLUTION_OUT
        
        # Map identity certainty
        identity_certainty = self._map_identity_certainty(resolution)
        
        # Generate deterministic event ID
        event_id = generate_immediate_event_id(
            source_resolution_id=resolution.resolution_id,
            event_type=event_type,
        )
        
        # Create immediate event
        event = ImmediateEvent(
            event_id=event_id,
            event_type=event_type,
            direction=direction,
            identity_certainty=identity_certainty,
            identity_candidate=None,  # Not available in ResolvedTransition
            identity_confidence=0.0,
            identity_evidence_ref=resolution.global_observation_id,
            event_timestamp=resolution.source_timestamp,
            event_frame_index=resolution.source_frame_index,
            camera_id=resolution.camera_id,
            local_track_id=resolution.local_track_id,
            global_observation_id=resolution.global_observation_id,
            source_raw_event_id=resolution.source_raw_event_id,
            source_resolution_id=resolution.resolution_id,
            source_crossing_event_id=resolution.source_crossing_event_id,
            geometry_version=resolution.geometry_version,
            geometry_config_hash=resolution.geometry_config_hash,
            resolver_version=resolution.resolver_version,
            resolver_config_hash=resolution.resolver_config_hash,
            delivery_status=EventDeliveryStatus.NEW,
        )
        
        # Validate
        validation_error = validate_immediate_event(event)
        if validation_error:
            return ImmediateEventCreationResult.failure_result(
                error=validation_error,
                rejection_reason="validation_failed"
            )
        
        return ImmediateEventCreationResult.success_result(event)
    
    def _map_identity_certainty(self, resolution: ResolvedTransition) -> IdentityCertainty:
        """Map identity certainty from resolution (limited info available)."""
        # ResolvedTransition doesn't directly carry identity certainty
        # It would need to be enriched from the raw event
        # For now, return UNKNOWN as default
        return IdentityCertainty.UNKNOWN
    
    def publish(self, resolution: ResolvedTransition) -> bool:
        """Convert and publish a resolution."""
        result = self.convert(resolution)
        if result.success and result.event:
            return self._publisher.publish(result.event)
        return False


class Phase26ToImmediateEventAdapter(ImmediateEventAdapter):
    """
    Adapter that converts Phase 26 AttendanceDecision to ImmediateEvent.
    
    This is the primary adapter for production use - it includes attendance state.
    """
    
    def __init__(self, publisher: EventPublisher):
        self._publisher = publisher
    
    def get_source_type(self) -> str:
        return "AttendanceDecision"
    
    def convert(self, decision: AttendanceDecision) -> ImmediateEventCreationResult:
        """
        Convert an AttendanceDecision to an ImmediateEvent.
        
        Includes full attendance state and decision reason.
        """
        # Map direction
        direction = ImmediateEventDirection.IN if decision.direction == "in" else ImmediateEventDirection.OUT
        
        # Map event type
        event_type = ImmediateEventType.ATTENDANCE_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT
        
        # Map identity certainty
        identity_certainty = self._map_identity_certainty(decision.identity_certainty)
        
        # Generate deterministic event ID
        event_id = generate_immediate_event_id(
            source_resolution_id=decision.source_resolution_id,
            event_type=event_type,
        )
        
        # Create immediate event with full attendance provenance
        event = ImmediateEvent(
            event_id=event_id,
            event_type=event_type,
            direction=direction,
            identity_certainty=identity_certainty,
            identity_candidate=decision.identity_candidate,
            identity_confidence=decision.identity_confidence,
            identity_evidence_ref=decision.identity_evidence_ref,
            event_timestamp=decision.event_timestamp,
            event_frame_index=decision.event_frame_index,
            camera_id=decision.camera_id,
            local_track_id=decision.local_track_id,
            global_observation_id=decision.global_observation_id,
            source_raw_event_id=decision.source_raw_event_id,
            source_resolution_id=decision.source_resolution_id,
            source_crossing_event_id=decision.source_crossing_event_id,
            source_attendance_decision_id=decision.decision_id,
            geometry_version=decision.geometry_version,
            geometry_config_hash=decision.geometry_config_hash,
            resolver_version=decision.resolver_version,
            resolver_config_hash=decision.resolver_config_hash,
            attendance_policy_id=decision.attendance_policy_id,
            attendance_policy_version=decision.attendance_policy_version,
            previous_attendance_state=decision.previous_attendance_state,
            new_attendance_state=decision.new_attendance_state,
            decision_reason=decision.decision_reason,
            timetable_id=decision.timetable_id,
            timetable_version=decision.timetable_version,
            session_id=decision.session_id,
            day=decision.day,
            delivery_status=EventDeliveryStatus.NEW,
        )
        
        # Validate
        validation_error = validate_immediate_event(event)
        if validation_error:
            return ImmediateEventCreationResult.failure_result(
                error=validation_error,
                rejection_reason="validation_failed"
            )
        
        return ImmediateEventCreationResult.success_result(event)
    
    def _map_identity_certainty(self, certainty: str) -> IdentityCertainty:
        """Map identity certainty string to enum."""
        mapping = {
            "known": IdentityCertainty.KNOWN,
            "unknown": IdentityCertainty.UNKNOWN,
            "ambiguous": IdentityCertainty.AMBIGUOUS,
            "insufficient": IdentityCertainty.INSUFFICIENT,
        }
        return mapping.get(certainty.lower(), IdentityCertainty.UNKNOWN)
    
    def publish(self, decision: AttendanceDecision) -> bool:
        """Convert and publish a decision."""
        result = self.convert(decision)
        if result.success and result.event:
            return self._publisher.publish(result.event)
        return False


class Phase25ToImmediateEventAdapter(ImmediateEventAdapter):
    """
    Adapter that converts Phase 25 AttendanceRecord to ImmediateEvent.
    
    Used for historical event replay from persistence.
    """
    
    def __init__(self, publisher: EventPublisher):
        self._publisher = publisher
    
    def get_source_type(self) -> str:
        return "AttendanceRecord"
    
    def convert(self, record: AttendanceRecord) -> ImmediateEventCreationResult:
        """
        Convert an AttendanceRecord to an ImmediateEvent.
        
        Marks as HISTORICAL delivery status.
        """
        # Map direction
        direction = ImmediateEventDirection.IN if record.direction == AttendanceDirection.IN else ImmediateEventDirection.OUT
        
        # Map event type (attendance events from persistence)
        event_type = ImmediateEventType.ATTENDANCE_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT
        
        # Map identity certainty
        identity_certainty = self._map_identity_certainty(record.identity_certainty)
        
        # Generate deterministic event ID
        event_id = generate_immediate_event_id(
            source_resolution_id=record.source_resolution_id,
            event_type=event_type,
        )
        
        # Create immediate event with historical status
        event = ImmediateEvent(
            event_id=event_id,
            event_type=event_type,
            direction=direction,
            identity_certainty=identity_certainty,
            identity_candidate=record.identity_candidate,
            identity_confidence=record.identity_confidence,
            identity_evidence_ref=record.identity_evidence_ref,
            event_timestamp=record.event_timestamp,
            event_frame_index=record.event_frame_index,
            camera_id=record.camera_id,
            local_track_id=record.local_track_id,
            global_observation_id=record.global_observation_id,
            source_raw_event_id=record.source_raw_event_id,
            source_resolution_id=record.source_resolution_id,
            source_crossing_event_id=record.source_crossing_event_id,
            source_attendance_record_id=record.attendance_record_id,
            geometry_version=record.geometry_version,
            geometry_config_hash=record.geometry_config_hash,
            resolver_version=record.resolver_version,
            resolver_config_hash=record.resolver_config_hash,
            delivery_status=EventDeliveryStatus.HISTORICAL,
        )
        
        # Validate
        validation_error = validate_immediate_event(event)
        if validation_error:
            return ImmediateEventCreationResult.failure_result(
                error=validation_error,
                rejection_reason="validation_failed"
            )
        
        return ImmediateEventCreationResult.success_result(event)
    
    def _map_identity_certainty(self, certainty: AttendanceIdentityCertainty) -> IdentityCertainty:
        """Map identity certainty from attendance record."""
        mapping = {
            AttendanceIdentityCertainty.KNOWN: IdentityCertainty.KNOWN,
            AttendanceIdentityCertainty.UNKNOWN: IdentityCertainty.UNKNOWN,
            AttendanceIdentityCertainty.AMBIGUOUS: IdentityCertainty.AMBIGUOUS,
            AttendanceIdentityCertainty.INSUFFICIENT: IdentityCertainty.INSUFFICIENT,
        }
        return mapping.get(certainty, IdentityCertainty.UNKNOWN)
    
    def publish(self, record: AttendanceRecord) -> bool:
        """Convert and publish a record."""
        result = self.convert(record)
        if result.success and result.event:
            return self._publisher.publish(result.event)
        return False


class Phase23ToImmediateEventAdapter(ImmediateEventAdapter):
    """
    Adapter that converts Phase 23 RawInOutEvent to ImmediateEvent.
    
    Used for raw event streaming (debugging, monitoring).
    """
    
    def __init__(self, publisher: EventPublisher):
        self._publisher = publisher
    
    def get_source_type(self) -> str:
        return "RawInOutEvent"
    
    def convert(self, raw_event: RawInOutEvent) -> ImmediateEventCreationResult:
        """
        Convert a RawInOutEvent to an ImmediateEvent.
        """
        # Map direction
        direction = ImmediateEventDirection.IN if raw_event.direction == RawEventDirection.IN else ImmediateEventDirection.OUT
        
        # Map event type
        event_type = ImmediateEventType.RAW_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.RAW_OUT
        
        # Map identity certainty
        identity_certainty = self._map_identity_certainty(raw_event.identity_certainty)
        
        # Generate deterministic event ID
        event_id = generate_immediate_event_id(
            source_resolution_id=raw_event.event_id,  # Use raw event ID as source
            event_type=event_type,
        )
        
        # Create immediate event
        event = ImmediateEvent(
            event_id=event_id,
            event_type=event_type,
            direction=direction,
            identity_certainty=identity_certainty,
            identity_candidate=raw_event.identity_candidate,
            identity_confidence=raw_event.identity_confidence,
            identity_evidence_ref=raw_event.identity_evidence_ref,
            event_timestamp=raw_event.crossing_timestamp,
            event_frame_index=raw_event.crossing_frame_index,
            camera_id=raw_event.camera_id,
            local_track_id=raw_event.local_track_id,
            global_observation_id=raw_event.global_observation_id,
            source_raw_event_id=raw_event.event_id,
            source_resolution_id=raw_event.event_id,  # No resolution yet
            source_crossing_event_id=raw_event.source_crossing_event_id,
            geometry_version=raw_event.geometry_version,
            geometry_config_hash=raw_event.geometry_config_hash,
            delivery_status=EventDeliveryStatus.NEW,
        )
        
        # Validate
        validation_error = validate_immediate_event(event)
        if validation_error:
            return ImmediateEventCreationResult.failure_result(
                error=validation_error,
                rejection_reason="validation_failed"
            )
        
        return ImmediateEventCreationResult.success_result(event)
    
    def _map_identity_certainty(self, certainty: RawIdentityCertainty) -> IdentityCertainty:
        """Map identity certainty from raw event."""
        mapping = {
            RawIdentityCertainty.KNOWN: IdentityCertainty.KNOWN,
            RawIdentityCertainty.UNKNOWN: IdentityCertainty.UNKNOWN,
            RawIdentityCertainty.AMBIGUOUS: IdentityCertainty.AMBIGUOUS,
            RawIdentityCertainty.INSUFFICIENT: IdentityCertainty.INSUFFICIENT,
        }
        return mapping.get(certainty, IdentityCertainty.UNKNOWN)
    
    def publish(self, raw_event: RawInOutEvent) -> bool:
        """Convert and publish a raw event."""
        result = self.convert(raw_event)
        if result.success and result.event:
            return self._publisher.publish(result.event)
        return False


class DevelopmentEventSource:
    """
    Development event source that generates deterministic test events.
    
    Clearly distinguished from live production events.
    """
    
    def __init__(self, publisher: EventPublisher):
        self._publisher = publisher
        self._sequence = 0
        self._lock = __import__('threading').Lock()
    
    def generate_test_events(self, count: int = 10) -> List[ImmediateEvent]:
        """Generate deterministic test events for development."""
        events = []
        
        test_data = [
            {"person_id": "HS001", "camera": "CAM1", "track": "A17", "certainty": IdentityCertainty.KNOWN, "confidence": 0.987, "direction": ImmediateEventDirection.IN},
            {"person_id": "HS004", "camera": "CAM2", "track": "B04", "certainty": IdentityCertainty.KNOWN, "confidence": 0.956, "direction": ImmediateEventDirection.IN},
            {"person_id": "HS017", "camera": "CAM1", "track": "C02", "certainty": IdentityCertainty.KNOWN, "confidence": 0.923, "direction": ImmediateEventDirection.OUT},
            {"person_id": "HS008", "camera": "CAM1", "track": "A19", "certainty": IdentityCertainty.AMBIGUOUS, "confidence": 0.612, "direction": ImmediateEventDirection.IN},
            {"person_id": "HS023", "camera": "CAM2", "track": "B11", "certainty": IdentityCertainty.UNKNOWN, "confidence": 0.0, "direction": ImmediateEventDirection.IN},
            {"person_id": "HS005", "camera": "CAM1", "track": "A03", "certainty": IdentityCertainty.KNOWN, "confidence": 0.991, "direction": ImmediateEventDirection.OUT},
        ]
        
        base_time = 1700000000  # Fixed base timestamp for determinism
        
        for i in range(min(count, len(test_data))):
            data = test_data[i]
            self._sequence += 1
            
            # Create a fake resolution ID for deduplication
            resolution_id = f"RES-DEV-{self._sequence:06d}"
            
            event = ImmediateEvent(
                event_id=generate_immediate_event_id(
                    source_resolution_id=resolution_id,
                    event_type=ImmediateEventType.ATTENDANCE_IN if data["direction"] == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT,
                ),
                event_type=ImmediateEventType.ATTENDANCE_IN if data["direction"] == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT,
                direction=data["direction"],
                identity_certainty=data["certainty"],
                identity_candidate=data["person_id"],
                identity_confidence=data["confidence"],
                identity_evidence_ref=f"GO-DEV-{self._sequence:03d}",
                event_timestamp=base_time + i * 60,  # 1 minute apart
                event_frame_index=i * 30,
                camera_id=data["camera"],
                local_track_id=data["track"],
                global_observation_id=f"GO-DEV-{self._sequence:03d}",
                source_raw_event_id=f"RIE-DEV-{self._sequence:06d}",
                source_resolution_id=resolution_id,
                source_crossing_event_id=f"CE-DEV-{self._sequence:06d}",
                source_attendance_decision_id=f"DEC-DEV-{self._sequence:06d}",
                geometry_version=1,
                geometry_config_hash="dev_hash_001",
                resolver_version="1.0",
                resolver_config_hash="dev_resolver_hash",
                attendance_policy_id="policy_default",
                attendance_policy_version="1.0",
                previous_attendance_state="unknown" if data["direction"] == ImmediateEventDirection.IN else "present",
                new_attendance_state="present" if data["direction"] == ImmediateEventDirection.IN else "left",
                decision_reason="within_entry_window" if data["direction"] == ImmediateEventDirection.IN else "exit_recorded",
                timetable_id="timetable_2024",
                timetable_version="1.0",
                session_id="morning",
                day="monday",
                delivery_status=EventDeliveryStatus.NEW,
                delivery_sequence=self._sequence,
            )
            
            events.append(event)
        
        return events
    
    def publish_test_events(self, count: int = 10) -> int:
        """Generate and publish test events."""
        events = self.generate_test_events(count)
        published = 0
        for event in events:
            if self._publisher.publish(event):
                published += 1
        return published
    
    def publish_single_event(
        self,
        person_id: str = "HS001",
        camera_id: str = "CAM1",
        track_id: str = "A17",
        direction: ImmediateEventDirection = ImmediateEventDirection.IN,
        certainty: IdentityCertainty = IdentityCertainty.KNOWN,
        confidence: float = 0.987,
    ) -> bool:
        """Publish a single deterministic test event."""
        self._sequence += 1
        resolution_id = f"RES-DEV-{self._sequence:06d}"
        
        event = ImmediateEvent(
            event_id=generate_immediate_event_id(
                source_resolution_id=resolution_id,
                event_type=ImmediateEventType.ATTENDANCE_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT,
            ),
            event_type=ImmediateEventType.ATTENDANCE_IN if direction == ImmediateEventDirection.IN else ImmediateEventType.ATTENDANCE_OUT,
            direction=direction,
            identity_certainty=certainty,
            identity_candidate=person_id,
            identity_confidence=confidence,
            identity_evidence_ref=f"GO-DEV-{self._sequence:03d}",
            event_timestamp=1700000000 + self._sequence * 60,
            event_frame_index=self._sequence * 30,
            camera_id=camera_id,
            local_track_id=track_id,
            global_observation_id=f"GO-DEV-{self._sequence:03d}",
            source_raw_event_id=f"RIE-DEV-{self._sequence:06d}",
            source_resolution_id=resolution_id,
            source_crossing_event_id=f"CE-DEV-{self._sequence:06d}",
            source_attendance_decision_id=f"DEC-DEV-{self._sequence:06d}",
            geometry_version=1,
            geometry_config_hash="dev_hash_001",
            resolver_version="1.0",
            resolver_config_hash="dev_resolver_hash",
            attendance_policy_id="policy_default",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown" if direction == ImmediateEventDirection.IN else "present",
            new_attendance_state="present" if direction == ImmediateEventDirection.IN else "left",
            decision_reason="within_entry_window" if direction == ImmediateEventDirection.IN else "exit_recorded",
            timetable_id="timetable_2024",
            timetable_version="1.0",
            session_id="morning",
            day="monday",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=self._sequence,
        )
        
        return self._publisher.publish(event)


def create_adapters(publisher: EventPublisher) -> Dict[str, ImmediateEventAdapter]:
    """Factory function to create all adapters."""
    return {
        "phase24": Phase24ToImmediateEventAdapter(publisher),
        "phase26": Phase26ToImmediateEventAdapter(publisher),
        "phase25": Phase25ToImmediateEventAdapter(publisher),
        "phase23": Phase23ToImmediateEventAdapter(publisher),
    }


def create_development_source(publisher: EventPublisher) -> DevelopmentEventSource:
    """Factory function to create development event source."""
    return DevelopmentEventSource(publisher)