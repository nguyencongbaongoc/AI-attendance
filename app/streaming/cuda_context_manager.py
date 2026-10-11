"""
Phase 9.4.3 — Shared CUDA Context Manager.

Manages explicit CUDA primary context per GPU for concurrent decoder support.
"""

from __future__ import annotations

import logging
import threading
import ctypes
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CUDAContextHandle:
    """Opaque handle for a CUDA context."""
    value: int
    device: int


class CUDAContextManager:
    """
    Manages explicit CUDA primary context per GPU device.
    
    Responsibilities:
    - One shared CUDA primary context per GPU
    - Safe acquisition with reference counting
    - Safe lifetime management
    - Protection against premature context destruction
    - Thread-safe access
    - Deterministic cleanup
    """
    
    _instances: Dict[int, "CUDAContextManager"] = {}
    _instance_lock = threading.Lock()
    _driver_initialized = False
    _driver_init_lock = threading.Lock()
    
    def __init__(self, gpu_device: int):
        self.gpu_device = gpu_device
        self._context_handle: Optional[CUDAContextHandle] = None
        self._ref_count = 0
        self._lock = threading.RLock()
        self._nvcuda = None
        
    @classmethod
    def get_instance(cls, gpu_device: int) -> "CUDAContextManager":
        """Get or create the singleton manager for a GPU device."""
        with cls._instance_lock:
            if gpu_device not in cls._instances:
                cls._instances[gpu_device] = CUDAContextManager(gpu_device)
            return cls._instances[gpu_device]
    
    def _load_nvcuda(self) -> ctypes.CDLL:
        """Load nvcuda.dll."""
        if self._nvcuda is None:
            self._nvcuda = ctypes.CDLL('nvcuda.dll')
        return self._nvcuda
    
    def _cuda_check(self, result: int, func_name: str) -> int:
        """Check CUDA driver API result."""
        if result != 0:
            raise RuntimeError(f"{func_name} failed with error {result}")
        return result
    
    def _ensure_driver_initialized(self) -> None:
        """Initialize CUDA driver once globally."""
        with CUDAContextManager._driver_init_lock:
            if not CUDAContextManager._driver_initialized:
                nvcuda = self._load_nvcuda()
                result = nvcuda.cuInit(0)
                self._cuda_check(result, "cuInit")
                CUDAContextManager._driver_initialized = True
                logger.info("CUDA driver initialized globally")
    
    def acquire(self) -> CUDAContextHandle:
        """
        Acquire the shared CUDA primary context.
        
        Returns:
            CUDAContextHandle with explicit context handle
            
        Raises:
            RuntimeError: If context acquisition fails
        """
        with self._lock:
            self._ensure_driver_initialized()
            
            if self._context_handle is None:
                # First acquisition - create/retain primary context
                nvcuda = self._load_nvcuda()
                
                dev = ctypes.c_int(self.gpu_device)
                ctx = ctypes.c_void_p()
                
                # Retain primary context for device
                result = nvcuda.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), dev)
                self._cuda_check(result, "cuDevicePrimaryCtxRetain")
                
                self._context_handle = CUDAContextHandle(
                    value=ctx.value,
                    device=self.gpu_device
                )
                logger.info(f"CUDAContextManager(GPU {self.gpu_device}): Primary context retained: {ctx.value}")
            
            self._ref_count += 1
            logger.debug(f"CUDAContextManager(GPU {self.gpu_device}): Acquired (ref_count={self._ref_count})")
            
            return self._context_handle
    
    def release(self) -> None:
        """
        Release the shared CUDA primary context.
        
        Context is only destroyed when ref_count reaches 0.
        """
        with self._lock:
            if self._ref_count <= 0:
                logger.warning(f"CUDAContextManager(GPU {self.gpu_device}): Release called with ref_count={self._ref_count}")
                return
            
            self._ref_count -= 1
            logger.debug(f"CUDAContextManager(GPU {self.gpu_device}): Released (ref_count={self._ref_count})")
            
            if self._ref_count == 0 and self._context_handle is not None:
                # Last reference - release primary context
                nvcuda = self._load_nvcuda()
                
                dev = ctypes.c_int(self.gpu_device)
                
                # Pop current context if set
                nvcuda.cuCtxSetCurrent(ctypes.c_void_p(0))
                
                # Release primary context
                result = nvcuda.cuDevicePrimaryCtxRelease(dev)
                self._cuda_check(result, "cuDevicePrimaryCtxRelease")
                
                logger.info(f"CUDAContextManager(GPU {self.gpu_device}): Primary context released")
                self._context_handle = None
    
    def get_context_handle(self) -> Optional[CUDAContextHandle]:
        """Get the current context handle without changing ref count."""
        with self._lock:
            return self._context_handle
    
    def is_acquired(self) -> bool:
        """Check if context is currently acquired."""
        with self._lock:
            return self._ref_count > 0 and self._context_handle is not None
    
    def get_ref_count(self) -> int:
        """Get current reference count."""
        with self._lock:
            return self._ref_count
    
    def force_release_all(self) -> None:
        """Force release all references (for emergency cleanup)."""
        with self._lock:
            while self._ref_count > 0:
                self.release()
            logger.warning(f"CUDAContextManager(GPU {self.gpu_device}): Force released all references")
    
    @classmethod
    def shutdown_all(cls) -> None:
        """Shutdown all context managers (for process exit)."""
        with cls._instance_lock:
            for device, manager in cls._instances.items():
                manager.force_release_all()
            cls._instances.clear()
            logger.info("CUDAContextManager: All instances shutdown")


