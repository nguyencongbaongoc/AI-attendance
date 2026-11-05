"""
Camera Manager - Manages multiple camera ingestion pipelines.

Handles per-camera lifecycle, health monitoring, and coordination.
"""

from __future__ import annotations

import logging
import threading
import time
import concurrent.futures
from queue import Empty
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Iterator
from enum import Enum
from datetime import datetime

from pipeline_engine.ingestion.rtsp_source import RTSPSource, RTSPSourceConfig, RTSPState
from pipeline_engine.decode.nvdec_decoder import NVDECDecoder, NVDECDecoderConfig, DecoderState
from pipeline_engine.encode.nvenc_encoder import NVENCEncoder, NVENCEncoderConfig, EncoderState
from pipeline_engine.inference.face_detection import SCRFDDetector, SCRFDConfig, FaceDetection
from pipeline_engine.inference.face_recognition import ArcFaceRecognizer, ArcFaceConfig, FaceEmbedding
from pipeline_engine.inference.person_detection import YOLOPersonDetector, YOLOConfig, PersonDetection
from pipeline_engine.inference.body_reid import ReIDDetector, ReIDConfig
from pipeline_engine.tracking.tracker import Tracker, TrackingConfig, TrackingResult
from pipeline_engine.vision.face_quality import QualityAssessor
from app.runtime.gpu_vram_safety import VRAMMonitor, VRAMBudget, GPUVRAMSafety
from pipeline_engine.attendance.attendance_engine import AttendanceEngine, create_attendance_engine
from pipeline_engine.annotation.overlay import GPUAnnotator, AnnotationConfig
from pipeline_engine.output.publisher import create_publisher, MediaMTXPublisher
from pipeline_engine.memory.frame_pool import FramePoolManager, FramePoolConfig
from pipeline_engine.memory.gpu_frame import GPUFrame, FrameStatus, FrameOwnership
from pipeline_engine.config import get_config, get_camera_config
from pipeline_engine.memory.gpu_frame import nv12_to_bgr_cuda

import torch
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

# Persistent HTTP session for metadata ingest
_http_session: Optional[aiohttp.ClientSession] = None
_http_session_lock = asyncio.Lock()


async def _get_http_session() -> aiohttp.ClientSession:
    """Get or create persistent HTTP session with connection pooling."""
    global _http_session
    async with _http_session_lock:
        if _http_session is None or _http_session.closed:
            timeout = aiohttp.ClientTimeout(total=0.03, connect=0.01)
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5, enable_cleanup_closed=True)
            _http_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
            logger.info("[CameraManager] Created persistent HTTP session for metadata ingest")
        return _http_session


async def _close_http_session() -> None:
    """Close the persistent HTTP session."""
    global _http_session
    async with _http_session_lock:
        if _http_session is not None and not _http_session.closed:
            await _http_session.close()
            _http_session = None
            logger.info("[CameraManager] Closed persistent HTTP session")


class CameraState(str, Enum):
    """High-level camera states."""
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTING = "connecting"
    READY = "ready"
    RUNNING = "running"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class CameraMetrics:
    """Aggregated camera metrics."""
    camera_id: str
    state: CameraState = CameraState.STOPPED
    rtsp_state: RTSPState = RTSPState.DISCONNECTED
    frames_received: int = 0
    frames_decoded: int = 0
    frames_encoded: int = 0
    frames_dropped: int = 0
    inference_count: int = 0
    tracks_active: int = 0
    attendance_events: int = 0
    encode_fps: float = 0.0
    publish_fps: float = 0.0
    end_to_end_latency_ms: float = 0.0
    gpu_memory_mb: float = 0.0
    last_error: str = ""
    uptime_seconds: float = 0.0
    # Per-frame timing (from last frame)
    decode_time_ms: float = 0.0
    inference_time_ms: float = 0.0
    tracking_time_ms: float = 0.0
    annotation_time_ms: float = 0.0
    encode_time_ms: float = 0.0
    # Detailed telemetry
    input_fps: float = 0.0
    decoded_fps: float = 0.0
    ai_fps: float = 0.0
    tracked_fps: float = 0.0
    encoded_fps: float = 0.0
    output_fps: float = 0.0
    queue_depth: int = 0
    latency_ms: float = 0.0
    decode_errors: int = 0
    ai_errors: int = 0
    encode_errors: int = 0
    reconnect_count: int = 0
    # GPU telemetry
    gpu_utilization: float = 0.0
    vram_used: float = 0.0
    vram_total: float = 0.0
    decoder_state: str = "stopped"
    encoder_state: str = "stopped"


