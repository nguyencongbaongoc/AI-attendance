"""
Phase 11.2 — Camera Runtime Manager.

Provides a deterministic, lifecycle-aware runtime orchestrator for camera streams.
Manages per-camera isolation, readiness verification, retry/reconnect, and graceful shutdown.

State Machine:
    STOPPED
        ↓
    STARTING
        ↓
    CONNECTING
        ↓
    DECODING
        ↓
    FIRST_GPU_FRAME
        ↓
    READY
        ↓
    RUNNING

Failure:
    STARTING/CONNECTING/DECODING/FIRST_GPU_FRAME
        ↓
    FAILED
        ↓
    RESTARTING (if retry enabled)
        ↓
    CONNECTING
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.streaming.reconnect import ReconnectConfig, ReconnectPolicy, create_reconnect_manager
from app.streaming.ingestion_worker import CameraIngestionWorker, CameraIngestionConfig, create_camera_ingestion_worker, WorkerState
from app.streaming.detection_pipeline import DetectionPipeline, DetectionPipelineConfig, create_detection_pipeline
from app.streaming.annotated_publisher import AnnotatedFramePublisher, AnnotatedPublisherConfig, create_annotated_publisher
from app.streaming.metadata_broadcaster import get_metadata_broadcaster, FrameMetadata, FaceMetadata, PersonMetadata, CrossingLineMetadata
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract
from app.vision.gpu_ai_bridge import GPUAIBridge, GPUAIInput, GPUAIOutput
from app.vision.tracking_attendance_telemetry import TrackingAttendanceProcessor, EndToEndTelemetry

logger = logging.getLogger(__name__)


class CameraRuntimeState(str, Enum):
    """Camera runtime lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTING = "connecting"
    DECODING = "decoding"
    FIRST_GPU_FRAME = "first_gpu_frame"
    READY = "ready"
    RUNNING = "running"
    FAILED = "failed"
    RESTARTING = "restarting"
    STOPPING = "stopping"


@dataclass(frozen=True)
class CameraRuntimeConfig:
    """Configuration for camera runtime manager."""
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
    stall_timeout_seconds: float = 6.0
    capture_worker_join_timeout: float = 3.0
    capture_min_teardown_interval_seconds: float = 1.0
    capture_max_consecutive_teardowns: int = 5
    capture_teardown_backoff_seconds: float = 2.0
    use_supervised_source: bool = True
    
    # Publisher config
    publisher_fps: float = 15.0
    publisher_enable_gpu_annotation: bool = True
    publisher_gpu_annotation_font_path: str = "C:/Windows/Fonts/arial.ttf"
    publisher_gpu_annotation_font_size: int = 48
    publisher_encoder_codec: str = "h264"
    publisher_encoder_preset: str = "P4"
    publisher_encoder_bitrate_kbps: int = 8000
    publisher_encoder_max_bitrate_kbps: int = 12000
    publisher_encoder_gop_length: int = 30
    publisher_encoder_idr_period: int = 60
    publisher_encoder_cuda_stream: int = 0
    
    # Detection config
    detection_confidence_threshold: float = 0.5
    detection_nms_threshold: float = 0.4
    detection_enable_crossing: bool = True
    detection_enable_attendance: bool = True
    detection_enable_policy: bool = True
    detection_enable_notification: bool = True

    @classmethod
    def from_settings(cls, settings, camera_id: str) -> "CameraRuntimeConfig":
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


@dataclass
class CameraRuntimeSnapshot:
    """Snapshot of camera runtime state."""
    camera_id: str
    state: CameraRuntimeState
    ingestion_worker_state: Optional[str] = None
    detection_pipeline_running: bool = False
    publisher_started: bool = False
    frames_received: int = 0
    frames_processed: int = 0
    frames_published: int = 0
    first_gpu_frame_received: bool = False
    first_gpu_frame_time: Optional[float] = None
    reconnect_attempts: int = 0
    last_frame_time: Optional[float] = None
    last_error: Optional[str] = None
    last_error_time: Optional[str] = None
    uptime_seconds: float = 0.0
    resolution: Optional[tuple] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    publisher_metrics: Optional[Dict[str, Any]] = None
    detection_pipeline_frame_count: int = 0


