"""
AI Worker — Standalone runtime for PipelineEngine with Legacy Backend integration.

Manages complete lifecycle: STARTING → INITIALIZING → RUNNING → DEGRADED → STOPPING → STOPPED/FAILED
Integrates health reporting, control commands, and event delivery.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pipeline_engine.config import load_pipeline_config, PipelineConfig
from pipeline_engine.core.engine import PipelineEngine, EngineState
from pipeline_engine.integration.health_client import (
    LegacyBackendHealthClient,
    HealthClientConfig,
    create_health_client,
    setup_health_reporting,
)
from pipeline_engine.integration.control_client import (
    PipelineEngineControlServer,
    ControlClientConfig,
    create_control_server,
    setup_control_integration,
)
from pipeline_engine.integration.event_client import (
    EventDeliveryClient,
    EventDeliveryConfig,
    create_event_client,
    setup_event_delivery,
)
from pipeline_engine.attendance.attendance_engine import AttendanceEngine, CrossingEvent

logger = logging.getLogger(__name__)


class WorkerState(str, Enum):
    """AI Worker lifecycle states."""
    STARTING = "starting"
    INITIALIZING = "initializing"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class WorkerMetrics:
    """Worker-level metrics."""
    state: WorkerState = WorkerState.STARTING
    uptime_seconds: float = 0.0
    cameras_total: int = 0
    cameras_healthy: int = 0
    cameras_degraded: int = 0
    total_frames_processed: int = 0
    total_attendance_events: int = 0
    events_delivered: int = 0
    events_failed: int = 0
    events_pending: int = 0
    gpu_memory_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    avg_latency_ms: float = 0.0
    errors: int = 0
    last_error: str = ""
    enrollment_reloads: int = 0
    enrollment_last_reload: Optional[float] = None


@dataclass
class WorkerConfig:
    """AI Worker configuration."""
    # Identity
    worker_id: str = "pipeline_engine_1"
    worker_version: str = "1.0.0"
    
    # Backend connection
    backend_base_url: str = "http://localhost:19146"
    ai_worker_api_key: str = ""
    ai_control_api_key: str = ""
    
    # PipelineEngine config
    pipeline_config_path: Optional[Path] = None
    
    # Health reporting
    health_report_interval: float = 5.0
    health_timeout: float = 5.0
    health_max_retries: int = 3
    
    # Control polling
    control_poll_interval: float = 2.0
    control_timeout: float = 5.0
    
    # Event delivery
    event_queue_max_size: int = 1000
    event_delivery_interval: float = 1.0
    event_delivery_timeout: float = 10.0
    event_max_retries: int = 3
    
    # Enrollment watching
    enrollment_watch_enabled: bool = True
    enrollment_watch_interval: float = 30.0
    
    # Graceful shutdown
    shutdown_timeout: float = 30.0
    
    def load_from_env(self) -> None:
        """Load configuration from environment variables."""
        self.worker_id = os.environ.get("WORKER_ID", self.worker_id)
        self.worker_version = os.environ.get("WORKER_VERSION", self.worker_version)
        self.backend_base_url = os.environ.get("BACKEND_BASE_URL", self.backend_base_url)
        self.ai_worker_api_key = os.environ.get("AI_WORKER_API_KEY", self.ai_worker_api_key)
        self.ai_control_api_key = os.environ.get("AI_CONTROL_API_KEY", self.ai_control_api_key)
        
        if os.environ.get("PIPELINE_CONFIG_PATH"):
            self.pipeline_config_path = Path(os.environ["PIPELINE_CONFIG_PATH"])
            
        self.health_report_interval = float(os.environ.get("HEALTH_REPORT_INTERVAL", self.health_report_interval))
        self.control_poll_interval = float(os.environ.get("CONTROL_POLL_INTERVAL", self.control_poll_interval))
        self.event_delivery_interval = float(os.environ.get("EVENT_DELIVERY_INTERVAL", self.event_delivery_interval))
        self.shutdown_timeout = float(os.environ.get("SHUTDOWN_TIMEOUT", self.shutdown_timeout))
        
        config_path = os.environ.get("PIPELINE_CONFIG_PATH")
        if config_path:
            self.pipeline_config_path = Path(config_path)


class AIWorker:
    """
    Main AI Worker class orchestrating PipelineEngine and Backend integration.
    
    Responsibilities:
    - Configuration loading and validation
    - PipelineEngine lifecycle management
    - Health reporting to Legacy Backend
    - Control command execution from Legacy Backend
    - Attendance event delivery to Legacy Backend
    - Enrollment database change detection
    - Graceful startup/shutdown
    - Signal handling
    """
    
    def __init__(self, config: Optional[WorkerConfig] = None):
        self.config = config or WorkerConfig()
        self.config.load_from_env()
        
        self._state = WorkerState.STARTING
        self._state_lock = asyncio.Lock()
        self._start_time: Optional[float] = None
        self._stop_event = asyncio.Event()
        
        # PipelineEngine
        self.engine: Optional[PipelineEngine] = None
        
        # Integration clients
        self.health_client: Optional[LegacyBackendHealthClient] = None
        self.control_server: Optional[PipelineEngineControlServer] = None
        self.event_client: Optional[EventDeliveryClient] = None
        
        # Background tasks
        self._health_update_task: Optional[asyncio.Task] = None
        self._enrollment_watcher_task: Optional[asyncio.Task] = None
        self._metrics_update_task: Optional[asyncio.Task] = None
        
        # Metrics
        self._metrics = WorkerMetrics()
        self._health_sequence = 0
        
        # Callbacks
        self._state_callbacks: List[Callable[[WorkerState, WorkerState], None]] = []
        
        # Signal handling
        self._signal_handlers_installed = False
        
        # Enrollment tracking
        self._last_enrollment_mtime: float = 0
        
    @property
    def state(self) -> WorkerState:
        return self._state
        
    @property
    def metrics(self) -> WorkerMetrics:
        return self._metrics
        
    def register_state_callback(self, callback: Callable[[WorkerState, WorkerState], None]) -> None:
        """Register callback for state changes."""
        self._state_callbacks.append(callback)
        
    def _set_state(self, state: WorkerState) -> None:
        old_state = self._state
        self._state = state
        self._metrics.state = state
        if old_state != state:
            logger.info(f"AI Worker: {old_state.value} -> {state.value}")
            for callback in self._state_callbacks:
                try:
                    callback(old_state, state)
                except Exception as e:
                    logger.error(f"State change callback error: {e}")
                    
    async def start(self) -> bool:
        """
        Start the AI Worker - complete initialization sequence.
        
        Returns True if started successfully, False otherwise.
        """
        async with self._state_lock:
            if self._state != WorkerState.STARTING:
                logger.warning(f"Worker already in state {self._state.value}, cannot start")
                return self._state == WorkerState.RUNNING
            self._set_state(WorkerState.INITIALIZING)
            
        logger.info(f"Starting AI Worker {self.config.worker_id} v{self.config.worker_version}")
        
        try:
            # 1. Load PipelineEngine config
            logger.info("Loading PipelineEngine configuration...")
            self.engine = PipelineEngine(self.config.pipeline_config_path)
            if not self.engine.load_config():
                raise RuntimeError("PipelineEngine config load failed")
            logger.info("PipelineEngine configuration loaded")
            
            # 2. Initialize PipelineEngine (memory, cameras, models)
            logger.info("Initializing PipelineEngine...")
            if not self.engine.initialize():
                raise RuntimeError("PipelineEngine initialization failed")
            logger.info("PipelineEngine initialized")
            
            # 3. Verify model readiness
            logger.info("Verifying model readiness...")
            if not await self._verify_model_readiness():
                raise RuntimeError("Model readiness verification failed")
            logger.info("Models ready")
            
            # 4. Start PipelineEngine (cameras + supervisor)
            logger.info("Starting PipelineEngine...")
            if not self.engine.start():
                raise RuntimeError("PipelineEngine start failed")
            logger.info("PipelineEngine started")
            
            # 5. Verify camera connectivity
            logger.info("Verifying camera connectivity...")
            if not await self._verify_camera_connectivity():
                # Don't fail - cameras might recover
                logger.warning("Some cameras not fully connected, continuing with degraded state")
                self._set_state(WorkerState.DEGRADED)
            else:
                logger.info("All cameras connected")
            
            # 6. Initialize integration clients
            logger.info("Initializing integration clients...")
            await self._initialize_integration_clients()
            logger.info("Integration clients initialized")
            
            # 7. Register event callback with AttendanceEngine
            self._register_event_callback()
            logger.info("Event callbacks registered")
            
            # 8. Start background tasks
            self._start_background_tasks()
            logger.info("Background tasks started")
            
            # 9. Install signal handlers
            self._install_signal_handlers()
            
            # All components ready
            self._start_time = time.time()
            async with self._state_lock:
                self._set_state(WorkerState.RUNNING)
            
            logger.info(f"AI Worker {self.config.worker_id} started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Worker start failed: {e}")
            self._metrics.errors += 1
            self._metrics.last_error = str(e)
            async with self._state_lock:
                self._set_state(WorkerState.FAILED)
            await self._cleanup_on_failure()
            return False
            
    async def stop(self, timeout: float = None) -> None:
        """Graceful shutdown."""
        timeout = timeout or self.config.shutdown_timeout
        
        async with self._state_lock:
            if self._state in (WorkerState.STOPPING, WorkerState.STOPPED):
                return
            self._set_state(WorkerState.STOPPING)
            
        logger.info("AI Worker stopping...")
        self._stop_event.set()
        
        # Stop background tasks
        await self._stop_background_tasks()
        
        # Stop integration clients
        if self.health_client:
            await self.health_client.stop()
        if self.control_server:
            await self.control_server.stop()
        if self.event_client:
            await self.event_client.stop()
            
        # Stop PipelineEngine
        if self.engine:
            self.engine.stop(timeout=timeout)
            
        async with self._state_lock:
            self._set_state(WorkerState.STOPPED)
            
        logger.info("AI Worker stopped")
        
    async def restart(self) -> bool:
        """Restart the worker."""
        logger.info("Restarting AI Worker...")
        await self.stop()
        await asyncio.sleep(1.0)
        
        # Reset state
        async with self._state_lock:
            self._state = WorkerState.STARTING
            self._stop_event.clear()
            
        return await self.start()
        
    async def _verify_model_readiness(self) -> bool:
        """Verify that all AI models are loaded and ready."""
        if not self.engine or not self.engine.camera_manager:
            return False
            
        cameras = self.engine.camera_manager.get_camera_list()
        if not cameras:
            logger.warning("No cameras configured")
            return True  # Not a failure, just no cameras
            
        for camera_id in cameras:
            camera = self.engine.camera_manager._cameras.get(camera_id)
            if not camera:
                continue
                
            # Check SCRFD
            scrfd = camera.get("scrfd")
            if not scrfd or not scrfd._initialized:
                logger.error(f"Camera {camera_id}: SCRFD not initialized")
                return False
                
            # Check ArcFace
            arcface = camera.get("arcface")
            if not arcface or not arcface._initialized:
                logger.error(f"Camera {camera_id}: ArcFace not initialized")
                return False
                
            # Check YOLO
            yolo = camera.get("yolo")
            if not yolo or not yolo._initialized:
                logger.error(f"Camera {camera_id}: YOLO not initialized")
                return False
                
        return True
        
    async def _verify_camera_connectivity(self) -> bool:
        """Verify camera RTSP connectivity."""
        if not self.engine or not self.engine.camera_manager:
            return False
            
        cameras = self.engine.camera_manager.get_camera_list()
        all_healthy = True
        
        for camera_id in cameras:
            rtsp_source = self.engine.camera_manager._cameras.get(camera_id, {}).get("rtsp_source")
            if rtsp_source:
                # Wait briefly for readiness
                start = time.time()
                while time.time() - start < 10.0:
                    if rtsp_source.metrics.readiness_passed:
                        logger.info(f"Camera {camera_id} readiness passed")
                        break
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(f"Camera {camera_id} readiness timeout")
                    all_healthy = False
                    
        return all_healthy
        
    async def _initialize_integration_clients(self) -> None:
        """Initialize health, control, and event delivery clients."""
        # Health client
        health_config = HealthClientConfig(
            backend_base_url=self.config.backend_base_url,
            worker_id=self.config.worker_id,
            worker_version=self.config.worker_version,
            api_key=self.config.ai_worker_api_key,
            report_interval=self.config.health_report_interval,
            timeout=self.config.health_timeout,
            max_retries=self.config.health_max_retries,
        )
        self.health_client = create_health_client(health_config, self.engine)
        await self.health_client.start()
        
        # Control server
        control_config = ControlClientConfig(
            backend_base_url=self.config.backend_base_url,
            worker_id=self.config.worker_id,
            api_key=self.config.ai_control_api_key,
            poll_interval=self.config.control_poll_interval,
            timeout=self.config.control_timeout,
        )
        self.control_server = create_control_server(self.engine, control_config)
        await self.control_server.start()
        
        # Event delivery client
        event_config = EventDeliveryConfig(
            backend_base_url=self.config.backend_base_url,
            api_key=self.config.ai_worker_api_key,
            queue_max_size=self.config.event_queue_max_size,
            delivery_interval=self.config.event_delivery_interval,
            timeout=self.config.event_delivery_timeout,
            max_retries=self.config.event_max_retries,
        )
        self.event_client = create_event_client(event_config)
        await self.event_client.start()
        
    def _register_event_callback(self) -> None:
        """Register callback to receive attendance events from AttendanceEngine."""
        if not self.engine or not self.engine.camera_manager:
            return
            
        attendance_engine = None
        # Get attendance engine from any camera (they share the same engine instance)
        for camera_id in self.engine.camera_manager.get_camera_list():
            camera = self.engine.camera_manager._cameras.get(camera_id)
            if camera and camera.get("attendance"):
                attendance_engine = camera["attendance"]
                break
                
        if attendance_engine and self.event_client:
            def on_attendance_event(event: CrossingEvent):
                self._on_attendance_event(event)
                
            attendance_engine.register_event_callback(on_attendance_event)
            logger.info("Registered attendance event callback")
            
    def _on_attendance_event(self, event: CrossingEvent) -> None:
        """Handle attendance event from AttendanceEngine."""
        try:
            # Convert CrossingEvent to CrossingEventRequest format
            request = self._convert_crossing_event(event)
            
            # Queue for delivery (non-blocking)
            if self.event_client:
                asyncio.create_task(self.event_client.submit_event(request))
                
            # Update metrics
            self._metrics.total_attendance_events += 1
            
        except Exception as e:
            logger.error(f"Failed to process attendance event: {e}")
            self._metrics.errors += 1
            self._metrics.last_error = str(e)
            
    def _convert_crossing_event(self, event: CrossingEvent) -> Any:
        """Convert PipelineEngine CrossingEvent to API CrossingEventRequest."""
        # Import here to avoid circular dependency
        from app.api.ai_worker import CrossingEventRequest, TimeBase, CrossingPoint, Position
        
        # Get stream info from engine
        stream_epoch = 0
        pts = 0
        time_base = TimeBase(num=1, den=90000)
        capture_timestamp = event.timestamp
        processing_timestamp = time.time()
        
        if self.engine and self.engine.camera_manager:
            camera = self.engine.camera_manager._cameras.get(event.camera_id)
            if camera:
                rtsp_source = camera.get("rtsp_source")
                if rtsp_source and hasattr(rtsp_source, '_stream') and rtsp_source._stream:
                    time_base = TimeBase(
                        num=rtsp_source._stream.time_base.num if rtsp_source._stream.time_base else 1,
                        den=rtsp_source._stream.time_base.den if rtsp_source._stream.time_base else 90000
                    )
                # Stream epoch tracked by health client
                stream_epoch = self.health_client._stream_epochs.get(event.camera_id, 0) if self.health_client else 0
                
        return CrossingEventRequest(
            event_id=event.event_id,
            camera_id=event.camera_id,
            track_id=event.track_id,
            direction=event.direction.value,
            event_type=event.event_type.value,
            crossing_point=CrossingPoint(x=event.crossing_point[0], y=event.crossing_point[1]),
            timestamp=event.timestamp,
            frame_index=event.frame_index,
            previous_position=Position(x=event.previous_position[0], y=event.previous_position[1]),
            current_position=Position(x=event.current_position[0], y=event.current_position[1]),
            person_id=event.person_id,
            person_name=event.person_name,
            identity_confidence=event.identity_confidence,
            stream_epoch=stream_epoch,
            pts=pts,  # TODO: Get actual PTS from frame
            time_base=time_base,
            capture_timestamp=capture_timestamp,
            processing_timestamp=processing_timestamp,
            model_version="scrfd_10g+arcface_glintr100+yolo11n",
            enrollment_version=str(int(self._last_enrollment_mtime)) if self._last_enrollment_mtime else "0",
            provenance="pipeline_engine_v1",
            schema_version="1.0",
        )
        
    def _start_background_tasks(self) -> None:
        """Start background maintenance tasks."""
        # Health update task - pushes metrics to health client
        self._health_update_task = asyncio.create_task(self._health_update_loop())
        
        # Metrics update task
        self._metrics_update_task = asyncio.create_task(self._metrics_update_loop())
        
        # Enrollment watcher
        if self.config.enrollment_watch_enabled:
            self._enrollment_watcher_task = asyncio.create_task(self._enrollment_watch_loop())
            
    async def _stop_background_tasks(self) -> None:
        """Stop all background tasks."""
        for task in [self._health_update_task, self._metrics_update_task, self._enrollment_watcher_task]:
            if task:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                    
    async def _health_update_loop(self) -> None:
        """Periodically update health client with current metrics."""
        while not self._stop_event.is_set():
            try:
                await self._push_health_update()
            except Exception as e:
                logger.error(f"Health update error: {e}")
            await asyncio.sleep(self.config.health_report_interval)
            
    async def _push_health_update(self) -> None:
        """Build and push health update to health client."""
        if not self.health_client:
            return
            
        self._health_sequence += 1
        
        # Get engine health
        engine_health = self.engine.get_health() if self.engine else {}
        
        # Build camera states
        camera_states = {}
        if self.engine and self.engine.camera_manager:
            for cam_id in self.engine.camera_manager.get_camera_list():
                cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
                cam_state = self.engine.camera_manager.get_camera_state(cam_id)
                if cam_metrics and cam_state:
                    camera_states[cam_id] = {
                        "state": cam_state.value if hasattr(cam_state, 'value') else str(cam_state),
                        "last_frame_timestamp": cam_metrics.last_frame_timestamp if hasattr(cam_metrics, 'last_frame_timestamp') else 0.0,
                        "decode_fps": cam_metrics.decoded_fps if hasattr(cam_metrics, 'decoded_fps') else 0.0,
                        "inference_fps": cam_metrics.ai_fps if hasattr(cam_metrics, 'ai_fps') else 0.0,
                        "track_count": cam_metrics.tracks_active if hasattr(cam_metrics, 'tracks_active') else 0,
                    }
                    
        # Model readiness
        model_readiness = self._get_model_readiness()
        
        # Stream epochs
        stream_epochs = {}
        if self.health_client:
            stream_epochs = self.health_client._stream_epochs.copy()
            
        # Errors
        errors = []
        if self._metrics.last_error:
            errors.append(self._metrics.last_error)
        if self.engine and self.engine.metrics.last_error:
            errors.append(self.engine.metrics.last_error)
            
        health_data = {
            "worker_id": self.config.worker_id,
            "worker_version": self.config.worker_version,
            "state": self._state.value,
            "timestamp": time.time(),
            "sequence_number": self._health_sequence,
            "camera_states": camera_states,
            "model_readiness": model_readiness,
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": self.event_client._queue.qsize() if self.event_client else 0,
            "processing_latency_ms": self._metrics.avg_latency_ms,
            "dropped_frames": 0,  # TODO: track from camera manager
            "stream_epochs": stream_epochs,
            "errors": errors,
        }
        
        self.health_client.update_health(health_data)
        
    def _get_model_readiness(self) -> Dict[str, bool]:
        """Get model readiness status."""
        readiness = {"scrfd": False, "arcface": False, "yolo": False}
        
        if not self.engine or not self.engine.camera_manager:
            return readiness
            
        # Check first camera (all cameras share same model instances)
        for cam_id in self.engine.camera_manager.get_camera_list():
            camera = self.engine.camera_manager._cameras.get(cam_id)
            if camera:
                if camera.get("scrfd") and camera["scrfd"]._initialized:
                    readiness["scrfd"] = True
                if camera.get("arcface") and camera["arcface"]._initialized:
                    readiness["arcface"] = True
                if camera.get("yolo") and camera["yolo"]._initialized:
                    readiness["yolo"] = True
                break
                
        return readiness
        
    async def _metrics_update_loop(self) -> None:
        """Update metrics periodically."""
        while not self._stop_event.is_set():
            try:
                self._update_metrics()
            except Exception as e:
                logger.error(f"Metrics update error: {e}")
            await asyncio.sleep(5.0)
            
    def _update_metrics(self) -> None:
        """Update worker metrics from engine."""
        if not self.engine:
            return
            
        engine_metrics = self.engine.metrics
        
        self._metrics.uptime_seconds = time.time() - self._start_time if self._start_time else 0
        self._metrics.cameras_total = engine_metrics.cameras_total
        self._metrics.cameras_healthy = engine_metrics.cameras_healthy
        self._metrics.cameras_degraded = engine_metrics.cameras_total - engine_metrics.cameras_healthy
        self._metrics.total_frames_processed = engine_metrics.total_frames_processed
        self._metrics.total_attendance_events = engine_metrics.total_attendance_events
        self._metrics.gpu_memory_mb = engine_metrics.gpu_memory_mb
        self._metrics.gpu_utilization_pct = engine_metrics.gpu_utilization_pct
        self._metrics.avg_latency_ms = engine_metrics.pipeline_latency_ms
        self._metrics.errors = engine_metrics.errors
        self._metrics.last_error = engine_metrics.last_error
        
        # Event delivery metrics
        if self.event_client:
            event_stats = self.event_client.get_stats()
            self._metrics.events_delivered = event_stats["delivered"]
            self._metrics.events_failed = event_stats["failed"]
            self._metrics.events_pending = event_stats["pending"]
            
    async def _enrollment_watch_loop(self) -> None:
        """Watch for enrollment database changes."""
        embeddings_path = Path("data/embeddings.npy")
        metadata_path = Path("data/embeddings.npy.metadata.json")
        
        while not self._stop_event.is_set():
            try:
                if embeddings_path.exists() and metadata_path.exists():
                    mtime = max(embeddings_path.stat().st_mtime, metadata_path.stat().st_mtime)
                    if mtime > self._last_enrollment_mtime:
                        logger.info("Enrollment database changed, reloading...")
                        await self._reload_enrollment()
                        self._last_enrollment_mtime = mtime
                        self._metrics.enrollment_reloads += 1
                        self._metrics.enrollment_last_reload = time.time()
                        
                        # Notify backend
                        await self._notify_backend_enrollment_reload()
            except Exception as e:
                logger.error(f"Enrollment watch error: {e}")
                
            await asyncio.sleep(self.config.enrollment_watch_interval)
            
    async def _reload_enrollment(self) -> None:
        """Reload enrollment database in all ArcFace recognizers."""
        if not self.engine or not self.engine.camera_manager:
            return
            
        for camera_id in self.engine.camera_manager.get_camera_list():
            camera = self.engine.camera_manager._cameras.get(camera_id)
            if camera and camera.get("arcface"):
                try:
                    camera["arcface"].load_enrollment_database(
                        "data/embeddings.npy",
                        "data/embeddings.npy.metadata.json"
                    )
                    logger.info(f"Reloaded enrollment for camera {camera_id}")
                except Exception as e:
                    logger.error(f"Failed to reload enrollment for {camera_id}: {e}")
                    
    async def _notify_backend_enrollment_reload(self) -> None:
        """Notify backend of enrollment reload."""
        if self.event_client and self.event_client._client:
            try:
                await self.event_client._client.post(
                    "/api/v1/enrollment/reload",
                    json={"trigger": "file_watcher", "worker_id": self.config.worker_id}
                )
            except Exception as e:
                logger.warning(f"Backend enrollment reload notification failed: {e}")
                
    def _cleanup_on_failure(self) -> None:
        """Cleanup resources on startup failure."""
        if self.engine:
            try:
                self.engine.stop(timeout=5.0)
            except Exception:
                pass
                
    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        if self._signal_handlers_installed:
            return
            
        def signal_handler(signum, frame):
            logger.info(f"AI Worker: Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.stop())
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
            
        self._signal_handlers_installed = True
        logger.info("AI Worker: Signal handlers installed")
        
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive worker status."""
        return {
            "worker_id": self.config.worker_id,
            "worker_version": self.config.worker_version,
            "state": self._state.value,
            "uptime_seconds": self._metrics.uptime_seconds,
            "cameras": {
                "total": self._metrics.cameras_total,
                "healthy": self._metrics.cameras_healthy,
                "degraded": self._metrics.cameras_degraded,
            },
            "frames_processed": self._metrics.total_frames_processed,
            "attendance_events": self._metrics.total_attendance_events,
            "event_delivery": {
                "delivered": self._metrics.events_delivered,
                "failed": self._metrics.events_failed,
                "pending": self._metrics.events_pending,
            },
            "gpu": {
                "memory_mb": self._metrics.gpu_memory_mb,
                "utilization_pct": self._metrics.gpu_utilization_pct,
            },
            "latency_ms": self._metrics.avg_latency_ms,
            "errors": self._metrics.errors,
            "last_error": self._metrics.last_error,
            "enrollment": {
                "reloads": self._metrics.enrollment_reloads,
                "last_reload": self._metrics.enrollment_last_reload,
            },
            "integration": {
                "health_client": self.health_client is not None,
                "control_server": self.control_server is not None,
                "event_client": self.event_client is not None,
            },
        }
        
    async def run_forever(self) -> None:
        """Run worker until stopped (blocking)."""
        self._install_signal_handlers()
        
        if not await self.start():
            logger.error("AI Worker: Start failed")
            return
            
        logger.info("AI Worker: Running (press Ctrl+C to stop)")
        
        try:
            while self._state == WorkerState.RUNNING:
                await asyncio.sleep(1.0)
                # Print status periodically
                if int(self._metrics.uptime_seconds) % 30 == 0:
                    logger.info(self.get_status_summary())
        except KeyboardInterrupt:
            logger.info("AI Worker: Keyboard interrupt")
        finally:
            await self.stop()
            
    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        return (
            f"AI Worker: {self._metrics.state.value.upper()} "
            f"| Uptime: {self._metrics.uptime_seconds:.0f}s "
            f"| Cameras: {self._metrics.cameras_healthy}/{self._metrics.cameras_total} "
            f"| Frames: {self._metrics.total_frames_processed} "
            f"| Events: {self._metrics.total_attendance_events} "
            f"| Delivered: {self._metrics.events_delivered} "
            f"| Failed: {self._metrics.events_failed} "
            f"| GPU: {self._metrics.gpu_memory_mb:.0f}MB ({self._metrics.gpu_utilization_pct:.1f}%) "
            f"| Errors: {self._metrics.errors}"
        )


# Global worker instance
_worker: Optional[AIWorker] = None
_worker_lock = asyncio.Lock()


async def get_worker(config: Optional[WorkerConfig] = None) -> AIWorker:
    """Get global AI Worker instance."""
    global _worker
    async with _worker_lock:
        if _worker is None:
            _worker = AIWorker(config)
        return _worker


async def shutdown_worker() -> None:
    """Shutdown global AI Worker."""
    global _worker
    async with _worker_lock:
        if _worker:
            await _worker.stop()
            _worker = None


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create and run worker
    config = WorkerConfig()
    worker = AIWorker(config)
    
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        pass