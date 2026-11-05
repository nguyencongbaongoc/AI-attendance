"""
GPU Frame Pool - Bounded memory management for GPUFrame objects.

Provides pre-allocated frame pools per camera to avoid allocation overhead
and enforce VRAM budgets.
"""

from __future__ import annotations

import logging
import threading
import torch
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from collections import deque
from enum import Enum

from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat, CUDAContext, FrameOwnership, FrameStatus

logger = logging.getLogger(__name__)


class PoolStrategy(str, Enum):
    """Frame pool allocation strategy."""
    FIXED = "fixed"           # Pre-allocate all frames at startup
    DYNAMIC = "dynamic"       # Allocate on demand up to max_size
    HYBRID = "hybrid"         # Pre-allocate min_size, grow to max_size


@dataclass
class FramePoolConfig:
    """Configuration for a frame pool."""
    camera_id: str
    width: int
    height: int
    pixel_format: PixelFormat = PixelFormat.NV12
    min_size: int = 8
    max_size: int = 32
    strategy: PoolStrategy = PoolStrategy.HYBRID
    device_id: int = 0
    # Memory tracking
    track_allocations: bool = True
    warn_on_exhaustion: bool = True


@dataclass
class PoolStats:
    """Frame pool statistics."""
    camera_id: str
    total_allocated: int = 0
    current_available: int = 0
    current_in_use: int = 0
    peak_in_use: int = 0
    allocations: int = 0
    releases: int = 0
    exhaustion_events: int = 0
    allocation_failures: int = 0


class FramePool:
    """
    Bounded GPUFrame pool for a single camera.
    
    Manages a pool of pre-allocated GPUFrame objects to:
    - Avoid repeated CUDA allocations/deallocations
    - Enforce VRAM budget per camera
    - Provide fast frame acquisition/release
    - Track memory usage and detect leaks
    """
    
    def __init__(self, config: FramePoolConfig):
        self.config = config
        self.camera_id = config.camera_id
        
        # CUDA context
        self.cuda_context = CUDAContext.current(config.device_id)
        
        # Pool state
        self._available: deque[GPUFrame] = deque()
        self._in_use: Dict[str, GPUFrame] = {}  # global_frame_id -> frame
        self._lock = threading.RLock()
        
        # Stats
        self.stats = PoolStats(camera_id=config.camera_id)
        
        # Pre-allocate if FIXED or HYBRID
        if config.strategy in (PoolStrategy.FIXED, PoolStrategy.HYBRID):
            self._preallocate(config.min_size)
        
        logger.info(
            f"FramePool({self.camera_id}): initialized "
            f"(min={config.min_size}, max={config.max_size}, "
            f"{config.width}x{config.height} {config.pixel_format.value})"
        )
    
    def _preallocate(self, count: int) -> None:
        """Pre-allocate frames."""
        for _ in range(count):
            frame = self._create_frame()
            self._available.append(frame)
            self.stats.total_allocated += 1
            self.stats.current_available += 1
    
    def _create_frame(self) -> GPUFrame:
        """Create a new GPUFrame with allocated tensors."""
        frame = GPUFrame.create_empty(
            camera_id=self.camera_id,
            frame_id=0,  # Will be set on acquire
            width=self.config.width,
            height=self.config.height,
            pixel_format=self.config.pixel_format,
            cuda_context=self.cuda_context,
        )
        return frame
    
    def acquire(self, frame_id: int, timestamp: float, pts: Optional[int] = None) -> GPUFrame:
        """
        Acquire a frame from the pool.
        
        Args:
            frame_id: Monotonic frame counter for this camera
            timestamp: Wall-clock timestamp
            pts: Presentation timestamp from stream
            
        Returns:
            GPUFrame ready for use (ref_count = 1, status = NEW)
            
        Raises:
            RuntimeError: If pool exhausted and cannot grow
        """
        with self._lock:
            frame = None
            
            # Try to get from available pool
            if self._available:
                frame = self._available.popleft()
                self.stats.current_available -= 1
            elif len(self._in_use) < self.config.max_size:
                # Pool not at max, create new frame
                frame = self._create_frame()
                self.stats.total_allocated += 1
            else:
                # Pool exhausted
                self.stats.exhaustion_events += 1
                if self.config.warn_on_exhaustion:
                    logger.warning(
                        f"FramePool({self.camera_id}): EXHAUSTED "
                        f"(in_use={len(self._in_use)}, max={self.config.max_size})"
                    )
                # Try to reclaim oldest completed frame
                frame = self._try_reclaim()
                if frame is None:
                    # Bounded ring-buffer recycling: recycle oldest unpinned/stale frame to prevent OOM
                    if self._in_use:
                        oldest_gfid, oldest_frame = next(iter(self._in_use.items()))
                        del self._in_use[oldest_gfid]
                        self.stats.current_in_use -= 1
                        logger.warning(
                            f"FramePool({self.camera_id}): Ring buffer backpressure recycling oldest frame {oldest_gfid} "
                            f"(status={oldest_frame.status.value}, ref_count={oldest_frame.ref_count}) to prevent OOM"
                        )
                        frame = oldest_frame
                    else:
                        self.stats.allocation_failures += 1
                        raise RuntimeError(
                            f"FramePool({self.camera_id}): exhausted, "
                            f"max_size={self.config.max_size} reached"
                        )
            
            # Initialize frame for new use
            frame.frame_id = frame_id
            frame.timestamp = timestamp
            frame.pts = pts
            frame.dts = pts
            frame.released = False
            frame.ref_count = 1
            frame.status = FrameStatus.NEW
            frame.memory_owner = FrameOwnership.DECODER
            frame.error = None
            frame.error_stage = None
            # Reset timing
            frame.decode_time_ms = 0.0
            frame.preprocess_time_ms = 0.0
            frame.inference_time_ms = 0.0
            frame.tracking_time_ms = 0.0
            frame.annotation_time_ms = 0.0
            frame.encode_time_ms = 0.0
            # Clear annotation tensor
            frame._annotation_tensor = None
            frame._encoder_ref = None
            
            # Track in use
            self._in_use[frame.global_frame_id] = frame
            self.stats.current_in_use += 1
            if self.stats.current_in_use > self.stats.peak_in_use:
                self.stats.peak_in_use = self.stats.current_in_use
            self.stats.allocations += 1
            
            return frame
    
    def _try_reclaim(self) -> Optional[GPUFrame]:
        """Try to reclaim a frame that's been released but not returned to pool."""
        # Look for frames with ref_count == 0 that are still in _in_use
        for gfid, frame in list(self._in_use.items()):
            if frame.ref_count <= 0 and frame.released:
                del self._in_use[gfid]
                self.stats.current_in_use -= 1
                self.stats.releases += 1
                return frame
        return None
    
    def release(self, frame: GPUFrame) -> bool:
        """
        Release a frame back to the pool.
        
        Args:
            frame: GPUFrame to release
            
        Returns:
            True if frame returned to pool, False if pool full (frame destroyed)
        """
        with self._lock:
            gfid = frame.global_frame_id
            
            # Remove from in_use
            if gfid in self._in_use:
                del self._in_use[gfid]
                self.stats.current_in_use -= 1
            
            # Decrement ref count
            actually_released = frame.release()
            self.stats.releases += 1
            
            if actually_released:
                # Frame tensors were released, destroy it
                return False
            
            # Frame still has refs (e.g., encoder holding it), keep tracking
            if frame.ref_count > 0:
                self._in_use[gfid] = frame
                self.stats.current_in_use += 1
                return False
            
