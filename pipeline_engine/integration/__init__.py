"""
PipelineEngine Integration Module

Provides integration clients for Legacy Backend communication.
"""

from pipeline_engine.integration.health_client import (
    LegacyBackendHealthClient,
    HealthClientConfig,
    create_health_client,
    setup_health_reporting,
)

from pipeline_engine.integration.control_client import (
    PipelineEngineControlServer,
    ControlClientConfig,
    create_control_server,
    setup_control_integration,
    Action,
    ControlResult,
    ControlRequest,
    ControlResponse,
)

from pipeline_engine.integration.event_client import (
    EventDeliveryClient,
    EventDeliveryConfig,
    create_event_client,
    setup_event_delivery,
    QueuedEvent,
)

__all__ = [
    # Health
    "LegacyBackendHealthClient",
    "HealthClientConfig",
    "create_health_client",
    "setup_health_reporting",
    # Control
    "PipelineEngineControlServer",
    "ControlClientConfig",
    "create_control_server",
    "setup_control_integration",
    "Action",
    "ControlResult",
    "ControlRequest",
    "ControlResponse",
    # Event Delivery
    "EventDeliveryClient",
    "EventDeliveryConfig",
    "create_event_client",
    "setup_event_delivery",
    "QueuedEvent",
]