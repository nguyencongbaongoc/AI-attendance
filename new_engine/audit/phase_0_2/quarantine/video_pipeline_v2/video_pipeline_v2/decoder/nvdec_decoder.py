"""
NVDEC Decoder - V2 GPU-first video pipeline.

Hardware-accelerated H.264/H.265 decoding directly to CUDA memory.
Zero-copy path: compressed packets → NVDEC → GPUFrame (NV12 on GPU).
No CPU frame staging in production path.
"""

from __future__ import annotations

import logging
import threading
import queue
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Any, Iterator, Dict, List, Tuple
from enum import Enum

import torch

logger = logging.getLogger(__name__)


class DecoderState(str, Enum):
    """Decoder lifecycle states."""
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    READY = "ready"
    DECODING = "decoding"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class NVDECDecoderConfig:
    """Configuration for NVDEC decoder."""
    camera_id: str
    # Input
    packet_source: Any  # PacketInput instance
    # GPU
    gpu_device: int = 0
    cuda_context: Optional[Any] = None  # Shared CUDA context
    cuda_stream: Optional[torch.cuda.Stream] = None  # Shared CUDA stream
    # Decoder
    codec: str = "h264"  # h264, h265
    width: int = 3840
    height: int = 2160
    max_surfaces: int = 32
    # Output queue
    max_queue_size: int = 8
    # Timing
    timeout: float = 10.0
    # Retry
    max_retries: int = 3
    retry_backoff: float = 2.0
    # Scaling (optional, done on GPU)
    scale_width: Optional[int] = None
    scale_height: Optional[int] = None


@dataclass
class DecoderMetrics:
    """Decoder performance metrics."""
    frames_decoded: int = 0
    frames_dropped: int = 0
    decode_errors: int = 0
    queue_full_drops: int = 0
    last_decode_time: float = 0.0
    avg_decode_ms: float = 0.0
    gpu_memory_mb: float = 0.0
    state: DecoderState = DecoderState.STOPPED
    reconnect_count: int = 0
    last_error: str = ""


