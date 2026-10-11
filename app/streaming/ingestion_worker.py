"""
Phase 44.1 — Camera Ingestion Worker.

Provides a production ingestion worker lifecycle for camera streams.
Uses the RTSPSource and StreamHealthMonitor with PyAV CUDA NVDEC.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.streaming.reconnect import ReconnectConfig, ReconnectPolicy, create_reconnect_manager
from app.streaming.rtsp_source import RTSPSource, RTSPSourceConfig, create_rtsp_source

logger = logging.getLogger(__name__)


class WorkerState(str, Enum):
    """Worker lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTING = "connecting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"


@dataclass(frozen=True)
class CameraIngestionConfig:
    """Configuration for a camera ingestion worker."""
    camera_id: str
    rtsp_url: str
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    decoder: str = "pyav_nvdec"
    nvdec_gpu_device: int = 0
    use_pts: bool = True
    max_queue_size: int = 10
    # CAMERA OPEN TIMEOUT = exactly 10 seconds (PART C requirement)
    timeout: float = 10.0
    retry_interval: float = 5.0
    max_retries: int = 3
    reconnect_policy: ReconnectPolicy = ReconnectPolicy.EXPONENTIAL_BACKOFF
    reconnect_max_retries: int = 5
    reconnect_base_interval: float = 2.0
    reconnect_max_interval: float = 60.0
    reconnect_backoff_multiplier: float = 2.0
    reconnect_jitter: float = 0.1
    health_stale_threshold: float = 5.0
    health_degraded_threshold: float = 2.0
    health_frame_timeout: float = 10.0
    health_max_consecutive_missing: int = 30
    # Phase 44.X.4-R3.3 capture watchdog configuration.
    stall_timeout_seconds: float = 6.0
    capture_worker_join_timeout: float = 3.0
    capture_min_teardown_interval_seconds: float = 1.0
    capture_max_consecutive_teardowns: int = 5
    capture_teardown_backoff_seconds: float = 2.0
    # Internal: whether to use the supervised RTSP source with watchdog.
    # Default False preserves legacy test behavior; production opts in
    # via CameraIngestionConfig.from_settings().
    use_supervised_source: bool = False
    
    @classmethod
    def from_settings(cls, settings, camera_id: str) -> "CameraIngestionConfig":
        """Create config from settings for CAM1 or CAM2."""
        cameras = settings.cameras
        
        if camera_id == "CAM1":
            rtsp_url = cameras.get_cam1_rtsp_url()
            enabled = cameras.cam1_enabled
        elif camera_id == "CAM2":
            rtsp_url = cameras.get_cam2_rtsp_url()
            enabled = cameras.cam2_enabled
        else:
            raise ValueError(f"Unknown camera_id: {camera_id}")
        
        reconnect_config = cameras.to_reconnect_config()
        stale, degraded = cameras.to_health_monitor_config()
        
        return cls(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            expected_codec=cameras.expected_codec,
            expected_width=cameras.expected_width,
            expected_height=cameras.expected_height,
            expected_fps=cameras.expected_fps,
            decoder=cameras.decoder_backend,
            nvdec_gpu_device=cameras.nvdec_gpu_device,
            # CAMERA OPEN TIMEOUT = exactly 10 seconds
            timeout=10.0,
            max_retries=cameras.reconnect_max_retries,
            retry_interval=cameras.reconnect_base_interval,
            reconnect_policy=reconnect_config.policy,
            reconnect_max_retries=reconnect_config.max_retries,
            reconnect_base_interval=reconnect_config.base_interval,
            reconnect_max_interval=reconnect_config.max_interval,
            reconnect_backoff_multiplier=reconnect_config.backoff_multiplier,
            reconnect_jitter=reconnect_config.jitter,
            health_stale_threshold=stale,
            health_degraded_threshold=degraded,
            health_frame_timeout=cameras.reconnect_max_interval,
            use_supervised_source=True,
        )
    
    def to_rtsp_source_config(self, cameras_config=None) -> "RTSPSourceConfig":
        """Convert to RTSPSourceConfig."""
        from app.streaming.rtsp_source import RTSPSourceConfig
        
        # Use cameras_config if provided, otherwise fallback to defaults
        if cameras_config is not None:
            readiness_check_enabled = cameras_config.readiness_check_enabled
            readiness_timeout = cameras_config.readiness_timeout
            readiness_poll_interval = cameras_config.readiness_poll_interval
            min_bytes_progress_interval = cameras_config.min_bytes_progress_interval
            consecutive_bytes_increases_required = cameras_config.consecutive_bytes_increases_required
        else:
            readiness_check_enabled = True
            readiness_timeout = 30.0
            readiness_poll_interval = 1.0
            min_bytes_progress_interval = 5.0
            consecutive_bytes_increases_required = 3
        
        return RTSPSourceConfig(
            camera_id=self.camera_id,
            rtsp_url=self.rtsp_url,
            use_pts=self.use_pts,
            max_queue_size=self.max_queue_size,
            timeout=self.timeout,
            retry_interval=self.retry_interval,
            max_retries=self.max_retries,
            expected_codec=self.expected_codec,
            expected_width=self.expected_width,
            expected_height=self.expected_height,
            expected_fps=self.expected_fps,
            decoder=self.decoder,
            nvdec_gpu_device=self.nvdec_gpu_device,
        )
    
    def to_reconnect_config(self) -> ReconnectConfig:
        """Convert to ReconnectConfig."""
        return ReconnectConfig(
            policy=self.reconnect_policy,
            max_retries=self.reconnect_max_retries,
            base_interval=self.reconnect_base_interval,
            max_interval=self.reconnect_max_interval,
            backoff_multiplier=self.reconnect_backoff_multiplier,
            jitter=self.reconnect_jitter,
        )


