"""
Phase 32/33 — Stream Health Monitoring.

Explicit health states for camera streams with diagnostic information.
Phase 33 adds:
- Frame freshness monitoring
- Stale frame detection
- Health event generation
- Live runtime health tracking
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.streaming.contracts import StreamHealthState
from app.streaming.health_events import (
    HealthEvent,
    HealthEventType,
    HealthEventSeverity,
    create_state_change_event,
    create_frame_stale_event,
    create_frame_timeout_event,
    create_reconnect_event,
    create_stream_validated_event,
)


@dataclass(frozen=True)
class HealthCheckResult:
    """Result of a single health check."""
    camera_id: str
    state: StreamHealthState
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    last_successful_frame: Optional[int] = None
    last_successful_time: Optional[float] = None
    failure_reason: Optional[str] = None
    reconnect_count: int = 0
    consecutive_failures: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "state": self.state.value,
            "timestamp": self.timestamp,
            "message": self.message,
            "details": self.details,
            "last_successful_frame": self.last_successful_frame,
            "last_successful_time": self.last_successful_time,
            "failure_reason": self.failure_reason,
            "reconnect_count": self.reconnect_count,
            "consecutive_failures": self.consecutive_failures,
        }
    
    @classmethod
    def healthy(cls, camera_id: str, frame_count: int, timestamp: float) -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.LIVE,
            message="Stream healthy",
            last_successful_frame=frame_count,
            last_successful_time=timestamp,
            consecutive_failures=0,
        )
    
    @classmethod
    def degraded(cls, camera_id: str, message: str, frame_count: int, timestamp: float) -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.DEGRADED,
            message=message,
            last_successful_frame=frame_count,
            last_successful_time=timestamp,
        )
    
    @classmethod
    def offline(cls, camera_id: str, reason: str = "Stream offline") -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.OFFLINE,
            message=reason,
            failure_reason=reason,
        )
    
    @classmethod
    def connecting(cls, camera_id: str) -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.CONNECTING,
            message="Connecting to stream",
        )
    
    @classmethod
    def reconnecting(cls, camera_id: str, attempt: int, max_attempts: int) -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.RECONNECTING,
            message=f"Reconnecting (attempt {attempt}/{max_attempts})",
            reconnect_count=attempt,
        )
    
    @classmethod
    def error(cls, camera_id: str, reason: str, frame_count: int = 0) -> "HealthCheckResult":
        return cls(
            camera_id=camera_id,
            state=StreamHealthState.ERROR,
            message=f"Stream error: {reason}",
            failure_reason=reason,
            last_successful_frame=frame_count if frame_count > 0 else None,
        )


@dataclass
class StreamHealthSnapshot:
    """Snapshot of stream health at a point in time."""
    camera_id: str
    state: StreamHealthState
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    frames_received: int = 0
    frames_dropped: int = 0
    bytes_received: int = 0
    last_frame_time: Optional[float] = None
    last_frame_timestamp: Optional[float] = None
    uptime_seconds: float = 0.0
    total_errors: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[str] = None
    reconnect_count: int = 0
    last_reconnect_time: Optional[str] = None
    current_resolution: Optional[tuple] = None
    current_fps: Optional[float] = None
    current_codec: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "state": self.state.value,
            "timestamp": self.timestamp,
            "frames_received": self.frames_received,
            "frames_dropped": self.frames_dropped,
            "bytes_received": self.bytes_received,
            "last_frame_time": self.last_frame_time,
            "last_frame_timestamp": self.last_frame_timestamp,
            "uptime_seconds": self.uptime_seconds,
            "total_errors": self.total_errors,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
            "reconnect_count": self.reconnect_count,
            "last_reconnect_time": self.last_reconnect_time,
            "current_resolution": list(self.current_resolution) if self.current_resolution else None,
            "current_fps": self.current_fps,
            "current_codec": self.current_codec,
        }
class StreamHealthMonitor:
    """
    Monitors health of camera streams.
    
    Provides explicit health states with diagnostic information.
    Does not use wall-clock-dependent logic in deterministic tests.
    
    Phase 33 additions:
    - Frame freshness monitoring
    - Stale frame detection
    - Health event generation
    - Live runtime health tracking
    """
    
    def __init__(
        self,
        stale_threshold_seconds: float = 5.0,
        degraded_threshold_seconds: float = 2.0,
        frame_timeout_seconds: float = 10.0,
        max_consecutive_missing_frames: int = 30,
        event_callback: Optional[Callable[[HealthEvent], None]] = None,
        time_func: Optional[Callable[[], float]] = None,
    ):
        self.stale_threshold = stale_threshold_seconds
        self.degraded_threshold = degraded_threshold_seconds
        self.frame_timeout = frame_timeout_seconds
        self.max_consecutive_missing_frames = max_consecutive_missing_frames
        self._event_callback = event_callback
        self._time_func = time_func or time.time
        
        self._snapshots: Dict[str, StreamHealthSnapshot] = {}
        self._start_times: Dict[str, float] = {}
        self._last_check_results: Dict[str, HealthCheckResult] = {}
        self._event_counter: Dict[str, int] = {}
        self._last_frame_indices: Dict[str, int] = {}
        self._consecutive_missing_frames: Dict[str, int] = {}
    
    def register_camera(self, camera_id: str) -> None:
        """Register a camera for monitoring."""
        if camera_id not in self._snapshots:
            self._snapshots[camera_id] = StreamHealthSnapshot(
                camera_id=camera_id,
                state=StreamHealthState.OFFLINE,
            )
            self._start_times[camera_id] = self._time_func()
    
    def unregister_camera(self, camera_id: str) -> None:
        """Unregister a camera."""
        self._snapshots.pop(camera_id, None)
        self._start_times.pop(camera_id, None)
        self._last_check_results.pop(camera_id, None)
    
    def update_frame_received(
        self,
        camera_id: str,
        frame_index: int,
        timestamp: float,
        frame_size: int = 0,
        resolution: Optional[tuple] = None,
        fps: Optional[float] = None,
        codec: Optional[str] = None,
        current_time: Optional[float] = None,
    ) -> None:
        """Update health when a frame is received."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        if current_time is None:
            current_time = self._time_func()
        
        # Track frame freshness
        prev_frame_index = self._last_frame_indices.get(camera_id, -1)
        if frame_index > prev_frame_index + 1:
            # Frames were missed
            missed = frame_index - prev_frame_index - 1
            self._consecutive_missing_frames[camera_id] = self._consecutive_missing_frames.get(camera_id, 0) + missed
        else:
            self._consecutive_missing_frames[camera_id] = 0
        
        self._last_frame_indices[camera_id] = frame_index
        
        snapshot.frames_received += 1
        snapshot.bytes_received += frame_size
        snapshot.last_frame_time = current_time
        snapshot.last_frame_timestamp = timestamp
        snapshot.uptime_seconds = current_time - self._start_times.get(camera_id, current_time)
        
        if resolution:
            snapshot.current_resolution = resolution
        if fps:
            snapshot.current_fps = fps
        if codec:
            snapshot.current_codec = codec
        
        prev_state = snapshot.state
        if snapshot.state in (StreamHealthState.OFFLINE, StreamHealthState.CONNECTING, StreamHealthState.RECONNECTING, StreamHealthState.ERROR):
            snapshot.state = StreamHealthState.LIVE
            self._emit_event(create_state_change_event(
                event_id=f"{snapshot.camera_id}-{self._get_event_counter(snapshot.camera_id)}",
                camera_id=snapshot.camera_id,
                previous_state=prev_state.value,
                new_state=StreamHealthState.LIVE.value,
                reason="Frame flow restored",
                source_identifier="rtsp",
            ))
        elif snapshot.state == StreamHealthState.DEGRADED:
            snapshot.state = StreamHealthState.LIVE
            self._emit_event(create_state_change_event(
                event_id=f"{snapshot.camera_id}-{self._get_event_counter(snapshot.camera_id)}",
                camera_id=snapshot.camera_id,
                previous_state=prev_state.value,
                new_state=StreamHealthState.LIVE.value,
                reason="Frame flow restored from degraded",
                source_identifier="rtsp",
            ))
        
        # Emit stream validated event on first frame with metadata
        if snapshot.frames_received == 1 and codec and resolution and fps:
            self._emit_event(create_stream_validated_event(
                event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
                camera_id=camera_id,
                codec=codec,
                width=resolution[0],
                height=resolution[1],
                fps=fps,
                source_identifier="rtsp",
            ))
    
    def update_frame_dropped(self, camera_id: str) -> None:
        """Update health when a frame is dropped."""
        self.register_camera(camera_id)
        self._snapshots[camera_id].frames_dropped += 1
    
    def update_error(self, camera_id: str, error: str) -> None:
        """Update health when an error occurs."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        snapshot.total_errors += 1
        snapshot.last_error = error
        snapshot.last_error_time = datetime.utcnow().isoformat() + "Z"
        
        if snapshot.state == StreamHealthState.LIVE:
            snapshot.state = StreamHealthState.DEGRADED
        elif snapshot.state == StreamHealthState.DEGRADED:
            snapshot.state = StreamHealthState.ERROR

    def update_reconnect(self, camera_id: str, attempt: int) -> None:
        """Update health during reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.reconnect_count = attempt
        snapshot.last_reconnect_time = datetime.utcnow().isoformat() + "Z"
        snapshot.state = StreamHealthState.RECONNECTING
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_ATTEMPT,
            attempt=attempt,
            max_attempts=5,  # Default, could be configurable
            reason=f"Reconnect attempt {attempt}",
            source_identifier="rtsp",
        ))

    def update_reconnect_success(self, camera_id: str) -> None:
        """Update health after successful reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.state = StreamHealthState.LIVE
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_SUCCESS,
            attempt=snapshot.reconnect_count,
            max_attempts=5,
            reason="Reconnection successful",
            source_identifier="rtsp",
            success=True,
        ))

    def update_reconnect_failed(self, camera_id: str, reason: str) -> None:
        """Update health after failed reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.state = StreamHealthState.ERROR
        snapshot.last_error = f"Reconnect failed: {reason}"
        snapshot.last_error_time = datetime.utcnow().isoformat() + "Z"
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_FAILED,
            attempt=snapshot.reconnect_count,
            max_attempts=5,
            reason=f"Reconnect failed: {reason}",
            source_identifier="rtsp",
        ))
    
    def _get_event_counter(self, camera_id: str) -> int:
        """Get and increment event counter for a camera."""
        if camera_id not in self._event_counter:
            self._event_counter[camera_id] = 0
        self._event_counter[camera_id] += 1
        return self._event_counter[camera_id]

    def _emit_event(self, event: HealthEvent) -> None:
        """Emit a health event."""
        if self._event_callback:
            self._event_callback(event)

    def check_health(self, camera_id: str, current_time: Optional[float] = None) -> HealthCheckResult:
        """Perform health check for a camera."""
        if current_time is None:
            current_time = self._time_func()
        
        self.register_camera(camera_id)
        snapshot = self._snapshots[camera_id]
        
        if snapshot.last_frame_time is None:
            if snapshot.state == StreamHealthState.CONNECTING:
                result = HealthCheckResult.connecting(camera_id)
            elif snapshot.state == StreamHealthState.RECONNECTING:
                result = HealthCheckResult.reconnecting(
                    camera_id, snapshot.reconnect_count, 3
                )
            else:
                result = HealthCheckResult.offline(camera_id, "No frames received")
        else:
            time_since_frame = current_time - snapshot.last_frame_time
            
            # State-specific checks FIRST - these take precedence
            if snapshot.state == StreamHealthState.RECONNECTING:
                result = HealthCheckResult.reconnecting(
                    camera_id, snapshot.reconnect_count, 3
                )
            elif snapshot.state == StreamHealthState.CONNECTING:
                result = HealthCheckResult.connecting(camera_id)
            elif snapshot.state == StreamHealthState.ERROR:
                result = HealthCheckResult.error(
                    camera_id,
                    snapshot.last_error or "Unknown error",
                    snapshot.frames_received,
                )
            else:
                # Only check frame freshness for LIVE/DEGRADED/OFFLINE states
                # Check for stale frames
                if time_since_frame > self.frame_timeout:
                    prev_state = snapshot.state
                    if snapshot.state != StreamHealthState.ERROR:
                        snapshot.state = StreamHealthState.ERROR
                        self._emit_event(create_frame_timeout_event(
                            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
                            camera_id=camera_id,
                            last_frame_timestamp=snapshot.last_frame_timestamp or 0,
                            last_frame_index=snapshot.frames_received,
                            timeout_seconds=time_since_frame,
                            source_identifier="rtsp",
                        ))
                    
                    result = HealthCheckResult.error(
                        camera_id,
                        f"No frames for {time_since_frame:.1f}s (timeout: {self.frame_timeout}s)",
                        snapshot.frames_received,
                    )
                elif time_since_frame >= self.degraded_threshold:
                    prev_state = snapshot.state
                    if snapshot.state != StreamHealthState.DEGRADED and snapshot.state != StreamHealthState.ERROR:
                        snapshot.state = StreamHealthState.DEGRADED
                        self._emit_event(create_frame_stale_event(
                            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
                            camera_id=camera_id,
                            last_frame_timestamp=snapshot.last_frame_timestamp or 0,
                            last_frame_index=snapshot.frames_received,
                            stale_duration_seconds=time_since_frame,
                            source_identifier="rtsp",
                        ))
                    
                    result = HealthCheckResult.degraded(
                        camera_id,
                        f"Frame delay: {time_since_frame:.1f}s",
                        snapshot.frames_received,
                        snapshot.last_frame_timestamp or 0,
                    )
                elif self._consecutive_missing_frames.get(camera_id, 0) > self.max_consecutive_missing_frames:
                    prev_state = snapshot.state
                    if snapshot.state != StreamHealthState.DEGRADED and snapshot.state != StreamHealthState.ERROR:
                        snapshot.state = StreamHealthState.DEGRADED
                        self._emit_event(create_state_change_event(
                            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
                            camera_id=camera_id,
                            previous_state=prev_state.value,
                            new_state=StreamHealthState.DEGRADED.value,
                            reason=f"Too many missing frames: {self._consecutive_missing_frames[camera_id]}",
                            source_identifier="rtsp",
                        ))
                    
                    result = HealthCheckResult.degraded(
                        camera_id,
                        f"Too many missing frames: {self._consecutive_missing_frames[camera_id]}",
                        snapshot.frames_received,
                        snapshot.last_frame_timestamp or 0,
                    )
                else:
                    result = HealthCheckResult.healthy(
                        camera_id,
                        snapshot.frames_received,
                        snapshot.last_frame_timestamp or 0,
                    )
        
        # Create a new result with details since HealthCheckResult is frozen
        result = HealthCheckResult(
            camera_id=result.camera_id,
            state=result.state,
            timestamp=result.timestamp,
            message=result.message,
            details={
                "frames_received": snapshot.frames_received,
                "frames_dropped": snapshot.frames_dropped,
                "total_errors": snapshot.total_errors,
                "uptime_seconds": snapshot.uptime_seconds,
                "current_resolution": snapshot.current_resolution,
                "current_fps": snapshot.current_fps,
                "current_codec": snapshot.current_codec,
            },
            last_successful_frame=result.last_successful_frame,
            last_successful_time=result.last_successful_time,
            failure_reason=result.failure_reason,
            reconnect_count=snapshot.reconnect_count,
            consecutive_failures=result.consecutive_failures,
        )
        
        self._last_check_results[camera_id] = result
        return result

    def check_all_health(self, current_time: Optional[float] = None) -> Dict[str, HealthCheckResult]:
        """Check health for all registered cameras."""
        return {
            camera_id: self.check_health(camera_id, current_time)
            for camera_id in self._snapshots.keys()
        }

    def get_snapshot(self, camera_id: str) -> Optional[StreamHealthSnapshot]:
        """Get current health snapshot for a camera."""
        return self._snapshots.get(camera_id)
    
    def get_all_snapshots(self) -> Dict[str, StreamHealthSnapshot]:
        """Get all health snapshots."""
        return dict(self._snapshots)
    
    def get_last_check_result(self, camera_id: str) -> Optional[HealthCheckResult]:
        """Get last health check result."""
        return self._last_check_results.get(camera_id)
    
    def is_healthy(self, camera_id: str) -> bool:
        """Quick check if camera is healthy."""
        result = self._last_check_results.get(camera_id)
        if result:
            return result.state == StreamHealthState.LIVE
        return False
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all camera health."""
        return {
            "total_cameras": len(self._snapshots),
            "healthy": sum(1 for s in self._snapshots.values() if s.state == StreamHealthState.LIVE),
            "degraded": sum(1 for s in self._snapshots.values() if s.state == StreamHealthState.DEGRADED),
            "offline": sum(1 for s in self._snapshots.values() if s.state == StreamHealthState.OFFLINE),
            "reconnecting": sum(1 for s in self._snapshots.values() if s.state == StreamHealthState.RECONNECTING),
            "error": sum(1 for s in self._snapshots.values() if s.state == StreamHealthState.ERROR),
            "cameras": {cid: snap.to_dict() for cid, snap in self._snapshots.items()},
        }


def create_health_monitor(
    stale_threshold_seconds: float = 5.0,
    degraded_threshold_seconds: float = 2.0,
    frame_timeout_seconds: float = 10.0,
    max_consecutive_missing_frames: int = 30,
    event_callback: Optional[Callable[[HealthEvent], None]] = None,
    time_func: Optional[Callable[[], float]] = None,
) -> StreamHealthMonitor:
    """Factory function to create a health monitor."""
    return StreamHealthMonitor(
        stale_threshold_seconds=stale_threshold_seconds,
        degraded_threshold_seconds=degraded_threshold_seconds,
        frame_timeout_seconds=frame_timeout_seconds,
        max_consecutive_missing_frames=max_consecutive_missing_frames,
        event_callback=event_callback,
        time_func=time_func,
    )