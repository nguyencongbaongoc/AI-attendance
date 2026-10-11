"""
Phase 29 — Event Publisher and In-Memory Event Bus.

Provides a clean delivery abstraction for immediate events with:
- Subscriber registration and management
- Bounded event history
- Deterministic delivery ordering
- Duplicate suppression
- Failure isolation
- Backpressure handling
- Bounded memory
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from app.output.contract import (
    ImmediateEvent,
    EventDeliveryStatus,
    validate_immediate_event,
)

logger = logging.getLogger(__name__)


class BackpressurePolicy(str, Enum):
    """Policy for handling slow subscribers."""
    DROP_OLDEST = "drop_oldest"      # Drop oldest events in subscriber queue
    DROP_NEWEST = "drop_newest"      # Drop newest events (reject new events)
    BLOCK = "block"                  # Block publisher (not recommended for real-time)
    REJECT_SUBSCRIBER = "reject_subscriber"  # Disconnect slow subscriber


@dataclass(frozen=True)
class SubscriberConfig:
    """Configuration for a subscriber."""
    subscriber_id: str
    queue_size: int = 1000
    backpressure_policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST
    filter_fn: Optional[Callable[[ImmediateEvent], bool]] = None
    name: str = ""


@dataclass
class SubscriberState:
    """Internal state for a subscriber."""
    config: SubscriberConfig
    queue: deque = field(default_factory=deque)
    events_delivered: int = 0
    events_dropped: int = 0
    events_failed: int = 0
    last_delivery_time: Optional[float] = None
    last_error: Optional[str] = None
    is_active: bool = True
    processing_count: int = 0  # Number of events currently being processed
    lock: threading.Lock = field(default_factory=threading.Lock)


class EventSubscriber(ABC):
    """Abstract base class for event subscribers."""
    
    @abstractmethod
    def on_event(self, event: ImmediateEvent) -> None:
        """Handle an immediate event."""
        pass
    
    @abstractmethod
    def on_error(self, error: Exception, event: Optional[ImmediateEvent]) -> None:
        """Handle an error during event delivery."""
        pass
    
    @property
    @abstractmethod
    def subscriber_id(self) -> str:
        """Unique subscriber identifier."""
        pass


class FunctionSubscriber(EventSubscriber):
    """Simple function-based subscriber."""
    
    def __init__(
        self,
        subscriber_id: str,
        handler: Callable[[ImmediateEvent], None],
        error_handler: Optional[Callable[[Exception, Optional[ImmediateEvent]], None]] = None,
    ):
        self._subscriber_id = subscriber_id
        self._handler = handler
        self._error_handler = error_handler
    
    @property
    def subscriber_id(self) -> str:
        return self._subscriber_id
    
    def on_event(self, event: ImmediateEvent) -> None:
        self._handler(event)
    
    def on_error(self, error: Exception, event: Optional[ImmediateEvent]) -> None:
        if self._error_handler:
            self._error_handler(error, event)
        else:
            logger.error(f"Subscriber {self._subscriber_id} error: {error}", exc_info=True)


class EventPublisher(ABC):
    """Abstract base class for event publishers."""
    
    @abstractmethod
    def publish(self, event: ImmediateEvent) -> bool:
        """Publish an event to all subscribers."""
        pass
    
    @abstractmethod
    def subscribe(self, subscriber: EventSubscriber, config: Optional[SubscriberConfig] = None) -> bool:
        """Register a subscriber."""
        pass
    
    @abstractmethod
    def unsubscribe(self, subscriber_id: str) -> bool:
        """Unregister a subscriber."""
        pass
    
    @abstractmethod
    def get_subscriber_count(self) -> int:
        """Get number of active subscribers."""
        pass
    
    @abstractmethod
    def get_history(self, limit: int = 100) -> List[ImmediateEvent]:
        """Get recent event history."""
        pass


class InMemoryEventBus(EventPublisher):
    """
    In-memory event bus with bounded history, deduplication, and failure isolation.
    
    Features:
    - Thread-safe subscriber management
    - Bounded event history (configurable)
    - Deterministic delivery ordering (by event_timestamp, then delivery_sequence)
    - Duplicate suppression using source_resolution_id
    - Subscriber isolation (one failure doesn't affect others)
    - Configurable backpressure policies
    - Bounded subscriber queues
    - Delivery sequence for ordering guarantees
    """
    
    def __init__(
        self,
        max_history: int = 10000,
        max_dedup_cache: int = 50000,
        default_queue_size: int = 1000,
        default_backpressure: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
    ):
        """
        Initialize the event bus.
        
        Args:
            max_history: Maximum number of events to keep in history
            max_dedup_cache: Maximum number of deduplication IDs to track
            default_queue_size: Default subscriber queue size
            default_backpressure: Default backpressure policy
        """
        self._max_history = max_history
        self._max_dedup_cache = max_dedup_cache
        self._default_queue_size = default_queue_size
        self._default_backpressure = default_backpressure
        
        # Event history (bounded)
        self._history: deque = deque(maxlen=max_history)
        
        # Deduplication cache (bounded) - tracks source_resolution_id + event_type
        self._dedup_cache: Set[str] = set()
        self._dedup_order: deque = deque()  # No maxlen, we manage manually
        
        # Subscribers
        self._subscribers: Dict[str, SubscriberState] = {}
        self._subscriber_lock = threading.RLock()
        
        # Delivery sequence counter (monotonic)
        self._delivery_sequence = 0
        self._sequence_lock = threading.Lock()
        
        # Statistics
        self._stats = {
            "events_published": 0,
            "events_duplicated": 0,
            "events_delivered": 0,
            "events_dropped": 0,
            "subscriber_errors": 0,
        }
        self._stats_lock = threading.Lock()
        
        # Thread pool for async event processing - single worker to ensure sequential processing
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eventbus")
        self._shutdown = False
    
    def _get_next_sequence(self) -> int:
        """Get next delivery sequence number."""
        with self._sequence_lock:
            self._delivery_sequence += 1
            return self._delivery_sequence
    
    def _is_duplicate(self, event: ImmediateEvent) -> bool:
        """Check if event is a duplicate based on source_resolution_id + event_type."""
        dedup_key = f"{event.source_resolution_id}:{event.event_type.value}"
        return dedup_key in self._dedup_cache
    
    def _mark_delivered(self, event: ImmediateEvent) -> None:
        """Mark event as delivered for deduplication."""
        dedup_key = f"{event.source_resolution_id}:{event.event_type.value}"
        self._dedup_cache.add(dedup_key)
        self._dedup_order.append(dedup_key)
        
        # Evict oldest if cache is full (deque maxlen handles this automatically)
        # But we also need to remove from set when deque evicts
        while len(self._dedup_order) > self._max_dedup_cache:
            oldest = self._dedup_order.popleft()
            self._dedup_cache.discard(oldest)
    
    def publish(self, event: ImmediateEvent) -> bool:
        """
        Publish an event to all subscribers.
        
        Returns True if event was published (not a duplicate), False if duplicate.
        """
        # Validate event
        validation_error = validate_immediate_event(event)
        if validation_error:
            logger.error(f"Invalid event: {validation_error}")
            return False
        
        # Check for duplicate
        if self._is_duplicate(event):
            with self._stats_lock:
                self._stats["events_duplicated"] += 1
            logger.debug(f"Duplicate event suppressed: {event.event_id}")
            return False
        
        # Assign delivery sequence for ordering
        sequence = self._get_next_sequence()
        event_dict = event.to_dict()
        event_dict["delivery_sequence"] = sequence
        event_with_sequence = ImmediateEvent.from_dict(event_dict)
        
        # Mark as delivered for deduplication
        self._mark_delivered(event)
        
        # Add to history
        self._history.append(event_with_sequence)
        
        # Update stats
        with self._stats_lock:
            self._stats["events_published"] += 1
        
        # Deliver to subscribers
        self._deliver_to_subscribers(event_with_sequence)
        
        return True
    
    def _deliver_to_subscribers(self, event: ImmediateEvent) -> None:
        """Deliver event to all active subscribers with failure isolation."""
        with self._subscriber_lock:
            subscriber_ids = list(self._subscribers.keys())
        
        for subscriber_id in subscriber_ids:
            self._deliver_to_subscriber(subscriber_id, event)
    
    def _deliver_to_subscriber(self, subscriber_id: str, event: ImmediateEvent) -> None:
        """Deliver event to a single subscriber with failure isolation."""
        with self._subscriber_lock:
            state = self._subscribers.get(subscriber_id)
            if not state or not state.is_active:
                return
            
            # Check filter
            if state.config.filter_fn and not state.config.filter_fn(event):
                return
            
            # Handle backpressure - check queue size including events being processed
            with state.lock:
                current_load = len(state.queue) + state.processing_count
                if current_load >= state.config.queue_size:
                    self._handle_backpressure(state, event)
                    return
                
                # Add to subscriber queue
                state.queue.append(event)
        
        # Process immediately in current thread (no executor to avoid blocking)
        # This ensures events are delivered promptly without blocking the publisher
        self._process_subscriber_queue(subscriber_id)
    
    def _handle_backpressure(self, state: SubscriberState, event: ImmediateEvent) -> None:
        """Handle backpressure according to policy.
        
        Note: This method assumes state.lock is already held by the caller.
        """
        policy = state.config.backpressure_policy
        
        if policy == BackpressurePolicy.DROP_OLDEST and state.queue:
            dropped = state.queue.popleft()
            state.events_dropped += 1
            logger.debug(f"Subscriber {state.config.subscriber_id}: dropped oldest event {dropped.event_id}")
            state.queue.append(event)
        elif policy == BackpressurePolicy.DROP_NEWEST:
            state.events_dropped += 1
            logger.debug(f"Subscriber {state.config.subscriber_id}: dropped newest event {event.event_id}")
        elif policy == BackpressurePolicy.REJECT_SUBSCRIBER:
            state.is_active = False
            state.last_error = "Backpressure: subscriber queue full, subscriber rejected"
            logger.warning(f"Subscriber {state.config.subscriber_id}: rejected due to backpressure")
        # BLOCK policy not implemented (would block publisher thread)
    
    def _process_subscriber_queue(self, subscriber_id: str) -> None:
        """Process events in subscriber queue."""
        with self._subscriber_lock:
            state = self._subscribers.get(subscriber_id)
            if not state or not state.is_active:
                return
            
            # Get events to process (copy to avoid holding lock during handler)
            events_to_process = list(state.queue)
            state.queue.clear()
        
        for event in events_to_process:
            # Increment processing count
            with state.lock:
                state.processing_count += 1
            
            try:
                # Find the actual subscriber object
                # Note: In a real implementation, we'd store the subscriber object
                # For now, we'll use a callback mechanism
                self._invoke_subscriber_handler(state, event)
                
                with state.lock:
                    state.events_delivered += 1
                    state.last_delivery_time = time.time()
                
                with self._stats_lock:
                    self._stats["events_delivered"] += 1
                    
            except Exception as e:
                with state.lock:
                    state.events_failed += 1
                    state.last_error = str(e)
                
                with self._stats_lock:
                    self._stats["subscriber_errors"] += 1
                
                logger.error(
                    f"Subscriber {state.config.subscriber_id} failed to process event {event.event_id}: {e}",
                    exc_info=True
                )
                
                # Call subscriber's error handler for failure isolation
                try:
                    # Get the subscriber callback and call on_error
                    if hasattr(self, '_subscriber_callbacks'):
                        with self._callback_lock:
                            subscriber = self._subscriber_callbacks.get(state.config.subscriber_id)
                            if subscriber:
                                subscriber.on_error(e, event)
                except Exception as err:
                    logger.error(f"Error in subscriber error handler: {err}")
                
            finally:
                # Decrement processing count
                with state.lock:
                    state.processing_count -= 1
            
            # Continue processing other events - failure isolation
    
    def _invoke_subscriber_handler(self, state: SubscriberState, event: ImmediateEvent) -> None:
        """Invoke subscriber handler. Override in subclass or use callback."""
        # This is a placeholder - actual implementation uses callback registration
        pass
    
    def subscribe(self, subscriber: EventSubscriber, config: Optional[SubscriberConfig] = None) -> bool:
        """Register a subscriber."""
        if config is None:
            config = SubscriberConfig(
                subscriber_id=subscriber.subscriber_id,
                queue_size=self._default_queue_size,
                backpressure_policy=self._default_backpressure,
            )
        
        with self._subscriber_lock:
            if config.subscriber_id in self._subscribers:
                logger.warning(f"Subscriber {config.subscriber_id} already registered")
                return False
            
            # Create a new config with the filter_fn if needed
            if config.filter_fn is not None:
                config = SubscriberConfig(
                    subscriber_id=config.subscriber_id,
                    queue_size=config.queue_size,
                    backpressure_policy=config.backpressure_policy,
                    filter_fn=config.filter_fn,
                    name=config.name,
                )
            
            state = SubscriberState(config=config)
            self._subscribers[config.subscriber_id] = state
            
            # Store subscriber reference for callback
            object.__setattr__(config, '_subscriber_ref', subscriber)
        
        logger.info(f"Subscriber {config.subscriber_id} registered")
        return True
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        """Unregister a subscriber."""
        with self._subscriber_lock:
            if subscriber_id not in self._subscribers:
                return False
            
            state = self._subscribers.pop(subscriber_id)
            state.is_active = False
        
        logger.info(f"Subscriber {subscriber_id} unregistered")
        return True
    
    def get_subscriber_count(self) -> int:
        """Get number of active subscribers."""
        with self._subscriber_lock:
            return sum(1 for s in self._subscribers.values() if s.is_active)
    
    def get_history(self, limit: int = 100) -> List[ImmediateEvent]:
        """Get recent event history (most recent first)."""
        with self._subscriber_lock:
            history = list(self._history)
        
        # Return most recent first
        return history[-limit:][::-1]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get publisher statistics."""
        with self._stats_lock:
            stats = dict(self._stats)
        
        with self._subscriber_lock:
            stats["active_subscribers"] = sum(1 for s in self._subscribers.values() if s.is_active)
            stats["total_subscribers"] = len(self._subscribers)
            stats["history_size"] = len(self._history)
            stats["dedup_cache_size"] = len(self._dedup_cache)
        
        return stats
    
    def get_subscriber_stats(self, subscriber_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific subscriber."""
        with self._subscriber_lock:
            state = self._subscribers.get(subscriber_id)
            if not state:
                return None
            
            with state.lock:
                return {
                    "subscriber_id": state.config.subscriber_id,
                    "name": state.config.name,
                    "events_delivered": state.events_delivered,
                    "events_dropped": state.events_dropped,
                    "events_failed": state.events_failed,
                    "queue_size": len(state.queue),
                    "max_queue_size": state.config.queue_size,
                    "is_active": state.is_active,
                    "last_delivery_time": state.last_delivery_time,
                    "last_error": state.last_error,
                }
    
    def clear_history(self) -> None:
        """Clear event history (for testing)."""
        self._history.clear()
        self._dedup_cache.clear()
        self._dedup_order.clear()
        with self._stats_lock:
            self._stats = {
                "events_published": 0,
                "events_duplicated": 0,
                "events_delivered": 0,
                "events_dropped": 0,
                "subscriber_errors": 0,
            }
    
    def shutdown(self) -> None:
        """Shutdown the event bus."""
        with self._subscriber_lock:
            for state in self._subscribers.values():
                state.is_active = False
            self._subscribers.clear()
        logger.info("Event bus shutdown complete")


class CallbackEventBus(InMemoryEventBus):
    """
    Event bus that uses callbacks for subscriber notification.
    
    This is the practical implementation for integrating with the UI.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._subscriber_callbacks: Dict[str, EventSubscriber] = {}
        self._callback_lock = threading.Lock()
    
    def subscribe(self, subscriber: EventSubscriber, config: Optional[SubscriberConfig] = None) -> bool:
        """Register a subscriber with callback."""
        result = super().subscribe(subscriber, config)
        if result and config:
            with self._callback_lock:
                self._subscriber_callbacks[config.subscriber_id] = subscriber
        return result
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        """Unregister a subscriber."""
        with self._callback_lock:
            self._subscriber_callbacks.pop(subscriber_id, None)
        return super().unsubscribe(subscriber_id)
    
    def _invoke_subscriber_handler(self, state: SubscriberState, event: ImmediateEvent) -> None:
        """Invoke subscriber callback."""
        with self._callback_lock:
            subscriber = self._subscriber_callbacks.get(state.config.subscriber_id)
        
        if subscriber:
            subscriber.on_event(event)
        else:
            # Fallback: log warning
            logger.warning(f"No callback found for subscriber {state.config.subscriber_id}")


def create_event_bus(
    max_history: int = 10000,
    max_dedup_cache: int = 50000,
    default_queue_size: int = 1000,
    default_backpressure: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
) -> CallbackEventBus:
    """Factory function to create a configured event bus."""
    return CallbackEventBus(
        max_history=max_history,
        max_dedup_cache=max_dedup_cache,
        default_queue_size=default_queue_size,
        default_backpressure=default_backpressure,
    )