@dataclass
class WorkerSnapshot:
    """Snapshot of worker state."""
    camera_id: str
    state: WorkerState
    frames_processed: int = 0
    frames_reported: int = 0
    reconnect_attempts: int = 0
    last_frame_time: Optional[float] = None
    last_frame_timestamp: Optional[float] = None
    last_error: Optional[str] = None
    last_error_time: Optional[str] = None
    uptime_seconds: float = 0.0
    resolution: Optional[tuple] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    capture_watchdog: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "state": self.state.value,
            "frames_processed": self.frames_processed,
            "frames_reported": self.frames_reported,
            "reconnect_attempts": self.reconnect_attempts,
            "last_frame_time": self.last_frame_time,
            "last_frame_timestamp": self.last_frame_timestamp,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
            "uptime_seconds": self.uptime_seconds,
            "resolution": list(self.resolution) if self.resolution else None,
            "fps": self.fps,
            "codec": self.codec,
            "capture_watchdog": self.capture_watchdog,
        }


class CameraIngestionWorker:
    """
    Camera ingestion worker lifecycle.

    Represents one camera ingestion pipeline:
    MediaMTX → RTMP (camera) → RTSP (AI) → RTSPSource → CameraIngestionWorker → CanonicalFrame → StreamHealthMonitor
    
    Features:
    - Per-camera isolation (no cross-camera state contamination)
    - Clean start/stop lifecycle
    - Frame consumption with health reporting
    - Timeout detection (no 100% CPU spin)
    - Reconnect with bounded exponential backoff
    - Thread-safe operation
    """
    
    def __init__(
        self,
        config: CameraIngestionConfig,
        health_monitor: Optional[StreamHealthMonitor] = None,
        frame_callback: Optional[Callable[[CanonicalFrame], None]] = None,
        time_func: Callable[[], float] = time.time,
        sleep_func: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.camera_id = config.camera_id
        self._frame_callback = frame_callback
        self._time_func = time_func
        self._sleep_func = sleep_func
        
        # Health monitor
        self._health_monitor = health_monitor or create_health_monitor(
            stale_threshold_seconds=config.health_stale_threshold,
            degraded_threshold_seconds=config.health_degraded_threshold,
            frame_timeout_seconds=config.health_frame_timeout,
            max_consecutive_missing_frames=config.health_max_consecutive_missing,
        )
        
        # RTSPSource
        self._source: Optional[RTSPSource] = None
        
        # Reconnect manager
        self._reconnect_manager = create_reconnect_manager(
            camera_id=self.camera_id,
            connect_func=self._attempt_connect,
            config=config.to_reconnect_config(),
            on_state_change=self._on_reconnect_state_change,
        )
        
        # Worker state
        self._state = WorkerState.STOPPED
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        
        # Metrics
        self._frames_processed = 0
        self._frames_reported = 0
        self._last_frame_time: Optional[float] = None
        self._last_frame_timestamp: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[str] = None
        self._resolution: Optional[tuple] = None
        self._fps: Optional[float] = None
        self._codec: Optional[str] = None
        
        # Register camera in health monitor
        self._health_monitor.register_camera(self.camera_id)
    
    @property
    def state(self) -> WorkerState:
        with self._state_lock:
            return self._state
    
    @property
    def is_running(self) -> bool:
        return self.state == WorkerState.RUNNING
    
    @property
    def is_stopped(self) -> bool:
        return self.state == WorkerState.STOPPED
    
    @property
    def frames_processed(self) -> int:
        return self._frames_processed
    
    @property
    def frames_reported(self) -> int:
        return self._frames_reported
    
    def _set_state(self, new_state: WorkerState) -> None:
        with self._state_lock:
            if self._state != new_state:
                logger.info(f"Worker {self.camera_id}: {self._state.value} -> {new_state.value}")
                self._state = new_state
    
    def _attempt_connect(self) -> bool:
        """Attempt to connect to RTMP source."""
        try:
            if self._source:
                self._source.close()

            # Use RTSP source with PyAV NVDEC decoder
            from app.config.settings import load_settings
            settings = load_settings()
            rtsp_config = self.config.to_rtsp_source_config(cameras_config=settings.cameras)
            self._source = create_rtsp_source(
                camera_id=rtsp_config.camera_id,
                rtsp_url=rtsp_config.rtsp_url,
                expected_codec=rtsp_config.expected_codec,
                expected_width=rtsp_config.expected_width,
                expected_height=rtsp_config.expected_height,
                expected_fps=rtsp_config.expected_fps,
                decoder=rtsp_config.decoder,
                nvdec_gpu_device=rtsp_config.nvdec_gpu_device,
            )

            info = self._source.open()
            self._resolution = (info.width, info.height)
            self._fps = info.fps if info.fps > 0 else self.config.expected_fps
            self._codec = self.config.expected_codec

            logger.info(f"Worker {self.camera_id}: Connected to {self.config.rtsp_url}")
            return True
        except Exception as e:
            logger.error(f"Worker {self.camera_id}: Connection failed: {e}")
            self._last_error = str(e)
            self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return False

    def _on_reconnect_state_change(self, state) -> None:
        """Handle reconnect state changes."""
        if state.value == "success":
            self._set_state(WorkerState.RUNNING)
            self._health_monitor.update_reconnect_success(self.camera_id)
        elif state.value == "failed" or state.value == "exhausted":
            self._set_state(WorkerState.STOPPED)
            self._health_monitor.update_reconnect_failed(self.camera_id, self._reconnect_manager.last_error or "Unknown")
        elif state.value in ("connecting", "waiting", "retrying"):
            self._set_state(WorkerState.RECONNECTING)
            self._health_monitor.update_reconnect(self.camera_id, self._reconnect_manager.attempt_count)
    
    def start(self) -> bool:
        """Start the ingestion worker."""
        with self._state_lock:
            if self._state != WorkerState.STOPPED:
                logger.warning(f"Worker {self.camera_id}: Already running or starting")
                return False
            
            self._set_state(WorkerState.STARTING)
            self._stop_event.clear()
            
            # Start in background thread
            self._worker_thread = threading.Thread(
                target=self._run_loop,
                name=f"ingestion-{self.camera_id}",
                daemon=True,
            )
            self._worker_thread.start()
            
            self._start_time = self._time_func()
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """Stop the ingestion worker cleanly."""
        with self._state_lock:
            if self._state == WorkerState.STOPPED:
                return True
            
            self._set_state(WorkerState.STOPPING)
            self._stop_event.set()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            
            if self._worker_thread.is_alive():
                logger.error(f"Worker {self.camera_id}: Failed to stop within timeout")
                return False
        
        if self._source:
            self._source.close()
            self._source = None
        
        self._reconnect_manager.reset()
        self._health_monitor.unregister_camera(self.camera_id)
        
        with self._state_lock:
            self._state = WorkerState.STOPPED
        
        logger.info(f"Worker {self.camera_id}: Stopped")
        return True
    
    def _run_loop(self) -> None:
        """Main worker loop."""
        try:
            # Initial connection
            self._set_state(WorkerState.CONNECTING)
            if not self._attempt_connect():
                self._handle_connection_failure()
                return
            
            self._set_state(WorkerState.RUNNING)
            self._health_monitor.register_camera(self.camera_id)
            
            # Frame consumption loop
            self._consume_frames()
            
        except Exception as e:
            logger.error(f"Worker {self.camera_id}: Unexpected error: {e}")
            self._last_error = str(e)
            self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        finally:
            self._cleanup()
    
    def _consume_frames(self) -> None:
        """Consume frames from RTMP source."""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while not self._stop_event.is_set():
            try:
                if not self._source or not getattr(self._source, "is_opened", True):
                    if not self._stop_event.is_set():
                        logger.warning(
                            f"Worker {self.camera_id}: Source closed, attempting reconnect"
                        )
                        self._trigger_reconnect()
                    break

                # Get next frame with timeout awareness
                try:
                    frame = self._get_frame_with_timeout()
                except Exception as e:
                    logger.warning(
                        f"Worker {self.camera_id}: frame error; reconnecting"
                    )
                    self._last_error = str(e)
                    self._last_error_time = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                    )
                    self._health_monitor.update_error(
                        self.camera_id, self._last_error
                    )
                    if self._attempt_reconnect_with_backoff():
                        continue
                    break

                if frame is None:
                    # No frame available, check if we should continue
                    if self._stop_event.is_set():
                        break
                    continue

                # Process frame
                self._process_frame(frame)
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Worker {self.camera_id}: Error in consume loop: {e}")
                self._last_error = str(e)
                self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._health_monitor.update_error(self.camera_id, str(e))

                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Worker {self.camera_id}: Too many consecutive errors, triggering reconnect")
                    self._trigger_reconnect()
                    consecutive_errors = 0

    def _attempt_reconnect_with_backoff(self) -> bool:
        """
        After an error, sleep with backoff and reconnect to the same
        RTMP source. Preserves camera_id and reconnects the same URL.
        Returns True on success.
        """
        logger.info(
            "[H2K][RECONNECT_START] camera=%s reconnect_count=%d timestamp=%.6f",
            self.camera_id,
            self._reconnect_manager.attempt_count + 1,
            time.time(),
        )
        
        backoff = self.config.reconnect_base_interval
        for attempt in range(1, self.config.reconnect_max_retries + 1):
            if self._stop_event.is_set():
                return False
            self._sleep_func(backoff)
            if self._attempt_connect():
                logger.info(
                    "[H2K][RECONNECT_RESULT] camera=%s result=True reconnect_count=%d timestamp=%.6f",
                    self.camera_id,
                    attempt,
                    time.time(),
                )
                return True
            backoff = min(
                backoff * self.config.reconnect_backoff_multiplier,
                self.config.reconnect_max_interval,
            )
        logger.info(
            "[H2K][RECONNECT_RESULT] camera=%s result=False reconnect_count=%d timestamp=%.6f",
            self.camera_id,
            self.config.reconnect_max_retries,
            time.time(),
        )
        logger.error(
            f"Worker {self.camera_id}: failed to reconnect after stall "
            f"({self.config.reconnect_max_retries} attempts)"
        )
        return False
    
    def _get_frame_with_timeout(self) -> Optional[CanonicalFrame]:
        """Get next frame with timeout to avoid busy waiting."""
        # Use the source's get_next_frame which handles its own timeout
        if self._source:
            return self._source.get_next_frame()
        return None
    
    def _process_frame(self, frame: CanonicalFrame) -> None:
        """Process a received frame."""
        current_time = self._time_func()
        
        logger.info(
            "[H2K][CANONICAL_FRAME] camera=%s timestamp=%.6f frame_index=%d width=%d height=%d",
            self.camera_id,
            current_time,
            frame.metadata.frame_index,
            frame.metadata.original_width,
            frame.metadata.original_height,
        )
        
        self._frames_processed += 1
        self._last_frame_time = current_time
        self._last_frame_timestamp = frame.metadata.timestamp
        
        # Update health monitor — minimal runtime evidence (no synthetic/mock/replay; adapter_contract identity preserved)
        payload_type = str(type(frame.data).__name__)
        payload_is_dict = isinstance(frame.data, dict)
        payload_has_nbytes = hasattr(frame.data, "nbytes")
        adapter_contract_ref = getattr(frame.data, "adapter_contract", None) if payload_is_dict else None
        adapter_contract_type = type(adapter_contract_ref).__name__ if adapter_contract_ref is not None else "None"
        payload_nbytes = getattr(frame.data, "nbytes", 0) if payload_has_nbytes else 0
        logger.info(
            "[BOOT-GPU] IngestionWorker(%s) .nbytes context: payload_type=%s is_dict=%s has_nbytes=%s adapter_contract_present=%s adapter_contract_type=%s payload_nbytes=%d",
            self.camera_id,
            payload_type,
            payload_is_dict,
            payload_has_nbytes,
            adapter_contract_ref is not None,
            adapter_contract_type,
            payload_nbytes,
        )
        frame_size = payload_nbytes
        resolution = (frame.width, frame.height)
        fps = frame.metadata.source_fps or self._fps
        codec = frame.metadata.pixel_format.value if frame.metadata.pixel_format else self._codec
        
        # Get decoder backend from frame metadata
        decoder_backend = frame.metadata.extra.get("decoder", self.config.decoder) if frame.metadata.extra else self.config.decoder
        
        self._health_monitor.update_frame_received(
            camera_id=self.camera_id,
            frame_index=self._frames_processed,
            timestamp=frame.metadata.timestamp,
            frame_size=frame_size,
            resolution=resolution,
            fps=fps,
            codec=codec,
            current_time=current_time,
            decoder_backend=decoder_backend,
        )
        
        self._frames_reported += 1
        
        # Call frame callback if provided
        if self._frame_callback:
            try:
                self._frame_callback(frame)
            except Exception as e:
                logger.error(f"Worker {self.camera_id}: Frame callback error: {e}")
    
    def _handle_connection_failure(self) -> None:
        """Handle initial connection failure."""
        self._trigger_reconnect()
        
        # Wait for reconnect or stop
        while not self._stop_event.is_set():
            if self._reconnect_manager.is_success:
                self._set_state(WorkerState.RUNNING)
                self._consume_frames()
                break
            elif self._reconnect_manager.is_exhausted:
                logger.error(f"Worker {self.camera_id}: Reconnect exhausted")
                break
            
            self._sleep_func(0.1)
    
    def _trigger_reconnect(self) -> None:
        """Trigger reconnection."""
        if self._state == WorkerState.RUNNING:
            self._set_state(WorkerState.RECONNECTING)
        
        self._reconnect_manager.attempt_reconnect()
    
    def _cleanup(self) -> None:
        """Cleanup resources."""
        if self._source:
            self._source.close()
            self._source = None
    
    def get_snapshot(self) -> WorkerSnapshot:
        """Get current worker snapshot."""
        with self._state_lock:
            uptime = 0.0
            if self._start_time:
                uptime = self._time_func() - self._start_time

            snap = WorkerSnapshot(
                camera_id=self.camera_id,
                state=self._state,
                frames_processed=self._frames_processed,
                frames_reported=self._frames_reported,
                reconnect_attempts=self._reconnect_manager.attempt_count,
                last_frame_time=self._last_frame_time,
                last_frame_timestamp=self._last_frame_timestamp,
                last_error=self._last_error,
                last_error_time=self._last_error_time,
                uptime_seconds=uptime,
                resolution=self._resolution,
                fps=self._fps,
                codec=self._codec,
            )
            # Attach watchdog metrics if the source exposes them.
            if self._source is not None and hasattr(self._source, "watchdog_metrics"):
                snap.capture_watchdog = self._source.watchdog_metrics
            return snap
    
    def get_health_result(self):
        """Get health check result for this camera."""
        return self._health_monitor.check_health(self.camera_id, current_time=self._time_func())


def create_camera_ingestion_worker(
    camera_id: str,
    settings=None,
    health_monitor: Optional[StreamHealthMonitor] = None,
    frame_callback: Optional[Callable[[CanonicalFrame], None]] = None,
) -> CameraIngestionWorker:
    """Factory function to create a camera ingestion worker."""
    if settings is None:
        settings = load_settings()
    
    config = CameraIngestionConfig.from_settings(settings, camera_id)
    
    return CameraIngestionWorker(
        config=config,
        health_monitor=health_monitor,
        frame_callback=frame_callback,
    )


def create_cam1_worker(
    settings=None,
    health_monitor: Optional[StreamHealthMonitor] = None,
    frame_callback: Optional[Callable[[CanonicalFrame], None]] = None,
) -> CameraIngestionWorker:
    """Create worker for CAM1."""
    return create_camera_ingestion_worker("CAM1", settings, health_monitor, frame_callback)


def create_cam2_worker(
    settings=None,
    health_monitor: Optional[StreamHealthMonitor] = None,
    frame_callback: Optional[Callable[[CanonicalFrame], None]] = None,
) -> CameraIngestionWorker:
    """Create worker for CAM2."""
    return create_camera_ingestion_worker("CAM2", settings, health_monitor, frame_callback)