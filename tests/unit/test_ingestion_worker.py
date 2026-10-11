"""
Phase 44.1 — Unit Tests for Camera Ingestion Worker.

Tests cover:
- Worker construction
- Worker start/stop
- CAM1 isolation
- CAM2 isolation
- CanonicalFrame propagation
- Frame counter monotonicity
- Timestamp validity
- Camera ID preservation
- Health report invocation
- Timeout handling
- Reconnect behavior
- Worker shutdown without orphan threads
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from dataclasses import dataclass

from app.streaming.contracts import StreamHealthState
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.streaming.reconnect import ReconnectConfig, ReconnectPolicy
from app.streaming.ingestion_worker import (
    CameraIngestionWorker,
    CameraIngestionConfig,
    WorkerState,
    WorkerSnapshot,
    create_camera_ingestion_worker,
    create_cam1_worker,
    create_cam2_worker,
)
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
import numpy as np


class MockRTSPSource:
    """Mock RTSPSource for testing."""

    def __init__(self, config, frames=None, should_fail=False, fail_after=0):
        self.config = config
        self.camera_id = config.camera_id
        self._frames = frames or []
        self._frame_index = 0
        self._should_fail = should_fail
        self._fail_after = fail_after
        self._opened = True
        self._exhausted = False
        self._error = None
        self._frame_count = 0
        self._info = Mock()
        self._info.width = config.expected_width
        self._info.height = config.expected_height
        self._info.fps = config.expected_fps
        self._info.frame_count = len(self._frames)

    def open(self):
        return self._info

    def get_next_frame(self):
        if self._should_fail and self._frame_count >= self._fail_after:
            raise Exception("Simulated frame read failure")

        if self._frame_index >= len(self._frames):
            self._exhausted = True
            return None

        frame = self._frames[self._frame_index]
        self._frame_index += 1
        self._frame_count += 1
        return frame

    def reconnect(self):
        self._frame_index = 0
        self._exhausted = False
        return True

    def close(self):
        self._opened = False

    @property
    def is_exhausted(self):
        return self._exhausted

    @property
    def has_error(self):
        return self._error is not None

    @property
    def error(self):
        return self._error

    @property
    def frames_produced(self):
        return self._frame_count

    @property
    def fps(self):
        return self._info.fps

    @property
    def resolution(self):
        return (self._info.width, self._info.height)

    @property
    def reconnect_count(self):
        return 0

    @property
    def last_frame_time(self):
        return time.time()

    @property
    def is_stream_validated(self):
        return True


def create_mock_frame(camera_id: str, frame_index: int, timestamp: float = None) -> CanonicalFrame:
    """Create a mock CanonicalFrame."""
    if timestamp is None:
        timestamp = frame_index * 0.033  # ~30 FPS

    metadata = FrameMetadata(
        source_type=SourceType.RTSP,
        source_id=f"rtsp://localhost:8554/live/{camera_id.lower()}",
        frame_index=frame_index,
        timestamp=timestamp,
        timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        original_width=3840,
        original_height=2160,
        pixel_format=PixelFormat.RGB,
        dtype="uint8",
        source_fps=30.0,
        source_duration=0.0,
        source_frame_count=100,
        extra={"camera_id": camera_id},
    )

    # Create dummy frame data
    data = np.zeros((2160, 3840, 3), dtype=np.uint8)

    return CanonicalFrame(data=data, metadata=metadata, conversions_applied={})


class TestCameraIngestionConfig:
    """Tests for CameraIngestionConfig."""

    def test_config_creation(self):
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        assert config.camera_id == "CAM1"
        assert config.rtsp_url == "rtsp://localhost:8554/live/cam1"
        assert config.expected_codec == "h264"
        assert config.expected_width == 3840
        assert config.expected_height == 2160

    def test_to_rtsp_source_config(self):
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        rtsp_config = config.to_rtsp_source_config()
        assert rtsp_config.camera_id == "CAM1"
        assert rtsp_config.rtsp_url == "rtsp://localhost:8554/live/cam1"

    def test_to_reconnect_config(self):
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        reconnect_config = config.to_reconnect_config()
        assert reconnect_config.policy == ReconnectPolicy.EXPONENTIAL_BACKOFF
        assert reconnect_config.max_retries == 5


class TestCameraIngestionWorker:
    """Tests for CameraIngestionWorker."""

    def setup_method(self):
        self.health_monitor = create_health_monitor()
        self.received_frames = []

        self.frame_callback = lambda frame: self.received_frames.append(frame)
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def create_worker(self, camera_id="CAM1", frames=None):
        """Create a worker with mocked RTSPSource."""
        config = CameraIngestionConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
        )

        mock_source = MockRTSPSource(config, frames=frames)
        self.mock_create_source.return_value = mock_source

        worker = CameraIngestionWorker(
            config=config,
            health_monitor=self.health_monitor,
            frame_callback=self.frame_callback,
        )

        return worker

    def test_worker_construction(self):
        worker = self.create_worker("CAM1")
        assert worker.camera_id == "CAM1"
        assert worker.state == WorkerState.STOPPED
        assert worker.frames_processed == 0
        assert worker.frames_reported == 0

    def test_worker_start_stop(self):
        worker = self.create_worker("CAM1", frames=[create_mock_frame("CAM1", i) for i in range(5)])

        # Start worker
        result = worker.start()
        assert result is True

        # Give it time to process frames
        time.sleep(0.5)

        # Stop worker
        result = worker.stop()
        assert result is True
        assert worker.state == WorkerState.STOPPED

    def test_worker_frames_processed(self):
        frames = [create_mock_frame("CAM1", i) for i in range(5)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)
        worker.stop()

        assert worker.frames_processed == 5
        assert worker.frames_reported == 5
        assert len(self.received_frames) == 5

    def test_cam1_isolation(self):
        """Test that CAM1 worker doesn't affect CAM2."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(3)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(3)]

        # Create separate mock sources for each worker
        config1 = CameraIngestionConfig(camera_id="CAM1", rtsp_url="rtsp://localhost:8554/live/cam1")
        config2 = CameraIngestionConfig(camera_id="CAM2", rtsp_url="rtsp://localhost:8554/live/cam2")

        mock_source1 = MockRTSPSource(config1, frames=frames1)
        mock_source2 = MockRTSPSource(config2, frames=frames2)

        # Patch create_rtsp_source to return the appropriate mock
        def side_effect(*args, **kwargs):
            camera_id = kwargs.get('camera_id', args[0] if args else 'CAM1')
            if camera_id == 'CAM1':
                return mock_source1
            return mock_source2

        with patch('app.streaming.ingestion_worker.create_rtsp_source', side_effect=side_effect):
            worker1 = CameraIngestionWorker(
                config=config1,
                health_monitor=self.health_monitor,
                frame_callback=self.frame_callback,
            )
            worker2 = CameraIngestionWorker(
                config=config2,
                health_monitor=self.health_monitor,
                frame_callback=self.frame_callback,
            )

            worker1.start()
            time.sleep(0.5)
            worker1.stop()

            worker2.start()
            time.sleep(0.5)
            worker2.stop()

        # Verify isolation
        assert worker1.frames_processed == 3
        assert worker2.frames_processed == 3

    def test_cam2_isolation(self):
        """Test that CAM2 worker doesn't affect CAM1."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(3)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(3)]

        # Create separate mock sources for each worker
        config1 = CameraIngestionConfig(camera_id="CAM1", rtsp_url="rtsp://localhost:8554/live/cam1")
        config2 = CameraIngestionConfig(camera_id="CAM2", rtsp_url="rtsp://localhost:8554/live/cam2")

        mock_source1 = MockRTSPSource(config1, frames=frames1)
        mock_source2 = MockRTSPSource(config2, frames=frames2)

        # Patch create_rtsp_source to return the appropriate mock
        def side_effect(*args, **kwargs):
            camera_id = kwargs.get('camera_id', args[0] if args else 'CAM1')
            if camera_id == 'CAM1':
                return mock_source1
            return mock_source2

        with patch('app.streaming.ingestion_worker.create_rtsp_source', side_effect=side_effect):
            worker1 = CameraIngestionWorker(
                config=config1,
                health_monitor=self.health_monitor,
                frame_callback=self.frame_callback,
            )
            worker2 = CameraIngestionWorker(
                config=config2,
                health_monitor=self.health_monitor,
                frame_callback=self.frame_callback,
            )

            worker2.start()
            time.sleep(0.5)
            worker2.stop()

            worker1.start()
            time.sleep(0.5)
            worker1.stop()

        # Verify isolation
        assert worker1.frames_processed == 3
        assert worker2.frames_processed == 3

    def test_canonical_frame_propagation(self):
        """Test that CanonicalFrame is properly propagated."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)
        worker.stop()

        assert len(self.received_frames) == 3

        for i, frame in enumerate(self.received_frames):
            assert isinstance(frame, CanonicalFrame)
            assert frame.metadata.extra.get("camera_id") == "CAM1"
            assert frame.metadata.frame_index == i
            assert frame.width == 3840
            assert frame.height == 2160

    def test_frame_counter_monotonicity(self):
        """Test that frame counter increases monotonically."""
        frames = [create_mock_frame("CAM1", i) for i in range(10)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)
        worker.stop()

        # Frame counter should be 10
        assert worker.frames_processed == 10
        assert worker.frames_reported == 10

        # Each frame should have increasing frame_index
        for i, frame in enumerate(self.received_frames):
            assert frame.metadata.frame_index == i

    def test_timestamp_validity(self):
        """Test that timestamps are valid and increasing."""
        frames = [create_mock_frame("CAM1", i, timestamp=i * 0.033) for i in range(5)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)
        worker.stop()

        timestamps = [f.metadata.timestamp for f in self.received_frames]

        # Timestamps should be monotonically increasing
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i-1], "Timestamps not monotonic"

    def test_camera_id_preservation(self):
        """Test that camera_id is preserved in frames."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)
        worker.stop()

        for frame in self.received_frames:
            assert frame.metadata.extra.get("camera_id") == "CAM1"

    def test_health_report_invocation(self):
        """Test that health monitor receives frame reports."""
        frames = [create_mock_frame("CAM1", i) for i in range(5)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.5)

        # Check health monitor state while worker is running
        snapshot = worker._health_monitor.get_snapshot("CAM1")
        assert snapshot is not None
        assert snapshot.frames_received == 5
        assert snapshot.state == StreamHealthState.LIVE
        assert snapshot.current_resolution == (3840, 2160)
        assert snapshot.current_fps == 30.0

        worker.stop()

    def test_timeout_handling(self):
        """Test that worker handles timeout without 100% CPU."""
        # Create a source that blocks/times out
        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            timeout=0.1,  # Short timeout
        )

        # Mock source that simulates timeout
        mock_source = Mock()
        mock_source.get_next_frame.side_effect = TimeoutError("Frame read timeout")
        mock_source.is_exhausted = False
        mock_source.has_error = False

        with patch('app.streaming.ingestion_worker.create_rtsp_source', return_value=mock_source):
            worker = CameraIngestionWorker(
                config=config,
                health_monitor=self.health_monitor,
            )

            worker.start()
            time.sleep(0.5)
            worker.stop()

        # Worker should handle timeout gracefully, not spin at 100% CPU
        assert worker.state == WorkerState.STOPPED

    def test_reconnect_behavior(self):
        """Test reconnect behavior on frame read failure."""
        # Create frames that fail after 2 frames
        frames = [create_mock_frame("CAM1", i) for i in range(2)]

        config = CameraIngestionConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            max_retries=1,
            retry_interval=0.1,
        )

        # Create mock source that fails after 2 frames
        mock_source = MockRTSPSource(config, frames=frames, should_fail=True, fail_after=2)

        with patch('app.streaming.ingestion_worker.create_rtsp_source', return_value=mock_source):
            worker = CameraIngestionWorker(
                config=config,
                health_monitor=self.health_monitor,
            )

            worker.start()
            time.sleep(1.0)  # Allow time for reconnect attempt
            worker.stop()

        # Should have processed at least the initial frames
        assert worker.frames_processed >= 2

    def test_worker_shutdown_no_orphan_threads(self):
        """Test that worker shutdown doesn't leave orphan threads."""
        frames = [create_mock_frame("CAM1", i) for i in range(100)]  # Many frames
        worker = self.create_worker("CAM1", frames=frames)

        initial_threads = threading.active_count()

        worker.start()
        time.sleep(0.2)
        worker.stop(timeout=2.0)

        # Allow thread cleanup
        time.sleep(0.1)

        final_threads = threading.active_count()

        # Thread count should return to baseline (allowing for test framework threads)
        assert final_threads <= initial_threads + 2

    def test_worker_snapshot(self):
        """Test worker snapshot functionality."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.3)
        worker.stop()

        snapshot = worker.get_snapshot()

        assert isinstance(snapshot, WorkerSnapshot)
        assert snapshot.camera_id == "CAM1"
        assert snapshot.state == WorkerState.STOPPED
        assert snapshot.frames_processed == 3
        assert snapshot.frames_reported == 3
        assert snapshot.resolution == (3840, 2160)
        assert snapshot.fps == 30.0

    def test_worker_get_health_result(self):
        """Test getting health check result."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)

        worker.start()
        time.sleep(0.3)

        # Check health while worker is running
        health_result = worker.get_health_result()

        assert health_result.camera_id == "CAM1"
        assert health_result.state == StreamHealthState.LIVE
        assert health_result.details["frames_received"] == 3

        worker.stop()

    def test_double_start_prevented(self):
        """Test that starting an already running worker is prevented."""
        worker = self.create_worker("CAM1")

        worker.start()
        result = worker.start()  # Second start

        assert result is False  # Should return False
        worker.stop()

    def test_stop_not_started_worker(self):
        """Test stopping a worker that was never started."""
        worker = self.create_worker("CAM1")

        result = worker.stop()

        assert result is True
        assert worker.state == WorkerState.STOPPED


