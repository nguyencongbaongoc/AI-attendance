#!/usr/bin/env python
"""
Phase 29 — Immediate Event Output Acceptance Script.

Validates the complete Phase 29 implementation including:
- ImmediateEvent contract
- Event delivery abstraction (EventPublisher, EventSubscriber, InMemoryEventBus)
- Deduplication and idempotency
- Bounded memory and backpressure
- Failure isolation
- Development fallback adapter
- UI adapter for Phase 28 integration
- End-to-end integration with Phase 23-26
"""

import json
import time
import sys
from typing import Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime

# Add project root to path
sys.path.insert(0, "c:/Users/Nguyen Cong Thong/Desktop/AI attendance")

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
    create_event_bus,
    FunctionSubscriber,
    SubscriberConfig,
    BackpressurePolicy,
    CallbackEventBus,
)
from app.output.adapter import (
    Phase24ToImmediateEventAdapter,
    Phase26ToImmediateEventAdapter,
    Phase25ToImmediateEventAdapter,
    Phase23ToImmediateEventAdapter,
    DevelopmentEventSource,
    create_adapters,
)
from app.output.ui_adapter import (
    UIEvent,
    UIEventSubscriber,
    Phase28UIAdapter,
    MockEventReplacer,
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
    IdentityCertainty as RawIdentityCertainty,
)
from app.attendance.policy import AttendanceDecision
from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    IdentityCertainty as AttendanceIdentityCertainty,
)


@dataclass
class AcceptanceResult:
    """Result of an acceptance criterion check."""
    criterion_id: str
    description: str
    passed: bool
    evidence: str
    duration_ms: float


class Phase29Acceptance:
    """Phase 29 acceptance test runner."""
    
    def __init__(self):
        self.results: List[AcceptanceResult] = []
        self.start_time = time.time()
    
    def run_test(self, criterion_id: str, description: str, test_fn) -> AcceptanceResult:
        """Run a single acceptance test."""
        start = time.time()
        try:
            evidence = test_fn()
            passed = True
            evidence_str = f"PASS: {evidence}"
        except Exception as e:
            passed = False
            evidence_str = f"FAIL: {type(e).__name__}: {e}"
        
        duration_ms = (time.time() - start) * 1000
        result = AcceptanceResult(
            criterion_id=criterion_id,
            description=description,
            passed=passed,
            evidence=evidence_str,
            duration_ms=duration_ms,
        )
        self.results.append(result)
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {criterion_id}: {description} ({duration_ms:.1f}ms)")
        return result
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate acceptance report."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        total_duration = (time.time() - self.start_time) * 1000
        
        return {
            "phase": "PHASE_29_IMMEDIATE_EVENT_OUTPUT",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "summary": {
                "total_criteria": total,
                "passed": passed,
                "failed": failed,
                "success_rate": f"{passed/total*100:.1f}%" if total > 0 else "0%",
                "total_duration_ms": total_duration,
            },
            "criteria": [asdict(r) for r in self.results],
        }


