"""
Phase 29 — UI Adapter for Phase 28 Integration.

Connects the ImmediateEvent output layer to the Phase 28 Pinia store.
Replaces the mock event adapter with a clean Immediate Event Adapter.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

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
    CallbackEventBus,
    SubscriberConfig,
    BackpressurePolicy,
)

logger = logging.getLogger(__name__)


@dataclass
class UIEvent:
    """
    UI-friendly event format for the Pinia store.
    
    This is the format expected by the LiveEventTimeline component.
    """
    id: str
    direction: str  # "in" or "out"
    personId: Optional[str]
    cameraId: str
    timestamp: float
    trackId: str
    certainty: str  # "known", "unknown", "ambiguous", "insufficient"
    confidence: float
    globalObservationId: Optional[str] = None
    eventType: Optional[str] = None
    attendanceState: Optional[str] = None
    decisionReason: Optional[str] = None
    deliveryStatus: str = "new"


class UIEventSubscriber(EventSubscriber):
    """
    Subscriber that converts ImmediateEvent to UIEvent and forwards to a callback.
    
    This bridges the Phase 29 output layer to the Phase 28 UI layer.
    """
    
    def __init__(
        self,
        subscriber_id: str,
        ui_callback: Callable[[UIEvent], None],
        error_callback: Optional[Callable[[Exception, Optional[ImmediateEvent]], None]] = None,
        filter_fn: Optional[Callable[[ImmediateEvent], bool]] = None,
    ):
        self._subscriber_id = subscriber_id
        self._ui_callback = ui_callback
        self._error_callback = error_callback
        self._filter_fn = filter_fn
    
    @property
    def subscriber_id(self) -> str:
        return self._subscriber_id
    
    def on_event(self, event: ImmediateEvent) -> None:
        """Convert ImmediateEvent to UIEvent and forward to UI callback."""
        try:
            # Apply filter if provided
            if self._filter_fn and not self._filter_fn(event):
                return
            
            ui_event = self._convert_to_ui_event(event)
            self._ui_callback(ui_event)
        except Exception as e:
            logger.error(f"UI subscriber {self._subscriber_id} failed to convert event: {e}", exc_info=True)
            if self._error_callback:
                self._error_callback(e, event)
    
    def on_error(self, error: Exception, event: Optional[ImmediateEvent]) -> None:
        """Handle delivery errors."""
        logger.error(f"UI subscriber {self._subscriber_id} delivery error: {error}", exc_info=True)
        if self._error_callback:
            self._error_callback(error, event)
    
    def _convert_to_ui_event(self, event: ImmediateEvent) -> UIEvent:
        """Convert ImmediateEvent to UI-friendly format."""
        # Map identity certainty
        certainty_map = {
            IdentityCertainty.KNOWN: "known",
            IdentityCertainty.UNKNOWN: "unknown",
            IdentityCertainty.AMBIGUOUS: "ambiguous",
            IdentityCertainty.INSUFFICIENT: "insufficient",
        }
        
        # Map direction
        direction = "in" if event.direction == ImmediateEventDirection.IN else "out"
        
        # Determine event type for UI
        event_type = event.event_type.value
        
        # Determine attendance state if available
        attendance_state = event.new_attendance_state
        
        return UIEvent(
            id=event.event_id,
            direction=direction,
            personId=event.identity_candidate,
            cameraId=event.camera_id,
            timestamp=event.event_timestamp,
            trackId=event.local_track_id,
            certainty=certainty_map.get(event.identity_certainty, "unknown"),
            confidence=event.identity_confidence,
            globalObservationId=event.global_observation_id,
            eventType=event_type,
            attendanceState=attendance_state,
            decisionReason=event.decision_reason,
            deliveryStatus=event.delivery_status.value,
        )


class Phase28UIAdapter:
    """
    Adapter that connects Phase 29 event bus to Phase 28 Pinia store.
    
    This replaces the mock event adapter in Phase 28 with a clean integration.
    """
    
    def __init__(
        self,
        event_bus: CallbackEventBus,
        pinia_store_callback: Callable[[UIEvent], None],
        subscriber_id: str = "phase28_ui",
        queue_size: int = 1000,
        backpressure_policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
    ):
        """
        Initialize the UI adapter.
        
        Args:
            event_bus: The Phase 29 event bus
            pinia_store_callback: Callback to Pinia store's addLiveEvent action
            subscriber_id: Unique subscriber ID
            queue_size: Subscriber queue size
            backpressure_policy: Backpressure policy for slow UI
        """
        self._event_bus = event_bus
        self._pinia_callback = pinia_store_callback
        self._subscriber_id = subscriber_id
        self._subscriber: Optional[UIEventSubscriber] = None
        self._config = SubscriberConfig(
            subscriber_id=subscriber_id,
            queue_size=queue_size,
            backpressure_policy=backpressure_policy,
            name="Phase28 UI Adapter",
        )
        self._is_connected = False
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect the adapter to the event bus."""
        with self._lock:
            if self._is_connected:
                logger.warning(f"UI adapter {self._subscriber_id} already connected")
                return False
            
            self._subscriber = UIEventSubscriber(
                subscriber_id=self._subscriber_id,
                ui_callback=self._pinia_callback,
                error_callback=self._on_subscriber_error,
            )
            
            success = self._event_bus.subscribe(self._subscriber, self._config)
            if success:
                self._is_connected = True
                logger.info(f"Phase 28 UI adapter connected: {self._subscriber_id}")
            return success
    
    def disconnect(self) -> bool:
        """Disconnect the adapter from the event bus."""
        with self._lock:
            if not self._is_connected:
                return False
            
            success = self._event_bus.unsubscribe(self._subscriber_id)
            if success:
                self._is_connected = False
                self._subscriber = None
                logger.info(f"Phase 28 UI adapter disconnected: {self._subscriber_id}")
            return success
    
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._is_connected
    
    def _on_subscriber_error(self, error: Exception, event: Optional[ImmediateEvent]) -> None:
        """Handle subscriber errors."""
        logger.error(f"UI adapter subscriber error: {error}")
        # Could emit to error tracking here
    
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get subscriber statistics."""
        return self._event_bus.get_subscriber_stats(self._subscriber_id)


class MockEventReplacer:
    """
    Utility to replace Phase 28's mock event initialization with real events.
    
    This helps transition from mock data to real Phase 29 events.
    """
    
    def __init__(self, ui_adapter: Phase28UIAdapter):
        self._ui_adapter = ui_adapter
    
    def replace_mock_initialization(self, store: Any) -> None:
        """
        Replace the store's initializeMockData with a version that uses real events.
        
        This is a development utility - in production, events come from the pipeline.
        """
        original_init = store.initializeMockData
        
        def new_initialize():
            # First, connect the adapter if not connected
            if not self._ui_adapter.is_connected():
                self._ui_adapter.connect()
            
            # Call original to set up camera feeds and attendance summary
            original_init()
            
            # Clear mock events - they'll be replaced by real events
            store.liveEvents = []
            logger.info("Mock events cleared - waiting for real Phase 29 events")
        
        store.initializeMockData = new_initialize
        logger.info("Phase 28 mock initialization replaced with Phase 29 adapter")


def create_ui_adapter(
    event_bus: CallbackEventBus,
    pinia_store_callback: Callable[[UIEvent], None],
    subscriber_id: str = "phase28_ui",
) -> Phase28UIAdapter:
    """Factory function to create UI adapter."""
    return Phase28UIAdapter(
        event_bus=event_bus,
        pinia_store_callback=pinia_store_callback,
        subscriber_id=subscriber_id,
    )