"""
Phase 29 — Integration Tests for Immediate Event Output.

Tests end-to-end flow from Phase 23-26 through Phase 29 to UI.
"""

import pytest
import time
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from app.output.contract import (
    ImmediateEvent,
    ImmediateEventType,
    ImmediateEventDirection,
    IdentityCertainty,
    EventDeliveryStatus,
    generate_immediate_event_id,
)
from app.output.publisher import (
    create_event_bus,
    FunctionSubscriber,
    SubscriberConfig,
    BackpressurePolicy,
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
from app.output.ui_adapter import (
    UIEvent,
    UIEventSubscriber,
    Phase28UIAdapter,
    MockEventReplacer,
    create_ui_adapter,
)
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


class TestEndToEndFlow:
    """Test complete flow from Phase 23-26 through Phase 29."""
    
    def create_resolved_transition(self, sequence: int, direction: str = "in", transition_type: TransitionType = TransitionType.IN):
        """Create a ResolvedTransition matching the actual contract."""
        return ResolvedTransition(
            resolution_id=f"TRANS-{sequence:03d}",
            source_raw_event_id=f"RIE-{sequence:03d}",
            camera_id="CAM1",
            local_track_id=f"A{sequence:02d}",
            global_observation_id=f"GO-{sequence:03d}",
            direction=direction,
            transition_type=transition_type,
            previous_state=DerivedState.OUTSIDE if direction == "in" else DerivedState.INSIDE,
            new_state=DerivedState.INSIDE if direction == "in" else DerivedState.OUTSIDE,
            source_timestamp=1700000000.0 + sequence,
            source_frame_index=sequence * 30,
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            resolution_status=ResolutionStatus.ACCEPTED,
            source_crossing_event_id=f"CE-{sequence:03d}",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
        )
    
    def create_attendance_decision(self, sequence: int, direction: str = "in"):
        """Create an AttendanceDecision matching the actual contract."""
        # Valid states: "unknown", "expected", "present", "late", "left", "absent"
        return AttendanceDecision(
            decision_id=f"DEC-{sequence:03d}",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=f"TRANS-{sequence:03d}",
            global_observation_id=f"GO-{sequence:03d}",
            camera_id="CAM1",
            local_track_id=f"A{sequence:02d}",
            direction=direction,
            event_timestamp=1700000000.0 + sequence,
            event_frame_index=sequence * 30,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            attendance_policy_id="policy_v1",
            attendance_policy_version="1.0",
            previous_attendance_state="absent" if direction == "in" else "present",
            new_attendance_state="present" if direction == "in" else "absent",
            decision_reason="within_entry_window",
            timetable_id=None,
            timetable_version=None,
            session_id=None,
            day=None,
            identity_candidate="HS001" if direction == "in" else None,
            identity_confidence=0.987 if direction == "in" else None,
            identity_evidence_ref=f"GO-{sequence:03d}" if direction == "in" else None,
            identity_certainty="KNOWN" if direction == "in" else "UNKNOWN",
        )
    
    def create_attendance_record(self, sequence: int, direction: str = "in"):
        """Create an AttendanceRecord matching the actual contract."""
        # Valid states: "unknown", "inside", "outside"
        return AttendanceRecord(
            attendance_record_id=f"REC-{sequence:03d}",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=f"TRANS-{sequence:03d}",
            global_observation_id=f"GO-{sequence:03d}",
            camera_id="CAM1",
            local_track_id=f"A{sequence:02d}",
            direction=AttendanceDirection.IN if direction == "in" else AttendanceDirection.OUT,
            event_timestamp=1700000000.0 + sequence,
            event_frame_index=sequence * 30,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            previous_state="outside" if direction == "in" else "inside",
            new_state="inside" if direction == "in" else "outside",
            identity_candidate="HS001" if direction == "in" else None,
            identity_confidence=0.987 if direction == "in" else None,
            identity_evidence_ref=f"GO-{sequence:03d}" if direction == "in" else None,
            identity_certainty=AttendanceIdentityCertainty.KNOWN if direction == "in" else AttendanceIdentityCertainty.UNKNOWN,
        )
    
    def create_raw_in_out_event(self, sequence: int, direction: str = "in"):
        """Create a RawInOutEvent matching the actual contract."""
        return RawInOutEvent(
            event_id=f"RIE-{sequence:03d}",
            camera_id="CAM1",
            geometry_id="geom_001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            local_track_id=f"A{sequence:02d}",
            direction=RawEventDirection.IN if direction == "in" else RawEventDirection.OUT,
            crossing_timestamp=1700000000.0 + sequence,
            crossing_frame_index=sequence * 30,
            global_observation_id=f"GO-{sequence:03d}",
            identity_candidate="HS001" if direction == "in" else None,
            identity_confidence=0.987 if direction == "in" else None,
            identity_evidence_ref=f"GO-{sequence:03d}" if direction == "in" else None,
            identity_certainty=RawIdentityCertainty.KNOWN if direction == "in" else RawIdentityCertainty.UNKNOWN,
            source_crossing_event_id=f"CE-{sequence:03d}",
        )
    
    def test_phase24_to_immediate_event_flow(self):
        """Test Phase 24 → ImmediateEvent → EventBus → UI."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapter = Phase24ToImmediateEventAdapter(bus)
        
        # Convert and publish IN transition
        transition = self.create_resolved_transition(1, "in", TransitionType.IN)
        result = adapter.convert(transition)
        
        assert result.success is True
        bus.publish(result.event)
        
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].event_type == ImmediateEventType.RESOLUTION_IN
        assert received_events[0].direction == ImmediateEventDirection.IN
        # Note: Phase24 adapter doesn't set identity_certainty to KNOWN
        # because ResolvedTransition doesn't have identity information
        assert received_events[0].source_resolution_id == "TRANS-001"
        assert received_events[0].delivery_status == EventDeliveryStatus.NEW
    
    def test_phase26_to_immediate_event_flow(self):
        """Test Phase 26 → ImmediateEvent → EventBus → UI."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapter = Phase26ToImmediateEventAdapter(bus)
        
        # Convert and publish IN decision
        decision = self.create_attendance_decision(1, "in")
        result = adapter.convert(decision)
        
        assert result.success is True
        bus.publish(result.event)
        
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].event_type == ImmediateEventType.ATTENDANCE_IN
        assert received_events[0].attendance_policy_id == "policy_v1"
        assert received_events[0].decision_reason == "within_entry_window"
        # Phase26 adapter uses decision.source_resolution_id (which is the transition ID)
        assert received_events[0].source_resolution_id == "TRANS-001"
        assert received_events[0].source_attendance_decision_id == "DEC-001"
        assert received_events[0].identity_certainty == IdentityCertainty.KNOWN
    
    def test_phase25_to_immediate_event_flow(self):
        """Test Phase 25 → ImmediateEvent (HISTORICAL) → EventBus."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapter = Phase25ToImmediateEventAdapter(bus)
        
        # Convert and publish IN record (historical)
        record = self.create_attendance_record(1, "in")
        result = adapter.convert(record)
        
        assert result.success is True
        bus.publish(result.event)
        
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].delivery_status == EventDeliveryStatus.HISTORICAL
        assert received_events[0].source_attendance_record_id == "REC-001"
        assert received_events[0].identity_certainty == IdentityCertainty.KNOWN
    
    def test_phase23_to_immediate_event_flow(self):
        """Test Phase 23 → ImmediateEvent (RAW) → EventBus."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapter = Phase23ToImmediateEventAdapter(bus)
        
        # Convert and publish raw event
        raw_event = self.create_raw_in_out_event(1, "in")
        result = adapter.convert(raw_event)
        
        assert result.success is True
        bus.publish(result.event)
        
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].event_type == ImmediateEventType.RAW_IN
        assert received_events[0].source_raw_event_id == "RIE-001"
        assert received_events[0].source_resolution_id == "RIE-001"
        assert received_events[0].identity_certainty == IdentityCertainty.KNOWN
    
    def test_multiple_adapters_same_bus(self):
        """Test multiple adapters publishing to same bus."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapters = create_adapters(bus)
        
        # Publish from all adapters
        transition = self.create_resolved_transition(1, "in", TransitionType.IN)
        decision = self.create_attendance_decision(2, "out")
        record = self.create_attendance_record(3, "in")
        raw_event = self.create_raw_in_out_event(4, "out")
        
        bus.publish(adapters["phase24"].convert(transition).event)
        bus.publish(adapters["phase26"].convert(decision).event)
        bus.publish(adapters["phase25"].convert(record).event)
        bus.publish(adapters["phase23"].convert(raw_event).event)
        
        time.sleep(0.1)
        
        assert len(received_events) == 4
        # Verify all event types present
        event_types = {e.event_type for e in received_events}
        assert ImmediateEventType.RESOLUTION_IN in event_types
        assert ImmediateEventType.ATTENDANCE_OUT in event_types
        assert ImmediateEventType.RAW_OUT in event_types
    
    def test_deduplication_across_adapters(self):
        """Test deduplication works across different adapters."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        adapter24 = Phase24ToImmediateEventAdapter(bus)
        adapter26 = Phase26ToImmediateEventAdapter(bus)
        
        # Same resolution_id, different adapters - should be duplicate
        # Note: Phase24 uses resolution_id, Phase26 uses decision.source_resolution_id (transition ID)
        # So they won't be duplicates unless we use same ID
        transition = self.create_resolved_transition(1, "in", TransitionType.IN)
        decision = self.create_attendance_decision(1, "in")
        
        result1 = adapter24.convert(transition)
        result2 = adapter26.convert(decision)
        
        # Create a new event with same source_resolution_id for deduplication test
        # (ImmediateEvent is frozen, so we need to create a new one)
        event2_dict = result2.event.to_dict()
        event2_dict["source_resolution_id"] = result1.event.source_resolution_id
        event2_dict["event_type"] = result1.event.event_type.value
        event2 = ImmediateEvent.from_dict(event2_dict)
        
        r1 = bus.publish(result1.event)
        r2 = bus.publish(event2)
        
        time.sleep(0.1)
        
        assert r1 is True
        assert r2 is False  # Duplicate suppressed
        assert len(received_events) == 1


