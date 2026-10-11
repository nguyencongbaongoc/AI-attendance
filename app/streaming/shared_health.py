"""
Shared health monitor for backend process.

Provides a single StreamHealthMonitor instance shared between
REST API, WebSocket, and SSE layers.
"""

from __future__ import annotations

import logging
from typing import Optional, Callable

from app.config.settings import load_settings
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.streaming.health_events import HealthEvent

logger = logging.getLogger(__name__)

_health_monitor: Optional[StreamHealthMonitor] = None


def get_shared_health_monitor() -> StreamHealthMonitor:
    """Get or create the shared health monitor for the backend process."""
    global _health_monitor
    if _health_monitor is None:
        settings = load_settings()
        _health_monitor = create_health_monitor(
            stale_threshold_seconds=settings.cameras.health_stale_threshold_seconds,
            degraded_threshold_seconds=settings.cameras.health_degraded_threshold_seconds,
            frame_timeout_seconds=10.0,
        )
        _health_monitor.register_camera("CAM1")
        _health_monitor.register_camera("CAM2")
        logger.info("Created shared health monitor for backend process")
    return _health_monitor


def init_shared_health_monitor(event_callback: Optional[Callable[[HealthEvent], None]] = None) -> StreamHealthMonitor:
    """Initialize the shared health monitor with optional event callback."""
    global _health_monitor
    settings = load_settings()
    _health_monitor = create_health_monitor(
        stale_threshold_seconds=settings.cameras.health_stale_threshold_seconds,
        degraded_threshold_seconds=settings.cameras.health_degraded_threshold_seconds,
        frame_timeout_seconds=10.0,
        event_callback=event_callback,
    )
    _health_monitor.register_camera("CAM1")
    _health_monitor.register_camera("CAM2")
    logger.info("Initialized shared health monitor for backend process")
    return _health_monitor