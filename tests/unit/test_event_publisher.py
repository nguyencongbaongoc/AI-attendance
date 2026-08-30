"""
Phase 29 — Unit Tests for Event Publisher and In-Memory Event Bus.

Tests:
- Subscriber registration and removal
- Multiple subscriber support
- Event publishing and delivery
- Duplicate suppression
- Deterministic ordering
- Bounded history
- Bounded deduplication state
- Subscriber failure isolation
- Backpressure policies
- Cleanup
"""

import pytest
import time
import threading
from typing import List, Optional

from app.output.contract import (
    ImmediateEvent,
    ImmediateEventType,
    ImmediateEventDirection,
    IdentityCertainty,
    EventDeliveryStatus,
)
from app.output.publisher import (
    EventPublisher,
    EventSubscriber,
    InMemoryEventBus,
    CallbackEventBus,
    SubscriberConfig,
    BackpressurePolicy,
    FunctionSubscriber,
    create_event_bus,
)


class TestEventPublisherBasics:
    """Tests for basic publisher functionality."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_publish_returns_true_for_new_event(self):
        """Test that publishing a new event returns True."""
        bus = create_event_bus()
        event = self.create_sample_event(1)
        
        result = bus.publish(event)
        
        assert result is True
    
    def test_publish_returns_false_for_duplicate(self):
        """Test that publishing a duplicate event returns False."""
        bus = create_event_bus()
        event = self.create_sample_event(1, "RES-001")
        
        result1 = bus.publish(event)
        result2 = bus.publish(event)  # Same resolution_id + event_type = duplicate
        
        assert result1 is True
        assert result2 is False
    
    def test_duplicate_suppression_by_resolution_id_and_type(self):
        """Test that deduplication uses source_resolution_id + event_type."""
        bus = create_event_bus()
        
        # Same resolution_id, different event_type should NOT be duplicate
        event1 = self.create_sample_event(1, "RES-001")
        event1_dict = event1.to_dict()
        event1_dict["event_type"] = ImmediateEventType.ATTENDANCE_IN.value
        event1 = ImmediateEvent.from_dict(event1_dict)
        
        event2 = self.create_sample_event(2, "RES-001")
        event2_dict = event2.to_dict()
        event2_dict["event_type"] = ImmediateEventType.ATTENDANCE_OUT.value
        event2 = ImmediateEvent.from_dict(event2_dict)
        
        result1 = bus.publish(event1)
        result2 = bus.publish(event2)
        
        assert result1 is True
        assert result2 is True  # Different event_type
    
    def test_get_history_returns_events(self):
        """Test that get_history returns published events."""
        bus = create_event_bus()
        event = self.create_sample_event(1)
        
        bus.publish(event)
        history = bus.get_history(limit=10)
        
        assert len(history) == 1
        assert history[0].event_id == event.event_id
    
    def test_history_most_recent_first(self):
        """Test that history returns most recent events first."""
        bus = create_event_bus()
        
        for i in range(5):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        history = bus.get_history(limit=10)
        
        # Should be in reverse order (most recent first)
        assert history[0].event_id == "IEV-test004"
        assert history[4].event_id == "IEV-test000"
    
    def test_history_limit(self):
        """Test that history respects limit."""
        bus = create_event_bus(max_history=100)
        
        for i in range(10):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        history = bus.get_history(limit=3)
        assert len(history) == 3
        assert history[0].event_id == "IEV-test009"


class TestSubscriberManagement:
    """Tests for subscriber registration and management."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_subscribe_function_subscriber(self):
        """Test subscribing a function subscriber."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_subscriber", handler)
        config = SubscriberConfig(subscriber_id="test_subscriber")
        
        result = bus.subscribe(subscriber, config)
        
        assert result is True
        assert bus.get_subscriber_count() == 1
    
    def test_unsubscribe(self):
        """Test unsubscribing a subscriber."""
        bus = create_event_bus()
        received_events: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received_events.append(event)
        
        subscriber = FunctionSubscriber("test_subscriber", handler)
        config = SubscriberConfig(subscriber_id="test_subscriber")
        
        bus.subscribe(subscriber, config)
        bus.unsubscribe("test_subscriber")
        
        assert bus.get_subscriber_count() == 0
    
    def test_multiple_subscribers(self):
        """Test multiple subscribers receive events."""
        bus = create_event_bus()
        received_1: List[ImmediateEvent] = []
        received_2: List[ImmediateEvent] = []
        
        def handler1(event: ImmediateEvent):
            received_1.append(event)
        
        def handler2(event: ImmediateEvent):
            received_2.append(event)
        
        sub1 = FunctionSubscriber("sub1", handler1)
        sub2 = FunctionSubscriber("sub2", handler2)
        
        bus.subscribe(sub1, SubscriberConfig(subscriber_id="sub1"))
        bus.subscribe(sub2, SubscriberConfig(subscriber_id="sub2"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        # Give time for async delivery
        time.sleep(0.1)
        
        assert len(received_1) == 1
        assert len(received_2) == 1
        assert received_1[0].event_id == event.event_id
        assert received_2[0].event_id == event.event_id
    
    def test_duplicate_subscriber_id_rejected(self):
        """Test that duplicate subscriber ID is rejected."""
        bus = create_event_bus()
        
        sub1 = FunctionSubscriber("same_id", lambda e: None)
        sub2 = FunctionSubscriber("same_id", lambda e: None)
        
        bus.subscribe(sub1, SubscriberConfig(subscriber_id="same_id"))
        result = bus.subscribe(sub2, SubscriberConfig(subscriber_id="same_id"))
        
        assert result is False
        assert bus.get_subscriber_count() == 1


class TestEventDelivery:
    """Tests for event delivery to subscribers."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_event_delivered_to_subscriber(self):
        """Test that event is delivered to subscriber."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        time.sleep(0.1)
        
        assert len(received) == 1
        assert received[0].event_id == event.event_id
    
    def test_delivery_sequence_assigned(self):
        """Test that delivery sequence is assigned to events."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        subscriber = FunctionSubscriber("test_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        time.sleep(0.1)
        
        assert received[0].delivery_sequence == 1
    
    def test_subscriber_filter(self):
        """Test that subscriber filter works."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        # Only accept CAM1 events
        subscriber = FunctionSubscriber("filtered_sub", handler)
        config = SubscriberConfig(
            subscriber_id="filtered_sub",
            filter_fn=lambda e: e.camera_id == "CAM1"
        )
        bus.subscribe(subscriber, config)
        
        # Publish CAM1 event (should be delivered)
        event1 = self.create_sample_event(1, "RES-001")
        event1_dict = event1.to_dict()
        event1_dict["camera_id"] = "CAM1"
        event1 = ImmediateEvent.from_dict(event1_dict)
        bus.publish(event1)
        
        # Publish CAM2 event (should be filtered)
        event2 = self.create_sample_event(2, "RES-002")
        event2_dict = event2.to_dict()
        event2_dict["camera_id"] = "CAM2"
        event2 = ImmediateEvent.from_dict(event2_dict)
        bus.publish(event2)
        
        time.sleep(0.1)
        
        assert len(received) == 1
        assert received[0].camera_id == "CAM1"


class TestBoundedMemory:
    """Tests for bounded memory (history and deduplication)."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_history_bounded(self):
        """Test that history is bounded by max_history."""
        bus = create_event_bus(max_history=5)
        
        for i in range(10):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        history = bus.get_history(limit=100)
        assert len(history) == 5  # Only last 5 kept
        assert history[0].event_id == "IEV-test009"
        assert history[4].event_id == "IEV-test005"
    
    def test_dedup_cache_bounded(self):
        """Test that deduplication cache is bounded."""
        bus = create_event_bus(max_dedup_cache=5)
        
        # Publish 10 unique events
        for i in range(10):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        # Try to publish first 5 again - they should be duplicates but cache is full
        # The oldest 5 should have been evicted
        for i in range(5):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            result = bus.publish(event)
            # These might not be detected as duplicates if evicted
            # The test verifies the cache doesn't grow unbounded
        
        stats = bus.get_stats()
        assert stats["dedup_cache_size"] <= 5