class CameraManager:
    """
    Manages multiple camera ingestion pipelines.
    
    Each camera runs independently with its own:
    - RTSP source
    - Frame pool
    - Decoder
    - AI inference (using shared singleton models)
    - Tracker
    - Encoder
    - Publisher
    
    Provides unified control and monitoring.
    """
    
    def __init__(self, config: Optional[Any] = None, shared_models: Optional[Dict[str, Any]] = None):
        self.config = config or get_config()
        self._cameras: Dict[str, Dict[str, Any]] = {}
        self._camera_threads: Dict[str, threading.Thread] = {}
        self._frame_pools: Optional[FramePoolManager] = None
        self._lock = threading.RLock()
        self._running = False
        self._start_time: Optional[float] = None
        self._shared_models = shared_models or {}
        
        # VRAM monitoring
        self._vram_monitor: Optional[VRAMMonitor] = None
        self._vram_safety = GPUVRAMSafety(preferred_device_index=0)
        
        # Global metrics
        self._global_metrics = {
            "total_cameras": 0,
            "running_cameras": 0,
            "healthy_cameras": 0,
            "total_frames": 0,
            "total_events": 0,
        }
    
    def initialize(self) -> bool:
        """Initialize camera manager and all configured cameras."""
        with self._lock:
            if self._running:
                logger.warning("CameraManager already initialized")
                return True
            
            try:
                # Initialize VRAM monitoring
                self._vram_monitor = self._vram_safety.start_monitoring(interval_seconds=1.0)
                
                # Initialize frame pools
                self._frame_pools = FramePoolManager.from_config(self.config)
                
                # Initialize async loop reference for thread-safe metadata dispatch
                try:
                    self._async_loop = asyncio.get_running_loop()
                except RuntimeError:
                    self._async_loop = None
                
                # Initialize cameras
                cameras_config = self.config.cameras or {}
                for camera_id, cam_config in cameras_config.items():
                    if not cam_config.get("enabled", True):
                        logger.info(f"CameraManager: Skipping disabled camera {camera_id}")
                        continue
                    
                    self._initialize_camera(camera_id, cam_config)
                
                self._running = True
                self._start_time = time.time()
                self._global_metrics["total_cameras"] = len(self._cameras)
                
                logger.info(f"CameraManager: Initialized {len(self._cameras)} cameras")
                return True
                
            except Exception as e:
                logger.error(f"CameraManager: Initialization failed: {e}")
                return False
    
    def _initialize_camera(self, camera_id: str, cam_config: Dict[str, Any]) -> None:
        """Initialize a single camera pipeline."""
        # Create dedicated CUDA stream for this camera FIRST (before detectors)
        device_id = cam_config.get("decode", {}).get("gpu_device", 0)
        cuda_stream = torch.cuda.Stream(device=device_id)
        
        # Create RTSP source
        rtsp_source = RTSPSource(
            RTSPSourceConfig(
                camera_id=camera_id,
                url=cam_config.get("input", {}).get("url", f"rtsp://localhost:8554/live/{camera_id}"),
                transport=cam_config.get("input", {}).get("transport", "tcp"),
                timeout=cam_config.get("input", {}).get("timeout_seconds", 10.0),
                reconnect_enabled=cam_config.get("reconnect", {}).get("enabled", True),
                max_retries=cam_config.get("reconnect", {}).get("max_retries", 5),
                base_interval=cam_config.get("reconnect", {}).get("base_interval_seconds", 2.0),
                max_interval=cam_config.get("reconnect", {}).get("max_interval_seconds", 60.0),
                backoff_multiplier=cam_config.get("reconnect", {}).get("backoff_multiplier", 2.0),
                jitter=cam_config.get("reconnect", {}).get("jitter", 0.1),
                stale_threshold=cam_config.get("health", {}).get("stale_threshold_seconds", 5.0),
                degraded_threshold=cam_config.get("health", {}).get("degraded_threshold_seconds", 2.0),
                readiness_enabled=cam_config.get("readiness", {}).get("enabled", True),
                readiness_timeout=cam_config.get("readiness", {}).get("timeout_seconds", 30.0),
                min_bytes_progress_interval=cam_config.get("readiness", {}).get("min_bytes_progress_interval", 5.0),
                consecutive_increases_required=cam_config.get("readiness", {}).get("consecutive_increases_required", 3),
            )
        )
        
        # Create frame pool
        pool_config = FramePoolConfig(
            camera_id=camera_id,
            width=cam_config.get("expected", {}).get("width", 3840),
            height=cam_config.get("expected", {}).get("height", 2160),
            min_size=cam_config.get("decode", {}).get("surfaces", 8),
            max_size=cam_config.get("decode", {}).get("surfaces", 32),
            device_id=device_id,
        )
        
        # Use shared AI models (singletons) instead of creating per-camera instances
        scrfd_detector = self._shared_models.get('scrfd')
        arcface_recognizer = self._shared_models.get('arcface')
        yolo_detector = self._shared_models.get('yolo')
        reid_detector = self._shared_models.get('reid')
        
        # Create tracker with shared recognizer
        tracker = Tracker(
            config=TrackingConfig(
                min_iou_threshold=cam_config.get("tracking", {}).get("min_iou", 0.3),
                max_lost_frames=cam_config.get("tracking", {}).get("max_lost", 10),
            ),
            recognizer=arcface_recognizer,
        )
        
        # Create attendance engine
        attendance_engine = create_attendance_engine()
        
        # Create annotator
        annotator = GPUAnnotator(
            config=AnnotationConfig(),
            device_id=device_id,
        )
        
        # Create quality assessor
        quality_assessor = QualityAssessor(device_id=device_id)
        
        # Store camera components (decoder, encoder, publisher will be created on start)
        self._cameras[camera_id] = {
            "config": cam_config,
            "rtsp_source": rtsp_source,
            "frame_pool": pool_config,
            "metrics": CameraMetrics(camera_id=camera_id),
            "state": CameraState.STOPPED,
            "start_time": None,
            # Pipeline components
            "decoder": None,
            "scrfd": scrfd_detector,
            "arcface": arcface_recognizer,
            "yolo": yolo_detector,
            "reid": reid_detector,
            "tracker": tracker,
            "attendance": attendance_engine,
            "annotator": annotator,
            "quality_assessor": quality_assessor,
            "encoder": None,
            "publisher": None,
            # Dedicated CUDA stream for this camera
            "cuda_stream": cuda_stream,
            # Telemetry
            "frame_times": [],  # For FPS calculation
            "last_metrics_update": time.time(),
        }
        
        logger.info(f"CameraManager: Initialized camera {camera_id} with shared models")
    
    def start_all(self) -> bool:
        """Start all cameras concurrently for faster cold start."""
        with self._lock:
            if not self._running:
                if not self.initialize():
                    return False
            
            camera_ids = list(self._cameras.keys())
        
        # Start cameras in parallel using ThreadPoolExecutor
        success = True
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(camera_ids)) as executor:
            # Submit all camera start tasks
            future_to_camera = {
                executor.submit(self.start_camera, camera_id): camera_id 
                for camera_id in camera_ids
            }
            
            # Wait for all to complete
            for future in concurrent.futures.as_completed(future_to_camera):
                camera_id = future_to_camera[future]
                try:
                    if not future.result():
                        logger.error(f"CameraManager: Camera {camera_id} failed to start")
                        success = False
                except Exception as e:
                    logger.error(f"CameraManager: Camera {camera_id} start exception: {e}")
                    success = False
        
        self._update_global_metrics()
        return success
    
    def stop_all(self) -> None:
        """Stop all cameras."""
        with self._lock:
            for camera_id in list(self._cameras.keys()):
                self.stop_camera(camera_id)
            
            if self._frame_pools:
                self._frame_pools.shutdown()
                self._frame_pools = None
            
            # Stop VRAM monitoring
            if self._vram_monitor:
                self._vram_monitor.stop()
                self._vram_monitor = None
            
            # Close persistent HTTP session
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_close_http_session())
                else:
                    loop.run_until_complete(_close_http_session())
            except Exception:
                # Best effort cleanup
                pass
            
            self._running = False
            self._start_time = None
            logger.info("CameraManager: All cameras stopped")
    
    def start_camera(self, camera_id: str) -> bool:
        """Start a specific camera."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                logger.error(f"CameraManager: Camera {camera_id} not found")
                return False
            
            if camera["state"] in (CameraState.RUNNING, CameraState.READY):
                logger.warning(f"CameraManager: Camera {camera_id} already running")
                return True
            
            camera["state"] = CameraState.STARTING
            camera["start_time"] = time.time()
        
        # Start RTSP source
        rtsp_source = camera["rtsp_source"]
        if not rtsp_source.start():
            with self._lock:
                camera["state"] = CameraState.ERROR
                camera["metrics"].last_error = "RTSP source start failed"
            return False
        
        # Wait for readiness
        start_wait = time.time()
        readiness_timeout = camera["config"].get("readiness", {}).get("timeout_seconds", 10.0)
        
        while time.time() - start_wait < readiness_timeout:
            if rtsp_source.metrics.readiness_passed:
                break
            time.sleep(0.3)
        else:
            logger.warning(f"CameraManager: Camera {camera_id} readiness timeout")
            # Continue anyway - might recover
        
        # Initialize and start decoder
        frame_pool = self._frame_pools.get_pool(camera_id) if self._frame_pools else None
        decoder_config = NVDECDecoderConfig(
            camera_id=camera_id,
            packet_source=rtsp_source,
            gpu_device=camera["config"].get("decode", {}).get("gpu_device", 0),
            codec=camera["config"].get("decode", {}).get("codec", "h264"),
            width=camera["config"].get("expected", {}).get("width", 3840),
            height=camera["config"].get("expected", {}).get("height", 2160),
            max_surfaces=camera["config"].get("decode", {}).get("surfaces", 32),
            max_queue_size=8,
            frame_pool=frame_pool,
        )
        decoder = NVDECDecoder(decoder_config, frame_pool)
        if not decoder.start():
            logger.error(f"CameraManager({camera_id}): Decoder start failed")
            rtsp_source.stop()
            with self._lock:
                camera["state"] = CameraState.ERROR
                camera["metrics"].last_error = "Decoder start failed"
            return False
        camera["decoder"] = decoder
        
        # AI models are shared singletons - already initialized by PipelineEngine
        # Just verify they are available
        scrfd = camera["scrfd"]
        arcface = camera["arcface"]
        yolo = camera["yolo"]
        reid = camera["reid"]
        
        for name, model in [("SCRFD", scrfd), ("ArcFace", arcface), ("YOLO", yolo), ("ReID", reid)]:
            if model is None:
                logger.error(f"CameraManager({camera_id}): {name} not available (shared model not initialized)")
                decoder.stop()
                rtsp_source.stop()
                with self._lock:
                    camera["state"] = CameraState.ERROR
                    camera["metrics"].last_error = f"{name} not available"
                return False
        
        # Initialize encoder (if enabled)
        encode_config = camera["config"].get("encode", {})
        encoder = None
        publisher = None
        
        if encode_config.get("enabled", True):
            output_config = camera["config"].get("output", {})
            mediamtx_host = "localhost"
            mediamtx_port = 8554
            output_path = output_config.get("path", f"live/{camera_id}-ai")
            output_url = f"rtsp://{mediamtx_host}:{mediamtx_port}/{output_path}"
            
            encoder_config = NVENCEncoderConfig(
                camera_id=camera_id,
                output_url=output_url,
                codec=encode_config.get("codec", "h264_nvenc"),
                width=encode_config.get("width", camera["config"].get("expected", {}).get("width", 3840)),
                height=encode_config.get("height", camera["config"].get("expected", {}).get("height", 2160)),
                fps=encode_config.get("fps", camera["config"].get("expected", {}).get("fps", 30.0)),
                bitrate_kbps=encode_config.get("bitrate_kbps", 8000),
                gop_size=encode_config.get("gop_size", 30),
                preset=encode_config.get("preset", "p4"),
                tune=encode_config.get("tune", "ll"),
                gpu_device=encode_config.get("gpu_device", camera["config"].get("decode", {}).get("gpu_device", 0)),
            )
            encoder = NVENCEncoder(encoder_config, frame_pool)
            if not encoder.start():
                logger.error(f"CameraManager({camera_id}): Encoder start failed")
                decoder.stop()
                for m in [scrfd, arcface, yolo]:
                    m.cleanup()
                rtsp_source.stop()
                with self._lock:
                    camera["state"] = CameraState.ERROR
                    camera["metrics"].last_error = "Encoder start failed"
                return False
            camera["encoder"] = encoder
            
            # Initialize publisher
            publisher = create_publisher(camera_id, use_ffmpeg=False)
            if not publisher.start():
                logger.error(f"CameraManager({camera_id}): Publisher start failed")
                encoder.stop()
                decoder.stop()
                for m in [scrfd, arcface, yolo]:
                    m.cleanup()
                rtsp_source.stop()
                with self._lock:
                    camera["state"] = CameraState.ERROR
                    camera["metrics"].last_error = "Publisher start failed"
                return False
            camera["publisher"] = publisher
        else:
            logger.info(f"CameraManager({camera_id}): Encoder/publisher disabled by config")
            camera["encoder"] = None
            camera["publisher"] = None
        
        # Start pipeline thread
        with self._lock:
            camera["state"] = CameraState.RUNNING
        thread = threading.Thread(
            target=self._camera_pipeline_loop,
            args=(camera_id,),
            name=f"camera-pipeline-{camera_id}",
            daemon=True,
        )
        camera["pipeline_thread"] = thread
        thread.start()
        
        logger.info(f"CameraManager: Camera {camera_id} started successfully")
        return True
    
    def stop_camera(self, camera_id: str) -> bool:
        """Stop a specific camera."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                logger.error(f"CameraManager: Camera {camera_id} not found")
                return False
            
            if camera["state"] == CameraState.STOPPED:
                return True
            
            logger.info(f"CameraManager: Stopping camera {camera_id}")
            camera["state"] = CameraState.STOPPED
        
        # Stop publisher
        publisher = camera.get("publisher")
        if publisher:
            publisher.stop()
        
        # Stop encoder
        encoder = camera.get("encoder")
        if encoder:
            encoder.stop()
        
        # Stop decoder
        decoder = camera.get("decoder")
        if decoder:
            decoder.stop()
        
        # NOTE: AI models are now shared singletons managed by PipelineEngine
        # Do NOT cleanup shared models here - they are cleaned up by PipelineEngine shutdown
        
        # Stop RTSP source
        rtsp_source = camera.get("rtsp_source")
        if rtsp_source:
            rtsp_source.stop()
        
        # Wait for pipeline thread
        thread = camera.get("pipeline_thread")
        if thread and thread.is_alive():
            thread.join(timeout=10.0)
        
        with self._lock:
            camera["state"] = CameraState.STOPPED
            camera["pipeline_thread"] = None
            camera["decoder"] = None
            camera["encoder"] = None
            camera["publisher"] = None
        
        logger.info(f"CameraManager: Camera {camera_id} stopped")
        return True
    
    def restart_camera(self, camera_id: str) -> bool:
        """Restart a specific camera."""
        self.stop_camera(camera_id)
        time.sleep(1.0)
        return self.start_camera(camera_id)
    
    def _camera_pipeline_loop(self, camera_id: str) -> None:
        """Main pipeline loop for a camera."""
        camera = self._cameras.get(camera_id)
        if not camera:
            return
        
        rtsp_source = camera["rtsp_source"]
        frame_pool = self._frame_pools.get_pool(camera_id) if self._frame_pools else None
        decoder = camera["decoder"]
        encoder = camera["encoder"]
        publisher = camera["publisher"]
        scrfd = camera["scrfd"]
        arcface = camera["arcface"]
        yolo = camera["yolo"]
        reid = camera["reid"]
        tracker = camera["tracker"]
        attendance = camera["attendance"]
        annotator = camera["annotator"]
        
        # Get dedicated CUDA stream for this camera
        cuda_stream = camera["cuda_stream"]
        device_id = camera["config"].get("decode", {}).get("gpu_device", 0)
        
        frame_counter = 0
        stream_epoch = 0
        epoch_start_time = time.time()
        
        # FPS calculation
        fps_window_size = 30
        frame_timestamps = []
        
        # Store frame_times in camera dict for metrics access
        camera["frame_times"] = frame_timestamps
        
        try:
            while self._running and camera["state"] in (CameraState.RUNNING, CameraState.DEGRADED):
                loop_start = time.perf_counter()
                
                # ========== STAGE 1: DECODE (Latest-Only Frame Drop Policy) ==========
                decode_start = time.perf_counter()
                gpu_frame = self._drain_to_latest_frame(decoder, max_age_ms=35.0)
                decode_ms = (time.perf_counter() - decode_start) * 1000
                
                if gpu_frame is None:
                    # No valid frame available - brief sleep to prevent tight loop
                    time.sleep(0.001)
                    continue
                
                camera["metrics"].frames_decoded += 1
                
                # Transfer ownership to decoder
                gpu_frame.transfer_ownership(FrameOwnership.DECODER)
                gpu_frame.set_status(FrameStatus.DECODED)
                gpu_frame.decode_time_ms = decode_ms
                gpu_frame.camera_id = camera_id
                gpu_frame.frame_id = frame_counter
                gpu_frame.timestamp = time.time()
                gpu_frame.pts = gpu_frame.pts  # Keep original PTS from decoder
                gpu_frame.dts = gpu_frame.dts
                gpu_frame.time_base = gpu_frame.time_base
                gpu_frame.stream_epoch = stream_epoch
                
                frame_counter += 1
                camera["metrics"].frames_received += 1
                
                # ========== STAGE 2: AI INFERENCE (within dedicated CUDA stream) ==========
                ai_start = time.perf_counter()
                
                with torch.cuda.stream(cuda_stream):
                    # Run face detection
                    face_detections = scrfd.detect(gpu_frame)
                    
                    # Run person detection
                    person_detections = yolo.detect(gpu_frame)
                    
                    # Check VRAM pressure & enforce backpressure
                    skip_heavy_inference = False
                    try:
                        if torch.cuda.is_available():
                            res_mb = torch.cuda.memory_reserved(device_id) / (1024 * 1024)
                            tot_mb = torch.cuda.get_device_properties(device_id).total_memory / (1024 * 1024)
                            util_pct = (res_mb / tot_mb) * 100.0 if tot_mb > 0 else 0.0
                            
                            # Warning Threshold (80% / ~4.8 GB): empty_cache + gc.collect + cap batch size to 8
                            if util_pct >= 80.0:
                                import gc
                                torch.cuda.empty_cache()
                                gc.collect()
                                if len(face_detections) > 8:
                                    logger.warning(f"CameraManager({camera_id}): VRAM at {util_pct:.1f}% (>=80%) - Capping face batch {len(face_detections)} -> 8")
                                    face_detections = face_detections[:8]
                                if len(person_detections) > 8:
                                    logger.warning(f"CameraManager({camera_id}): VRAM at {util_pct:.1f}% (>=80%) - Capping person batch {len(person_detections)} -> 8")
                                    person_detections = person_detections[:8]
                            
                            # Critical Threshold (90% / ~5.1 GB): Drop non-keyframe inference, recycle oldest unpinned frame buffer
                            if util_pct >= 90.0:
                                import gc
                                torch.cuda.empty_cache()
                                gc.collect()
                                skip_heavy_inference = True
                                logger.warning(f"CameraManager({camera_id}): CRITICAL VRAM ({util_pct:.1f}%)! Dropping non-keyframe inference for frame {frame_counter} to prevent OOM")
                                if frame_pool and hasattr(frame_pool, '_try_reclaim'):
                                    frame_pool._try_reclaim()
                    except Exception as ve:
                        logger.debug(f"VRAM check error: {ve}")
                    
                    # Run face recognition for each face detection
                    face_embeddings = {}
                    if not skip_heavy_inference:
                        for face_det in face_detections:
                            # Extract face crop and align (simplified - using face bbox for now)
                            # In production, would extract aligned 112x112 crop
                            aligned_face = self._extract_aligned_face(gpu_frame, face_det)
                            if aligned_face is not None:
                                embedding = arcface.infer_embedding(aligned_face)
                                embedding.detection_id = face_det.detection_id
                                embedding.frame_index = gpu_frame.frame_id
                                embedding.source_id = gpu_frame.camera_id
                                face_embeddings[face_det.detection_id] = embedding
                    
                    # Run ReID for each person detection
                    body_embeddings = {}
                    if not skip_heavy_inference:
                        for person_det in person_detections:
                            body_embedding = reid.infer_embedding(
                                frame=gpu_frame,
                                person_bbox=person_det.bbox,
                                detection_id=person_det.detection_id,
                                frame_index=gpu_frame.frame_id,
                                source_id=gpu_frame.camera_id,
                            )
                            body_embeddings[person_det.detection_id] = body_embedding
                    
                    # Quality assessment
                    quality_assessor = camera["quality_assessor"]
                    for face_det in face_detections:
                        if face_det.detection_id in face_embeddings:
                            face_quality = quality_assessor.assess_face(
                                gpu_frame, 
                                face_det.bbox, 
                                face_det.landmarks5
                            )
                            face_embeddings[face_det.detection_id].face_quality = face_quality.overall
                    
                    for person_det in person_detections:
                        if person_det.detection_id in body_embeddings:
                            body_quality = quality_assessor.assess_body(
                                gpu_frame, 
                                person_det.bbox
                            )
                            body_embeddings[person_det.detection_id].body_quality = body_quality.overall
                
                # Synchronize stream before CPU-side processing (tracking, etc.)
                cuda_stream.synchronize()
                
                ai_ms = (time.perf_counter() - ai_start) * 1000
                gpu_frame.inference_time_ms = ai_ms
                camera["metrics"].inference_count += len(face_detections) + len(person_detections)
                
                # Transfer ownership to inference
                gpu_frame.transfer_ownership(FrameOwnership.INFERENCE)
                gpu_frame.set_status(FrameStatus.INFERRING)
                
                # ========== STAGE 3: TRACKING ==========
                tracking_start = time.perf_counter()
                tracking_result = tracker.process_frame(
                    person_detections=person_detections,
                    face_detections=face_detections,
                    face_embeddings=face_embeddings,
                    body_embeddings=body_embeddings,
                    camera_id=camera_id,
                    timestamp=gpu_frame.timestamp,
                )
                tracking_ms = (time.perf_counter() - tracking_start) * 1000
                gpu_frame.tracking_time_ms = tracking_ms
                
                # Transfer ownership to tracking
                gpu_frame.transfer_ownership(FrameOwnership.TRACKING)
                gpu_frame.set_status(FrameStatus.TRACKING)
                
                # ========== STAGE 4: ATTENDANCE ==========
                attendance_events = attendance.process_tracks(tracking_result)
                camera["metrics"].attendance_events += len(attendance_events)
                active_tracks = tracking_result.get_active_tracks()
                camera["metrics"].tracks_active = len(active_tracks)

                # Broadcast live metadata to WebSocket clients (Task 6)
                try:
                    in_c = getattr(attendance, "in_count", 0)
                    out_c = getattr(attendance, "out_count", 0)
                    
                    # Get frame dimensions for normalization
                    frame_w = camera["config"].get("expected", {}).get("width", 3840)
                    frame_h = camera["config"].get("expected", {}).get("height", 2160)
                    
                    persons_data = [
                        {
                            "track_id": track.track_id,
                            "bbox": [
                                track.bbox_original_frame[0] / frame_w,  # xmin normalized
                                track.bbox_original_frame[1] / frame_h,  # ymin normalized
                                track.bbox_original_frame[2] / frame_w,  # xmax normalized
                                track.bbox_original_frame[3] / frame_h,  # ymax normalized
                            ],
                            "confidence": float(track.confidence) if hasattr(track, "confidence") else 1.0,
                            "face_name": getattr(track, "matched_name", None) or getattr(track, "person_name", None) or "Unknown",
                            "face_id": getattr(track, "matched_id", None) or getattr(track, "person_id", "") or ""
                        } for track in active_tracks
                    ]
                    
                    payload = {
                        "camera_id": camera_id.lower(),
                        "frame_sequence": frame_counter,
                        "pts_ns": int(gpu_frame.timestamp * 1e9) if hasattr(gpu_frame, 'timestamp') and gpu_frame.timestamp else int(time.time() * 1e9),
                        "capture_timestamp": datetime.utcnow().isoformat() + "Z",
                        "persons": persons_data,
                        "counts": {"in": in_c, "out": out_c}
                    }
                    
                    # Non-blocking async dispatch - never blocks AI pipeline
                    self._dispatch_metadata(payload)
                        
                except Exception as e:
                    import traceback
                    logger.error(f"Metadata broadcast error: {e}")
                    logger.error(traceback.format_exc())
                
                # ========== STAGE 5: ANNOTATION ==========
                annotation_start = time.perf_counter()
                
                # Prepare frame metrics for annotation
                frame_metrics = {
                    "fps": camera["metrics"].decoded_fps,
                    "latency_ms": camera["metrics"].latency_ms,
                    "gpu_memory_mb": camera["metrics"].gpu_memory_mb,
                }
                
                annotated_frame = annotator.annotate(
                    frame=gpu_frame,
                    tracks=tracking_result.get_active_tracks(),
                    camera_id=camera_id,
                    frame_metrics=frame_metrics,
                )
                annotation_ms = (time.perf_counter() - annotation_start) * 1000
                gpu_frame.annotation_time_ms = annotation_ms
                
                # Transfer ownership to annotation
                annotated_frame.transfer_ownership(FrameOwnership.ANNOTATION)
                annotated_frame.set_status(FrameStatus.ANNOTATING)
                
                # ========== STAGE 6: ENCODE (if enabled) ==========
                if encoder is not None:
                    encode_start = time.perf_counter()
                    if encoder.submit_frame(annotated_frame):
                        encode_ms = (time.perf_counter() - encode_start) * 1000
                        gpu_frame.encode_time_ms = encode_ms
                        camera["metrics"].frames_encoded += 1
                    else:
                        camera["metrics"].frames_dropped += 1
                        if frame_pool:
                            frame_pool.return_to_pool(annotated_frame)
                        continue
                    
                    # Transfer ownership to encoder
                    annotated_frame.transfer_ownership(FrameOwnership.ENCODER)
                    annotated_frame.set_status(FrameStatus.ENCODED)
                    
                    # Encoder will return frame to pool via callback
                else:
                    # No encoder - return frame to pool directly
                    if frame_pool:
                        frame_pool.return_to_pool(annotated_frame)
                
                # ========== STAGE 7: PUBLISH (if enabled) ==========
                # Publisher is handled asynchronously by encoder output
                
                # ========== TELEMETRY ==========
                frame_timestamps.append(time.time())
                if len(frame_timestamps) > 30:
                    frame_timestamps.pop(0)
                
                # Update per-stage FPS
                if len(frame_timestamps) >= 2:
                    window = frame_timestamps[-1] - frame_timestamps[0]
                    if window > 0:
                        camera["metrics"].input_fps = len(frame_timestamps) / window
                        camera["metrics"].decoded_fps = camera["metrics"].frames_decoded / window
                        camera["metrics"].ai_fps = camera["metrics"].inference_count / window
                        camera["metrics"].tracked_fps = camera["metrics"].tracks_active / max(window, 1)
                        if encoder is not None:
                            camera["metrics"].encoded_fps = camera["metrics"].frames_encoded / window
                            camera["metrics"].output_fps = publisher.metrics.packets_published / window if publisher and publisher.metrics.packets_published > 0 else 0
                        else:
                            camera["metrics"].encoded_fps = 0
                            camera["metrics"].output_fps = 0
                
                # Update latencies
                camera["metrics"].latency_ms = (time.perf_counter() - loop_start) * 1000
                
                # Update decoder/encoder state
                camera["metrics"].decoder_state = decoder.state.value
                if encoder:
                    camera["metrics"].encoder_state = encoder.state.value
                    camera["metrics"].queue_depth = decoder.get_queue_depth() + encoder.get_queue_depth()
                else:
                    camera["metrics"].encoder_state = "disabled"
                    camera["metrics"].queue_depth = decoder.get_queue_depth()
                
                # Update GPU metrics from VRAM monitor
                if self._vram_monitor:
                    vram_snapshot = self._vram_monitor.get_current()
                    camera["metrics"].gpu_memory_mb = vram_snapshot.allocated_mb
                    camera["metrics"].vram_used = vram_snapshot.reserved_mb
                    camera["metrics"].vram_total = vram_snapshot.total_mb
                    camera["metrics"].gpu_utilization = vram_snapshot.utilization_pct
                    
                    # Check VRAM budget
                    if self._vram_monitor.is_over_budget():
                        logger.warning(f"CameraManager({camera_id}): VRAM budget exceeded! "
                                     f"Allocated: {vram_snapshot.allocated_mb:.1f}MB, "
                                     f"Budget: {self._vram_monitor.budget.max_allocated_mb:.1f}MB")
                        camera["state"] = CameraState.DEGRADED
                    elif camera["state"] == CameraState.DEGRADED:
                        camera["state"] = CameraState.RUNNING
                else:
                    # Fallback to direct torch measurement
                    try:
                        if torch.cuda.is_available():
                            allocated = torch.cuda.memory_allocated(0) / (1024 * 1024)
                            reserved = torch.cuda.memory_reserved(0) / (1024 * 1024)
                            total = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
                            camera["metrics"].gpu_memory_mb = reserved
                            camera["metrics"].vram_used = reserved
                            camera["metrics"].vram_total = total
                            camera["metrics"].gpu_utilization = (reserved / total) * 100
                    except Exception:
                        pass
                
                # Periodic metrics update
                if time.time() - camera["last_metrics_update"] > 5.0:
                    self._update_camera_metrics(camera_id)
                    camera["last_metrics_update"] = time.time()
                
                # Small sleep to prevent CPU spinning
                loop_elapsed = (time.perf_counter() - loop_start) * 1000
                if loop_elapsed < 20:  # Target ~50 FPS max processing
                    time.sleep(0.001)
                
        except Exception as e:
            logger.error(f"CameraManager({camera_id}): Pipeline error: {e}")
            import traceback
            traceback.print_exc()
            with self._lock:
                camera["state"] = CameraState.ERROR
                camera["metrics"].last_error = str(e)
        finally:
            logger.info(f"CameraManager({camera_id}): Pipeline loop ended")

    def _drain_to_latest_frame(self, decoder, max_age_ms: float = 35.0) -> Optional[Any]:
        """Drain decoder queue, keeping only the latest valid frame."""
        latest_frame = None
        now = time.time()
        
        while True:
            try:
                frame = decoder._frame_queue.get_nowait()
                frame_age_ms = (now - getattr(frame, "timestamp", now)) * 1000.0
                
                if frame_age_ms > max_age_ms:
                    # Stale frame - return to pool
                    if getattr(decoder, "_frame_pool", None):
                        decoder._frame_pool.return_to_pool(frame)
                    decoder._metrics.frames_dropped += 1
                    continue
                
                # Drop previous latest if we have a newer one
                if latest_frame and getattr(decoder, "_frame_pool", None):
                    decoder._frame_pool.return_to_pool(latest_frame)
                    decoder._metrics.frames_dropped += 1
                
                latest_frame = frame
                
            except Empty:
                break
        
        return latest_frame
        """Extract and align 112x112 face crop from GPUFrame using face landmarks."""
        try:
            y_tensor, uv_tensor = frame.get_tensors()
            bgr = nv12_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) uint8
            
            # Use landmarks to align (simplified - crop face bbox and resize)
            x1, y1, x2, y2 = [int(c) for c in face_det.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(bgr.shape[1], x2), min(bgr.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                return None
            
            face_crop = bgr[y1:y2, x1:x2]
            
            # Resize to 112x112
            face_resized = torch.nn.functional.interpolate(
                face_crop.permute(2, 0, 1).unsqueeze(0).float(),
                size=(112, 112),
                mode='bilinear',
                align_corners=False
            ).squeeze(0).permute(1, 2, 0).byte()
            
            return face_resized
        except Exception as e:
            logger.warning(f"Failed to extract aligned face: {e}")
            return None

    def _update_camera_metrics(self, camera_id: str) -> None:
        """Update camera metrics with latest telemetry."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                return
            
            metrics = camera["metrics"]
            decoder = camera.get("decoder")
            encoder = camera.get("encoder")
            publisher = camera.get("publisher")
            
            if decoder:
                d_stats = decoder.get_stats()
                metrics.frames_decoded = d_stats.get("frames_decoded", 0)
                metrics.decode_errors = d_stats.get("decode_errors", 0)
                metrics.decoder_state = d_stats.get("state", "unknown")
            
            if encoder:
                e_stats = encoder.get_metrics()
                metrics.frames_encoded = e_stats.get("frames_encoded", 0)
                metrics.encode_errors = e_stats.get("encoder_restarts", 0)
                metrics.encoder_state = e_stats.get("state", "unknown")
                metrics.avg_encode_ms = e_stats.get("avg_encode_ms", 0.0)
            else:
                metrics.encoder_state = "disabled"
            
            if publisher:
                p_stats = publisher.get_metrics()
                metrics.publish_fps = p_stats.get("packets_published", 0) / 5.0  # Approximate
            else:
                metrics.publish_fps = 0
            
            # Update derived metrics
            metrics.uptime_seconds = time.time() - camera["start_time"] if camera["start_time"] else 0
            metrics.queue_depth = (decoder.get_queue_depth() if decoder else 0) + (encoder.get_queue_depth() if encoder else 0)
            metrics.latency_ms = metrics.decode_time_ms + metrics.inference_time_ms + metrics.tracking_time_ms + metrics.annotation_time_ms + metrics.encode_time_ms
            
            # Recalculate FPS
            frame_times = camera.get("frame_times", [])
            if len(frame_times) >= 2:
                window = frame_times[-1] - frame_times[0]
                if window > 0:
                    metrics.input_fps = len(frame_times) / window
                    metrics.decoded_fps = metrics.frames_decoded / window
                    metrics.ai_fps = metrics.inference_count / window
                    metrics.tracked_fps = metrics.tracks_active / max(window, 1)
                    if encoder:
                        metrics.encoded_fps = metrics.frames_encoded / window
                        metrics.output_fps = metrics.publish_fps
                    else:
                        metrics.encoded_fps = 0
                        metrics.output_fps = 0
    
    def get_camera_state(self, camera_id: str) -> Optional[CameraState]:
        """Get camera state."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            return camera["state"] if camera else None
    
    def get_camera_metrics(self, camera_id: str) -> Optional[CameraMetrics]:
        """Get camera metrics."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if camera:
                # Update from RTSP source
                rtsp_source = camera.get("rtsp_source")
                if rtsp_source:
                    camera["metrics"].rtsp_state = rtsp_source.state
                return camera["metrics"]
            return None
    
    def get_all_metrics(self) -> Dict[str, CameraMetrics]:
        """Get metrics for all cameras."""
        with self._lock:
            return {cid: cam["metrics"] for cid, cam in self._cameras.items()}
    
    def get_global_metrics(self) -> Dict[str, Any]:
        """Get global metrics."""
        with self._lock:
            self._update_global_metrics()
            return self._global_metrics.copy()
    
    def _update_global_metrics(self) -> None:
        """Update global metrics."""
        running = sum(1 for c in self._cameras.values() if c["state"] == CameraState.RUNNING)
        healthy = sum(1 for c in self._cameras.values() 
                     if c["state"] in (CameraState.RUNNING, CameraState.READY))
        
        total_frames = sum(c["metrics"].frames_received for c in self._cameras.values())
        total_events = sum(c["metrics"].attendance_events for c in self._cameras.values())
        
        self._global_metrics.update({
            "running_cameras": running,
            "healthy_cameras": healthy,
            "total_frames": total_frames,
            "total_events": total_events,
            "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
        })

    # ========== ASYNC METADATA DISPATCH ==========
    
    def _dispatch_metadata(self, payload: dict) -> None:
        """Non-blocking metadata dispatch using thread-safe asyncio."""
        loop = getattr(self, '_async_loop', None)
        if loop and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._async_post_metadata(payload), loop)
            except Exception as e:
                logger.debug(f"Metadata dispatch failed: {e}")

    async def _async_post_metadata(self, payload: dict) -> None:
        """Async HTTP POST with short timeout - fire and forget.
        
        Uses persistent HTTP session with connection pooling for efficiency.
        """
        try:
            session = await _get_http_session()
            async with session.post(
                "http://127.0.0.1:8000/api/v1/stream/metadata/ingest",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=0.03)
            ) as resp:
                pass  # Non-blocking - drop on backpressure
        except Exception:
            pass  # Silent drop - never blocks AI pipeline
    
    def is_camera_healthy(self, camera_id: str) -> bool:
        """Check if camera is healthy."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                return False
            if camera["state"] in (CameraState.ERROR, CameraState.STOPPED):
                return False
            decoder = camera.get("decoder")
            if decoder and hasattr(decoder, "is_degraded") and decoder.is_degraded():
                return False
            rtsp_source = camera.get("rtsp_source")
            if rtsp_source:
                return rtsp_source.is_healthy()
            return camera["state"] == CameraState.RUNNING
    
    def get_camera_list(self) -> List[str]:
        """Get list of camera IDs."""
        with self._lock:
            return list(self._cameras.keys())
    
    def get_camera_config(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Get camera configuration."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            return camera["config"].copy() if camera else None
    
    def update_camera_config(self, camera_id: str, config: Dict[str, Any]) -> bool:
        """Update camera configuration (requires restart)."""
        with self._lock:
            camera = self._cameras.get(camera_id)
            if not camera:
                return False
            
            was_running = camera["state"] == CameraState.RUNNING
            if was_running:
                self.stop_camera(camera_id)
            
            camera["config"].update(config)
            
            if was_running:
                self.start_camera(camera_id)
            
            return True

    def update_crossing_line(
        self,
        camera_id: str,
        p1: tuple[float, float],
        p2: tuple[float, float],
        direction_semantics: str = "side_a_to_b_in"
    ) -> bool:
        """Dynamically update crossing line geometry for a camera without restarting."""
        with self._lock:
            norm_id = camera_id.lower().replace("-", "").strip()
            updated = False
            for cid, cam in self._cameras.items():
                if cid.lower().replace("-", "").strip() == norm_id:
                    # Update AttendanceEngine on this camera
                    att = cam.get("attendance")
                    if att and hasattr(att, "update_camera_line"):
                        att.update_camera_line(cid, p1, p2, direction_semantics)
                    
                    # Update stored geometry in camera config
                    if "config" in cam and "geometry" in cam["config"]:
                        cam["config"]["geometry"]["line_start"] = [int(p1[0]), int(p1[1])]
                        cam["config"]["geometry"]["line_end"] = [int(p2[0]), int(p2[1])]
                        cam["config"]["geometry"]["direction_semantics"] = direction_semantics
                    updated = True
            return updated

    def reload_gallery(
        self,
        npy_path: str = "data/embeddings.npy",
        metadata_path: str = "data/embeddings.npy.metadata.json"
    ) -> int:
        """Reload ArcFace embedding database across all active cameras."""
        with self._lock:
            total_loaded = 0
            for cid, cam in self._cameras.items():
                arcface = cam.get("arcface")
                if arcface and hasattr(arcface, "load_enrollment_database"):
                    try:
                        count = arcface.load_enrollment_database(npy_path, metadata_path)
                        total_loaded = max(total_loaded, count or 0)
                        logger.info(f"CameraManager({cid}): Reloaded {count} ArcFace embeddings from {npy_path}")
                    except Exception as e:
                        logger.error(f"CameraManager({cid}): Failed to reload ArcFace embeddings: {e}")
            return total_loaded

    def restart_camera(self, camera_id: str) -> bool:
        """Restart a camera pipeline."""
        with self._lock:
            self.stop_camera(camera_id)
            time.sleep(0.5)
            return self.start_camera(camera_id)

    def __enter__(self):
        self.start_all()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_all()


# Convenience functions
_camera_manager: Optional[CameraManager] = None
_manager_lock = threading.Lock()


def get_camera_manager(config: Optional[Any] = None) -> CameraManager:
    """Get global camera manager instance."""
    global _camera_manager
    with _manager_lock:
        if _camera_manager is None:
            _camera_manager = CameraManager(config)
        return _camera_manager


def shutdown_camera_manager() -> None:
    """Shutdown global camera manager."""
    global _camera_manager
    with _manager_lock:
        if _camera_manager:
            _camera_manager.stop_all()
            _camera_manager = None


if __name__ == "__main__":
    # Test
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    manager = CameraManager()
    
    if manager.initialize():
        print("CameraManager initialized!")
        print(f"Cameras: {manager.get_camera_list()}")
        
        # Start all cameras
        if manager.start_all():
            print("All cameras started!")
            
            # Run for a bit
            time.sleep(10)
            
            # Print metrics
            for cam_id in manager.get_camera_list():
                metrics = manager.get_camera_metrics(cam_id)
                print(f"{cam_id}: {metrics}")
            
            print(f"Global: {manager.get_global_metrics()}")
        
        manager.stop_all()
        print("CameraManager stopped!")
    else:
        print("Failed to initialize CameraManager")