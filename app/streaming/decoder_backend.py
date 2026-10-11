"""
Phase 9.2 — Decoder Backend Abstraction.

Abstract base class and factory for decoder backends.
Allows A/B comparison between PyAV NVDEC (Backend A) and PyNvVideoCodec (Backend B).
"""

from __future__ import annotations

import abc
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Tuple, Union

from app.streaming.cuda_context_manager import CUDAContextManager, SharedContextManager

import numpy as np
import torch

if TYPE_CHECKING:
    from app.data.input_adapter import VideoFrame, VideoInfo, WatchdogFrame

logger = logging.getLogger(__name__)

# Per-GPU initialization locks for consumer GPU NVDEC session limit
_init_locks: Dict[int, threading.Lock] = {}
_init_locks_lock = threading.Lock()


def _get_init_lock(gpu_device: int) -> threading.Lock:
    """Get or create initialization lock for a GPU device."""
    with _init_locks_lock:
        if gpu_device not in _init_locks:
            _init_locks[gpu_device] = threading.Lock()
        return _init_locks[gpu_device]


@dataclass
class DecoderBackendConfig:
    """Base configuration for decoder backends."""
    camera_id: str
    rtsp_url: str
    nvdec_gpu_device: int = 0
    max_queue_size: int = 10
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    timeout: float = 10.0


class DecoderBackend(abc.ABC):
    """Abstract base class for decoder backends."""
    
    def __init__(self, config: DecoderBackendConfig):
        self.config = config
        self.camera_id = config.camera_id
        self._frame_queue: "queue.Queue[WatchdogFrame]" = queue.Queue(maxsize=config.max_queue_size)
        self._frame_index = 0
        self._opened = False
        self._error: Optional[Exception] = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
    
    @abc.abstractmethod
    def initialize(self) -> None:
        """Initialize backend resources (create decoder, demuxer)."""
        pass
    
    @abc.abstractmethod
    def open(self) -> VideoInfo:
        """Open the video source and return metadata."""
        pass
    
    @abc.abstractmethod
    def _reader_loop(self) -> None:
        """Reader thread loop - decode frames and push to queue."""
        pass
    
    def get_frame(self) -> Optional[WatchdogFrame]:
        """Get next frame from queue (non-blocking with short timeout)."""
        try:
            return self._frame_queue.get(timeout=1.0)
        except queue.Empty:
            return None
    
    def iter_with_watchdog(
        self,
        watchdog: Any,
        stop_event: Any,
    ) -> Iterator[WatchdogFrame]:
        """Iterate frames while a watchdog supervises."""
        if not self._opened:
            self.open()
        
        watchdog.register_capture(self)
        
        try:
            while not stop_event.is_set():
                if watchdog.teardown_requested:
                    yield WatchdogFrame(
                        data=None,
                        frame_index=self._frame_index,
                        timestamp=0.0,
                        pts=0,
                        stalled=True,
                    )
                    return
                
                try:
                    wframe = self._frame_queue.get(timeout=0.5)
                except queue.Empty:
                    if not self._opened:
                        yield WatchdogFrame(
                            data=None,
                            frame_index=self._frame_index,
                            timestamp=0.0,
                            pts=0,
                            stalled=watchdog.teardown_requested,
                        )
                        return
                    continue
                
                if wframe.stalled:
                    return
                
                watchdog.mark_progress()
                yield wframe
        finally:
            watchdog.unregister_capture(self)
    
    @abc.abstractmethod
    def close(self) -> None:
        """Close backend and release all resources."""
        pass
    
    def reconnect(self) -> bool:
        """Reconnect by closing and reopening."""
        self.close()
        time.sleep(self.config.timeout)
        try:
            self.open()
            return True
        except Exception as e:
            logger.error(f"DecoderBackend({self.camera_id}): Reconnect failed: {e}")
            return False
    
    @property
    def is_opened(self) -> bool:
        return self._opened
    
    @abc.abstractmethod
    def health(self) -> Dict[str, Any]:
        """Return health/status information."""
        pass
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


@dataclass
class PyAVNVDECBackendConfig(DecoderBackendConfig):
    """Configuration for PyAV NVDEC backend."""
    ffmpeg_path: Optional[str] = None
    nvdec_surfaces: int = 32
    scale_cuda: Optional[str] = None


