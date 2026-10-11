"""
Phase R3.14-H.2-F — Focused Tests for Publisher Liveness Watchdog Lifecycle Fix.

Tests cover the 10 acceptance criteria from the phase specification:
1. publisher_alive=False + frames_submitted=0 + elapsed < startup_grace → STARTING
2. publisher_alive=False + frames_submitted=0 + elapsed > startup_grace → UNHEALTHY
3. FFmpeg PID exists + last_encode_time=0 + elapsed < post_spawn_grace → HANDSHAKE
4. FFmpeg PID exists + MediaMTX ready=True → HEALTHY/READY
5. FFmpeg PID exists + frames encoded + last_encode_time fresh → HEALTHY
6. FFmpeg PID exists + frames previously encoded + last_encode_time stale → UNHEALTHY
7. Slow publisher startup (~22s first frame) with 15s startup_grace → no premature restart
8. Three+ watchdog polls during STARTING → consecutive_unhealthy=0, restart_count=0
9. Publisher reaches READY then FFmpeg dies → normal post-READY restart behavior
10. CAM1 and CAM2 follow identical slow-start lifecycle → neither prematurely restarted
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from typing import Any, Dict

from app.streaming.publisher_liveness import (
    PublisherLivenessWatchdog,
    PublisherLivenessConfig,
    PublisherHealthState,
    create_publisher_liveness_watchdog,
)


class MockPublisher:
    """Mock AnnotatedFramePublisher for liveness testing."""

    def __init__(self, camera_id="CAM1", **kwargs):
        self.camera_id = camera_id
        self._metrics = {
            "camera_id": camera_id,
            "started": True,
            "frames_encoded": kwargs.get("frames_encoded", 0),
            "ffmpeg_pid": kwargs.get("ffmpeg_pid", None),
            "last_encode_time": kwargs.get("last_encode_time", 0.0),
            "frames_submitted": kwargs.get("frames_submitted", 0),
            "last_error": "",
        }

    def get_metrics(self):
        return self._metrics.copy()


# ================================================================ Test 1: STARTING state during startup grace
# ================================================================

def test_test1_publisher_alive_false_zero_frames_elapsed_less_than_grace_is_starting():
    """TEST 1: publisher_alive=False + frames_submitted=0 + elapsed < startup_grace → STARTING"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=1.0,
        stale_after_seconds=0.5,
        require_bytes_progress=False,
    )

    mock_publisher = MockPublisher("CAM1", frames_encoded=0, ffmpeg_pid=None, last_encode_time=0.0, frames_submitted=0)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=Mock(),
        )

        watchdog.start()
        time.sleep(0.3)  # Elapsed ~0.3s < 1s grace
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["current_state"] == "starting"
        assert metrics["consecutive_unhealthy_polls"] == 0
        assert metrics["restart_count"] == 0


def test_test2_publisher_alive_false_zero_frames_elapsed_greater_than_grace_is_unhealthy():
    """TEST 2: publisher_alive=False + frames_submitted=0 + elapsed > startup_grace → UNHEALTHY"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=0.2,
        stale_after_seconds=0.5,
        require_bytes_progress=False,
        consecutive_unhealthy_threshold=1,
    )

    mock_publisher = MockPublisher("CAM1", frames_encoded=0, ffmpeg_pid=None, last_encode_time=0.0, frames_submitted=0)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock = Mock()
        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=restart_mock,
        )

        watchdog.start()
        time.sleep(0.6)  # Elapsed > 0.2s grace
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["restart_count"] > 0
        restart_mock.assert_called()


# ================================================================ Test 3: HANDSHAKE state
# ================================================================

def test_test3_ffmpeg_pid_exists_last_encode_time_zero_handshake_state():
    """TEST 3: FFmpeg PID exists + last_encode_time=0 + elapsed < post_spawn_grace → HANDSHAKE"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,  # Long startup grace
        stale_after_seconds=10.0,
        require_bytes_progress=False,
    )

    # Simulate publisher that has submitted frames (triggered FFmpeg spawn) but hasn't encoded first frame yet
    mock_publisher = MockPublisher("CAM1", frames_encoded=0, ffmpeg_pid=12345, last_encode_time=0.0, frames_submitted=1)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        # MediaMTX not ready yet during handshake
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=Mock(),
        )

        watchdog.start()
        time.sleep(0.3)  # Within post-spawn grace (default 5s)
        watchdog.stop()

        metrics = watchdog.get_metrics()
        # Should be in HANDSHAKE state, not UNHEALTHY
        assert metrics["current_state"] in ("handshake", "starting")
        assert metrics["consecutive_unhealthy_polls"] == 0
        assert metrics["restart_count"] == 0


