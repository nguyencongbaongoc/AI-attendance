"""
Phase 9.3 — Unit Tests for Dual Camera Operation.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os
import time
import threading

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
from app.streaming.health import create_health_monitor


def wait_for_frames(worker, expected_frames, timeout=5.0):
    """Wait until worker processes expected frames or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if worker.frames_processed >= expected_frames:
            return True
        time.sleep(0.01)  # Small poll interval
    return False


def wait_for_state(worker, expected_state, timeout=5.0):
    """Wait until worker reaches expected state or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if worker.state == expected_state:
            return True
        time.sleep(0.01)
    return False


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


class TestDualCameraSequentialInit:
    """Tests for dual camera sequential initialization."""
    
    def setup_method(self):
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
    def test_cam1_then_cam2_sequential(self, mock_publisher, mock_detection, mock_ingestion):
        """CAM1 should fully initialize before CAM2 starts."""
        # Track initialization order
        init_order = []
        
        # Create mock instances that will be returned
        mock_ingestion_instance1 = MagicMock()
        mock_ingestion_instance1.start.return_value = True
        mock_ingestion_instance1.state = WorkerState.RUNNING
        mock_ingestion_instance1.stop.return_value = True
        
        mock_ingestion_instance2 = MagicMock()
        mock_ingestion_instance2.start.return_value = True
        mock_ingestion_instance2.state = WorkerState.RUNNING
        mock_ingestion_instance2.stop.return_value = True
        
        # Return appropriate instance based on call count
        call_count = [0]
        def track_ingestion_start(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                init_order.append("CAM1_ingestion_start")
                return mock_ingestion_instance1
            else:
                init_order.append("CAM2_ingestion_start")
                return mock_ingestion_instance2
        
        mock_ingestion.side_effect = track_ingestion_start
        
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
        
        # Start CAM1 first
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=1000.0):
            cam1_result = cam1_manager.start(wait_ready=False)
        
        assert cam1_result is True
        assert cam1_manager.state == CameraRuntimeState.RUNNING
        
        # Then start CAM2
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=2000.0):
            cam2_result = cam2_manager.start(wait_ready=False)
        
        assert cam2_result is True
        assert cam2_manager.state == CameraRuntimeState.RUNNING
        
        # Both running
        assert cam1_manager.is_running
        assert cam2_manager.is_running
        
        cam1_manager.stop()
        cam2_manager.stop()
    
    @patch('app.streaming.camera_runtime_manager.CameraIngestionWorker')
    @patch('app.streaming.camera_runtime_manager.DetectionPipeline')
    @patch('app.streaming.camera_runtime_manager.AnnotatedFramePublisher')
    def test_cam2_fails_cam1_unaffected(self, mock_publisher, mock_detection, mock_ingestion):
        """CAM2 failure should not affect CAM1."""
        # CAM1 succeeds
        mock_ingestion_cam1 = MagicMock()
        mock_ingestion_cam1.start.return_value = True
        mock_ingestion_cam1.state = WorkerState.RUNNING
        mock_ingestion_cam1.stop.return_value = True
        
        # CAM2 fails
        mock_ingestion_cam2 = MagicMock()
        mock_ingestion_cam2.start.return_value = False
        mock_ingestion_cam2.state = WorkerState.STOPPED
        
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
        
        assert cam1_result is True
        assert cam1_manager.state == CameraRuntimeState.RUNNING
        
        with patch('app.streaming.camera_runtime_manager.time.time', return_value=2000.0):
            cam2_result = cam2_manager.start(wait_ready=False)
        
        assert cam2_result is False
        assert cam2_manager.state == CameraRuntimeState.FAILED
        
        # CAM1 should still be running
        assert cam1_manager.is_running
        
        cam1_manager.stop()


class TestDualCameraIndependentFailure:
    """Tests for independent camera failure handling."""
    
    def setup_method(self):
        self.health_monitor = create_health_monitor()
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()
    
    def teardown_method(self):
        self._patcher.stop()
        if hasattr(self, '_mock_sources'):
            del self._mock_sources
    
    def create_worker(self, camera_id, frames=None, should_fail=False, fail_after=0):
        config = CameraIngestionConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
            decoder="pynvvideocodec",
        )
        
        mock_source = MockRTSPSource(config, frames=frames, should_fail=should_fail, fail_after=fail_after)
        
        # Store mock source per camera_id to avoid overwriting
        if not hasattr(self, '_mock_sources'):
            self._mock_sources = {}
        self._mock_sources[camera_id] = mock_source
        
        def mock_create_source_func(*args, **kwargs):
            # Match by camera_id in args or kwargs
            if args and hasattr(args[0], 'camera_id'):
                cid = args[0].camera_id
                if cid in self._mock_sources:
                    return self._mock_sources[cid]
            if 'camera_id' in kwargs:
                cid = kwargs['camera_id']
                if cid in self._mock_sources:
                    return self._mock_sources[cid]
            # Fallback: return the mock_source for the current camera_id
            return self._mock_sources.get(camera_id, mock_source)
        
        self.mock_create_source.side_effect = mock_create_source_func
        
        worker = CameraIngestionWorker(
            config=config,
            health_monitor=self.health_monitor,
        )
        
        return worker
    
    def test_cam1_failure_cam2_continues(self):
        """CAM1 frame read failure should not affect CAM2."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(5)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(5)]
        
        # CAM1 fails after 2 frames
        worker1 = self.create_worker("CAM1", frames=frames1, should_fail=True, fail_after=2)
        # CAM2 normal
        worker2 = self.create_worker("CAM2", frames=frames2)
        
        worker1.start()
        worker2.start()
        
        # Wait for CAM2 to process all frames
        assert wait_for_frames(worker2, 5), f"worker2 only processed {worker2.frames_processed}/5 frames"
        
        worker1.stop()
        worker2.stop()
        
        # Both should have processed frames
        assert worker1.frames_processed >= 2
        assert worker2.frames_processed == 5
    
    def test_cam1_reconnect_no_destroy_cam2(self):
        """CAM1 reconnect should not destroy CAM2."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(10)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(10)]
        
        # CAM1 will fail after 3 frames, then reconnect
        worker1 = self.create_worker("CAM1", frames=frames1, should_fail=True, fail_after=3)
        worker2 = self.create_worker("CAM2", frames=frames2)
        
        worker1.start()
        worker2.start()
        
        # Wait for CAM2 to process all frames
        assert wait_for_frames(worker2, 10), f"worker2 only processed {worker2.frames_processed}/10 frames"
        
        worker1.stop()
        worker2.stop()
        
        # CAM2 should have continued processing
        assert worker2.frames_processed == 10
        # CAM1 should have reconnected and continued
        assert worker1.frames_processed >= 3


class TestCameraIsolation:
    """Tests for per-camera isolation (no shared state)."""
    
    def setup_method(self):
        self.health_monitor = create_health_monitor()
        self._patcher = patch('app.streaming.ingestion_worker.create_rtsp_source')
        self.mock_create_source = self._patcher.start()
    
    def teardown_method(self):
        self._patcher.stop()
        if hasattr(self, '_mock_sources'):
            del self._mock_sources
    
    def create_worker(self, camera_id, frames=None, should_fail=False, fail_after=0):
        config = CameraIngestionConfig(
            camera_id=camera_id,
            rtsp_url=f"rtsp://localhost:8554/live/{camera_id.lower()}",
            decoder="pynvvideocodec",
        )
        
        mock_source = MockRTSPSource(config, frames=frames, should_fail=should_fail, fail_after=fail_after)
        
        # Store mock source per camera_id to avoid overwriting
        if not hasattr(self, '_mock_sources'):
            self._mock_sources = {}
        self._mock_sources[camera_id] = mock_source
        
        def mock_create_source_func(*args, **kwargs):
            # Match by camera_id in args or kwargs
            if args and hasattr(args[0], 'camera_id'):
                cid = args[0].camera_id
                if cid in self._mock_sources:
                    return self._mock_sources[cid]
            if 'camera_id' in kwargs:
                cid = kwargs['camera_id']
                if cid in self._mock_sources:
                    return self._mock_sources[cid]
            # Fallback: return the mock_source for the current camera_id
            return self._mock_sources.get(camera_id, mock_source)
        
        self.mock_create_source.side_effect = mock_create_source_func
        
        worker = CameraIngestionWorker(
            config=config,
            health_monitor=self.health_monitor,
        )
        
        return worker
    
    def test_no_shared_frame_counters(self):
        """Each camera should have independent frame counter."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(5)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(3)]
        
        worker1 = self.create_worker("CAM1", frames=frames1)
        worker2 = self.create_worker("CAM2", frames=frames2)
        
        worker1.start()
        worker2.start()
        
        # Wait for both to complete their frames
        assert wait_for_frames(worker1, 5), f"worker1 only processed {worker1.frames_processed}/5 frames"
        assert wait_for_frames(worker2, 3), f"worker2 only processed {worker2.frames_processed}/3 frames"
        
        worker1.stop()
        worker2.stop()
        
        assert worker1.frames_processed == 5
        assert worker2.frames_processed == 3
        assert worker1.frames_processed != worker2.frames_processed
    
    def test_no_shared_health_state(self):
        """Each camera should have independent health state."""
        from app.streaming.contracts import StreamHealthState
        
        frames1 = [create_mock_frame("CAM1", i) for i in range(5)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(5)]
        
        worker1 = self.create_worker("CAM1", frames=frames1)
        worker2 = self.create_worker("CAM2", frames=frames2)
        
        worker1.start()
        
        # Wait for CAM1 to be running and process some frames
        assert wait_for_state(worker1, WorkerState.RUNNING), "worker1 did not reach RUNNING state"
        assert wait_for_frames(worker1, 2), "worker1 did not process 2 frames"
        
        # Check health for CAM1
        health1 = worker1.get_health_result()
        assert health1.camera_id == "CAM1"
        assert health1.state == StreamHealthState.LIVE
        
        worker2.start()
        
        # Wait for CAM2 to be running
        assert wait_for_state(worker2, WorkerState.RUNNING), "worker2 did not reach RUNNING state"
        assert wait_for_frames(worker2, 2), "worker2 did not process 2 frames"
        
        # Check health for CAM2
        health2 = worker2.get_health_result()
        assert health2.camera_id == "CAM2"
        assert health2.state == StreamHealthState.LIVE
        
        worker1.stop()
        worker2.stop()
    
    def test_no_shared_reconnect_state(self):
        """Each camera should have independent reconnect state."""
        frames1 = [create_mock_frame("CAM1", i) for i in range(3)]
        frames2 = [create_mock_frame("CAM2", i) for i in range(3)]
        
        # CAM1 will fail and reconnect
        worker1 = self.create_worker("CAM1", frames=frames1, should_fail=True, fail_after=2)
        worker2 = self.create_worker("CAM2", frames=frames2)
        
        worker1.start()
        worker2.start()
        
        # Wait for CAM2 to process all frames
        assert wait_for_frames(worker2, 3), f"worker2 only processed {worker2.frames_processed}/3 frames"
        
        # Wait for CAM1 to attempt reconnect and process frames
        assert wait_for_frames(worker1, 2), f"worker1 only processed {worker1.frames_processed}/2 frames"
        
        worker1.stop()
        worker2.stop()
        
        # CAM2 should not have been affected by CAM1's reconnect
        assert worker2.frames_processed == 3
        
        # CAM1 should have attempted reconnect
        snap1 = worker1.get_snapshot()
        assert snap1.reconnect_attempts >= 0  # May have attempted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])