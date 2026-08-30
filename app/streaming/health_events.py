"""
Phase 33 — Stream Health Events.

Health event contracts for live stream monitoring, failover, and recovery.
All events are serializable and use deterministic IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class HealthEventType(str, Enum):
    """Types of health events."""
    STATE_CHANGE = "state_change"
    FRAME_RECEIVED = "frame_received"
    FRAME_STALE = "frame_stale"
    FRAME_TIMEOUT = "frame_timeout"
    RECONNECT_STARTED = "reconnect_started"
    RECONNECT_ATTEMPT = "reconnect_attempt"
    RECONNECT_SUCCESS = "reconnect_success"
    RECONNECT_FAILED = "reconnect_failed"
    RECONNECT_EXHAUSTED = "reconnect_exhausted"
    STREAM_VALIDATED = "stream_validated"
    STREAM_INVALID = "stream_invalid"
    MEDIAMTX_HEALTH = "mediamtx_health"
    FFMPEG_HEALTH = "ffmpeg_health"


class HealthEventSeverity(str, Enum):
    """Severity levels for health events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HealthEvent:
    """
    Health event for stream monitoring.
    
    Contains enough information to diagnose stream state changes.
    """
    event_id: str
    camera_id: str
    event_type: HealthEventType
    severity: HealthEventSeverity
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    reason: str = ""
    reconnect_attempt: int = 0
    max_reconnect_attempts: int = 0
    last_frame_timestamp: Optional[float] = None
    last_frame_index: Optional[int] = None
    source_identifier: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "reason": self.reason,
            "reconnect_attempt": self.reconnect_attempt,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "last_frame_timestamp": self.last_frame_timestamp,
            "last_frame_index": self.last_frame_index,
            "source_identifier": self.source_identifier,
            "details": self.details,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthEvent":
        return cls(
            event_id=data["event_id"],
            camera_id=data["camera_id"],
            event_type=HealthEventType(data["event_type"]),
            severity=HealthEventSeverity(data["severity"]),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            reason=data.get("reason", ""),
            reconnect_attempt=data.get("reconnect_attempt", 0),
            max_reconnect_attempts=data.get("max_reconnect_attempts", 0),
            last_frame_timestamp=data.get("last_frame_timestamp"),
            last_frame_index=data.get("last_frame_index"),
            source_identifier=data.get("source_identifier", ""),
            details=data.get("details", {}),
            schema_version=data.get("schema_version", 1),
        )
@dataclass(frozen=True)
class HealthEventBatch:
    """Batch of health events for efficient processing."""
    events: tuple[HealthEvent, ...]
    camera_id: str
    batch_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "camera_id": self.camera_id,
            "batch_timestamp": self.batch_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthEventBatch":
        return cls(
            events=tuple(HealthEvent.from_dict(e) for e in data["events"]),
            camera_id=data["camera_id"],
            batch_timestamp=data.get("batch_timestamp", datetime.utcnow().isoformat() + "Z"),
        )


def create_state_change_event(
    event_id: str,
    camera_id: str,
    previous_state: str,
    new_state: str,
    reason: str = "",
    source_identifier: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> HealthEvent:
    """Create a state change health event."""
    severity = HealthEventSeverity.INFO
    if new_state in ("offline", "error"):
        severity = HealthEventSeverity.ERROR
    elif new_state in ("degraded", "reconnecting"):
        severity = HealthEventSeverity.WARNING
    
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.STATE_CHANGE,
        severity=severity,
        previous_state=previous_state,
        new_state=new_state,
        reason=reason,
        source_identifier=source_identifier,
        details=details or {},
    )