class NVDECDecoder:
    """
    NVDEC hardware decoder using PyAV with CUDA hwaccel.
    
    Pipeline:
        CompressedPacket (H.264 NAL)
            → PyAV demuxer
            → NVDEC (CUDA hwaccel)
            → AVFrame (format='cuda', NV12 2-plane)
            → DLPack → PyTorch CUDA tensors
            → GPUFrame contract
    
    Zero-copy: No CPU memory allocation for frame data.
    """
    
    def __init__(self, config: NVDECDecoderConfig):
        self.config = config
        self.camera_id = config.camera_id
        self._state = DecoderState.STOPPED
        self._metrics = DecoderMetrics()
        
        # PyAV objects
        self._container = None
        self._stream = None
        self._hwaccel = None
        self._codec_context = None
        
        # CUDA
        self._cuda_device = config.gpu_device
        self._cuda_context = config.cuda_context
        # Don't create CUDA stream here - it may conflict with NVDEC hwaccel
        # The stream will be created lazily in the reader thread if needed
        self._cuda_stream = config.cuda_stream
        
        # Threading
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_queue: "queue.Queue[Any]" = queue.Queue(maxsize=config.max_queue_size)
        self._frame_id = 0
        self._error: Optional[Exception] = None
        self._lock = threading.RLock()
        
        # Stats
        self._decode_times: List[float] = []
        self._max_decode_samples = 100
        
        # Expected dimensions (may be updated from stream)
        self._width = config.width
        self._height = config.height
        self._fps = 30.0
    
    @property
    def state(self) -> DecoderState:
        return self._state
    
    @property
    def metrics(self) -> DecoderMetrics:
        m = self._metrics
        m.state = self._state
        return m
    
    def _set_state(self, state: DecoderState) -> None:
        with self._lock:
            old_state = self._state
            self._state = state
            self._metrics.state = state
            if old_state != state:
                logger.info(f"NVDECDecoder({self.camera_id}): state {old_state.value} → {state.value}")
    
    def _build_hwaccel(self):
        """Build PyAV HWAccel for CUDA decoding."""
        import av
        from av.codec.hwaccel import HWAccel
        
        hw = HWAccel(
            device_type="cuda",
            is_hw_owned=True,
            allow_software_fallback=False,  # Critical: no CPU fallback
        )
        return hw
    
    def _open_container(self) -> None:
        """Open PyAV container with NVDEC hardware acceleration."""
        import av
        
        # Use the packet source's URL
        if hasattr(self.config.packet_source, 'url'):
            url = self.config.packet_source.url
        else:
            raise ValueError("Packet source must have 'url' attribute")
        
        # Determine format and options based on URL
        is_rtmp = url.lower().startswith("rtmp://")
        is_file = not (is_rtmp or url.lower().startswith("rtsp://"))
        
        if is_file:
            # For local files, use explicit format and no transport options
            format_name = "mp4"  # Explicit format for mp4 files
            options = {
                "hwaccel": "cuda",
                "hwaccel_device": str(self._cuda_device),
                "hwaccel_output_format": "cuda",
            }
        elif is_rtmp:
            format_name = "flv"
            options = {
                "hwaccel": "cuda",
                "hwaccel_device": str(self._cuda_device),
                "hwaccel_output_format": "cuda",
                "rtmp_buffer": "100",
            }
        else:
            format_name = "rtsp"
            options = {
                "hwaccel": "cuda",
                "hwaccel_device": str(self._cuda_device),
                "hwaccel_output_format": "cuda",
                "rtsp_transport": "tcp",
            }
        
        self._hwaccel = self._build_hwaccel()
        
        self._container = av.open(
            url,
            format=format_name,
            options=options,
            hwaccel=self._hwaccel,
        )
        
        # Get video stream
        self._stream = self._container.streams.video[0]
        self._codec_context = self._stream.codec_context
        
        # Update dimensions from stream
        self._width = self._stream.width or self.config.width
        self._height = self._stream.height or self.config.height
        self._fps = float(self._stream.average_rate) if self._stream.average_rate else 30.0
        
        logger.info(
            f"NVDECDecoder({self.camera_id}): opened {self._width}x{self._height}@{self._fps}fps "
            f"codec={self._codec_context.name} pix_fmt=cuda (NV12)"
        )
    
    def start(self) -> bool:
        """Start the decoder."""
        with self._lock:
            if self._state in (DecoderState.READY, DecoderState.DECODING):
                logger.warning(f"NVDECDecoder({self.camera_id}): already started")
                return True
            
            self._set_state(DecoderState.INITIALIZING)
            
            try:
                # Open container with NVDEC
                self._open_container()
                
                # Start reader thread
                self._stop_event.clear()
                self._reader_thread = threading.Thread(
                    target=self._reader_loop,
                    name=f"nvdec-reader-{self.camera_id}",
                    daemon=True,
                )
                self._reader_thread.start()
                
                self._frame_id = 0
                self._error = None
                self._set_state(DecoderState.DECODING)
                
                logger.info(f"NVDECDecoder({self.camera_id}): started successfully")
                return True
                
            except Exception as e:
                self._error = e
                self._set_state(DecoderState.ERROR)
                logger.error(f"NVDECDecoder({self.camera_id}): start failed: {e}")
                logger.debug(traceback.format_exc())
                return False
    
    def _reader_loop(self) -> None:
        """Read frames from NVDEC and convert to GPUFrame."""
        import av
        import torch
        
        try:
            # Note: Do NOT call torch.cuda.set_device() before NVDEC initialization
            # It can cause OSError -129. The CUDA stream will be set in reader loop.
            for frame in self._container.decode(video=0):
                if self._stop_event.is_set():
                    break
                
                decode_start = time.perf_counter()
                
                # Validate frame
                if frame.format.name != "cuda":
                    logger.warning(
                        f"NVDECDecoder({self.camera_id}): Expected CUDA frame, got {frame.format.name}"
                    )
                    # Still process but log warning
                    is_gpu = False
                else:
                    is_gpu = True
                
                if not is_gpu:
                    self._metrics.decode_errors += 1
                    continue
                
                # Frame is PyAV VideoFrame with format='cuda' (AV_PIX_FMT_CUDA)
                # 2 planes: plane 0 = Y, plane 1 = interleaved UV
                try:
                    # Get DLPack capsules from both planes
                    dlpack_y = frame.planes[0].__dlpack__()
                    dlpack_uv = frame.planes[1].__dlpack__()
                    
                    # Convert to PyTorch CUDA tensors (zero-copy)
                    y_tensor = torch.utils.dlpack.from_dlpack(dlpack_y)
                    uv_tensor = torch.utils.dlpack.from_dlpack(dlpack_uv)
                    
                    # Ensure contiguous
                    y_tensor = y_tensor.contiguous()
                    uv_tensor = uv_tensor.contiguous()
                    
                    # Validate shapes
                    H, W = y_tensor.shape
                    if uv_tensor.shape != (H // 2, W // 2, 2):
                        logger.warning(
                            f"NVDECDecoder({self.camera_id}): Unexpected UV shape {uv_tensor.shape} for Y {y_tensor.shape}"
                        )
                    
                    # Create GPUFrame
                    timestamp = time.time()
                    pts = frame.pts if frame.pts is not None else self._frame_id
                    
                    gpu_frame = GPUFrame.from_pyav_nvdec(
                        y_tensor=y_tensor,
                        uv_tensor=uv_tensor,
                        camera_id=self.camera_id,
                        frame_id=self._frame_id,
                        timestamp=timestamp,
                        pts=pts,
                        width=W,
                        height=H,
                        cuda_context=self._cuda_context,
                    )
                    
                    # Queue frame
                    try:
                        self._frame_queue.put_nowait(gpu_frame)
                    except queue.Full:
                        self._metrics.queue_full_drops += 1
                        # Drop oldest
                        try:
                            old_frame = self._frame_queue.get_nowait()
                            old_frame.release()
                        except queue.Empty:
                            pass
                        try:
                            self._frame_queue.put_nowait(gpu_frame)
                        except queue.Full:
                            gpu_frame.release()
                            self._metrics.frames_dropped += 1
                    
                    self._frame_id += 1
                    self._metrics.frames_decoded += 1
                    
                    # Track decode time
                    decode_ms = (time.perf_counter() - decode_start) * 1000
                    self._decode_times.append(decode_ms)
                    if len(self._decode_times) > self._max_decode_samples:
                        self._decode_times.pop(0)
                    self._metrics.avg_decode_ms = sum(self._decode_times) / len(self._decode_times)
                    self._metrics.last_decode_time = timestamp
                    
                except Exception as e:
                    self._metrics.decode_errors += 1
                    logger.error(f"NVDECDecoder({self.camera_id}): Frame conversion failed: {e}")
                    continue
                    
        except av.error.FFmpegError as e:
            logger.error(f"NVDECDecoder({self.camera_id}): FFmpeg decode error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"NVDECDecoder({self.camera_id}): Reader loop error: {e}")
            self._error = e
        finally:
            logger.debug(f"NVDECDecoder({self.camera_id}): Reader loop exited")
            self._set_state(DecoderState.ERROR)
    
    def get_frame(self, timeout: float = 1.0) -> Optional["GPUFrame"]:
        """Get next decoded GPUFrame."""
        if self._state != DecoderState.DECODING:
            if self._state == DecoderState.STOPPED:
                self.start()
            elif self._state == DecoderState.ERROR:
                # Try to reconnect
                if not self.reconnect():
                    return None
        
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def iter_frames(self) -> Iterator["GPUFrame"]:
        """Iterate decoded frames."""
        while self._state == DecoderState.DECODING:
            frame = self.get_frame(1.0)
            if frame is None:
                if self._state != DecoderState.DECODING:
                    break
                continue
            yield frame
    
    def reconnect(self) -> bool:
        """Reconnect decoder after error."""
        with self._lock:
            if self._state == DecoderState.RECONNECTING:
                return False
            
            self._set_state(DecoderState.RECONNECTING)
            self._metrics.reconnect_count += 1
            
            logger.info(f"NVDECDecoder({self.camera_id}): reconnecting (attempt {self._metrics.reconnect_count})")
            
            # Close current
            self._close_internal()
            
            # Wait before retry
            time.sleep(self.config.retry_backoff)
            
            # Retry
            for attempt in range(self.config.max_retries):
                try:
                    torch.cuda.set_device(self._cuda_device)
                    self._open_container()
                    
                    self._stop_event.clear()
                    self._reader_thread = threading.Thread(
                        target=self._reader_loop,
                        name=f"nvdec-reader-{self.camera_id}",
                        daemon=True,
                    )
                    self._reader_thread.start()
                    
                    self._error = None
                    self._set_state(DecoderState.DECODING)
                    
                    logger.info(f"NVDECDecoder({self.camera_id}): reconnected successfully")
                    return True
                    
                except Exception as e:
                    logger.warning(f"NVDECDecoder({self.camera_id}): Reconnect attempt {attempt+1} failed: {e}")
                    time.sleep(self.config.retry_backoff * (attempt + 1))
            
            self._set_state(DecoderState.ERROR)
            return False
    
    def _close_internal(self) -> None:
        """Internal close without lock."""
        self._stop_event.set()
        
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)
        
        if self._container:
            try:
                self._container.close()
            except Exception as e:
                logger.debug(f"NVDECDecoder({self.camera_id}): Container close error: {e}")
            finally:
                self._container = None
                self._stream = None
                self._hwaccel = None
                self._codec_context = None
        
        # Clear queue
        while True:
            try:
                frame = self._frame_queue.get_nowait()
                frame.release()
            except queue.Empty:
                break
    
    def stop(self) -> None:
        """Stop the decoder."""
        with self._lock:
            if self._state == DecoderState.STOPPED:
                return
            
            logger.info(f"NVDECDecoder({self.camera_id}): stopping")
            self._close_internal()
            self._set_state(DecoderState.STOPPED)
            logger.info(f"NVDECDecoder({self.camera_id}): stopped")
    
    def get_queue_depth(self) -> int:
        return self._frame_queue.qsize()
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "state": self._state.value,
                "frames_decoded": self._metrics.frames_decoded,
                "frames_dropped": self._metrics.frames_dropped,
                "decode_errors": self._metrics.decode_errors,
                "queue_full_drops": self._metrics.queue_full_drops,
                "queue_depth": self._frame_queue.qsize(),
                "avg_decode_ms": self._metrics.avg_decode_ms,
                "reconnect_count": self._metrics.reconnect_count,
                "last_error": self._metrics.last_error,
                "width": self._width,
                "height": self._height,
                "fps": self._fps,
                "gpu_device": self._cuda_device,
            }
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# Import GPUFrame here to avoid circular import
from video_pipeline_v2.core.gpu_frame import GPUFrame


if __name__ == "__main__":
    # Test with file source
    import sys
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        
        from video_pipeline_v2.input.packet_input import create_packet_source, FileSourceConfig
        
        packet_source = create_packet_source("file", "test_cam", test_file)
        
        config = NVDECDecoderConfig(
            camera_id="test_cam",
            packet_source=packet_source,
            gpu_device=0,
        )
        
        decoder = NVDECDecoder(config)
        decoder.start()
        
        count = 0
        for frame in decoder.iter_frames():
            print(f"Frame {count}: {frame.width}x{frame.height}, id={frame.frame_id}, pts={frame.pts}")
            count += 1
            if count >= 10:
                break
        
        decoder.stop()
        print(f"Decoded {count} frames")
        print(f"Stats: {decoder.get_stats()}")
    else:
        print("Usage: python nvdec_decoder.py <video_file>")