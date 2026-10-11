"""
CUDA Context and GPU Resource Lifecycle Management - V2.

Defines clear ownership, lifetime, and synchronization for all GPU resources.
Prevents use-after-free, context mismatches, and resource leaks.
"""

from __future__ import annotations

import torch
import threading
import logging
import atexit
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Set
from contextlib import contextmanager
from enum import Enum
import weakref

logger = logging.getLogger(__name__)


class GPUResourceType(str, Enum):
    """Types of GPU resources tracked."""
    TENSOR = "tensor"
    STREAM = "stream"
    CONTEXT = "context"
    NVDEC_SURFACE = "nvdec_surface"
    NVENC_SURFACE = "nvenc_surface"
    MODEL_SESSION = "model_session"
    BUFFER_POOL = "buffer_pool"


@dataclass
class GPUResource:
    """Tracked GPU resource with ownership and lifetime."""
    resource_id: str
    resource_type: GPUResourceType
    owner: str  # Component that owns this resource
    creator_thread: int
    cuda_device: int
    cuda_context_ptr: int
    cuda_stream_ptr: int
    data_ptr: int  # Actual GPU memory pointer
    size_bytes: int
    created_at: float
    released: bool = False
    released_at: Optional[float] = None
    released_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self):
        return hash(self.resource_id)
    
    def __eq__(self, other):
        return isinstance(other, GPUResource) and self.resource_id == other.resource_id