class PyAVNVDECBackend(DecoderBackend):
    """Backend A: Wraps existing PyAVNVDECDecoder."""
    
    def __init__(self, config: PyAVNVDECBackendConfig):
        super().__init__(config)
        self._decoder = None
    
    def initialize(self) -> None:
        from app.streaming.pyav_nvdec_decoder import create_pyav_nvdec_decoder
        self._decoder = create_pyav_nvdec_decoder(
            camera_id=self.config.camera_id,
            rtsp_url=self.config.rtsp_url,
            nvdec_gpu_device=self.config.nvdec_gpu_device,
            expected_width=self.config.expected_width,
            expected_height=self.config.expected_height,
            expected_fps=self.config.expected_fps,
            ffmpeg_path=self.config.ffmpeg_path,
            nvdec_surfaces=self.config.nvdec_surfaces,
            scale_cuda=self.config.scale_cuda,
        )
    
    def open(self) -> VideoInfo:
        if self._decoder is None:
            self.initialize()
        
        info = self._decoder.open()
        
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"pyav-nvdec-reader-{self.camera_id}",
            daemon=True,
        )
        self._reader_thread.start()
        
        self._opened = True
        self._frame_index = 0
        self._error = None
        
        return info
    
    def _reader_loop(self) -> None:
        """Proxy to underlying decoder's reader loop."""
        if self._decoder:
            self._decoder._reader_loop()
    
    def close(self) -> None:
        with self._lock:
            if not self._opened and self._decoder is None:
                return
            
            logger.info(f"PyAVNVDECBackend({self.camera_id}): closing")
            
            self._stop_event.set()
            
            if self._decoder:
                self._decoder.close()
                self._decoder = None
            
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            
            self._opened = False
            logger.info(f"PyAVNVDECBackend({self.camera_id}): closed")
    
    def health(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "backend": "pyav",
            "opened": self._opened,
            "frame_index": self._frame_index,
            "queue_size": self._frame_queue.qsize(),
            "error": str(self._error) if self._error else None,
        }


@dataclass
class PyNvVideoCodecBackendConfig(DecoderBackendConfig):
    """Configuration for PyNvVideoCodec backend."""
    cuda_context: Optional[int] = None    # Explicit CUDA context handle (shared)
    cuda_stream: Optional[int] = None     # Explicit CUDA stream handle (per-decoder)
    use_device_memory: bool = True
    enable_async_allocations: bool = True
    output_color_type: str = "NATIVE"
    latency_mode: str = "NATIVE"
    enable_sei: bool = False
    enable_decode_stats: bool = False


