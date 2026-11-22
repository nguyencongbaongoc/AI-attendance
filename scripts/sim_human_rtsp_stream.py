"""
STREAM 1: Simulated Human Video & RTSP Publisher (100% Camera-Free).

1. Generates photorealistic human-in-motion H.264 videos:
   - artifacts/sim_human_cam1.mp4 (Subject A: Nguyen Cong Bao Ngoc crossing cam1 line IN -> OUT)
   - artifacts/sim_human_cam2.mp4 (Subject B: Tran Minh Quan crossing cam2 line IN & OUT)
2. Verifies offline via YOLOPersonDetector + SCRFDDetector (bbox + 5 landmarks).
3. Publishes continuous RTSP loops via MediaMTX + dual FFmpeg publishers.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
MEDIAMTX_EXE = ROOT / "mediamtx" / "mediamtx.exe"
MEDIAMTX_CFG = ROOT / "mediamtx" / "mediamtx.yml"


def _build_subjects() -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build bright lobby/classroom backgrounds and Subject A & Subject B textures."""
    cam1_src = cv2.imread(str(ROOT / "cam1_frame.jpg"))
    cam1_live = cv2.imread(str(ROOT / "cam1_live.jpg"))
    face_b_raw = cv2.imread(str(ROOT / "realistic_test_face.jpg"))

    if cam1_src is None or cam1_live is None or face_b_raw is None:
        raise FileNotFoundError(
            "Required local assets (cam1_frame.jpg, cam1_live.jpg, realistic_test_face.jpg) not found."
        )

    # Bright, realistic school lobby/classroom backgrounds (1920x1080)
    bg_cam1 = cv2.resize(
        cv2.convertScaleAbs(cv2.GaussianBlur(cam1_live, (45, 45), 15), alpha=1.2, beta=40),
        (1920, 1080),
        interpolation=cv2.INTER_AREA,
    )
    bg_cam2 = cv2.convertScaleAbs(bg_cam1, alpha=0.95, beta=15)
    bg_cam2[:, :, 0] = np.clip(bg_cam2[:, :, 0].astype(np.int32) + 14, 0, 255).astype(np.uint8)

    # Subject A (Nguyen Cong Bao Ngoc): real human from cam1_frame.jpg (1000x750)
    subj_a = cv2.resize(cam1_src[100:2130, 1030:3820], (1000, 750), interpolation=cv2.INTER_AREA)

    # Subject B (Tran Minh Quan): distinct face + green-tinted shirt (distinct in both face & body ReID)
    subj_b = subj_a.copy()
    subj_b[490:, :, 1] = np.clip(subj_b[490:, :, 1].astype(np.int32) + 40, 0, 255).astype(np.uint8)
    subj_b[490:, :, 0] = np.clip(subj_b[490:, :, 0].astype(np.int32) - 30, 0, 255).astype(np.uint8)
    face_b_crop = face_b_raw[60:430, 170:490]
    fb_res = cv2.resize(face_b_crop, (310, 360), interpolation=cv2.INTER_AREA)
    m_fb = np.zeros((360, 310), dtype=np.float32)
    cv2.ellipse(m_fb, (155, 180), (120, 145), 0, 0, 360, 1.0, -1)
    m_fb = cv2.GaussianBlur(m_fb, (31, 31), 9)[:, :, None]
    roi_b = subj_b[110:470, 370:680].astype(np.float32)
    subj_b[110:470, 370:680] = np.clip(
        roi_b * (1.0 - m_fb) + fb_res.astype(np.float32) * m_fb, 0, 255
    ).astype(np.uint8)

    return bg_cam1, bg_cam2, subj_a, subj_b