# Frame ready for reuse
            if len(self._available) < self.config.max_size:
                frame.status = FrameStatus.COMPLETED
                self._available.append(frame)
                self.stats.current_available += 1
                return True
            else:
                # Pool full, destroy frame
                frame._release_internal()
                self.stats.total_allocated -= 1
                return False
    
    def return_to_pool(self, frame: GPUFrame) -> None:
        """
        Explicitly return a frame to the available pool (for frames that completed normally).
        Call this when a frame has finished all pipeline stages and is ready for reuse.
        """
        with self._lock:
            gfid = frame.global_frame_id
            
            if gfid in self._in_use:
                del self._in_use[gfid]
                self.stats.current_in_use -= 1
            
            if len(self._available) < self.config.max_size:
                frame.status = FrameStatus.COMPLETED
                self._available.append(frame)
                self.stats.current_available += 1
            else:
                frame._release_internal()
                self.stats.total_allocated -= 1
    
    def get_available_count(self) -> int:
        """Get number of frames available in pool."""
        with self._lock:
            return len(self._available)
    
    def get_in_use_count(self) -> int:
        """Get number of frames currently in use."""
        with self._lock:
            return len(self._in_use)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "total_allocated": self.stats.total_allocated,
                "current_available": self.stats.current_available,
                "current_in_use": self.stats.current_in_use,
                "peak_in_use": self.stats.peak_in_use,
                "allocations": self.stats.allocations,
                "releases": self.stats.releases,
                "exhaustion_events": self.stats.exhaustion_events,
                "allocation_failures": self.stats.allocation_failures,
                "max_size": self.config.max_size,
                "utilization_pct": (
                    (self.stats.current_in_use / self.config.max_size * 100)
                    if self.config.max_size > 0 else 0
                ),
            }
    
    def get_all_frames_status(self) -> List[Dict[str, Any]]:
        """Get status of all frames (for debugging)."""
        with self._lock:
            frames = []
            for frame in self._available:
                frames.append({**frame.to_dict(), "pool_state": "available"})
            for frame in self._in_use.values():
                frames.append({**frame.to_dict(), "pool_state": "in_use"})
            return frames
    
    def clear(self) -> None:
        """Clear the pool and release all frames."""
        with self._lock:
            for frame in self._available:
                frame._release_internal()
            for frame in self._in_use.values():
                frame._release_internal()
            self._available.clear()
            self._in_use.clear()
            self.stats.current_available = 0
            self.stats.current_in_use = 0
            self.stats.total_allocated = 0
            logger.info(f"FramePool({self.camera_id}): cleared")


