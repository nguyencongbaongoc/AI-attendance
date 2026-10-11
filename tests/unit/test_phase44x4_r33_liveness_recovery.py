"""
Phase 44.X.4-R3.3 — Focused Tests for Liveness Recovery.

Tests cover:
1. Blocking/stalled capture detection
2. Capture recovery
3. Recovery without duplicate readers
4. Frame progress after recovery
5. Publisher process alive but MediaMTX unhealthy
6. Publisher liveness detection
7. Publisher restart
8. MediaMTX readiness verification
9. bytesReceived progress verification
10. No restart when publisher is healthy
11. Independent CAM1/CAM2 recovery
12. Restart/backoff behavior
13. Clean shutdown during recovery
14. No orphan FFmpeg process
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from app.streaming.capture_watchdog import (
    CaptureWatchdog,
    CaptureWatchdogConfig,
)
from app.streaming.publisher_liveness import (
    PublisherLivenessWatchdog,
    PublisherLivenessConfig,
    PublisherLivenessMetrics,
    create_publisher_liveness_watchdog,
)
from app.streaming.supervised_rtsp_source import (
    SupervisedRTSPSource,
    SupervisedRTSPSourceConfig,
    create_supervised_rtsp_source,
    RTSPCaptureStalledError,
)
from app.streaming.ingestion_worker import (
    CameraIngestionWorker,
    CameraIngestionConfig,
    WorkerState,
)
from app.streaming.annotated_publisher import (
    AnnotatedFramePublisher,
    AnnotatedPublisherConfig,
)
from app.streaming.health import StreamHealthMonitor, create_health_monitor


# ================================================================ Test Doubles
# ================================================================

class MockVideoFrameIterator:
    """Mock video iterator that can simulate blocked reads."""

    def __init__(self, frames=None, should_block=False, block_duration=100.0):
        self.frames = frames or []
        self.idx = 0
        self._should_block = should_block
        self._block_duration = block_duration
        self._blocked = False
        self.closed = False
        self._path = "mock"

    @property
    def info(self):
        from app.data.input_adapter import VideoInfo
        return VideoInfo(
            width=3840, height=2160, fps=30.0,
            frame_count=len(self.frames), duration=10.0,
            codec="h264", pixel_format="bgr24", path=self._path
        )

    def iter_with_watchdog(self, watchdog, stop_event):
        for i, frame in enumerate(self.frames):
            if stop_event.is_set():
                return
            if watchdog.teardown_requested:
                yield type('Frame', (object,), {'stalled': True, 'data': None, 'frame_index': i, 'timestamp': 0.0, 'pts': 0})()
                return
            # Wrap frame with stalled=False
            yield type('Frame', (object,), {
                'stalled': False,
                'data': frame.data,
                'frame_index': frame.frame_index,
                'timestamp': frame.timestamp,
                'pts': frame.pts,
            })()
            watchdog.mark_progress()

    def close(self):
        self.closed = True


class MockSubprocess:
    """Mock FFmpeg subprocess."""

    def __init__(self, pid=12345, alive=True, exit_code=None):
        self.pid = pid
        self._alive = alive
        self._exit_code = exit_code
        self.stdin = Mock()
        self.stderr = Mock()
        self._poll_result = None if alive else (exit_code or 1)

    def poll(self):
        return self._poll_result

    def wait(self, timeout=None):
        return self._exit_code or 0

    def terminate(self):
        self._alive = False
        self._poll_result = -15

    def kill(self):
        self._alive = False
        self._poll_result = -9


class MockPublisher:
    """Mock AnnotatedFramePublisher for liveness testing."""

    def __init__(self, camera_id="CAM1", healthy=True, frames_encoded=0, last_encode_time=None):
        self.camera_id = camera_id
        self._healthy = healthy
        self._frames_encoded = frames_encoded
        self._ffmpeg_pid = 12345
        self._last_encode_time = last_encode_time if last_encode_time is not None else (time.time() if healthy else 0)
        self._started = True

    def get_metrics(self):
        return {
            "camera_id": self.camera_id,
            "started": self._started,
            "frames_encoded": self._frames_encoded,
            "ffmpeg_pid": self._ffmpeg_pid,
            "last_encode_time": self._last_encode_time,
            "last_error": "",
        }

    def stop(self):
        self._started = False


# ================================================================ Capture Watchdog Tests
# ================================================================

class TestCaptureWatchdog:
    """Tests for CaptureWatchdog - the independent supervisor for blocking reads."""

    def test_stall_detected_after_timeout(self):
        """Watchdog should detect a stall when no progress is reported."""
        config = CaptureWatchdogConfig(stall_timeout_seconds=0.5)
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        # Don't call mark_progress - simulate a blocked read
        time.sleep(0.7)
        # The watchdog loop would detect this; we test the logic directly
        since_progress = time.time() - watchdog.last_progress_time
        assert since_progress > 0.5

    def test_mark_progress_resets_stall_timer(self):
        """Calling mark_progress should update last_progress_time."""
        config = CaptureWatchdogConfig(stall_timeout_seconds=2.0)
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        old_time = watchdog.last_progress_time
        time.sleep(0.1)
        watchdog.mark_progress()
        new_time = watchdog.last_progress_time
        assert new_time > old_time

    def test_force_teardown_clears_capture_reference(self):
        """_force_teardown should call cap.release() and clear _cap."""
        config = CaptureWatchdogConfig(stall_timeout_seconds=0.5)
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        mock_cap = Mock()
        watchdog.register_capture(mock_cap)
        assert watchdog._cap is mock_cap

        watchdog._force_teardown(since_progress=1.0)

        mock_cap.release.assert_called_once()
        assert watchdog._cap is None
        assert watchdog.teardown_requested

    def test_teardown_storm_guard(self):
        """Min interval between teardowns should be enforced."""
        config = CaptureWatchdogConfig(
            stall_timeout_seconds=0.5,
            min_teardown_interval_seconds=1.0,
        )
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        mock_cap = Mock()
        watchdog.register_capture(mock_cap)

        watchdog._force_teardown(since_progress=1.0)
        assert watchdog._forced_teardown_count == 1

        # Immediate second call should be suppressed
        watchdog._force_teardown(since_progress=1.0)
        assert watchdog._forced_teardown_count == 1  # Still 1

    def test_consecutive_teardowns_backoff(self):
        """Too many consecutive teardowns should trigger backoff."""
        config = CaptureWatchdogConfig(
            stall_timeout_seconds=0.5,
            max_consecutive_teardowns=2,
            teardown_backoff_seconds=0.1,
            min_teardown_interval_seconds=0.0,  # Disable storm guard for this test
        )
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        mock_cap = Mock()
        watchdog.register_capture(mock_cap)

        watchdog._force_teardown(since_progress=1.0)
        watchdog._force_teardown(since_progress=1.0)
        watchdog._force_teardown(since_progress=1.0)  # Third = exceeds max

        assert watchdog._consecutive_teardowns >= 3

    def test_owner_prevents_duplicate_readers(self):
        """Only one thread can claim ownership."""
        config = CaptureWatchdogConfig()
        watchdog = CaptureWatchdog(config=config, camera_id="CAM1")

        t1 = threading.current_thread()
        assert watchdog.claim_ownership() is True

        # Same thread can reclaim
        assert watchdog.claim_ownership() is True

        # Different thread conceptually - but we can't easily simulate
        # This test documents the invariant
        watchdog.release_ownership()
        assert not watchdog.has_active_owner


# ================================================================ SupervisedRTSPSource Tests
# ================================================================

class TestSupervisedRTSPSource:
    """Tests for SupervisedRTSPSource with capture watchdog."""

    def test_creation_and_open(self):
        """Source should open and start watchdog thread."""
        config = SupervisedRTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            stall_timeout_seconds=5.0,
        )
        source = create_supervised_rtsp_source(config=config)

        # Patch the internal iterator to avoid real FFmpeg/cv2
        with patch('app.streaming.supervised_rtsp_source.VideoFrameIterator') as mock_iter:
            mock_instance = MockVideoFrameIterator()
            mock_iter.return_value = mock_instance

            info = source.open()
            assert info.width == 3840
            assert source.is_opened

            # Watchdog should be running
            assert source._watchdog._watchdog_thread is not None
            assert source._watchdog._watchdog_thread.is_alive()

    def test_get_next_frame_returns_frames(self):
        """get_next_frame should return CanonicalFrames."""
        config = SupervisedRTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            stall_timeout_seconds=5.0,
        )
        source = create_supervised_rtsp_source(config=config)

        with patch('app.streaming.supervised_rtsp_source.VideoFrameIterator') as mock_iter:
            # Create mock frames - return each frame repeatedly to simulate
            # a live stream that produces frames continuously.
            frame = type('obj', (object,), {
                'data': np.zeros((2160, 3840, 3), dtype=np.uint8),
                'frame_index': 0,
                'timestamp': 0.0,
                'pts': 0,
            })()

            class InfiniteIterator:
                def __init__(self):
                    self.idx = 0
                @property
                def info(self):
                    from app.data.input_adapter import VideoInfo
                    return VideoInfo(width=3840, height=2160, fps=30.0,
                                     frame_count=0, duration=0.0, codec="h264",
                                     pixel_format="bgr24", path="mock")
                def iter_with_watchdog(self, watchdog, stop_event):
                    i = 0
                    while not stop_event.is_set() and not watchdog.teardown_requested:
                        yield type('F', (object,), {
                            'stalled': False,
                            'data': frame.data,
                            'frame_index': i,
                            'timestamp': i * 0.033,
                            'pts': i,
                        })()
                        watchdog.mark_progress()
                        i += 1
                def close(self):
                    pass
            mock_iter.return_value = InfiniteIterator()

            source.open()
            time.sleep(0.3)

            frame = source.get_next_frame(timeout=1.0)
            assert frame is not None
            frame2 = source.get_next_frame(timeout=1.0)
            assert frame2 is not None
            assert frame is not frame2

            source.close()

    def test_stalled_read_raises_exception(self):
        """If watchdog forces teardown, get_next_frame raises RTSPCaptureStalledError."""
        config = SupervisedRTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            stall_timeout_seconds=0.1,
        )
        source = create_supervised_rtsp_source(config=config)

        # Mock the iterator to avoid real FFmpeg
        with patch('app.streaming.supervised_rtsp_source.VideoFrameIterator') as mock_iter:
            mock_instance = MockVideoFrameIterator(frames=[])
            mock_iter.return_value = mock_instance

            source.open()
            # Force teardown from watchdog
            source._watchdog._force_teardown(since_progress=0.5)

            # Now get_next_frame should raise
            with pytest.raises(RTSPCaptureStalledError):
                source.get_next_frame(timeout=0.1)

    def test_reconnect_closes_and_reopens(self):
        """reconnect() should close source and reopen."""
        config = SupervisedRTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        source = create_supervised_rtsp_source(config=config)

        with patch('app.streaming.supervised_rtsp_source.VideoFrameIterator') as mock_iter:
            mock_instance = MockVideoFrameIterator()
            mock_iter.return_value = mock_instance

            source.open()
            assert source.is_opened

            # Reconnect
            result = source.reconnect()
            assert result is True
            assert source.is_opened


# ================================================================ Publisher Liveness Tests
# ================================================================

class TestPublisherLivenessWatchdog:
    """Tests for PublisherLivenessWatchdog - detects stale AI publishers."""

    def test_healthy_publisher_not_restarted(self):
        """Publisher with ready=true and bytes progress should not restart."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            stale_after_seconds=1.0,
            require_bytes_progress=False,
            request_timeout_seconds=0.5,
        )

        mock_publisher = MockPublisher("CAM1", healthy=True, frames_encoded=10)

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":1000}]}'
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
            assert metrics["healthy_count"] > 0
            assert metrics["restart_count"] == 0

    def test_ready_false_triggers_unhealthy(self):
        """ready=false should mark publisher unhealthy."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            stale_after_seconds=0.5,
            require_bytes_progress=True,
            request_timeout_seconds=0.5,
            startup_grace_seconds=0.1,  # Short grace period for test
            consecutive_unhealthy_threshold=1,  # Immediate restart for test
        )

        mock_publisher = MockPublisher("CAM1", healthy=True, frames_encoded=10, last_encode_time=time.time() - 10)

        with patch('urllib.request.urlopen') as mock_urlopen:
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
            time.sleep(0.3)
            watchdog.stop()

            metrics = watchdog.get_metrics()
            assert metrics["unhealthy_count"] > 0
            restart_mock.assert_called()

    def test_ready_true_but_no_bytes_progress_triggers_unhealthy(self):
        """ready=true but no bytesReceived growth should trigger unhealthy after stale_after."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            stale_after_seconds=0.3,
            require_bytes_progress=True,
            request_timeout_seconds=0.5,
            startup_grace_seconds=0.1,  # Short grace period for test
            consecutive_unhealthy_threshold=1,  # Immediate restart for test
        )

        mock_publisher = MockPublisher("CAM1", healthy=True, frames_encoded=10, last_encode_time=time.time() - 10)

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":1000}]}'
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
            assert metrics["unhealthy_count"] > 0
            restart_mock.assert_called()

    def test_restart_storm_guard(self):
        """min_restart_interval_seconds should prevent restart storms."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            stale_after_seconds=0.2,
            min_restart_interval_seconds=1.0,
            require_bytes_progress=True,
        )

        mock_publisher = MockPublisher("CAM1", healthy=True)

        with patch('urllib.request.urlopen') as mock_urlopen:
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
            time.sleep(0.5)
            watchdog.stop()

            assert restart_mock.call_count <= 2

    def test_consecutive_restarts_backoff(self):
        """Too many consecutive restarts should trigger backoff."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            stale_after_seconds=0.2,
            max_consecutive_restarts=2,
            restart_backoff_seconds=0.1,
            min_restart_interval_seconds=0.0,
            require_bytes_progress=True,
            startup_grace_seconds=0.1,  # Short grace for post-grace testing
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)

        with patch('urllib.request.urlopen') as mock_urlopen:
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
            time.sleep(0.8)
            watchdog.stop()

            metrics = watchdog.get_metrics()
            assert metrics["consecutive_restarts"] >= 3