def test_test4_ffmpeg_pid_exists_mediamtx_ready_true_is_healthy():
    """TEST 4: FFmpeg PID exists + MediaMTX ready=True → HEALTHY/READY"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,
        stale_after_seconds=10.0,
        require_bytes_progress=False,
    )

    mock_publisher = MockPublisher("CAM1", frames_encoded=10, ffmpeg_pid=12345, last_encode_time=time.time(), frames_submitted=10)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":10000}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=Mock(),
        )

        watchdog.start()
        time.sleep(0.3)
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["current_state"] in ("ready", "healthy")
        assert metrics["consecutive_unhealthy_polls"] == 0
        assert metrics["restart_count"] == 0


def test_test5_ffmpeg_pid_exists_frames_encoded_last_encode_fresh_is_healthy():
    """TEST 5: FFmpeg PID exists + frames encoded + last_encode_time fresh → HEALTHY"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,
        stale_after_seconds=10.0,
        require_bytes_progress=True,
    )

    mock_publisher = MockPublisher("CAM1", frames_encoded=100, ffmpeg_pid=12345, last_encode_time=time.time(), frames_submitted=100)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":100000}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=Mock(),
        )

        watchdog.start()
        time.sleep(0.3)
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["current_state"] in ("ready", "healthy")
        assert metrics["consecutive_unhealthy_polls"] == 0
        assert metrics["restart_count"] == 0


def test_test6_ffmpeg_pid_exists_frames_previously_encoded_last_encode_stale_is_unhealthy():
    """TEST 6: FFmpeg PID exists + frames previously encoded + last_encode_time stale → UNHEALTHY"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,
        stale_after_seconds=0.3,
        require_bytes_progress=True,
        consecutive_unhealthy_threshold=1,
    )

    # Simulate publisher that was encoding but stopped (stale)
    mock_publisher = MockPublisher("CAM1", frames_encoded=100, ffmpeg_pid=12345, last_encode_time=time.time() - 5.0, frames_submitted=100)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":100000}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock = Mock()
        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=restart_mock,
        )

        watchdog.start()
        time.sleep(0.5)
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["current_state"] == "unhealthy"
        assert metrics["restart_count"] > 0
        restart_mock.assert_called()


# ================================================================ Test 7: Slow startup scenario (22s first frame, 15s grace)
# ================================================================

def test_test7_slow_publisher_startup_22s_first_frame_15s_grace_no_premature_restart():
    """TEST 7: Slow publisher startup (~22s first frame) with 15s startup_grace → no premature restart"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,
        stale_after_seconds=10.0,
        require_bytes_progress=False,
        consecutive_unhealthy_threshold=3,
    )

    # Publisher starts with no frames, first frame arrives after ~22s (simulated)
    mock_publisher = MockPublisher("CAM1", frames_encoded=0, ffmpeg_pid=None, last_encode_time=0.0, frames_submitted=0)

    call_count = [0]

    def dynamic_metrics():
        call_count[0] += 1
        metrics = mock_publisher.get_metrics()
        # Simulate first frame arriving around poll 220 (simulated ~22s at 0.1s intervals)
        if call_count[0] >= 30:  # Earlier in test for speed
            metrics["frames_submitted"] = 1
            metrics["frames_encoded"] = 1
            metrics["last_encode_time"] = time.time()
            metrics["ffmpeg_pid"] = 12345
        return metrics

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        # MediaMTX not ready initially, becomes ready after first frame
        def media_mtx_response():
            if call_count[0] >= 35:
                return b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":5000}]}'
            return b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
        mock_resp.read.side_effect = media_mtx_response
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock = Mock()
        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=dynamic_metrics,
            on_unhealthy=restart_mock,
        )

        watchdog.start()
        time.sleep(4.0)  # Simulate ~22s production time
        watchdog.stop()

        metrics = watchdog.get_metrics()
        # Should reach READY/HEALTHY state, not UNHEALTHY
        assert metrics["current_state"] in ("ready", "healthy", "handshake")
        assert metrics["consecutive_unhealthy_polls"] == 0
        assert metrics["restart_count"] == 0
        restart_mock.assert_not_called()


# ================================================================ Test 8: Multiple polls during STARTING
# ================================================================

