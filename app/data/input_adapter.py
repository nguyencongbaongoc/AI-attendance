"""
Phase 20 — Video Input Adapter.

Provides video frame iteration using FFmpeg/OpenCV with standardized output format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

# Import GPUFrameContract for conversion
try:
    from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract
except ImportError:
    GPUFrameContract = None

# Import health monitoring for fallback events
try:
    from app.streaming.health import create_health_monitor
    from app.streaming.health_events import create_decoder_fallback_event
except ImportError:
    create_health_monitor = None
    create_decoder_fallback_event = None

# Import decoder backend factory - use lazy import to avoid circular dependency
DecoderBackendFactory = None
DecoderBackendConfig = None
PyAVNVDECBackendConfig = None
PyNvVideoCodecBackendConfig = None

def _import_decoder_backend():
    """Lazy import decoder backend factory."""
    global DecoderBackendFactory, DecoderBackendConfig, PyAVNVDECBackendConfig, PyNvVideoCodecBackendConfig
    if DecoderBackendFactory is None:
        from app.streaming.decoder_backend import (
            DecoderBackendFactory as _DecoderBackendFactory,
            DecoderBackendConfig as _DecoderBackendConfig,
            PyAVNVDECBackendConfig as _PyAVNVDECBackendConfig,
            PyNvVideoCodecBackendConfig as _PyNvVideoCodecBackendConfig,
        )
        DecoderBackendFactory = _DecoderBackendFactory
        DecoderBackendConfig = _DecoderBackendConfig
        PyAVNVDECBackendConfig = _PyAVNVDECBackendConfig
        PyNvVideoCodecBackendConfig = _PyNvVideoCodecBackendConfig
    return DecoderBackendFactory


@dataclass
class VideoInfo:
    """Metadata about a video source."""
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float
    codec: str
    pixel_format: str
    path: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "duration": self.duration,
            "codec": self.codec,
            "pixel_format": self.pixel_format,
            "path": self.path,
        }


@dataclass
class VideoFrame:
    """A single video frame with metadata."""
    data: Any  # np.ndarray for CPU frames, dict for GPU/CUDA frames
    frame_index: int
    timestamp: float
    pts: Optional[int] = None
    keyframe: bool = False
    # Optional fields for metadata
    source_fps: float = 0.0
    decoder: str = ""
    nvdec_gpu_device: int = 0
    
    @property
    def metadata(self):
        """Compatibility property for existing code."""
        from app.data.frame import FrameMetadata, PixelFormat, SourceType
        
        # Handle GPUFrameContract (NV12 CUDA tensors)
        if GPUFrameContract is not None and isinstance(self.data, GPUFrameContract):
            original_width = self.data.width
            original_height = self.data.height
            pixel_format = PixelFormat.NV12
            dtype = "uint8"
        # H.10-C.3: Handle both numpy.ndarray (CPU) and dict (CUDA/PyAV) frame data
        elif isinstance(self.data, dict):
            # CUDA/PyAV path: dimensions are explicit in the dict
            original_width = int(self.data.get("width", 0))
            original_height = int(self.data.get("height", 0))
            pixel_format = PixelFormat.NV12
            dtype = "uint8"
        else:
            # Legacy CPU/BGR24 path
            original_width = self.data.shape[1] if self.data.ndim >= 2 else 0
            original_height = self.data.shape[0] if self.data.ndim >= 1 else 0
            pixel_format = PixelFormat.BGR
            dtype = str(self.data.dtype)
        
        return FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id=self.path if hasattr(self, 'path') else "",
            frame_index=self.frame_index,
            timestamp=self.timestamp,
            original_width=original_width,
            original_height=original_height,
            pixel_format=pixel_format,
            dtype=dtype,
            source_fps=self.source_fps,
            source_duration=0.0,
            source_frame_count=0,
            extra={
                "pts": self.pts,
                "keyframe": self.keyframe,
                "decoder": self.decoder,
                "gpu_device": self.nvdec_gpu_device,
            },
        )


class VideoFrameIterator:
    """
    Iterator over video frames using OpenCV.
    
    Provides streaming frame access with metadata.
    """
    
    def __init__(
        self,
        path: str,
        decoder: str = "pynvvideocodec",
        nvdec_gpu_device: int = 0,
        expected_width: int = 3840,
        expected_height: int = 2160,
        expected_fps: float = 30.0,
        scale_cuda: Optional[str] = None,
        nvdec_output_mode: str = "gpu",
        camera_id: str = "pyav_iterator",
    ):
        """
        Initialize video frame iterator using canonical PyNvVideoCodec NVDEC decoder (Phase 9.3+).
        
        Args:
            path: Path to video file or RTSP/RTMP URL
            decoder: Decoder to use ("pyav_nvdec" for Backend A, "pynvvideocodec" for Backend B)
            nvdec_gpu_device: GPU device index for NVDEC
            expected_width: Expected source width (default 3840 for 4K)
            expected_height: Expected source height (default 2160 for 4K)
            expected_fps: Expected source FPS
            scale_cuda: Optional NVDEC scale target (e.g. "1920x1080").
                When None, NVDEC outputs the native source resolution (4K).
            nvdec_output_mode: NVDEC output mode (canonical: "gpu" CUDA frames)
            camera_id: Camera identifier for decoder isolation (e.g., "CAM1", "CAM2")
        """
        self.path = path
        self.decoder = decoder
        self.nvdec_gpu_device = nvdec_gpu_device
        self.expected_width = expected_width
        self.expected_height = expected_height
        self.expected_fps = expected_fps
        self.scale_cuda = scale_cuda
        self.nvdec_output_mode = nvdec_output_mode
        self.camera_id = camera_id
        self._backend = None
        self._info = None
        self._frame_index = 0
        self._opened = False
        self._actual_backend: Optional[str] = None  # Track which backend was actually used
    
    def _open(self) -> None:
        """Open the video source using the selected decoder backend with fallback."""
        _import_decoder_backend()
        
        # Determine backend type and config from decoder parameter
        if self.decoder == "pyav_nvdec":
            backend_type = "pyav"
            config = PyAVNVDECBackendConfig(
                camera_id=self.camera_id,
                rtsp_url=self.path,
                nvdec_gpu_device=self.nvdec_gpu_device,
                expected_width=self.expected_width,
                expected_height=self.expected_height,
                expected_fps=self.expected_fps,
                scale_cuda=self.scale_cuda,
            )
        elif self.decoder == "pynvvideocodec":
            backend_type = "pynvvideocodec"
            config = PyNvVideoCodecBackendConfig(
                camera_id=self.camera_id,
                rtsp_url=self.path,
                nvdec_gpu_device=self.nvdec_gpu_device,
                expected_width=self.expected_width,
                expected_height=self.expected_height,
                expected_fps=self.expected_fps,
            )
        else:
            raise ValueError(f"Unknown decoder: {self.decoder}")
        
        # Use factory with fallback support
        # Enable fallback only for primary backend (pynvvideocodec -> pyav)
        enable_fallback = (backend_type == "pynvvideocodec")
        self._backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend=backend_type,
            config=config,
            enable_fallback=enable_fallback
        )
        
        # Log which backend is actually being used
        if actual_backend != backend_type:
            logger.warning(
                f"VideoFrameIterator({self.camera_id}): Fell back from {backend_type} to {actual_backend}"
            )
            # Emit decoder fallback health event
            if create_health_monitor and create_decoder_fallback_event:
                try:
                    health_monitor = create_health_monitor()
                    health_monitor.register_camera(self.camera_id)
                    event = create_decoder_fallback_event(
                        event_id=f"{self.camera_id}-fallback-{int(time.time())}",
                        camera_id=self.camera_id,
                        primary_backend=backend_type,
                        fallback_backend=actual_backend,
                        failure_reason="Initialization failed",
                        source_identifier="rtsp",
                    )
                    health_monitor._emit_event(event)
                except Exception as e:
                    logger.debug(f"Failed to emit fallback event: {e}")
        else:
            logger.info(f"VideoFrameIterator({self.camera_id}): Using {actual_backend} backend")
        
        self._actual_backend = actual_backend
        
        info = self._backend.open()
        self._info = info
        self._opened = True
        return
    
    @property
    def info(self) -> VideoInfo:
        """Get video metadata."""
        if not self._opened:
            self._open()
        return self._info
    
    @property
    def actual_backend(self) -> Optional[str]:
        """Get the actual backend being used (after fallback)."""
        return self._actual_backend
    
    def __iter__(self) -> "VideoFrameIterator":
        """Return self as iterator."""
        if not self._opened:
            self._open()
        return self
    
    def __next__(self) -> VideoFrame:
        """Get next frame (iterator protocol)."""
        if not self._opened:
            self._open()

        wframe = self._backend.get_frame()
        if wframe is None:
            raise StopIteration
        if wframe.stalled:
            raise StopIteration

        frame_data = wframe.data
        
        # GPUFrameContract is already the canonical format from backend
        # No conversion needed if backend returns GPUFrameContract directly
        
        video_frame = VideoFrame(
            data=frame_data,
            frame_index=wframe.frame_index,
            timestamp=wframe.timestamp,
            pts=wframe.pts,
            source_fps=self._info.fps if self._info else 0.0,
            decoder=self._actual_backend or self.decoder,  # Report actual backend used
            nvdec_gpu_device=self.nvdec_gpu_device,
        )
        video_frame.path = self.path
        self._frame_index = wframe.frame_index + 1
        return video_frame

    # ---------------------------------------------------------- watchdog iter
    def iter_with_watchdog(
        self,
        watchdog: Any,
        stop_event: Any,
    ) -> Iterator["WatchdogFrame"]:
        """
        Iterate frames while a separate watchdog supervises the read loop.

        This iterator must be consumed from a single worker thread (the
        thread that called this method). The watchdog runs in another
        thread and can call self._cap.release() to break a blocked read().

        The yielded WatchdogFrame exposes `stalled` so the worker can
        decide whether the read returned a real frame or whether the
        watchdog forced teardown.
        """
        if not self._opened:
            self._open()

        # Use backend's iter_with_watchdog
        for wframe in self._backend.iter_with_watchdog(watchdog, stop_event):
            if wframe.stalled:
                yield wframe
                continue
            frame_data = wframe.data
            # GPUFrameContract is already the canonical format from backend
            yield WatchdogFrame(
                data=frame_data,
                frame_index=wframe.frame_index,
                timestamp=wframe.timestamp,
                pts=wframe.pts,
                stalled=wframe.stalled,
            )
        return

    def close(self) -> None:
        """Close the video source."""
        if hasattr(self, '_backend') and self._backend:
            self._backend.close()
            self._backend = None
            self._opened = False
            return
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


@dataclass
class WatchdogFrame:
    """A video frame possibly marked as stalled by the watchdog."""

    data: Any
    frame_index: int
    timestamp: float
    pts: int
    stalled: bool = False


def create_video_frame_iterator(
    path: str,
    decoder: str = "pynvvideocodec",
    nvdec_gpu_device: int = 0,
    expected_width: int = 3840,
    expected_height: int = 2160,
    expected_fps: float = 30.0,
    scale_cuda: Optional[str] = None,
    nvdec_output_mode: str = "gpu",
    camera_id: str = "pyav_iterator",
) -> VideoFrameIterator:
    """Factory function to create VideoFrameIterator with selectable decoder backend."""
    return VideoFrameIterator(
        path, 
        decoder, 
        nvdec_gpu_device,
        expected_width,
        expected_height,
        expected_fps,
        scale_cuda,
        nvdec_output_mode=nvdec_output_mode,
        camera_id=camera_id,
    )