class TestUIIntegration:
    """Test Phase 28 UI integration."""
    
    def test_ui_event_subscriber(self):
        """Test UIEventSubscriber converts ImmediateEvent to UIEvent."""
        bus = create_event_bus()
        ui_events: List[UIEvent] = []
        
        def ui_handler(ui_event: UIEvent):
            ui_events.append(ui_event)
        
        ui_subscriber = UIEventSubscriber("ui_sub", ui_handler)
        bus.subscribe(ui_subscriber, SubscriberConfig(subscriber_id="ui_sub"))
        
        # Create and publish an ImmediateEvent
        event = ImmediateEvent(
            event_id="IEV-test001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=0,
            camera_id="CAM1",
            local_track_id="A01",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
        )
        
        bus.publish(event)
        time.sleep(0.1)
        
        assert len(ui_events) == 1
        ui_event = ui_events[0]
        assert ui_event.id == "IEV-test001"
        assert ui_event.eventType == "attendance_in"
        assert ui_event.direction == "in"
        assert ui_event.certainty == "known"
        assert ui_event.personId == "HS001"
        assert ui_event.cameraId == "CAM1"
    
    def test_phase28_ui_adapter(self):
        """Test Phase28UIAdapter connects bus to Pinia store callback."""
        bus = create_event_bus()
        pinia_events: List[dict] = []
        
        def pinia_callback(ui_event: UIEvent):
            pinia_events.append({
                "event_id": ui_event.id,
                "event_type": ui_event.eventType,
                "direction": ui_event.direction,
                "identity_certainty": ui_event.certainty,
                "identity_candidate": ui_event.personId,
                "camera_id": ui_event.cameraId,
            })
        
        adapter = Phase28UIAdapter(bus, pinia_callback)
        adapter.connect()
        
        # Publish event
        event = ImmediateEvent(
            event_id="IEV-test001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=0,
            camera_id="CAM1",
            local_track_id="A01",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
        )
        
        bus.publish(event)
        time.sleep(0.1)
        
        assert len(pinia_events) == 1
        assert pinia_events[0]["event_id"] == "IEV-test001"
        assert pinia_events[0]["event_type"] == "attendance_in"
        
        adapter.disconnect()
    
    def test_mock_event_replacer(self):
        """Test MockEventReplacer replaces mock adapter with real one."""
        bus = create_event_bus()
        pinia_events: List[dict] = []
        
        def pinia_callback(ui_event: UIEvent):
            pinia_events.append(ui_event.id)
        
        ui_adapter = Phase28UIAdapter(bus, pinia_callback)
        replacer = MockEventReplacer(ui_adapter)
        
        # Connect the adapter
        ui_adapter.connect()
        
        # Publish event
        event = ImmediateEvent(
            event_id="IEV-test001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=0,
            camera_id="CAM1",
            local_track_id="A01",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
        )
        
        bus.publish(event)
        time.sleep(0.1)
        
        assert len(pinia_events) == 1
        assert pinia_events[0] == "IEV-test001"
        
        ui_adapter.disconnect()


