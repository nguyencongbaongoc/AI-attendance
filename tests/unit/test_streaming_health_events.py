"""
Phase 33 — Unit Tests for Stream Health Events.

Tests cover:
- HealthEvent serialization/deserialization
- HealthEventBatch serialization/deserialization
- Event factory functions
- Deterministic IDs
"""

import pytest

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


class TestHealthEventType:
    """Tests for HealthEventType enum."""

    def test_all_types_exist(self):
        types = [
            HealthEventType.STATE_CHANGE,
            HealthEventType.FRAME_RECEIVED,
            HealthEventType.FRAME_STALE,
            HealthEventType.FRAME_TIMEOUT,
            HealthEventType.RECONNECT_STARTED,
            HealthEventType.RECONNECT_ATTEMPT,
            HealthEventType.RECONNECT_SUCCESS,
            HealthEventType.RECONNECT_FAILED,
            HealthEventType.RECONNECT_EXHAUSTED,
            HealthEventType.STREAM_VALIDATED,
            HealthEventType.STREAM_INVALID,
            HealthEventType.MEDIAMTX_HEALTH,
            HealthEventType.FFMPEG_HEALTH,
        ]
        assert len(types) == 13

    def test_type_values(self):
        assert HealthEventType.STATE_CHANGE.value == "state_change"
        assert HealthEventType.FRAME_STALE.value == "frame_stale"
        assert HealthEventType.FRAME_TIMEOUT.value == "frame_timeout"
        assert HealthEventType.RECONNECT_ATTEMPT.value == "reconnect_attempt"
        assert HealthEventType.RECONNECT_SUCCESS.value == "reconnect_success"
class TestHealthEvent:
    """Tests for HealthEvent dataclass."""

    def test_create_minimal_event(self):
        event = HealthEvent(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.STATE_CHANGE,
            severity=HealthEventSeverity.INFO,
        )
        assert event.event_id == "evt-001"
        assert event.camera_id == "CAM1"
        assert event.event_type == HealthEventType.STATE_CHANGE
        assert event.severity == HealthEventSeverity.INFO
        assert event.previous_state is None
        assert event.new_state is None
        assert event.reason == ""
        assert event.reconnect_attempt == 0
        assert event.max_reconnect_attempts == 0
        assert event.last_frame_timestamp is None
        assert event.last_frame_index is None
        assert event.source_identifier == ""
        assert event.details == {}
        assert event.schema_version == 1

    def test_create_full_event(self):
        event = HealthEvent(
            event_id="evt-002",
            camera_id="CAM2",
            event_type=HealthEventType.FRAME_STALE,
            severity=HealthEventSeverity.WARNING,
            previous_state="live",
            new_state="degraded",
            reason="No frames for 5s",
            reconnect_attempt=1,
            max_reconnect_attempts=5,
            last_frame_timestamp=1234567890.0,
            last_frame_index=150,
            source_identifier="rtsp",
            details={"stale_duration_seconds": 5.0},
            schema_version=1,
        )
        assert event.previous_state == "live"
        assert event.new_state == "degraded"
        assert event.reason == "No frames for 5s"
        assert event.reconnect_attempt == 1
        assert event.max_reconnect_attempts == 5
        assert event.last_frame_timestamp == 1234567890.0
        assert event.last_frame_index == 150
        assert event.source_identifier == "rtsp"
        assert event.details == {"stale_duration_seconds": 5.0}

    def test_serialization_roundtrip(self):
        event = HealthEvent(
            event_id="evt-003",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_ATTEMPT,
            severity=HealthEventSeverity.INFO,
            previous_state="offline",
            new_state="reconnecting",
            reason="Attempting reconnect",
            reconnect_attempt=2,
            max_reconnect_attempts=5,
            last_frame_timestamp=1234567890.0,
            last_frame_index=100,
            source_identifier="rtsp",
            details={"attempt": 2},
        )
        data = event.to_dict()
        restored = HealthEvent.from_dict(data)
        assert restored.event_id == event.event_id
        assert restored.camera_id == event.camera_id
        assert restored.event_type == event.event_type
        assert restored.severity == event.severity
        assert restored.previous_state == event.previous_state
        assert restored.new_state == event.new_state
        assert restored.reason == event.reason
        assert restored.reconnect_attempt == event.reconnect_attempt
        assert restored.max_reconnect_attempts == event.max_reconnect_attempts
        assert restored.last_frame_timestamp == event.last_frame_timestamp
        assert restored.last_frame_index == event.last_frame_index
        assert restored.source_identifier == event.source_identifier
        assert restored.details == event.details
        assert restored.schema_version == event.schema_version