class DecoderBackendFactory:
    """Factory for creating decoder backend instances."""
    
    _backends = {
        "pyav": PyAVNVDECBackend,
        "pynvvideocodec": "PyNvVideoCodecBackend",  # Lazy import
    }
    
    # Fallback chain: primary -> fallback
    _fallback_chain = {
        "pynvvideocodec": "pyav",
        "pyav": None,  # No fallback for Backend A
    }
    
    @classmethod
    def create(cls, backend_type: str, config: DecoderBackendConfig) -> DecoderBackend:
        if backend_type not in cls._backends:
            raise ValueError(f"Unknown decoder backend: {backend_type}. Available: {list(cls._backends.keys())}")
        
        backend_class = cls._backends[backend_type]
        
        # Handle lazy import for PyNvVideoCodecBackend
        if isinstance(backend_class, str):
            if backend_class == "PyNvVideoCodecBackend":
                from app.streaming.pynvvideocodec_backend import PyNvVideoCodecBackend
                backend_class = PyNvVideoCodecBackend
                cls._backends[backend_type] = backend_class
            else:
                raise ValueError(f"Unknown backend class: {backend_class}")
        
        return backend_class(config)
    
    @classmethod
    def _get_shared_context_manager(cls, gpu_device: int) -> SharedContextManager:
        """Get or create shared context manager for a GPU device."""
        if not hasattr(cls, '_shared_context_managers'):
            cls._shared_context_managers: Dict[int, SharedContextManager] = {}
            cls._shared_context_lock = threading.Lock()
        
        with cls._shared_context_lock:
            if gpu_device not in cls._shared_context_managers:
                cls._shared_context_managers[gpu_device] = SharedContextManager(gpu_device)
            return cls._shared_context_managers[gpu_device]
    
    @classmethod
    def create_with_fallback(
        cls, 
        primary_backend: str, 
        config: DecoderBackendConfig,
        enable_fallback: bool = True
    ) -> tuple[DecoderBackend, str]:
        """
        Create decoder backend with automatic fallback on initialization failure.
        Includes per-GPU initialization lock for consumer GPU NVDEC session limit.
        For PyNvVideoCodec backend, uses shared CUDA context and per-decoder streams.
        
        Args:
            primary_backend: Primary backend to try ("pynvvideocodec" or "pyav")
            config: Backend configuration
            enable_fallback: Whether to attempt fallback on failure
            
        Returns:
            Tuple of (backend_instance, actual_backend_used)
            
        Raises:
            RuntimeError: If both primary and fallback fail
        """
        # Get GPU device for lock
        gpu_device = getattr(config, 'nvdec_gpu_device', 0)
        init_lock = _get_init_lock(gpu_device)
        
        attempted = []
        current_backend = primary_backend
        
        # Get the appropriate config for each backend type
        def get_config_for_backend(backend_type: str, base_config: DecoderBackendConfig) -> DecoderBackendConfig:
            """Convert base config to backend-specific config."""
            if backend_type == "pyav":
                if isinstance(base_config, PyAVNVDECBackendConfig):
                    return base_config
                # Convert from base config
                return PyAVNVDECBackendConfig(
                    camera_id=base_config.camera_id,
                    rtsp_url=base_config.rtsp_url,
                    nvdec_gpu_device=base_config.nvdec_gpu_device,
                    max_queue_size=base_config.max_queue_size,
                    expected_codec=base_config.expected_codec,
                    expected_width=base_config.expected_width,
                    expected_height=base_config.expected_height,
                    expected_fps=base_config.expected_fps,
                    timeout=base_config.timeout,
                )
            elif backend_type == "pynvvideocodec":
                if isinstance(base_config, PyNvVideoCodecBackendConfig):
                    return base_config
                # Convert from base config
                return PyNvVideoCodecBackendConfig(
                    camera_id=base_config.camera_id,
                    rtsp_url=base_config.rtsp_url,
                    nvdec_gpu_device=base_config.nvdec_gpu_device,
                    max_queue_size=base_config.max_queue_size,
                    expected_codec=base_config.expected_codec,
                    expected_width=base_config.expected_width,
                    expected_height=base_config.expected_height,
                    expected_fps=base_config.expected_fps,
                    timeout=base_config.timeout,
                )
            else:
                return base_config
        
        with init_lock:  # SERIALIZE INITIALIZATION PER GPU
            logger.debug(f"DecoderBackendFactory: Acquired init lock for GPU {gpu_device} (camera={config.camera_id})")
            
            # Get shared context manager for PyNvVideoCodec backend
            shared_ctx_mgr = None
            if current_backend == "pynvvideocodec":
                shared_ctx_mgr = cls._get_shared_context_manager(gpu_device)
            
            while current_backend is not None:
                attempted.append(current_backend)
                try:
                    logger.info(f"DecoderBackendFactory: Attempting to create {current_backend} backend for {config.camera_id}")
                    
                    # Use backend-specific config
                    backend_config = get_config_for_backend(current_backend, config)
                    
                    # For PyNvVideoCodec, inject shared context and stream
                    if current_backend == "pynvvideocodec" and shared_ctx_mgr is not None:
                        # Acquire shared context
                        ctx_handle = shared_ctx_mgr.acquire_context()
                        # Create per-decoder stream
                        stream_handle = shared_ctx_mgr.create_stream(config.camera_id)
                        
                        # Inject into config
                        backend_config.cuda_context = ctx_handle.value
                        backend_config.cuda_stream = stream_handle
                        
                        logger.info(
                            f"DecoderBackendFactory: Injected shared context {ctx_handle.value} "
                            f"and stream {stream_handle} for {config.camera_id}"
                        )
                    
                    backend = cls.create(current_backend, backend_config)
                    backend.initialize()
                    logger.info(f"DecoderBackendFactory: Successfully created {current_backend} backend for {config.camera_id}")
                    
                    # Attach shared context manager to backend for cleanup
                    if current_backend == "pynvvideocodec" and shared_ctx_mgr is not None:
                        backend._shared_context_manager = shared_ctx_mgr
                    
                    return backend, current_backend
                except Exception as e:
                    logger.warning(f"DecoderBackendFactory: {current_backend} backend initialization failed for {config.camera_id}: {e}")
                    
                    # On failure, release stream if we created one
                    if current_backend == "pynvvideocodec" and shared_ctx_mgr is not None:
                        shared_ctx_mgr.release_stream(config.camera_id)
                        # Note: We don't release context here - it's shared
                        # The context will be released when decoder closes
                    
                    if not enable_fallback:
                        raise
                    
                    # Get fallback
                    current_backend = cls._fallback_chain.get(current_backend)
                    if current_backend is None:
                        logger.error(f"DecoderBackendFactory: No fallback available for {attempted[-1]}")
                        break
                    logger.info(f"DecoderBackendFactory: Falling back to {current_backend} for {config.camera_id}")
        
        # All attempts failed - cleanup shared context manager if created
        if shared_ctx_mgr is not None:
            # Release the context reference we acquired
            shared_ctx_mgr.release_context()
        
        # All attempts failed
        raise RuntimeError(
            f"DecoderBackendFactory: All backend attempts failed for {config.camera_id}. "
            f"Attempted: {attempted}"
        )
    
    @classmethod
    def available_backends(cls) -> List[str]:
        return list(cls._backends.keys())