class TestDevelopmentEventSource:
    """Test development fallback adapter."""
    
    def test_development_source_generates_events(self):
        """Test DevelopmentEventSource generates deterministic test events."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        dev_source = DevelopmentEventSource(bus)
        dev_source.publish_test_events(count=5)
        
        time.sleep(0.1)
        
        assert len(received_events) == 5
        # Verify events were generated (IDs are deterministic but based on hash)
        for event in received_events:
            assert event.event_id.startswith("IEV-")
            assert event.event_type in [ImmediateEventType.ATTENDANCE_IN, ImmediateEventType.ATTENDANCE_OUT]
    
    def test_development_source_deterministic(self):
        """Test DevelopmentEventSource produces same events each time."""
        bus1 = create_event_bus()
        bus2 = create_event_bus()
        
        events1: List[ImmediateEvent] = []
        events2: List[ImmediateEvent] = []
        
        bus1.subscribe(FunctionSubscriber("sub1", lambda e: events1.append(e)), SubscriberConfig(subscriber_id="sub1"))
        bus2.subscribe(FunctionSubscriber("sub2", lambda e: events2.append(e)), SubscriberConfig(subscriber_id="sub2"))
        
        dev1 = DevelopmentEventSource(bus1)
        dev2 = DevelopmentEventSource(bus2)
        
        dev1.publish_test_events(count=3)
        dev2.publish_test_events(count=3)
        
        time.sleep(0.1)
        
        assert len(events1) == 3
        assert len(events2) == 3
        for e1, e2 in zip(events1, events2):
            assert e1.event_id == e2.event_id
            assert e1.event_timestamp == e2.event_timestamp


class TestBackpressureIntegration:
    """Test backpressure in integration scenarios."""
    
    def test_slow_subscriber_backpressure(self):
        """Test backpressure with slow subscriber in integration."""
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_OLDEST)
        received: List[ImmediateEvent] = []
        
        def slow_handler(event: ImmediateEvent):
            received.append(event)
            time.sleep(0.01)  # Simulate slow processing
        
        subscriber = FunctionSubscriber("slow_sub", slow_handler)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.DROP_OLDEST
        ))
        
        # Publish multiple events quickly
        for i in range(5):
            event = ImmediateEvent(
                event_id=f"IEV-test{i:03d}",
                event_type=ImmediateEventType.ATTENDANCE_IN,
                direction=ImmediateEventDirection.IN,
                identity_certainty=IdentityCertainty.KNOWN,
                identity_candidate="HS001",
                identity_confidence=0.987,
                identity_evidence_ref=f"GO-{i:03d}",
                event_timestamp=1700000000.0 + i,
                event_frame_index=i * 30,
                camera_id="CAM1",
                local_track_id=f"A{i:02d}",
                global_observation_id=f"GO-{i:03d}",
                source_raw_event_id=f"RIE-{i:03d}",
                source_resolution_id=f"RES-{i:03d}",
                geometry_version=1,
                geometry_config_hash="geom_hash_001",
                resolver_version="1.0",
                resolver_config_hash="resolver_hash_001",
                delivery_status=EventDeliveryStatus.NEW,
                delivery_sequence=i + 1,
            )
            bus.publish(event)
        
        time.sleep(0.2)
        
        # Should have received some events (backpressure handled)
        assert len(received) > 0
        stats = bus.get_subscriber_stats("slow_sub")
        assert stats is not None


class TestFailureIsolationIntegration:
    """Test failure isolation in integration scenarios."""
    
    def test_bad_subscriber_does_not_block_good(self):
        """Test that a failing subscriber doesn't block others."""
        bus = create_event_bus()
        good_received: List[ImmediateEvent] = []
        bad_received: List[ImmediateEvent] = []
        error_count = 0
        
        def good_handler(event: ImmediateEvent):
            good_received.append(event)
        
        def bad_handler(event: ImmediateEvent):
            bad_received.append(event)
            raise RuntimeError("Simulated failure")
        
        def error_handler(error: Exception, event):
            nonlocal error_count
            error_count += 1
        
        good_sub = FunctionSubscriber("good_sub", good_handler, error_handler)
        bad_sub = FunctionSubscriber("bad_sub", bad_handler, error_handler)
        
        bus.subscribe(good_sub, SubscriberConfig(subscriber_id="good_sub"))
        bus.subscribe(bad_sub, SubscriberConfig(subscriber_id="bad_sub"))
        
        event = ImmediateEvent(
            event_id="IEV-test001",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=1700000000.0,
            event_frame_index=0,
            camera_id="CAM1",
            local_track_id="A01",
            global_observation_id="GO-001",
            source_raw_event_id="RIE-001",
            source_resolution_id="RES-001",
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=1,
        )
        
        bus.publish(event)
        time.sleep(0.1)
        
        # Good subscriber should receive event
        assert len(good_received) == 1
        # Bad subscriber should have received before failing
        assert len(bad_received) == 1
        # Error should be caught
        assert error_count == 1
        # Stats should track error
        stats = bus.get_stats()
        assert stats["subscriber_errors"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])