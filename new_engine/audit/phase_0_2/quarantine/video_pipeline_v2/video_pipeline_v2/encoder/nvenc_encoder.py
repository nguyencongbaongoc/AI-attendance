"""
NVENC Encoder - V2 GPU-first video pipeline.

Direct NVENC encoding from CUDA-resident GPUFrame (NV12) to H.264 packets.
Uses PyAV with CUDA input format for zero-copy encoding.
Produces compressed H.264 packets for external MediaMTX publisher.
"""

from __future__ import annotations

import logging
import threading
import queue
import time
import traceback
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Tuple, Iterator
from enum import Enum

import torch

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
    gop_size: int = 30  # 1 second at 30fps
    preset: str = "p4"
    tune: str = "ll"
    # GPU
    gpu_device: int = 0
    # Queue
    max_queue_size: int = 4
    # Retry/restart
    max_restarts: int = 3
    restart_backoff: float = 2.0


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
    
    def __init__(self, config: NVENCEncoderConfig):
        self.config = config
        self.camera_id = config.camera_id
        
        self._state = EncoderState.STOPPED
        self._metrics = EncoderMetrics()
        
        # PyAV objects
        self._container = None
        self._stream = None
        
        # Threading
        self._stop_event = threading.Event()
        self._encode_thread: Optional[threading.Thread] = None
        self._finalized = False
        self._frame_queue: "queue.Queue[Any]" = queue.Queue(maxsize=config.max_queue_size)
        
        # Stats
        self._encode_times: List[float] = []
        
        self._lock = threading.RLock()
        self._session_id = f"ENC_{self.camera_id}"
        self._generation = 0
    
    @property
    def state(self) -> EncoderState:
        return self._state
    
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
        import av
        from fractions import Fraction
        
        # Open output for RTSP
        self._container = av.open(
            self.config.output_url,
            mode='w',
            format='rtsp',
            options={
                'rtsp_transport': 'tcp',
            },
        )
        
        # Add H.264 NVENC stream
        rate = Fraction(int(self.config.fps * 1000), 1000)
        self._stream = self._container.add_stream('h264_nvenc', rate=rate)
        self._stream.width = self.config.width
        self._stream.height = self.config.height
        self._stream.pix_fmt = 'cuda'  # CUDA hardware input
        self._stream.bit_rate = self.config.bitrate_kbps * 1000
        self._stream.gop_size = self.config.gop_size
        
        # Encoder options
        preset = self.config.preset
        tune = self.config.tune
        
        # Set NVENC-specific options
        codec_options = {
            'preset': preset,
            'tune': tune,
            'gpu': str(self.config.gpu_device),
            'rc': 'cbr',
        }
        
        # Note: For newer FFmpeg, options are set through the codec context
        # We set them on the stream options
        self._stream.options = codec_options
        
        logger.info(
            f"NVENCEncoder({self.camera_id}): NVENC stream configured "
            f"(pix_fmt=cuda, {self.config.width}x{self.config.height}@{self.config.fps}fps, "
            f"bitrate={self.config.bitrate_kbps}kbps, gpu={self.config.gpu_device})"
        )
    
    def submit_frame(self, gpu_frame: "GPUFrame") -> bool:
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
        except queue.Full:
            # Drop oldest, insert newest (latest-wins)
            try:
                old_frame = self._frame_queue.get_nowait()
                old_frame.release()
            except queue.Empty:
                pass
            try:
                gpu_frame.add_ref()
                self._frame_queue.put_nowait(gpu_frame)
                self._metrics.frames_dropped += 1
                return True
            except queue.Full:
                gpu_frame.release()
                self._metrics.frames_dropped += 1
                return False
    
    def submit_nv12_planes(
        self,
        y_tensor: torch.Tensor,
        uv_tensor: torch.Tensor,
        camera_id: str,
        frame_id: int,
        timestamp: float,
        pts: int,
    ) -> bool:
        """
        Submit NV12 planes directly (alternative interface).
        Creates GPUFrame and submits.
        """
        from video_pipeline_v2.core.gpu_frame import GPUFrame
        
        gpu_frame = GPUFrame.from_pyav_nvdec(
            y_tensor=y_tensor,
            uv_tensor=uv_tensor,
            camera_id=camera_id,
            frame_id=frame_id,
            timestamp=timestamp,
            pts=pts,
            width=y_tensor.shape[1],
            height=y_tensor.shape[0],
        )
        return self.submit_frame(gpu_frame)
    
    def _encode_loop(self) -> None:
        """Main encoding loop."""
        import av
        import torch
        
        backoff = self.config.restart_backoff
        restarts = 0
        
        while not self._stop_event.is_set():
            try:
                # Get frame from queue
                try:
                    gpu_frame = self._frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Verify frame
                if gpu_frame is None or gpu_frame.released:
                    if gpu_frame:
                        gpu_frame.release()
                    continue
                
                # Verify NV12 format
                if not gpu_frame.validate():
                    logger.warning(f"NVENCEncoder({self.camera_id}): Invalid GPUFrame submitted")
                    gpu_frame.release()
                    continue
                
                # Re-initialize encoder if needed
                if self._container is None or self._stream is None:
                    try:
                        self._init_pyav_encoder()
                    except Exception as e:
                        logger.error(f"NVENCEncoder({self.camera_id}): Encoder re-init failed: {e}")
                        gpu_frame.release()
                        continue
                
                # Create PyAV CUDA VideoFrame from DLPack capsules
                y_ptr, uv_ptr = gpu_frame.get_gpu_pointers()
                
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
                
                # Verify CUDA frame
                if av_frame.format.name != 'cuda':
                    logger.warning(
                        f"NVENCEncoder({self.camera_id}): Frame format is {av_frame.format.name}, expected 'cuda'"
                    )
                    gpu_frame.release()
                    continue
                
                # Encode frame
                encode_start = time.perf_counter()
                packets = []
                
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
                
            except av.error.OSError as e:
                # Handle FFmpeg errors (including potential OSError -129)
                # Log full diagnostic info
                errno = getattr(e, 'errno', None)
                strerror = getattr(e, 'strerror', None)
                message = str(e)
                
                logger.error(
                    f"NVENCEncoder({self.camera_id}): PyAV encode error: "
                    f"errno={errno}, strerror={strerror!r}, message={message!r}"
                )
                self._metrics.last_error = f"PyAV encode error: {message} (errno={errno})"
                
                # Capture exit chronology for diagnostic
                # This is important: OSError -129 is a symptom, not root cause
                # The real error is the earlier process/resource failure that caused it
                
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
        
        restarts = self._metrics.encoder_restarts + 1
        self._metrics.encoder_restarts = restarts
        
        logger.warning(
            f"NVENCEncoder({self.camera_id}): Restart attempt {restarts}/{self.config.max_restarts}"
        )
        
        # Close current container
        self._close_internal()
        
        # Clear queue
        while True:
            try:
                frame = self._frame_queue.get_nowait()
                if frame is not None:
                    frame.release()
            except queue.Empty:
                break
        
        # Wait before retry (exponential backoff)
        time.sleep(self.config.restart_backoff)
        
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
            except queue.Empty:
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
    output_url: str,
    width: int = 3840,
    height: int = 2160,
    fps: float = 30.0,
    bitrate_kbps: int = 8000,
    gpu_device: int = 0,
) -> NVENCEncoder:
    """Factory function to create NVENC encoder."""
    config = NVENCEncoderConfig(
        camera_id=camera_id,
        output_url=output_url,
        width=width,
        height=height,
        fps=fps,
        bitrate_kbps=bitrate_kbps,
        gpu_device=gpu_device,
    )
    return NVENCEncoder(config)


if __name__ == "__main__":
    # Test basic initialization
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    # Note: Full test requires MediaMTX running
    encoder = create_nvenc_encoder("test_cam", "rtsp://localhost:8554/stream")
    
    if encoder.start():
        print("NVENC encoder started!")
        print(f"Stats: {encoder.get_metrics()}")
        encoder.stop()
        print("NVENC encoder stopped!")
    else:
        print("NVENC encoder start failed (expected without running MediaMTX)")