"""
Phase H.10-C.2 — PyAV Annotated Frame Publisher.

Zero-copy PyAV-based publisher for CUDA-resident frames.
Replaces FFmpeg subprocess + BGR24 pipe with PyAV NVENC encoder.

Architecture:
    DetectionPipeline.process_frame(frame)
        |
        +-- existing path: HealthEvent -> WebSocket (KEEP)
        +-- NEW path:     PyAVAnnotatedPublisher.submit(
                              y_plane_dlpack, uv_plane_dlpack,
                              detections, lines, regions, camera_id
                          )
                              |
                              v
                          latest-wins bounded queue (size 2)
                              |
                              v
                          PyAV NVENC Encoder (h264_nvenc on GPU)
                              |
                              v
                          RTSP → MediaMTX → HLS

The publisher does NOT re-run inference. It only:
  * Consumes annotated NV12 planes (Y + UV) from GPU pipeline
  * Sends them to PyAV NVENC encoder for H.264 encoding
  * Drops frames if encoder cannot keep up (latest-wins)
  * Keeps per-camera state isolated (one publisher, one queue,
    one PyAV encoder, one RTSP target per camera_id)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.gpu_annotation_pyav import GPUAnnotationPyAVConfig, get_gpu_annotation_pyav_renderer, reset_gpu_annotation_pyav_renderers
from app.vision.gpu_4k_surface_pyav import get_gpu_4k_surface_pyav_pool, reset_gpu_4k_surface_pyav_pool
from app.streaming.pyav_nvenc_encoder import PyAVNVENCEncoderConfig, create_pyav_nvenc_encoder

logger = logging.getLogger(__name__)


@dataclass
class PyAVAnnotatedPublisherConfig:
    """Configuration for the PyAV annotated frame publisher."""
    camera_id: str
    rtsp_url: str
    width: int = 3840
    height: int = 2160
    fps: float = 15.0
    video_bitrate_kbps: int = 2500
    gop_seconds: float = 1.0
    max_restarts: int = 5
    restart_backoff_seconds: float = 2.0
    nvenc_gpu_device: int = 0
    nvenc_preset: str = "p1"
    nvenc_tune: str = "ll"
    nvenc_rc: str = "cbr"
    nvenc_hw_frames: int = 32
    # GPU annotation
    gpu_annotation_enabled: bool = True
    gpu_annotation_gpu_device: int = 0


@dataclass
class PyAVAnnotatedPublisherMetrics:
    """Metrics for PyAV annotated publisher."""
    frames_submitted: int = 0
    frames_encoded: int = 0
    frames_dropped: int = 0
    encoder_restarts: int = 0
    last_encode_time: float = 0.0
    started: bool = False
    last_error: str = ""


class PyAVAnnotatedFramePublisher:
    """
    Per-camera publisher of annotated frames to MediaMTX over RTSP using PyAV.
    
    Lifecycle:
        p = PyAVAnnotatedFramePublisher(config)
        p.start()        # spawns PyAV NVENC encoder
        p.submit(y_plane_dlpack, uv_plane_dlpack, detections, lines, regions)
        ...
        p.stop()         # drains queue and terminates encoder cleanly
    
    Threading model:
        * submit() is called from the detection pipeline thread (per-camera
          ingestion worker). It is non-blocking; it enqueues the latest
          annotated NV12 planes using a size-2 queue (latest-wins).
        * The encode thread runs PyAV NVENC encoder.
        * Camera isolation: each publisher owns its own config, queue,
          thread, encoder and RTSP URL.
    """
    
    def __init__(
        self,
        config: PyAVAnnotatedPublisherConfig,
        time_func: Any = time.time,
    ) -> None:
        self.config = config
        self._time = time_func
        self._queue: "queue.Queue[Tuple[Any, Any, Optional[List], Optional[List], Optional[List]]]" = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()
        self._encode_thread: Optional[threading.Thread] = None
        self._encoder: Optional[Any] = None  # PyAVNVENCEncoder
        self._metrics = PyAVAnnotatedPublisherMetrics()
        self._camera_tag = config.camera_id
        
        # GPU annotation renderer (per-camera isolation)
        self._gpu_annotation_renderer = None
        if config.gpu_annotation_enabled:
            try:
                gpu_config = GPUAnnotationPyAVConfig(
                    enabled=True,
                    gpu_device=config.gpu_annotation_gpu_device,
                )
                self._gpu_annotation_renderer = get_gpu_annotation_pyav_renderer(config.camera_id, gpu_config)
                logger.info("PyAVAnnotatedFramePublisher(%s): GPU annotation renderer initialized", config.camera_id)
            except Exception as e:
                logger.warning("PyAVAnnotatedFramePublisher(%s): GPU annotation init failed: %s", config.camera_id, e)
                self._gpu_annotation_renderer = None
    
    def start(self) -> bool:
        """Start the PyAV NVENC encoder."""
        if self._metrics.started:
            logger.warning("PyAVAnnotatedFramePublisher(%s): already started", self.camera_id)
            return True
        
        logger.info("PyAVAnnotatedFramePublisher(%s): starting encoder", self.camera_id)
        
        try:
            encoder_config = PyAVNVENCEncoderConfig(
                camera_id=self.config.camera_id,
                rtsp_url=self.config.rtsp_url,
                width=self.config.width,
                height=self.config.height,
                fps=self.config.fps,
                video_bitrate_kbps=self.config.video_bitrate_kbps,
                gop_seconds=self.config.gop_seconds,
                max_restarts=self.config.max_restarts,
                restart_backoff_seconds=self.config.restart_backoff_seconds,
                nvenc_gpu_device=self.config.nvenc_gpu_device,
                nvenc_preset=self.config.nvenc_preset,
                nvenc_tune=self.config.nvenc_tune,
                nvenc_rc=self.config.nvenc_rc,
                nvenc_hw_frames=self.config.nvenc_hw_frames,
            )
            self._encoder = create_pyav_nvenc_encoder(**vars(encoder_config))
            if not self._encoder.start():
                logger.error("PyAVAnnotatedFramePublisher(%s): encoder start failed", self.camera_id)
                return False
        except Exception as e:
            self._metrics.last_error = f"Encoder init failed: {e}"
            logger.error("PyAVAnnotatedFramePublisher(%s): %s", self.camera_id, self._metrics.last_error)
            return False
        
        self._stop_event.clear()
        self._encode_thread = threading.Thread(
            target=self._encode_loop,
            name=f"pyav-publisher-{self.camera_id}",
            daemon=True,
        )
        self._encode_thread.start()
        
        self._metrics.started = True
        logger.info(
            "PyAVAnnotatedFramePublisher(%s): started (target=%s, %dx%d@%.1ffps)",
            self.camera_id,
            self.config.rtsp_url,
            self.config.width,
            self.config.height,
            self.config.fps,
        )
        return True
    
    def submit(
        self,
        y_plane_dlpack,
        uv_plane_dlpack,
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Submit NV12 planes (as DLPack capsules) and overlay metadata for encoding.

        The frames are NEVER downloaded to CPU. The DLPack capsules share GPU memory
        with the PyAV NVDEC output and GPU annotation surfaces.

        Returns True if the frame was accepted into the queue, False if dropped.
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False

        # Apply GPU annotation if enabled
        if self._gpu_annotation_renderer is not None:
            try:
                import torch
                # Convert DLPack to PyTorch tensors (zero-copy)
                y_tensor = torch.utils.dlpack.from_dlpack(y_plane_dlpack)
                uv_tensor = torch.utils.dlpack.from_dlpack(uv_plane_dlpack)

                # Annotate on GPU (modifies tensors in-place)
                annotated_y, annotated_uv = self._gpu_annotation_renderer.annotate_nv12(
                    y_plane=y_tensor,
                    uv_plane=uv_tensor,
                    detections=detections,
                    lines=lines,
                    regions=regions,
                    camera_id=self.camera_id,
                )

                # Convert back to DLPack for encoder
                y_plane_dlpack = torch.utils.dlpack.to_dlpack(annotated_y)
                uv_plane_dlpack = torch.utils.dlpack.to_dlpack(annotated_uv)

            except Exception as e:
                logger.error("PyAVAnnotatedFramePublisher(%s): GPU annotation failed: %s", self.camera_id, e)
                # Continue without annotation
                pass

        self._metrics.frames_submitted += 1

        # Latest-wins: replace the current queue head if full
        try:
            self._queue.put_nowait((y_plane_dlpack, uv_plane_dlpack, detections, lines, regions))
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((y_plane_dlpack, uv_plane_dlpack, detections, lines, regions))
                self._metrics.frames_dropped += 1
                return True
            except queue.Full:
                self._metrics.frames_dropped += 1
                return False

    def submit_from_pool(
        self,
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        H.10-C.3: Submit annotated frame from GPU surface pool for encoding.

        Reads the latest NV12 planes from the GPU surface pool, applies annotation,
        and queues for NVENC encoding. No DLPack capsules are passed - all data
        stays in the GPU surface pool (zero-copy).

        Returns True if the frame was accepted into the queue, False if dropped.
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False

        # Get NV12 planes from GPU surface pool
        from app.vision.gpu_4k_surface_pyav import get_gpu_4k_surface_pyav_pool
        pool = get_gpu_4k_surface_pyav_pool()
        if not pool.enabled:
            return False

        surface = pool.get_surface(self.camera_id)
        if surface is None:
            return False

        y_tensor, uv_tensor = surface.get_nv12_planes()
        if y_tensor is None or uv_tensor is None:
            return False

        # Apply GPU annotation if enabled
        if self._gpu_annotation_renderer is not None:
            try:
                import torch
                # Annotate on GPU (modifies tensors in-place)
                annotated_y, annotated_uv = self._gpu_annotation_renderer.annotate_nv12(
                    y_plane=y_tensor,
                    uv_plane=uv_tensor,
                    detections=detections,
                    lines=lines,
                    regions=regions,
                    camera_id=self.camera_id,
                )

                # Update surface pool with annotated frames
                surface.update_nv12_planes(annotated_y, annotated_uv)
            except Exception as e:
                logger.error("PyAVAnnotatedFramePublisher(%s): GPU annotation failed: %s", self.camera_id, e)
                # Continue without annotation
                pass

        # Convert to DLPack for encoder
        import torch
        y_plane_dlpack = torch.utils.dlpack.to_dlpack(y_tensor)
        uv_plane_dlpack = torch.utils.dlpack.to_dlpack(uv_tensor)

        self._metrics.frames_submitted += 1

        # Latest-wins: replace the current queue head if full
        try:
            self._queue.put_nowait((y_plane_dlpack, uv_plane_dlpack, detections, lines, regions))
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((y_plane_dlpack, uv_plane_dlpack, detections, lines, regions))
                self._metrics.frames_dropped += 1
                return True
            except queue.Full:
                self._metrics.frames_dropped += 1
                return False
    
    def _encode_loop(self) -> None:
        """Encode loop: pull frames from queue and submit to PyAV NVENC encoder."""
        while not self._stop_event.is_set():
            try:
                # Get frame data from queue
                try:
                    y_dlpack, uv_dlpack, detections, lines, regions = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                if self._encoder is None:
                    continue
                
                # Submit NV12 planes to encoder (zero-copy DLPack)
                success = self._encoder.submit_nv12_planes(y_dlpack, uv_dlpack)
                
                if success:
                    self._metrics.frames_encoded += 1
                    self._metrics.last_encode_time = self._time()
                
            except Exception as e:
                self._metrics.last_error = f"Encode loop error: {e}"
                logger.error("PyAVAnnotatedFramePublisher(%s): %s", self.camera_id, self._metrics.last_error)
                # Encoder handles its own restarts internally
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the publisher and encoder cleanly."""
        if not self._metrics.started:
            return
        
        logger.info("PyAVAnnotatedFramePublisher(%s): stopping", self.camera_id)
        self._stop_event.set()
        
        if self._encode_thread and self._encode_thread.is_alive():
            self._encode_thread.join(timeout=timeout)
        
        if self._encoder:
            try:
                self._encoder.stop(timeout=timeout)
            except Exception as e:
                logger.warning("PyAVAnnotatedFramePublisher(%s): encoder stop error: %s", self.camera_id, e)
            finally:
                self._encoder = None
        
        # Release GPU resources (H.9.6 — CUDA/VRAM lifecycle)
        if self._gpu_annotation_renderer is not None:
            try:
                self._gpu_annotation_renderer.reset()
            except Exception:
                pass
            self._gpu_annotation_renderer = None
        
        try:
            pool = get_gpu_4k_surface_pyav_pool()
            pool.reset_camera(self.camera_id)
        except Exception:
            pass
        
        self._metrics.started = False
        logger.info("PyAVAnnotatedFramePublisher(%s): stopped", self.camera_id)
    
    @property
    def camera_id(self) -> str:
        return self._camera_tag

    @property
    def started(self) -> bool:
        """H.10-C.3: True when the publisher is started and accepting frames."""
        return bool(self._metrics.started)

    def get_metrics(self) -> Dict[str, Any]:
        m = self._metrics
        out = {
            "camera_id": self.camera_id,
            "started": m.started,
            "frames_submitted": m.frames_submitted,
            "frames_encoded": m.frames_encoded,
            "frames_dropped": m.frames_dropped,
            "encoder_restarts": m.encoder_restarts,
            "last_encode_time": m.last_encode_time,
            "output_dimensions": [self.config.width, self.config.height],
            "target_fps": self.config.fps,
            "rtsp_url": self.config.rtsp_url,
            "last_error": m.last_error,
            "encode_backend": "pyav_nvenc",
            "gpu_annotation_enabled": self._gpu_annotation_renderer is not None,
        }
        
        if self._encoder:
            out["encoder"] = self._encoder.get_metrics()
        
        if self._gpu_annotation_renderer is not None:
            out["gpu_annotation"] = self._gpu_annotation_renderer.get_metrics()
        
        try:
            pool = get_gpu_4k_surface_pyav_pool()
            out["gpu_surface"] = pool.stats().get(self.camera_id)
        except Exception:
            pass
        
        return out


