"""
Phase H.10-C.2 — PyAV NVENC Encoder for CUDA Frames.

Direct PyAV encoding from CUDA-resident frames (NV12 planes) to H.264 via NVENC.
Eliminates the CPU BGR24/NV12 pipe boundary entirely.

Architecture:
    GPU AI Pipeline
        │
        ├── GPU Annotation (rectangles, lines, text)
        │
        ▼
    4K CUDA NV12 planes (Y + UV)
        │
        ▼
    PyAV VideoFrame.from_dlpack() → CUDA AVFrame (format='cuda')
        │
        ▼
    h264_nvenc encoder (GPU 0)
        │
        ▼
    H.264 bitstream → MediaMTX → HLS
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from app.streaming.instrumentation_47b2 import emit_event

logger = logging.getLogger(__name__)


@dataclass
class PyAVNVENCEncoderConfig:
    """Configuration for PyAV NVENC encoder."""
    camera_id: str
    rtsp_url: str
    width: int = 3840
    height: int = 2160
    fps: float = 15.0
    video_bitrate_kbps: int = 2500
    gop_seconds: float = 1.0
    max_restarts: int = 5
    restart_backoff_seconds: float = 2.0
    nvenc_gpu_device: int = 0
    nvenc_preset: str = "p1"
    nvenc_tune: str = "ll"
    nvenc_rc: str = "cbr"
    nvenc_hw_frames: int = 32


@dataclass
class PyAVNVENCEncoderMetrics:
    """Metrics for PyAV NVENC encoder."""
    frames_encoded: int = 0
    frames_dropped: int = 0
    encoder_restarts: int = 0
    last_encode_time: float = 0.0
    started: bool = False
    last_error: str = ""


class PyAVNVENCEncoder:
    """
    PyAV-based NVENC encoder for CUDA-resident frames.
    
    Accepts NV12 planes (Y + UV) as DLPack capsules, converts to PyAV
    CUDA VideoFrames via VideoFrame.from_dlpack(), and encodes directly
    using h264_nvenc on GPU.
    
    Zero-copy path: No full-frame CPU transfer at any point.
    """
    
    def __init__(
        self,
        config: PyAVNVENCEncoderConfig,
        time_func: Any = time.time,
    ):
        self.config = config
        self.camera_id = config.camera_id
        self._time = time_func
        
        self._container = None
        self._stream = None
        self._stop_event = threading.Event()
        self._encode_thread: Optional[threading.Thread] = None
        self._finalized = False  # 46D: ensure flush/finalize runs exactly once.
        self._frame_queue: "queue.Queue[Tuple[Any, Any]]" = queue.Queue(maxsize=2)  # (y_plane_dlpack, uv_plane_dlpack)
        self._metrics = PyAVNVENCEncoderMetrics()
        self._lock = threading.Lock()
        self._error: Optional[Exception] = None

        # H.10-D.1: Explicit ownership tracking for zero-copy CUDA surfaces
        # Prevents reuse of surfaces still owned by encoder/NVENC.
        from app.vision.surface_ownership_pool import CUDAFrameOwnershipPool, SurfaceOwnershipState
        
        def _telemetry_callback(surface_id: str, frame_ref: str, state: SurfaceOwnershipState, ref_count: int, generation: int) -> None:
            """Telemetry callback for surface ownership state transitions."""
            # We can't emit directly here because we need camera_id and other context
            # The encoder will emit events at the appropriate points
            pass
        
        self._ownership_pool: CUDAFrameOwnershipPool = CUDAFrameOwnershipPool(telemetry_callback=_telemetry_callback)
        self._ownership_states: dict = {}
        self._generation: int = 0  # encoder generation counter
        # PHASE 50: CUDA event tracking per submitted frame
        self._pending_cuda_events: dict = {}
        self._session_id = f"S{self._generation:05d}"
        self._current_generation: int = 0
        # 47B.2: Session creation diagnostic
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="SESSION",
            meta={"session_id": self._session_id, "generation": self._generation},
        )
    
    def start(self) -> bool:
        """Start the encoder thread and initialize PyAV NVENC."""
        with self._lock:
            if self._metrics.started:
                logger.warning(f"PyAVNVENCEncoder({self.camera_id}): already started")
                return True
            
            logger.info(f"PyAVNVENCEncoder({self.camera_id}): starting encoder")
            
            try:
                self._init_pyav_encoder()
            except Exception as e:
                self._metrics.last_error = f"PyAV encoder init failed: {e}"
                logger.error(f"PyAVNVENCEncoder({self.camera_id}): {self._metrics.last_error}")
                return False
            
            self._stop_event.clear()
            self._encode_thread = threading.Thread(
                target=self._encode_loop,
                name=f"pyav-nvenc-{self.camera_id}",
                daemon=True,
            )
            self._encode_thread.start()
            
            self._metrics.started = True
            logger.info(
                f"PyAVNVENCEncoder({self.camera_id}): started "
                f"(target={self.config.rtsp_url}, {self.config.width}x{self.config.height}@{self.config.fps}fps)"
            )
            return True

    def _init_pyav_encoder(self) -> None:
        """Initialize PyAV container and NVENC stream."""
        import av
        from fractions import Fraction

        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="RTSP_CONNECT",
            meta={"level": "APP_LEVEL", "transport": "tcp"},
        )
        # Open output container for RTSP
        self._container = av.open(
            self.config.rtsp_url,
            mode='w',
            format='rtsp',
            options={
                'rtsp_transport': 'tcp',
            },
        )

        # Add H.264 NVENC stream - rate must be a Fraction for PyAV
        self._stream = self._container.add_stream('h264_nvenc', rate=Fraction(int(self.config.fps * 1000), 1000))
        self._stream.width = self.config.width
        self._stream.height = self.config.height
        self._stream.pix_fmt = 'cuda'  # CUDA hardware frames input
        self._stream.bit_rate = self.config.video_bitrate_kbps * 1000
        self._stream.gop_size = max(1, int(round(self.config.fps * self.config.gop_seconds)))
        # keyint_min is not available in newer PyAV versions; use gop_size instead
        self._stream.options = {
            'preset': self.config.nvenc_preset,
            'tune': self.config.nvenc_tune,
            'rc': self.config.nvenc_rc,
            'gpu': str(self.config.nvenc_gpu_device),
        }

        logger.info(
            f"PyAVNVENCEncoder({self.camera_id}): NVENC stream configured "
            f"(pix_fmt=cuda, gpu={self.config.nvenc_gpu_device}, "
            f"preset={self.config.nvenc_preset}, tune={self.config.nvenc_tune})"
        )

    def submit_nv12_planes(
        self,
        y_plane_dlpack,
        uv_plane_dlpack,
    ) -> bool:
        """
        Submit NV12 planes (as DLPack capsules) for encoding.
        
        Args:
            y_plane_dlpack: DLPack capsule for Y plane
            uv_plane_dlpack: DLPack capsule for UV plane
        
        Returns:
            True if accepted, False if queue full (frame dropped)
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False
        
        try:
            self._frame_queue.put_nowait((y_plane_dlpack, uv_plane_dlpack))
            # Queue telemetry: QUEUE_PUSH
            emit_event(
                camera=self.camera_id,
                session_id=self._session_id,
                event="QUEUE_PUSH",
                meta={"queue_size_after_push": self._frame_queue.qsize()},
            )
            return True
        except queue.Full:
            # Latest-wins: drop oldest, insert newest
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            # Queue telemetry: QUEUE_DROP
            emit_event(
                camera=self.camera_id,
                session_id=self._session_id,
                event="QUEUE_DROP",
                meta={"queue_size_before_insert": self._frame_queue.qsize()},
            )
            try:
                self._frame_queue.put_nowait((y_plane_dlpack, uv_plane_dlpack))
                self._metrics.frames_dropped += 1
                return True
            except queue.Full:
                self._metrics.frames_dropped += 1
                return False

    def _encode_loop(self) -> None:
        """Encode loop: pull frames from queue and encode via PyAV NVENC."""
        import av
        import torch

        # Initialize CUDA context in this thread before opening encoder
        # PyTorch lazy-initializes CUDA when first used; without this, 
        # avcodec_open2 fails with EFAULT (Bad address) when opened from worker thread
        _ = torch.zeros(1, device=f'cuda:{self.config.nvenc_gpu_device}')

        backoff = self.config.restart_backoff_seconds
        restarts = 0

        while not self._stop_event.is_set():
            try:
                # Get frame data from queue
                try:
                    y_dlpack, uv_dlpack = self._frame_queue.get(timeout=0.5)
                    # Queue telemetry: QUEUE_POP
                    emit_event(
                        camera=self.camera_id,
                        session_id=self._session_id,
                        event="QUEUE_POP",
                        meta={"queue_size_after_pop": self._frame_queue.qsize()},
                    )
                    emit_event(
                        camera=self.camera_id,
                        session_id=self._session_id,
                        event="FRAME_READY",
                        meta={"queue_size_after_get": self._frame_queue.qsize()},
                    )
                except queue.Empty:
                    continue

                if self._container is None:
                    self._init_pyav_encoder()

                # Create PyAV CUDA VideoFrame from NV12 DLPack planes
                # This is zero-copy: the resulting AVFrame shares GPU memory
                frame = av.VideoFrame.from_dlpack(
                    [y_dlpack, uv_dlpack],
                    format='nv12',
                    width=self.config.width,
                    height=self.config.height,
                    device_id=self.config.nvenc_gpu_device,
                    current_ctx=True,
                )

                # Verify frame is CUDA hardware frame
                if frame.format.name != 'cuda':
                    logger.warning(
                        f"PyAVNVENCEncoder({self.camera_id}): Frame format is {frame.format.name}, "
                        f"expected 'cuda'. This may indicate a problem."
                    )

                # H.10-D.1: Track surface ownership before encoding.
                # The DLPack capsules share memory with the underlying CUDA
                # surface. We must establish SUBMITTED -> IN_FLIGHT before
                # encode() and only release after a safe boundary.
                # H.10-D.1 / PHASE 54: Use CUDA memory identity, not Python object identity.
                # data_ptr() identifies the actual GPU allocation shared by DLPack.
                # Note: y_dlpack and uv_dlpack may be capsule objects; we attempt to
                # extract underlying tensor pointers where possible. If they are raw
                # DLPack capsules, we fall back to a composite key using the DLPack
                # device id + shape metadata, but prefer data_ptr.
                def _dlpack_key(dlpack_obj, label: str) -> str:
                    # Try to extract from a PyTorch tensor backing
                    if hasattr(dlpack_obj, 'data_ptr'):
                        return f"{label}:{dlpack_obj.data_ptr()}"
                    # For DLPack capsules, try from_dlpack conversion for identity
                    import torch.utils.dlpack
                    try:
                        tensor = torch.utils.dlpack.from_dlpack(dlpack_obj)
                        return f"{label}:{tensor.data_ptr()}:{str(tensor.device)}"
                    except Exception:
                        # Fallback: capsule identity (less reliable across GC)
                        return f"{label}:{id(dlpack_obj)}"

                y_key = _dlpack_key(y_dlpack, "Y")
                uv_key = _dlpack_key(uv_dlpack, "UV")
                surface_key = f"{self.camera_id}:{y_key}:{uv_key}"
                # Extract data_ptr for telemetry
                data_ptr = 0
                if hasattr(y_dlpack, 'data_ptr'):
                    data_ptr = y_dlpack.data_ptr()
                elif hasattr(y_dlpack, '__dlpack__'):
                    import torch.utils.dlpack
                    try:
                        tensor = torch.utils.dlpack.from_dlpack(y_dlpack)
                        data_ptr = tensor.data_ptr()
                    except Exception:
                        pass
                self._ownership_pool.submit_encoder(surface_key, generation=self._current_generation)
                if surface_key not in self._ownership_states:
                    self._ownership_states[surface_key] = {
                        "generation": self._current_generation,
                        "submitted": True,
                    }

                # 47B.2 DIAGNOSTIC: ENCODE_BEGIN (with surface correlation)
                emit_event(
                    camera=self.camera_id,
                    session_id=self._session_id,
                    event="ENCODE_BEGIN",
                    meta={"generation": self._current_generation, "session": self._session_id},
                    surface_key=surface_key,
                    data_ptr=data_ptr,
                    generation=self._current_generation,
                    ownership_state="in_flight",
                    ref_count=0,
                    frame_id=self._session_id,
                )
                # PHASE 50: Record CUDA event after encode submission
                cuda_event = torch.cuda.Event(enable_timing=True) if torch.cuda.is_available() else None
                # Encode frame
                packets = []
                try:
                    packets = list(self._stream.encode(frame))
                    if cuda_event is not None:
                        cuda_event.record()
                except Exception as exc:
                    # ENCODE_ERROR with surface correlation
                    emit_event(
                        camera=self.camera_id,
                        session_id=self._session_id,
                        event="ENCODE_ERROR",
                        meta={"exception": type(exc).__name__, "message": str(exc)},
                        surface_key=surface_key,
                        data_ptr=data_ptr,
                        generation=self._current_generation,
                        ownership_state="encode_error",
                        ref_count=0,
                        frame_id=self._session_id,
                    )
                    raise
                for packet in packets:
                    # PACKET_READY with surface correlation
                    emit_event(
                        camera=self.camera_id,
                        session_id=self._session_id,
                        event="PACKET_READY",
                        meta={
                            "packet_size": packet.size if hasattr(packet, 'size') else None,
                            "pts": packet.pts if hasattr(packet, 'pts') else None,
                            "dts": packet.dts if hasattr(packet, 'dts') else None,
                        },
                        surface_key=surface_key,
                        data_ptr=data_ptr,
                        generation=self._current_generation,
                        ownership_state="nvenc_consuming",
                        ref_count=0,
                        frame_id=self._session_id,
                    )
                    # MUX_BEGIN with surface correlation
                    emit_event(
                        camera=self.camera_id,
                        session_id=self._session_id,
                        event="MUX_BEGIN",
                        surface_key=surface_key,
                        data_ptr=data_ptr,
                        generation=self._current_generation,
                        ownership_state="nvenc_consuming",
                        ref_count=0,
                        frame_id=self._session_id,
                    )
                    try:
                        self._container.mux(packet)
                        # MUX_SUCCESS with surface correlation
                        emit_event(
                            camera=self.camera_id,
                            session_id=self._session_id,
                            event="MUX_SUCCESS",
                            surface_key=surface_key,
                            data_ptr=data_ptr,
                            generation=self._current_generation,
                            ownership_state="nvenc_safe_to_release",
                            ref_count=0,
                            frame_id=self._session_id,
                        )
                    except Exception as mux_exc:
                        # MUX_ERROR with surface correlation
                        emit_event(
                            camera=self.camera_id,
                            session_id=self._session_id,
                            event="MUX_ERROR",
                            meta={
                                "exception": type(mux_exc).__name__,
                                "message": str(mux_exc),
                                "errno": getattr(mux_exc, 'errno', None),
                            },
                            surface_key=surface_key,
                            data_ptr=data_ptr,
                            generation=self._current_generation,
                            ownership_state="nvenc_safe_to_release",
                            ref_count=0,
                            frame_id=self._session_id,
                        )
                        raise
                # ENCODE_SUCCESS with surface correlation
                emit_event(
                    camera=self.camera_id,
                    session_id=self._session_id,
                    event="ENCODE_SUCCESS",
                    meta={"packets": len(packets)},
                    surface_key=surface_key,
                    data_ptr=data_ptr,
                    generation=self._current_generation,
                    ownership_state="releasable",
                    ref_count=0,
                    frame_id=self._session_id,
                )

                # PHASE 54 — CONSERVATIVE OWNERSHIP / EVENT HANDLING.
                # The installed PyAV 18.1.0 / FFmpeg 9.0 / CUDA 12.6 path does
                # NOT expose NVENC async/sync mode or an input-resource fence.
                # A CUDA event on the current stream (recorded after encode())
                # does NOT prove NVENC has finished consuming the input resource,
                # because NVENC work may operate on a different stream or through
                # WDDM scheduling not ordered into the event's stream.
                # Therefore: we retain the event as DEFENSIVE MONITORING ONLY,
                # not as proof of safe release. The event is bounded and cleaned
                # on restart; it does not trigger premature release.
                if cuda_event is not None:
                    # Store for bounded tracking and defensive sync at restart.
                    # This is NOT a safe-release trigger for normal frames.
                    self._pending_cuda_events[surface_key] = cuda_event
                self._metrics.frames_encoded += 1
                self._metrics.last_encode_time = self._time()

                # H.10-D.1 / PHASE 54: Conservative release contract.
                # The ONLY verified safe release for this installed stack is
                # flush (encode(None)), which forces FFmpeg/NVENC to drain its
                # internal pipeline synchronously. Non-flush frames remain
                # IN_FLIGHT; we do NOT transition to AVAILABLE or RELEASABLE
                # here because the safe boundary for non-flush encode() is NOT
                # fully provable through installed APIs (see PHASE 54 evidence).
                # This avoids premature reuse at the cost of surface retention
                # until flush/restart completes.
                state = self._ownership_pool.get_state(surface_key)
                if state is not None:
                    # Intentionally keep IN_FLIGHT for non-flush frames.
                    # Only flush/restart will transition to RELEASABLE.
                    pass

            except av.error.OSError as e:
                self._metrics.last_error = f"PyAV encode error: {e}"
                logger.error(f"PyAVNVENCEncoder({self.camera_id}): {self._metrics.last_error}")
                # Attempt restart
                self._attempt_restart()
            except Exception as e:
                self._metrics.last_error = f"Encode loop error: {e}"
                logger.error(f"PyAVNVENCEncoder({self.camera_id}): {self._metrics.last_error}")
                self._attempt_restart()
    
    def _attempt_restart(self) -> None:
        """Attempt to restart the encoder."""
        if self._metrics.encoder_restarts >= self.config.max_restarts:
            logger.error(
                f"PyAVNVENCEncoder({self.camera_id}): giving up after "
                f"{self.config.max_restarts} restarts"
            )
            self._stop_event.set()
            return
        
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="ENCODER_RESTART",
            meta={
                "restarts": self._metrics.encoder_restarts,
                "generation_before": self._current_generation,
            },
            surface_key="",
            data_ptr=0,
            generation=self._current_generation,
            ownership_state="restart",
            ref_count=0,
            frame_id=self._session_id,
        )
        self._metrics.encoder_restarts += 1
        logger.warning(
            f"PyAVNVENCEncoder({self.camera_id}): restarting encoder "
            f"(attempt {self._metrics.encoder_restarts}/{self.config.max_restarts})"
        )
        
        # H.10-D.1: Before restart, increment generation and release
        # all old-generation surfaces so new encoder never reuses them.
        old_gen = self._current_generation
        self._current_generation += 1
        self._session_id = f"S{self._generation:05d}"
        self._generation += 1

        # PHASE 50: Synchronize all pending CUDA events before releasing old surfaces
        for sid, event in list(self._pending_cuda_events.items()):
            try:
                event.synchronize()
                # CUDA event telemetry: CUDA_EVENT_STATUS
                emit_event(
                    camera=self.camera_id,
                    session_id=self._session_id,
                    event="CUDA_EVENT_STATUS",
                    meta={"surface_key": sid, "status": "completed"},
                    surface_key=sid,
                    data_ptr=0,
                    generation=old_gen,
                    ownership_state="cuda_stream_complete",
                    ref_count=0,
                    frame_id=self._session_id,
                )
            except Exception:
                pass
        self._pending_cuda_events.clear()
        # Release all IN_FLIGHT surfaces from previous generation
        for sid in list(self._ownership_states.keys()):
            info = self._ownership_states[sid]
            if info.get("generation") == old_gen:
                self._ownership_pool.release_encoder(sid, generation=self._current_generation)
                info["released_after_restart"] = True
                # Surface telemetry: SURFACE_RELEASABLE after restart
                emit_event(
                    camera=self.camera_id,
                    session_id=self._session_id,
                    event="SURFACE_RELEASABLE",
                    meta={"generation_before": old_gen, "generation_after": self._current_generation},
                    surface_key=sid,
                    data_ptr=0,
                    generation=self._current_generation,
                    ownership_state="releasable",
                    ref_count=0,
                    frame_id=self._session_id,
                )

        # Close current container
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="CONTAINER_CLOSE",
        )
        try:
            if self._container:
                self._container.close()
        except Exception:
            pass
        self._container = None
        self._stream = None

        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="QUEUE_STATE",
            meta={"queue_length": self._frame_queue.qsize(), "action": "before_drain"},
        )
        # PHASE 46B: Ensure new encoder session does not inherit stale queue frames.
        # Drain any queued frames from the previous session; create new empty queue.
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
        self._frame_queue = queue.Queue(maxsize=2)
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="QUEUE_STATE",
            meta={"queue_length": self._frame_queue.qsize(), "action": "recreated"},
        )
        self._finalized = False  # 46D: new session may need finalization again.

        # Wait before restart
        time.sleep(backoff)
        backoff = min(backoff * 2, 30.0)
        
        try:
            self._init_pyav_encoder()
        except Exception as e:
            logger.error(f"PyAVNVENCEncoder({self.camera_id}): Restart failed: {e}")
            # Ensure no partial/dead session remains after failed restart.
            if self._container:
                try:
                    self._container.close()
                except Exception:
                    pass
            self._container = None
            self._stream = None
            # Queue already cleared by 46B invariant; do not recreate here.

        # 46C: Confirm new session owns valid container and stream before resuming.
        if self._container is None or self._stream is None:
            logger.warning(
                f"PyAVNVENCEncoder({self.camera_id}): Restart left container/stream empty; "
                f"encode loop will attempt re-init on next frame."
            )
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the encoder and flush remaining frames."""
        if not self._metrics.started:
            return
        
        logger.info(f"PyAVNVENCEncoder({self.camera_id}): stopping")
        self._stop_event.set()
        
        # Flush encoder
        # Flush encoder: flush consumes in-flight frames through NVENC.
        # After flush completes, we can release surfaces safely.
        if self._stream and self._container and not self._finalized:
            emit_event(
                camera=self.camera_id,
                session_id=self._session_id,
                event="FINALIZE",
                meta={"finalized": True},
            )
            self._finalized = True  # 46D: only finalize once.
            try:
                for packet in self._stream.encode(None):
                    self._container.mux(packet)
            except Exception as e:
                logger.debug(f"PyAVNVENCEncoder({self.camera_id}): Flush error: {e}")
            # H.10-D.1: After flush, release all tracked surfaces from
            # this generation so they can become RELEASABLE/AVAILABLE.
            for sid in list(self._ownership_states.keys()):
                info = self._ownership_states[sid]
                if info.get("generation") == self._current_generation:
                    self._ownership_pool.release_encoder(sid)
                    info["released_after_flush"] = True
                    self._ownership_pool.mark_available_for_reuse(sid)
        
        if self._encode_thread and self._encode_thread.is_alive():
            self._encode_thread.join(timeout=timeout)
        
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="CONTAINER_CLOSE",
        )
        if self._container:
            try:
                self._container.close()
            except Exception as e:
                logger.debug(f"PyAVNVENCEncoder({self.camera_id}): Container close error: {e}")
            finally:
                self._container = None
                self._stream = None
        
        emit_event(
            camera=self.camera_id,
            session_id=self._session_id,
            event="RTSP_DISCONNECT",
            meta={"level": "APP_LEVEL"},
        )
        self._metrics.started = False
        logger.info(f"PyAVNVENCEncoder({self.camera_id}): stopped")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get encoder metrics."""
        m = self._metrics
        return {
            "camera_id": self.camera_id,
            "started": m.started,
            "frames_encoded": m.frames_encoded,
            "frames_dropped": m.frames_dropped,
            "encoder_restarts": m.encoder_restarts,
            "last_encode_time": m.last_encode_time,
            "output_dimensions": [self.config.width, self.config.height],
            "target_fps": self.config.fps,
            "rtsp_url": self.config.rtsp_url,
            "last_error": m.last_error,
            "encode_backend": "pyav_nvenc",
            "nvenc_gpu_device": self.config.nvenc_gpu_device,
            "nvenc_preset": self.config.nvenc_preset,
            "nvenc_tune": self.config.nvenc_tune,
            "nvenc_rc": self.config.nvenc_rc,
        }
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def create_pyav_nvenc_encoder(
    camera_id: str,
    rtsp_url: str,
    width: int = 3840,
    height: int = 2160,
    fps: float = 15.0,
    video_bitrate_kbps: int = 2500,
    gop_seconds: float = 1.0,
    max_restarts: int = 5,
    restart_backoff_seconds: float = 2.0,
    nvenc_gpu_device: int = 0,
    nvenc_preset: str = "p1",
    nvenc_tune: str = "ll",
    nvenc_rc: str = "cbr",
    nvenc_hw_frames: int = 8,
) -> PyAVNVENCEncoder:
    """Factory function to create PyAVNVENCEncoder."""
    config = PyAVNVENCEncoderConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        width=width,
        height=height,
        fps=fps,
        video_bitrate_kbps=video_bitrate_kbps,
        gop_seconds=gop_seconds,
        max_restarts=max_restarts,
        restart_backoff_seconds=restart_backoff_seconds,
        nvenc_gpu_device=nvenc_gpu_device,
        nvenc_preset=nvenc_preset,
        nvenc_tune=nvenc_tune,
        nvenc_rc=nvenc_rc,
        nvenc_hw_frames=nvenc_hw_frames,
    )
    return PyAVNVENCEncoder(config)