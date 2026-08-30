"""
Phase 32/33 — RTMP + MediaMTX Streaming Infrastructure + Live Health/Failover.

This module provides the camera ingestion infrastructure:
- RTMP publishing/input contract
- MediaMTX configuration
- RTMP → RTSP routing
- Camera stream discovery/health checks
- Stream lifecycle handling
- Reconnect behavior
- Two-camera support: CAM1 + CAM2
- H.264 compatibility verification
- Stream metadata/provenance
- Offline testability
- Deterministic configuration validation
- Integration with existing camera ingestion interface (ReplaySource/ReplayScheduler)
- Live health monitoring
- Frame freshness detection
- Stale frame detection
- Failover and recovery
- Health event generation

Architecture:
RTMP Publisher → MediaMTX → RTSP → RTSP Source Adapter → ReplayScheduler → Existing Pipeline
"""

from __future__ import annotations

# Phase 32: Streaming contracts
from app.streaming.contracts import (
    CameraStreamConfig,
    StreamCodec,
    StreamHealthState,
    StreamMetadata,
    StreamProtocol,
    RTMPPath,
    RTSPPath,
    CameraStreamContract,
    create_camera_stream_contract,
    validate_camera_stream_contract,
)

# Phase 32: MediaMTX configuration
from app.streaming.mediamtx_config import (
    MediaMTXConfig,
    MediaMTXPathConfig,
    create_mediamtx_config,
    validate_mediamtx_config,
    MEDIAMTX_DEFAULT_CONFIG_YAML,
)

# Phase 32: RTSP source adapter (integrates with existing ReplaySource)
from app.streaming.rtsp_source import (
    RTSPSourceConfig,
    RTSPSource,
    RTSPSourceError,
    create_rtsp_source,
)

# Phase 32: Stream health monitoring
from app.streaming.health import (
    StreamHealthMonitor,
    StreamHealthSnapshot,
    HealthCheckResult,
    create_health_monitor,
)

# Phase 32: Reconnect logic
from app.streaming.reconnect import (
    ReconnectConfig,
    ReconnectPolicy,
    ReconnectState,
    ReconnectManager,
    create_reconnect_manager,
)

# Phase 33: Health events
from app.streaming.health_events import (
    HealthEvent,
    HealthEventBatch,
    HealthEventType,
    HealthEventSeverity,
    create_state_change_event,
    create_frame_stale_event,
    create_frame_timeout_event,
    create_reconnect_event,
    create_stream_validated_event,
    create_mediamtx_health_event,
    create_ffmpeg_health_event,
)

__all__ = [
    # Contracts
    "CameraStreamConfig",
    "StreamCodec",
    "StreamHealthState",
    "StreamMetadata",
    "StreamProtocol",
    "RTMPPath",
    "RTSPPath",
    "CameraStreamContract",
    "create_camera_stream_contract",
    "validate_camera_stream_contract",
    # MediaMTX
    "MediaMTXConfig",
    "MediaMTXPathConfig",
    "create_mediamtx_config",
    "validate_mediamtx_config",
    "MEDIAMTX_DEFAULT_CONFIG_YAML",
    # RTSP Source
    "RTSPSourceConfig",
    "RTSPSource",
    "RTSPSourceError",
    "create_rtsp_source",
    # Health
    "StreamHealthMonitor",
    "StreamHealthSnapshot",
    "HealthCheckResult",
    "create_health_monitor",
    # Reconnect
    "ReconnectConfig",
    "ReconnectPolicy",
    "ReconnectState",
    "ReconnectManager",
    "create_reconnect_manager",
    # Phase 33: Health Events
    "HealthEvent",
    "HealthEventBatch",
    "HealthEventType",
    "HealthEventSeverity",
    "create_state_change_event",
    "create_frame_stale_event",
    "create_frame_timeout_event",
    "create_reconnect_event",
    "create_stream_validated_event",
    "create_mediamtx_health_event",
    "create_ffmpeg_health_event",
]