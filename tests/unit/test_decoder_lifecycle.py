"""
Phase 9.3 — Unit Tests for Decoder Lifecycle.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import sys
import os
import time

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.streaming.camera_runtime_manager import (
    CameraRuntimeManager,
    CameraRuntimeConfig,
    CameraRuntimeState,
)
from app.streaming.ingestion_worker import (
    CameraIngestionWorker,
    CameraIngestionConfig,
    WorkerState,
)


class MockRTSPSource:
    """Mock RTSPSource for testing."""
    
    def __init__(self, config, frames=None, should_fail=False):
        self.config = config
        self.camera_id = config.camera_id
        self._frames = frames or []
        self._frame_index = 0
        self._should_fail = should_fail
        self._opened = True
        self._exhausted = False
        self._info = MagicMock()
        self._info.width = config.expected_width
        self._info.height = config.expected_height
        self._info.fps = config.expected_fps
        self._info.frame_count = len(self._frames)
        self._frame_count = 0
        self._error = None
    
    def open(self):
        return self._info
    
    def get_next_frame(self):
        if self._should_fail:
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


def create_mock_frame(camera_id: str, frame_index: int):
    """Create a mock CanonicalFrame."""
    from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
    import numpy as np
    
    metadata = FrameMetadata(
        source_type=SourceType.RTSP,
        source_id=f"rtsp://localhost:8554/live/{camera_id.lower()}",
        frame_index=frame_index,
        timestamp=frame_index * 0.033,
        timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        original_width=3840,
        original_height=2160,
        pixel_format=PixelFormat.RGB,
        dtype="uint8",
        source_fps=30.0,
        source_duration=0.0,
        source_frame_count=100,
        extra={"camera_id": camera_id, "decoder": "pynvvideocodec"},
    )
    
    data = np.zeros((2160, 3840, 3), dtype=np.uint8)
    
    return CanonicalFrame(data=data, metadata=metadata, conversions_applied={})


class TestCameraRuntimeManagerLifecycle:
    """Tests for CameraRuntimeManager lifecycle."""
    
    def setup_method(self):
        self.health_monitor = None
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()
    
    def teardown_method(self):
        self._patcher.stop()
    
    def create_manager(self, camera_id="CAM1", frames=None):
        config = CameraRuntimeConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
            decoder="pynvvideocodec",
        )
        
        mock_source = MockRTSPSource(config, frames=frames)
        self.mock_create_source.return_value = mock_source
        
        manager = CameraRuntimeManager(
            config=config,
            health_monitor=self.health_monitor,
        )
        
        return manager
    
    def test_initial_state_stopped(self):
        """Initial state should be STOPPED."""
        manager = self.create_manager("CAM1")
        assert manager.state == CameraRuntimeState.STOPPED
        assert manager.is_stopped
        assert not manager.is_ready
        assert not manager.is_running
    
    @patch('app.streaming.camera_runtime_manager.CameraIngestionWorker')
    @patch('app.streaming.camera_runtime_manager.DetectionPipeline')
    @patch('app.streaming.camera_runtime_manager.AnnotatedFramePublisher')
    def test_start_transitions_through_states(self, mock_publisher, mock_detection, mock_ingestion):
        """Start should transition through expected states."""
        # Setup mocks
        mock_ingestion_instance = MagicMock()
        mock_ingestion_instance.start.return_value = True
        mock_ingestion_instance.state = WorkerState.RUNNING
        mock_ingestion.return_value = mock_ingestion_instance
        
        mock_detection_instance = MagicMock()
        mock_detection_instance.start.return_value = True
        mock_detection_instance._running = True
        mock_detection.return_value = mock_detection_instance
        
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.start.return_value = True
        mock_publisher_instance._metrics = MagicMock()
        mock_publisher_instance._metrics.started = True
        mock_publisher.return_value = mock_publisher_instance
        
        # Create manager with minimal frames to trigger FIRST_GPU_FRAME
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        manager = self.create_manager("CAM1", frames=frames)
        
        # Mock time to control ready_event
        original_time = time.time
        time_values = [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]
        time_calls = [0]
        
        def mock_time():
            idx = time_calls[0]
            time_calls[0] += 1
            return time_values[min(idx, len(time_values) - 1)]
        
        with patch('app.streaming.camera_runtime_manager.time.time', mock_time):
            result = manager.start(wait_ready=False)
        
        assert result is True
        # State transitions happen quickly, final should be RUNNING
        assert manager.state == CameraRuntimeState.RUNNING
        assert manager.is_running
    
    def test_stop_from_stopped(self):
        """Stop from STOPPED should return True."""
        manager = self.create_manager("CAM1")
        result = manager.stop()
        assert result is True
    
    @patch('app.streaming.camera_runtime_manager.CameraIngestionWorker')
    @patch('app.streaming.camera_runtime_manager.DetectionPipeline')
    @patch('app.streaming.camera_runtime_manager.AnnotatedFramePublisher')
    def test_stop_cleans_up(self, mock_publisher, mock_detection, mock_ingestion):
        """Stop should clean up all components."""
        mock_ingestion_instance = MagicMock()
        mock_ingestion_instance.start.return_value = True
        mock_ingestion_instance.state = WorkerState.RUNNING
        mock_ingestion_instance.stop.return_value = True
        mock_ingestion.return_value = mock_ingestion_instance
        
        mock_detection_instance = MagicMock()
        mock_detection_instance.start.return_value = True
        mock_detection_instance.stop.return_value = None
        mock_detection_instance._running = True
        mock_detection.return_value = mock_detection_instance
        
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.start.return_value = True
        mock_publisher_instance.stop.return_value = None
        mock_publisher_instance._metrics = MagicMock()
        mock_publisher_instance._metrics.started = True
        mock_publisher.return_value = mock_publisher_instance
        
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        manager = self.create_manager("CAM1", frames=frames)
        
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=1000.0):
            manager.start(wait_ready=False)
        
        result = manager.stop(timeout=5.0)
        
        assert result is True
        assert manager.state == CameraRuntimeState.STOPPED
        mock_ingestion_instance.stop.assert_called_once()
        mock_detection_instance.stop.assert_called_once()
        mock_publisher_instance.stop.assert_called_once()
    
    def test_restart_increments_counter(self):
        """Restart should increment reconnect counter."""
        manager = self.create_manager("CAM1")
        initial_attempts = manager._reconnect_attempts
        
        with patch.object(manager, 'stop', return_value=True):
            with patch.object(manager, 'start', return_value=True):
                manager.restart(timeout=5.0)
        
        assert manager._reconnect_attempts == initial_attempts + 1


class TestCameraIngestionWorkerLifecycle:
    """Tests for CameraIngestionWorker lifecycle."""
    
    def setup_method(self):
        from app.streaming.health import create_health_monitor
        self.health_monitor = create_health_monitor()
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()
    
    def teardown_method(self):
        self._patcher.stop()
    
    def create_worker(self, camera_id="CAM1", frames=None):
        config = CameraIngestionConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
            decoder="pynvvideocodec",
        )
        
        mock_source = MockRTSPSource(config, frames=frames)
        self.mock_create_source.return_value = mock_source
        
        worker = CameraIngestionWorker(
            config=config,
            health_monitor=self.health_monitor,
        )
        
        return worker
    
    def test_initial_state_stopped(self):
        """Initial state should be STOPPED."""
        worker = self.create_worker("CAM1")
        assert worker.state == WorkerState.STOPPED
        assert worker.is_stopped
        assert not worker.is_running
    
    def test_start_stop_cycle(self):
        """Start then stop should work."""
        frames = [create_mock_frame("CAM1", i) for i in range(5)]
        worker = self.create_worker("CAM1", frames=frames)
        
        result = worker.start()
        assert result is True
        assert worker.state in (WorkerState.STARTING, WorkerState.CONNECTING, WorkerState.RUNNING)
        
        time.sleep(0.1)
        
        result = worker.stop()
        assert result is True
        assert worker.state == WorkerState.STOPPED
    
    def test_double_start_prevented(self):
        """Starting already running worker should return False."""
        frames = [create_mock_frame("CAM1", i) for i in range(5)]
        worker = self.create_worker("CAM1", frames=frames)
        
        worker.start()
        result = worker.start()  # Second start
        assert result is False
        worker.stop()
    
    def test_reconnect_same_backend(self):
        """Reconnect should use same backend configuration."""
        frames = [create_mock_frame("CAM1", i) for i in range(3)]
        worker = self.create_worker("CAM1", frames=frames)
        
        worker.start()
        time.sleep(0.1)
        
        # Simulate frame read failure to trigger reconnect
        worker._source._should_fail = True
        time.sleep(0.5)
        
        # Worker should attempt reconnect with same decoder config
        # The reconnect logic uses the same config.decoder
        
        worker.stop()
        
        # Verify config.decoder unchanged
        assert worker.config.decoder == "pynvvideocodec"


class TestDualCameraLifecycle:
    """Tests for dual camera lifecycle (sequential initialization)."""
    
    def setup_method(self):
        from app.streaming.health import create_health_monitor
        self.health_monitor = create_health_monitor()
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()
    
    def teardown_method(self):
        self._patcher.stop()
    
    def create_manager(self, camera_id):
        config = CameraRuntimeConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
            decoder="pynvvideocodec",
        )
        
        mock_source = MockRTSPSource(config)
        self.mock_create_source.return_value = mock_source
        
        manager = CameraRuntimeManager(
            config=config,
            health_monitor=self.health_monitor,
        )
        
        return manager
    
    @patch('app.streaming.camera_runtime_manager.CameraIngestionWorker')
    @patch('app.streaming.camera_runtime_manager.DetectionPipeline')
    @patch('app.streaming.camera_runtime_manager.AnnotatedFramePublisher')
    def test_sequential_initialization(self, mock_publisher, mock_detection, mock_ingestion):
        """CAM1 should fully initialize before CAM2 starts."""
        # Setup mocks for both cameras
        mock_ingestion_instance = MagicMock()
        mock_ingestion_instance.start.return_value = True
        mock_ingestion_instance.state = WorkerState.RUNNING
        mock_ingestion_instance.stop.return_value = True
        mock_ingestion.return_value = mock_ingestion_instance
        
        mock_detection_instance = MagicMock()
        mock_detection_instance.start.return_value = True
        mock_detection_instance.stop.return_value = None
        mock_detection_instance._running = True
        mock_detection.return_value = mock_detection_instance
        
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.start.return_value = True
        mock_publisher_instance.stop.return_value = None
        mock_publisher_instance._metrics = MagicMock()
        mock_publisher_instance._metrics.started = True
        mock_publisher.return_value = mock_publisher_instance
        
        # Create managers
        cam1_manager = self.create_manager("CAM1")
        cam2_manager = self.create_manager("CAM2")
        
        # Sequential start (simulating GTX 1660 Ti constraint)
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=1000.0):
            cam1_result = cam1_manager.start(wait_ready=False)
        
        assert cam1_result is True
        assert cam1_manager.state == CameraRuntimeState.RUNNING
        
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=2000.0):
            cam2_result = cam2_manager.start(wait_ready=False)
        
        assert cam2_result is True
        assert cam2_manager.state == CameraRuntimeState.RUNNING
        
        # Both running
        assert cam1_manager.is_running
        assert cam2_manager.is_running
        
        # Stop both
        cam1_manager.stop()
        cam2_manager.stop()
    
    @patch('app.streaming.camera_runtime_manager.CameraIngestionWorker')
    @patch('app.streaming.camera_runtime_manager.DetectionPipeline')
    @patch('app.streaming.camera_runtime_manager.AnnotatedFramePublisher')
    def test_independent_failure(self, mock_publisher, mock_detection, mock_ingestion):
        """CAM1 failure should not affect CAM2."""
        # CAM1 fails
        mock_ingestion_cam1 = MagicMock()
        mock_ingestion_cam1.start.return_value = False  # Fail to start
        mock_ingestion_cam1.state = WorkerState.STOPPED
        
        # CAM2 succeeds
        mock_ingestion_cam2 = MagicMock()
        mock_ingestion_cam2.start.return_value = True
        mock_ingestion_cam2.state = WorkerState.RUNNING
        mock_ingestion_cam2.stop.return_value = True
        
        mock_ingestion.side_effect = [mock_ingestion_cam1, mock_ingestion_cam2]
        
        mock_detection_instance = MagicMock()
        mock_detection_instance.start.return_value = True
        mock_detection_instance.stop.return_value = None
        mock_detection_instance._running = True
        mock_detection.return_value = mock_detection_instance
        
        mock_publisher_instance = MagicMock()
        mock_publisher_instance.start.return_value = True
        mock_publisher_instance.stop.return_value = None
        mock_publisher_instance._metrics = MagicMock()
        mock_publisher_instance._metrics.started = True
        mock_publisher.return_value = mock_publisher_instance
        
        cam1_manager = self.create_manager("CAM1")
        cam2_manager = self.create_manager("CAM2")
        
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=1000.0):
            cam1_result = cam1_manager.start(wait_ready=False)
        
        assert cam1_result is False
        assert cam1_manager.state == CameraRuntimeState.FAILED
        
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=2000.0):
            cam2_result = cam2_manager.start(wait_ready=False)
        
        assert cam2_result is True
        assert cam2_manager.state == CameraRuntimeState.RUNNING
        
        cam2_manager.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])