class SharedContextManager:
    """
    High-level shared context manager for decoder backends.
    
    Provides simplified interface for DecoderBackendFactory to:
    - Acquire shared context per GPU
    - Create per-decoder CUDA streams
    - Manage context lifetime across decoder lifecycle
    """
    
    def __init__(self, gpu_device: int):
        self.gpu_device = gpu_device
        self._context_manager = CUDAContextManager.get_instance(gpu_device)
        self._streams: Dict[str, int] = {}  # camera_id -> stream handle
        self._stream_lock = threading.RLock()
    
    def acquire_context(self) -> CUDAContextHandle:
        """Acquire shared CUDA context for this GPU."""
        return self._context_manager.acquire()
    
    def release_context(self) -> None:
        """Release shared CUDA context for this GPU."""
        self._context_manager.release()
    
    def create_stream(self, camera_id: str) -> int:
        """
        Create a CUDA stream for a specific camera.
        
        Args:
            camera_id: Unique camera identifier
            
        Returns:
            CUDA stream handle
        """
        import torch
        
        with self._stream_lock:
            if camera_id in self._streams:
                logger.warning(f"SharedContextManager(GPU {self.gpu_device}): Stream for {camera_id} already exists")
                return self._streams[camera_id]
            
            device = torch.device(f'cuda:{self.gpu_device}')
            stream = torch.cuda.Stream(device=device)
            stream_handle = stream.cuda_stream
            self._streams[camera_id] = stream_handle
            logger.info(f"SharedContextManager(GPU {self.gpu_device}): Created stream for {camera_id}: {stream_handle}")
            return stream_handle
    
    def release_stream(self, camera_id: str) -> None:
        """Release CUDA stream for a camera."""
        with self._stream_lock:
            if camera_id in self._streams:
                del self._streams[camera_id]
                logger.info(f"SharedContextManager(GPU {self.gpu_device}): Released stream for {camera_id}")
    
    def get_stream(self, camera_id: str) -> Optional[int]:
        """Get existing stream handle for camera."""
        with self._stream_lock:
            return self._streams.get(camera_id)
    
    def get_context_handle(self) -> Optional[CUDAContextHandle]:
        """Get current context handle."""
        return self._context_manager.get_context_handle()
    
    def get_ref_count(self) -> int:
        """Get context reference count."""
        return self._context_manager.get_ref_count()
    
    def __enter__(self) -> "SharedContextManager":
        self.acquire_context()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Don't auto-release on exit - managed by factory
        pass