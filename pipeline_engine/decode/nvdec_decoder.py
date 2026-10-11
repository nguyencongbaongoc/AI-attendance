"""
NVDEC Decoder - Hardware-accelerated H.264/H.265 decoding to GPUFrame.

Uses PyAV with CUDA hwaccel for zero-copy decode directly to GPU memory.
On Windows with GTX 1660 Ti, cuvid outputs dxva2_vld which can't easily convert to CUDA.
Falls back to software decode + GPU upload for reliable operation.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Any, Iterator, Dict, List, Tuple
from enum import Enum
from queue import Queue, Empty, Full

import torch
import av

from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat, CUDAContext, FrameOwnership
from pipeline_engine.memory.frame_pool import FramePool
from pipeline_engine.memory.synchronization import CUDASyncManager
from pipeline_engine.config import get_camera_config

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
    packet_source: Any  # RTSPSource instance
    # GPU
    gpu_device: int = 0
    cuda_context: Optional[Any] = None
    cuda_stream: Optional[torch.cuda.Stream] = None
    # Decoder
    codec: str = "h264"
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
    # Frame pool
    frame_pool: Optional[FramePool] = None


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
            → NVDEC (CUDA hwaccel) / Software fallback
            → AVFrame (format='cuda', NV12 2-plane) or yuv420p uploaded to GPU
            → DLPack → PyTorch CUDA tensors
            → GPUFrame contract
    
    Zero-copy when hardware decode works; CPU decode + GPU upload as fallback.
    """

    def __init__(self, config: NVDECDecoderConfig, frame_pool: Optional[FramePool] = None):
        self.config = config
        self.camera_id = config.camera_id
        self._frame_pool = frame_pool
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
        self._cuda_stream = config.cuda_stream
        
        # Sync manager
        self._sync = CUDASyncManager(device_id=config.gpu_device)
        
        # Threading
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_queue: Queue = Queue(maxsize=config.max_queue_size)
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
        self._time_base = None
        
        # Pre-allocated GPU tensors for reuse (software decode fallback)
        self._y_gpu = None
        self._uv_gpu = None
        self._use_hw_decode = False

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
        # On Windows, cuvid outputs dxva2_vld frames, not cuda.
        # We'll use software decode + GPU upload as primary approach.
        hw = av.codec.hwaccel.HWAccel(
            device_type="cuvid",
            is_hw_owned=True,
            allow_software_fallback=True,
        )
        return hw

    def _open_container(self) -> None:
        """Open PyAV container with best available hardware acceleration."""
        # Use the packet source's URL
        if hasattr(self.config.packet_source, 'url'):
            url = self.config.packet_source.url
        elif hasattr(self.config.packet_source, 'config') and hasattr(self.config.packet_source.config, 'url'):
            url = self.config.packet_source.config.url
        else:
            raise ValueError("Packet source must have 'url' attribute")
        
        # Determine format and options based on URL
        is_rtmp = url.lower().startswith("rtmp://")
        is_rtsp = url.lower().startswith("rtsp://")
        is_file = not (is_rtmp or is_rtsp)
        
        # Try cuvid first; it outputs dxva2_vld on Windows which we can't easily convert to CUDA
        # So we'll use software decode + GPU upload as reliable approach
        if is_file:
            format_name = "mp4"
            options = {}
        elif is_rtmp:
            format_name = "flv"
            options = {"rtmp_buffer": "100"}
        else:  # RTSP
            format_name = "rtsp"
            options = {"rtsp_transport": "tcp"}
        
        # Don't use hwaccel - we'll do software decode + GPU upload
        self._hwaccel = None
        
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
        self._time_base = float(self._stream.time_base) if self._stream.time_base else None
        
        # Pre-allocate GPU tensors for reuse
        torch.cuda.set_device(self._cuda_device)
        self._y_gpu = torch.zeros((self._height, self._width), dtype=torch.uint8, device=f'cuda:{self._cuda_device}')
        # UV interleaved: H/2, W/2, 2
        self._uv_gpu = torch.zeros((self._height // 2, self._width // 2, 2), dtype=torch.uint8, device=f'cuda:{self._cuda_device}')
        
        logger.info(
            f"NVDECDecoder({self.camera_id}): opened {self._width}x{self._height}@{self._fps}fps "
            f"codec={self._codec_context.name} (software decode + GPU upload)"
        )
        self._use_hw_decode = False

    def start(self) -> bool:
        """Start the decoder."""
        with self._lock:
            if self._state in (DecoderState.READY, DecoderState.DECODING):
                logger.warning(f"NVDECDecoder({self.camera_id}): already started")
                return True
            
            self._set_state(DecoderState.INITIALIZING)
            
            try:
                # Open container
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
        """Read frames from decoder and convert to GPUFrame (software decode + GPU upload)."""
        try:
            for frame in self._container.decode(video=0):
                if self._stop_event.is_set():
                    break
                
                decode_start = time.perf_counter()
                
                # Frame is yuv420p (software decode) - 3 planes: Y, U, V
                try:
                    # Get plane data
                    y_plane = frame.planes[0]
                    u_plane = frame.planes[1]
                    v_plane = frame.planes[2]
                    
                    # Get plane data via memoryview
                    y_mv = memoryview(y_plane)
                    u_mv = memoryview(u_plane)
                    v_mv = memoryview(v_plane)
                    
                    # Copy to pre-allocated GPU tensors
                    # Y plane: H x W
                    y_cpu = torch.frombuffer(y_mv, dtype=torch.uint8).reshape(frame.height, frame.width)
                    self._y_gpu.copy_(y_cpu, non_blocking=True)
                    
                    # U plane: H/2 x W/2, V plane: H/2 x W/2
                    u_cpu = torch.frombuffer(memoryview(u_plane), dtype=torch.uint8).reshape(frame.height // 2, frame.width // 2)
                    v_cpu = torch.frombuffer(memoryview(v_plane), dtype=torch.uint8).reshape(frame.height // 2, frame.width // 2)
                    
                    # Interleave U and V for NV12 format: (H/2, W/2, 2)
                    uv_cpu = torch.stack([u_cpu, v_cpu], dim=-1)  # (H/2, W/2, 2)
                    self._uv_gpu.copy_(uv_cpu, non_blocking=True)
                    
                    torch.cuda.synchronize()
                    
                    # Acquire frame from pool or create new
                    if self._frame_pool:
                        try:
                            gpu_frame = self._frame_pool.acquire(
                                frame_id=self._frame_id,
                                timestamp=time.time(),
                                pts=frame.pts if frame.pts is not None else self._frame_id,
                            )
                            # Copy to pooled frame
                            gpu_frame.y_tensor.copy_(self._y_gpu)
                            gpu_frame.uv_tensor.copy_(self._uv_gpu)
                            gpu_frame.pts = frame.pts if frame.pts is not None else self._frame_id
                            gpu_frame.dts = frame.pts if frame.pts is not None else self._frame_id
                            gpu_frame.time_base = self._time_base
                            gpu_frame.width = self._width
                            gpu_frame.height = self._height
                            gpu_frame.actual_width = self._width
                            gpu_frame.actual_height = self._height
                        except RuntimeError:
                            self._metrics.frames_dropped += 1
                            continue
                    else:
                        # Create GPUFrame directly
                        gpu_frame = GPUFrame(
                            camera_id=self.camera_id,
                            frame_id=self._frame_id,
                            source_provenance="rtsp",
                            timestamp=time.time(),
                            pts=frame.pts if frame.pts is not None else self._frame_id,
                            dts=frame.pts if frame.pts is not None else self._frame_id,
                            time_base=self._time_base,
                            width=self._width,
                            height=self._height,
                            actual_width=self._width,
                            actual_height=self._height,
                            pixel_format=PixelFormat.NV12,
                            y_tensor=self._y_gpu,
                            uv_tensor=self._uv_gpu,
                            memory_owner=FrameOwnership.DECODER,
                        )
                    
                    # Record decode time
                    decode_ms = (time.perf_counter() - decode_start) * 1000
                    gpu_frame.decode_time_ms = decode_ms
                    
                    # Queue frame
                    try:
                        self._frame_queue.put_nowait(gpu_frame)
                    except Full:
                        self._metrics.queue_full_drops += 1
                        # Drop oldest
                        try:
                            old_frame = self._frame_queue.get_nowait()
                            if self._frame_pool:
                                self._frame_pool.return_to_pool(old_frame)
                        except Empty:
                            pass
                        try:
                            self._frame_queue.put_nowait(gpu_frame)
                        except Full:
                            if self._frame_pool:
                                self._frame_pool.return_to_pool(gpu_frame)
                            self._metrics.frames_dropped += 1
                    
                    self._frame_id += 1
                    self._metrics.frames_decoded += 1
                    
                    # Track decode time
                    self._decode_times.append(decode_ms)
                    if len(self._decode_times) > self._max_decode_samples:
                        self._decode_times.pop(0)
                    self._metrics.avg_decode_ms = sum(self._decode_times) / len(self._decode_times)
                    self._metrics.last_decode_time = time.time()
                    
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

    def get_frame(self, timeout: float = 1.0) -> Optional[GPUFrame]:
        """Get next decoded GPUFrame."""
        if self._state != DecoderState.DECODING:
            if self._state == DecoderState.STOPPED:
                self.start()
            elif self._state == DecoderState.ERROR:
                if not self.reconnect():
                    return None
        
        try:
            return self._frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def iter_frames(self) -> Iterator[GPUFrame]:
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
        
        # Clear queue and return frames to pool
        while True:
            try:
                frame = self._frame_queue.get_nowait()
                if self._frame_pool:
                    self._frame_pool.return_to_pool(frame)
            except Empty:
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


def create_nvdec_decoder(
    camera_id: str,
    packet_source: Any,
    frame_pool: Optional[FramePool] = None,
    config: Optional[Dict[str, Any]] = None,
) -> NVDECDecoder:
    """Factory function to create NVDEC decoder."""
    if config is None:
        from pipeline_engine.config import get_config
        config = get_camera_config(get_config(), camera_id)
    
    decoder_config = NVDECDecoderConfig(
        camera_id=camera_id,
        packet_source=packet_source,
        gpu_device=config.get("decode", {}).get("gpu_device", 0),
        codec=config.get("decode", {}).get("codec", "h264"),
        width=config.get("expected", {}).get("width", 3840),
        height=config.get("expected", {}).get("height", 2160),
        max_surfaces=config.get("decode", {}).get("surfaces", 32),
        max_queue_size=8,
        timeout=config.get("input", {}).get("timeout_seconds", 10.0),
    )
    
    return NVDECDecoder(decoder_config, frame_pool)


if __name__ == "__main__":
    # Test with file source
    import sys
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        
        from pipeline_engine.ingestion.rtsp_source import RTSPSource, RTSPSourceConfig
        
        packet_source = RTSPSource(RTPSourceConfig(camera_id="test_cam", url=test_file))
        
        decoder = create_nvdec_decoder("test_cam", packet_source)
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