def create_frame_stale_event(
    event_id: str,
    camera_id: str,
    last_frame_timestamp: float,
    last_frame_index: int,
    stale_duration_seconds: float,
    source_identifier: str = "",
) -> HealthEvent:
    """Create a stale frame health event."""
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.FRAME_STALE,
        severity=HealthEventSeverity.WARNING,
        reason=f"Frame stale for {stale_duration_seconds:.1f}s",
        last_frame_timestamp=last_frame_timestamp,
        last_frame_index=last_frame_index,
        source_identifier=source_identifier,
        details={"stale_duration_seconds": stale_duration_seconds},
    )


def create_frame_timeout_event(
    event_id: str,
    camera_id: str,
    last_frame_timestamp: float,
    last_frame_index: int,
    timeout_seconds: float,
    source_identifier: str = "",
) -> HealthEvent:
    """Create a frame timeout health event."""
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.FRAME_TIMEOUT,
        severity=HealthEventSeverity.ERROR,
        reason=f"Frame timeout after {timeout_seconds:.1f}s",
        last_frame_timestamp=last_frame_timestamp,
        last_frame_index=last_frame_index,
        source_identifier=source_identifier,
        details={"timeout_seconds": timeout_seconds},
    )
def create_reconnect_event(
    event_id: str,
    camera_id: str,
    event_type: HealthEventType,
    attempt: int,
    max_attempts: int,
    reason: str = "",
    source_identifier: str = "",
    success: bool = False,
) -> HealthEvent:
    """Create a reconnect health event."""
    severity = HealthEventSeverity.INFO
    if event_type == HealthEventType.RECONNECT_FAILED:
        severity = HealthEventSeverity.WARNING
    elif event_type == HealthEventType.RECONNECT_EXHAUSTED:
        severity = HealthEventSeverity.ERROR
    elif event_type == HealthEventType.RECONNECT_SUCCESS:
        severity = HealthEventSeverity.INFO
    
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        severity=severity,
        reason=reason,
        reconnect_attempt=attempt,
        max_reconnect_attempts=max_attempts,
        source_identifier=source_identifier,
        details={"success": success},
    )


def create_stream_validated_event(
    event_id: str,
    camera_id: str,
    codec: str,
    width: int,
    height: int,
    fps: float,
    source_identifier: str = "",
) -> HealthEvent:
    """Create a stream validated health event."""
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.STREAM_VALIDATED,
        severity=HealthEventSeverity.INFO,
        reason=f"Stream validated: {codec} {width}x{height}@{fps}fps",
        source_identifier=source_identifier,
        details={
            "codec": codec,
            "width": width,
            "height": height,
            "fps": fps,
        },
    )


def create_mediamtx_health_event(
    event_id: str,
    camera_id: str,
    mediamtx_status: str,
    details: Optional[Dict[str, Any]] = None,
) -> HealthEvent:
    """Create a MediaMTX health event."""
    severity = HealthEventSeverity.INFO
    if mediamtx_status in ("unhealthy", "unreachable"):
        severity = HealthEventSeverity.ERROR
    elif mediamtx_status == "degraded":
        severity = HealthEventSeverity.WARNING
    
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.MEDIAMTX_HEALTH,
        severity=severity,
        reason=f"MediaMTX status: {mediamtx_status}",
        source_identifier="mediamtx",
        details=details or {},
    )


def create_ffmpeg_health_event(
    event_id: str,
    camera_id: str,
    ffmpeg_status: str,
    exit_code: Optional[int] = None,
    stderr: str = "",
    source_identifier: str = "",
) -> HealthEvent:
    """Create an FFmpeg health event."""
    severity = HealthEventSeverity.INFO
    if ffmpeg_status in ("crashed", "terminated", "error"):
        severity = HealthEventSeverity.ERROR
    elif ffmpeg_status == "degraded":
        severity = HealthEventSeverity.WARNING
    
    return HealthEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=HealthEventType.FFMPEG_HEALTH,
        severity=severity,
        reason=f"FFmpeg status: {ffmpeg_status}",
        source_identifier=source_identifier or "ffmpeg",
        details={
            "exit_code": exit_code,
            "stderr": stderr[:500] if stderr else "",
        },
    )