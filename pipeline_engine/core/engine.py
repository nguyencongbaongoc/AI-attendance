"""
Pipeline Engine - Core orchestration for AI Attendance video pipeline.

Manages the complete end-to-end pipeline lifecycle.
"""

from __future__ import annotations

import logging
import threading
import time
import signal
import sys
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from pathlib import Path

from pipeline_engine.config import load_pipeline_config, PipelineConfig
from pipeline_engine.ingestion.camera_manager import CameraManager, CameraState
from pipeline_engine.memory.frame_pool import FramePoolManager
from pipeline_engine.memory.memory_monitor import GPUMemoryMonitor, MemoryPressureLevel

logger = logging.getLogger(__name__)


class EngineState(str, Enum):
    """Pipeline engine states."""
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    VALIDATING = "validating"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class EngineMetrics:
    """Engine-level metrics."""
    state: EngineState = EngineState.STOPPED
    uptime_seconds: float = 0.0
    cameras_total: int = 0
    cameras_running: int = 0
    cameras_healthy: int = 0
    total_frames_processed: int = 0
    total_attendance_events: int = 0
    gpu_memory_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    pipeline_latency_ms: float = 0.0
    errors: int = 0
    last_error: str = ""


class PipelineEngine:
    """
    Main pipeline engine - orchestrates the complete video pipeline.
    
    Responsibilities:
    - Configuration loading and validation
    - Component initialization (cameras, memory, monitoring)
    - Startup/shutdown sequencing
    - Health monitoring
    - Signal handling
    - Metrics aggregation
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.config: Optional[PipelineConfig] = None
        
        # Core components
        self.camera_manager: Optional[CameraManager] = None
        self.frame_pool_manager: Optional[FramePoolManager] = None
        self.memory_monitor: Optional[GPUMemoryMonitor] = None
        
        # Shared AI models (singletons) - created once, shared across cameras
        self._shared_scrfd: Optional[Any] = None
        self._shared_arcface: Optional[Any] = None
        self._shared_yolo: Optional[Any] = None
        self._shared_reid: Optional[Any] = None
        
        # State
        self._state = EngineState.STOPPED
        self._metrics = EngineMetrics()
        self._start_time: Optional[float] = None
        self._lock = threading.RLock()
        
        # Control
        self._stop_event = threading.Event()
        self._supervisor_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._state_change_callbacks: List[Callable[[EngineState, EngineState], None]] = []
        self._health_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        # Signal handling
        self._signal_handlers_installed = False
    
    @property
    def state(self) -> EngineState:
        return self._state
    
    @property
    def metrics(self) -> EngineMetrics:
        with self._lock:
            self._update_metrics()
            return self._metrics
    
    def _set_state(self, state: EngineState) -> None:
        with self._lock:
            old_state = self._state
            self._state = state
            self._metrics.state = state
            if old_state != state:
                logger.info(f"PipelineEngine: {old_state.value} -> {state.value}")
                for callback in self._state_change_callbacks:
                    try:
                        callback(old_state, state)
                    except Exception as e:
                        logger.error(f"State change callback error: {e}")
    
    def register_state_callback(self, callback: Callable[[EngineState, EngineState], None]) -> None:
        """Register callback for state changes."""
        self._state_change_callbacks.append(callback)
    
    def register_health_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register callback for health updates."""
        self._health_callbacks.append(callback)
    
    def load_config(self) -> bool:
        """Load and validate configuration."""
        self._set_state(EngineState.INITIALIZING)
        
        try:
            self.config = load_pipeline_config(self.config_path)
            logger.info(f"PipelineEngine: Configuration loaded from {self.config_path or 'default'}")
            
            # Validate critical settings
            if not self._validate_config():
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"PipelineEngine: Config load failed: {e}")
            self._metrics.last_error = str(e)
            self._set_state(EngineState.ERROR)
            return False
    
    def _validate_config(self) -> bool:
        """Validate configuration."""
        if not self.config:
            return False
        
        # Check GPU requirement
        if self.config.gpu.get("required", True):
            import torch
            if not torch.cuda.is_available():
                logger.error("PipelineEngine: GPU required but CUDA not available")
                return False
            
            device_id = self.config.gpu.get("device_id", 0)
            if device_id >= torch.cuda.device_count():
                logger.error(f"PipelineEngine: GPU device {device_id} not available")
                return False
        
        # Check cameras
        cameras = self.config.cameras or {}
        if not cameras:
            logger.warning("PipelineEngine: No cameras configured")
        
        # Check model paths
        models = self.config.models or {}
        required_models = ["scrfd", "arcface", "yolo"]
        for model_name in required_models:
            model_config = models.get(model_name, {})
            model_path = model_path = model_config.get("path", "")
            if not model_path:
                logger.warning(f"PipelineEngine: Model {model_name} path not configured")
            else:
                path = Path(model_path)
                if not path.exists():
                    logger.warning(f"PipelineEngine: Model {model_name} not found at {path}")
        
        return True
    
    def _initialize_shared_models(self) -> None:
        """Initialize shared AI models as singletons to avoid VRAM duplication."""
        import torch
        from pipeline_engine.inference.face_detection import SCRFDDetector, SCRFDConfig
        from pipeline_engine.inference.face_recognition import ArcFaceRecognizer, ArcFaceConfig
        from pipeline_engine.inference.person_detection import YOLOPersonDetector, YOLOConfig
        from pipeline_engine.inference.body_reid import ReIDDetector, ReIDConfig
        
        device_id = self.config.gpu.get("device_id", 0) if self.config else 0
        
        # Create shared CUDA stream for inference
        cuda_stream = torch.cuda.Stream(device=device_id)
        
        # SCRFD Face Detector
        scrfd_cfg = self.config.models.get("scrfd", {}) if self.config and self.config.models else {}
        self._shared_scrfd = SCRFDDetector(
            model_path="models/scrfd/scrfd_10g_bnkps_fp16.engine",
            config=SCRFDConfig(
                confidence_threshold=scrfd_cfg.get("confidence_threshold", 0.5),
                nms_threshold=scrfd_cfg.get("nms_threshold", 0.4),
            ),
            device_id=device_id,
            cuda_stream=cuda_stream,
        )
        
        # ArcFace Recognizer
        arcface_cfg = self.config.models.get("arcface", {}) if self.config and self.config.models else {}
        self._shared_arcface = ArcFaceRecognizer(
            model_path="models/arcface/glintr100_fp16.engine",
            config=ArcFaceConfig(
                similarity_threshold=arcface_cfg.get("similarity_threshold", 0.6),
            ),
            device_id=device_id,
            cuda_stream=cuda_stream,
        )
        
        # Load enrollment database for ArcFace
        self._shared_arcface.load_enrollment_database(
            "data/embeddings.npy",
            "data/embeddings.npy.metadata.json"
        )
        
        # YOLO Person Detector
        yolo_cfg = self.config.models.get("yolo", {}) if self.config and self.config.models else {}
        self._shared_yolo = YOLOPersonDetector(
            model_path="models/yolo/yolo11n_fp16.engine",
            config=YOLOConfig(
                confidence_threshold=yolo_cfg.get("confidence_threshold", 0.35),
                nms_threshold=yolo_cfg.get("nms_threshold", 0.45),
                input_size=tuple(yolo_cfg.get("input_size", [640, 640])),
                person_class_id=yolo_cfg.get("person_class_id", 0),
                max_detections=yolo_cfg.get("max_detections", 100),
            ),
            device_id=device_id,
            cuda_stream=cuda_stream,
        )
        
        # ReID Detector
        reid_cfg = self.config.models.get("reid", {}) if self.config and self.config.models else {}
        self._shared_reid = ReIDDetector(
            model_path="models/reid/resnet50_reid_fp16.engine",
            config=ReIDConfig(),
            device_id=device_id,
            cuda_stream=cuda_stream,
        )
        
        # Initialize all shared models
        for name, model in [
            ("SCRFD", self._shared_scrfd),
            ("ArcFace", self._shared_arcface),
            ("YOLO", self._shared_yolo),
            ("ReID", self._shared_reid),
        ]:
            if not model.initialize():
                logger.error(f"PipelineEngine: Shared {name} initialization failed")
                raise RuntimeError(f"Shared {name} initialization failed")
        
        logger.info("PipelineEngine: Shared AI models initialized successfully as singletons")
    
    def initialize(self) -> bool:
        """Initialize all pipeline components."""
        self._set_state(EngineState.INITIALIZING)
        
        try:
            # Initialize memory monitor
            gpu_config = self.config.gpu if self.config else {}
            vram_budget = gpu_config.get("vram_budget_mb", 4096)
            device_id = gpu_config.get("device_id", 0)
            
            self.memory_monitor = GPUMemoryMonitor(
                device_id=device_id,
                vram_budget_mb=vram_budget,
                poll_interval=1.0,
            )
            
            # Register memory pressure callback
            self.memory_monitor.register_callback(
                MemoryPressureLevel.HIGH,
                self._on_memory_pressure
            )
            self.memory_monitor.register_callback(
                MemoryPressureLevel.CRITICAL,
                self._on_memory_critical
            )
            
            self.memory_monitor.start()
            
            # Initialize camera manager with shared models
            self._initialize_shared_models()
            
            self.camera_manager = CameraManager(self.config, shared_models={
                'scrfd': self._shared_scrfd,
                'arcface': self._shared_arcface,
                'yolo': self._shared_yolo,
                'reid': self._shared_reid,
            })
            if not self.camera_manager.initialize():
                logger.error("PipelineEngine: Camera manager initialization failed")
                return False
            
            self._set_state(EngineState.VALIDATING)
            
            # Validate camera connectivity - WARNING only, do not fail initialization
            # Cameras can be offline at startup; they will retry at runtime
            self._validate_cameras()
            
            logger.info("PipelineEngine: Initialized successfully (cameras may be offline)")
            return True
            
        except Exception as e:
            logger.error(f"PipelineEngine: Initialization failed: {e}")
            self._metrics.last_error = str(e)
            self._set_state(EngineState.ERROR)
            return False
    
    def _validate_cameras(self) -> bool:
        """Validate camera RTSP connectivity - warning only, never fails."""
        if not self.config:
            return True
        
        cameras = self.config.cameras or {}
        
        for camera_id, cam_config in cameras.items():
            if not cam_config.get("enabled", True):
                continue
            
            url = cam_config.get("input", {}).get("url", "")
            if not url:
                logger.warning(f"PipelineEngine: Camera {camera_id} has no input URL")
                continue
            
            # Quick connectivity test - log but don't fail
            try:
                import cv2
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret:
                        logger.info(f"PipelineEngine: Camera {camera_id} connectivity OK")
                    else:
                        logger.warning(f"PipelineEngine: Camera {camera_id} connected but no frames (will retry at runtime)")
                else:
                    logger.warning(f"PipelineEngine: Camera {camera_id} connection failed (will retry at runtime)")
            except Exception as e:
                logger.warning(f"PipelineEngine: Camera {camera_id} validation error: {e} (will retry at runtime)")
        
        # Always return True - camera connectivity is not a hard requirement
        return True
    
    def start(self) -> bool:
        """Start the complete pipeline."""
        with self._lock:
            if self._state in (EngineState.RUNNING, EngineState.STARTING):
                logger.warning("PipelineEngine: Already running")
                return True
            
            if self._state not in (EngineState.VALIDATING, EngineState.STOPPED, EngineState.ERROR):
                logger.error(f"PipelineEngine: Cannot start from state {self._state}")
                return False
        
        self._set_state(EngineState.STARTING)
        self._stop_event.clear()
        
        try:
            # Start cameras - allow partial success (some cameras may be offline)
            self.camera_manager.start_all()
            
            # Start supervisor thread
            self._supervisor_thread = threading.Thread(
                target=self._supervisor_loop,
                name="pipeline-supervisor",
                daemon=True,
            )
            self._supervisor_thread.start()
            
            self._start_time = time.time()
            
            # Check if any cameras are running
            if self.camera_manager:
                running_count = sum(1 for c in self.camera_manager._cameras.values() 
                                   if c["state"] == CameraState.RUNNING)
                total_count = len(self.camera_manager._cameras)
                
                if running_count == 0 and total_count > 0:
                    self._set_state(EngineState.DEGRADED)
                    logger.warning(f"PipelineEngine: Started in DEGRADED state - 0/{total_count} cameras running")
                else:
                    self._set_state(EngineState.RUNNING)
                    logger.info(f"PipelineEngine: Started successfully ({running_count}/{total_count} cameras running)")
            else:
                self._set_state(EngineState.RUNNING)
                logger.info("PipelineEngine: Started successfully (no cameras configured)")
            
            return True
            
        except Exception as e:
            logger.error(f"PipelineEngine: Start failed: {e}")
            self._metrics.last_error = str(e)
            self._set_state(EngineState.ERROR)
            return False
    
    def stop(self, timeout: float = 30.0) -> None:
        """Stop the pipeline gracefully."""
        with self._lock:
            if self._state in (EngineState.STOPPED, EngineState.STOPPING):
                return
            
            logger.info("PipelineEngine: Stopping...")
            self._set_state(EngineState.STOPPING)
        
        self._stop_event.set()
        
        # Stop cameras
        if self.camera_manager:
            self.camera_manager.stop_all()
        
        # Wait for supervisor
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            self._supervisor_thread.join(timeout=timeout)
        
        # Stop memory monitor
        if self.memory_monitor:
            self.memory_monitor.stop()
        
        # Cleanup shared AI models
        for name, model in [
            ("SCRFD", self._shared_scrfd),
            ("ArcFace", self._shared_arcface),
            ("YOLO", self._shared_yolo),
            ("ReID", self._shared_reid),
        ]:
            if model:
                try:
                    model.cleanup()
                    logger.info(f"PipelineEngine: Cleaned up shared {name}")
                except Exception as e:
                    logger.error(f"PipelineEngine: Error cleaning up shared {name}: {e}")
        
        self._shared_scrfd = None
        self._shared_arcface = None
        self._shared_yolo = None
        self._shared_reid = None
        
        with self._lock:
            self._state = EngineState.STOPPED
            self._start_time = None
        
        logger.info("PipelineEngine: Stopped")
    
    def restart(self) -> bool:
        """Restart the pipeline."""
        self.stop()
        time.sleep(1.0)
        return self.start()
    
    def _supervisor_loop(self) -> None:
        """Main supervisor loop - monitors health and handles issues."""
        check_interval = 5.0
        
        while not self._stop_event.is_set():
            try:
                self._health_check()
                self._update_metrics()
                
                # Trigger health callbacks
                health = self.get_health()
                for callback in self._health_callbacks:
                    try:
                        callback(health)
                    except Exception as e:
                        logger.error(f"Health callback error: {e}")
                
            except Exception as e:
                logger.error(f"PipelineEngine: Supervisor error: {e}")
                self._metrics.errors += 1
                self._metrics.last_error = str(e)
            
            self._stop_event.wait(check_interval)
        
        logger.debug("PipelineEngine: Supervisor loop ended")
    
    def _health_check(self) -> None:
        """Perform health check on all components."""
        if not self.camera_manager:
            return
        
        cameras = self.camera_manager.get_camera_list()
        healthy = 0
        running = 0
        
        for camera_id in cameras:
            state = self.camera_manager.get_camera_state(camera_id)
            if state == CameraState.RUNNING:
                running += 1
                if self.camera_manager.is_camera_healthy(camera_id):
                    healthy += 1
            elif state in (CameraState.DEGRADED, CameraState.UNHEALTHY):
                # Try to recover
                logger.warning(f"PipelineEngine: Camera {camera_id} in state {state.value}, attempting recovery")
                self.camera_manager.restart_camera(camera_id)
        
        # Update engine state based on camera health
        with self._lock:
            self._metrics.cameras_total = len(cameras)
            self._metrics.cameras_running = running
            self._metrics.cameras_healthy = healthy
            
            if running == 0 and len(cameras) > 0:
                self._set_state(EngineState.ERROR)
            elif healthy < running:
                self._set_state(EngineState.DEGRADED)
            elif running > 0:
                self._set_state(EngineState.RUNNING)
    
    def _update_metrics(self) -> None:
        """Update engine metrics."""
        with self._lock:
            if self._start_time:
                self._metrics.uptime_seconds = time.time() - self._start_time
            
            if self.camera_manager:
                cam_metrics = self.camera_manager.get_global_metrics()
                self._metrics.total_frames_processed = cam_metrics.get("total_frames", 0)
                self._metrics.total_attendance_events = cam_metrics.get("total_events", 0)
            
            if self.memory_monitor:
                mem_stats = self.memory_monitor.get_stats()
                current = mem_stats.get("current")
                if current:
                    self._metrics.gpu_memory_mb = current.get("reserved_mb", 0)
                    self._metrics.gpu_utilization_pct = current.get("utilization_pct", 0)
    
    def _on_memory_pressure(self, snapshot) -> None:
        """Handle high memory pressure."""
        logger.warning(f"PipelineEngine: HIGH memory pressure - {snapshot.utilization_pct:.1f}%")
        # Could trigger frame dropping, reduce batch size, etc.
        if self.camera_manager:
            # Notify cameras to reduce processing
            pass
    
    def _on_memory_critical(self, snapshot) -> None:
        """Handle critical memory pressure."""
        logger.error(f"PipelineEngine: CRITICAL memory pressure - {snapshot.utilization_pct:.1f}%")
        # Emergency measures
        if self.memory_monitor:
            self.memory_monitor.empty_cache()
    
    def get_health(self) -> Dict[str, Any]:
        """Get comprehensive health status."""
        with self._lock:
            health = {
                "engine": {
                    "state": self._state.value,
                    "uptime_seconds": self._metrics.uptime_seconds,
                    "errors": self._metrics.errors,
                    "last_error": self._metrics.last_error,
                },
                "cameras": {},
                "memory": {},
            }
            
            if self.camera_manager:
                for cam_id in self.camera_manager.get_camera_list():
                    cam_metrics = self.camera_manager.get_camera_metrics(cam_id)
                    if cam_metrics:
                        health["cameras"][cam_id] = {
                            "state": self.camera_manager.get_camera_state(cam_id).value,
                            "frames_received": cam_metrics.frames_received,
                            "frames_dropped": cam_metrics.frames_dropped,
                            "tracks_active": cam_metrics.tracks_active,
                            "attendance_events": cam_metrics.attendance_events,
                            "uptime_seconds": cam_metrics.uptime_seconds,
                            "last_error": cam_metrics.last_error,
                        }
            
            if self.memory_monitor:
                health["memory"] = self.memory_monitor.get_stats()
            
            return health
    
    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        metrics = self.metrics
        return (
            f"PipelineEngine: {metrics.state.value.upper()} "
            f"| Uptime: {metrics.uptime_seconds:.0f}s "
            f"| Cameras: {metrics.cameras_healthy}/{metrics.cameras_running}/{metrics.cameras_total} "
            f"| Frames: {metrics.total_frames_processed} "
            f"| Events: {metrics.total_attendance_events} "
            f"| GPU: {metrics.gpu_memory_mb:.0f}MB ({metrics.gpu_utilization_pct:.1f}%) "
            f"| Errors: {metrics.errors}"
        )
    
    def install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        if self._signal_handlers_installed:
            return
        
        def signal_handler(signum, frame):
            logger.info(f"PipelineEngine: Received signal {signum}, shutting down...")
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
        
        self._signal_handlers_installed = True
        logger.info("PipelineEngine: Signal handlers installed")
    
    def run_forever(self) -> None:
        """Run engine until stopped (blocking)."""
        self.install_signal_handlers()
        
        if not self.load_config():
            logger.error("PipelineEngine: Config load failed")
            return
        
        if not self.initialize():
            logger.error("PipelineEngine: Initialization failed")
            return
        
        if not self.start():
            logger.error("PipelineEngine: Start failed")
            return
        
        logger.info("PipelineEngine: Running (press Ctrl+C to stop)")
        
        try:
            while self._state == EngineState.RUNNING:
                time.sleep(1.0)
                print(self.get_status_summary())
        except KeyboardInterrupt:
            logger.info("PipelineEngine: Keyboard interrupt")
        finally:
            self.stop()
    
    def __enter__(self):
        self.load_config()
        self.initialize()
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# Global engine instance
_engine: Optional[PipelineEngine] = None
_engine_lock = threading.Lock()


def get_engine(config_path: Optional[Path] = None) -> PipelineEngine:
    """Get global pipeline engine instance."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = PipelineEngine(config_path)
        return _engine


def shutdown_engine() -> None:
    """Shutdown global pipeline engine."""
    global _engine
    with _engine_lock:
        if _engine:
            _engine.stop()
            _engine = None


if __name__ == "__main__":
    # Test
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    engine = PipelineEngine()
    
    if engine.load_config():
        print("Config loaded!")
        
        if engine.initialize():
            print("Engine initialized!")
            
            if engine.start():
                print("Engine started!")
                
                # Run for a bit
                time.sleep(10)
                
                print(engine.get_status_summary())
            
            engine.stop()
            print("Engine stopped!")
        else:
            print("Initialization failed!")
    else:
        print("Config load failed!")