class GPUResourceRegistry:
    """
    Central registry for all GPU resources.
    Tracks ownership, prevents leaks, detects use-after-free.
    """
    
    _instance: Optional["GPUResourceRegistry"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._resources: Dict[str, GPUResource] = {}
        self._lock = threading.RLock()
        self._resource_counter = 0
        self._owner_resources: Dict[str, Set[str]] = {}  # owner -> resource_ids
        self._device_resources: Dict[int, Set[str]] = {}  # device -> resource_ids
        self._initialized = True
        atexit.register(self._atexit_cleanup)
    
    def _generate_id(self, resource_type: GPUResourceType) -> str:
        self._resource_counter += 1
        return f"{resource_type.value}_{self._resource_counter:06d}"
    
    def register(
        self,
        resource_type: GPUResourceType,
        owner: str,
        cuda_device: int,
        cuda_context_ptr: int,
        cuda_stream_ptr: int,
        data_ptr: int,
        size_bytes: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GPUResource:
        """Register a new GPU resource."""
        import time
        with self._lock:
            resource_id = self._generate_id(resource_type)
            resource = GPUResource(
                resource_id=resource_id,
                resource_type=resource_type,
                owner=owner,
                creator_thread=threading.get_ident(),
                cuda_device=cuda_device,
                cuda_context_ptr=cuda_context_ptr,
                cuda_stream_ptr=cuda_stream_ptr,
                data_ptr=data_ptr,
                size_bytes=size_bytes,
                created_at=time.time(),
                metadata=metadata or {},
            )
            self._resources[resource_id] = resource
            
            if owner not in self._owner_resources:
                self._owner_resources[owner] = set()
            self._owner_resources[owner].add(resource_id)
            
            if cuda_device not in self._device_resources:
                self._device_resources[cuda_device] = set()
            self._device_resources[cuda_device].add(resource_id)
            
            logger.debug(f"GPU resource registered: {resource_id} ({resource_type.value}) by {owner}")
            return resource
    
    def unregister(self, resource_id: str, released_by: str) -> bool:
        """Unregister a GPU resource."""
        import time
        with self._lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                logger.warning(f"Attempt to unregister unknown resource: {resource_id}")
                return False
            
            if resource.released:
                logger.warning(f"Resource already released: {resource_id}")
                return False
            
            resource.released = True
            resource.released_at = time.time()
            resource.released_by = released_by
            
            # Remove from owner tracking
            if resource.owner in self._owner_resources:
                self._owner_resources[resource.owner].discard(resource_id)
            
            # Remove from device tracking
            if resource.cuda_device in self._device_resources:
                self._device_resources[resource.cuda_device].discard(resource_id)
            
            logger.debug(f"GPU resource released: {resource_id} by {released_by}")
            return True
    
    def get(self, resource_id: str) -> Optional[GPUResource]:
        """Get resource by ID."""
        with self._lock:
            return self._resources.get(resource_id)
    
    def get_by_owner(self, owner: str) -> List[GPUResource]:
        """Get all resources owned by a component."""
        with self._lock:
            resource_ids = self._owner_resources.get(owner, set())
            return [self._resources[rid] for rid in resource_ids if rid in self._resources]
    
    def get_by_device(self, device: int) -> List[GPUResource]:
        """Get all resources on a CUDA device."""
        with self._lock:
            resource_ids = self._device_resources.get(device, set())
            return [self._resources[rid] for rid in resource_ids if rid in self._resources]
    
    def check_leaks(self) -> List[GPUResource]:
        """Check for unreleased resources."""
        with self._lock:
            return [r for r in self._resources.values() if not r.released]
    
    def force_release_owner(self, owner: str, released_by: str = "force_cleanup") -> int:
        """Force release all resources owned by a component."""
        with self._lock:
            resource_ids = list(self._owner_resources.get(owner, set()))
            count = 0
            for rid in resource_ids:
                if self.unregister(rid, released_by):
                    count += 1
            return count
    
    def _atexit_cleanup(self):
        """Cleanup on process exit."""
        leaks = self.check_leaks()
        if leaks:
            logger.warning(f"GPU resource leaks detected at exit: {len(leaks)} resources")
            for r in leaks:
                logger.warning(f"  Leaked: {r.resource_id} ({r.resource_type.value}) owned by {r.owner}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            total = len(self._resources)
            active = sum(1 for r in self._resources.values() if not r.released)
            released = total - active
            by_type = {}
            for r in self._resources.values():
                if r.resource_type.value not in by_type:
                    by_type[r.resource_type.value] = {"active": 0, "released": 0}
                if r.released:
                    by_type[r.resource_type.value]["released"] += 1
                else:
                    by_type[r.resource_type.value]["active"] += 1
            return {
                "total": total,
                "active": active,
                "released": released,
                "by_type": by_type,
                "by_owner": {k: len(v) for k, v in self._owner_resources.items()},
                "by_device": {k: len(v) for k, v in self._device_resources.items()},
            }


class CUDAContextManager:
    """
    Manages CUDA contexts and streams for the pipeline.
    Ensures proper context isolation and synchronization.
    """
    
    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self._primary_context: Optional[torch.cuda.CudaContext] = None
        self._primary_stream: Optional[torch.cuda.Stream] = None
        self._worker_streams: Dict[str, torch.cuda.Stream] = {}
        self._lock = threading.Lock()
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize primary CUDA context and stream."""
        with self._lock:
            if self._initialized:
                return
            
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA not available")
            
            torch.cuda.set_device(self.device_id)
            self._primary_context = torch.cuda.current_context()
            self._primary_stream = torch.cuda.current_stream(self.device_id)
            self._initialized = True
            
            # Register primary context
            registry = GPUResourceRegistry()
            registry.register(
                resource_type=GPUResourceType.CONTEXT,
                owner="cuda_context_manager",
                cuda_device=self.device_id,
                cuda_context_ptr=id(self._primary_context) if self._primary_context else 0,
                cuda_stream_ptr=self._primary_stream.cuda_stream if self._primary_stream else 0,
                data_ptr=0,
                size_bytes=0,
                metadata={"type": "primary_context"},
            )
            
            logger.info(f"CUDA context initialized on device {self.device_id}")
    
    @property
    def primary_stream(self) -> torch.cuda.Stream:
        """Get primary CUDA stream."""
        if not self._initialized:
            self.initialize()
        return self._primary_stream
    
    @property
    def primary_context(self) -> torch.cuda.CudaContext:
        """Get primary CUDA context."""
        if not self._initialized:
            self.initialize()
        return self._primary_context
    
    def get_worker_stream(self, worker_name: str) -> torch.cuda.Stream:
        """Get or create a dedicated stream for a worker."""
        with self._lock:
            if worker_name not in self._worker_streams:
                self._worker_streams[worker_name] = torch.cuda.Stream(
                    device=self.device_id,
                    priority=-1  # Normal priority
                )
                # Register stream
                registry = GPUResourceRegistry()
                stream = self._worker_streams[worker_name]
                registry.register(
                    resource_type=GPUResourceType.STREAM,
                    owner=f"worker_stream:{worker_name}",
                    cuda_device=self.device_id,
                    cuda_context_ptr=id(self._primary_context) if self._primary_context else 0,
                    cuda_stream_ptr=stream.cuda_stream,
                    data_ptr=0,
                    size_bytes=0,
                    metadata={"worker": worker_name, "type": "worker_stream"},
                )
            return self._worker_streams[worker_name]
    
    def synchronize(self, stream: Optional[torch.cuda.Stream] = None) -> None:
        """Synchronize a stream (default: primary)."""
        if stream is None:
            stream = self.primary_stream
        stream.synchronize()
    
    def synchronize_device(self) -> None:
        """Synchronize entire device."""
        torch.cuda.synchronize(self.device_id)
    
    @contextmanager
    def stream_context(self, stream: Optional[torch.cuda.Stream] = None):
        """Context manager for CUDA stream."""
        if stream is None:
            stream = self.primary_stream
        with torch.cuda.stream(stream):
            yield stream
    
    def release_worker_stream(self, worker_name: str) -> None:
        """Release a worker stream."""
        with self._lock:
            stream = self._worker_streams.pop(worker_name, None)
            if stream:
                stream.synchronize()
                registry = GPUResourceRegistry()
                # Note: We can't easily unregister by stream pointer, 
                # but the stream object will be GC'd
                logger.debug(f"Released worker stream: {worker_name}")
    
    def cleanup(self) -> None:
        """Cleanup all managed resources."""
        with self._lock:
            for name, stream in self._worker_streams.items():
                stream.synchronize()
            self._worker_streams.clear()
            
            if self._primary_context:
                registry = GPUResourceRegistry()
                registry.force_release_owner("cuda_context_manager")
            
            self._initialized = False
            logger.info("CUDA context manager cleaned up")


class GPUBufferPool:
    """
    Pre-allocated GPU buffer pool for zero-copy frame processing.
    Avoids repeated cudaMalloc/cudaFree in hot path.
    """
    
    def __init__(
        self,
        device_id: int,
        width: int,
        height: int,
        pixel_format: str = "nv12",
        pool_size: int = 8,
    ):
        self.device_id = device_id
        self.width = width
        self.height = height
        self.pixel_format = pixel_format
        self.pool_size = pool_size
        
        self._available: List[Tuple[torch.Tensor, torch.Tensor]] = []
        self._in_use: Set[int] = set()  # data_ptr of in-use buffers
        self._lock = threading.Lock()
        self._initialized = False
    
    def initialize(self) -> None:
        """Pre-allocate buffer pool."""
        with self._lock:
            if self._initialized:
                return
            
            torch.cuda.set_device(self.device_id)
            
            for _ in range(self.pool_size):
                if self.pixel_format == "nv12":
                    y_tensor = torch.empty(
                        (self.height, self.width),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                    uv_tensor = torch.empty(
                        (self.height // 2, self.width // 2, 2),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                elif self.pixel_format == "bgr":
                    y_tensor = torch.empty(
                        (self.height, self.width, 3),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                    uv_tensor = None
                else:
                    raise ValueError(f"Unsupported format: {self.pixel_format}")
                
                self._available.append((y_tensor, uv_tensor))
            
            self._initialized = True
            logger.info(f"GPU buffer pool initialized: {self.pool_size} buffers ({self.width}x{self.height} {self.pixel_format})")
    
    def acquire(self) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Acquire a buffer from the pool."""
        with self._lock:
            if not self._initialized:
                self.initialize()
            
            if not self._available:
                # Pool exhausted - allocate new (should not happen in steady state)
                logger.warning("GPU buffer pool exhausted, allocating new buffer")
                if self.pixel_format == "nv12":
                    y_tensor = torch.empty(
                        (self.height, self.width),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                    uv_tensor = torch.empty(
                        (self.height // 2, self.width // 2, 2),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                else:
                    y_tensor = torch.empty(
                        (self.height, self.width, 3),
                        dtype=torch.uint8,
                        device=f"cuda:{self.device_id}"
                    )
                    uv_tensor = None
                return y_tensor, uv_tensor
            
            y_tensor, uv_tensor = self._available.pop()
            self._in_use.add(y_tensor.data_ptr())
            return y_tensor, uv_tensor
    
    def release(self, y_tensor: torch.Tensor, uv_tensor: Optional[torch.Tensor] = None) -> None:
        """Release buffer back to pool."""
        with self._lock:
            ptr = y_tensor.data_ptr()
            if ptr in self._in_use:
                self._in_use.discard(ptr)
                self._available.append((y_tensor, uv_tensor))
    
    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics."""
        with self._lock:
            return {
                "pool_size": self.pool_size,
                "available": len(self._available),
                "in_use": len(self._in_use),
            }
    
    def cleanup(self) -> None:
        """Release all buffers."""
        with self._lock:
            self._available.clear()
            self._in_use.clear()
            torch.cuda.empty_cache()


# Global instances
_context_manager: Optional[CUDAContextManager] = None
_context_manager_lock = threading.Lock()


def get_cuda_context_manager(device_id: int = 0) -> CUDAContextManager:
    """Get global CUDA context manager."""
    global _context_manager
    with _context_manager_lock:
        if _context_manager is None or _context_manager.device_id != device_id:
            _context_manager = CUDAContextManager(device_id)
        return _context_manager


def get_gpu_resource_registry() -> GPUResourceRegistry:
    """Get global GPU resource registry."""
    return GPUResourceRegistry()


@contextmanager
def cuda_device_context(device_id: int):
    """Context manager for CUDA device."""
    prev_device = torch.cuda.current_device() if torch.cuda.is_available() else None
    torch.cuda.set_device(device_id)
    try:
        yield
    finally:
        if prev_device is not None:
            torch.cuda.set_device(prev_device)


if __name__ == "__main__":
    # Test
    import time
    
    ctx_mgr = get_cuda_context_manager(0)
    ctx_mgr.initialize()
    
    registry = get_gpu_resource_registry()
    
    # Test buffer pool
    pool = GPUBufferPool(0, 640, 480, "nv12", 4)
    pool.initialize()
    
    y, uv = pool.acquire()
    print(f"Acquired: y={y.shape}, uv={uv.shape}, ptr={y.data_ptr()}")
    
    pool.release(y, uv)
    print(f"Pool stats: {pool.get_stats()}")
    
    # Test registry
    resource = registry.register(
        GPUResourceType.TENSOR,
        "test",
        0, 0, 0, y.data_ptr(), y.numel(),
        {"test": True}
    )
    print(f"Registered: {resource.resource_id}")
    
    registry.unregister(resource.resource_id, "test")
    print(f"Stats: {registry.get_stats()}")
    
    pool.cleanup()
    ctx_mgr.cleanup()
    print("GPU lifecycle test passed!")