class TestFactoryFunctions:
    """Tests for factory functions."""

    @patch('app.streaming.ingestion_worker.load_settings')
    def test_create_camera_ingestion_worker(self, mock_load_settings):
        mock_settings = Mock()
        mock_settings.cameras.get_cam1_rtsp_url.return_value = "rtsp://localhost:8554/live/cam1"
        mock_settings.cameras.get_cam2_rtsp_url.return_value = "rtsp://localhost:8554/live/cam2"
        mock_settings.cameras.expected_codec = "h264"
        mock_settings.cameras.expected_width = 3840
        mock_settings.cameras.expected_height = 2160
        mock_settings.cameras.expected_fps = 30.0
        mock_settings.cameras.nvdec_enabled = False
        mock_settings.cameras.nvdec_gpu_device = 0
        mock_settings.cameras.reconnect_max_retries = 5
        mock_settings.cameras.reconnect_base_interval = 2.0
        mock_settings.cameras.to_reconnect_config.return_value = ReconnectConfig()
        mock_settings.cameras.to_health_monitor_config.return_value = (5.0, 2.0)
        mock_load_settings.return_value = mock_settings

        worker = create_camera_ingestion_worker("CAM1")

        assert worker.camera_id == "CAM1"
        assert "cam1" in worker.config.rtsp_url

    @patch('app.streaming.ingestion_worker.load_settings')
    def test_create_cam1_worker(self, mock_load_settings):
        mock_settings = Mock()
        mock_settings.cameras.get_cam1_rtsp_url.return_value = "rtsp://localhost:8554/live/cam1"
        mock_settings.cameras.get_cam2_rtsp_url.return_value = "rtsp://localhost:8554/live/cam2"
        mock_settings.cameras.expected_codec = "h264"
        mock_settings.cameras.expected_width = 3840
        mock_settings.cameras.expected_height = 2160
        mock_settings.cameras.expected_fps = 30.0
        mock_settings.cameras.nvdec_enabled = False
        mock_settings.cameras.nvdec_gpu_device = 0
        mock_settings.cameras.reconnect_max_retries = 5
        mock_settings.cameras.reconnect_base_interval = 2.0
        mock_settings.cameras.to_reconnect_config.return_value = ReconnectConfig()
        mock_settings.cameras.to_health_monitor_config.return_value = (5.0, 2.0)
        mock_load_settings.return_value = mock_settings

        worker = create_cam1_worker()

        assert worker.camera_id == "CAM1"

    @patch('app.streaming.ingestion_worker.load_settings')
    def test_create_cam2_worker(self, mock_load_settings):
        mock_settings = Mock()
        mock_settings.cameras.get_cam1_rtsp_url.return_value = "rtsp://localhost:8554/live/cam1"
        mock_settings.cameras.get_cam2_rtsp_url.return_value = "rtsp://localhost:8554/live/cam2"
        mock_settings.cameras.expected_codec = "h264"
        mock_settings.cameras.expected_width = 3840
        mock_settings.cameras.expected_height = 2160
        mock_settings.cameras.expected_fps = 30.0
        mock_settings.cameras.nvdec_enabled = False
        mock_settings.cameras.nvdec_gpu_device = 0
        mock_settings.cameras.reconnect_max_retries = 5
        mock_settings.cameras.reconnect_base_interval = 2.0
        mock_settings.cameras.to_reconnect_config.return_value = ReconnectConfig()
        mock_settings.cameras.to_health_monitor_config.return_value = (5.0, 2.0)
        mock_load_settings.return_value = mock_settings

        worker = create_cam2_worker()

        assert worker.camera_id == "CAM2"


class TestWorkerStateTransitions:
    """Tests for worker state transitions."""

    def setup_method(self):
        self.health_monitor = create_health_monitor()
        self.received_frames = []
        self.frame_callback = lambda frame: self.received_frames.append(frame)
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()

    def create_worker(self, camera_id="CAM1", frames=None):
        config = CameraIngestionConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
        )
        mock_source = MockRTSPSource(config, frames=frames)
        self.mock_create_source.return_value = mock_source
        worker = CameraIngestionWorker(
            config=config,
            health_monitor=self.health_monitor,
            frame_callback=self.frame_callback,
        )
        return worker

    def test_state_transitions(self):
        """Test proper state transitions."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)

        assert worker.state == WorkerState.STOPPED

        worker.start()
        time.sleep(0.1)
        # State should be RUNNING (or CONNECTING briefly)
        assert worker.state in (WorkerState.CONNECTING, WorkerState.RUNNING)

        time.sleep(0.3)
        worker.stop()

        assert worker.state == WorkerState.STOPPED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])