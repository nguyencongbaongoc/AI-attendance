"""
NVENC Encoder - Hardware-accelerated H.264 encoding from GPUFrame to packets.

Uses PyAV with CUDA input format for zero-copy encoding.
Produces compressed H.264 packets for MediaMTX publishing.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Tuple, Iterator
from enum import Enum
from queue import Queue, Empty, Full

import torch
import av

from pipeline_engine.memory.gpu_frame import GPUFrame
from pipeline_engine.memory.frame_pool import FramePool
from pipeline_engine.config import get_camera_config, get_config

logger = logging.getLogger(__name__)


class EncoderState(str, Enum):
    """Encoder lifecycle states."""
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    READY = "ready"
    ENCODING = "encoding"
    FLUSHING = "flushing"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class NVENCEncoderConfig:
    """Configuration for NVENC encoder."""
    camera_id: str
    # Output
    output_url: str  # RTSP URL for MediaMTX
    # Encoder settings
    codec: str = "h264_nvenc"
    width: int = 3840
    height: int = 2160
    fps: float = 30.0
    bitrate_kbps: int = 8000
    gop_size: int = 30
    preset: str = "p4"
    tune: str = "ll"
    # GPU
    gpu_device: int = 0
    # Queue
    max_queue_size: int = 4
    # Retry/restart
    max_restarts: int = 3
    restart_backoff: float = 2.0
    # Frame pool
    frame_pool: Optional[FramePool] = None


@dataclass
class EncoderMetrics:
    """Encoder metrics."""
    frames_encoded: int = 0
    frames_dropped: int = 0
    packets_output: int = 0
    encoder_restarts: int = 0
    last_encode_time: float = 0.0
    avg_encode_ms: float = 0.0
    state: EncoderState = EncoderState.STOPPED
    last_error: str = ""


class NVENCEncoder:
    """
    NVENC hardware encoder using PyAV.
    
    Pipeline:
        GPUFrame (NV12, CUDA)
            → PyAV VideoFrame.from_dlpack() (zero-copy)
            → h264_nvenc (GPU)
            → H.264 packets (Annex-B bitstream)
    
    Key principle: No CPU frame staging at any point.
    """
    
    def __init__(self, config: NVENCEncoderConfig, frame_pool: Optional[FramePool] = None):
        self.config = config
        self.camera_id = config.camera_id
        self._frame_pool = frame_pool
        
        self._state = EncoderState.STOPPED
        self._metrics = EncoderMetrics()
        
        # PyAV objects
        self._container = None
        self._stream = None
        
        # Threading
        self._stop_event = threading.Event()
        self._encode_thread: Optional[threading.Thread] = None
        self._finalized = False
        self._frame_queue: Queue = Queue(maxsize=config.max_queue_size)
        
        # Stats
        self._encode_times: List[float] = []
        
        self._lock = threading.RLock()
        self._session_id = f"ENC_{self.camera_id}"
        self._generation = 0
    
    @property
    def state(self) -> EncoderState:
        return self._state
    
    @property
    def metrics(self) -> EncoderMetrics:
        with self._lock:
            return self._metrics
    
    def _set_state(self, state: EncoderState) -> None:
        with self._lock:
            old_state = self._state
            self._state = state
            self._metrics.state = state
            if old_state != state:
                logger.info(f"NVENCEncoder({self.camera_id}): state {old_state.value} → {state.value}")
    
    def start(self) -> bool:
        """Start the encoder."""
        with self._lock:
            if self._state in (EncoderState.READY, EncoderState.ENCODING):
                logger.warning(f"NVENCEncoder({self.camera_id}): already started")
                return True
            
            self._set_state(EncoderState.INITIALIZING)
            
            try:
                # Initialize CUDA context in this thread
                torch.cuda.set_device(self.config.gpu_device)
                _ = torch.zeros(1, device=f'cuda:{self.config.gpu_device}')
                
                self._init_pyav_encoder()
                
                self._stop_event.clear()
                self._metrics.frames_encoded = 0
                self._metrics.frames_dropped = 0
                self._metrics.encoder_restarts = 0
                
                self._encode_thread = threading.Thread(
                    target=self._encode_loop,
                    name=f"nvenc-encode-{self.camera_id}",
                    daemon=True,
                )
                self._encode_thread.start()
                
                self._finalized = False
                self._set_state(EncoderState.ENCODING)
                
                logger.info(f"NVENCEncoder({self.camera_id}): started (target={self.config.output_url})")
                return True
                
            except Exception as e:
                self._metrics.last_error = f"Encoder init failed: {e}"
                logger.error(f"NVENCEncoder({self.camera_id}): {self._metrics.last_error}")
                self._set_state(EncoderState.ERROR)
                return False
    
    def _init_pyav_encoder(self) -> None:
        """Initialize PyAV container and NVENC stream."""
        from fractions import Fraction
        
        # Determine format based on output URL
        url = self.config.output_url
        is_rtsp = url.lower().startswith('rtsp://')
        is_file = not is_rtsp
        
        if is_file:
            format_name = 'mp4'
            options = {}
        else:
            format_name = 'rtsp'
            options = {'rtsp_transport': 'tcp'}
        
        # Open output
        self._container = av.open(
            self.config.output_url,
            mode='w',
            format=format_name,
            options=options,
        )
        
        # Add H.264 NVENC stream with all parameters at once
        # Use Fraction for time_base - handle float fps
        fps = self.config.fps
        if isinstance(fps, float):
            # Convert float fps to rational (e.g., 30.0 -> 30/1, 29.97 -> 30000/1001)
            if abs(fps - 30.0) < 0.1:
                rate = Fraction(30, 1)
                time_base = Fraction(1, 30)
            elif abs(fps - 29.97) < 0.1:
                rate = Fraction(30000, 1001)
                time_base = Fraction(1001, 30000)
            elif abs(fps - 25.0) < 0.1:
                rate = Fraction(25, 1)
                time_base = Fraction(1, 25)
            elif abs(fps - 24.0) < 0.1:
                rate = Fraction(24, 1)
                time_base = Fraction(1, 24)
            elif abs(fps - 60.0) < 0.1:
                rate = Fraction(60, 1)
                time_base = Fraction(1, 60)
            else:
                rate = Fraction(int(fps * 1000), 1000)
                time_base = Fraction(1000, int(fps * 1000))
        else:
            rate = Fraction(int(fps * 1000), 1000)
            time_base = Fraction(1, int(fps))
        
        # Configure stream with all parameters at creation time
        self._stream = self._container.add_stream(
            'h264_nvenc',
            rate=rate,
            width=self.config.width,
            height=self.config.height,
            pix_fmt='nv12',
            bit_rate=self.config.bitrate_kbps * 1000,
            gop_size=self.config.gop_size,
            time_base=time_base,
        )
        
        # Set encoder options BEFORE the stream is used
        ctx = self._stream.codec_context
        
        # Set NVENC-specific options - all values must be strings
        codec_options = {
            'preset': str(self.config.preset),
            'tune': str(self.config.tune),
            'gpu': str(self.config.gpu_device),
            'rc': 'cbr',
            'bit_rate': str(self.config.bitrate_kbps * 1000),
            'gop_size': str(self.config.gop_size),
        }
        
        ctx.options = codec_options
        
        # CRITICAL: Explicitly open the codec context with our options NOW
        # This ensures the NVENC encoder is initialized with our options before any frame is encoded
        try:
            ctx.open()
            logger.info(f"NVENCEncoder({self.camera_id}): Codec context opened successfully with options")
        except Exception as e:
            logger.error(f"NVENCEncoder({self.camera_id}): Failed to open codec context: {e}")
            raise
        
        logger.info(
            f"NVENCEncoder({self.camera_id}): NVENC stream configured "
            f"(pix_fmt=nv12, {self.config.width}x{self.config.height}@{self.config.fps}fps, "
            f"bitrate={self.config.bitrate_kbps}kbps, gpu={self.config.gpu_device})"
        )
    
    def submit_frame(self, gpu_frame: GPUFrame) -> bool:
        """
        Submit GPUFrame for encoding.
        
        Args:
            gpu_frame: GPUFrame with NV12 CUDA tensors
            
        Returns:
            True if accepted, False if queue full (frame dropped)
        """
        if self._state != EncoderState.ENCODING or self._stop_event.is_set():
            return False
        
        try:
            # Add reference to prevent premature GC
            gpu_frame.add_ref()
            self._frame_queue.put_nowait(gpu_frame)
            return True
        except Full:
            # Drop oldest, insert newest (latest-wins)
            try:
                old_frame = self._frame_queue.get_nowait()
                old_frame.release()
                if self._frame_pool:
                    self._frame_pool.return_to_pool(old_frame)
            except Empty:
                pass
            try:
                gpu_frame.add_ref()
                self._frame_queue.put_nowait(gpu_frame)
                self._metrics.frames_dropped += 1
                return True
            except Full:
                gpu_frame.release()
                if self._frame_pool:
                    self._frame_pool.return_to_pool(gpu_frame)
                self._metrics.frames_dropped += 1
                return False
    
    def _encode_loop(self) -> None:
        """Main encoding loop."""
        backoff = self.config.restart_backoff
        
        while not self._stop_event.is_set():
            try:
                # Get frame from queue
                try:
                    gpu_frame = self._frame_queue.get(timeout=0.5)
                except Empty:
                    continue
                
                # Verify frame
                if gpu_frame is None or gpu_frame.released:
                    if gpu_frame:
                        gpu_frame.release()
                        if self._frame_pool:
                            self._frame_pool.return_to_pool(gpu_frame)
                    continue
                
                # Verify NV12 format
                if not gpu_frame.validate():
                    logger.warning(f"NVENCEncoder({self.camera_id}): Invalid GPUFrame submitted")
                    gpu_frame.release()
                    if self._frame_pool:
                        self._frame_pool.return_to_pool(gpu_frame)
                    continue
                
                # Re-initialize encoder if needed
                if self._container is None or self._stream is None:
                    try:
                        self._init_pyav_encoder()
                    except Exception as e:
                        logger.error(f"NVENCEncoder({self.camera_id}): Encoder re-init failed: {e}")
                        gpu_frame.release()
                        if self._frame_pool:
                            self._frame_pool.return_to_pool(gpu_frame)
                        continue
                
                # Create PyAV CUDA VideoFrame from DLPack capsules
                try:
                    # Get DLPack capsules from tensors
                    y_dlpack = gpu_frame.y_tensor.__dlpack__()
                    uv_dlpack = gpu_frame.uv_tensor.__dlpack__()
                    
                    # Create PyAV CUDA VideoFrame (zero-copy - shares GPU memory)
                    av_frame = av.VideoFrame.from_dlpack(
                        [y_dlpack, uv_dlpack],
                        format='nv12',
                        width=self.config.width,
                        height=self.config.height,
                        device_id=self.config.gpu_device,
                        current_ctx=True,
                    )
                    
                    # Verify CUDA frame - if it's CUDA format, reformat to NV12
                    # NVENC expects NV12 format, not CUDA format
                    if av_frame.format.name == 'cuda':
                        # Reformat to NV12 - this converts CUDA frame to NV12 on GPU
                        av_frame = av_frame.reformat(
                            width=self.config.width,
                            height=self.config.height,
                            format='nv12'
                        )
                    
                    # Verify frame format
                    if av_frame.format.name != 'nv12':
                        logger.warning(
                            f"NVENCEncoder({self.camera_id}): Frame format is {av_frame.format.name}, expected 'nv12'"
                        )
                        gpu_frame.release()
                        if self._frame_pool:
                            self._frame_pool.return_to_pool(gpu_frame)
                        continue
                    
                    # Encode frame
                    encode_start = time.perf_counter()
                    packets = list(self._stream.encode(av_frame))
                    
                    # Mux packets
                    for packet in packets:
                        try:
                            self._container.mux(packet)
                            self._metrics.packets_output += 1
                        except Exception as mux_exc:
                            logger.error(f"NVENCEncoder({self.camera_id}): Mux error: {mux_exc}")
                    
                    encode_ms = (time.perf_counter() - encode_start) * 1000
                    self._encode_times.append(encode_ms)
                    if len(self._encode_times) > 100:
                        self._encode_times.pop(0)
                    
                    self._metrics.frames_encoded += 1
                    self._metrics.last_encode_time = time.time()
                    self._metrics.avg_encode_ms = sum(self._encode_times) / len(self._encode_times)
                    
                    # Release GPUFrame reference
                    gpu_frame.release()
                    if self._frame_pool:
                        self._frame_pool.return_to_pool(gpu_frame)
                    
                except Exception as e:
                    logger.error(f"NVENCEncoder({self.camera_id}): Frame encoding failed: {e}")
                    gpu_frame.release()
                    if self._frame_pool:
                        self._frame_pool.return_to_pool(gpu_frame)
                    continue
                
            except av.error.OSError as e:
                # Handle FFmpeg errors (including potential OSError -129)
                errno = getattr(e, 'errno', None)
                strerror = getattr(e, 'strerror', None)
                message = str(e)
                
                logger.error(
                    f"NVENCEncoder({self.camera_id}): PyAV encode error: "
                    f"errno={errno}, strerror={strerror!r}, message={message!r}"
                )
                self._metrics.last_error = f"PyAV encode error: {message} (errno={errno})"
                
                # Attempt restart with bounded retries
                self._attempt_restart()
                
            except Exception as e:
                logger.error(f"NVENCEncoder({self.camera_id}): Encode loop error: {e}")
                self._metrics.last_error = f"Encode loop error: {e}"
                self._attempt_restart()
        
        # Final flush
        self._flush_final()
    
    def _flush_final(self) -> None:
        """Flush remaining frames and finalize encoder."""
        if not self._finalized and self._stream and self._container:
            try:
                for packet in self._stream.encode(None):
                    self._container.mux(packet)
                    self._metrics.packets_output += 1
                self._finalized = True
                logger.info(f"NVENCEncoder({self.camera_id}): Flush completed")
            except Exception as e:
                logger.debug(f"NVENCEncoder({self.camera_id}): Flush error: {e}")
                self._finalized = True
    
    def _attempt_restart(self) -> None:
        """Attempt encoder restart with bounded retries."""
        if self._metrics.encoder_restarts >= self.config.max_restarts:
            logger.error(
                f"NVENCEncoder({self.camera_id}): Giving up after "
                f"{self.config.max_restarts} restarts"
            )
            self._stop_event.set()
            return
        
        self._metrics.encoder_restarts += 1
        
        logger.warning(
            f"NVENCEncoder({self.camera_id}): Restart attempt "
            f"{self._metrics.encoder_restarts}/{self.config.max_restarts}"
        )
        
        # Close current container
        self._close_internal()
        
        # Clear queue
        while True:
            try:
                frame = self._frame_queue.get_nowait()
                if frame is not None:
                    frame.release()
                    if self._frame_pool:
                        self._frame_pool.return_to_pool(frame)
            except Empty:
                break
        
        # Wait before retry (exponential backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 30.0)
        
        # Try to restart
        try:
            self._init_pyav_encoder()
            self._finalized = False
            logger.info(f"NVENCEncoder({self.camera_id}): Restart successful")
        except Exception as e:
            logger.error(f"NVENCEncoder({self.camera_id}): Restart failed: {e}")
    
    def _close_internal(self) -> None:
        """Internal close (without state change)."""
        if self._container:
            try:
                self._container.close()
            except Exception:
                pass
            finally:
                self._container = None
                self._stream = None
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop encoder gracefully."""
        if self._state == EncoderState.STOPPED:
            return
        
        logger.info(f"NVENCEncoder({self.camera_id}): Stopping")
        
        self._set_state(EncoderState.FLUSHING)
        self._stop_event.set()
        
        # Flush
        self._flush_final()
        
        # Wait for thread
        if self._encode_thread and self._encode_thread.is_alive():
            self._encode_thread.join(timeout=timeout)
        
        # Close
        self._close_internal()
        
        # Clear queue
        while True:
            try:
                frame = self._frame_queue.get_nowait()
                if frame is not None:
                    frame.release()
                    if self._frame_pool:
                        self._frame_pool.return_to_pool(frame)
            except Empty:
                break
        
        self._set_state(EncoderState.STOPPED)
        logger.info(f"NVENCEncoder({self.camera_id}): Stopped")
    
    def get_queue_depth(self) -> int:
        return self._frame_queue.qsize()
    
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "started": self._state == EncoderState.ENCODING,
                "frames_encoded": self._metrics.frames_encoded,
                "frames_dropped": self._metrics.frames_dropped,
                "packets_output": self._metrics.packets_output,
                "encoder_restarts": self._metrics.encoder_restarts,
                "avg_encode_ms": self._metrics.avg_encode_ms,
                "state": self._state.value,
                "last_error": self._metrics.last_error,
                "queue_depth": self._frame_queue.qsize(),
                "width": self.config.width,
                "height": self.config.height,
                "target_fps": self.config.fps,
                "output_url": self.config.output_url,
                "gpu_device": self.config.gpu_device,
            }
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def create_nvenc_encoder(
    camera_id: str,
    frame_pool: Optional[FramePool] = None,
    config: Optional[Dict[str, Any]] = None,
) -> NVENCEncoder:
    """Factory function to create NVENC encoder from pipeline config."""
    if config is None:
        config = get_camera_config(get_config(), camera_id)
    
    encode_config = config.get("encode", {})
    output_config = config.get("output", {})
    
    # Build output URL
    mediamtx_host = "localhost"
    mediamtx_port = 8554
    output_path = output_config.get("path", f"live/{camera_id}-ai")
    output_url = f"rtsp://{mediamtx_host}:{mediamtx_port}/{output_path}"
    
    encoder_config = NVENCEncoderConfig(
        camera_id=camera_id,
        output_url=output_url,
        codec=encode_config.get("codec", "h264_nvenc"),
        width=encode_config.get("width", config.get("expected", {}).get("width", 3840)),
        height=encode_config.get("height", config.get("expected", {}).get("height", 2160)),
        fps=encode_config.get("fps", config.get("expected", {}).get("fps", 30.0)),
        bitrate_kbps=encode_config.get("bitrate_kbps", 8000),
        gop_size=encode_config.get("gop_size", 30),
        preset=encode_config.get("preset", "p4"),
        tune=encode_config.get("tune", "ll"),
        gpu_device=encode_config.get("gpu_device", config.get("decode", {}).get("gpu_device", 0)),
    )
    
    return NVENCEncoder(encoder_config, frame_pool)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    encoder = create_nvenc_encoder("test_cam")
    
    if encoder.start():
        print("NVENC encoder started!")
        print(f"Stats: {encoder.get_metrics()}")
        encoder.stop()
        print("NVENC encoder stopped!")
    else:
        print("NVENC encoder start failed (expected without running MediaMTX)")