class TestHealthEventBatch:
    """Tests for HealthEventBatch."""

    def test_create_batch(self):
        events = (
            HealthEvent(
                event_id="evt-001",
                camera_id="CAM1",
                event_type=HealthEventType.STATE_CHANGE,
                severity=HealthEventSeverity.INFO,
            ),
            HealthEvent(
                event_id="evt-002",
                camera_id="CAM1",
                event_type=HealthEventType.FRAME_RECEIVED,
                severity=HealthEventSeverity.INFO,
            ),
        )
        batch = HealthEventBatch(events=events, camera_id="CAM1")
        assert len(batch.events) == 2
        assert batch.camera_id == "CAM1"

    def test_batch_serialization_roundtrip(self):
        events = (
            HealthEvent(
                event_id="evt-001",
                camera_id="CAM1",
                event_type=HealthEventType.STATE_CHANGE,
                severity=HealthEventSeverity.INFO,
            ),
        )
        batch = HealthEventBatch(events=events, camera_id="CAM1")
        data = batch.to_dict()
        restored = HealthEventBatch.from_dict(data)
        assert len(restored.events) == 1
        assert restored.camera_id == "CAM1"
        assert restored.events[0].event_id == "evt-001"


class TestEventFactories:
    """Tests for event factory functions."""

    def test_create_state_change_event(self):
        event = create_state_change_event(
            event_id="evt-001",
            camera_id="CAM1",
            previous_state="offline",
            new_state="live",
            reason="Stream started",
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.STATE_CHANGE
        assert event.previous_state == "offline"
        assert event.new_state == "live"
        assert event.reason == "Stream started"
        assert event.source_identifier == "rtsp"
        assert event.severity == HealthEventSeverity.INFO

    def test_create_state_change_event_error_severity(self):
        event = create_state_change_event(
            event_id="evt-001",
            camera_id="CAM1",
            previous_state="live",
            new_state="offline",
            reason="Stream stopped",
        )
        assert event.severity == HealthEventSeverity.ERROR

    def test_create_state_change_event_warning_severity(self):
        event = create_state_change_event(
            event_id="evt-001",
            camera_id="CAM1",
            previous_state="live",
            new_state="degraded",
            reason="Frame delay",
        )
        assert event.severity == HealthEventSeverity.WARNING

    def test_create_frame_stale_event(self):
        event = create_frame_stale_event(
            event_id="evt-001",
            camera_id="CAM1",
            last_frame_timestamp=1234567890.0,
            last_frame_index=150,
            stale_duration_seconds=5.5,
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.FRAME_STALE
        assert event.severity == HealthEventSeverity.WARNING
        assert event.last_frame_timestamp == 1234567890.0
        assert event.last_frame_index == 150
        assert "5.5" in event.reason
        assert event.details["stale_duration_seconds"] == 5.5

    def test_create_frame_timeout_event(self):
        event = create_frame_timeout_event(
            event_id="evt-001",
            camera_id="CAM1",
            last_frame_timestamp=1234567890.0,
            last_frame_index=150,
            timeout_seconds=10.0,
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.FRAME_TIMEOUT
        assert event.severity == HealthEventSeverity.ERROR
        assert event.last_frame_timestamp == 1234567890.0
        assert event.last_frame_index == 150
        assert "10.0" in event.reason
        assert event.details["timeout_seconds"] == 10.0

    def test_create_reconnect_event_attempt(self):
        event = create_reconnect_event(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_ATTEMPT,
            attempt=2,
            max_attempts=5,
            reason="Reconnect attempt 2",
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.RECONNECT_ATTEMPT
        assert event.reconnect_attempt == 2
        assert event.max_reconnect_attempts == 5
        assert event.severity == HealthEventSeverity.INFO

    def test_create_reconnect_event_failed(self):
        event = create_reconnect_event(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_FAILED,
            attempt=3,
            max_attempts=5,
            reason="Connection refused",
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.RECONNECT_FAILED
        assert event.severity == HealthEventSeverity.WARNING

    def test_create_reconnect_event_exhausted(self):
        event = create_reconnect_event(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_EXHAUSTED,
            attempt=5,
            max_attempts=5,
            reason="Max retries reached",
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.RECONNECT_EXHAUSTED
        assert event.severity == HealthEventSeverity.ERROR

    def test_create_stream_validated_event(self):
        event = create_stream_validated_event(
            event_id="evt-001",
            camera_id="CAM1",
            codec="h264",
            width=3840,
            height=2160,
            fps=30.0,
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.STREAM_VALIDATED
        assert event.severity == HealthEventSeverity.INFO
        assert event.details["codec"] == "h264"
        assert event.details["width"] == 3840
        assert event.details["height"] == 2160
        assert event.details["fps"] == 30.0

    def test_create_mediamtx_health_event(self):
        event = create_mediamtx_health_event(
            event_id="evt-001",
            camera_id="CAM1",
            mediamtx_status="healthy",
        )
        assert event.event_type == HealthEventType.MEDIAMTX_HEALTH
        assert event.severity == HealthEventSeverity.INFO
        assert event.source_identifier == "mediamtx"

    def test_create_mediamtx_health_event_unhealthy(self):
        event = create_mediamtx_health_event(
            event_id="evt-001",
            camera_id="CAM1",
            mediamtx_status="unhealthy",
        )
        assert event.severity == HealthEventSeverity.ERROR

    def test_create_ffmpeg_health_event(self):
        event = create_ffmpeg_health_event(
            event_id="evt-001",
            camera_id="CAM1",
            ffmpeg_status="running",
            exit_code=None,
            stderr="",
            source_identifier="ffmpeg",
        )
        assert event.event_type == HealthEventType.FFMPEG_HEALTH
        assert event.severity == HealthEventSeverity.INFO
        assert event.source_identifier == "ffmpeg"

    def test_create_ffmpeg_health_event_crashed(self):
        event = create_ffmpeg_health_event(
            event_id="evt-001",
            camera_id="CAM1",
            ffmpeg_status="crashed",
            exit_code=1,
            stderr="Error: connection lost",
            source_identifier="ffmpeg",
        )
        assert event.severity == HealthEventSeverity.ERROR
        assert event.details["exit_code"] == 1
        assert "connection lost" in event.details["stderr"]


class TestDeterministicIDs:
    """Tests that events use deterministic IDs."""

    def test_event_ids_are_deterministic(self):
        """Events should use provided deterministic IDs, not random UUIDs."""
        event1 = create_state_change_event(
            event_id="CAM1-001",
            camera_id="CAM1",
            previous_state="offline",
            new_state="live",
        )
        event2 = create_state_change_event(
            event_id="CAM1-002",
            camera_id="CAM1",
            previous_state="live",
            new_state="degraded",
        )
        assert event1.event_id == "CAM1-001"
        assert event2.event_id == "CAM1-002"
        assert event1.event_id != event2.event_id
        event = create_reconnect_event(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_EXHAUSTED,
            attempt=5,
            max_attempts=5,
            reason="Max retries reached",
            source_identifier="rtsp",
        )
        assert event.event_type == HealthEventType.RECONNECT_EXHAUSTED
        assert event.severity == HealthEventSeverity.ERROR

    def test_create_reconnect_event_success(self):
        event = create_reconnect_event(
            event_id="evt-001",
            camera_id="CAM1",
            event_type=HealthEventType.RECONNECT_SUCCESS,
            attempt=2,
            max_attempts=5,
            reason="Reconnected",
            source_identifier="rtsp",
            success=True,
        )
        assert event.event_type == HealthEventType.RECONNECT_SUCCESS
        assert event.severity == HealthEventSeverity.INFO
        assert event.details["success"] is True
        events = (
            HealthEvent(
                event_id="evt-001",
                camera_id="CAM1",
                event_type=HealthEventType.STATE_CHANGE,
                severity=HealthEventSeverity.INFO,
            ),
            HealthEvent(
                event_id="evt-002",
                camera_id="CAM1",
                event_type=HealthEventType.FRAME_RECEIVED,
                severity=HealthEventSeverity.INFO,
            ),
        )
        batch = HealthEventBatch(events=events, camera_id="CAM1")
        assert len(batch.events) == 2
        assert batch.camera_id == "CAM1"

    def test_batch_serialization_roundtrip(self):
        events = (
            HealthEvent(
                event_id="evt-001",
                camera_id="CAM1",
                event_type=HealthEventType.STATE_CHANGE,
                severity=HealthEventSeverity.INFO,
            ),
        )
        batch = HealthEventBatch(events=events, camera_id="CAM1")
        data = batch.to_dict()
        restored = HealthEventBatch.from_dict(data)
        assert len(restored.events) == 1
        assert restored.camera_id == "CAM1"
        assert restored.events[0].event_id == "evt-001"
        assert HealthEventType.RECONNECT_FAILED.value == "reconnect_failed"
        assert HealthEventType.RECONNECT_EXHAUSTED.value == "reconnect_exhausted"
        assert HealthEventType.STREAM_VALIDATED.value == "stream_validated"
        assert HealthEventType.MEDIAMTX_HEALTH.value == "mediamtx_health"
        assert HealthEventType.FFMPEG_HEALTH.value == "ffmpeg_health"


class TestHealthEventSeverity:
    """Tests for HealthEventSeverity enum."""

    def test_all_severities_exist(self):
        severities = [
            HealthEventSeverity.INFO,
            HealthEventSeverity.WARNING,
            HealthEventSeverity.ERROR,
            HealthEventSeverity.CRITICAL,
        ]
        assert len(severities) == 4

    def test_severity_values(self):
        assert HealthEventSeverity.INFO.value == "info"
        assert HealthEventSeverity.WARNING.value == "warning"
        assert HealthEventSeverity.ERROR.value == "error"
        assert HealthEventSeverity.CRITICAL.value == "critical"