def _composite_subject(bg: np.ndarray, subject: np.ndarray, cx: int, cy: int) -> np.ndarray:
    """Alpha-feather composite subject centered at (cx, cy) onto 3840x2160 background."""
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

    mask = np.zeros((sh, sw), dtype=np.float32)
    cv2.ellipse(mask, (sw // 2, sh // 2), (int(sw * 0.47), int(sh * 0.48)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (41, 41), 12)
    alpha = mask[sy1:sy2, sx1:sx2, None]

    roi = frame[y1:y2, x1:x2].astype(np.float32)
    patch = subject[sy1:sy2, sx1:sx2].astype(np.float32)
    frame[y1:y2, x1:x2] = np.clip(roi * (1.0 - alpha) + patch * alpha, 0, 255).astype(np.uint8)
    return frame


def _encode_h264_annexb(raw_path: pathlib.Path, out_path: pathlib.Path, fps: int = 30) -> None:
    """Encode raw video to H.264 with regular keyframes and Annex-B compatibility for MediaMTX + NVDEC."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg H.264 encode failed: {proc.stderr[-600:]}")
    raw_path.unlink(missing_ok=True)


def generate_human_videos() -> Dict[str, pathlib.Path]:
    """Generate artifacts/sim_human_cam1.mp4 and artifacts/sim_human_cam2.mp4."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    bg_cam1, bg_cam2, subj_a, subj_b = _build_subjects()

    width, height, fps, total_frames = 1920, 1080, 30, 300
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # 1. sim_human_cam1.mp4: Subject A walks IN (cy: 380 -> 760), pauses, then walks OUT (cy: 760 -> 380) seamlessly
    raw_cam1 = ARTIFACTS / "_raw_sim_human_cam1.mp4"
    out_cam1 = ARTIFACTS / "sim_human_cam1.mp4"
    writer1 = cv2.VideoWriter(str(raw_cam1), fourcc, fps, (width, height))
    for i in range(total_frames):
        if i < 30:
            cx, cy = 960, 380
        elif i < 130:
            t = (i - 30) / (130 - 30)
            cx = int(960 + 40 * np.sin(t * np.pi))
            cy = int(380 + t * (760 - 380))
        elif i < 170:
            cx, cy = 960, 760
        elif i < 270:
            t = (i - 170) / (270 - 170)
            cx = int(960 - 40 * np.sin(t * np.pi))
            cy = int(760 - t * (760 - 380))
        else:
            cx, cy = 960, 380
        writer1.write(_composite_subject(bg_cam1, subj_a, cx, cy))
    writer1.release()
    _encode_h264_annexb(raw_cam1, out_cam1, fps)
    print(f"[STREAM 1] Generated {out_cam1} ({out_cam1.stat().st_size / (1024*1024):.2f} MB)")

    # 2. sim_human_cam2.mp4: Subject B walks IN (cy: 380 -> 760), pauses, then walks OUT (cy: 760 -> 380) seamlessly
    raw_cam2 = ARTIFACTS / "_raw_sim_human_cam2.mp4"
    out_cam2 = ARTIFACTS / "sim_human_cam2.mp4"
    writer2 = cv2.VideoWriter(str(raw_cam2), fourcc, fps, (width, height))
    for i in range(total_frames):
        if i < 30:
            cx, cy = 910, 380
        elif i < 130:
            t = (i - 30) / (130 - 30)
            cx = int(910 + t * 90)
            cy = int(380 + t * (760 - 380))
        elif i < 170:
            cx, cy = 1000, 760
        elif i < 270:
            t = (i - 170) / (270 - 170)
            cx = int(1000 - t * 90)
            cy = int(760 - t * (760 - 380))
        else:
            cx, cy = 910, 380
        writer2.write(_composite_subject(bg_cam2, subj_b, cx, cy))
    writer2.release()
    _encode_h264_annexb(raw_cam2, out_cam2, fps)
    print(f"[STREAM 1] Generated {out_cam2} ({out_cam2.stat().st_size / (1024*1024):.2f} MB)")

    return {"cam1": out_cam1, "cam2": out_cam2}


def probe_generated_videos(video_paths: Dict[str, pathlib.Path]) -> Dict[str, Any]:
    """Verify YOLOPersonDetector and SCRFDDetector detect valid persons & faces + 5 landmarks."""
    from pipeline_engine.inference import create_yolo_detector, create_scrfd_detector
    from pipeline_engine.memory.gpu_frame import GPUFrame, CUDAContext, bgr_to_nv12_cuda

    yolo_path = (
        "models/yolo/yolo11n_fp16.engine"
        if (ROOT / "models/yolo/yolo11n_fp16.engine").exists()
        else "models/yolo/yolo11n.onnx"
    )
    yolo = create_yolo_detector(str(ROOT / yolo_path))
    scrfd = create_scrfd_detector(str(ROOT / "models/scrfd/scrfd_10g_bnkps_fp16.engine"))
    assert yolo.initialize(), "Failed to initialize YOLOPersonDetector"
    assert scrfd.initialize(), "Failed to initialize SCRFDDetector"

    ctx = CUDAContext.current(0)
    results: Dict[str, Any] = {}

    for cam, vpath in video_paths.items():
        cap = cv2.VideoCapture(str(vpath))
        assert cap.isOpened(), f"Failed to open {vpath}"
        # Sample frame 15 (early) and frame 100 (mid-walk)
        person_hits = 0
        face_hits = 0
        sample_info = {}
        for f_idx in (15, 100):
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ok, frame = cap.read()
            assert ok and frame is not None, f"Failed to read frame {f_idx} from {vpath}"
            h, w = frame.shape[:2]
            t = torch.from_numpy(frame).cuda()
            y, uv = bgr_to_nv12_cuda(t)
            gf = GPUFrame(
                camera_id=cam,
                frame_id=f_idx,
                width=w,
                height=h,
                cuda_context=ctx,
                y_tensor=y,
                uv_tensor=uv,
            )
            p_dets = yolo.detect(gf)
            f_dets = scrfd.detect(gf)
            if p_dets:
                person_hits += 1
            if f_dets and len(f_dets[0].landmarks5) == 5:
                face_hits += 1
            sample_info[f"frame_{f_idx}"] = {
                "yolo_count": len(p_dets),
                "yolo_conf": round(p_dets[0].confidence, 3) if p_dets else 0.0,
                "scrfd_count": len(f_dets),
                "scrfd_conf": round(f_dets[0].confidence, 3) if f_dets else 0.0,
                "landmarks5": len(f_dets[0].landmarks5) if f_dets else 0,
            }
        cap.release()
        assert person_hits > 0, f"{cam}: YOLOPersonDetector found 0 persons in probed frames!"
        assert face_hits > 0, f"{cam}: SCRFDDetector found 0 faces with 5 landmarks in probed frames!"
        results[cam] = sample_info
        print(f"[STREAM 1 PROBE] {cam}: {sample_info}")

    return results


class RTSPSimPublisher:
    """Manages MediaMTX and dual FFmpeg RTSP publishers for cam1 & cam2."""

    def __init__(self, cam1_mp4: pathlib.Path, cam2_mp4: pathlib.Path, log_dir: pathlib.Path):
        self.cam1_mp4 = cam1_mp4
        self.cam2_mp4 = cam2_mp4
        self.log_dir = log_dir
        self.mediamtx_proc: Optional[subprocess.Popen] = None
        self.ffmpeg1_proc: Optional[subprocess.Popen] = None
        self.ffmpeg2_proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.mediamtx_proc = subprocess.Popen(
            [str(MEDIAMTX_EXE), str(MEDIAMTX_CFG)],
            cwd=str(ROOT),
            stdout=open(self.log_dir / "mediamtx.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        time.sleep(1.5)

        self.ffmpeg1_proc = subprocess.Popen(
            [
                "ffmpeg",
                "-re",
                "-stream_loop",
                "-1",
                "-i",
                str(self.cam1_mp4),
                "-c",
                "copy",
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                "rtsp://127.0.0.1:8554/live/cam1",
            ],
            stdout=open(self.log_dir / "ffmpeg_cam1.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.ffmpeg2_proc = subprocess.Popen(
            [
                "ffmpeg",
                "-re",
                "-stream_loop",
                "-1",
                "-i",
                str(self.cam2_mp4),
                "-c",
                "copy",
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                "rtsp://127.0.0.1:8554/live/cam2",
            ],
            stdout=open(self.log_dir / "ffmpeg_cam2.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        for proc in (self.ffmpeg1_proc, self.ffmpeg2_proc, self.mediamtx_proc):
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                    except Exception:
                        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream 1: Simulated Human Video & RTSP Publisher")
    parser.add_argument("--skip-generate", action="store_true", help="Reuse existing sim_human_cam*.mp4")
    parser.add_argument("--publish", action="store_true", help="Keep MediaMTX + FFmpeg RTSP running until Ctrl+C")
    args = parser.parse_args()

    cam1_mp4 = ARTIFACTS / "sim_human_cam1.mp4"
    cam2_mp4 = ARTIFACTS / "sim_human_cam2.mp4"
    if not args.skip_generate or not (cam1_mp4.exists() and cam2_mp4.exists()):
        videos = generate_human_videos()
    else:
        videos = {"cam1": cam1_mp4, "cam2": cam2_mp4}

    probe_generated_videos(videos)

    if args.publish:
        pub = RTSPSimPublisher(videos["cam1"], videos["cam2"], ARTIFACTS / "sim_logs")
        pub.start()
        print("[STREAM 1] Publishing rtsp://127.0.0.1:8554/live/cam1 & cam2 (Ctrl+C to stop)...")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            pub.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
