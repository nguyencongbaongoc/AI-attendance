"""
Phase H.10-C.2 — PyAV CUDA NVDEC Decoder.

Direct PyAV hardware-frame decoding for RTSP H.264 streams.
Eliminates the FFmpeg subprocess + BGR24 pipe boundary.
Produces CUDA-resident AVFrames (AV_PIX_FMT_CUDA) in NV12 layout.

Architecture:
    RTSP H.264 4K
    → PyAV av.open(rtsp_url, hwaccel=HWAccel(cuda, is_hw_owned=True))
    → NVDEC / CUDA AVFrame (NV12, GPU, 2 planes: Y + interleaved UV)
    → DLPack capsule (plane.__dlpack__())
    → PyTorch CUDA Tensor (zero-copy GPU memory sharing)
    → GPU AI pipeline / GPU annotation / NVENC
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import numpy as np

from app.data.input_adapter import VideoInfo, VideoFrame, WatchdogFrame

logger = logging.getLogger(__name__)


def log_pyav_ffmpeg_error(*, stage: str, camera_id: str, error: Exception, retry_attempt: Optional[int] = None, stream_url: Optional[str] = None) -> None:
    """
    Log detailed PyAV/FFmpeg error information for forensic diagnostics.
    
    Captures the exact exception attributes without assuming error meanings.
    """
    errno = getattr(error, "errno", None)
    strerror = getattr(error, "strerror", None)
    filename = getattr(error, "filename", None)
    exception_type = type(error).__name__
    message = str(error)
    
    # Redact credentials from stream URL if present
    redacted_url = stream_url
    if stream_url and "@" in stream_url:
        # Simple redaction for rtsp://user:pass@host URLs
        try:
            protocol, rest = stream_url.split("://", 1)
            if "@" in rest:
                creds, host = rest.split("@", 1)
                redacted_url = f"{protocol}://***:***@{host}"
        except Exception:
            redacted_url = stream_url
    
    logger.error(
        f"[PYAV-FFMPEG-ERROR] "
        f"camera={camera_id} "
        f"stage={stage} "
        f"type={exception_type} "
        f"errno={errno} "
        f"strerror={strerror!r} "
        f"filename={filename!r} "
        f"message={message!r} "
        f"retry={retry_attempt} "
        f"stream={redacted_url!r}"
    )
    
    # Also log full traceback at debug level for detailed analysis
    logger.debug(f"[PYAV-FFMPEG-ERROR] Full traceback for {camera_id} at {stage}:", exc_info=error)


@dataclass(frozen=True)
class PyAVNVDECDecoderConfig:
    """Configuration for PyAV NVDEC decoder."""
    camera_id: str
    rtsp_url: str
    nvdec_gpu_device: int = 0
    use_pts: bool = True
    max_queue_size: int = 10
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    timeout: float = 10.0
    ffmpeg_path: Optional[str] = None
    nvdec_surfaces: int = 32
    scale_cuda: Optional[str] = None


class PyAVNVDECWatchdogFrame:
    """A video frame from PyAV NVDEC decoder, possibly marked as stalled."""
    
    def __init__(
        self,
        data: Any,
        frame_index: int,
        timestamp: float,
        pts: int,
        stalled: bool = False,
        is_gpu_frame: bool = True,
    ):
        self.data = data
        self.frame_index = frame_index
        self.timestamp = timestamp
        self.pts = pts
        self.stalled = stalled
        self.is_gpu_frame = is_gpu_frame


class PyAVNVDECDecoder:
    """
    PyAV-based NVDEC decoder using hardware frames (CUDA).
    
    Uses PyAV's HWAccel with is_hw_owned=True to create a CUDA hwdevice context
    and decode directly into GPU-resident AVFrames (format='cuda', 2-plane NV12).
    
    No subprocess, no BGR24 pipe, no full-frame CPU boundary.
    """
    
    def __init__(
        self,
        config: PyAVNVDECDecoderConfig,
        time_func: Any = time.time,
    ):
        self.config = config
        self.camera_id = config.camera_id
        self._time = time_func
        
        # Handle both RTSP and RTMP URLs
        url = config.rtsp_url
        if url.lower().startswith("rtsp://") and "transport=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}transport=tcp"
        self.rtsp_url = url
        self._input_url = config.rtsp_url  # Store original for format detection
        
        self._container = None
        self._stream = None
        self._hwaccel = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_queue: "queue.Queue[PyAVNVDECWatchdogFrame]" = queue.Queue(maxsize=config.max_queue_size)
        self._frame_index = 0
        self._opened = False
        self._info: Optional[VideoInfo] = None
        self._lock = threading.RLock()
        self._error: Optional[Exception] = None
        self._width = config.expected_width
        self._height = config.expected_height
        self._fps = config.expected_fps
    
    def _build_hwaccel(self):
        """Build PyAV HWAccel for CUDA decoding."""
        import av
        from av.codec.hwaccel import HWAccel
        
        # Use CUDA hwaccel with PyAV-owned context, no software fallback
        hw = HWAccel(
            device_type="cuda",
            is_hw_owned=True,
            allow_software_fallback=False
        )
        return hw
    
    def open(self) -> VideoInfo:
        """Open the RTSP source via PyAV NVDEC and return metadata."""
        import av
        
        with self._lock:
            if self._opened:
                return self._info
        
        logger.info(f"PyAVNVDECDecoder({self.camera_id}): opening {self._input_url}")
        
        # H.10-C.3: Retry on transient FFmpeg errors (e.g., EAGAIN -129)
        # Extended retries for live stream connection stabilization
        max_retries = 10
        retry_delay = 2.0
        
        # Determine format based on URL
        is_rtmp = self._input_url.lower().startswith("rtmp://")
        format_name = "flv" if is_rtmp else "rtsp"
        options = {
            "hwaccel": "cuda",
            "hwaccel_device": str(self.config.nvdec_gpu_device),
            "hwaccel_output_format": "cuda",
        }
        if is_rtmp:
            options["rtmp_buffer"] = "100"
        else:
            options["rtsp_transport"] = "tcp"
        
        # Controlled experiment: pass nvdec_surfaces to container options if configured and != default 32
        if self.config.nvdec_surfaces and self.config.nvdec_surfaces != 32:
            options["surfaces"] = str(self.config.nvdec_surfaces)
        
        for attempt in range(max_retries):
            try:
                # Build hardware accelerator
                self._hwaccel = self._build_hwaccel()
                logger.debug(f"PyAVNVDECDecoder({self.camera_id}): HWAccel created")
                
                # Open container with hardware acceleration
                # This creates the CUDA hwdevice context and initializes NVDEC
                self._container = av.open(
                    self.rtsp_url,
                    format=format_name,
                    options=options,
                    hwaccel=self._hwaccel,
                )
                # Success - break out of retry loop
                break
            except av.FFmpegError as e:
                # Log detailed diagnostic information
                log_pyav_ffmpeg_error(
                    stage="av.open",
                    camera_id=self.camera_id,
                    error=e,
                    retry_attempt=attempt + 1,
                    stream_url=self.rtsp_url,
                )
                
                error_str = str(e)
                # Check if this is a transient error (EAGAIN -129, or "Resource temporarily unavailable")
                is_transient = (
                    "Errno 129" in error_str or
                    "Error number -129" in error_str or
                    "Resource temporarily unavailable" in error_str or
                    "EAGAIN" in error_str
                )
                
                if is_transient and attempt < max_retries - 1:
                    logger.warning(
                        f"PyAVNVDECDecoder({self.camera_id}): Transient error on attempt {attempt+1}/{max_retries}: {e}. Retrying in {retry_delay}s..."
                    )
                    # Clean up partial state
                    self._hwaccel = None
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 10.0)  # Exponential backoff with cap
                    continue
                else:
                    # Non-transient error or out of retries
                    raise
            except Exception as e:
                # Log detailed diagnostic for non-FFmpeg errors too
                log_pyav_ffmpeg_error(
                    stage="av.open",
                    camera_id=self.camera_id,
                    error=e,
                    retry_attempt=attempt + 1,
                    stream_url=self.rtsp_url,
                )
                raise
        
        # Use lock to protect state updates
        with self._lock:
            # Get video stream
            self._stream = self._container.streams.video[0]
            logger.debug(
                f"PyAVNVDECDecoder({self.camera_id}): stream codec={self._stream.codec_context.name}, "
                f"width={self._stream.width}, height={self._stream.height}, "
                f"pix_fmt={self._stream.codec_context.pix_fmt}"
            )
            
            # Controlled experiment: pass surfaces and extra_hw_frames to stream codec context
            if self.config.nvdec_surfaces and self.config.nvdec_surfaces != 32:
                self._stream.codec_context.options["surfaces"] = str(self.config.nvdec_surfaces)
                self._stream.codec_context.options["extra_hw_frames"] = str(self.config.nvdec_surfaces)
                logger.info(
                    f"PyAVNVDECDecoder({self.camera_id}): configured codec options for surfaces: {self._stream.codec_context.options}"
                )
            
            # Set expected resolution if scale_cuda is configured
            if self.config.scale_cuda:
                try:
                    self._width, self._height = map(int, self.config.scale_cuda.split("x"))
                except Exception:
                    logger.warning(
                        f"PyAVNVDECDecoder({self.camera_id}): Invalid scale_cuda "
                        f"'{self.config.scale_cuda}', using native"
                    )
                    self._width = self._stream.width or self.config.expected_width
                    self._height = self._stream.height or self.config.expected_height
            else:
                self._width = self._stream.width or self.config.expected_width
                self._height = self._stream.height or self.config.expected_height
            
            self._fps = float(self._stream.average_rate) if self._stream.average_rate else self.config.expected_fps
            
            # Verify the stream is using CUDA hardware frames
            # The decoder context should report 'cuda' pix_fmt when hwaccel_output_format=cuda
            logger.info(
                f"PyAVNVDECDecoder({self.camera_id}): expected format=cuda (NV12 2-plane), "
                f"resolution={self._width}x{self._height}, fps={self._fps}"
            )
            
            self._info = VideoInfo(
                width=self._width,
                height=self._height,
                fps=self._fps,
                frame_count=0,  # live stream
                duration=0.0,
                codec="h264",
                pixel_format="cuda",  # CUDA hardware frames (NV12 2-plane)
                path=self.rtsp_url,
            )
            
            # Start reader thread
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
            
            logger.info(
                f"PyAVNVDECDecoder({self.camera_id}): opened successfully "
                f"({self._width}x{self._height}@{self._fps}fps, cuda, NVDEC gpu={self.config.nvdec_gpu_device})"
            )
        # End of with self._lock: block - the with context manager handles cleanup

        return self._info

    def _reader_loop(self) -> None:
        """Read frames from PyAV decoder and convert to PyTorch CUDA tensors."""
        import av
        import torch
        
        try:
            # Iterate over decoded frames from the container
            for frame in self._container.decode(video=0):
                if self._stop_event.is_set():
                    break
                
                # Validate frame properties
                if frame.format.name != "cuda":
                    logger.warning(
                        f"PyAVNVDECDecoder({self.camera_id}): Expected CUDA frame, got {frame.format.name}"
                    )
                    # Still process but mark as not GPU frame
                    is_gpu = False
                else:
                    is_gpu = True
                
                # Frame is a PyAV VideoFrame with format='cuda' (AV_PIX_FMT_CUDA)
                # It has 2 planes: plane 0 = Y, plane 1 = interleaved UV
                # We convert to PyTorch CUDA tensors for zero-copy GPU access
                try:
                    # Get DLPack capsules from both planes
                    dlpack_y = frame.planes[0].__dlpack__()
                    dlpack_uv = frame.planes[1].__dlpack__()
                    
                    # Convert to PyTorch tensors (zero-copy, memory owned by tensors)
                    t_y = torch.utils.dlpack.from_dlpack(dlpack_y)
                    t_uv = torch.utils.dlpack.from_dlpack(dlpack_uv)
                    
                    # Store PyTorch CUDA tensors for zero-copy GPU access
                    frame_data = {
                        "y_plane": t_y,  # PyTorch CUDA tensor, shape (H, W) uint8
                        "uv_plane": t_uv,  # PyTorch CUDA tensor, shape (H/2, W/2, 2) uint8
                        "width": frame.width,
                        "height": frame.height,
                        "format": "nv12_cuda",  # 2-plane NV12 on CUDA
                        "pts": frame.pts,
                        "time_base": frame.time_base,
                        # Keep reference to prevent GC (but tensors own memory)
                        "av_frame": frame,
                    }
                    
                    timestamp = self._time()
                    pts = frame.pts if frame.pts is not None else self._frame_index
                    
                except Exception as e:
                    logger.error(f"PyAVNVDECDecoder({self.camera_id}): PyTorch conversion failed: {e}")
                    self._error = e
                    # Fallback: try to get numpy array (CPU download - slow)
                    try:
                        frame_data = frame.to_ndarray(format="nv12")
                        is_gpu = False
                    except Exception as e2:
                        logger.error(f"PyAVNVDECDecoder({self.camera_id}): Frame conversion failed completely: {e2}")
                        continue
                
                # Create watchdog frame
                wframe = PyAVNVDECWatchdogFrame(
                    data=frame_data,
                    frame_index=self._frame_index,
                    timestamp=timestamp,
                    pts=pts,
                    stalled=False,
                    is_gpu_frame=is_gpu,
                )
                
                # Latest-wins queue semantics
                try:
                    self._frame_queue.put_nowait(wframe)
                except queue.Full:
                    try:
                        self._frame_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._frame_queue.put_nowait(wframe)
                    except queue.Full:
                        pass
                
                self._frame_index += 1
                
        except av.error.FFmpegError as e:
            log_pyav_ffmpeg_error(
                stage="decode",
                camera_id=self.camera_id,
                error=e,
                stream_url=self.rtsp_url,
            )
            logger.info(f"PyAVNVDECDecoder({self.camera_id}): Decode ended: {e}")
        except Exception as e:
            log_pyav_ffmpeg_error(
                stage="decode",
                camera_id=self.camera_id,
                error=e,
                stream_url=self.rtsp_url,
            )
            logger.error(f"PyAVNVDECDecoder({self.camera_id}): Reader loop error: {e}")
            self._error = e
        finally:
            logger.debug(f"PyAVNVDECDecoder({self.camera_id}): Reader loop exited")
    
    def iter_with_watchdog(
        self,
        watchdog: Any,
        stop_event: Any,
    ) -> Iterator[PyAVNVDECWatchdogFrame]:
        """Iterate frames while a watchdog supervises."""
        if not self._opened:
            self.open()
        
        # Register with watchdog so it can force close
        watchdog.register_capture(self)
        
        try:
            while not stop_event.is_set():
                if watchdog.teardown_requested:
                    yield PyAVNVDECWatchdogFrame(
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
                    # Check if container/stream is still alive
                    if self._container is None:
                        logger.info(f"PyAVNVDECDecoder({self.camera_id}): Container closed")
                        yield PyAVNVDECWatchdogFrame(
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
    
    def get_next_frame(self) -> Optional[PyAVNVDECWatchdogFrame]:
        """Get next frame (non-watchdog path)."""
        if not self._opened:
            self.open()
        
        try:
            return self._frame_queue.get(timeout=1.0)
        except queue.Empty:
            return None
    
    @property
    def info(self) -> VideoInfo:
        if not self._opened:
            self.open()
        return self._info
    
    def __iter__(self):
        """Iterate frames (yields WatchdogFrame)."""
        while True:
            wf = self.get_next_frame()
            if wf is None:
                break
            if wf.stalled:
                break
            yield wf
    
    def close(self) -> None:
        """Close decoder and cleanup resources."""
        with self._lock:
            if not self._opened and self._container is None:
                return
            
            logger.info(f"PyAVNVDECDecoder({self.camera_id}): closing")
            
            # Set stop event first to signal reader thread to exit
            self._stop_event.set()
            
            # Wait for reader thread to finish BEFORE closing container
            # This prevents the reader thread from accessing a closed container
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            
            # Now close container (releases FFmpeg resources, CUDA hw_frames_ctx)
            if self._container:
                try:
                    self._container.close()
                except Exception as e:
                    logger.debug(f"PyAVNVDECDecoder({self.camera_id}): Container close error: {e}")
                finally:
                    self._container = None
                    self._stream = None
                    self._hwaccel = None
            
            self._opened = False
            logger.info(f"PyAVNVDECDecoder({self.camera_id}): closed")
    
    def reconnect(self) -> bool:
        """Reconnect by closing and reopening."""
        self.close()
        time.sleep(self.config.timeout)
        try:
            self.open()
            return True
        except Exception as e:
            logger.error(f"PyAVNVDECDecoder({self.camera_id}): Reconnect failed: {e}")
            return False
    
    @property
    def is_opened(self) -> bool:
        return self._opened
    
    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def create_pyav_nvdec_decoder(
    camera_id: str,
    rtsp_url: str,
    nvdec_gpu_device: int = 0,
    expected_width: int = 3840,
    expected_height: int = 2160,
    expected_fps: float = 30.0,
    ffmpeg_path: Optional[str] = None,
    nvdec_surfaces: int = 32,
    scale_cuda: Optional[str] = None,
) -> PyAVNVDECDecoder:
    """Factory function to create PyAVNVDECDecoder."""
    config = PyAVNVDECDecoderConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        nvdec_gpu_device=nvdec_gpu_device,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_fps=expected_fps,
        ffmpeg_path=ffmpeg_path,
        nvdec_surfaces=nvdec_surfaces,
        scale_cuda=scale_cuda,
    )
    return PyAVNVDECDecoder(config)