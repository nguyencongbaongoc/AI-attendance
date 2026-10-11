"""
Phase R3.14-H.9 — GPU Pipeline Integration.

Integrates the 4K GPU surface with model preprocessing. This is the
central coordinator that:
1. Uploads NVDEC BGR24 frames to the 4K GPU surface
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
    # Annotation (always CPU for now)
    annotation_on_cpu: bool = True


@dataclass
class GPUPipelineMetrics:
    """Metrics for GPU pipeline operations."""
    frames_uploaded: int = 0
    yolo_preprocesses: int = 0
    scrfd_preprocesses: int = 0
    arcface_crops: int = 0
    reid_crops: int = 0
    total_upload_time_ms: float = 0.0
    total_yolo_time_ms: float = 0.0
    total_scrfd_time_ms: float = 0.0
    total_arcface_time_ms: float = 0.0
    total_reid_time_ms: float = 0.0
    upload_errors: int = 0


class GPUPipeline:
    """
    GPU pipeline integration coordinator.
    
    Manages the 4K GPU surface pool and provides preprocessing methods
    for all models. Each camera_id gets its own GPU surface.
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
            logger.info("GPUPipeline: disabled (CPU path)")
            return
        
        try:
            from app.vision.gpu_4k_surface import get_gpu_4k_surface_pool
            self._pool = get_gpu_4k_surface_pool()
            self._enabled = self._pool.enabled
            if self._enabled:
                logger.info("GPUPipeline: enabled (GPU-resident path)")
            else:
                logger.warning("GPUPipeline: CUDA not available, falling back to CPU path")
        except ImportError as e:
            logger.error(f"GPUPipeline: failed to import surface pool: {e}")
            self._enabled = False
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def upload_frame(
        self,
        camera_id: str,
        cpu_frame: np.ndarray,
    ) -> bool:
        """
        Upload CPU BGR frame to GPU surface.
        
        Args:
            camera_id: Camera identifier
            cpu_frame: BGR24 numpy array, shape (H, W, 3), uint8
        
        Returns:
            True if upload succeeded, False otherwise
        """
        if not self._enabled:
            return False
        
        if cpu_frame is None or not isinstance(cpu_frame, np.ndarray):
            return False
        
        t0 = time.perf_counter()
        
        try:
            surface = self._pool.get_surface(camera_id, cpu_frame.shape)
            if surface is None:
                self.metrics.upload_errors += 1
                return False
            
            surface.upload_from_cpu(cpu_frame)
            self.metrics.frames_uploaded += 1
            self.metrics.total_upload_time_ms += (time.perf_counter() - t0) * 1000
            return True
        except Exception as e:
            logger.error(f"GPUPipeline: upload failed for {camera_id}: {e}")
            self.metrics.upload_errors += 1
            return False
    
    def preprocess_yolo(
        self,
        camera_id: str,
    ) -> Optional["torch.Tensor"]:
        """
        Preprocess YOLO input from GPU surface.
        
        Returns:
            GPU tensor (1, 3, 640, 640) float32, or None if disabled/failed
        """
        if not self._enabled or not self.config.yolo_enabled:
            return None
        
        try:
            import torch
            from app.vision.gpu_roi_crop import gpu_resize_letterbox
            
            surface = self._pool.get_surface(camera_id, (2160, 3840, 3))
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            gpu_surface = surface.get_surface()
            
            # Letterbox resize to 640x640
            resized, scale, padding = gpu_resize_letterbox(
                gpu_surface,
                self.config.yolo_input_size,
                self.config.yolo_input_size,
                self.config.yolo_padding_value,
            )
            
            # Convert to float32, normalize to [0, 1], BGR->RGB
            tensor = resized.float() / 255.0
            
            # HWC -> CHW -> NCHW
            tensor = tensor.permute(2, 0, 1).unsqueeze(0)
            
            self.metrics.yolo_preprocesses += 1
            self.metrics.total_yolo_time_ms += (time.perf_counter() - t0) * 1000
            
            return tensor
        except Exception as e:
            logger.error(f"GPUPipeline: YOLO preprocess failed: {e}")
            return None
    
    def preprocess_scrfd(
        self,
        camera_id: str,
    ) -> Optional["torch.Tensor"]:
        """
        Preprocess SCRFD input from GPU surface.
        
        Returns:
            GPU tensor (1, 3, 640, 640) float32, or None if disabled/failed
        """
        if not self._enabled or not self.config.scrfd_enabled:
            return None
        
        try:
            import torch
            from app.vision.gpu_roi_crop import gpu_resize_letterbox
            
            surface = self._pool.get_surface(camera_id, (2160, 3840, 3))
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            gpu_surface = surface.get_surface()
            
            # Letterbox resize to 640x640
            resized, scale, padding = gpu_resize_letterbox(
                gpu_surface,
                self.config.scrfd_input_size,
                self.config.scrfd_input_size,
                self.config.scrfd_padding_value,
            )
            
            # SCRFD expects BGR, normalized with mean/std
            # Default SCRFD normalization: (127.5, 127.5, 127.5) mean, 128.0 std
            tensor = resized.float()
            mean = torch.tensor([127.5, 127.5, 127.5], device=tensor.device).view(1, 1, 3)
            std = torch.tensor([128.0, 128.0, 128.0], device=tensor.device).view(1, 1, 3)
            tensor = (tensor - mean) / std
            
            # HWC -> CHW -> NCHW
            tensor = tensor.permute(2, 0, 1).unsqueeze(0)
            
            self.metrics.scrfd_preprocesses += 1
            self.metrics.total_scrfd_time_ms += (time.perf_counter() - t0) * 1000
            
            return tensor
        except Exception as e:
            logger.error(f"GPUPipeline: SCRFD preprocess failed: {e}")
            return None
    
    def crop_arcface(
        self,
        camera_id: str,
        bbox: Tuple[float, float, float, float],
    ) -> Optional["torch.Tensor"]:
        """
        Crop ArcFace ROI from GPU surface.
        
        Args:
            camera_id: Camera identifier
            bbox: (x1, y1, x2, y2) in 4K coordinates
        
        Returns:
            GPU tensor (112, 112, 3) uint8, or None if disabled/failed
        """
        if not self._enabled or not self.config.arcface_enabled:
            return None
        
        try:
            from app.vision.gpu_roi_crop import crop_and_resize_gpu
            
            surface = self._pool.get_surface(camera_id, (2160, 3840, 3))
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            gpu_surface = surface.get_surface()
            
            result = crop_and_resize_gpu(
                gpu_surface,
                bbox,
                self.config.arcface_input_size,
                self.config.arcface_input_size,
            )
            
            self.metrics.arcface_crops += 1
            self.metrics.total_arcface_time_ms += (time.perf_counter() - t0) * 1000
            
            return result.tensor
        except Exception as e:
            logger.error(f"GPUPipeline: ArcFace crop failed: {e}")
            return None
    
    def crop_reid(
        self,
        camera_id: str,
        bbox: Tuple[float, float, float, float],
    ) -> Optional["torch.Tensor"]:
        """
        Crop ReID ROI from GPU surface.
        
        Args:
            camera_id: Camera identifier
            bbox: (x1, y1, x2, y2) in 4K coordinates
        
        Returns:
            GPU tensor (256, 128, 3) uint8, or None if disabled/failed
        """
        if not self._enabled or not self.config.reid_enabled:
            return None
        
        try:
            from app.vision.gpu_roi_crop import crop_and_resize_gpu
            
            surface = self._pool.get_surface(camera_id, (2160, 3840, 3))
            if surface is None:
                return None
            
            t0 = time.perf_counter()
            
            gpu_surface = surface.get_surface()
            
            result = crop_and_resize_gpu(
                gpu_surface,
                bbox,
                self.config.reid_input_size_h,
                self.config.reid_input_size_w,
            )
            
            self.metrics.reid_crops += 1
            self.metrics.total_reid_time_ms += (time.perf_counter() - t0) * 1000
            
            return result.tensor
        except Exception as e:
            logger.error(f"GPUPipeline: ReID crop failed: {e}")
            return None
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get pipeline metrics for diagnostics."""
        m = self.metrics
        return {
            "enabled": self._enabled,
            "frames_uploaded": m.frames_uploaded,
            "yolo_preprocesses": m.yolo_preprocesses,
            "scrfd_preprocesses": m.scrfd_preprocesses,
            "arcface_crops": m.arcface_crops,
            "reid_crops": m.reid_crops,
            "avg_upload_time_ms": (
                m.total_upload_time_ms / m.frames_uploaded
                if m.frames_uploaded > 0 else 0.0
            ),
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
            "upload_errors": m.upload_errors,
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
_PIPELINE: Optional[GPUPipeline] = None
_PIPELINE_LOCK = __import__("threading").Lock()


def get_gpu_pipeline(config: Optional[GPUPipelineConfig] = None) -> GPUPipeline:
    """Get the process-singleton GPU pipeline."""
    global _PIPELINE
    if _PIPELINE is None:
        with _PIPELINE_LOCK:
            if _PIPELINE is None:
                _PIPELINE = GPUPipeline(config)
    return _PIPELINE


def reset_gpu_pipeline() -> None:
    """Reset the process-singleton (for tests)."""
    global _PIPELINE
    with _PIPELINE_LOCK:
        if _PIPELINE is not None:
            _PIPELINE.reset_all()
        _PIPELINE = None
