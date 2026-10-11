"""
Phase 29 — Unit Tests for Event Adapters.

Tests:
- Phase 24 to ImmediateEvent adapter
- Phase 26 to ImmediateEvent adapter
- Phase 25 to ImmediateEvent adapter
- Phase 23 to ImmediateEvent adapter
- Development event source
"""

import pytest
from datetime import datetime

from app.in_out.resolver_contract import (
    ResolvedTransition,
    TransitionType,
    ResolutionStatus,
    DerivedState,
)
from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
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
)
from app.output.adapter import (
    Phase24ToImmediateEventAdapter,
    Phase26ToImmediateEventAdapter,
    Phase25ToImmediateEventAdapter,
    Phase23ToImmediateEventAdapter,
    DevelopmentEventSource,
    create_adapters,
    create_development_source,
)
from app.output.publisher import (
    CallbackEventBus,
    create_event_bus,
)


class TestPhase24Adapter:
    """Tests for Phase 24 to ImmediateEvent adapter."""
    
    def create_resolved_transition(self, transition_type: TransitionType = TransitionType.IN) -> ResolvedTransition:
        """Create a sample ResolvedTransition."""
        return ResolvedTransition(
            resolution_id="RES-001",
            source_raw_event_id="RIE-001",
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            direction="in" if transition_type == TransitionType.IN else "out",
            transition_type=transition_type,
            previous_state=DerivedState.UNKNOWN,
            new_state=DerivedState.INSIDE if transition_type == TransitionType.IN else DerivedState.OUTSIDE,
            source_timestamp=1700000000.0,
            source_frame_index=100,
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            resolution_status=ResolutionStatus.ACCEPTED,
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolution_schema_version="1.0",
        )
    
    def test_convert_accepted_in_transition(self):
        """Test converting an ACCEPTED IN transition."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.IN)
        
        result = adapter.convert(resolution)
        
        assert result.success is True
        assert result.event is not None
        assert result.event.event_type == ImmediateEventType.RESOLUTION_IN
        assert result.event.direction == ImmediateEventDirection.IN
        assert result.event.source_resolution_id == "RES-001"
        assert result.event.source_raw_event_id == "RIE-001"
    
    def test_convert_accepted_out_transition(self):
        """Test converting an ACCEPTED OUT transition."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.OUT)
        
        result = adapter.convert(resolution)
        
        assert result.success is True
        assert result.event.event_type == ImmediateEventType.RESOLUTION_OUT
        assert result.event.direction == ImmediateEventDirection.OUT
    
    def test_reject_suppressed_transition(self):
        """Test that SUPPRESSED transitions are rejected."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.IN)
        resolution = ResolvedTransition(
            **{**resolution.to_dict(), "resolution_status": ResolutionStatus.SUPPRESSED}
        )
        
        result = adapter.convert(resolution)
        
        assert result.success is False
        assert result.rejection_reason == "not_accepted"
    
    def test_reject_rejected_transition(self):
        """Test that REJECTED transitions are rejected."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.IN)
        resolution = ResolvedTransition(
            **{**resolution.to_dict(), "resolution_status": ResolutionStatus.REJECTED}
        )
        
        result = adapter.convert(resolution)
        
        assert result.success is False
        assert result.rejection_reason == "not_accepted"
    
    def test_reject_none_transition(self):
        """Test that NONE transitions are rejected."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.NONE)
        
        result = adapter.convert(resolution)
        
        assert result.success is False
        assert result.rejection_reason == "not_a_transition"
    
    def test_publish_integration(self):
        """Test publishing through adapter."""
        bus = create_event_bus()
        adapter = Phase24ToImmediateEventAdapter(bus)
        resolution = self.create_resolved_transition(TransitionType.IN)
        
        result = adapter.publish(resolution)
        
        assert result is True
        history = bus.get_history(10)
        assert len(history) == 1
        assert history[0].event_type == ImmediateEventType.RESOLUTION_IN


class TestPhase26Adapter:
    """Tests for Phase 26 to ImmediateEvent adapter."""
    
    def create_attendance_decision(self, direction: str = "in") -> AttendanceDecision:
        """Create a sample AttendanceDecision."""
        return AttendanceDecision(
            decision_id="DEC-001",
            identity_certainty="known",
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            direction=direction,
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            timetable_id="timetable_2024",
            timetable_version="1.0",
            session_id="morning",
            day="monday",
            previous_attendance_state="unknown" if direction == "in" else "present",
            new_attendance_state="present" if direction == "in" else "left",
            decision_reason="within_entry_window" if direction == "in" else "exit_recorded",
            attendance_policy_id="policy_default",
            attendance_policy_version="1.0",
            decision_schema_version="1.0",
        )
    
    def test_convert_in_decision(self):
        """Test converting an IN attendance decision."""
        bus = create_event_bus()
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = self.create_attendance_decision("in")
        
        result = adapter.convert(decision)
        
        assert result.success is True
        assert result.event is not None
        assert result.event.event_type == ImmediateEventType.ATTENDANCE_IN
        assert result.event.direction == ImmediateEventDirection.IN
        assert result.event.identity_certainty == IdentityCertainty.KNOWN
        assert result.event.identity_candidate == "HS001"
        assert result.event.identity_confidence == 0.987
        assert result.event.new_attendance_state == "present"
        assert result.event.decision_reason == "within_entry_window"
        assert result.event.source_attendance_decision_id == "DEC-001"
    
    def test_convert_out_decision(self):
        """Test converting an OUT attendance decision."""
        bus = create_event_bus()
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = self.create_attendance_decision("out")
        
        result = adapter.convert(decision)
        
        assert result.success is True
        assert result.event.event_type == ImmediateEventType.ATTENDANCE_OUT
        assert result.event.direction == ImmediateEventDirection.OUT
        assert result.event.new_attendance_state == "left"
        assert result.event.decision_reason == "exit_recorded"
    
    def test_convert_unknown_identity(self):
        """Test converting decision with UNKNOWN identity."""
        bus = create_event_bus()
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = self.create_attendance_decision("in")
        decision = AttendanceDecision(
            **{**decision.to_dict(), "identity_certainty": "unknown", "identity_candidate": None, "identity_confidence": 0.0}
        )
        
        result = adapter.convert(decision)
        
        assert result.success is True
        assert result.event.identity_certainty == IdentityCertainty.UNKNOWN
        assert result.event.identity_candidate is None
        assert result.event.identity_confidence == 0.0
    
    def test_convert_ambiguous_identity(self):
        """Test converting decision with AMBIGUOUS identity."""
        bus = create_event_bus()
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = self.create_attendance_decision("in")
        decision = AttendanceDecision(
            **{**decision.to_dict(), "identity_certainty": "ambiguous", "identity_candidate": "HS008", "identity_confidence": 0.612}
        )
        
        result = adapter.convert(decision)
        
        assert result.success is True
        assert result.event.identity_certainty == IdentityCertainty.AMBIGUOUS
        assert result.event.identity_candidate == "HS008"
        assert result.event.identity_confidence == 0.612
    
    def test_publish_integration(self):
        """Test publishing through adapter."""
        bus = create_event_bus()
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = self.create_attendance_decision("in")
        
        result = adapter.publish(decision)
        
        assert result is True
        history = bus.get_history(10)
        assert len(history) == 1
        assert history[0].event_type == ImmediateEventType.ATTENDANCE_IN
        assert history[0].new_attendance_state == "present"


class TestPhase25Adapter:
    """Tests for Phase 25 to ImmediateEvent adapter."""
    
    def create_attendance_record(self, direction: AttendanceDirection = AttendanceDirection.IN) -> AttendanceRecord:
        """Create a sample AttendanceRecord."""
        return AttendanceRecord(
            attendance_record_id="ATT-001",
            identity_certainty=AttendanceIdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            direction=direction,
            event_timestamp=1700000000.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            previous_state="unknown" if direction == AttendanceDirection.IN else "inside",
            new_state="inside" if direction == AttendanceDirection.IN else "outside",
            attendance_schema_version="1.0",
        )
    
    def test_convert_in_record(self):
        """Test converting an IN attendance record."""
        bus = create_event_bus()
        adapter = Phase25ToImmediateEventAdapter(bus)
        record = self.create_attendance_record(AttendanceDirection.IN)
        
        result = adapter.convert(record)
        
        assert result.success is True
        assert result.event is not None
        assert result.event.event_type == ImmediateEventType.ATTENDANCE_IN
        assert result.event.direction == ImmediateEventDirection.IN
        assert result.event.delivery_status == EventDeliveryStatus.HISTORICAL
        assert result.event.source_attendance_record_id == "ATT-001"
    
    def test_convert_out_record(self):
        """Test converting an OUT attendance record."""
        bus = create_event_bus()
        adapter = Phase25ToImmediateEventAdapter(bus)
        record = self.create_attendance_record(AttendanceDirection.OUT)
        
        result = adapter.convert(record)
        
        assert result.success is True
        assert result.event.event_type == ImmediateEventType.ATTENDANCE_OUT
        assert result.event.direction == ImmediateEventDirection.OUT
        assert result.event.delivery_status == EventDeliveryStatus.HISTORICAL
    
    def test_publish_integration(self):
        """Test publishing through adapter."""
        bus = create_event_bus()
        adapter = Phase25ToImmediateEventAdapter(bus)
        record = self.create_attendance_record(AttendanceDirection.IN)
        
        result = adapter.publish(record)
        
        assert result is True
        history = bus.get_history(10)
        assert len(history) == 1
        assert history[0].delivery_status == EventDeliveryStatus.HISTORICAL


class TestPhase23Adapter:
    """Tests for Phase 23 to ImmediateEvent adapter."""
    
    def create_raw_event(self, direction: RawEventDirection = RawEventDirection.IN) -> RawInOutEvent:
        """Create a sample RawInOutEvent."""
        return RawInOutEvent(
            event_id="RIE-001",
            camera_id="CAM1",
            geometry_id="GEOM-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            local_track_id="A17",
            global_observation_id="GO-001",
            event_type=RawEventType.LINE_CROSSING,
            direction=direction,
            crossing_point_x=100.0,
            crossing_point_y=200.0,
            crossing_timestamp=1700000000.0,
            crossing_frame_index=100,
            previous_position_x=90.0,
            previous_position_y=190.0,
            current_position_x=110.0,
            current_position_y=210.0,
            previous_frame_index=99,
            current_frame_index=101,
            previous_timestamp=1699999999.0,
            current_timestamp=1700000001.0,
            crossing_distance=28.28,
            side_transition="outside_to_inside",
            identity_certainty=RawIdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            source_crossing_event_id="CE-001",
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.0",
        )
    
    def test_convert_in_raw_event(self):
        """Test converting an IN raw event."""
        bus = create_event_bus()
        adapter = Phase23ToImmediateEventAdapter(bus)
        raw_event = self.create_raw_event(RawEventDirection.IN)
        
        result = adapter.convert(raw_event)
        
        assert result.success is True
        assert result.event is not None
        assert result.event.event_type == ImmediateEventType.RAW_IN
        assert result.event.direction == ImmediateEventDirection.IN
        assert result.event.identity_certainty == IdentityCertainty.KNOWN
        assert result.event.identity_candidate == "HS001"
        assert result.event.source_raw_event_id == "RIE-001"
        assert result.event.source_resolution_id == "RIE-001"  # Uses raw event ID as resolution ID
    
    def test_convert_out_raw_event(self):
        """Test converting an OUT raw event."""
        bus = create_event_bus()
        adapter = Phase23ToImmediateEventAdapter(bus)
        raw_event = self.create_raw_event(RawEventDirection.OUT)
        
        result = adapter.convert(raw_event)
        
        assert result.success is True
        assert result.event.event_type == ImmediateEventType.RAW_OUT
        assert result.event.direction == ImmediateEventDirection.OUT
    
    def test_publish_integration(self):
        """Test publishing through adapter."""
        bus = create_event_bus()
        adapter = Phase23ToImmediateEventAdapter(bus)
        raw_event = self.create_raw_event(RawEventDirection.IN)
        
        result = adapter.publish(raw_event)
        
        assert result is True
        history = bus.get_history(10)
        assert len(history) == 1
        assert history[0].event_type == ImmediateEventType.RAW_IN


class TestDevelopmentEventSource:
    """Tests for development event source."""
    
    def test_generate_test_events(self):
        """Test generating deterministic test events."""
        bus = create_event_bus()
        dev_source = DevelopmentEventSource(bus)
        
        events = dev_source.generate_test_events(6)
        
        assert len(events) == 6
        assert events[0].identity_candidate == "HS001"
        assert events[0].direction == ImmediateEventDirection.IN
        assert events[2].direction == ImmediateEventDirection.OUT
        assert events[3].identity_certainty == IdentityCertainty.AMBIGUOUS
        assert events[4].identity_certainty == IdentityCertainty.UNKNOWN
    
    def test_deterministic_generation(self):
        """Test that event generation is deterministic."""
        bus1 = create_event_bus()
        bus2 = create_event_bus()
        dev1 = DevelopmentEventSource(bus1)
        dev2 = DevelopmentEventSource(bus2)
        
        events1 = dev1.generate_test_events(6)
        events2 = dev2.generate_test_events(6)
        
        # Should be identical
        for e1, e2 in zip(events1, events2):
            assert e1.event_id == e2.event_id
            assert e1.identity_candidate == e2.identity_candidate
            assert e1.event_timestamp == e2.event_timestamp
    
    def test_publish_test_events(self):
        """Test publishing test events."""
        bus = create_event_bus()
        dev_source = DevelopmentEventSource(bus)
        
        count = dev_source.publish_test_events(6)
        
        assert count == 6
        history = bus.get_history(10)
        assert len(history) == 6
    
    def test_publish_single_event(self):
        """Test publishing a single custom event."""
        bus = create_event_bus()
        dev_source = DevelopmentEventSource(bus)
        
        result = dev_source.publish_single_event(
            person_id="HS999",
            camera_id="CAM2",
            track_id="B99",
            direction=ImmediateEventDirection.OUT,
            certainty=IdentityCertainty.KNOWN,
            confidence=0.999,
        )
        
        assert result is True
        history = bus.get_history(10)
        assert len(history) == 1
        assert history[0].identity_candidate == "HS999"
        assert history[0].camera_id == "CAM2"
        assert history[0].direction == ImmediateEventDirection.OUT


class TestAdapterFactory:
    """Tests for adapter factory functions."""
    
    def test_create_adapters(self):
        """Test creating all adapters."""
        bus = create_event_bus()
        adapters = create_adapters(bus)
        
        assert "phase24" in adapters
        assert "phase26" in adapters
        assert "phase25" in adapters
        assert "phase23" in adapters
        assert isinstance(adapters["phase24"], Phase24ToImmediateEventAdapter)
        assert isinstance(adapters["phase26"], Phase26ToImmediateEventAdapter)
        assert isinstance(adapters["phase25"], Phase25ToImmediateEventAdapter)
        assert isinstance(adapters["phase23"], Phase23ToImmediateEventAdapter)
    
    def test_create_development_source(self):
        """Test creating development source."""
        bus = create_event_bus()
        dev_source = create_development_source(bus)
        
        assert isinstance(dev_source, DevelopmentEventSource)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])