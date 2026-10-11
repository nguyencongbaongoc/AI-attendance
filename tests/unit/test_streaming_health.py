"""
Phase 33 — Unit Tests for Stream Health Monitor.

Tests cover:
- Health state machine
- Frame freshness monitoring
- Stale frame detection
- Frame timeout detection
- Reconnect handling
- Health event generation
- CAM1/CAM2 isolation
- Deterministic tests with injectable time
"""

import pytest
import time
from unittest.mock import Mock

from app.streaming.contracts import StreamHealthState
from app.streaming.health import (
    StreamHealthMonitor,
    StreamHealthSnapshot,
    HealthCheckResult,
    create_health_monitor,
)
from app.streaming.health_events import (
    HealthEvent,
    HealthEventType,
    HealthEventSeverity,
)


class TestStreamHealthMonitor:
    """Tests for StreamHealthMonitor."""

    def test_register_camera(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot is not None
        assert snapshot.camera_id == "CAM1"
        assert snapshot.state == StreamHealthState.OFFLINE

    def test_unregister_camera(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.unregister_camera("CAM1")
        
        assert monitor.get_snapshot("CAM1") is None

    def test_update_frame_received_first_frame(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, frame_size=1024)
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.state == StreamHealthState.LIVE
        assert snapshot.frames_received == 1
        assert snapshot.bytes_received == 1024
        assert snapshot.last_frame_timestamp == 1000.0

    def test_update_frame_received_multiple_frames(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        for i in range(10):
            monitor.update_frame_received("CAM1", frame_index=i, timestamp=1000.0 + i * 0.033, frame_size=1024)
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.frames_received == 10
        assert snapshot.state == StreamHealthState.LIVE

    def test_update_frame_received_missing_frames(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        monitor.update_frame_received("CAM1", frame_index=5, timestamp=1000.165)
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.frames_received == 2

    def test_update_frame_dropped(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        monitor.update_frame_dropped("CAM1")
        monitor.update_frame_dropped("CAM1")
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.frames_dropped == 2

    def test_update_error_live_to_degraded(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        
        monitor.update_error("CAM1", "Decoder error")
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.state == StreamHealthState.DEGRADED
        assert snapshot.total_errors == 1
        assert snapshot.last_error == "Decoder error"

    def test_update_error_degraded_to_error(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        monitor.update_error("CAM1", "First error")
        
        monitor.update_error("CAM1", "Second error")
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.state == StreamHealthState.ERROR

    def test_update_reconnect(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        
        monitor.update_reconnect("CAM1", attempt=1)
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.state == StreamHealthState.RECONNECTING
        assert snapshot.reconnect_count == 1

    def test_update_reconnect_success(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        monitor.update_reconnect("CAM1", attempt=1)
        
        monitor.update_reconnect_success("CAM1")
        
        snapshot = monitor.get_snapshot("CAM1")
        assert snapshot.state == StreamHealthState.LIVE

    def test_update_reconnect_failed(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        monitor.update_reconnect("CAM1", attempt=1)
class TestHealthCheck:
    """Tests for health check functionality."""

    def test_check_health_no_frames(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        
        result = monitor.check_health("CAM1", current_time=1000.0)
        
        assert result.state == StreamHealthState.OFFLINE
        assert "No frames received" in result.message

    def test_check_health_healthy(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        result = monitor.check_health("CAM1", current_time=1000.5)
        
        assert result.state == StreamHealthState.LIVE
        assert result.message == "Stream healthy"

    def test_check_health_degraded(self):
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        result = monitor.check_health("CAM1", current_time=1003.0)
        
        assert result.state == StreamHealthState.DEGRADED
        assert "Frame delay" in result.message

    def test_check_health_timeout(self):
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
            frame_timeout_seconds=10.0,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        result = monitor.check_health("CAM1", current_time=1015.0)
        
        assert result.state == StreamHealthState.ERROR
        assert "No frames for" in result.message

    def test_check_health_reconnecting_state(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        monitor.update_reconnect("CAM1", attempt=1)
        
        result = monitor.check_health("CAM1", current_time=1005.0)
        
        assert result.state == StreamHealthState.RECONNECTING

    def test_check_all_health(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        results = monitor.check_all_health(current_time=1000.5)
        
        assert "CAM1" in results
        assert "CAM2" in results
        assert results["CAM1"].state == StreamHealthState.LIVE
        assert results["CAM2"].state == StreamHealthState.OFFLINE

    def test_get_summary(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        
        summary = monitor.get_summary()
        
class TestHealthEventGeneration:
    """Tests for health event generation."""

    def test_frame_received_emits_state_change_event(self):
        events = []
        def callback(event):
            events.append(event)
        
        monitor = create_health_monitor(event_callback=callback)
        monitor.register_camera("CAM1")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        assert len(events) == 1
        assert events[0].event_type == HealthEventType.STATE_CHANGE
        assert events[0].previous_state == "offline"
        assert events[0].new_state == "live"

    def test_frame_received_emits_stream_validated_event(self):
        events = []
        def callback(event):
            events.append(event)
        
        monitor = create_health_monitor(event_callback=callback)
        monitor.register_camera("CAM1")
        
        monitor.update_frame_received(
            "CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0,
            resolution=(3840, 2160), fps=30.0, codec="h264"
        )
        
        assert len(events) == 2
        assert events[1].event_type == HealthEventType.STREAM_VALIDATED
        assert events[1].details["codec"] == "h264"
        assert events[1].details["width"] == 3840
        assert events[1].details["height"] == 2160
        assert events[1].details["fps"] == 30.0

    def test_stale_frame_emits_event(self):
        events = []
        def callback(event):
            events.append(event)
        
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
            event_callback=callback,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.check_health("CAM1", current_time=1008.0)
        
        stale_events = [e for e in events if e.event_type == HealthEventType.FRAME_STALE]
        assert len(stale_events) == 1
        assert stale_events[0].severity == HealthEventSeverity.WARNING

    def test_frame_timeout_emits_event(self):
        events = []
        def callback(event):
            events.append(event)
        
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
            frame_timeout_seconds=10.0,
            event_callback=callback,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.check_health("CAM1", current_time=1015.0)
        
        timeout_events = [e for e in events if e.event_type == HealthEventType.FRAME_TIMEOUT]
        assert len(timeout_events) == 1
        assert timeout_events[0].severity == HealthEventSeverity.ERROR

    def test_reconnect_emits_events(self):
        events = []
        def callback(event):
            events.append(event)
        
        monitor = create_health_monitor(event_callback=callback)
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.update_reconnect("CAM1", attempt=1)
        monitor.update_reconnect_success("CAM1")
        
        reconnect_events = [e for e in events if e.event_type in (
            HealthEventType.RECONNECT_ATTEMPT,
            HealthEventType.RECONNECT_SUCCESS,
        )]
        assert len(reconnect_events) == 2
        assert reconnect_events[0].event_type == HealthEventType.RECONNECT_ATTEMPT
        assert reconnect_events[1].event_type == HealthEventType.RECONNECT_SUCCESS
        assert reconnect_events[1].details["success"] is True


class TestCAM1CAM2Isolation:
    """Tests for CAM1/CAM2 isolation."""

    def test_cam1_failure_does_not_affect_cam2(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        monitor.update_frame_received("CAM2", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.update_error("CAM1", "CAM1 error")
        monitor.check_health("CAM1", current_time=1015.0)
        
        result_cam2 = monitor.check_health("CAM2", current_time=1000.5)
        assert result_cam2.state == StreamHealthState.LIVE
        
        result_cam1 = monitor.check_health("CAM1", current_time=1015.0)
        assert result_cam1.state == StreamHealthState.ERROR

    def test_cam2_failure_does_not_affect_cam1(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        monitor.update_frame_received("CAM2", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.update_error("CAM2", "CAM2 error")
        monitor.check_health("CAM2", current_time=1015.0)
        
        result_cam1 = monitor.check_health("CAM1", current_time=1000.5)
        assert result_cam1.state == StreamHealthState.LIVE
        
        result_cam2 = monitor.check_health("CAM2", current_time=1015.0)
        assert result_cam2.state == StreamHealthState.ERROR

    def test_independent_reconnect(self):
        monitor = create_health_monitor()
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        monitor.update_frame_received("CAM2", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.update_reconnect("CAM1", attempt=1)
        
        result_cam2 = monitor.check_health("CAM2", current_time=1000.5)
        assert result_cam2.state == StreamHealthState.LIVE
        
        result_cam1 = monitor.check_health("CAM1", current_time=1000.5)
        assert result_cam1.state == StreamHealthState.RECONNECTING

    def test_independent_frame_freshness(self):
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
        )
        monitor.register_camera("CAM1")
        monitor.register_camera("CAM2")
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        monitor.update_frame_received("CAM2", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        monitor.update_frame_received("CAM2", frame_index=1, timestamp=1000.033, current_time=1000.033)
        
        # Check at 1002.0: CAM1 has 2 seconds since last frame (DEGRADED), CAM2 has 1.967 seconds (LIVE)
        result_cam1 = monitor.check_health("CAM1", current_time=1002.0)
        result_cam2 = monitor.check_health("CAM2", current_time=1002.0)
        
        assert result_cam1.state == StreamHealthState.DEGRADED
        assert result_cam2.state == StreamHealthState.LIVE


class TestDeterministicTime:
    """Tests with injectable time for determinism."""

    def test_injectable_time_func(self):
        current_time = [1000.0]
        
        def time_func():
            return current_time[0]
        
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
            time_func=time_func,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        
        current_time[0] = 1003.0
        result = monitor.check_health("CAM1")
        
        assert result.state == StreamHealthState.DEGRADED
        
        current_time[0] = 1015.0
        result = monitor.check_health("CAM1")
        
        assert result.state == StreamHealthState.ERROR

    def test_no_wall_clock_in_deterministic_tests(self):
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        result = monitor.check_health("CAM1", current_time=1000.5)
        assert result.state == StreamHealthState.LIVE
        
        result = monitor.check_health("CAM1", current_time=1003.0)
        assert result.state == StreamHealthState.DEGRADED


class TestHealthCheckResult:
    """Tests for HealthCheckResult."""

    def test_healthy_result(self):
        result = HealthCheckResult.healthy("CAM1", frame_count=10, timestamp=1000.0)
        assert result.state == StreamHealthState.LIVE
        assert result.last_successful_frame == 10
        assert result.last_successful_time == 1000.0
        assert result.consecutive_failures == 0

    def test_degraded_result(self):
        result = HealthCheckResult.degraded("CAM1", "Frame delay", frame_count=10, timestamp=1000.0)
        assert result.state == StreamHealthState.DEGRADED
        assert result.message == "Frame delay"

    def test_offline_result(self):
        result = HealthCheckResult.offline("CAM1", "No stream")
        assert result.state == StreamHealthState.OFFLINE
        assert result.failure_reason == "No stream"

    def test_error_result(self):
        result = HealthCheckResult.error("CAM1", "Connection lost", frame_count=10)
        assert result.state == StreamHealthState.ERROR
        assert result.failure_reason == "Connection lost"
        assert result.last_successful_frame == 10

    def test_connecting_result(self):
        result = HealthCheckResult.connecting("CAM1")
        assert result.state == StreamHealthState.CONNECTING

    def test_reconnecting_result(self):
        result = HealthCheckResult.reconnecting("CAM1", attempt=2, max_attempts=5)
        assert result.state == StreamHealthState.RECONNECTING
        assert result.reconnect_count == 2

    def test_serialization(self):
        result = HealthCheckResult.healthy("CAM1", frame_count=10, timestamp=1000.0)
        data = result.to_dict()
        
        assert data["camera_id"] == "CAM1"
        assert data["state"] == "live"
        assert data["last_successful_frame"] == 10
        assert data["last_successful_time"] == 1000.0
        
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        monitor.update_frame_received("CAM2", frame_index=0, timestamp=1000.0)
        
        monitor.update_frame_received("CAM2", frame_index=1, timestamp=1000.033)
        
        result_cam1 = monitor.check_health("CAM1", current_time=1003.0)
        result_cam2 = monitor.check_health("CAM2", current_time=1003.0)
        
        assert result_cam1.state == StreamHealthState.DEGRADED
        assert result_cam2.state == StreamHealthState.LIVE


class TestDeterministicTime:
    """Tests with injectable time for determinism."""

    def test_injectable_time_func(self):
        current_time = [1000.0]
        
        def time_func():
            return current_time[0]
        
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
            time_func=time_func,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0)
        
        current_time[0] = 1003.0
        result = monitor.check_health("CAM1")
        
        assert result.state == StreamHealthState.DEGRADED
        
        current_time[0] = 1015.0
        result = monitor.check_health("CAM1")
        
        assert result.state == StreamHealthState.ERROR

    def test_no_wall_clock_in_deterministic_tests(self):
        monitor = create_health_monitor(
            stale_threshold_seconds=5.0,
            degraded_threshold_seconds=2.0,
        )
        monitor.register_camera("CAM1")
        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)
        
        result = monitor.check_health("CAM1", current_time=1000.5)
        assert result.state == StreamHealthState.LIVE
        
        result = monitor.check_health("CAM1", current_time=1003.0)
        assert result.state == StreamHealthState.DEGRADED


class TestHealthCheckResult:
    """Tests for HealthCheckResult."""

    def test_healthy_result(self):
        result = HealthCheckResult.healthy("CAM1", frame_count=10, timestamp=1000.0)
        assert result.state == StreamHealthState.LIVE
        assert result.last_successful_frame == 10
        assert result.last_successful_time == 1000.0
        assert result.consecutive_failures == 0

    def test_degraded_result(self):
        result = HealthCheckResult.degraded("CAM1", "Frame delay", frame_count=10, timestamp=1000.0)
        assert result.state == StreamHealthState.DEGRADED
        assert result.message == "Frame delay"

    def test_offline_result(self):
        result = HealthCheckResult.offline("CAM1", "No stream")
        assert result.state == StreamHealthState.OFFLINE
        assert result.failure_reason == "No stream"

    def test_error_result(self):
        result = HealthCheckResult.error("CAM1", "Connection lost", frame_count=10)
        assert result.state == StreamHealthState.ERROR
        assert result.failure_reason == "Connection lost"
        assert result.last_successful_frame == 10

    def test_connecting_result(self):
        result = HealthCheckResult.connecting("CAM1")
        assert result.state == StreamHealthState.CONNECTING

    def test_reconnecting_result(self):
        result = HealthCheckResult.reconnecting("CAM1", attempt=2, max_attempts=5)
        assert result.state == StreamHealthState.RECONNECTING
        assert result.reconnect_count == 2

    def test_serialization(self):
        result = HealthCheckResult.healthy("CAM1", frame_count=10, timestamp=1000.0)
        data = result.to_dict()
        
        assert data["camera_id"] == "CAM1"
        assert data["state"] == "live"
        assert data["last_successful_frame"] == 10
        assert data["last_successful_time"] == 1000.0