"""
Zero-Latency Hardware NVENC Annotated Stream Publisher.

Renders frame-locked bounding boxes and cached Vietnamese Pillow TrueType
label pills directly onto the exact inferred frame (< 1ms/frame) and publishes
a baseline H.264 stream (``-bf 0 -preset p1 -tune ull -zerolatency 1``) via
TCP RTSP to MediaMTX (``live/{cam_id}_ai``) for unified WebRTC WHEP playback.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)

_NVENC_PROBE_LOCK = threading.Lock()
_NVENC_PROBE_RESULT: Optional[bool] = None


def probe_h264_nvenc_available() -> bool:
    """Probe ``ffmpeg -encoders`` once and cache whether ``h264_nvenc`` is available."""
    global _NVENC_PROBE_RESULT
    with _NVENC_PROBE_LOCK:
        if _NVENC_PROBE_RESULT is not None:
            return _NVENC_PROBE_RESULT
        try:
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=6.0,
            )
            available = proc.returncode == 0 and ("h264_nvenc" in (proc.stdout or ""))
            _NVENC_PROBE_RESULT = bool(available)
        except Exception as exc:
            logger.warning(f"probe_h264_nvenc_available failed: {exc}")
            _NVENC_PROBE_RESULT = False
        logger.info(f"[NVENC] Probe ffmpeg h264_nvenc available={_NVENC_PROBE_RESULT}")
        return _NVENC_PROBE_RESULT


def nv12_gpu_to_bgr_resized_cpu(
    y_tensor: torch.Tensor,
    uv_tensor: torch.Tensor,
    out_w: int,
    out_h: int,
    cuda_stream: Optional[torch.cuda.Stream] = None,
) -> np.ndarray:
    """Downscale NV12 CUDA planes to ``(out_h, out_w, 3)`` uint8 BGR on GPU and copy to CPU."""
    def _convert() -> torch.Tensor:
        h_in, w_in = int(y_tensor.shape[0]), int(y_tensor.shape[1])
        if h_in != out_h or w_in != out_w:
            y_f = F.interpolate(
                y_tensor.unsqueeze(0).unsqueeze(0).float(),
                size=(out_h, out_w),
                mode="bilinear",
                align_corners=False,
            ).squeeze(0).squeeze(0)
        else:
            y_f = y_tensor.float()

        uv_f = F.interpolate(
            uv_tensor.permute(2, 0, 1).unsqueeze(0).float(),
            size=(out_h, out_w),
            mode="bilinear",
            align_corners=False,
        ).squeeze(0)  # (2, out_h, out_w)

        y = (y_f - 16.0) * (255.0 / 219.0)
        u = (uv_f[0] - 128.0) * (255.0 / 224.0)
        v = (uv_f[1] - 128.0) * (255.0 / 224.0)

        r = torch.clamp(y + 1.402 * v, 0.0, 255.0)
        g = torch.clamp(y - 0.344136 * u - 0.714136 * v, 0.0, 255.0)
        b = torch.clamp(y + 1.772 * u, 0.0, 255.0)
        return torch.stack((b, g, r), dim=2).byte().contiguous()

    with torch.no_grad():
        if cuda_stream is not None and y_tensor.is_cuda:
            with torch.cuda.stream(cuda_stream):
                bgr_gpu = _convert()
            cuda_stream.synchronize()
        else:
            bgr_gpu = _convert()
            if y_tensor.is_cuda:
                torch.cuda.synchronize(y_tensor.device)
        bgr_cpu = bgr_gpu.cpu().numpy()

    return np.ascontiguousarray(bgr_cpu, dtype=np.uint8)


class VietnameseLabelCache:
    """
    LRU-cached Pillow RGBA label pill renderer for sub-millisecond OpenCV overlay.

    Avoids running Pillow over the full frame: each unique ``(label, color_key)``
    badge is rasterized once to a tight RGBA numpy sprite and alpha-blended only
    over its small ROI rectangle on the BGR frame.
    """

    COLOR_STYLES: Dict[str, Dict[str, Any]] = {
        "verified": {
            "box_bgr": (129, 185, 16),          # #10b981 emerald
            "pill_rgba": (16, 185, 129, 236),
            "border_rgba": (167, 243, 208, 255),
            "text_rgba": (0, 0, 0, 255),
        },
        "pending": {
            "box_bgr": (11, 158, 245),          # #f59e0b amber
            "pill_rgba": (245, 158, 11, 236),
            "border_rgba": (253, 230, 138, 255),
            "text_rgba": (0, 0, 0, 255),
        },
        "unmatched": {
            "box_bgr": (68, 68, 239),           # #ef4444 red
            "pill_rgba": (239, 68, 68, 236),
            "border_rgba": (254, 202, 202, 255),
            "text_rgba": (255, 255, 255, 255),
        },
    }

    def __init__(self, font_size: int = 15, max_entries: int = 256):
        self.font_size = int(font_size)
        self.max_entries = int(max_entries)
        self._font = self._load_font(self.font_size)
        self._cache: OrderedDict[Tuple[str, str], Tuple[np.ndarray, np.ndarray]] = OrderedDict()

    @staticmethod
    def _load_font(font_size: int) -> ImageFont.ImageFont:
        for path in _FONT_CANDIDATES:
            try:
                return ImageFont.truetype(path, font_size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    def classify_person(cls, person: Dict[str, Any]) -> Tuple[str, str]:
        """Classify track color key and construct Vietnamese display text."""
        tid = person.get("track_id", "?")
        candidate = str(
            person.get("identity_candidate")
            or person.get("person_name")
            or person.get("face_name")
            or person.get("name")
            or "Đang chờ thấy mặt..."
        ).strip()
        is_verified = bool(person.get("face_verified", False)) or bool(person.get("bridged_from_cam"))
        lower_cand = candidate.lower()
        if is_verified:
            color_key = "verified"
        elif "khách" in lower_cand or "chưa đăng ký" in lower_cand or "unknown" in lower_cand:
            color_key = "unmatched"
        else:
            color_key = "pending"
        return color_key, f"ID: {tid} | {candidate}"

    def _get_sprite(self, display_text: str, color_key: str) -> Tuple[np.ndarray, np.ndarray]:
        key = (display_text, color_key)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        style = self.COLOR_STYLES.get(color_key, self.COLOR_STYLES["pending"])
        dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        d0 = ImageDraw.Draw(dummy)
        tb = d0.textbbox((0, 0), display_text, font=self._font)
        text_w = max(1, int(tb[2] - tb[0]))
        text_h = max(1, int(tb[3] - tb[1]))

        pad_x = 8
        pad_y = 4
        pill_w = text_w + pad_x * 2
        pill_h = text_h + pad_y * 2

        img = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [0, 0, pill_w - 1, pill_h - 1],
            radius=5,
            fill=style["pill_rgba"],
            outline=style["border_rgba"],
            width=1,
        )
        draw.text(
            (pad_x - tb[0], pad_y - tb[1]),
            display_text,
            font=self._font,
            fill=style["text_rgba"],
        )

        rgba = np.asarray(img, dtype=np.uint8)
        bgr_sprite = np.ascontiguousarray(rgba[:, :, [2, 1, 0]], dtype=np.uint8)
        alpha_3ch = np.ascontiguousarray(
            rgba[:, :, 3:4].astype(np.float32) * (1.0 / 255.0),
            dtype=np.float32,
        )

        self._cache[key] = (bgr_sprite, alpha_3ch)
        if len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return bgr_sprite, alpha_3ch

    def render_tracks(self, frame_bgr: np.ndarray, persons: List[Dict[str, Any]]) -> np.ndarray:
        """Draw active current-frame bboxes and cached Vietnamese pills onto ``frame_bgr``."""
        if not persons:
            return frame_bgr

        frame_h, frame_w = frame_bgr.shape[:2]
        for person in persons:
            if str(person.get("state", "active")).lower() not in ("active", "new"):
                continue
            if int(person.get("time_since_update", 0) or 0) != 0:
                continue
            if int(person.get("missed_frames", 0) or 0) != 0:
                continue

            bbox = person.get("bbox")
            if not bbox or len(bbox) < 4:
                continue

            c1, c2, c3, c4 = [float(v) for v in bbox[:4]]
            if max(c1, c2, c3, c4) <= 1.5:
                x1 = int(round(max(0.0, min(1.0, c1)) * frame_w))
                y1 = int(round(max(0.0, min(1.0, c2)) * frame_h))
                x2 = int(round(max(0.0, min(1.0, c3)) * frame_w))
                y2 = int(round(max(0.0, min(1.0, c4)) * frame_h))
            else:
                x1, y1, x2, y2 = int(round(c1)), int(round(c2)), int(round(c3)), int(round(c4))

            x1 = max(0, min(frame_w - 2, x1))
            y1 = max(0, min(frame_h - 2, y1))
            x2 = max(x1 + 1, min(frame_w - 1, x2))
            y2 = max(y1 + 1, min(frame_h - 1, y2))

            color_key, display_text = self.classify_person(person)
            box_bgr = self.COLOR_STYLES[color_key]["box_bgr"]

            # Crisp bounding box (dark outer hairline + bright color stroke)
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (10, 10, 14), 4, lineType=cv2.LINE_AA)
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), box_bgr, 2, lineType=cv2.LINE_AA)

            bgr_sprite, alpha_3ch = self._get_sprite(display_text, color_key)
            sp_h, sp_w = bgr_sprite.shape[:2]

            px0 = max(2, min(x1, frame_w - sp_w - 2))
            py0 = y1 - sp_h - 3
            if py0 < 2:
                py0 = min(y1 + 3, max(2, frame_h - sp_h - 2))

            px1 = min(frame_w, px0 + sp_w)
            py1 = min(frame_h, py0 + sp_h)
            cw = px1 - px0
            ch = py1 - py0
            if cw <= 0 or ch <= 0:
                continue

            roi = frame_bgr[py0:py1, px0:px1]
            sprite_crop = bgr_sprite[:ch, :cw]
            alpha_crop = alpha_3ch[:ch, :cw]
            blended = (
                roi.astype(np.float32) * (1.0 - alpha_crop)
                + sprite_crop.astype(np.float32) * alpha_crop
            ).astype(np.uint8)
            frame_bgr[py0:py1, px0:px1] = blended

        return frame_bgr


@dataclass
class NvencPublisherConfig:
    """Configuration for hardware NVENC RTSP annotated publisher."""

    camera_id: str
    width: int = 1280
    height: int = 720
    fps: int = 30
    bitrate: str = "2800k"
    maxrate: str = "3200k"
    bufsize: str = "1200k"
    mediamtx_rtsp_base: str = "rtsp://127.0.0.1:8554/live"


class NvencAnnotatedPublisher:
    """
    Non-blocking single-slot RTSP publisher using ``h264_nvenc`` (or ``libx264`` fallback).

    Pushes annotated frames directly to ``rtsp://127.0.0.1:8554/live/{cam_id}_ai``
    with zero B-frames (``-bf 0``) and baseline H.264 profile so MediaMTX WebRTC
    WHEP works identically for both H.264 and H.265/HEVC camera sources.
    """

    def __init__(self, config: NvencPublisherConfig):
        self.config = config
        self.camera_id = str(config.camera_id).lower().strip()
        base = config.mediamtx_rtsp_base.rstrip("/")
        self.rtsp_url = f"{base}/{self.camera_id}_ai"
        parsed = urlparse(self.rtsp_url)
        self.ai_stream_path = parsed.path.lstrip("/") or f"live/{self.camera_id}_ai"

        self._renderer = VietnameseLabelCache(font_size=15)
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lifecycle_lock = threading.RLock()

        self._slot_lock = threading.Lock()
        self._slot_cond = threading.Condition(self._slot_lock)
        self._pending_item: Optional[Tuple[np.ndarray, List[Dict[str, Any]]]] = None

        self._active = False
        self._encoder_name = "h264_nvenc"
        self._frames_published = 0
        self._frames_dropped = 0
        self._render_times_ms: Deque[float] = deque(maxlen=60)
        self._stderr_tail: Deque[str] = deque(maxlen=30)

    @property
    def is_active(self) -> bool:
        proc = self._proc
        return bool(self._active and proc is not None and proc.poll() is None)

    @property
    def encoder_name(self) -> str:
        return self._encoder_name

    @property
    def frames_published(self) -> int:
        return self._frames_published

    @property
    def frames_dropped(self) -> int:
        return self._frames_dropped

    @property
    def avg_render_ms(self) -> float:
        if not self._render_times_ms:
            return 0.0
        return round(sum(self._render_times_ms) / len(self._render_times_ms), 3)

    def _build_ffmpeg_cmd(self, use_nvenc: bool) -> List[str]:
        w = int(self.config.width)
        h = int(self.config.height)
        fps = int(self.config.fps)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{w}x{h}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
        ]
        if use_nvenc:
            cmd.extend([
                "-c:v", "h264_nvenc",
                "-preset", "p1",
                "-tune", "ull",
                "-zerolatency", "1",
                "-rc", "cbr",
                "-b:v", str(self.config.bitrate),
                "-maxrate", str(self.config.maxrate),
                "-bufsize", str(self.config.bufsize),
                "-bf", "0",
                "-g", str(fps),
                "-profile:v", "baseline",
                "-pix_fmt", "yuv420p",
            ])
        else:
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-b:v", str(self.config.bitrate),
                "-maxrate", str(self.config.maxrate),
                "-bufsize", str(self.config.bufsize),
                "-bf", "0",
                "-g", str(fps),
                "-profile:v", "baseline",
                "-pix_fmt", "yuv420p",
            ])
        cmd.extend([
            "-flush_packets", "1",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            "-muxdelay", "0",
            "-muxpreload", "0",
            self.rtsp_url,
        ])
        return cmd

    def _spawn_ffmpeg(self, use_nvenc: bool) -> bool:
        cmd = self._build_ffmpeg_cmd(use_nvenc=use_nvenc)
        enc_label = "h264_nvenc" if use_nvenc else "libx264"
        self._stderr_tail.clear()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            logger.error(f"NvencPublisher({self.camera_id}): Failed spawning {enc_label}: {exc}")
            return False

        self._proc = proc
        self._encoder_name = enc_label
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(proc,),
            name=f"nvenc-err-{self.camera_id}",
            daemon=True,
        )
        self._stderr_thread.start()

        time.sleep(0.05)
        if proc.poll() is not None:
            tail = " | ".join(self._stderr_tail)
            logger.warning(
                f"NvencPublisher({self.camera_id}): {enc_label} exited immediately (rc={proc.returncode}): {tail}"
            )
            self._close_proc()
            return False

        logger.info(
            f"NvencPublisher({self.camera_id}): Started {enc_label} ({self.config.width}x{self.config.height}@{self.config.fps}fps) -> {self.rtsp_url}"
        )
        return True

    def _drain_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        pipe = proc.stderr
        if pipe is None:
            return
        try:
            while True:
                raw = pipe.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    self._stderr_tail.append(line)
        except Exception:
            pass

    def _close_proc(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        try:
            if proc.stderr and not proc.stderr.closed:
                proc.stderr.close()
        except Exception:
            pass

    def start(self) -> bool:
        """Start FFmpeg publisher and single-slot writer thread."""
        with self._lifecycle_lock:
            if self.is_active:
                return True
            self.stop()

            self._stop_event.clear()
            with self._slot_cond:
                self._pending_item = None

            use_nvenc = probe_h264_nvenc_available()
            started = False
            if use_nvenc:
                started = self._spawn_ffmpeg(use_nvenc=True)
            if not started:
                logger.warning(
                    f"NvencPublisher({self.camera_id}): Falling back to libx264 ultrafast zerolatency"
                )
                started = self._spawn_ffmpeg(use_nvenc=False)

            if not started:
                self._active = False
                return False

            self._active = True
            self._writer_thread = threading.Thread(
                target=self._writer_loop,
                name=f"nvenc-pub-{self.camera_id}",
                daemon=True,
            )
            self._writer_thread.start()
            return True

    def submit_frame(self, frame_bgr: np.ndarray, persons: List[Dict[str, Any]]) -> None:
        """Non-blocking single-slot submit (overwrites stale unconsumed frame)."""
        if not self._active or self._stop_event.is_set():
            return
        with self._slot_cond:
            if self._pending_item is not None:
                self._frames_dropped += 1
            self._pending_item = (frame_bgr, persons)
            self._slot_cond.notify()

    def _writer_loop(self) -> None:
        """Render cached Vietnamese overlays onto latest frame and write BGR24 to FFmpeg."""
        fallback_attempted = False
        while not self._stop_event.is_set():
            with self._slot_cond:
                while self._pending_item is None and not self._stop_event.is_set():
                    self._slot_cond.wait(timeout=0.2)
                if self._stop_event.is_set():
                    break
                item = self._pending_item
                self._pending_item = None

            if item is None:
                continue

            frame_bgr, persons = item
            if (
                frame_bgr.shape[1] != self.config.width
                or frame_bgr.shape[0] != self.config.height
            ):
                frame_bgr = cv2.resize(
                    frame_bgr,
                    (self.config.width, self.config.height),
                    interpolation=cv2.INTER_LINEAR,
                )

            t0 = time.perf_counter()
            self._renderer.render_tracks(frame_bgr, persons)
            self._render_times_ms.append((time.perf_counter() - t0) * 1000.0)

            proc = self._proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                if self._stop_event.is_set():
                    break
                if self._encoder_name == "h264_nvenc" and not fallback_attempted:
                    fallback_attempted = True
                    logger.warning(
                        f"NvencPublisher({self.camera_id}): h264_nvenc pipe lost, failing over to libx264"
                    )
                    self._close_proc()
                    if not self._spawn_ffmpeg(use_nvenc=False):
                        break
                    proc = self._proc
                else:
                    break

            try:
                proc.stdin.write(frame_bgr.tobytes())
                proc.stdin.flush()
                self._frames_published += 1
            except (BrokenPipeError, OSError, ValueError) as exc:
                if self._stop_event.is_set():
                    break
                tail = " | ".join(self._stderr_tail)
                logger.warning(f"NvencPublisher({self.camera_id}): FFmpeg write failed ({exc}): {tail}")
                if self._encoder_name == "h264_nvenc" and not fallback_attempted:
                    fallback_attempted = True
                    self._close_proc()
                    if self._spawn_ffmpeg(use_nvenc=False):
                        continue
                break

        self._active = False

    def stop(self) -> None:
        """Terminate FFmpeg publisher cleanly so MediaMTX drops ``live/{cam_id}_ai`` immediately."""
        with self._lifecycle_lock:
            self._stop_event.set()
            self._active = False
            with self._slot_cond:
                self._pending_item = None
                self._slot_cond.notify_all()

            self._close_proc()
            if self._writer_thread is not None and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=2.0)
            self._writer_thread = None
            logger.info(f"NvencPublisher({self.camera_id}): Stopped ({self.ai_stream_path})")