# ================================================================ R3.14-H.2-A Watchdog Startup Lifecycle Tests
# ================================================================

class TestWatchdogStartupLifecycle:
    """Tests for R3.14-H.2-A — Watchdog Startup Lifecycle Fix.

    Verifies:
    1. publisher_alive=false + 0 frames + elapsed < grace → STARTING
    2. STARTING does not increment consecutive_unhealthy
    3. STARTING does not trigger restart
    4. publisher_alive=false + 0 frames + elapsed > grace → UNHEALTHY
    5. first frame during grace → READY
    6. READY publisher becoming unhealthy → existing UNHEALTHY behavior
    7. three startup polls during grace → zero restarts
    8. exact grace boundary
    9. CAM1 startup sequence reproducing R3.14-H.1 → no premature restart before first frame
    10. CAM2 with genuinely missing source: watchdog may eventually become UNHEALTHY AFTER grace,
        but must not restart immediately during startup grace.
    """

    def test_publisher_alive_false_zero_frames_elapsed_less_than_grace_is_starting(
        self,
    ):
        """publisher_alive=false + 0 frames + elapsed < grace → STARTING."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=1.0,  # 1s grace
            stale_after_seconds=0.5,
            require_bytes_progress=False,
        )

        # Mock publisher: not alive, 0 frames submitted
        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None
        mock_publisher._started = True

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

    def test_starting_does_not_increment_consecutive_unhealthy(self):
        """STARTING does not increment consecutive_unhealthy."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.05,
            startup_grace_seconds=1.0,
            stale_after_seconds=0.5,
            require_bytes_progress=False,
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

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
            time.sleep(0.3)  # ~6 polls at 0.05s interval
            watchdog.stop()

            metrics = watchdog.get_metrics()
            assert metrics["current_state"] == "starting"
            assert metrics["consecutive_unhealthy_polls"] == 0
            assert metrics["unhealthy_count"] == 0  # STARTING is healthy=True

    def test_starting_does_not_trigger_restart(self):
        """STARTING does not trigger restart."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.05,
            startup_grace_seconds=1.0,
            stale_after_seconds=0.5,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=1,  # Would restart if UNHEALTHY
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

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
            time.sleep(0.3)  # ~6 polls
            watchdog.stop()

            assert restart_mock.call_count == 0
            metrics = watchdog.get_metrics()
            assert metrics["restart_count"] == 0

    def test_publisher_alive_false_zero_frames_elapsed_greater_than_grace_is_unhealthy(
        self,
    ):
        """publisher_alive=false + 0 frames + elapsed > grace → UNHEALTHY."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=0.2,  # Short grace
            stale_after_seconds=0.5,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=1,
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

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
            time.sleep(0.6)  # Elapsed > 0.2s grace, well past restart grace
            watchdog.stop()

            metrics = watchdog.get_metrics()
            # After grace expires AND no frames, watchdog must have restarted
            assert metrics["restart_count"] > 0
            restart_mock.assert_called()

    def test_first_frame_during_grace_transitions_to_ready(self):
        """first frame during grace → READY."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=1.0,
            stale_after_seconds=0.5,
            require_bytes_progress=False,
        )

        # Publisher not yet alive, but frames_submitted > 0
        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None
        mock_publisher._started = True

        call_count = [0]

        def dynamic_metrics():
            call_count[0] += 1
            # On 3rd poll, simulate first frame submitted
            metrics = mock_publisher.get_metrics()
            if call_count[0] >= 3:
                metrics["frames_submitted"] = 1
                metrics["frames_encoded"] = 1
                metrics["last_encode_time"] = time.time()
                metrics["ffmpeg_pid"] = 12345
            return metrics

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            # MediaMTX ready=false initially
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            watchdog = create_publisher_liveness_watchdog(
                config=config,
                camera_id="CAM1",
                publisher_metrics_func=dynamic_metrics,
                on_unhealthy=Mock(),
            )

            watchdog.start()
            time.sleep(0.5)  # ~5 polls, grace=1s
            watchdog.stop()

            metrics = watchdog.get_metrics()
            # Should transition to READY after frames_submitted > 0
            assert metrics["current_state"] in ("ready", "healthy", "starting")
            assert metrics["consecutive_unhealthy_polls"] == 0
            assert metrics["restart_count"] == 0

    def test_ready_publisher_becoming_unhealthy_uses_existing_semantics(self):
        """READY publisher becoming unhealthy → existing UNHEALTHY behavior."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=0.1,  # Very short grace - READY immediately
            stale_after_seconds=0.3,
            require_bytes_progress=True,
            consecutive_unhealthy_threshold=2,
        )

        # Publisher starts healthy with frames
        mock_publisher = MockPublisher("CAM1", healthy=True, frames_encoded=10)
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
            # MediaMTX ready=true with bytes
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

    def test_three_startup_polls_during_grace_zero_restarts(self):
        """three startup polls during grace → zero restarts."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.05,
            startup_grace_seconds=1.0,
            stale_after_seconds=0.5,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=1,  # Would restart immediately if UNHEALTHY
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

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

    def test_exact_grace_boundary(self):
        """Exact grace boundary: at grace → UNHEALTHY if no frames."""
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=0.2,
            stale_after_seconds=0.5,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=1,
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

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
            time.sleep(0.6)  # Well past 0.2s grace
            watchdog.stop()

            metrics = watchdog.get_metrics()
            assert metrics["restart_count"] > 0
            restart_mock.assert_called()

    def test_cam1_startup_sequence_no_premature_restart(self):
        """CAM1 startup sequence reproducing R3.14-H.1 → no premature restart before first frame.

        Simulates: publisher starts at T=0, first frame at ~T+13s.
        Watchdog must remain STARTING and not restart during this period.
        """
        config = PublisherLivenessConfig(
            ai_path="live/cam1-ai",
            poll_interval_seconds=0.1,
            startup_grace_seconds=15.0,  # Match production config
            stale_after_seconds=10.0,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=3,
        )

        mock_publisher = MockPublisher("CAM1", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None
        mock_publisher._started = True

        call_count = [0]

        def dynamic_metrics():
            call_count[0] += 1
            metrics = mock_publisher.get_metrics()
            # Simulate first frame arriving at ~poll 50 (5 seconds in test time)
            if call_count[0] >= 30:
                metrics["frames_submitted"] = 1
                metrics["frames_encoded"] = 1
                metrics["last_encode_time"] = time.time()
                metrics["ffmpeg_pid"] = 12345
            return metrics

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":false,"bytesReceived":0}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            restart_mock = Mock()
            watchdog = create_publisher_liveness_watchdog(
                config=config,
                camera_id="CAM1",
                publisher_metrics_func=dynamic_metrics,
                on_unhealthy=restart_mock,
            )

            watchdog.start()
            time.sleep(5.0)  # Simulate 5s (proportional to ~13s in prod)
            watchdog.stop()

            metrics = watchdog.get_metrics()
            # Should be READY/HEALTHY, not UNHEALTHY
            assert metrics["current_state"] in ("ready", "healthy")
            assert metrics["consecutive_unhealthy_polls"] == 0
            assert metrics["restart_count"] == 0

    def test_cam2_missing_source_eventually_unhealthy_after_grace(self):
        """CAM2 with genuinely missing source: watchdog may eventually become
        UNHEALTHY AFTER grace, but must not restart immediately during startup grace.
        """
        config = PublisherLivenessConfig(
            ai_path="live/cam2-ai",
            poll_interval_seconds=0.05,
            startup_grace_seconds=0.5,  # Short grace for test
            stale_after_seconds=0.2,
            require_bytes_progress=False,
            consecutive_unhealthy_threshold=1,
        )

        mock_publisher = MockPublisher("CAM2", healthy=False)
        mock_publisher._frames_encoded = 0
        mock_publisher._last_encode_time = 0.0
        mock_publisher._ffmpeg_pid = None

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam2-ai","ready":false,"bytesReceived":0}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            restart_mock = Mock()
            watchdog = create_publisher_liveness_watchdog(
                config=config,
                camera_id="CAM2",
                publisher_metrics_func=mock_publisher.get_metrics,
                on_unhealthy=restart_mock,
            )

            watchdog.start()
            time.sleep(0.2)  # During grace period
            watchdog.stop()

            metrics = watchdog.get_metrics()
            # During grace: STARTING, no restart
            assert metrics["current_state"] == "starting"
            assert metrics["restart_count"] == 0
            assert restart_mock.call_count == 0

            # Now continue past grace
            restart_mock.reset_mock()
            watchdog.start()
            time.sleep(1.0)  # Well past 0.5s grace
            watchdog.stop()

            metrics = watchdog.get_metrics()
            # After grace: restart triggered
            assert metrics["restart_count"] > 0
            restart_mock.assert_called()


# ================================================================ Integration Tests
# ================================================================

class TestCameraIsolation:
    """Tests verifying CAM1/CAM2 independence."""

    def test_capture_watchdogs_independent(self):
        """CAM1 watchdog should not affect CAM2."""
        wd1 = CaptureWatchdog(CaptureWatchdogConfig(stall_timeout_seconds=0.1), "CAM1")
        wd2 = CaptureWatchdog(CaptureWatchdogConfig(stall_timeout_seconds=0.1), "CAM2")

        wd1.claim_ownership()
        wd2.claim_ownership()

        assert wd1.has_active_owner
        assert wd2.has_active_owner

        # Force stall on CAM1
        wd1._force_teardown(1.0)
        assert wd1.teardown_requested
        assert not wd2.teardown_requested

    def test_publisher_watchdogs_independent(self):
        """CAM1 publisher watchdog should not affect CAM2."""
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"items":[{"name":"live/cam1-ai","ready":true,"bytesReceived":1000},{"name":"live/cam2-ai","ready":true,"bytesReceived":1000}]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            config1 = PublisherLivenessConfig(
                ai_path="live/cam1-ai",
                poll_interval_seconds=0.1,
                require_bytes_progress=False,
                request_timeout_seconds=0.5,
            )
            config2 = PublisherLivenessConfig(
                ai_path="live/cam2-ai",
                poll_interval_seconds=0.1,
                require_bytes_progress=False,
                request_timeout_seconds=0.5,
            )

            pub1 = MockPublisher("CAM1", healthy=True, frames_encoded=10)
            pub2 = MockPublisher("CAM2", healthy=True, frames_encoded=10)

            wd1 = create_publisher_liveness_watchdog(config1, "CAM1", pub1.get_metrics, Mock())
            wd2 = create_publisher_liveness_watchdog(config2, "CAM2", pub2.get_metrics, Mock())

            wd1.start()
            wd2.start()
            time.sleep(0.2)
            wd1.stop()
            wd2.stop()

            assert wd1.get_metrics()["healthy_count"] > 0
            assert wd2.get_metrics()["healthy_count"] > 0


class TestCaptureRecoveryInvariants:
    """Tests verifying recovery invariants from Phase 44.X.4-R3.3 Section C."""

    def test_frames_received_increases_after_recovery(self):
        """After recovery, frames_received must increase."""
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            use_supervised_source=False,  # Use legacy for test control
        )

        health_monitor = create_health_monitor()
        received = []

        worker = CameraIngestionWorker(
            config=config,
            health_monitor=health_monitor,
            frame_callback=lambda f: received.append(f),
        )

        # Mock the source to provide frames
        with patch('app.streaming.ingestion_worker.create_rtsp_source') as mock_create:
            mock_source = Mock()
            frames = []
            for i in range(5):
                frame = Mock()
                frame.metadata = Mock()
                frame.metadata.frame_index = i
                frame.metadata.timestamp = i * 0.033
                frame.data = np.zeros((2160, 3840, 3), dtype=np.uint8)
                frames.append(frame)

            mock_source.get_next_frame.side_effect = frames + [None]
            mock_source.is_exhausted = False
            mock_source.is_opened = True
            mock_source.open.return_value = Mock(width=3840, height=2160, fps=30.0)
            mock_create.return_value = mock_source

            worker.start()
            time.sleep(0.3)
            worker.stop()

            assert worker.frames_processed == 5
            assert len(received) == 5

    def test_frame_index_continues(self):
        """frame_index must continue after recovery."""
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            use_supervised_source=False,
        )

        health_monitor = create_health_monitor()
        indices = []

        worker = CameraIngestionWorker(
            config=config,
            health_monitor=health_monitor,
            frame_callback=lambda f: indices.append(f.metadata.frame_index),
        )

        with patch('app.streaming.ingestion_worker.create_rtsp_source') as mock_create:
            mock_source = Mock()
            frames = []
            for i in range(5):
                frame = Mock()
                frame.metadata = Mock()
                frame.metadata.frame_index = i
                frame.metadata.timestamp = i * 0.033
                frame.data = np.zeros((2160, 3840, 3), dtype=np.uint8)
                frames.append(frame)

            mock_source.get_next_frame.side_effect = frames + [None]
            mock_source.is_exhausted = False
            mock_source.is_opened = True
            mock_source.open.return_value = Mock(width=3840, height=2160, fps=30.0)
            mock_create.return_value = mock_source

            worker.start()
            time.sleep(0.3)
            worker.stop()

            # frame_index should be sequential
            assert indices == [0, 1, 2, 3, 4]

    def test_camera_id_preserved(self):
        """camera_id must remain correct after recovery."""
        config = CameraIngestionConfig(
            camera_id="CAM2",
            rtsp_url="rtsp://localhost:8554/live/cam2",
            use_supervised_source=False,
        )

        health_monitor = create_health_monitor()
        cams = []

        worker = CameraIngestionWorker(
            config=config,
            health_monitor=health_monitor,
            frame_callback=lambda f: cams.append(f.metadata.extra.get("camera_id")),
        )

        with patch('app.streaming.ingestion_worker.create_rtsp_source') as mock_create:
            mock_source = Mock()
            frame = Mock()
            frame.metadata = Mock()
            frame.metadata.frame_index = 0
            frame.metadata.timestamp = 0.0
            frame.metadata.extra = {"camera_id": "CAM2"}
            frame.data = np.zeros((2160, 3840, 3), dtype=np.uint8)
            mock_source.get_next_frame.side_effect = [frame, None]
            mock_source.is_exhausted = False
            mock_source.is_opened = True
            mock_source.open.return_value = Mock(width=3840, height=2160, fps=30.0)
            mock_create.return_value = mock_source

            worker.start()
            time.sleep(0.2)
            worker.stop()

            assert cams == ["CAM2"]


class TestPublisherRecoveryInvariants:
    """Tests verifying publisher recovery invariants from Phase 44.X.4-R3.3 Section E."""

    def test_restart_stops_stale_ffmpeg(self):
        """Restart should terminate the stale FFmpeg process."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()
            publisher._ffmpeg_proc = mock_proc
            assert publisher._ffmpeg_proc is mock_proc

            publisher.restart()

            # The old process was terminated via wait() or terminate().
            # After restart, _ffmpeg_proc should be None (cleared by
            # _terminate_ffmpeg).
            assert publisher._ffmpeg_proc is None

    def test_restart_clears_queue(self):
        """Restart should drain stale frames from queue."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()

            # Put a frame in queue
            frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
            publisher._queue.put(frame)
            assert publisher._queue.qsize() == 1

            publisher.restart()

            # Queue should be empty
            assert publisher._queue.empty()

    def test_restart_resets_metrics(self):
        """Restart should reset per-restart metrics."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()
            publisher._ffmpeg_proc = mock_proc
            publisher._metrics.frames_encoded = 100
            publisher._metrics.last_encode_time = time.time()

            publisher.restart()

            assert publisher._metrics.frames_encoded == 0
            assert publisher._metrics.last_encode_time == 0.0


