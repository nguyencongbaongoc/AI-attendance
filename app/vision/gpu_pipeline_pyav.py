"""
Phase H.10-C.2 — GPU Pipeline Integration for PyAV CUDA Frames.

Integrates the 4K GPU surface with model preprocessing. This is the
central coordinator that:
1. Receives PyAV CUDA frames via DLPack (zero-copy)
2. Provides GPU-resident preprocessing for YOLO (640x640), SCRFD (640x640)
3. Provides GPU ROI crop for ArcFace (112x112) and ReID (256x128)
4. Returns GPU tensors ready for model inference

The integration is feature-flagged via settings. The default is the
existing CPU path; enabling `gpu_pipeline_enabled` switches to the
GPU-resident path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GPUPipelineConfig:
    """Configuration for the GPU pipeline integration."""
    enabled: bool = False
    gpu_device: int = 0
    # YOLO preprocessing
    yolo_enabled: bool = True
    yolo_input_size: int = 640
    yolo_padding_value: int = 114
    # SCRFD preprocessing
    scrfd_enabled: bool = True
    scrfd_input_size: int = 640
    scrfd_padding_value: int = 0
    # ArcFace ROI crop
    arcface_enabled: bool = True
    arcface_input_size: int = 112
    # ReID ROI crop
    reid_enabled: bool = True
    reid_input_size_h: int = 256
    reid_input_size_w: int = 128
    # Annotation
    annotation_on_cpu: bool = True


@dataclass
class GPUPipelineMetrics:
    """Metrics for GPU pipeline operations."""
    frames_processed: int = 0
    yolo_preprocesses: int = 0
    scrfd_preprocesses: int = 0
    arcface_crops: int = 0
    reid_crops: int = 0
    total_yolo_time_ms: float = 0.0
    total_scrfd_time_ms: float = 0.0
    total_arcface_time_ms: float = 0.0
    total_reid_time_ms: float = 0.0
    errors: int = 0


class GPUPipelinePyAV:
    """
    GPU pipeline integration coordinator for PyAV CUDA frames.
    
    Manages the 4K GPU surface pool and provides preprocessing methods
    for all models. Each camera_id gets its own GPU surface.
    
    Zero-copy path:
    - PyAV NVDEC → CUDA AVFrame (NV12, GPU)
    - DLPack capsules from frame planes
    - GPUPipelinePyAV.update_from_dlpack() (zero-copy GPU memory sharing)
    - GPU preprocessing (YOLO, SCRFD, ArcFace, ReID) directly on CUDA tensors
    """
    
    def __init__(self, config: Optional[GPUPipelineConfig] = None):
        self.config = config or GPUPipelineConfig()
        self.metrics = GPUPipelineMetrics()
        self._pool = None
        self._enabled = False
        self._init_pool()
    
    def _init_pool(self) -> None:
        """Initialize the GPU surface pool if enabled."""
        if not self.config.enabled:
            logger.info("GPUPipelinePyAV: disabled (CPU path)")
            return
        
        try:
            from app.vision.gpu_4k_surface_pyav import get_gpu_4k_surface_pyav_pool
            self._pool = get_gpu_4k_surface_pyav_pool()
            self._enabled = self._pool.enabled
            if self._enabled:
                logger.info("GPUPipelinePyAV: enabled (zero-copy GPU-resident path)")
            else:
                logger.warning("GPUPipelinePyAV: CUDA not available, falling back to CPU path")
        except ImportError as e:
            logger.error(f"GPUPipelinePyAV: failed to import surface pool: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def update_from_dlpack(
        self,
        camera_id: str,
        dlpack_y,
        dlpack_uv,
        width: int = 3840,
        height: int = 2160,
    ) -> bool:
        """
        Update GPU surface from PyAV CUDA frame DLPack capsules (zero-copy).
        
        Args:
            camera_id: Camera identifier
            dlpack_y: DLPack capsule for Y plane
            dlpack_uv: DLPack capsule for UV plane
            width: Frame width
            height: Frame height
        
        Returns:
            True if update succeeded, False otherwise
        """
        if not self._enabled:
            return False
        
        try:
            surface = self._pool.get_surface(camera_id, width, height)
            if surface is None:
                self.metrics.errors += 1
                return False
            
            surface.update_from_dlpack(dlpack_y, dlpack_uv)
            self.metrics.frames_processed += 1
            return True
        except Exception as e:
            logger.error(f"GPUPipelinePyAV: update failed for {camera_id}: {e}")
            self.metrics.errors += 1
            return False
    
    def update_from_frame_data(
        self,
        camera_id: str,
        frame_data: Dict,
    ) -> bool:
        """
        Update GPU surface from VideoFrameIterator frame_data dict.
        
        Args:
            camera_id: Camera identifier
            frame_data: Dict with keys: dlpack_y, dlpack_uv, width, height
        
        Returns:
            True if update succeeded, False otherwise
        """
        if not isinstance(frame_data, dict):
            return False
        
        dlpack_y = frame_data.get("dlpack_y")
        dlpack_uv = frame_data.get("dlpack_uv")
        width = frame_data.get("width", 3840)
        height = frame_data.get("height", 2160)
        
        if dlpack_y is None or dlpack_uv is None:
            return False
        
        return self.update_from_dlpack(camera_id, dlpack_y, dlpack_uv, width, height)
    
    def preprocess_yolo(
        self,
        camera_id: str,
    ) -> Optional["torch.Tensor"]:
        """
        Preprocess YOLO input from GPU surface (NV12 planes).
        
        Returns:
            GPU tensor (1, 3, 640, 640) float32 RGB normalized [0,1], or None if disabled/failed
        """
        if not self._enabled or not self.config.yolo_enabled:
            return None
        
        try:
            import torch
            from app.vision.gpu_nv12_to_bgr import nv12_to_bgr_tensor_letterbox
            
            surface = self._pool.get_surface(camera_id, 3840, 2160)
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            y_plane = surface.get_y_plane()
            uv_plane = surface.get_uv_plane()
            
            # Letterbox resize to 640x640 with BGR conversion on GPU
            bgr_resized, scale, padding = nv12_to_bgr_tensor_letterbox(
                y_plane,
                uv_plane,
                self.config.yolo_input_size,
                self.config.yolo_padding_value,
            )
            
            # Convert to float32, normalize to [0, 1], BGR->RGB
            tensor = bgr_resized.float() / 255.0
            # BGR to RGB
            tensor = tensor.flip(dims=[2])
            
            # HWC -> CHW -> NCHW
            tensor = tensor.permute(2, 0, 1).unsqueeze(0)
            
            self.metrics.yolo_preprocesses += 1
            self.metrics.total_yolo_time_ms += (time.perf_counter() - t0) * 1000
            
            return tensor
        except Exception as e:
            logger.error(f"GPUPipelinePyAV: YOLO preprocess failed: {e}")
            self.metrics.errors += 1
            return None
    
    def preprocess_scrfd(
        self,
        camera_id: str,
    ) -> Optional["torch.Tensor"]:
        """
        Preprocess SCRFD input from GPU surface (NV12 planes).
        
        Returns:
            GPU tensor (1, 3, 640, 640) float32 BGR normalized with mean/std, or None if disabled/failed
        """
        if not self._enabled or not self.config.scrfd_enabled:
            return None
        
        try:
            import torch
            from app.vision.gpu_nv12_to_bgr import nv12_to_bgr_tensor_letterbox
            
            surface = self._pool.get_surface(camera_id, 3840, 2160)
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            y_plane = surface.get_y_plane()
            uv_plane = surface.get_uv_plane()
            
            # Letterbox resize to 640x640 with BGR conversion on GPU
            bgr_resized, scale, padding = nv12_to_bgr_tensor_letterbox(
                y_plane,
                uv_plane,
                self.config.scrfd_input_size,
                self.config.scrfd_padding_value,
            )
            
            # SCRFD expects BGR, normalized with mean/std
            # Default SCRFD normalization: (127.5, 127.5, 127.5) mean, 128.0 std
            tensor = bgr_resized.float()
            mean = torch.tensor([127.5, 127.5, 127.5], device=tensor.device).view(1, 1, 3)
            std = torch.tensor([128.0, 128.0, 128.0], device=tensor.device).view(1, 1, 3)
            tensor = (tensor - mean) / std
            
            # HWC -> CHW -> NCHW
            tensor = tensor.permute(2, 0, 1).unsqueeze(0)
            
            self.metrics.scrfd_preprocesses += 1
            self.metrics.total_scrfd_time_ms += (time.perf_counter() - t0) * 1000
            
            return tensor
        except Exception as e:
            logger.error(f"GPUPipelinePyAV: SCRFD preprocess failed: {e}")
            self.metrics.errors += 1
            return None
    
    def crop_arcface(
        self,
        camera_id: str,
        bbox: Tuple[float, float, float, float],
    ) -> Optional["torch.Tensor"]:
        """
        Crop ArcFace ROI from GPU surface (NV12 planes).
        
        Args:
            camera_id: Camera identifier
            bbox: (x1, y1, x2, y2) in 4K coordinates
        
        Returns:
            GPU tensor (112, 112, 3) uint8 BGR, or None if disabled/failed
        """
        if not self._enabled or not self.config.arcface_enabled:
            return None
        
        try:
            from app.vision.gpu_nv12_to_bgr import nv12_crop_and_resize_gpu
            
            surface = self._pool.get_surface(camera_id, 3840, 2160)
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            y_plane = surface.get_y_plane()
            uv_plane = surface.get_uv_plane()
            
            result = nv12_crop_and_resize_gpu(
                y_plane,
                uv_plane,
                bbox,
                self.config.arcface_input_size,
                self.config.arcface_input_size,
            )
            
            self.metrics.arcface_crops += 1
            self.metrics.total_arcface_time_ms += (time.perf_counter() - t0) * 1000
            
            return result
        except Exception as e:
            logger.error(f"GPUPipelinePyAV: ArcFace crop failed: {e}")
            self.metrics.errors += 1
            return None
    
    def crop_reid(
        self,
        camera_id: str,
        bbox: Tuple[float, float, float, float],
    ) -> Optional["torch.Tensor"]:
        """
        Crop ReID ROI from GPU surface (NV12 planes).
        
        Args:
            camera_id: Camera identifier
            bbox: (x1, y1, x2, y2) in 4K coordinates
        
        Returns:
            GPU tensor (256, 128, 3) uint8 BGR, or None if disabled/failed
        """
        if not self._enabled or not self.config.reid_enabled:
            return None
        
        try:
            from app.vision.gpu_nv12_to_bgr import nv12_crop_and_resize_gpu
            
            surface = self._pool.get_surface(camera_id, 3840, 2160)
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            y_plane = surface.get_y_plane()
            uv_plane = surface.get_uv_plane()
            
            result = nv12_crop_and_resize_gpu(
                y_plane,
                uv_plane,
                bbox,
                self.config.reid_input_size_h,
                self.config.reid_input_size_w,
            )
            
            self.metrics.reid_crops += 1
            self.metrics.total_reid_time_ms += (time.perf_counter() - t0) * 1000
            
            return result
        except Exception as e:
            logger.error(f"GPUPipelinePyAV: ReID crop failed: {e}")
            self.metrics.errors += 1
            return None
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get pipeline metrics for diagnostics."""
        m = self.metrics
        return {
            "enabled": self._enabled,
            "frames_processed": m.frames_processed,
            "yolo_preprocesses": m.yolo_preprocesses,
            "scrfd_preprocesses": m.scrfd_preprocesses,
            "arcface_crops": m.arcface_crops,
            "reid_crops": m.reid_crops,
            "avg_yolo_time_ms": (
                m.total_yolo_time_ms / m.yolo_preprocesses
                if m.yolo_preprocesses > 0 else 0.0
            ),
            "avg_scrfd_time_ms": (
                m.total_scrfd_time_ms / m.scrfd_preprocesses
                if m.scrfd_preprocesses > 0 else 0.0
            ),
            "avg_arcface_time_ms": (
                m.total_arcface_time_ms / m.arcface_crops
                if m.arcface_crops > 0 else 0.0
            ),
            "avg_reid_time_ms": (
                m.total_reid_time_ms / m.reid_crops
                if m.reid_crops > 0 else 0.0
            ),
            "errors": m.errors,
        }
    
    def reset_camera(self, camera_id: str) -> None:
        """Release the per-camera GPU surface."""
        if self._pool:
            self._pool.reset_camera(camera_id)
    
    def reset_all(self) -> None:
        """Release all per-camera GPU surfaces."""
        if self._pool:
            self._pool.reset_all()


# Process-singleton
_PIPELINE_PYAV: Optional[GPUPipelinePyAV] = None
_PIPELINE_PYAV_LOCK = __import__("threading").Lock()


def get_gpu_pipeline_pyav(config: Optional[GPUPipelineConfig] = None) -> GPUPipelinePyAV:
    """Get the process-singleton GPU pipeline for PyAV frames."""
    global _PIPELINE_PYAV
    if _PIPELINE_PYAV is None:
        with _PIPELINE_PYAV_LOCK:
            if _PIPELINE_PYAV is None:
                _PIPELINE_PYAV = GPUPipelinePyAV(config)
    return _PIPELINE_PYAV


def reset_gpu_pipeline_pyav() -> None:
    """Reset the process-singleton (for tests)."""
    global _PIPELINE_PYAV
    with _PIPELINE_PYAV_LOCK:
        if _PIPELINE_PYAV is not None:
            _PIPELINE_PYAV.reset_all()
        _PIPELINE_PYAV = None