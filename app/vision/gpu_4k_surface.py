"""
Phase R3.14-H.9 — GPU 4K Frame Surface.

Manages a single 4K GPU surface (CUDA memory) that serves as the authoritative
master frame for the entire GPU pipeline. The 4K surface is uploaded once
from CPU (NVDEC BGR24 pipe output) and reused across all downstream GPU
preprocessing branches (YOLO, SCRFD, ArcFace, ReID).

Architecture:

    NVDEC BGR24 (CPU) ───upload───> 4K GPU Surface (CUDA)
                                           │
                                           ├─> YOLO 640x640 GPU
                                           ├─> SCRFD 640x640 GPU
                                           ├─> ArcFace 112x112 GPU ROI
                                           └─> ReID 256x128 GPU ROI

Per-camera isolation: each camera_id has its own GPU surface, allocated
lazily on first use. Surfaces are reused (no per-frame allocation).
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class GPU4KFrameSurface:
    """
    Per-camera 4K GPU surface using PyTorch CUDA tensors.
    
    The surface is a single (H, W, 3) uint8 tensor on CUDA that holds the
    authoritative 4K master frame. It is uploaded from CPU BGR24 data
    (from NVDEC pipe) and reused across all model preprocessing branches.
    
    Per-camera isolation: one surface per camera_id, no sharing.
    Memory: ~24.9 MiB per surface at 3840x2160x3 uint8.
    """
    
    __slots__ = ("surface", "shape", "lock", "_dirty")
    
    def __init__(self, shape: Tuple[int, int, int]):
        """
        Initialize GPU surface.
        
        Args:
            shape: (H, W, C) tuple, typically (2160, 3840, 3)
        """
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available for GPU 4K surface")
        
        h, w = shape[0], shape[1]
        c = shape[2] if len(shape) > 2 else 3
        
        # Allocate GPU tensor directly (no CPU intermediate)
        self.surface = torch.empty((h, w, c), dtype=torch.uint8, device="cuda:0")
        self.shape = (h, w, c)
        self.lock = threading.Lock()
        self._dirty = False
    
    def upload_from_cpu(self, cpu_frame: np.ndarray) -> None:
        """
        Upload CPU BGR frame to GPU surface (overwrites existing data).
        
        This is the only H2D transfer in the optimized path. After this
        call, all downstream consumers read from the GPU surface without
        additional CPU↔GPU round trips.
        
        Args:
            cpu_frame: BGR24 numpy array, shape (H, W, 3), uint8
        """
        import torch
        
        if cpu_frame.shape != self.shape:
            raise ValueError(
                f"CPU frame shape {cpu_frame.shape} does not match "
                f"GPU surface shape {self.shape}"
            )
        
        with self.lock:
            # torch.from_numpy shares memory with numpy array, then .to() copies to GPU
            # This is the only H2D copy in the pipeline
            cpu_tensor = torch.from_numpy(cpu_frame)
            self.surface.copy_(cpu_tensor, non_blocking=True)
            self._dirty = True
    
    def get_surface(self):
        """Get the GPU surface tensor (read-only access)."""
        return self.surface
    
    def mark_clean(self) -> None:
        """Mark the surface as processed (for frame age tracking)."""
        with self.lock:
            self._dirty = False


class GPU4KFrameSurfacePool:
    """
    Process-singleton pool of per-camera 4K GPU surfaces.
    
    Each camera_id gets its own 4K GPU surface, allocated lazily on first use.
    Surfaces are NEVER shared between cameras (camera isolation contract).
    
    Usage:
        pool = get_gpu_4k_surface_pool()
        surface = pool.get_surface("CAM1", (2160, 3840, 3))
        surface.upload_from_cpu(bgr_frame)
        gpu_tensor = surface.get_surface()  # Use for YOLO, SCRFD, etc.
    """
    
    def __init__(self):
        self._surfaces: Dict[str, GPU4KFrameSurface] = {}
        self._global_lock = threading.Lock()
        self._enabled = False
        self._check_cuda()
    
    def _check_cuda(self) -> None:
        """Check if CUDA is available and enable the pool."""
        try:
            import torch
            if torch.cuda.is_available():
                self._enabled = True
                logger.info("GPU4KFrameSurfacePool: CUDA available, pool enabled")
            else:
                logger.warning("GPU4KFrameSurfacePool: CUDA not available, pool disabled")
        except ImportError:
            logger.warning("GPU4KFrameSurfacePool: torch not available, pool disabled")
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def get_surface(
        self, camera_id: str, shape: Tuple[int, int, int]
    ) -> Optional[GPU4KFrameSurface]:
        """
        Get the GPU surface for camera_id, allocating if needed.
        
        Args:
            camera_id: Camera identifier
            shape: (H, W, C) shape, typically (2160, 3840, 3)
        
        Returns:
            GPU4KFrameSurface instance, or None if CUDA is unavailable
        """
        if not self._enabled:
            return None
        
        # Fast path: camera known and shape matches
        surface = self._surfaces.get(camera_id)
        if surface is not None:
            if surface.shape == shape:
                return surface
            # Shape mismatch: reallocate
            with self._global_lock:
                del self._surfaces[camera_id]
                logger.info(
                    "GPU4KFrameSurfacePool: reallocating surface for %s (new shape=%s)",
                    camera_id, shape,
                )
        
        # Slow path: allocate new surface
        with self._global_lock:
            surface = self._surfaces.get(camera_id)
            if surface is None or surface.shape != shape:
                try:
                    surface = GPU4KFrameSurface(shape)
                    self._surfaces[camera_id] = surface
                    logger.info(
                        "GPU4KFrameSurfacePool: allocated 4K surface for %s shape=%s "
                        "(~%.1f MiB)",
                        camera_id, shape,
                        (shape[0] * shape[1] * shape[2]) / (1024 * 1024),
                    )
                except Exception as e:
                    logger.error(
                        "GPU4KFrameSurfacePool: failed to allocate surface for %s: %s",
                        camera_id, e,
                    )
                    return None
            return surface
    
    def reset_camera(self, camera_id: str) -> None:
        """Release the per-camera surface (e.g. on pipeline stop)."""
        with self._global_lock:
            surface = self._surfaces.pop(camera_id, None)
        if surface is not None:
            logger.info("GPU4KFrameSurfacePool: released surface for %s", camera_id)
    
    def reset_all(self) -> None:
        """Release all per-camera surfaces."""
        with self._global_lock:
            cams = list(self._surfaces.keys())
            self._surfaces.clear()
        for cam_id in cams:
            logger.info("GPU4KFrameSurfacePool: released surface for %s", cam_id)
    
    def stats(self) -> Dict[str, Tuple[int, int, int]]:
        """Return {camera_id: shape} for diagnostics."""
        with self._global_lock:
            return {
                cam_id: surface.shape
                for cam_id, surface in self._surfaces.items()
            }


# Process-singleton pool
_POOL: Optional[GPU4KFrameSurfacePool] = None
_POOL_LOCK = threading.Lock()


def get_gpu_4k_surface_pool() -> GPU4KFrameSurfacePool:
    """Return the process-singleton GPU4KFrameSurfacePool."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = GPU4KFrameSurfacePool()
    return _POOL


def reset_gpu_4k_surface_pool() -> None:
    """Drop the process-singleton (used in tests)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.reset_all()
        _POOL = None