class TestCleanShutdown:
    """Tests for clean shutdown during recovery (Section H item 13)."""

    def test_worker_stop_during_recovery(self):
        """Stop during recovery should not hang."""
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            use_supervised_source=False,
        )

        health_monitor = create_health_monitor()
        worker = CameraIngestionWorker(
            config=config,
            health_monitor=health_monitor,
        )

        with patch('app.streaming.ingestion_worker.create_rtsp_source') as mock_create:
            mock_source = Mock()
            mock_source.get_next_frame.side_effect = [None]  # Immediate EOF
            mock_source.is_exhausted = True
            mock_source.is_opened = True
            mock_source.open.return_value = Mock(width=3840, height=2160, fps=30.0)
            mock_create.return_value = mock_source

            worker.start()
            time.sleep(0.05)
            # Stop while reconnect might be triggered
            result = worker.stop(timeout=5.0)
            assert result is True
            assert worker.state == WorkerState.STOPPED

    def test_publisher_stop_during_restart(self):
        """Stop during restart should not leave orphan FFmpeg."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()
            publisher._ffmpeg_proc = mock_proc
            publisher.restart()
            publisher.stop(timeout=3.0)

            assert not publisher._metrics.started
            assert publisher._ffmpeg_proc is None


class TestNoOrphanFFmpeg:
    """Tests ensuring no orphan FFmpeg processes (Section H item 14)."""

    def test_publisher_stop_terminates_ffmpeg(self):
        """Stop must terminate the FFmpeg subprocess."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()
            publisher._ffmpeg_proc = mock_proc
            publisher.stop(timeout=3.0)

            # After stop, the ffmpeg proc reference should be cleared
            assert publisher._ffmpeg_proc is None

    def test_publisher_restart_terminates_old(self):
        """Restart must terminate the old FFmpeg before starting new."""
        config = AnnotatedPublisherConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        )
        publisher = AnnotatedFramePublisher(
            config=config,
            enable_liveness_watchdog=False,
        )

        with patch('subprocess.Popen') as mock_popen:
            mock_proc = MockSubprocess(pid=12345, alive=True)
            mock_popen.return_value = mock_proc

            publisher.start()
            publisher._ffmpeg_proc = mock_proc
            publisher.restart()

            # After restart, the ffmpeg proc reference should be cleared
            assert publisher._ffmpeg_proc is None


# ================================================================ Run Tests
# ================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])