"""
Phase 44.X.4 — Annotated Frame Publisher.

Per-camera transport that turns annotated frames into a continuous H.264
stream and pushes it into MediaMTX over RTSP. MediaMTX in turn repackages
the stream as HLS, which the existing CameraCard consumes.

Architecture:

    DetectionPipeline.process_frame(frame)
        |
        +-- existing path: HealthEvent -> WebSocket (KEEP)
        +-- NEW path:     AnnotatedFramePublisher.submit(frame_data, overlay, lines, regions)
                              |
                              v
                          latest-wins bounded queue (size 1)
                              |
                              v
                          FFmpeg subprocess per camera
                              ffmpeg -f rawvideo -pix_fmt bgr24 -s WxH -r N
                                     -i pipe:0  -c:v libx264 -preset veryfast
                                     -tune zerolatency -g N -pix_fmt yuv420p
                                     -f rtsp  rtsp://localhost:8554/live/<cam>-ai

The publisher does NOT re-run inference. It only:
  * Consumes the canonical annotated ndarray produced by
    app.streaming.annotation_renderer.annotate_frame(...)
  * Sends it to FFmpeg which encodes H.264 and pushes RTSP into MediaMTX.
  * Drops frames if the encoder cannot keep up (latest-wins).
  * Keeps per-camera state isolated (one publisher, one queue, one
    FFmpeg subprocess, one RTSP target per camera_id).

Failure mode:
  If the FFmpeg subprocess crashes, the publisher attempts one restart.
  If it cannot recover, the publisher stops accepting new frames but
  does NOT stop the detection pipeline - the pipeline must continue to
  feed the WebSocket/DetectionSnapshot path.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import torch

from app.streaming.annotation_renderer import annotate_frame
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract, nv12_cuda_to_bgr_cuda
from app.vision.gpu_annotation_pyav import GPUAnnotationPyAVRenderer, GPUAnnotationPyAVConfig, get_gpu_annotation_pyav_renderer
from app.video.pynvcodec.encoder_adapter import EncoderAdapter
from app.streaming.encoder_packet_publisher import EncoderPacketToPublisherBridge

logger = logging.getLogger(__name__)


@dataclass
class AnnotatedPublisherConfig:
    """Configuration for the annotated frame publisher."""

    camera_id: str
    # RTSP target published to MediaMTX (must match mediamtx.yml path).
    rtsp_url: str
    # Output frame width/height. If None, use the first frame's dimensions.
    width: Optional[int] = None
    height: Optional[int] = None
    # Output frame rate (1/fps). Used by FFmpeg to pace frames.
    fps: float = 15.0
    # FFmpeg encoder settings.
    video_bitrate_kbps: int = 2500
    gop_seconds: float = 1.0
    # Maximum reconnection attempts to the FFmpeg subprocess / RTSP.
    max_restarts: int = 5
    restart_backoff_seconds: float = 2.0
    # Sizing cap: downscale oversized frames for transport efficiency.
    max_output_width: int = 1920
    max_output_height: int = 1080
    # Whether to draw overlays on frames.
    enable_overlay: bool = True
    # GPU annotation settings
    enable_gpu_annotation: bool = True
    gpu_annotation_font_path: str = "C:/Windows/Fonts/arial.ttf"
    gpu_annotation_font_size: int = 48
    # Encoder settings (for native NVENC path)
    encoder_codec: str = "h264"
    encoder_preset: str = "P4"
    encoder_bitrate_kbps: int = 8000
    encoder_max_bitrate_kbps: int = 12000
    encoder_gop_length: int = 30
    encoder_idr_period: int = 60
    encoder_cuda_stream: int = 0


@dataclass
class AnnotatedPublisherMetrics:
    """Counters surfaced for runtime diagnostics / phase 44.X.4 proof."""

    frames_submitted: int = 0
    frames_encoded: int = 0
    frames_dropped: int = 0
    encoder_restarts: int = 0
    last_frame_width: int = 0
    last_frame_height: int = 0
    last_submit_time: float = 0.0
    last_encode_time: float = 0.0
    started: bool = False
    ffmpeg_pid: Optional[int] = None
    last_error: str = ""


class AnnotatedFramePublisher:
    """
    Per-camera publisher of annotated frames to MediaMTX over RTSP.

    Lifecycle:
        p = AnnotatedFramePublisher(config)
        p.start()        # spawns encode thread + FFmpeg subprocess
        p.submit(frame_data, overlay_items, lines, regions)
        ...
        p.stop()         # drains queue and terminates FFmpeg cleanly

    Threading model:
        * submit() is called from the detection pipeline thread (per-camera
          ingestion worker). It is non-blocking; it enqueues the latest
          annotated frame using a size-1 queue (latest-wins).
        * The encode thread runs FFmpeg via stdin pipe (raw BGR frames).
        * Camera isolation: each publisher owns its own config, queue,
          thread, subprocess and RTSP URL.
    """

    def __init__(
        self,
        config: AnnotatedPublisherConfig,
        time_func: Any = time.time,
        enable_liveness_watchdog: bool = True,
        liveness_config: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._time = time_func
        self._queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._ffmpeg_lock = threading.Lock()
        self._width: Optional[int] = config.width
        self._height: Optional[int] = config.height
        self._metrics = AnnotatedPublisherMetrics()
        self._camera_tag = config.camera_id

        # Per-publisher re-entrancy guard for restart to prevent
        # concurrent restarts by the liveness watchdog and the encode
        # loop.
        self._restart_in_progress = threading.Lock()
        self._liveness_watchdog: Optional[Any] = None
        self._enable_liveness_watchdog = enable_liveness_watchdog
        self._liveness_config = liveness_config

        # GPU annotation renderer
        self._gpu_annotation_renderer: Optional[GPUAnnotationPyAVRenderer] = None
        self._gpu_annotation_enabled = config.enable_gpu_annotation

        # Native NVENC encoder
        self._encoder: Optional[EncoderAdapter] = None
        self._encoder_initialized = False

        # Packet publisher bridge for H.264 packets
        self._packet_bridge: Optional[EncoderPacketToPublisherBridge] = None

    # ------------------------------------------------------------------ start
    def start(self) -> bool:
        """Spawn the encode thread. Returns True on success."""
        if self._metrics.started:
            logger.warning("AnnotatedFramePublisher(%s): already started", self.camera_id)
            return True

        if not shutil.which("ffmpeg"):
            logger.error("AnnotatedFramePublisher(%s): ffmpeg not found in PATH", self.camera_id)
            self._metrics.last_error = "ffmpeg not found in PATH"
            return False

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_encode_loop,
            name=f"ai-encoder-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()
        self._metrics.started = True

        if self._enable_liveness_watchdog:
            self._start_liveness_watchdog()

        logger.info(
            "AnnotatedFramePublisher(%s): started (target=%s)",
            self.camera_id,
            self.config.rtsp_url,
        )
        return True

    # ------------------------------------------------------------- liveness
    def _start_liveness_watchdog(self) -> None:
        """Start the per-publisher liveness watchdog (idempotent)."""
        if self._liveness_watchdog is not None:
            return
        try:
            from app.streaming.publisher_liveness import (
                PublisherLivenessConfig,
                create_publisher_liveness_watchdog,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "AnnotatedFramePublisher(%s): could not import "
                "publisher_liveness: %s",
                self.camera_id,
                e,
            )
            return

        ai_path = self._ai_path()
        if self._liveness_config is None:
            self._liveness_config = PublisherLivenessConfig(
                ai_path=ai_path,
            )
        elif self._liveness_config.ai_path == "":
            # Patch the path if the caller didn't set it.
            object.__setattr__(
                self._liveness_config, "ai_path", ai_path
            )

        self._liveness_watchdog = create_publisher_liveness_watchdog(
            config=self._liveness_config,
            camera_id=self.camera_id,
            publisher_metrics_func=self.get_metrics,
            on_unhealthy=self._on_liveness_unhealthy,
        )
        self._liveness_watchdog.start()
        logger.info(
            "AnnotatedFramePublisher(%s): liveness watchdog started "
            "(ai_path=%s)",
            self.camera_id,
            ai_path,
        )

    def _ai_path(self) -> str:
        """Extract MediaMTX AI path from the RTSP URL.

        MediaMTX Control API returns path names WITHOUT a leading slash
        (e.g. ``live/cam1-ai``). The liveness watchdog compares
        ``config.ai_path`` against ``item["name"]`` in the API response,
        so the path must be returned in the same form MediaMTX uses,
        i.e. without the leading slash.
        """
        url = self.config.rtsp_url
        # rtsp://host:port/live/<name>
        # Strip scheme + host + port; strip leading slash so it matches
        # MediaMTX path names exactly.
        try:
            without_scheme = url.split("rtsp://", 1)[1]
            host_part, path = without_scheme.split("/", 1)
            return path.lstrip("/")
        except Exception:  # noqa: BLE001
            return "live/" + self.camera_id.lower() + "-ai"

    def _on_liveness_unhealthy(self, info: Dict[str, Any]) -> None:
        """Liveness watchdog callback: restart the publisher."""
        logger.warning(
            "AnnotatedFramePublisher(%s): liveness watchdog reports "
            "unhealthy; restarting",
            self.camera_id,
        )
        try:
            self.restart()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "AnnotatedFramePublisher(%s): restart failed: %s",
                self.camera_id,
                e,
            )

    # ----------------------------------------------------------------- restart
    def restart(self, timeout: float = 5.0) -> bool:
        """
        Restart the publisher: stop FFmpeg, drain state, spawn a new
        FFmpeg subprocess. Returns True if the new FFmpeg process was
        started.
        """
        if not self._metrics.started:
            return False
        if not self._restart_in_progress.acquire(blocking=False):
            logger.debug(
                "AnnotatedFramePublisher(%s): restart already in progress",
                self.camera_id,
            )
            return False
        try:
            self._terminate_ffmpeg()
            # Drain stale frames so the next FFmpeg starts clean.
            try:
                while True:
                    self._queue.get_nowait()
            except queue.Empty:
                pass
            # Reset per-restart metrics so the liveness watchdog sees
            # fresh state.
            self._metrics.frames_encoded = 0
            self._metrics.last_encode_time = 0.0
            # The encode loop will reopen FFmpeg on the next iteration.
            # Wake the encode loop by injecting a sentinel-sized frame
            # so it exits the current _drain_queue_into_ffmpeg() and
            # re-enters the open_ffmpeg() path. We use a non-blocking
            # put of an existing placeholder if available.
            try:
                # No-op: _drain_queue_into_ffmpeg checks proc.poll();
                # after _terminate_ffmpeg the loop will exit and the
                # outer _run_encode_loop will reopen.
                pass
            except Exception:  # noqa: BLE001
                pass
            return True
        finally:
            self._restart_in_progress.release()

    # ------------------------------------------------------------------- stop
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the publisher and terminate FFmpeg cleanly."""
        if not self._metrics.started:
            return
        self._stop_event.set()
        # Wake the encode thread by sending an empty marker.
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._terminate_ffmpeg()
        if self._liveness_watchdog is not None:
            try:
                self._liveness_watchdog.stop()
            except Exception:  # noqa: BLE001
                pass
            self._liveness_watchdog = None
        self._metrics.started = False
        logger.info("AnnotatedFramePublisher(%s): stopped", self.camera_id)

    # Encoded-packet entrypoint: adapter packets directly (no CPU BGR conversion, no synthetic packets, no replay, no decode/re-encode, no PyAV production path).
    # The adapter produces real NVENC H.264 packets (Dict {"data": bytes, ...}) through PyNvVideoCodec 2.2.3.
    # This entrypoint receives the packet payload directly and feeds it to the adapter-bridge or existing FFmpeg stdin.
    # The existing raw-frame submit(np.ndarray) contract is preserved independently for non-encoded pipeline use.
    def submit_encoded_packet(self, payload: bytes) -> bool:
        """
        Submit an already-encoded H.264 packet payload directly to the publisher pipeline.

        The payload must be real H.264 Annex-B bytes (e.g. adapter packets from
        EncoderAdapter.encode_frame() / end_encode()).

        No CPU BGR conversion is performed. No synthetic/mock/replay packets are allowed.
        No decode/re-encode occurs. The payload reaches FFmpeg stdin directly.
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False
        if payload is None or not isinstance(payload, (bytes, bytearray)):
            logger.error("AnnotatedFramePublisher(%s): submit_encoded_packet requires real bytes payload; got %s", self.camera_id, type(payload))
            return False
        if len(payload) == 0:
            logger.error("AnnotatedFramePublisher(%s): submit_encoded_packet requires non-empty payload; empty bytes rejected", self.camera_id)
            return False

        # If FFmpeg is running in rawvideo mode, we need to restart it in h264 mode
        # to accept elementary H.264 stream
        with self._ffmpeg_lock:
            proc = self._ffmpeg_proc
            if proc is not None and proc.poll() is None:
                # Check if FFmpeg was started in rawvideo mode
                if not hasattr(self, '_input_format') or self._input_format != 'h264':
                    # Need to restart FFmpeg in h264 mode
                    logger.info("AnnotatedFramePublisher(%s): Restarting FFmpeg in h264 mode for encoded packets", self.camera_id)
                    try:
                        proc.stdin.close()
                        proc.wait(timeout=3.0)
                    except Exception:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3.0)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                    self._ffmpeg_proc = None
                    proc = None
                    # Set flag to use h264 input format
                    self._input_format = 'h264'

        if proc is None or proc.stdin is None or proc.stdin.closed:
            # Start FFmpeg in h264 mode
            self._input_format = 'h264'
            try:
                self._open_ffmpeg()
                proc = self._ffmpeg_proc
                time.sleep(0.5)  # Wait for FFmpeg to initialize
            except Exception as e:
                logger.error("AnnotatedFramePublisher(%s): Failed to start FFmpeg in h264 mode: %s", self.camera_id, e)
                return False

        if proc is None or proc.stdin is None or proc.stdin.closed:
            logger.warning("AnnotatedFramePublisher(%s): FFmpeg process not running or stdin closed", self.camera_id)
            return False

        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
            self._metrics.frames_submitted += 1
            self._metrics.packets_submitted = 1
            logger.debug("AnnotatedFramePublisher(%s): submit_encoded_packet accepted payload bytes=%d", self.camera_id, len(payload))
            return True
        except (BrokenPipeError, OSError) as exc:
            logger.error("AnnotatedFramePublisher(%s): submit_encoded_packet stdin write failed: %s", self.camera_id, exc)
            return False


    def submit(
        self,
        frame_data: GPUFrameContract,
        detections: Optional[List[Dict[str, Any]]] = None,
        lines: Optional[List[Dict[str, Any]]] = None,
        regions: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Submit a GPUFrameContract with overlay items for GPU annotation + NVENC encoding.
        
        This is the GPU-native path: GPUFrameContract -> GPU annotation -> Native NVENC -> H.264 -> Publisher -> MediaMTX
        No CPU raw-frame staging occurs.
        """
        if not self._metrics.started or self._stop_event.is_set():
            return False
        if frame_data is None:
            logger.error("AnnotatedFramePublisher(%s): submit requires GPUFrameContract; got None", self.camera_id)
            return False

        self._metrics.frames_submitted += 1

        try:
            # Initialize GPU annotation renderer if enabled and not yet created
            if self._gpu_annotation_enabled and self._gpu_annotation_renderer is None:
                gpu_config = GPUAnnotationPyAVConfig(
                    enabled=True,
                    gpu_device=0,
                    text_enabled=True,
                    text_font_path=self.config.gpu_annotation_font_path,
                    text_font_size=self.config.gpu_annotation_font_size,
                )
                self._gpu_annotation_renderer = get_gpu_annotation_pyav_renderer(self.camera_id, gpu_config)
                logger.info("AnnotatedFramePublisher(%s): GPU annotation renderer initialized", self.camera_id)

            # Initialize native NVENC encoder if not yet created
            if self._encoder is None and not self._encoder_initialized:
                import torch
                torch_stream = torch.cuda.Stream()
                self._encoder = EncoderAdapter(
                    codec=self.config.encoder_codec,
                    preset=self.config.encoder_preset,
                    fps=self.config.fps,
                    bitrate_kbps=self.config.encoder_bitrate_kbps,
                    max_bitrate_kbps=self.config.encoder_max_bitrate_kbps,
                    gop_length=self.config.encoder_gop_length,
                    idr_period=self.config.encoder_idr_period,
                    cuda_stream=torch_stream.cuda_stream,
                )
                self._encoder.open(width=frame_data.width, height=frame_data.height)
                self._encoder_initialized = True
                logger.info("AnnotatedFramePublisher(%s): Native NVENC encoder initialized (%dx%d)", 
                           self.camera_id, frame_data.width, frame_data.height)

            # Initialize packet bridge if not yet created
            if self._packet_bridge is None:
                self._packet_bridge = EncoderPacketToPublisherBridge(
                    rtsp_url=self.config.rtsp_url,
                    width=frame_data.width,
                    height=frame_data.height,
                    fps=self.config.fps,
                )
                self._packet_bridge.start(bitrate_kbps=self.config.encoder_bitrate_kbps, gop_seconds=self.config.gop_seconds)
                logger.info("AnnotatedFramePublisher(%s): Packet bridge started", self.camera_id)

            # Get NV12 planes from GPUFrameContract
            y_tensor, uv_tensor = frame_data.get_tensors()

            # Apply GPU annotation if enabled
            if self._gpu_annotation_enabled and self._gpu_annotation_renderer is not None:
                try:
                    annotated_y, annotated_uv = self._gpu_annotation_renderer.annotate_nv12(
                        y_plane=y_tensor,
                        uv_plane=uv_tensor,
                        detections=detections,
                        lines=lines,
                        regions=regions,
                        camera_id=self.camera_id,
                    )
                    # Use annotated planes
                    y_tensor, uv_tensor = annotated_y, annotated_uv
                except Exception as e:
                    logger.error("AnnotatedFramePublisher(%s): GPU annotation failed: %s", self.camera_id, e)
                    # Continue without annotation (use original planes)

            # Encode using native NVENC
            packets = self._encoder.encode_frame(
                gpu_frame_ref=frame_data,
                pts=frame_data.pts,
                frame_id=frame_data.frame_id,
                camera_id=frame_data.camera_id,
            )

            # Submit packets to publisher bridge
            if packets and self._packet_bridge:
                for pkt in packets:
                    data = pkt.get('data', b'')
                    if data:
                        self._packet_bridge.submit_packet_bytes(data)
                        self._metrics.frames_encoded += 1
                        self._metrics.last_encode_time = self._time()

            return True

        except Exception as e:
            logger.error("AnnotatedFramePublisher(%s): submit failed: %s", self.camera_id, e)
            self._metrics.last_error = str(e)
            return False


    # -------------------------------------------------------------- internals
    def _prepare_frame(self, frame: np.ndarray) -> Optional[np.ndarray]:
        """Resize the annotated frame to the configured output dimensions."""
        if frame.ndim == 2:
            frame = _ensure_bgr(frame)
        if frame.ndim != 3 or frame.shape[2] not in (3, 4):
            return None

        h, w = frame.shape[:2]

        if self._width is None or self._height is None:
            self._width, self._height = self._fit_to_max(w, h)

        target_w, target_h = self._width, self._height
        if (w, h) != (target_w, target_h):
            frame = _resize(frame, target_w, target_h)
        return np.ascontiguousarray(frame[:, :, :3])

    def _fit_to_max(self, w: int, h: int) -> tuple:
        max_w = self.config.max_output_width
        max_h = self.config.max_output_height
        if w <= max_w and h <= max_h:
            return w, h
        scale = min(max_w / w, max_h / h)
        new_w = max(2, int((w * scale) // 2 * 2))
        new_h = max(2, int((h * scale) // 2 * 2))
        return new_w, new_h

    def _run_encode_loop(self) -> None:
        """Encode loop: pull frames from the queue and pipe to FFmpeg."""
        backoff = self.config.restart_backoff_seconds
        restarts = 0
        # Counter incremented by the liveness watchdog restart path
        # so this loop can notice "external restart requested".
        self._external_restart_count = 0
        while not self._stop_event.is_set():
            # Wait until the first annotated frame arrives so we know
            # the output dimensions. Bounded wait so a stop is responsive.
            while not self._stop_event.is_set() and (self._width is None or self._height is None):
                try:
                    first = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if first is _SENTINEL:
                    return
                prepared = self._prepare_frame(first)
                if prepared is None:
                    continue
                # Park the first frame so the encode loop can drain it as
                # soon as ffmpeg is opened.
                try:
                    self._queue.put_nowait(prepared)
                except queue.Full:
                    # Queue is size 1; replace the head with the prepared copy.
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(prepared)
                self._metrics.frames_submitted += 1
                self._metrics.last_frame_width = prepared.shape[1]
                self._metrics.last_frame_height = prepared.shape[0]
                self._metrics.last_submit_time = self._time()
                break

            if self._stop_event.is_set():
                return

            try:
                self._open_ffmpeg()
            except Exception as e:  # noqa: BLE001
                self._metrics.last_error = f"ffmpeg open failed: {e}"
                logger.error(
                    "AnnotatedFramePublisher(%s): %s", self.camera_id, self._metrics.last_error
                )
                restarts += 1
                if restarts > self.config.max_restarts:
                    logger.error(
                        "AnnotatedFramePublisher(%s): giving up after %d restarts",
                        self.camera_id,
                        restarts,
                    )
                    return
                self._stop_event.wait(timeout=backoff)
                backoff = min(backoff * 2, 30.0)
                continue

            backoff = self.config.restart_backoff_seconds
            restarts = 0
            self._drain_queue_into_ffmpeg()
            if self._stop_event.is_set():
                break
            # FFmpeg died unexpectedly; the loop restarts it.
            self._metrics.encoder_restarts += 1
            self._metrics.last_error = "ffmpeg exited unexpectedly"
            logger.warning(
                "AnnotatedFramePublisher(%s): ffmpeg exited, restart=%d",
                self.camera_id,
                self._metrics.encoder_restarts,
            )

    def _open_ffmpeg(self) -> None:
        if self._width is None or self._height is None:
            # Wait for the first frame to set dimensions.
            raise RuntimeError("output dimensions not yet known")

        # Support both rawvideo and h264 input formats
        if hasattr(self, '_input_format') and self._input_format == 'h264':
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-fflags", "+genpts",
                "-f", "h264",
                "-i", "pipe:0",
                "-an",
                "-c:v", "copy",
                "-muxdelay", "0",
                "-muxpreload", "0",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                self.config.rtsp_url,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-s", f"{self._width}x{self._height}",
                "-r", f"{self.config.fps:.3f}",
                "-i", "pipe:0",
                "-an",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "zerolatency",
                "-g", str(max(1, int(round(self.config.fps * self.config.gop_seconds)))),
                "-keyint_min", str(max(1, int(round(self.config.fps * self.config.gop_seconds)))),
                "-sc_threshold", "0",
                "-pix_fmt", "yuv420p",
                "-b:v", f"{self.config.video_bitrate_kbps}k",
                "-bufsize", f"{self.config.video_bitrate_kbps * 2}k",
                "-fflags", "+flush_packets",
                "-flush_packets", "1",
                "-muxdelay", "0",
                "-muxpreload", "0",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                self.config.rtsp_url,
            ]

        env = os.environ.copy()
        env.setdefault("AV_LOG_FORCE_NOCOLOR", "1")

        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        self._ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            creationflags=creationflags,
        )
        self._metrics.ffmpeg_pid = self._ffmpeg_proc.pid
        logger.info(
            "AnnotatedFramePublisher(%s): ffmpeg started pid=%s url=%s",
            self.camera_id,
            self._ffmpeg_proc.pid,
            self.config.rtsp_url,
        )
        # Drain stderr in a small thread so FFmpeg can't block on a full pipe.
        threading.Thread(
            target=self._drain_ffmpeg_stderr,
            name=f"ai-encoder-stderr-{self.camera_id}",
            daemon=True,
        ).start()

    def _drain_ffmpeg_stderr(self) -> None:
        proc = self._ffmpeg_proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in iter(proc.stderr.readline, b""):
                if not line:
                    break
                msg = line.decode("utf-8", errors="replace").rstrip()
                if msg:
                    logger.debug("ffmpeg[%s]: %s", self.camera_id, msg)
        except Exception:
            pass

    def _drain_queue_into_ffmpeg(self) -> None:
        proc = self._ffmpeg_proc
        if proc is None or proc.stdin is None:
            return

        frame_bytes = (self._width or 0) * (self._height or 0) * 3
        while not self._stop_event.is_set():
            # If FFmpeg has died, break out and let the outer loop restart.
            if proc.poll() is not None:
                return
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if frame is _SENTINEL:
                return
            try:
                proc.stdin.write(frame.tobytes())
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._metrics.last_error = f"ffmpeg pipe write failed: {e}"
                logger.warning(
                    "AnnotatedFramePublisher(%s): %s", self.camera_id, self._metrics.last_error
                )
                return
            self._metrics.frames_encoded += 1
            self._metrics.last_encode_time = self._time()
            if frame_bytes <= 0:
                frame_bytes = frame.shape[0] * frame.shape[1] * 3

    def _terminate_ffmpeg(self) -> None:
        with self._ffmpeg_lock:
            proc = self._ffmpeg_proc
            self._ffmpeg_proc = None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "AnnotatedFramePublisher(%s): error terminating ffmpeg: %s", self.camera_id, e
            )

    # ----------------------------------------------------------------- access
    @property
    def camera_id(self) -> str:
        return self._camera_tag

    def get_metrics(self) -> Dict[str, Any]:
        m = self._metrics
        out = {
            "camera_id": self.camera_id,
            "started": m.started,
            "frames_submitted": m.frames_submitted,
            "frames_encoded": m.frames_encoded,
            "frames_dropped": m.frames_dropped,
            "encoder_restarts": m.encoder_restarts,
            "ffmpeg_pid": m.ffmpeg_pid,
            "last_frame_width": m.last_frame_width,
            "last_frame_height": m.last_frame_height,
            "last_submit_time": m.last_submit_time,
            "last_encode_time": m.last_encode_time,
            "output_dimensions": [self._width or 0, self._height or 0],
            "target_fps": self.config.fps,
            "rtsp_url": self.config.rtsp_url,
            "last_error": m.last_error,
        }
        if self._liveness_watchdog is not None:
            out["liveness"] = self._liveness_watchdog.get_metrics()
        return out


_SENTINEL = np.zeros((1, 1, 3), dtype=np.uint8)


def _ensure_bgr(frame: np.ndarray) -> np.ndarray:
    import cv2

    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    return frame


def _resize(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    import cv2

    return cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)


def create_annotated_publisher(
    camera_id: str,
    rtsp_url: Optional[str] = None,
    fps: float = 15.0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    video_bitrate_kbps: int = 2500,
    enable_liveness_watchdog: bool = True,
    liveness_config: Optional[Any] = None,
) -> AnnotatedFramePublisher:
    """Factory for the canonical annotated frame publisher."""
    path_id = camera_id.lower()
    if rtsp_url is None:
        rtsp_url = f"rtsp://localhost:8554/live/{path_id}-ai"
    config = AnnotatedPublisherConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        fps=fps,
        width=width,
        height=height,
        video_bitrate_kbps=video_bitrate_kbps,
    )
    return AnnotatedFramePublisher(
        config=config,
        enable_liveness_watchdog=enable_liveness_watchdog,
        liveness_config=liveness_config,
    )