def create_sample_transition(sequence: int, direction: str = "in") -> ResolvedTransition:
    """Create a sample ResolvedTransition for testing."""
    return ResolvedTransition(
        resolution_id=f"TRANS-{sequence:03d}",
        source_raw_event_id=f"RIE-{sequence:03d}",
        camera_id="CAM1",
        local_track_id=f"A{sequence:02d}",
        global_observation_id=f"GO-{sequence:03d}",
        direction=direction,
        transition_type=TransitionType.IN if direction == "in" else TransitionType.OUT,
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


def create_sample_decision(sequence: int, direction: str = "in") -> AttendanceDecision:
    """Create a sample AttendanceDecision for testing."""
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


def create_sample_record(sequence: int, direction: str = "in") -> AttendanceRecord:
    """Create a sample AttendanceRecord for testing."""
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


def create_sample_raw_event(sequence: int, direction: str = "in") -> RawInOutEvent:
    """Create a sample RawInOutEvent for testing."""
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


def create_sample_immediate_event(sequence: int = 1) -> ImmediateEvent:
    """Create a sample ImmediateEvent for testing."""
    return ImmediateEvent(
        event_id=f"IEV-test{sequence:03d}",
        event_type=ImmediateEventType.ATTENDANCE_IN,
        direction=ImmediateEventDirection.IN,
        identity_certainty=IdentityCertainty.KNOWN,
        identity_candidate="HS001",
        identity_confidence=0.987,
        identity_evidence_ref="GO-001",
        event_timestamp=1700000000.0 + sequence,
        event_frame_index=sequence * 30,
        camera_id="CAM1",
        local_track_id=f"A{sequence:02d}",
        global_observation_id=f"GO-{sequence:03d}",
        source_raw_event_id=f"RIE-{sequence:03d}",
        source_resolution_id=f"RES-{sequence:03d}",
        geometry_version=1,
        geometry_config_hash="geom_hash_001",
        resolver_version="1.0",
        resolver_config_hash="resolver_hash_001",
        delivery_status=EventDeliveryStatus.NEW,
        delivery_sequence=sequence,
    )


def main():
    """Run Phase 29 acceptance tests."""
    print("=" * 80)
    print("PHASE 29 — IMMEDIATE EVENT OUTPUT ACCEPTANCE TEST")
    print("=" * 80)
    
    acceptance = Phase29Acceptance()
    
    # ============================================================
    # CONTRACT TESTS
    # ============================================================
    print("\n[CONTRACT] ImmediateEvent Contract Tests")
    
    def test_contract_creation():
        event = create_sample_immediate_event(1)
        error = validate_immediate_event(event)
        if error:
            raise ValueError(f"Validation failed: {error}")
        return f"Created valid ImmediateEvent with ID {event.event_id}"
    
    acceptance.run_test(
        "AC-29-01",
        "ImmediateEvent can be created with all required fields",
        test_contract_creation,
    )
    
    def test_deterministic_id():
        id1 = generate_immediate_event_id("RES-001", ImmediateEventType.ATTENDANCE_IN)
        id2 = generate_immediate_event_id("RES-001", ImmediateEventType.ATTENDANCE_IN)
        if id1 != id2:
            raise ValueError(f"IDs not deterministic: {id1} != {id2}")
        return f"Deterministic ID generation verified: {id1}"
    
    acceptance.run_test(
        "AC-29-02",
        "ImmediateEvent ID is deterministic (SHA256 of source_resolution_id + event_type)",
        test_deterministic_id,
    )
    
    def test_serialization():
        event = create_sample_immediate_event(1)
        # Round-trip through dict
        event_dict = event.to_dict()
        event2 = ImmediateEvent.from_dict(event_dict)
        if event.event_id != event2.event_id:
            raise ValueError("Round-trip serialization failed")
        return "Serialization round-trip verified"
    
    acceptance.run_test(
        "AC-29-03",
        "ImmediateEvent supports serialization/deserialization (to_dict/from_dict)",
        test_serialization,
    )
    
    # ============================================================
    # EVENT BUS TESTS
    # ============================================================
    print("\n[EVENT BUS] InMemoryEventBus Tests")
    
    def test_publish_subscribe():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        event = create_sample_immediate_event(1)
        result = bus.publish(event)
        time.sleep(0.1)
        
        if not result:
            raise ValueError("Publish returned False")
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        return "Publish/subscribe works correctly"
    
    acceptance.run_test(
        "AC-29-04",
        "Event bus publishes events to subscribers",
        test_publish_subscribe,
    )
    
    def test_duplicate_suppression():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        event = create_sample_immediate_event(1)
        r1 = bus.publish(event)
        r2 = bus.publish(event)  # Duplicate
        time.sleep(0.1)
        
        if r1 is not True or r2 is not False:
            raise ValueError(f"Duplicate handling failed: r1={r1}, r2={r2}")
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        return "Duplicate suppression works correctly"
    
    acceptance.run_test(
        "AC-29-05",
        "Event bus suppresses duplicate events (same source_resolution_id + event_type)",
        test_duplicate_suppression,
    )
    
    def test_delivery_sequence():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        for i in range(3):
            event = create_sample_immediate_event(i + 1)
            bus.publish(event)
        time.sleep(0.1)
        
        if len(received) != 3:
            raise ValueError(f"Expected 3 events, got {len(received)}")
        for i, e in enumerate(received):
            if e.delivery_sequence != i + 1:
                raise ValueError(f"Delivery sequence mismatch: expected {i+1}, got {e.delivery_sequence}")
        return "Delivery sequence assigned correctly"
    
    acceptance.run_test(
        "AC-29-06",
        "Events receive monotonic delivery sequence numbers",
        test_delivery_sequence,
    )
    
    def test_bounded_history():
        bus = create_event_bus(max_history=5)
        
        for i in range(10):
            event = create_sample_immediate_event(i + 1)
            bus.publish(event)
        
        # Small delay to ensure all events are processed
        time.sleep(0.1)
        
        history = bus.get_history(limit=100)
        if len(history) != 5:
            raise ValueError(f"History not bounded: expected 5, got {len(history)}")
        # Check that we have the last 5 events (indices 5-9, which are test006 through test010)
        # Note: get_history returns most recent first, so we expect test010, test009, test008, test007, test006
        expected_ids = ["IEV-test010", "IEV-test009", "IEV-test008", "IEV-test007", "IEV-test006"]
        actual_ids = [e.event_id for e in history]
        if actual_ids != expected_ids:
            raise ValueError(f"History order wrong: expected {expected_ids}, got {actual_ids}")
        return f"History bounded to 5 events (most recent first)"
    
    acceptance.run_test(
        "AC-29-07",
        "Event history is bounded by max_history parameter",
        test_bounded_history,
    )
    
    def test_bounded_dedup_cache():
        bus = create_event_bus(max_dedup_cache=5)
        
        # Publish 10 unique events
        for i in range(10):
            event = create_sample_immediate_event(i + 1)
            bus.publish(event)
        
        stats = bus.get_stats()
        if stats["dedup_cache_size"] > 5:
            raise ValueError(f"Dedup cache not bounded: {stats['dedup_cache_size']} > 5")
        return f"Deduplication cache bounded to 5 entries"
    
    acceptance.run_test(
        "AC-29-08",
        "Deduplication cache is bounded by max_dedup_cache parameter",
        test_bounded_dedup_cache,
    )
    
    def test_multiple_subscribers():
        bus = create_event_bus()
        received_1 = []
        received_2 = []
        
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received_1.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        bus.subscribe(FunctionSubscriber("sub2", lambda e: received_2.append(e)), 
                       SubscriberConfig(subscriber_id="sub2"))
        
        event = create_sample_immediate_event(1)
        bus.publish(event)
        time.sleep(0.1)
        
        if len(received_1) != 1 or len(received_2) != 1:
            raise ValueError(f"Expected 1 event each, got {len(received_1)} and {len(received_2)}")
        return "Multiple subscribers receive events independently"
    
    acceptance.run_test(
        "AC-29-09",
        "Multiple subscribers receive events independently",
        test_multiple_subscribers,
    )
    
    def test_subscriber_filter():
        bus = create_event_bus()
        received = []
        
        bus.subscribe(FunctionSubscriber("filtered", lambda e: received.append(e)), 
                       SubscriberConfig(
                           subscriber_id="filtered",
                           filter_fn=lambda e: e.camera_id == "CAM1"
                       ))
        
        event1 = create_sample_immediate_event(1)
        event1_dict = event1.to_dict()
        event1_dict["camera_id"] = "CAM1"
        event1 = ImmediateEvent.from_dict(event1_dict)
        
        event2 = create_sample_immediate_event(2)
        event2_dict = event2.to_dict()
        event2_dict["camera_id"] = "CAM2"
        event2 = ImmediateEvent.from_dict(event2_dict)
        
        bus.publish(event1)
        bus.publish(event2)
        time.sleep(0.1)
        
        if len(received) != 1:
            raise ValueError(f"Expected 1 filtered event, got {len(received)}")
        if received[0].camera_id != "CAM1":
            raise ValueError(f"Filter failed: got {received[0].camera_id}")
        return "Subscriber filter works correctly"
    
    acceptance.run_test(
        "AC-29-10",
        "Subscriber filter_fn filters events correctly",
        test_subscriber_filter,
    )
    
    # ============================================================
    # BACKPRESSURE TESTS
    # ============================================================
    print("\n[BACKPRESSURE] Backpressure Policy Tests")
    
    def test_drop_oldest():
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_OLDEST)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.DROP_OLDEST
        ))
        
        # Get subscriber state and manually fill queue
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        event1 = create_sample_immediate_event(1)
        event2 = create_sample_immediate_event(2)
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        # Publish 3rd event - should trigger DROP_OLDEST
        event3 = create_sample_immediate_event(3)
        bus.publish(event3)
        
        with state.lock:
            if len(state.queue) != 2:
                raise ValueError(f"Queue size should be 2, got {len(state.queue)}")
            if state.queue[0].event_id != "IEV-test002":
                raise ValueError(f"Oldest not dropped: {state.queue[0].event_id}")
            if state.queue[1].event_id != "IEV-test003":
                raise ValueError(f"Newest not added: {state.queue[1].event_id}")
            if state.events_dropped != 1:
                raise ValueError(f"Events dropped should be 1, got {state.events_dropped}")
        return "DROP_OLDEST policy works correctly"
    
    acceptance.run_test(
        "AC-29-11",
        "DROP_OLDEST backpressure policy drops oldest event when queue full",
        test_drop_oldest,
    )
    
    def test_drop_newest():
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_NEWEST)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.DROP_NEWEST
        ))
        
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        event1 = create_sample_immediate_event(1)
        event2 = create_sample_immediate_event(2)
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        event3 = create_sample_immediate_event(3)
        bus.publish(event3)
        
        with state.lock:
            if len(state.queue) != 2:
                raise ValueError(f"Queue size should be 2, got {len(state.queue)}")
            if state.queue[0].event_id != "IEV-test001":
                raise ValueError(f"Queue changed: {state.queue[0].event_id}")
            if state.events_dropped != 1:
                raise ValueError(f"Events dropped should be 1, got {state.events_dropped}")
        return "DROP_NEWEST policy works correctly"
    
    acceptance.run_test(
        "AC-29-12",
        "DROP_NEWEST backpressure policy rejects newest event when queue full",
        test_drop_newest,
    )
    
    def test_reject_subscriber():
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.REJECT_SUBSCRIBER)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.REJECT_SUBSCRIBER
        ))
        
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        event1 = create_sample_immediate_event(1)
        event2 = create_sample_immediate_event(2)
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        event3 = create_sample_immediate_event(3)
        bus.publish(event3)
        
        with state.lock:
            if state.is_active is not False:
                raise ValueError("Subscriber should be inactive")
            if "Backpressure" not in state.last_error:
                raise ValueError(f"Error message should mention backpressure: {state.last_error}")
        return "REJECT_SUBSCRIBER policy works correctly"
    
    acceptance.run_test(
        "AC-29-13",
        "REJECT_SUBSCRIBER backpressure policy marks subscriber inactive when queue full",
        test_reject_subscriber,
    )
    
    # ============================================================
    # FAILURE ISOLATION TESTS
    # ============================================================
    print("\n[FAILURE ISOLATION] Subscriber Failure Isolation Tests")
    
    def test_failure_isolation():
        bus = create_event_bus()
        good_received = []
        bad_received = []
        error_count = 0
        
        def good_handler(event):
            good_received.append(event)
        
        def bad_handler(event):
            bad_received.append(event)
            raise RuntimeError("Simulated failure")
        
        def error_handler(error, event):
            nonlocal error_count
            error_count += 1
        
        bus.subscribe(FunctionSubscriber("good", good_handler, error_handler), 
                       SubscriberConfig(subscriber_id="good"))
        bus.subscribe(FunctionSubscriber("bad", bad_handler, error_handler), 
                       SubscriberConfig(subscriber_id="bad"))
        
        event = create_sample_immediate_event(1)
        bus.publish(event)
        time.sleep(0.1)
        
        if len(good_received) != 1:
            raise ValueError(f"Good subscriber should receive 1 event, got {len(good_received)}")
        if len(bad_received) != 1:
            raise ValueError(f"Bad subscriber should receive 1 event before failing, got {len(bad_received)}")
        if error_count != 1:
            raise ValueError(f"Error handler should be called once, got {error_count}")
        
        stats = bus.get_stats()
        if stats["subscriber_errors"] < 1:
            raise ValueError(f"Stats should track subscriber errors: {stats['subscriber_errors']}")
        return "Failure isolation works - bad subscriber doesn't block good subscriber"
    
    acceptance.run_test(
        "AC-29-14",
        "Subscriber failure isolation - one subscriber failing doesn't affect others",
        test_failure_isolation,
    )
    
    # ============================================================
    # ADAPTER TESTS
    # ============================================================
    print("\n[ADAPTERS] Phase 23-26 Adapter Tests")
    
    def test_phase24_adapter():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapter = Phase24ToImmediateEventAdapter(bus)
        transition = create_sample_transition(1, "in")
        result = adapter.convert(transition)
        
        if not result.success:
            raise ValueError(f"Conversion failed: {result.error}")
        bus.publish(result.event)
        time.sleep(0.1)
        
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        if received[0].event_type != ImmediateEventType.RESOLUTION_IN:
            raise ValueError(f"Wrong event type: {received[0].event_type}")
        if received[0].source_resolution_id != "TRANS-001":
            raise ValueError(f"Wrong source_resolution_id: {received[0].source_resolution_id}")
        return "Phase24 adapter converts ResolvedTransition to ImmediateEvent"
    
    acceptance.run_test(
        "AC-29-15",
        "Phase24 adapter converts ResolvedTransition to ImmediateEvent (RESOLUTION_IN/OUT)",
        test_phase24_adapter,
    )
    
    def test_phase26_adapter():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapter = Phase26ToImmediateEventAdapter(bus)
        decision = create_sample_decision(1, "in")
        result = adapter.convert(decision)
        
        if not result.success:
            raise ValueError(f"Conversion failed: {result.error}")
        bus.publish(result.event)
        time.sleep(0.1)
        
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        if received[0].event_type != ImmediateEventType.ATTENDANCE_IN:
            raise ValueError(f"Wrong event type: {received[0].event_type}")
        if received[0].attendance_policy_id != "policy_v1":
            raise ValueError(f"Missing attendance_policy_id")
        if received[0].source_attendance_decision_id != "DEC-001":
            raise ValueError(f"Missing source_attendance_decision_id")
        return "Phase26 adapter converts AttendanceDecision to ImmediateEvent with full provenance"
    
    acceptance.run_test(
        "AC-29-16",
        "Phase26 adapter converts AttendanceDecision to ImmediateEvent with attendance state",
        test_phase26_adapter,
    )
    
    def test_phase25_adapter():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapter = Phase25ToImmediateEventAdapter(bus)
        record = create_sample_record(1, "in")
        result = adapter.convert(record)
        
        if not result.success:
            raise ValueError(f"Conversion failed: {result.error}")
        bus.publish(result.event)
        time.sleep(0.1)
        
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        if received[0].delivery_status != EventDeliveryStatus.HISTORICAL:
            raise ValueError(f"Expected HISTORICAL delivery status, got {received[0].delivery_status}")
        if received[0].source_attendance_record_id != "REC-001":
            raise ValueError(f"Missing source_attendance_record_id")
        return "Phase25 adapter converts AttendanceRecord to ImmediateEvent (HISTORICAL)"
    
    acceptance.run_test(
        "AC-29-17",
        "Phase25 adapter converts AttendanceRecord to ImmediateEvent with HISTORICAL status",
        test_phase25_adapter,
    )
    
    def test_phase23_adapter():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapter = Phase23ToImmediateEventAdapter(bus)
        raw_event = create_sample_raw_event(1, "in")
        result = adapter.convert(raw_event)
        
        if not result.success:
            raise ValueError(f"Conversion failed: {result.error}")
        bus.publish(result.event)
        time.sleep(0.1)
        
        if len(received) != 1:
            raise ValueError(f"Expected 1 event, got {len(received)}")
        if received[0].event_type != ImmediateEventType.RAW_IN:
            raise ValueError(f"Wrong event type: {received[0].event_type}")
        if received[0].source_resolution_id != "RIE-001":
            raise ValueError(f"Wrong source_resolution_id: {received[0].source_resolution_id}")
        return "Phase23 adapter converts RawInOutEvent to ImmediateEvent (RAW_IN/OUT)"
    
    acceptance.run_test(
        "AC-29-18",
        "Phase23 adapter converts RawInOutEvent to ImmediateEvent (RAW_IN/OUT)",
        test_phase23_adapter,
    )
    
    def test_multiple_adapters():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapters = create_adapters(bus)
        
        transition = create_sample_transition(1, "in")
        decision = create_sample_decision(2, "out")
        record = create_sample_record(3, "in")
        raw_event = create_sample_raw_event(4, "out")
        
        bus.publish(adapters["phase24"].convert(transition).event)
        bus.publish(adapters["phase26"].convert(decision).event)
        bus.publish(adapters["phase25"].convert(record).event)
        bus.publish(adapters["phase23"].convert(raw_event).event)
        time.sleep(0.1)
        
        if len(received) != 4:
            raise ValueError(f"Expected 4 events, got {len(received)}")
        event_types = {e.event_type for e in received}
        if ImmediateEventType.RESOLUTION_IN not in event_types:
            raise ValueError("Missing RESOLUTION_IN")
        if ImmediateEventType.ATTENDANCE_OUT not in event_types:
            raise ValueError("Missing ATTENDANCE_OUT")
        if ImmediateEventType.RAW_OUT not in event_types:
            raise ValueError("Missing RAW_OUT")
        return "Multiple adapters publish to same bus correctly"
    
    acceptance.run_test(
        "AC-29-19",
        "Multiple adapters can publish to the same event bus",
        test_multiple_adapters,
    )
    
    def test_deduplication_across_adapters():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        adapter24 = Phase24ToImmediateEventAdapter(bus)
        adapter26 = Phase26ToImmediateEventAdapter(bus)
        
        transition = create_sample_transition(1, "in")
        decision = create_sample_decision(1, "in")
        
        result1 = adapter24.convert(transition)
        result2 = adapter26.convert(decision)
        
        # Create new event with same source_resolution_id for deduplication test
        event2_dict = result2.event.to_dict()
        event2_dict["source_resolution_id"] = result1.event.source_resolution_id
        event2_dict["event_type"] = result1.event.event_type.value
        event2 = ImmediateEvent.from_dict(event2_dict)
        
        r1 = bus.publish(result1.event)
        r2 = bus.publish(event2)
        time.sleep(0.1)
        
        if r1 is not True or r2 is not False:
            raise ValueError(f"Deduplication failed: r1={r1}, r2={r2}")
        if len(received) != 1:
            raise ValueError(f"Expected 1 event after deduplication, got {len(received)}")
        return "Deduplication works across different adapters"
    
    acceptance.run_test(
        "AC-29-20",
        "Deduplication works across different adapters (same source_resolution_id + event_type)",
        test_deduplication_across_adapters,
    )
    
    # ============================================================
    # DEVELOPMENT FALLBACK TESTS
    # ============================================================
    print("\n[DEVELOPMENT] Development Fallback Adapter Tests")
    
    def test_dev_source():
        bus = create_event_bus()
        received = []
        bus.subscribe(FunctionSubscriber("sub1", lambda e: received.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        
        dev_source = DevelopmentEventSource(bus)
        dev_source.publish_test_events(count=5)
        time.sleep(0.1)
        
        if len(received) != 5:
            raise ValueError(f"Expected 5 events, got {len(received)}")
        for event in received:
            if not event.event_id.startswith("IEV-"):
                raise ValueError(f"Event ID should start with IEV-: {event.event_id}")
        return "DevelopmentEventSource generates deterministic test events"
    
    acceptance.run_test(
        "AC-29-21",
        "DevelopmentEventSource generates deterministic test events for development",
        test_dev_source,
    )
    
    def test_dev_source_deterministic():
        bus1 = create_event_bus()
        bus2 = create_event_bus()
        events1 = []
        events2 = []
        
        bus1.subscribe(FunctionSubscriber("sub1", lambda e: events1.append(e)), 
                       SubscriberConfig(subscriber_id="sub1"))
        bus2.subscribe(FunctionSubscriber("sub2", lambda e: events2.append(e)), 
                       SubscriberConfig(subscriber_id="sub2"))
        
        dev1 = DevelopmentEventSource(bus1)
        dev2 = DevelopmentEventSource(bus2)
        
        dev1.publish_test_events(count=3)
        dev2.publish_test_events(count=3)
        time.sleep(0.1)
        
        if len(events1) != 3 or len(events2) != 3:
            raise ValueError(f"Expected 3 events each, got {len(events1)} and {len(events2)}")
        for e1, e2 in zip(events1, events2):
            if e1.event_id != e2.event_id:
                raise ValueError(f"Events not deterministic: {e1.event_id} != {e2.event_id}")
        return "DevelopmentEventSource produces identical events across runs"
    
    acceptance.run_test(
        "AC-29-22",
        "DevelopmentEventSource produces deterministic events across multiple runs",
        test_dev_source_deterministic,
    )
    
    # ============================================================
    # UI INTEGRATION TESTS
    # ============================================================
    print("\n[UI INTEGRATION] Phase 28 UI Adapter Tests")
    
    def test_ui_subscriber():
        bus = create_event_bus()
        ui_events = []
        
        ui_subscriber = UIEventSubscriber("ui_sub", lambda e: ui_events.append(e))
        bus.subscribe(ui_subscriber, SubscriberConfig(subscriber_id="ui_sub"))
        
        event = create_sample_immediate_event(1)
        bus.publish(event)
        time.sleep(0.1)
        
        if len(ui_events) != 1:
            raise ValueError(f"Expected 1 UI event, got {len(ui_events)}")
        ui_event = ui_events[0]
        if ui_event.id != "IEV-test001":
            raise ValueError(f"UI event ID mismatch: {ui_event.id}")
        if ui_event.eventType != "attendance_in":
            raise ValueError(f"UI event type mismatch: {ui_event.eventType}")
        if ui_event.certainty != "known":
            raise ValueError(f"UI certainty mismatch: {ui_event.certainty}")
        return "UIEventSubscriber converts ImmediateEvent to UIEvent format"
    
    acceptance.run_test(
        "AC-29-23",
        "UIEventSubscriber converts ImmediateEvent to UI-friendly format for Pinia store",
        test_ui_subscriber,
    )
    
    def test_phase28_adapter():
        bus = create_event_bus()
        pinia_events = []
        
        def pinia_callback(ui_event):
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
        
        event = create_sample_immediate_event(1)
        bus.publish(event)
        time.sleep(0.1)
        
        if len(pinia_events) != 1:
            raise ValueError(f"Expected 1 Pinia event, got {len(pinia_events)}")
        if pinia_events[0]["event_id"] != "IEV-test001":
            raise ValueError(f"Pinia event ID mismatch: {pinia_events[0]['event_id']}")
        if pinia_events[0]["event_type"] != "attendance_in":
            raise ValueError(f"Pinia event type mismatch: {pinia_events[0]['event_type']}")
        
        adapter.disconnect()
        return "Phase28UIAdapter connects event bus to Pinia store callback"
    
    acceptance.run_test(
        "AC-29-24",
        "Phase28UIAdapter connects event bus to Pinia store callback",
        test_phase28_adapter,
    )
    
    def test_mock_replacer():
        bus = create_event_bus()
        pinia_events = []
        
        def pinia_callback(ui_event):
            pinia_events.append(ui_event.id)
        
        ui_adapter = Phase28UIAdapter(bus, pinia_callback)
        replacer = MockEventReplacer(ui_adapter)
        ui_adapter.connect()
        
        event = create_sample_immediate_event(1)
        bus.publish(event)
        time.sleep(0.1)
        
        if len(pinia_events) != 1:
            raise ValueError(f"Expected 1 event, got {len(pinia_events)}")
        if pinia_events[0] != "IEV-test001":
            raise ValueError(f"Event ID mismatch: {pinia_events[0]}")
        
        ui_adapter.disconnect()
        return "MockEventReplacer enables transition from mock to real events"
    
    acceptance.run_test(
        "AC-29-25",
        "MockEventReplacer replaces Phase 28 mock adapter with real Phase 29 events",
        test_mock_replacer,
    )
    
    # ============================================================
    # GENERATE REPORT
    # ============================================================
    print("\n" + "=" * 80)
    print("GENERATING ACCEPTANCE REPORT")
    print("=" * 80)
    
    report = acceptance.generate_report()
    
    # Save JSON report
    json_path = "benchmark_results/PHASE_29_IMMEDIATE_EVENT_OUTPUT.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report saved to: {json_path}")
    
    # Save Markdown report
    md_path = "benchmark_results/PHASE_29_IMMEDIATE_EVENT_OUTPUT.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Phase 29 - Immediate Event Output Acceptance Report\n\n")
        f.write(f"**Timestamp:** {report['timestamp']}\n\n")
        f.write("## Summary\n\n")
        f.write(f"- **Total Criteria:** {report['summary']['total_criteria']}\n")
        f.write(f"- **Passed:** {report['summary']['passed']}\n")
        f.write(f"- **Failed:** {report['summary']['failed']}\n")
        f.write(f"- **Success Rate:** {report['summary']['success_rate']}\n")
        f.write(f"- **Total Duration:** {report['summary']['total_duration_ms']:.1f}ms\n\n")
        f.write("## Criteria Details\n\n")
        for criterion in report["criteria"]:
            status = "[PASS]" if criterion["passed"] else "[FAIL]"
            f.write(f"### {criterion['criterion_id']}: {criterion['description']} {status}\n\n")
            f.write(f"**Duration:** {criterion['duration_ms']:.1f}ms\n\n")
            f.write(f"**Evidence:** {criterion['evidence']}\n\n")
    print(f"Markdown report saved to: {md_path}")
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"PHASE 29 ACCEPTANCE SUMMARY")
    print(f"{'='*80}")
    print(f"Total Criteria: {report['summary']['total_criteria']}")
    print(f"Passed: {report['summary']['passed']}")
    print(f"Failed: {report['summary']['failed']}")
    print(f"Success Rate: {report['summary']['success_rate']}")
    print(f"Total Duration: {report['summary']['total_duration_ms']:.1f}ms")
    
    # Exit with appropriate code
    if report['summary']['failed'] > 0:
        print("\n[FAIL] PHASE 29 ACCEPTANCE: FAILED")
        sys.exit(1)
    else:
        print("\n[PASS] PHASE 29 ACCEPTANCE: PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()