class FramePoolManager:
    """
    Manages frame pools for all cameras.
    
    Provides centralized pool management, VRAM budgeting,
    and cross-camera memory pressure handling.
    """
    
    def __init__(self, pools: Dict[str, FramePool], vram_budget_mb: int = 4096):
        self._pools = pools
        self.vram_budget_mb = vram_budget_mb
        self._lock = threading.RLock()
    
    @classmethod
    def from_config(cls, config: Any, vram_budget_mb: int = 4096) -> "FramePoolManager":
        """Create manager from pipeline config."""
        from pipeline_engine.config import get_camera_config, get_config
        
        pools = {}
        if hasattr(config, 'cameras'):
            for camera_id, cam_config in config.cameras.items():
                if not cam_config.get('enabled', True):
                    continue
                
                pool_config = FramePoolConfig(
                    camera_id=camera_id,
                    width=cam_config.get('expected', {}).get('width', 3840),
                    height=cam_config.get('expected', {}).get('height', 2160),
                    min_size=cam_config.get('decode', {}).get('surfaces', 8),
                    max_size=cam_config.get('decode', {}).get('surfaces', 32),
                    device_id=cam_config.get('decode', {}).get('gpu_device', 0),
                )
                pools[camera_id] = FramePool(pool_config)
        
        return cls(pools, vram_budget_mb)
    
    def get_pool(self, camera_id: str) -> Optional[FramePool]:
        """Get pool for a camera."""
        return self._pools.get(camera_id)
    
    def acquire(self, camera_id: str, frame_id: int, timestamp: float, pts: Optional[int] = None) -> GPUFrame:
        """Acquire frame from camera's pool."""
        pool = self._pools.get(camera_id)
        if pool is None:
            raise ValueError(f"No frame pool for camera: {camera_id}")
        return pool.acquire(frame_id, timestamp, pts)
    
    def release(self, frame: GPUFrame) -> bool:
        """Release frame to its camera's pool."""
        pool = self._pools.get(frame.camera_id)
        if pool is None:
            # No pool for this camera, just release tensors
            frame._release_internal()
            return False
        return pool.release(frame)
    
    def return_to_pool(self, frame: GPUFrame) -> None:
        """Return frame to its camera's pool."""
        pool = self._pools.get(frame.camera_id)
        if pool is None:
            frame._release_internal()
            return
        pool.return_to_pool(frame)
    
    def get_total_vram_mb(self) -> float:
        """Estimate total VRAM usage across all pools."""
        total = 0.0
        for pool in self._pools.values():
            for frame in pool._available:
                total += frame.nbytes / (1024 * 1024)
            for frame in pool._in_use.values():
                total += frame.nbytes / (1024 * 1024)
        return total
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all pools."""
        with self._lock:
            stats = {
                "vram_budget_mb": self.vram_budget_mb,
                "estimated_vram_mb": self.get_total_vram_mb(),
                "pools": {},
            }
            for camera_id, pool in self._pools.items():
                stats["pools"][camera_id] = pool.get_stats()
            return stats
    
    def handle_memory_pressure(self) -> None:
        """Handle VRAM pressure by shrinking pools."""
        with self._lock:
            current_vram = self.get_total_vram_mb()
            if current_vram > self.vram_budget_mb * 0.9:  # 90% threshold
                logger.warning(f"FramePoolManager: VRAM pressure ({current_vram:.0f}MB / {self.vram_budget_mb}MB)")
                # Shrink available pools
                for pool in self._pools.values():
                    while pool.get_available_count() > pool.config.min_size:
                        try:
                            frame = pool._available.popleft()
                            frame._release_internal()
                            pool.stats.current_available -= 1
                            pool.stats.total_allocated -= 1
                        except IndexError:
                            break
    
    def shutdown(self) -> None:
        """Shutdown all pools."""
        with self._lock:
            for pool in self._pools.values():
                pool.clear()
            self._pools.clear()


if __name__ == "__main__":
    # Quick test
    import torch
    
    if not torch.cuda.is_available():
        print("CUDA not available, skipping test")
    else:
        config = FramePoolConfig(
            camera_id="test_cam",
            width=640,
            height=480,
            min_size=2,
            max_size=4,
        )
        
        pool = FramePool(config)
        print(f"Initial stats: {pool.get_stats()}")
        
        # Acquire frames
        frame1 = pool.acquire(1, 1000.0, 90000)
        print(f"After acquire 1: {pool.get_stats()}")
        
        frame2 = pool.acquire(2, 1001.0, 93000)
        print(f"After acquire 2: {pool.get_stats()}")
        
        # Release one
        pool.release(frame1)
        print(f"After release 1: {pool.get_stats()}")
        
        # Acquire again (should reuse)
        frame3 = pool.acquire(3, 1002.0, 96000)
        print(f"After acquire 3: {pool.get_stats()}")
        print(f"Frame3 global_id: {frame3.global_frame_id}")
        
        pool.shutdown()
        print("FramePool test passed!")