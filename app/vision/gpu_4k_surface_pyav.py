"""
Phase H.10-C.2 — GPU 4K Frame Surface for PyAV CUDA Frames.

Manages a single 4K GPU surface (CUDA memory) that serves as the authoritative
master frame for the entire GPU pipeline. The 4K surface receives CUDA-resident
frames from PyAV NVDEC via DLPack (zero-copy) and is reused across all downstream
GPU preprocessing branches (YOLO, SCRFD, ArcFace, ReID).

Architecture:

    RTSP H.264 4K
    → PyAV NVDEC → CUDA AVFrame (NV12, GPU, 2 planes)
    → DLPack (plane.__dlpack__())
    → GPU4KFrameSurfacePyAV (zero-copy GPU memory sharing)
                                            │
                                            ├─> YOLO 640x640 GPU
                                            ├─> SCRFD 640x640 GPU
                                            ├─> ArcFace 112x112 GPU ROI
                                            └─> ReID 256x128 GPU ROI

Per-camera isolation: each camera_id has its own GPU surface, allocated
lazily on first use. Surfaces are reused (no per-frame allocation).
Zero-copy: DLPack capsules share GPU memory with PyAV frames.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class GPU4KFrameSurfacePyAV:
    """
    Per-camera 4K GPU surface for PyAV CUDA frames via DLPack.
    
    The surface holds the authoritative 4K master frame as CUDA tensors
    (Y plane + UV plane) that share GPU memory with the PyAV NVDEC output
    via DLPack zero-copy interop.
    
    Per-camera isolation: one surface per camera_id, no sharing.
    Memory: ~12.5 MiB per surface at 3840x2160 NV12 (Y + UV planes).
    """
    
    __slots__ = ("y_plane", "uv_plane", "width", "height", "lock", "_initialized",
                 "_surface_id", "_ownership_pool", "_camera_id", "_generation")

    def __init__(self, width: int = 3840, height: int = 2160, camera_id: str = "unknown", generation: int = 0, telemetry_callback=None):
        """
        Initialize GPU surface for NV12 2-plane layout.

        Args:
            width: Frame width (default 3840 for 4K)
            height: Frame height (default 2160 for 4K)
            camera_id: Camera identifier for telemetry correlation
            generation: Encoder generation counter for restart correlation
            telemetry_callback: Optional callback for ownership state transitions
        """
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available for GPU 4K surface")

        self.width = width
        self.height = height
        self.lock = threading.Lock()
        self._initialized = False
        self._camera_id = camera_id
        self._generation = generation

        # Pre-allocate plane tensors (will be replaced by DLPack tensors on first frame)
        # Y plane: (H, W) uint8
        # UV plane: (H//2, W//2, 2) uint8 (interleaved)
        self.y_plane = torch.empty((height, width), dtype=torch.uint8, device="cuda:0")
        self.uv_plane = torch.empty((height // 2, width // 2, 2), dtype=torch.uint8, device="cuda:0")
        self._initialized = True
        # H.10-D.1: Per-surface ownership lease tracking
        # Phase 54: Use data_ptr() identity for tracking underlying GPU memory.
        # The surface identity combines a base identifier with the actual
        # CUDA allocation pointers. Note: the pre-allocated y_plane/uv_plane
        # are placeholders; on first DLPack update, the actual shared memory
        # identity will be established. We initialize with placeholder identity.
        def _t_data_ptr(t):
            return t.data_ptr() if hasattr(t, 'data_ptr') else id(t)
        self._surface_id = f"gpu4k_surf_{_t_data_ptr(self.y_plane)}_{_t_data_ptr(self.uv_plane)}"
        from app.vision.surface_ownership_pool import CUDAFrameOwnershipPool
        
        def _surface_telemetry(surface_id: str, frame_ref: str, state, ref_count: int, generation: int) -> None:
            """Telemetry callback for surface ownership state transitions."""
            try:
                from app.streaming.telemetry import get_telemetry, TelemetryEvent
                import time
                telemetry = get_telemetry()
                telemetry.emit(TelemetryEvent(
                    camera=self._camera_id,
                    frame_id=frame_ref,
                    surface_key=surface_id,
                    data_ptr=self.y_plane.data_ptr() if hasattr(self.y_plane, 'data_ptr') else 0,
                    generation=self._generation,
                    ownership_state=state.value if hasattr(state, 'value') else str(state),
                    ref_count=ref_count,
                    timestamp_monotonic=time.monotonic(),
                    timestamp_wall=time.time(),
                    event=f"SURFACE_{state.value.upper()}" if hasattr(state, 'value') else f"SURFACE_{str(state).upper()}",
                ))
            except Exception:
                # Telemetry must never crash the production pipeline
                pass
        
        self._ownership_pool = CUDAFrameOwnershipPool(telemetry_callback=_surface_telemetry)
        self._ownership_pool.register_surface(self._surface_id)
        logger.info(f"GPU4KFrameSurfacePyAV: allocated for {width}x{height} NV12 (camera={camera_id}, gen={generation})")

    def update_from_dlpack(self, dlpack_y, dlpack_uv) -> None:
        """
        Update GPU surface from PyAV CUDA frame DLPack capsules.
        
        Zero-copy: The DLPack capsules share GPU memory with PyAV frame planes.
        We convert to PyTorch tensors that share the same underlying memory.
        
        Args:
            dlpack_y: DLPack capsule for Y plane (shape: H x W)
            dlpack_uv: DLPack capsule for UV plane (shape: H/2 x W/2 x 2)
        """
        import torch
        import torch.utils.dlpack
        
        with self.lock:
            # H.10-D.1: Before updating this surface, verify it is not
            # still IN_FLIGHT from a previous encoder reference. If the
            # surface is not available for reuse, reject the update.
            if not self._ownership_pool.is_available_for_reuse(self._surface_id):
                logger.warning(
                    f"GPU4KFrameSurfacePyAV({self._surface_id}): "
                    f"Surface not available for reuse (IN_FLIGHT/RELEASABLE); "
                    f"update rejected. Waiting for release boundary."
                )
                # Do not overwrite; keep previous safe state
                return

            # Convert DLPack capsules to PyTorch CUDA tensors (zero-copy)
            # These tensors share the exact same GPU memory as the PyAV frame
            y_tensor = torch.utils.dlpack.from_dlpack(dlpack_y)
            uv_tensor = torch.utils.dlpack.from_dlpack(dlpack_uv)
            
            # Validate shapes
            expected_y_shape = (self.height, self.width)
            expected_uv_shape = (self.height // 2, self.width // 2, 2)
            
            if y_tensor.shape != expected_y_shape:
                logger.warning(
                    f"GPU4KFrameSurfacePyAV: Y plane shape mismatch: "
                    f"got {y_tensor.shape}, expected {expected_y_shape}"
                )
                # Resize if needed (should not happen in production)
                self.y_plane = torch.empty(expected_y_shape, dtype=torch.uint8, device="cuda:0")
            
            if uv_tensor.shape != expected_uv_shape:
                logger.warning(
                    f"GPU4KFrameSurfacePyAV: UV plane shape mismatch: "
                    f"got {uv_tensor.shape}, expected {expected_uv_shape}"
                )
                self.uv_plane = torch.empty(expected_uv_shape, dtype=torch.uint8, device="cuda:0")
            
            # Replace surface tensors with DLPack-backed tensors (zero-copy)
            # Note: We keep references to prevent PyAV frame GC until next frame
            self.y_plane = y_tensor
            self.uv_plane = uv_tensor

            # H.10-D.1: After update, this surface is now SUBMITTED.
            # It must not be considered AVAILABLE for reuse until an explicit
            # release boundary (flush or restart) transitions it back.
            # The call site (publisher/annotation) should submit to encoder.
            # We do NOT mark available here; the release must come from encoder.
            self._ownership_pool.submit_encoder(self._surface_id)
    
    def get_y_plane(self):
        """Get the Y plane tensor (H, W) uint8 on CUDA."""
        return self.y_plane
    
    def get_uv_plane(self):
        """Get the UV plane tensor (H/2, W/2, 2) uint8 on CUDA."""
        return self.uv_plane
    
    def get_bgr_surface(self):
        """
        Get the full frame as BGR tensor for backward compatibility.
        
        This does NV12->BGR conversion on GPU. Use only when BGR is required.
        For zero-copy path, use get_y_plane() and get_uv_plane() directly.
        """
        import torch
        from app.vision.gpu_nv12_to_bgr import nv12_to_bgr_gpu
        
        with self.lock:
            return nv12_to_bgr_gpu(self.y_plane, self.uv_plane)
    
    def get_nv12_planes(self) -> Tuple["torch.Tensor", "torch.Tensor"]:
        """Get both NV12 planes (Y, UV) for direct NVENC input."""
        with self.lock:
            return self.y_plane, self.uv_plane

    def update_nv12_planes(self, y_tensor, uv_tensor) -> None:
        """H.10-C.3: Update surface planes with annotated tensors (zero-copy)."""
        with self.lock:
            self.y_plane = y_tensor
            self.uv_plane = uv_tensor

    def snapshot_ownership(self) -> dict:
        """
        Lock-safe snapshot of surface ownership state.

        Acquires the lock briefly, copies immutable scalar telemetry,
        releases the lock, then returns the snapshot.

        Returns:
            dict with surface_key, data_ptr, camera, frame_id, generation,
            ownership_state, ref_count
        """
        with self.lock:
            # Get data_ptr from the Y plane tensor (actual CUDA allocation)
            y_ptr = self.y_plane.data_ptr() if hasattr(self.y_plane, 'data_ptr') else id(self.y_plane)

            # Get ownership state from the pool
            ownership_state = "unknown"
            ref_count = 0
            frame_ref = "unknown"
            if self._ownership_pool is not None:
                lease = self._ownership_pool._leases.get(self._surface_id)
                if lease is not None:
                    ownership_state = lease.state.value
                    ref_count = lease.ref_count
                    frame_ref = lease.frame_ref

            return {
                "surface_key": self._surface_id,
                "data_ptr": y_ptr,
                "camera": self._camera_id,
                "frame_id": frame_ref,
                "generation": self._generation,
                "ownership_state": ownership_state,
                "ref_count": ref_count,
            }

    def set_generation(self, generation: int) -> None:
        """Update the generation counter (called on encoder restart)."""
        with self.lock:
            self._generation = generation


class GPU4KFrameSurfacePyAVPool:
    """
    Process-singleton pool of per-camera 4K GPU surfaces for PyAV CUDA frames.
    
    Each camera_id gets its own 4K GPU surface, allocated lazily on first use.
    Surfaces are NEVER shared between cameras (camera isolation contract).
    
    Usage:
        pool = get_gpu_4k_surface_pyav_pool()
        surface = pool.get_surface("CAM1", 3840, 2160)
        surface.update_from_dlpack(dlpack_y, dlpack_uv)
        y_plane, uv_plane = surface.get_nv12_planes()  # For NVENC
        yolo_tensor = surface.get_y_plane()  # For YOLO preprocessing
    """
    
    def __init__(self):
        self._surfaces: Dict[str, GPU4KFrameSurfacePyAV] = {}
        self._global_lock = threading.Lock()
        self._enabled = False
        self._generation = 0
        self._check_cuda()
    
    def _check_cuda(self) -> None:
        """Check if CUDA is available and enable the pool."""
        try:
            import torch
            if torch.cuda.is_available():
                self._enabled = True
                logger.info("GPU4KFrameSurfacePyAVPool: CUDA available, pool enabled")
            else:
                logger.warning("GPU4KFrameSurfacePyAVPool: CUDA not available, pool disabled")
        except ImportError:
            logger.warning("GPU4KFrameSurfacePyAVPool: torch not available, pool disabled")
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def get_surface(
        self, camera_id: str, width: int = 3840, height: int = 2160
    ) -> Optional[GPU4KFrameSurfacePyAV]:
        """
        Get the GPU surface for camera_id, allocating if needed.
        
        Args:
            camera_id: Camera identifier
            width: Frame width
            height: Frame height
        
        Returns:
            GPU4KFrameSurfacePyAV instance, or None if CUDA is unavailable
        """
        if not self._enabled:
            return None
        
        # Fast path: camera known
        surface = self._surfaces.get(camera_id)
        if surface is not None:
            if surface.width == width and surface.height == height:
                # Safety: only return if reusable and matches current generation.
                # IN_FLIGHT / SUBMITTED / stale-generation surfaces must NOT be reused.
                if surface._ownership_pool.is_available_for_reuse(surface._surface_id) and surface._generation == self._generation:
                    return surface
                # Unsafe to reuse; fall through. We do not delete; fall through to reallocate/replacement
            # Shape mismatch: reallocate
            with self._global_lock:
                del self._surfaces[camera_id]
                logger.info(
                    "GPU4KFrameSurfacePyAVPool: reallocating surface for %s (new shape=%dx%d)",
                    camera_id, width, height,
                )
        
        # Slow path: allocate new surface
        with self._global_lock:
            surface = self._surfaces.get(camera_id)
            if surface is None or surface.width != width or surface.height != height:
                try:
                    surface = GPU4KFrameSurfacePyAV(width, height, camera_id=camera_id, generation=self._generation)
                    self._surfaces[camera_id] = surface
                    logger.info(
                        "GPU4KFrameSurfacePyAVPool: allocated 4K surface for %s %dx%d "
                        "(~%.1f MiB NV12)",
                        camera_id, width, height,
                        (width * height * 3 // 2) / (1024 * 1024),
                    )
                except Exception as e:
                    logger.error(
                        "GPU4KFrameSurfacePyAVPool: failed to allocate surface for %s: %s",
                        camera_id, e,
                    )
                    return None
            return surface
    
    def reset_camera(self, camera_id: str) -> None:
        """Release the per-camera surface (e.g. on pipeline stop)."""
        with self._global_lock:
            surface = self._surfaces.pop(camera_id, None)
        if surface is not None:
            logger.info("GPU4KFrameSurfacePyAVPool: released surface for %s", camera_id)
    
    def reset_all(self) -> None:
        """Release all per-camera surfaces."""
        with self._global_lock:
            cams = list(self._surfaces.keys())
            self._surfaces.clear()
        for cam_id in cams:
            logger.info("GPU4KFrameSurfacePyAVPool: released surface for %s", cam_id)

    def increment_generation(self) -> int:
        """
        Increment the generation counter (called on encoder restart).
        Also updates all existing surfaces to the new generation.
        """
        with self._global_lock:
            self._generation += 1
            new_gen = self._generation
            for surface in self._surfaces.values():
                surface.set_generation(new_gen)
            logger.info(f"GPU4KFrameSurfacePyAVPool: generation incremented to {new_gen}")
        return new_gen
    
    def stats(self) -> Dict[str, Tuple[int, int]]:
        """Return {camera_id: (width, height)} for diagnostics."""
        with self._global_lock:
            return {
                cam_id: (surface.width, surface.height)
                for cam_id, surface in self._surfaces.items()
            }


# Process-singleton pool
_POOL: Optional[GPU4KFrameSurfacePyAVPool] = None
_POOL_LOCK = threading.Lock()


def get_gpu_4k_surface_pyav_pool() -> GPU4KFrameSurfacePyAVPool:
    """Return the process-singleton GPU4KFrameSurfacePyAVPool."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = GPU4KFrameSurfacePyAVPool()
    return _POOL


def reset_gpu_4k_surface_pyav_pool() -> None:
    """Drop the process-singleton (used in tests)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.reset_all()
        _POOL = None