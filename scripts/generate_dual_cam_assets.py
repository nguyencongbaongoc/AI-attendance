"""
Gate 2: Generate realistic dual-camera 4K 30FPS offline test videos
for end-to-end MediaMTX -> RTSP -> NVDEC -> TensorRT -> Tracker -> CrossingEngine -> WebSocket -> HLS proof.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import cv2
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"


def _composite_subject(
    bg: np.ndarray,
    subject: np.ndarray,
    cx: int,
    cy: int,
) -> np.ndarray:
    """Alpha-feather composite subject centered at (cx, cy) onto 4K background."""
    frame = bg.copy()
    bh, bw = frame.shape[:2]
    sh, sw = subject.shape[:2]

    x1 = max(0, cx - sw // 2)
    y1 = max(0, cy - sh // 2)
    x2 = min(bw, x1 + sw)
    y2 = min(bh, y1 + sh)

    sx1 = max(0, (sw // 2) - cx) if cx - sw // 2 < 0 else 0
    sy1 = max(0, (sh // 2) - cy) if cy - sh // 2 < 0 else 0
    sx2 = sx1 + (x2 - x1)
    sy2 = sy1 + (y2 - y1)

    if x2 <= x1 or y2 <= y1:
        return frame

    # Soft elliptical edge mask so the composited person blends naturally
    mask = np.zeros((sh, sw), dtype=np.float32)
    cv2.ellipse(
        mask,
        (sw // 2, sh // 2),
        (int(sw * 0.44), int(sh * 0.46)),
        0,
        0,
        360,
        1.0,
        -1,
    )
    mask = cv2.GaussianBlur(mask, (51, 51), 15)
    alpha = mask[sy1:sy2, sx1:sx2, None]

    roi = frame[y1:y2, x1:x2].astype(np.float32)
    patch = subject[sy1:sy2, sx1:sx2].astype(np.float32)
    blended = roi * (1.0 - alpha) + patch * alpha
    frame[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
    return frame


def _encode_h264(raw_path: pathlib.Path, out_path: pathlib.Path, fps: int = 30) -> None:
    """Re-encode OpenCV mp4v to standard H.264 baseline/main for MediaMTX + NVDEC compatibility."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg H.264 encode failed: {proc.stderr[-500:]}")
    raw_path.unlink(missing_ok=True)


def generate_videos() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    cam1_src = cv2.imread(str(ROOT / "cam1_frame.jpg"))
    cam1_bg = cv2.imread(str(ROOT / "cam1_live.jpg"))
    cam2_bg = cv2.imread(str(ROOT / "cam2_frame.jpg"))

    if cam1_src is None or cam1_bg is None or cam2_bg is None:
        raise FileNotFoundError("Required local 4K assets (cam1_frame.jpg, cam1_live.jpg, cam2_frame.jpg) not found.")

    # Extract real person from cam1_frame.jpg (YOLO-verified bbox: [1033, 102, 3831, 2138])
    person_crop = cam1_src[100:2130, 1030:3820]
    subj1 = cv2.resize(person_crop, (960, 720), interpolation=cv2.INTER_AREA)

    # Create distinct Subject 2 (mirrored + subtle cool tint)
    subj2 = cv2.flip(subj1, 1)
    subj2 = np.clip(subj2.astype(np.float32) * np.array([1.05, 0.98, 0.92]), 0, 255).astype(np.uint8)

    width, height, fps, total_frames = 3840, 2160, 30, 300
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # 1. Generate sim_cam1.mp4: Subject 1 walks IN (y: 1100 -> 1800) and pauses
    raw_cam1 = ARTIFACTS / "_raw_sim_cam1.mp4"
    out_cam1 = ARTIFACTS / "sim_cam1.mp4"
    writer1 = cv2.VideoWriter(str(raw_cam1), fourcc, fps, (width, height))
    for i in range(total_frames):
        if i < 45:
            cx, cy = 1920, 1100
        elif i < 180:
            t = (i - 45) / (180 - 45)
            cx = int(1920 + 120 * np.sin(t * np.pi))
            cy = int(1100 + t * (1800 - 1100))
        else:
            cx, cy = 1920, 1800
        frame = _composite_subject(cam1_bg, subj1, cx, cy)
        writer1.write(frame)
    writer1.release()
    _encode_h264(raw_cam1, out_cam1, fps)
    print(f"Generated {out_cam1} ({out_cam1.stat().st_size / (1024*1024):.2f} MB)")

    # 2. Generate sim_cam2.mp4: Subject 2 walks IN (y: 1100 -> 1800), pauses, then walks OUT (y: 1800 -> 1100)
    raw_cam2 = ARTIFACTS / "_raw_sim_cam2.mp4"
    out_cam2 = ARTIFACTS / "sim_cam2.mp4"
    writer2 = cv2.VideoWriter(str(raw_cam2), fourcc, fps, (width, height))
    for i in range(total_frames):
        if i < 45:
            cx, cy = 1700, 1100
        elif i < 165:
            t = (i - 45) / (165 - 45)
            cx = int(1700 + t * 400)
            cy = int(1100 + t * (1800 - 1100))
        elif i < 210:
            cx, cy = 2100, 1800
        else:
            t = (i - 210) / (total_frames - 210)
            cx = int(2100 - t * 200)
            cy = int(1800 - t * (1800 - 1100))
        frame = _composite_subject(cam2_bg, subj2, cx, cy)
        writer2.write(frame)
    writer2.release()
    _encode_h264(raw_cam2, out_cam2, fps)
    print(f"Generated {out_cam2} ({out_cam2.stat().st_size / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    generate_videos()
    sys.exit(0)