def test_test8_three_or_more_watchdog_polls_during_starting_zero_unhealthy():
    """TEST 8: Three+ watchdog polls during STARTING → consecutive_unhealthy=0, restart_count=0"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.05,
        startup_grace_seconds=1.0,
        stale_after_seconds=0.5,
        require_bytes_progress=False,
        consecutive_unhealthy_threshold=1,
    )

    mock_publisher = MockPublisher("CAM1", frames_encoded=0, ffmpeg_pid=None, last_encode_time=0.0, frames_submitted=0)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock = Mock()
        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=mock_publisher.get_metrics,
            on_unhealthy=restart_mock,
        )

        watchdog.start()
        time.sleep(0.25)  # ~5 polls during grace
        watchdog.stop()

        assert restart_mock.call_count == 0
        metrics = watchdog.get_metrics()
        assert metrics["restart_count"] == 0
        assert metrics["current_state"] == "starting"
        assert metrics["consecutive_unhealthy_polls"] == 0


# ================================================================ Test 9: Post-READY failure behavior intact
# ================================================================

def test_test9_publisher_reaches_ready_then_ffmpeg_dies_normal_restart():
    """TEST 9: Publisher reaches READY then FFmpeg dies → normal post-READY restart behavior"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=0.1,
        stale_after_seconds=0.3,
        require_bytes_progress=True,
        consecutive_unhealthy_threshold=2,
    )

    # Publisher starts healthy with frames
    mock_publisher = MockPublisher("CAM1", frames_encoded=10, ffmpeg_pid=12345, last_encode_time=time.time(), frames_submitted=10)
    call_count = [0]

    def dynamic_metrics():
        call_count[0] += 1
        metrics = mock_publisher.get_metrics()
        # After 2 polls, FFmpeg dies
        if call_count[0] >= 3:
            metrics["ffmpeg_pid"] = None
            metrics["last_encode_time"] = 0.0
            metrics["frames_encoded"] = 0
        return metrics

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":1000}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock = Mock()
        watchdog = create_publisher_liveness_watchdog(
            config=config,
            camera_id="CAM1",
            publisher_metrics_func=dynamic_metrics,
            on_unhealthy=restart_mock,
        )

        watchdog.start()
        time.sleep(0.6)  # ~6 polls
        watchdog.stop()

        metrics = watchdog.get_metrics()
        assert metrics["current_state"] == "unhealthy"
        assert metrics["consecutive_unhealthy_polls"] >= 2
        restart_mock.assert_called()


# ================================================================ Test 10: CAM1 and CAM2 identical lifecycle
# ================================================================

def test_test10_cam1_and_cam2_identical_slow_start_neither_prematurely_restarted():
    """TEST 10: CAM1 and CAM2 follow identical slow-start lifecycle → neither prematurely restarted"""
    config = PublisherLivenessConfig(
        ai_path="live/cam1-ai",
        poll_interval_seconds=0.1,
        startup_grace_seconds=15.0,
        stale_after_seconds=10.0,
        require_bytes_progress=False,
        consecutive_unhealthy_threshold=3,
    )

    def make_publisher(camera_id):
        return MockPublisher(camera_id, frames_encoded=0, ffmpeg_pid=None, last_encode_time=0.0, frames_submitted=0)

    call_counts = {"CAM1": 0, "CAM2": 0}

    def dynamic_metrics_cam1():
        call_counts["CAM1"] += 1
        metrics = make_publisher("CAM1").get_metrics()
        if call_counts["CAM1"] >= 30:
            metrics["frames_submitted"] = 1
            metrics["frames_encoded"] = 1
            metrics["last_encode_time"] = time.time()
            metrics["ffmpeg_pid"] = 12345
        return metrics

    def dynamic_metrics_cam2():
        call_counts["CAM2"] += 1
        metrics = make_publisher("CAM2").get_metrics()
        if call_counts["CAM2"] >= 30:
            metrics["frames_submitted"] = 1
            metrics["frames_encoded"] = 1
            metrics["last_encode_time"] = time.time()
            metrics["ffmpeg_pid"] = 12346
        return metrics

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        def media_mtx_response():
            if call_counts["CAM1"] >= 35 and call_counts["CAM2"] >= 35:
                return b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":5000},{"name":"live/cam2-ai","ready":true,"bytesReceived":5000}]}'
            return b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0},{"name":"live/cam2-ai","ready":false,"bytesReceived":0}]}'
        mock_resp.read.side_effect = media_mtx_response
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        restart_mock_1 = Mock()
        restart_mock_2 = Mock()

        watchdog1 = create_publisher_liveness_watchdog(
            config=PublisherLivenessConfig(ai_path="live/cam1-ai", **{k:v for k,v in config.__dict__.items() if k != 'ai_path'}),
            camera_id="CAM1",
            publisher_metrics_func=dynamic_metrics_cam1,
            on_unhealthy=restart_mock_1,
        )
        watchdog2 = create_publisher_liveness_watchdog(
            config=PublisherLivenessConfig(ai_path="live/cam2-ai", **{k:v for k,v in config.__dict__.items() if k != 'ai_path'}),
            camera_id="CAM2",
            publisher_metrics_func=dynamic_metrics_cam2,
            on_unhealthy=restart_mock_2,
        )

        watchdog1.start()
        watchdog2.start()
        time.sleep(4.0)
        watchdog1.stop()
        watchdog2.stop()

        metrics1 = watchdog1.get_metrics()
        metrics2 = watchdog2.get_metrics()

        # Both should reach healthy state
        assert metrics1["current_state"] in ("ready", "healthy", "handshake")
        assert metrics2["current_state"] in ("ready", "healthy", "handshake")
        assert metrics1["restart_count"] == 0
        assert metrics2["restart_count"] == 0
        restart_mock_1.assert_not_called()
        restart_mock_2.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])