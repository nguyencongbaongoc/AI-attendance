"""
Phase 29 — Immediate Event Output Package.

Canonical immediate-event delivery layer that exposes new attendance/IN/OUT events
to the UI and downstream consumers without changing existing event-generation
or attendance logic.
"""

from app.output.contract import (
    ImmediateEvent,
    ImmediateEventType,
    ImmediateEventDirection,
    IdentityCertainty,
    EventDeliveryStatus,
    generate_immediate_event_id,
    validate_immediate_event,
)

from app.output.publisher import (
    EventPublisher,
    EventSubscriber,
    InMemoryEventBus,
    CallbackEventBus,
    BackpressurePolicy,
    SubscriberConfig,
    create_event_bus,
)

from app.output.adapter import (
    ImmediateEventAdapter,
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

__all__ = [
    # Contract
    "ImmediateEvent",
    "ImmediateEventType",
    "ImmediateEventDirection",
    "IdentityCertainty",
    "EventDeliveryStatus",
    "generate_immediate_event_id",
    "validate_immediate_event",
    # Publisher
    "EventPublisher",
    "EventSubscriber",
    "InMemoryEventBus",
    "CallbackEventBus",
    "BackpressurePolicy",
    "SubscriberConfig",
    "create_event_bus",
    # Adapter
    "ImmediateEventAdapter",
    "Phase24ToImmediateEventAdapter",
    "Phase26ToImmediateEventAdapter",
    "Phase25ToImmediateEventAdapter",
    "Phase23ToImmediateEventAdapter",
    "DevelopmentEventSource",
    "create_adapters",
    "create_development_source",
    # UI Adapter
    "UIEvent",
    "UIEventSubscriber",
    "Phase28UIAdapter",
    "MockEventReplacer",
    "create_ui_adapter",
]