def create_pyav_annotated_publisher(
    camera_id: str,
    rtsp_url: Optional[str] = None,
    fps: float = 15.0,
    width: int = 3840,
    height: int = 2160,
    video_bitrate_kbps: int = 2500,
    nvenc_gpu_device: int = 0,
    nvenc_preset: str = "p1",
    nvenc_tune: str = "ll",
    nvenc_rc: str = "cbr",
    gpu_annotation_enabled: bool = True,
    gpu_annotation_gpu_device: int = 0,
) -> PyAVAnnotatedFramePublisher:
    """Factory for the PyAV annotated frame publisher."""
    if rtsp_url is None:
        rtsp_url = f"rtsp://localhost:8554/live/{camera_id.lower()}-ai"
    
    config = PyAVAnnotatedPublisherConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        width=width,
        height=height,
        fps=fps,
        video_bitrate_kbps=video_bitrate_kbps,
        nvenc_gpu_device=nvenc_gpu_device,
        nvenc_preset=nvenc_preset,
        nvenc_tune=nvenc_tune,
        nvenc_rc=nvenc_rc,
        gpu_annotation_enabled=gpu_annotation_enabled,
        gpu_annotation_gpu_device=gpu_annotation_gpu_device,
    )
    return PyAVAnnotatedFramePublisher(config=config)