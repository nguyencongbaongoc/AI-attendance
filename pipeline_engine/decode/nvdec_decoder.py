"""
NVDEC Decoder - Hardware-accelerated H.264/H.265 decoding to GPUFrame.

Uses PyNvVideoCodec for zero-copy NVDEC decode directly to GPU memory.
On Windows with GTX 1660 Ti, provides true hardware decoding in VRAM.
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

from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat, CUDAContext, FrameOwnership
from pipeline_engine.memory.frame_pool import FramePool
from pipeline_engine.memory.synchronization import CUDASyncManager
from pipeline_engine.config import get_camera_config

logger = logging.getLogger(__name__)

# Import PyNvVideoCodec
try:
    import PyNvVideoCodec as nvc
    PYNVIDEOCODEC_AVAILABLE = True
except ImportError:
    try:
        import PyNvVideoCodec as nvc
        PYNVIDEOCODEC_AVAILABLE = True
    except ImportError:
        PYNVIDEOCODEC_AVAILABLE = False
        nvc = None


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
        
        # Transient decode error & IDR keyframe recovery tracking
        self._waiting_for_keyframe = False
        self._first_decode_error_time: Optional[float] = None
        self._consecutive_decode_errors = 0

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
                logger.info(f"NVDECDecoder({self.camera_id}): state {old_state.value} -> {state.value}")

    def _build_hwaccel(self):
        """Build PyNvVideoCodec decoder for true hardware NVDEC."""
        if not PYNVIDEOCODEC_AVAILABLE:
            raise RuntimeError("PyNvVideoCodec not available. Cannot use hardware NVDEC.")
        return None  # Not used with PyNvVideoCodec

    def _open_container(self) -> None:
        """Initialize PyNvVideoCodec decoder for true hardware NVDEC."""
        if not PYNVIDEOCODEC_AVAILABLE:
            raise RuntimeError("PyNvVideoCodec not available. Cannot use hardware NVDEC.")
        
        # Get URL from packet source
        if hasattr(self.config.packet_source, 'url'):
            url = self.config.packet_source.url
        elif hasattr(self.config.packet_source, 'config') and hasattr(self.config.packet_source.config, 'url'):
            url = self.config.packet_source.config.url
        else:
            raise ValueError("Packet source must have 'url' attribute")
        
        self._rtsp_url = url
        
        # Determine if it's a local file or network stream
        is_rtmp = url.lower().startswith("rtmp://")
        is_rtsp = url.lower().startswith("rtsp://")
        is_file = not (is_rtmp or is_rtsp)
        
        # Open PyAV container for demuxing only (packet extraction)
        if is_file:
            format_name = "mp4"
            options = {}
        elif is_rtmp:
            format_name = "flv"
            options = {"rtmp_buffer": "100"}
        else:  # RTSP
            format_name = "rtsp"
            options = {
                "rtsp_transport": "tcp",
                "buffer_size": "10240000",
                "max_delay": "500000",
                "stimeout": "5000000",
            }
        
        import av
        self._container = av.open(
            url,
            format=format_name,
            options=options,
        )
        
        # Get video stream for metadata
        self._stream = self._container.streams.video[0]
        self._codec_context = self._stream.codec_context
        
        # Update dimensions from stream
        self._width = self._stream.width or self.config.width
        self._height = self._stream.height or self.config.height
        self._fps = float(self._stream.average_rate) if self._stream.average_rate else 30.0
        self._time_base = float(self._stream.time_base) if self._stream.time_base else None
        
        # Initialize PyNvVideoCodec decoder
        self._init_pynv_decoder()
        
        logger.info(
            f"NVDECDecoder({self.camera_id}): Hardware NVDEC ACTIVE via PyNvVideoCodec "
            f"on GPU {self._cuda_device} ({self._width}x{self._height}@{self._fps}fps)"
        )
        self._use_hw_decode = True
    
    def _init_pynv_decoder(self):
        """Initialize PyNvVideoCodec decoder with CUDA context."""
        import ctypes
        import torch
        
        # Set CUDA device
        torch.cuda.set_device(self._cuda_device)
        
        # Get or create CUDA stream
        if self._cuda_stream is None:
            self._cuda_stream = torch.cuda.Stream(device=f'cuda:{self._cuda_device}')
        
        stream_handle = self._cuda_stream.cuda_stream
        
        # Use default CUDA context (0) - PyNvVideoCodec will use the current context
        cudacontext = self._cuda_context if self._cuda_context is not None else 0
        
        # Map output color type - NV12 native
        output_color_type = nvc.OutputColorType.NATIVE
        
        # Create decoder
        self._decoder = nvc.CreateDecoder(
            gpuid=self._cuda_device,
            codec=nvc.cudaVideoCodec.H264,
            cudacontext=cudacontext,
            cudastream=stream_handle,
            usedevicememory=True,
            enableasyncallocations=True,
            maxwidth=self._width,
            maxheight=self._height,
            outputColorType=output_color_type,
            enableSEIMessage=False,
            latency=nvc.DisplayDecodeLatencyType.NATIVE,
            enableDecodeStats=False,
        )
        
        logger.info(
            f"NVDECDecoder({self.camera_id}): PyNvVideoCodec decoder created "
            f"(gpu={self._cuda_device}, context={cudacontext}, stream={stream_handle})"
        )

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
        """Read packets from demuxer, decode with PyNvVideoCodec, push frames to queue."""
        import ctypes
        import av
        
        try:
            self._waiting_for_keyframe = False
            self._first_decode_error_time = None
            self._consecutive_decode_errors = 0
            
            # Use PyAV container for demuxing (RTSP/RTMP)
            demux_iter = iter(self._container.demux(self._stream))
            while not self._stop_event.is_set():
                try:
                    packet = next(demux_iter)
                except StopIteration:
                    break
                except Exception as e:
                    # Transient demux error (e.g. truncated packet)
                    now = time.time()
                    self._metrics.decode_errors += 1
                    self._metrics.frames_dropped += 1
                    self._waiting_for_keyframe = True
                    if self._first_decode_error_time is None:
                        self._first_decode_error_time = now
                    err_dur = now - self._first_decode_error_time
                    if err_dur > 3.0:
                        logger.error(f"NVDECDecoder({self.camera_id}): Demux errors persisted > 3s: {e}")
                        raise
                    logger.warning(
                        f"NVDECDecoder({self.camera_id}): Transient demux error ({err_dur:.2f}s), "
                        f"waiting for IDR keyframe: {e}"
                    )
                    time.sleep(0.01)
                    continue

                if self._stop_event.is_set():
                    break

                # If waiting for IDR keyframe after decode error or corrupted packet
                if self._waiting_for_keyframe:
                    if not packet.is_keyframe:
                        self._metrics.frames_dropped += 1
                        continue
                    else:
                        logger.info(f"NVDECDecoder({self.camera_id}): IDR Keyframe received, recovering decode stream")
                        self._waiting_for_keyframe = False

                if packet.is_corrupt:
                    self._metrics.frames_dropped += 1
                    self._waiting_for_keyframe = True
                    continue

                decode_start = time.perf_counter()

                # Create PyNvVideoCodec PacketData from PyAV packet
                pnv_packet = nvc.PacketData()
                pnv_packet.bsl = packet.size
                pnv_packet.bsl_data = packet.buffer_ptr
                pnv_packet.pts = packet.pts if packet.pts is not None else 0
                pnv_packet.dts = packet.dts if packet.dts is not None else 0
                pnv_packet.duration = packet.duration if packet.duration is not None else 0
                pnv_packet.decode_flag = 0
                pnv_packet.key = 1 if packet.is_keyframe else 0
                pnv_packet.is_video = 1
                pnv_packet.stream_index = 0

                # Decode packet with PyNvVideoCodec
                try:
                    decode_fn = getattr(self._decoder, "Decode", None) or getattr(self._decoder, "decode", None)
                    decoded_frames = decode_fn(pnv_packet)
                    # Successful decode resets error streak
                    self._first_decode_error_time = None
                    self._consecutive_decode_errors = 0
                except Exception as e:
                    now = time.time()
                    self._metrics.decode_errors += 1
                    self._metrics.frames_dropped += 1
                    self._consecutive_decode_errors += 1
                    if self._first_decode_error_time is None:
                        self._first_decode_error_time = now

                    error_duration = now - self._first_decode_error_time
                    self._waiting_for_keyframe = True

                    # Only degrade and exit reader loop if errors persist > 3 consecutive seconds
                    if error_duration > 3.0:
                        logger.error(
                            f"NVDECDecoder({self.camera_id}): Decode errors persisted for {error_duration:.1f}s (> 3s threshold): {e}"
                        )
                        self._metrics.last_error = str(e)
                        self._set_state(DecoderState.ERROR)
                        break
                    else:
                        logger.warning(
                            f"NVDECDecoder({self.camera_id}): Transient decode error ({error_duration:.2f}s elapsed), "
                            f"dropping frame and waiting for next IDR keyframe: {e}"
                        )
                        continue
                
                # Process decoded frames
                for decoded_frame in decoded_frames:
                    if self._stop_event.is_set():
                        break
                    
                    # Get frame timestamp
                    timestamp = time.time()
                    pts = decoded_frame.getPTS()
                    
                    # Get frame dimensions from shape
                    shape = decoded_frame.shape
                    if len(shape) == 2:
                        height = shape[0] * 2 // 3  # NV12 is 1.5x height
                        width = shape[1]
                    else:
                        width = self._width
                        height = self._height
                    
                    # Verify NV12 format
                    pixel_format = str(decoded_frame.format)
                    if "NV12" not in pixel_format.upper():
                        logger.warning(f"NVDECDecoder({self.camera_id}): Unexpected pixel format: {pixel_format}, assuming NV12")
                    
                    # Get CAI memory views (zero-copy)
                    try:
                        cai_views = decoded_frame.cuda()
                    except Exception as e:
                        logger.error(f"NVDECDecoder({self.camera_id}): CAI export failed: {e}")
                        try:
                            self._decoder.UnlockFrame(0)
                        except Exception:
                            pass
                        continue
                    
                    if len(cai_views) < 2:
                        logger.error(f"NVDECDecoder({self.camera_id}): Expected 2 CAI views (Y, UV), got {len(cai_views)}")
                        try:
                            self._decoder.UnlockFrame(0)
                        except Exception:
                            pass
                        continue
                    
                    y_view = cai_views[0]
                    uv_view = cai_views[1]
                    
                    # Convert CAI views to PyTorch CUDA tensors (zero-copy)
                    try:
                        y_tensor = torch.as_tensor(y_view, device='cuda')
                        uv_tensor = torch.as_tensor(uv_view, device='cuda')
                    except Exception as e:
                        logger.error(f"NVDECDecoder({self.camera_id}): PyTorch tensor creation failed: {e}")
                        try:
                            self._decoder.UnlockFrame(0)
                        except Exception:
                            pass
                        continue
                    
                    # Squeeze Y if needed (H, W, 1) -> (H, W)
                    if y_tensor.dim() == 3 and y_tensor.shape[2] == 1:
                        y_tensor = y_tensor.squeeze(2)
                    
                    # Validate tensors
                    assert y_tensor.is_cuda, f"y_tensor must be on CUDA, got {y_tensor.device}"
                    assert uv_tensor.is_cuda, f"uv_tensor must be on CUDA, got {uv_tensor.device}"
                    assert y_tensor.dtype == torch.uint8, f"y_tensor must be uint8, got {y_tensor.dtype}"
                    assert uv_tensor.dtype == torch.uint8, f"uv_tensor must be uint8, got {uv_tensor.dtype}"
                    
                    # Acquire frame from pool or create new
                    if self._frame_pool:
                        try:
                            gpu_frame = self._frame_pool.acquire(
                                frame_id=self._frame_id,
                                timestamp=timestamp,
                                pts=pts if pts is not None else self._frame_id,
                            )
                            # Copy to pooled frame (zero-copy via tensor assignment)
                            gpu_frame.y_tensor.copy_(y_tensor)
                            gpu_frame.uv_tensor.copy_(uv_tensor)
                            gpu_frame.pts = pts if pts is not None else self._frame_id
                            gpu_frame.dts = pts if pts is not None else self._frame_id
                            gpu_frame.time_base = self._time_base
                            gpu_frame.width = width
                            gpu_frame.height = height
                            gpu_frame.actual_width = width
                            gpu_frame.actual_height = height
                        except RuntimeError:
                            self._metrics.frames_dropped += 1
                            # Unlock frame
                            try:
                                self._decoder.UnlockFrame(0)
                            except Exception:
                                pass
                            continue
                    else:
                        # Create GPUFrame directly
                        gpu_frame = GPUFrame(
                            camera_id=self.camera_id,
                            frame_id=self._frame_id,
                            source_provenance="rtsp",
                            timestamp=timestamp,
                            pts=pts if pts is not None else self._frame_id,
                            dts=pts if pts is not None else self._frame_id,
                            time_base=self._time_base,
                            width=width,
                            height=height,
                            actual_width=width,
                            actual_height=height,
                            pixel_format=PixelFormat.NV12,
                            y_tensor=y_tensor,
                            uv_tensor=uv_tensor,
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
                    
                    # Unlock frame after creating tensor references
                    try:
                        self._decoder.UnlockFrame(0)
                    except Exception as e:
                        logger.debug(f"NVDECDecoder({self.camera_id}): UnlockFrame error: {e}")
                        
        except av.error.FFmpegError as e:
            logger.error(f"NVDECDecoder({self.camera_id}): FFmpeg demux error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"NVDECDecoder({self.camera_id}): Reader loop error: {e}")
            logger.debug(traceback.format_exc())
        finally:
            logger.debug(f"NVDECDecoder({self.camera_id}): Reader loop exited")
            if self._stop_event.is_set():
                self._set_state(DecoderState.STOPPED)
            elif self._first_decode_error_time and (time.time() - self._first_decode_error_time) > 3.0:
                self._set_state(DecoderState.ERROR)
            else:
                self._set_state(DecoderState.STOPPED)

    def is_degraded(self) -> bool:
        """Check if decoder is in degraded state (persistent errors > 3 seconds)."""
        with self._lock:
            if self._first_decode_error_time is not None:
                if (time.time() - self._first_decode_error_time) > 3.0:
                    return True
            return self._state == DecoderState.ERROR

    def is_healthy(self) -> bool:
        """Check if decoder is healthy (not in persistent error state)."""
        return not self.is_degraded()

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
        
        # Cleanup PyNvVideoCodec decoder
        if self._decoder:
            self._decoder = None
        
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

        packet_source = RTSPSource(RTSPSourceConfig(camera_id="test_cam", url=test_file))

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