class CameraRuntimeManager:
    """
    Manages the complete lifecycle of a camera runtime.
    
    Responsibilities:
    - Ingestion worker lifecycle (RTSP -> NVDEC -> CanonicalFrame)
    - Detection pipeline lifecycle (Person/Face detection -> Tracking -> Association -> Crossing -> Attendance)
    - Annotated publisher lifecycle (GPU annotation -> Native NVENC -> RTSP -> MediaMTX)
    - Readiness verification (first valid GPU frame received)
    - Retry/reconnect with clean resource lifecycle
    - Per-camera isolation (no shared state between cameras)
    - Structured logging for diagnostics
    """
    
    def __init__(
        self,
        config: CameraRuntimeConfig,
        health_monitor: Optional[StreamHealthMonitor] = None,
        health_event_callback: Optional[Callable] = None,
        time_func: Callable[[], float] = time.time,
        sleep_func: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.camera_id = config.camera_id
        self._health_monitor = health_monitor
        self._health_event_callback = health_event_callback
        self._time_func = time_func
        self._sleep_func = sleep_func
        
        # Components
        self._ingestion_worker: Optional[CameraIngestionWorker] = None
        self._detection_pipeline: Optional[DetectionPipeline] = None  # Legacy, kept for backward compatibility
        self._gpu_ai_bridge: Optional[GPUAIBridge] = None
        self._tracking_processor: Optional[TrackingAttendanceProcessor] = None
        self._telemetry: Optional[EndToEndTelemetry] = None
        self._annotated_publisher: Optional[AnnotatedFramePublisher] = None
        
        # State machine
        self._state = CameraRuntimeState.STOPPED
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._manager_thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        
        # Metrics
        self._frames_received = 0
        self._frames_processed = 0
        self._frames_published = 0
        self._first_gpu_frame_received = False
        self._first_gpu_frame_time: Optional[float] = None
        self._reconnect_attempts = 0
        self._last_frame_time: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[str] = None
        self._resolution: Optional[tuple] = None
        self._fps: Optional[float] = None
        self._codec: Optional[str] = None
        
        # Frame callback chain: ingestion -> detection -> publisher
        self._frame_callback_chain: List[Callable[[CanonicalFrame], None]] = []
        
        logger.info(f"[BOOT] CameraRuntimeManager({self.camera_id}): initialized")

    @property
    def state(self) -> CameraRuntimeState:
        with self._state_lock:
            return self._state

    @property
    def is_ready(self) -> bool:
        return self._state in (CameraRuntimeState.READY, CameraRuntimeState.RUNNING)

    @property
    def is_running(self) -> bool:
        return self._state == CameraRuntimeState.RUNNING

    @property
    def is_stopped(self) -> bool:
        return self._state == CameraRuntimeState.STOPPED

    @property
    def is_failed(self) -> bool:
        return self._state == CameraRuntimeState.FAILED

    def _set_state(self, new_state: CameraRuntimeState) -> None:
        with self._state_lock:
            if self._state != new_state:
                old_state = self._state
                self._state = new_state
                logger.info(f"[BOOT] {self.camera_id}: {old_state.value} -> {new_state.value}")
                
                if new_state == CameraRuntimeState.READY:
                    self._ready_event.set()
                elif new_state in (CameraRuntimeState.STOPPED, CameraRuntimeState.FAILED):
                    self._ready_event.clear()

    def _build_frame_callback_chain(self) -> Callable[[CanonicalFrame], None]:
        """Build the frame processing callback chain."""
        def frame_callback(frame: CanonicalFrame) -> None:
            current_time = self._time_func()
            self._frames_received += 1
            self._last_frame_time = current_time
            
            # Convert PyAV frame dict to GPUFrameContract for GPU-native pipeline
            gpu_frame_contract = None
            if isinstance(frame.data, dict) and "y_plane" in frame.data and "uv_plane" in frame.data:
                try:
                    gpu_frame_contract = GPUFrameContract.from_pyav_frame_data(
                        frame_data=frame.data,
                        frame_id=self._frames_received,
                        camera_id=self.camera_id,
                        timestamp=frame.metadata.timestamp,
                        pts=frame.metadata.extra.get("pts", self._frames_received) if frame.metadata.extra else self._frames_received,
                        cuda_stream=0,
                    )
                    # Replace frame.data with GPUFrameContract for downstream consumers
                    frame.data = gpu_frame_contract
                except Exception as e:
                    logger.error(f"[BOOT] {self.camera_id}: GPUFrameContract conversion failed: {e}")
                    self._last_error = str(e)
                    self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            # Check for first valid GPU frame
            if not self._first_gpu_frame_received:
                # Verify frame has GPU data (NV12 CUDA tensors)
                if self._is_valid_gpu_frame(frame):
                    self._first_gpu_frame_received = True
                    self._first_gpu_frame_time = current_time
                    self._resolution = (frame.width, frame.height)
                    self._fps = frame.metadata.source_fps or self.config.expected_fps
                    self._codec = frame.metadata.pixel_format.value if frame.metadata.pixel_format else self.config.expected_codec
                    
                    logger.info(
                        f"[BOOT] {self.camera_id}: FIRST_GPU_FRAME received "
                        f"(frame={self._frames_received}, width={frame.width}, height={frame.height}, "
                        f"fps={self._fps}, codec={self._codec})"
                    )
                    
                    # Transition from FIRST_GPU_FRAME to READY
                    if self._state == CameraRuntimeState.FIRST_GPU_FRAME:
                        self._set_state(CameraRuntimeState.READY)
            
            # Process through GPU AI Bridge (zero-copy inference)
            if self._gpu_ai_bridge and self._gpu_ai_bridge._initialized:
                try:
                    # frame.data should now be GPUFrameContract after conversion above
                    # Pass the full CanonicalFrame (which has GPUFrameContract in .data and metadata in .metadata)
                    if frame is None or frame.metadata is None:
                        logger.warning(f"[BOOT] {self.camera_id}: Invalid frame (None or missing metadata)")
                    elif isinstance(frame.data, GPUFrameContract):
                        gpu_input = GPUAIInput(
                            gpu_frame=frame.data,
                            camera_id=self.camera_id,
                            frame_index=self._frames_received,
                            timestamp=frame.metadata.timestamp,
                        )
                        
                        # Run zero-copy GPU inference
                        try:
                            ai_output: GPUAIOutput = self._gpu_ai_bridge.process_frame(gpu_input)
                        except Exception as e:
                            logger.error(f"[BOOT] {self.camera_id}: GPU AI Bridge inference error: {e}")
                            raise
                        
                        # Process through tracking and attendance
                        tracking_result = None
                        if self._tracking_processor:
                            try:
                                # Pass the GPUFrameContract (frame.data) to tracking processor
                                tracking_result = self._tracking_processor.process(
                                    ai_output, frame.data, ai_output.t_ai_inference_done_ns
                                )
                            except Exception as e:
                                import traceback
                                logger.error(f"[BOOT] {self.camera_id}: Tracking processor error: {e}\n{traceback.format_exc()}")
                                tracking_result = None
                        
                        # Broadcast metadata to WebSocket clients (non-blocking)
                        try:
                            self._broadcast_metadata(frame, ai_output, tracking_result)
                        except Exception as e:
                            logger.warning(f"[BOOT] {self.camera_id}: Metadata broadcast error: {e}")
                        
                        # Record telemetry
                        if self._telemetry:
                            try:
                                timestamps = {
                                    't_packet_ingress_ns': int(frame.metadata.timestamp * 1_000_000_000),
                                    't_decode_submit_ns': int(frame.metadata.timestamp * 1_000_000_000),
                                    't_gpu_frame_ready_ns': ai_output.t_ai_preprocess_start_ns,
                                    't_pipeline_egress_ns': ai_output.t_ai_inference_done_ns,
                                    't_ai_preprocess_start_ns': ai_output.t_ai_preprocess_start_ns,
                                    't_ai_inference_start_ns': ai_output.t_ai_inference_start_ns,
                                    't_ai_inference_done_ns': ai_output.t_ai_inference_done_ns,
                                    't_tracking_start_ns': getattr(tracking_result, 't_tracking_start_ns', 0) if tracking_result else 0,
                                    't_tracking_done_ns': getattr(tracking_result, 't_tracking_done_ns', 0) if tracking_result else 0,
                                    't_crossing_done_ns': getattr(tracking_result, 't_crossing_done_ns', 0) if tracking_result else 0,
                                    't_attendance_persisted_ns': getattr(tracking_result, 't_attendance_persisted_ns', 0) if tracking_result else 0,
                                }
                                vram = self._gpu_ai_bridge.get_vram_report()
                                self._telemetry.record_frame(timestamps, 
                                    vram_allocated_mb=vram.get('allocated_mb', 0),
                                    vram_reserved_mb=vram.get('reserved_mb', 0))
                            except Exception as e:
                                logger.error(f"[BOOT] {self.camera_id}: Telemetry recording error: {e}")
                        
                        self._frames_processed += 1
                    else:
                        logger.warning(f"[BOOT] {self.camera_id}: Frame data not GPUFrameContract: {type(frame.data)}")
                except Exception as e:
                    logger.error(f"[BOOT] {self.camera_id}: GPU AI Bridge error: {e}")
                    self._last_error = str(e)
                    self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            # Update health monitor
            if self._health_monitor:
                try:
                    payload_type = str(type(frame.data).__name__)
                    payload_is_dict = isinstance(frame.data, dict)
                    payload_has_nbytes = hasattr(frame.data, "nbytes")
                    adapter_contract_ref = getattr(frame.data, "adapter_contract", None) if payload_is_dict else None
                    adapter_contract_type = type(adapter_contract_ref).__name__ if adapter_contract_ref is not None else "None"
                    payload_nbytes = getattr(frame.data, "nbytes", 0) if payload_has_nbytes else 0
                    frame_size = payload_nbytes
                    resolution = (frame.width, frame.height)
                    fps = frame.metadata.source_fps or self._fps
                    codec = frame.metadata.pixel_format.value if frame.metadata.pixel_format else self._codec
                    
                    self._health_monitor.update_frame_received(
                        camera_id=self.camera_id,
                        frame_index=self._frames_received,
                        timestamp=frame.metadata.timestamp,
                        frame_size=frame_size,
                        resolution=resolution,
                        fps=fps,
                        codec=codec,
                        current_time=current_time,
                    )
                except Exception as e:
                    logger.warning(f"[BOOT] {self.camera_id}: Health monitor update failed: {e}")
        
        return frame_callback

    def _is_valid_gpu_frame(self, frame: CanonicalFrame) -> bool:
        """Verify frame has valid GPU-resident data."""
        if frame.data is None:
            return False
        
        # Check for CUDA tensor or GPUFrameContract
        if hasattr(frame.data, "nbytes") and frame.data.nbytes > 0:
            return True
        
        # Check for dict with adapter_contract (GPUFrameContract)
        if isinstance(frame.data, dict):
            adapter = frame.data.get("adapter_contract")
            if adapter is not None and hasattr(adapter, "cuda_memory_ref"):
                return True
        
        # Check for GPUFrameContract object directly
        if hasattr(frame.data, "get_tensors"):
            return True
        
        return False

    def _broadcast_metadata(self, frame: CanonicalFrame, ai_output: GPUAIOutput, tracking_result: Any) -> None:
        """
        Broadcast detection/tracking metadata to WebSocket clients.
        
        Non-blocking - uses asyncio.create_task to avoid blocking the AI pipeline.
        """
        import asyncio
        
        # Extract faces from tracking result
        faces = []
        persons = []
        crossing_line = None
        
        if tracking_result:
            # Get face tracks with identities
            if hasattr(tracking_result, 'face_tracks'):
                for track_id, track in tracking_result.face_tracks.items():
                    if hasattr(track, 'bbox') and hasattr(track, 'identity_name'):
                        faces.append(FaceMetadata(
                            track_id=track_id,
                            bbox=list(track.bbox) if track.bbox else [0, 0, 0, 0],
                            name=track.identity_name or "Unknown",
                            confidence=track.identity_confidence or 0.0,
                        ))
            
            # Get person tracks
            if hasattr(tracking_result, 'person_tracks'):
                for track_id, track in tracking_result.person_tracks.items():
                    if hasattr(track, 'bbox'):
                        persons.append(PersonMetadata(
                            track_id=track_id,
                            bbox=list(track.bbox) if track.bbox else [0, 0, 0, 0],
                        ))
            
            # Get crossing line status
            if hasattr(tracking_result, 'crossing_line'):
                cl = tracking_result.crossing_line
                if cl:
                    crossing_line = CrossingLineMetadata(
                        coords=cl.coords if hasattr(cl, 'coords') else [[0.1, 0.5], [0.9, 0.5]],
                        status=cl.status if hasattr(cl, 'status') else "NORMAL",
                    )
        
        # Create metadata packet
        metadata = FrameMetadata(
            camera_id=self.camera_id,
            frame_sequence=self._frames_received,
            pts_ns=int(frame.metadata.timestamp * 1_000_000_000) if frame.metadata else 0,
            capture_timestamp=time.strftime("%Y-%m-%dT%H:%M:%S.%fZ", time.gmtime()),
            faces=faces,
            persons=persons,
            crossing_line=crossing_line,
        )
        
        # Non-blocking broadcast via asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                broadcaster = get_metadata_broadcaster()
                loop.create_task(broadcaster.broadcast_metadata(self.camera_id, metadata))
            else:
                logger.debug(f"[BOOT] {self.camera_id}: No running event loop for metadata broadcast")
        except RuntimeError:
            # No event loop in this thread
            logger.debug(f"[BOOT] {self.camera_id}: No event loop available for metadata broadcast")
        except Exception as e:
            logger.warning(f"[BOOT] {self.camera_id}: Metadata broadcast failed: {e}")

    def start(self, wait_ready: bool = True, ready_timeout: float = 120.0) -> bool:
        """Start the camera runtime and optionally wait for READY state."""
        with self._state_lock:
            if self._state != CameraRuntimeState.STOPPED:
                logger.warning(f"[BOOT] {self.camera_id}: Already running or starting (state={self._state.value})")
                return False
            
            self._set_state(CameraRuntimeState.STARTING)
            self._stop_event.clear()
            self._ready_event.clear()
            self._start_time = self._time_func()
        
        logger.info(f"[BOOT] {self.camera_id}: Starting camera runtime...")
        
        try:
            # Create and start ingestion worker
            self._set_state(CameraRuntimeState.CONNECTING)
            logger.info(f"[BOOT] {self.camera_id}: Creating ingestion worker...")
            
            ingestion_config = CameraIngestionConfig(
                camera_id=self.config.camera_id,
                rtsp_url=self.config.rtsp_url,
                expected_codec=self.config.expected_codec,
                expected_width=self.config.expected_width,
                expected_height=self.config.expected_height,
                expected_fps=self.config.expected_fps,
                decoder=self.config.decoder,
                nvdec_gpu_device=self.config.nvdec_gpu_device,
                use_pts=self.config.use_pts,
                max_queue_size=self.config.max_queue_size,
                timeout=self.config.timeout,
                retry_interval=self.config.retry_interval,
                max_retries=self.config.max_retries,
                reconnect_policy=self.config.reconnect_policy,
                reconnect_max_retries=self.config.reconnect_max_retries,
                reconnect_base_interval=self.config.reconnect_base_interval,
                reconnect_max_interval=self.config.reconnect_max_interval,
                reconnect_backoff_multiplier=self.config.reconnect_backoff_multiplier,
                reconnect_jitter=self.config.reconnect_jitter,
                health_stale_threshold=self.config.health_stale_threshold,
                health_degraded_threshold=self.config.health_degraded_threshold,
                health_frame_timeout=self.config.health_frame_timeout,
                health_max_consecutive_missing=self.config.health_max_consecutive_missing,
                stall_timeout_seconds=self.config.stall_timeout_seconds,
                capture_worker_join_timeout=self.config.capture_worker_join_timeout,
                capture_min_teardown_interval_seconds=self.config.capture_min_teardown_interval_seconds,
                capture_max_consecutive_teardowns=self.config.capture_max_consecutive_teardowns,
                capture_teardown_backoff_seconds=self.config.capture_teardown_backoff_seconds,
                use_supervised_source=self.config.use_supervised_source,
            )
            
            self._ingestion_worker = CameraIngestionWorker(
                config=ingestion_config,
                health_monitor=self._health_monitor,
                frame_callback=self._build_frame_callback_chain(),
                time_func=self._time_func,
                sleep_func=self._sleep_func,
            )
            
            if not self._ingestion_worker.start():
                logger.error(f"[BOOT] {self.camera_id}: Failed to start ingestion worker")
                self._set_state(CameraRuntimeState.FAILED)
                return False
            
            logger.info(f"[BOOT] {self.camera_id}: Ingestion worker started")
            
            # Wait for ingestion worker to reach RUNNING state before proceeding
            self._set_state(CameraRuntimeState.DECODING)
            logger.info(f"[BOOT] {self.camera_id}: Waiting for ingestion worker RUNNING state...")
            
            # Wait for WorkerState.RUNNING with timeout
            # Must be >= PyAVNVDECDecoder max retry duration (~76s) to allow retries to complete
            worker_ready_timeout = 90.0
            worker_start_time = self._time_func()
            while self._time_func() - worker_start_time < worker_ready_timeout:
                if self._ingestion_worker.state == WorkerState.RUNNING:
                    logger.info(f"[BOOT] {self.camera_id}: Ingestion worker reached RUNNING state")
                    break
                self._sleep_func(0.1)
            else:
                logger.error(f"[BOOT] {self.camera_id}: Timeout waiting for ingestion worker RUNNING state (current: {self._ingestion_worker.state.value})")
                self._set_state(CameraRuntimeState.FAILED)
                return False
            
            # Wait for first GPU frame to be received
            logger.info(f"[BOOT] {self.camera_id}: Waiting for decoder to produce frames...")
            
            # Create GPU AI Bridge (replaces DetectionPipeline for GPU inference)
            self._set_state(CameraRuntimeState.FIRST_GPU_FRAME)
            logger.info(f"[BOOT] {self.camera_id}: Creating GPU AI Bridge...")
            
            self._gpu_ai_bridge = GPUAIBridge(
                device_id=self.config.nvdec_gpu_device,
                reuse_ortvalues=True,
                reuse_io_binding=True,
                no_unnecessary_sync=True,
            )
            
            if not self._gpu_ai_bridge.initialize():
                logger.error(f"[BOOT] {self.camera_id}: Failed to initialize GPU AI Bridge")
                self._set_state(CameraRuntimeState.FAILED)
                return False
            
            logger.info(f"[BOOT] {self.camera_id}: GPU AI Bridge initialized")
            
            # Create tracking and attendance processor
            logger.info(f"[BOOT] {self.camera_id}: Creating tracking & attendance processor...")
            
            from app.config.settings import load_settings
            from app.attendance.timetable import Timetable
            from app.attendance.policy import AttendancePolicy
            
            settings = load_settings()
            timetable = None
            attendance_policy = None
            try:
                timetable = Timetable.from_dict(settings.timetable.to_dict())
                attendance_policy = AttendancePolicy.from_dict(settings.attendance_policy.to_dict())
            except Exception as e:
                logger.warning(f"[BOOT] {self.camera_id}: Timetable/policy not loaded: {e}")
            
            self._tracking_processor = TrackingAttendanceProcessor(
                camera_id=self.config.camera_id,
                timetable=timetable,
                attendance_policy=attendance_policy,
            )
            
            logger.info(f"[BOOT] {self.camera_id}: Tracking & attendance processor created")
            
            # Create telemetry
            self._telemetry = EndToEndTelemetry(
                camera_id=self.config.camera_id,
                window_seconds=10.0,
                log_interval_seconds=10.0,
            )
            
            logger.info(f"[BOOT] {self.camera_id}: Telemetry initialized")
            
            # Create annotated publisher
            logger.info(f"[BOOT] {self.camera_id}: Creating annotated publisher...")
            
            publisher_config = AnnotatedPublisherConfig(
                camera_id=self.config.camera_id,
                rtsp_url=f"rtsp://localhost:8554/live/{self.config.camera_id.lower()}-ai",
                fps=self.config.publisher_fps,
                video_bitrate_kbps=self.config.publisher_encoder_bitrate_kbps,
                enable_gpu_annotation=self.config.publisher_enable_gpu_annotation,
                gpu_annotation_font_path=self.config.publisher_gpu_annotation_font_path,
                gpu_annotation_font_size=self.config.publisher_gpu_annotation_font_size,
                encoder_codec=self.config.publisher_encoder_codec,
                encoder_preset=self.config.publisher_encoder_preset,
                encoder_bitrate_kbps=self.config.publisher_encoder_bitrate_kbps,
                encoder_max_bitrate_kbps=self.config.publisher_encoder_max_bitrate_kbps,
                encoder_gop_length=self.config.publisher_encoder_gop_length,
                encoder_idr_period=self.config.publisher_encoder_idr_period,
                encoder_cuda_stream=self.config.publisher_encoder_cuda_stream,
            )
            
            self._annotated_publisher = AnnotatedFramePublisher(
                config=publisher_config,
                enable_liveness_watchdog=True,
            )
            
            if not self._annotated_publisher.start():
                logger.warning(f"[BOOT] {self.camera_id}: Annotated publisher failed to start (continuing without)")
            else:
                logger.info(f"[BOOT] {self.camera_id}: Annotated publisher started")
                # Wire up publisher to tracking processor (for annotated frames)
                if self._tracking_processor:
                    self._tracking_processor._annotated_publisher = self._annotated_publisher
            
            if wait_ready:
                logger.info(f"[BOOT] {self.camera_id}: Waiting for READY state (timeout={ready_timeout}s)...")
                ready = self._ready_event.wait(timeout=ready_timeout)
                if not ready:
                    current_state = self._state
                    logger.warning(f"[BOOT] {self.camera_id}: READY timeout after {ready_timeout}s (state={current_state.value})")
                    # Don't fail - let it continue to RUNNING if frames start arriving
                else:
                    logger.info(f"[BOOT] {self.camera_id}: READY state achieved")
            
            # Transition to RUNNING
            self._set_state(CameraRuntimeState.RUNNING)
            logger.info(f"[BOOT] {self.camera_id}: Camera runtime RUNNING")
            return True
            
        except Exception as e:
            logger.error(f"[BOOT] {self.camera_id}: Start failed: {e}")
            self._last_error = str(e)
            self._last_error_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._set_state(CameraRuntimeState.FAILED)
            return False

    def stop(self, timeout: float = 15.0) -> bool:
        """Stop the camera runtime cleanly."""
        with self._state_lock:
            if self._state == CameraRuntimeState.STOPPED:
                return True
            
            self._set_state(CameraRuntimeState.STOPPING)
            self._stop_event.set()
        
        logger.info(f"[BOOT] {self.camera_id}: Stopping camera runtime...")
        
        success = True
        
        # Stop annotated publisher first
        if self._annotated_publisher:
            try:
                self._annotated_publisher.stop(timeout=5.0)
                logger.info(f"[BOOT] {self.camera_id}: Annotated publisher stopped")
            except Exception as e:
                logger.warning(f"[BOOT] {self.camera_id}: Error stopping publisher: {e}")
                success = False
        
        # Stop GPU AI Bridge
        if self._gpu_ai_bridge:
            try:
                self._gpu_ai_bridge.close()
                logger.info(f"[BOOT] {self.camera_id}: GPU AI Bridge stopped")
            except Exception as e:
                logger.warning(f"[BOOT] {self.camera_id}: Error stopping GPU AI Bridge: {e}")
                success = False
        
        # Stop detection pipeline (legacy)
        if self._detection_pipeline:
            try:
                self._detection_pipeline.stop()
                logger.info(f"[BOOT] {self.camera_id}: Detection pipeline stopped")
            except Exception as e:
                logger.warning(f"[BOOT] {self.camera_id}: Error stopping detection pipeline: {e}")
                success = False
        
        # Stop ingestion worker
        if self._ingestion_worker:
            try:
                self._ingestion_worker.stop(timeout=timeout)
                logger.info(f"[BOOT] {self.camera_id}: Ingestion worker stopped")
            except Exception as e:
                logger.warning(f"[BOOT] {self.camera_id}: Error stopping ingestion worker: {e}")
                success = False
        
        with self._state_lock:
            self._state = CameraRuntimeState.STOPPED
            self._ready_event.clear()
        
        logger.info(f"[BOOT] {self.camera_id}: Camera runtime STOPPED")
        return success

    def restart(self, timeout: float = 15.0) -> bool:
        """Restart the camera runtime with clean resource lifecycle."""
        logger.info(f"[BOOT] {self.camera_id}: Restarting camera runtime...")
        self._reconnect_attempts += 1
        
        # Stop current runtime
        self.stop(timeout=timeout)
        
        # Wait briefly for resources to release
        self._sleep_func(1.0)
        
        # Start fresh
        return self.start(wait_ready=True, ready_timeout=120.0)

    def wait_ready(self, timeout: float = 120.0) -> bool:
        """Wait for camera to reach READY state."""
        return self._ready_event.wait(timeout=timeout)

    def get_snapshot(self) -> CameraRuntimeSnapshot:
        """Get current runtime snapshot."""
        with self._state_lock:
            uptime = 0.0
            if self._start_time:
                uptime = self._time_func() - self._start_time
            
            ingestion_state = None
            if self._ingestion_worker:
                ingestion_state = self._ingestion_worker.state.value
            
            detection_running = self._detection_pipeline._running if self._detection_pipeline else False
            gpu_bridge_initialized = self._gpu_ai_bridge._initialized if self._gpu_ai_bridge else False
            publisher_started = self._annotated_publisher._metrics.started if self._annotated_publisher else False
            publisher_metrics = self._annotated_publisher.get_metrics() if self._annotated_publisher else None
            detection_frame_count = self._detection_pipeline._frame_count if self._detection_pipeline else 0
            
            return CameraRuntimeSnapshot(
                camera_id=self.camera_id,
                state=self._state,
                ingestion_worker_state=ingestion_state,
                detection_pipeline_running=detection_running,
                publisher_started=publisher_started,
                frames_received=self._frames_received,
                frames_processed=self._frames_processed,
                frames_published=self._frames_published,
                first_gpu_frame_received=self._first_gpu_frame_received,
                first_gpu_frame_time=self._first_gpu_frame_time,
                reconnect_attempts=self._reconnect_attempts,
                last_frame_time=self._last_frame_time,
                last_error=self._last_error,
                last_error_time=self._last_error_time,
                uptime_seconds=uptime,
                resolution=self._resolution,
                fps=self._fps,
                codec=self._codec,
                publisher_metrics=publisher_metrics,
                detection_pipeline_frame_count=detection_frame_count,
            )

    def get_health_result(self):
        """Get health check result for this camera."""
        if self._health_monitor:
            return self._health_monitor.check_health(self.camera_id, current_time=self._time_func())
        return None


def create_camera_runtime_manager(
    camera_id: str,
    settings=None,
    health_monitor: Optional[StreamHealthMonitor] = None,
    health_event_callback: Optional[Callable] = None,
) -> CameraRuntimeManager:
    """Factory function to create a camera runtime manager."""
    if settings is None:
        settings = load_settings()
    
    config = CameraRuntimeConfig.from_settings(settings, camera_id)
    
    return CameraRuntimeManager(
        config=config,
        health_monitor=health_monitor,
        health_event_callback=health_event_callback,
    )