class TestFailureIsolation:
    """Tests for subscriber failure isolation."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_subscriber_failure_does_not_affect_others(self):
        """Test that one subscriber failing doesn't affect others."""
        bus = create_event_bus()
        received_good: List[ImmediateEvent] = []
        received_bad: List[ImmediateEvent] = []
        error_count = 0
        
        def good_handler(event: ImmediateEvent):
            received_good.append(event)
        
        def bad_handler(event: ImmediateEvent):
            received_bad.append(event)
            raise RuntimeError("Simulated subscriber failure")
        
        def error_handler(error: Exception, event: Optional[ImmediateEvent]):
            nonlocal error_count
            error_count += 1
        
        good_sub = FunctionSubscriber("good_sub", good_handler, error_handler)
        bad_sub = FunctionSubscriber("bad_sub", bad_handler, error_handler)
        
        bus.subscribe(good_sub, SubscriberConfig(subscriber_id="good_sub"))
        bus.subscribe(bad_sub, SubscriberConfig(subscriber_id="bad_sub"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        time.sleep(0.1)
        
        # Good subscriber should still receive event
        assert len(received_good) == 1
        # Bad subscriber should have received event before failing
        assert len(received_bad) == 1
        # Error should have been caught
        assert error_count == 1
    
    def test_subscriber_error_tracked_in_stats(self):
        """Test that subscriber errors are tracked in statistics."""
        bus = create_event_bus()
        
        def bad_handler(event: ImmediateEvent):
            raise RuntimeError("Simulated failure")
        
        bad_sub = FunctionSubscriber("bad_sub", bad_handler)
        bus.subscribe(bad_sub, SubscriberConfig(subscriber_id="bad_sub"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        time.sleep(0.1)
        
        stats = bus.get_stats()
        assert stats["subscriber_errors"] >= 1


class TestBackpressure:
    """Tests for backpressure handling."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_drop_oldest_policy(self):
        """Test DROP_OLDEST backpressure policy by directly testing the handler."""
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_OLDEST)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.DROP_OLDEST
        ))
        
        # Get subscriber state and manually fill queue to capacity
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        # Fill queue to capacity (simulate slow subscriber)
        event1 = self.create_sample_event(1, "RES-001")
        event2 = self.create_sample_event(2, "RES-002")
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        # Now publish a 3rd event - should trigger DROP_OLDEST
        event3 = self.create_sample_event(3, "RES-003")
        bus.publish(event3)
        
        # Verify oldest was dropped and new event queued
        with state.lock:
            assert len(state.queue) == 2
            assert state.queue[0].event_id == "IEV-test002"  # event2 (oldest kept after drop)
            assert state.queue[1].event_id == "IEV-test003"  # event3 (newest)
            assert state.events_dropped == 1
    
    def test_drop_newest_policy(self):
        """Test DROP_NEWEST backpressure policy by directly testing the handler."""
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.DROP_NEWEST)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.DROP_NEWEST
        ))
        
        # Get subscriber state and manually fill queue to capacity
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        event1 = self.create_sample_event(1, "RES-001")
        event2 = self.create_sample_event(2, "RES-002")
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        # Publish a 3rd event - should trigger DROP_NEWEST (reject new)
        event3 = self.create_sample_event(3, "RES-003")
        bus.publish(event3)
        
        # Verify newest was dropped, queue unchanged
        with state.lock:
            assert len(state.queue) == 2
            assert state.queue[0].event_id == "IEV-test001"
            assert state.queue[1].event_id == "IEV-test002"
            assert state.events_dropped == 1
    
    def test_reject_subscriber_policy(self):
        """Test REJECT_SUBSCRIBER backpressure policy by directly testing the handler."""
        bus = create_event_bus(default_queue_size=2, default_backpressure=BackpressurePolicy.REJECT_SUBSCRIBER)
        
        subscriber = FunctionSubscriber("slow_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(
            subscriber_id="slow_sub",
            queue_size=2,
            backpressure_policy=BackpressurePolicy.REJECT_SUBSCRIBER
        ))
        
        # Get subscriber state and manually fill queue to capacity
        with bus._subscriber_lock:
            state = bus._subscribers["slow_sub"]
        
        event1 = self.create_sample_event(1, "RES-001")
        event2 = self.create_sample_event(2, "RES-002")
        with state.lock:
            state.queue.append(event1)
            state.queue.append(event2)
        
        # Publish a 3rd event - should trigger REJECT_SUBSCRIBER
        event3 = self.create_sample_event(3, "RES-003")
        bus.publish(event3)
        
        # Verify subscriber marked inactive
        with state.lock:
            assert state.is_active is False
            assert "Backpressure" in state.last_error
            # REJECT_SUBSCRIBER doesn't increment events_dropped, it just rejects the subscriber
            assert state.events_dropped == 0


class TestDeterministicOrdering:
    """Tests for deterministic event ordering."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001", timestamp: float = None) -> ImmediateEvent:
        """Create a sample event for testing."""
        return ImmediateEvent(
            event_id=f"IEV-test{sequence:03d}",
            event_type=ImmediateEventType.ATTENDANCE_IN,
            direction=ImmediateEventDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS001",
            identity_confidence=0.987,
            identity_evidence_ref="GO-001",
            event_timestamp=timestamp if timestamp is not None else 1700000000.0 + sequence,
            event_frame_index=sequence * 30,
            camera_id="CAM1",
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_ordering_by_delivery_sequence(self):
        """Test that events are delivered in publish order (delivery_sequence)."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        subscriber = FunctionSubscriber("order_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="order_sub"))
        
        # Publish events with different timestamps (out of order)
        event1 = self.create_sample_event(1, "RES-001", timestamp=1700000002.0)
        event2 = self.create_sample_event(2, "RES-002", timestamp=1700000000.0)
        event3 = self.create_sample_event(3, "RES-003", timestamp=1700000001.0)
        
        bus.publish(event1)
        bus.publish(event2)
        bus.publish(event3)
        
        time.sleep(0.1)
        
        # Should be delivered in publish order (delivery_sequence)
        assert received[0].delivery_sequence == 1
        assert received[1].delivery_sequence == 2
        assert received[2].delivery_sequence == 3
    
    def test_equal_timestamp_tiebreak_by_sequence(self):
        """Test that equal timestamps are ordered by delivery sequence."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        subscriber = FunctionSubscriber("tiebreak_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="tiebreak_sub"))
        
        # Publish events with SAME timestamp but different sequence
        event1 = self.create_sample_event(1, "RES-001", timestamp=1700000000.0)
        event2 = self.create_sample_event(2, "RES-002", timestamp=1700000000.0)
        event3 = self.create_sample_event(3, "RES-003", timestamp=1700000000.0)
        
        bus.publish(event1)
        bus.publish(event2)
        bus.publish(event3)
        
        time.sleep(0.1)
        
        # Should be delivered in sequence order (delivery_sequence)
        assert received[0].delivery_sequence == 1
        assert received[1].delivery_sequence == 2
        assert received[2].delivery_sequence == 3


class TestCleanup:
    """Tests for cleanup and shutdown."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_clear_history(self):
        """Test clearing history."""
        bus = create_event_bus()
        
        for i in range(5):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        assert len(bus.get_history(100)) == 5
        
        bus.clear_history()
        
        assert len(bus.get_history(100)) == 0
        stats = bus.get_stats()
        assert stats["events_published"] == 0
        assert stats["dedup_cache_size"] == 0
    
    def test_shutdown(self):
        """Test shutdown clears subscribers."""
        bus = create_event_bus()
        
        subscriber = FunctionSubscriber("test_sub", lambda e: None)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="test_sub"))
        
        assert bus.get_subscriber_count() == 1
        
        bus.shutdown()
        
        assert bus.get_subscriber_count() == 0


class TestStatistics:
    """Tests for publisher statistics."""
    
    def create_sample_event(self, sequence: int = 1, resolution_id: str = "RES-001") -> ImmediateEvent:
        """Create a sample event for testing."""
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
            local_track_id="A17",
            global_observation_id="GO-001",
            source_raw_event_id=f"RIE-{sequence:03d}",
            source_resolution_id=resolution_id,
            geometry_version=1,
            geometry_config_hash="geom_hash_001",
            resolver_version="1.0",
            resolver_config_hash="resolver_hash_001",
            delivery_status=EventDeliveryStatus.NEW,
            delivery_sequence=sequence,
        )
    
    def test_stats_track_published_events(self):
        """Test that stats track published events."""
        bus = create_event_bus()
        
        for i in range(3):
            event = self.create_sample_event(i, f"RES-{i:03d}")
            bus.publish(event)
        
        # Publish duplicate
        bus.publish(self.create_sample_event(0, "RES-000"))
        
        stats = bus.get_stats()
        assert stats["events_published"] == 3
        assert stats["events_duplicated"] == 1
    
    def test_subscriber_stats(self):
        """Test subscriber-specific statistics."""
        bus = create_event_bus()
        received: List[ImmediateEvent] = []
        
        def handler(event: ImmediateEvent):
            received.append(event)
        
        subscriber = FunctionSubscriber("stats_sub", handler)
        bus.subscribe(subscriber, SubscriberConfig(subscriber_id="stats_sub"))
        
        event = self.create_sample_event(1)
        bus.publish(event)
        
        time.sleep(0.1)
        
        stats = bus.get_subscriber_stats("stats_sub")
        assert stats is not None
        assert stats["subscriber_id"] == "stats_sub"
        assert stats["events_delivered"] == 1
        assert stats["is_active"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])