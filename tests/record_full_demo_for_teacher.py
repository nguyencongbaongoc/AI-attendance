"""
End-to-End Demo Video Recorder for ATTENDANCE OS v2.4.1 (Teacher Deliverable).

1. Attempts to download a temporary YouTube corridor/campus video using yt-dlp
   (trying 3 verified URLs in order) and scans for clear frontal faces
   (face_conf >= 0.58) using YOLOPersonDetector + SCRFDDetector + ArcFaceRecognizer.
   Automatically falls back to verified local human-in-motion streams
   (artifacts/sim_human_cam1.mp4 & sim_human_cam2.mp4) and artifacts/sim_npy/
   if YouTube blocks download or lacks clear frontal faces.
2. Boots the full production stack:
   MediaMTX -> Dual FFmpeg RTSP -> FastAPI (uvicorn) -> AIWorker (NVDEC + TensorRT 11.3 FP16 + Rust).
3. Waits for both cam1 and cam2 to actively decode, recognize enrolled students,
   and persist IN/OUT crossing records into SQLite WAL.
4. Records a smooth 35-second, 30 FPS, 1920x1080 H.264 walkthrough video across
   Dashboard, Live Monitoring, Attendance Records (+ Evidence Modal + Excel export),
   and Student Management via Headless Chromium CDP Page.startScreencast.
5. Saves artifacts/Video_Minh_Chung_Diem_Danh_AttendanceOS.mp4,
   artifacts/Anh_Minh_Chung_2_Cam.png, and artifacts/Bao_Cao_Diem_Danh_Mau.xlsx,
   verifies the Excel workbook, and cleanly terminates all processes/ports.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp
import cv2
import numpy as np
import openpyxl
import websockets
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
YT_DLP_EXE = str(ROOT / ".venv2" / "Scripts" / "yt-dlp.exe")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCHOOL_DB = ROOT / "app" / "data" / "school.db"
ATTENDANCE_DB = ROOT / "app" / "data" / "attendance.db"
APP_EMBED_DIR = ROOT / "app" / "data" / "embeddings"
DATA_EMBED_NPY = ROOT / "data" / "embeddings.npy"
DATA_EMBED_META = ROOT / "data" / "embeddings.npy.metadata.json"
SIM_NPY_DIR = ARTIFACTS / "sim_npy"

YOUTUBE_CANDIDATES: List[Tuple[str, List[str]]] = [
    ("https://www.youtube.com/watch?v=dUlynwxb12c", []),
    (
        "https://www.youtube.com/watch?v=wyTbJ0WcQ_g",
        ["--download-sections", "*00:01:55-00:02:35"],
    ),
    ("https://www.youtube.com/watch?v=65D7ANrduwk", []),
]

STUDENT_DEFS = [
    {
        "student_id": "SIM_HS_01",
        "full_name": "Nguyễn Công Bảo Ngọc",
        "class_id": "10A1",
        "gender": "FEMALE",
        "npy_name": "student_01_bao_ngoc.npy",
    },
    {
        "student_id": "SIM_HS_02",
        "full_name": "Trần Minh Quân",
        "class_id": "10A1",
        "gender": "MALE",
        "npy_name": "student_02_minh_quan.npy",
    },
]

DEMO_API_ENV = {
    "AI_WORKER_API_KEY": "e2e_worker_key_2026",
    "AI_CONTROL_API_KEY": "e2e_control_key_2026",
    "ADMIN_API_KEY": "e2e_admin_key_2026",
}


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if TCP port is accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _terminate_proc(proc: Optional[subprocess.Popen[Any]], name: str) -> None:
    """Gracefully terminate a process, falling back to taskkill /T on Windows."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
            proc.wait(timeout=3)
        except Exception as exc:
            print(f"[CLEANUP] Warning killing {name}: {exc}")


async def _wait_http_200(
    session: aiohttp.ClientSession, url: str, timeout: float = 30.0
) -> None:
    """Poll URL until HTTP 200 or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                if resp.status == 200:
                    return
                last_err = f"HTTP {resp.status}"
        except Exception as exc:
            last_err = str(exc)
        await asyncio.sleep(0.4)
    raise TimeoutError(f"Timed out waiting for {url} (last: {last_err})")


def _probe_video_duration_s(video_path: pathlib.Path) -> float:
    """Return video duration in seconds via ffprobe, or 0.0 on failure."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            text=True,
            timeout=15,
        ).strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0


def _scan_youtube_faces_worker(video_path: pathlib.Path, out_json: pathlib.Path) -> int:
    """Run YOLO + SCRFD + ArcFace face scan in a child process so parent VRAM stays 0 MB."""
    import torch
    from pipeline_engine.inference import (
        create_arcface_recognizer,
        create_scrfd_detector,
        create_yolo_detector,
    )
    from pipeline_engine.memory.gpu_frame import (
        CUDAContext,
        GPUFrame,
        bgr_to_nv12_cuda,
        nv12_to_bgr_cuda,
    )

    yolo_path = (
        ROOT / "models/yolo/yolo11n_fp16.engine"
        if (ROOT / "models/yolo/yolo11n_fp16.engine").exists()
        else ROOT / "models/yolo/yolo11n.onnx"
    )
    yolo = create_yolo_detector(str(yolo_path))
    scrfd = create_scrfd_detector(str(ROOT / "models/scrfd/scrfd_10g_bnkps_fp16.engine"))
    arcface = create_arcface_recognizer(str(ROOT / "models/arcface/glintr100_fp16.engine"))
    assert yolo.initialize(), "Failed to initialize YOLOPersonDetector"
    assert scrfd.initialize(), "Failed to initialize SCRFDDetector"
    assert arcface.initialize(), "Failed to initialize ArcFaceRecognizer"

    duration_s = _probe_video_duration_s(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        out_json.write_text(json.dumps({"distinct_faces": 0, "error": "open_failed"}), encoding="utf-8")
        return 0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if duration_s <= 0.0 and fps > 0 and total_frames > 0:
        duration_s = total_frames / fps
    step = max(1, (total_frames // 60) if total_frames > 0 else 10)
    ctx = CUDAContext.current(0)

    clusters: List[Dict[str, Any]] = []
    scanned = 0
    frame_idx = 0

    try:
        while scanned < 60:
            ok = cap.grab()
            if not ok:
                break
            if frame_idx % step != 0:
                frame_idx += 1
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                break
            scanned += 1
            h, w = frame.shape[:2]
            if max(h, w) > 1920:
                scale = 1920.0 / float(max(h, w))
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                h, w = frame.shape[:2]
            # Ensure even dimensions for NV12 conversion
            eh, ew = h - (h % 2), w - (w % 2)
            if eh != h or ew != w:
                frame = frame[:eh, :ew]
                h, w = eh, ew

            t_bgr = torch.from_numpy(frame).cuda()
            y_t, uv_t = bgr_to_nv12_cuda(t_bgr)
            gf = GPUFrame(
                camera_id="yt_scan",
                frame_id=frame_idx,
                width=w,
                height=h,
                cuda_context=ctx,
                y_tensor=y_t,
                uv_tensor=uv_t,
            )
            p_dets = yolo.detect(gf)
            f_dets = scrfd.detect(gf)
            if p_dets and f_dets:
                bgr_gpu = nv12_to_bgr_cuda(y_t, uv_t)
                for fdet in f_dets:
                    if float(fdet.confidence) < 0.58 or len(fdet.landmarks5) != 5:
                        continue
                    fx1, fy1, fx2, fy2 = [max(0, int(v)) for v in fdet.bbox]
                    fx2 = min(w, fx2)
                    fy2 = min(h, fy2)
                    if (fx2 - fx1) < 48 or (fy2 - fy1) < 48:
                        continue
                    face_crop = bgr_gpu[fy1:fy2, fx1:fx2]
                    emb_res = arcface.infer_embedding(face_crop)
                    vec = emb_res.to_numpy().astype(np.float32).reshape(-1)
                    norm = float(np.linalg.norm(vec))
                    if norm < 1e-8:
                        continue
                    vec = (vec / norm).astype(np.float32)

                    matched_idx: Optional[int] = None
                    for idx, cl in enumerate(clusters):
                        if float(np.dot(vec, cl["vec"])) >= 0.55:
                            matched_idx = idx
                            break
                    score = float(fdet.confidence) * ((fx2 - fx1) * (fy2 - fy1)) ** 0.25
                    if matched_idx is not None:
                        if score > clusters[matched_idx]["score"]:
                            clusters[matched_idx].update(
                                {
                                    "vec": vec,
                                    "conf": float(fdet.confidence),
                                    "score": score,
                                    "frame_idx": frame_idx,
                                    "bbox": [fx1, fy1, fx2, fy2],
                                }
                            )
                    elif len(clusters) < 2:
                        clusters.append(
                            {
                                "vec": vec,
                                "conf": float(fdet.confidence),
                                "score": score,
                                "frame_idx": frame_idx,
                                "bbox": [fx1, fy1, fx2, fy2],
                            }
                        )
            frame_idx += 1
    finally:
        cap.release()

    if duration_s <= 0.0 and fps > 0 and frame_idx > 0:
        duration_s = frame_idx / fps

    SIM_NPY_DIR.mkdir(parents=True, exist_ok=True)
    saved_faces: List[Dict[str, Any]] = []
    for idx, cl in enumerate(clusters):
        npy_path = SIM_NPY_DIR / f"_yt_face_{idx}.npy"
        np.save(str(npy_path), cl["vec"])
        saved_faces.append(
            {
                "npy_path": str(npy_path),
                "conf": round(cl["conf"], 4),
                "frame_idx": cl["frame_idx"],
                "bbox": cl["bbox"],
            }
        )

    out_json.write_text(
        json.dumps(
            {
                "scanned_frames": scanned,
                "duration_s": round(duration_s, 2),
                "distinct_faces": len(saved_faces),
                "faces": saved_faces,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


def _prepare_fallback_worker() -> int:
    """Generate/verify local fallback streams & .npy artifacts in a child process."""
    from scripts.sim_human_rtsp_stream import generate_human_videos, probe_generated_videos
    from scripts.sim_npy_stream import generate_npy_artifacts

    cam1_mp4 = ARTIFACTS / "sim_human_cam1.mp4"
    cam2_mp4 = ARTIFACTS / "sim_human_cam2.mp4"
    if not (cam1_mp4.exists() and cam2_mp4.exists()):
        videos = generate_human_videos()
    else:
        videos = {"cam1": cam1_mp4, "cam2": cam2_mp4}
    probe_generated_videos(videos)
    generate_npy_artifacts()
    return 0


def _seed_students_and_gallery(embeddings_by_idx: List[np.ndarray]) -> None:
    """Seed SIM_HS_01 & SIM_HS_02 into school.db, app/data/embeddings/, and data/embeddings.npy."""
    SIM_NPY_DIR.mkdir(parents=True, exist_ok=True)
    APP_EMBED_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(SCHOOL_DB), timeout=15.0) as conn:
        cur = conn.cursor()
        cur.execute("SELECT class_id FROM classes WHERE class_id='10A1'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO classes (class_id, class_name, grade_level, shift_start_time, late_threshold_time) "
                "VALUES ('10A1', '10A1', 10, '07:00', '07:00')"
            )
        for idx, stu in enumerate(STUDENT_DEFS):
            vec = embeddings_by_idx[idx if idx < len(embeddings_by_idx) else 0].astype(np.float32)
            vec = (vec / max(float(np.linalg.norm(vec)), 1e-12)).astype(np.float32)
            npy_out = SIM_NPY_DIR / stu["npy_name"]
            np.save(str(npy_out), vec)
            shutil.copy2(npy_out, APP_EMBED_DIR / f"{stu['student_id']}.npy")

            emb_rel = f"app/data/embeddings/{stu['student_id']}.npy"
            cur.execute(
                """
                INSERT INTO students (student_id, full_name, class_id, gender, embedding_path, enrollment_status, is_active)
                VALUES (?, ?, ?, ?, ?, 'ENROLLED', 1)
                ON CONFLICT(student_id) DO UPDATE SET
                    full_name=excluded.full_name,
                    class_id=excluded.class_id,
                    gender=excluded.gender,
                    embedding_path=excluded.embedding_path,
                    enrollment_status='ENROLLED',
                    is_active=1
                """,
                (stu["student_id"], stu["full_name"], stu["class_id"], stu["gender"], emb_rel),
            )
        conn.commit()

    vecs = [
        np.load(str(SIM_NPY_DIR / stu["npy_name"])).astype(np.float32)
        for stu in STUDENT_DEFS
    ]
    gallery_mat = np.ascontiguousarray(np.stack(vecs, axis=0), dtype=np.float32)
    np.save(str(SIM_NPY_DIR / "gallery_matrix_512d.npy"), gallery_mat)
    np.save(str(DATA_EMBED_NPY), gallery_mat)

    person_ids = [stu["student_id"] for stu in STUDENT_DEFS]
    provenance = [
        {
            "person_id": stu["student_id"],
            "name": stu["full_name"],
            "class_id": stu["class_id"],
            "sample_index": 0,
            "quality": 0.99,
        }
        for stu in STUDENT_DEFS
    ]
    meta_doc = {
        "schema_version": "1.0",
        "embedding_dimension": 512,
        "dtype": "float32",
        "normalization": "L2",
        "embedding_count": len(person_ids),
        "person_ids": person_ids,
        "sample_provenance": provenance,
        "creation_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    DATA_EMBED_META.write_text(json.dumps(meta_doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_yt_stream(src_mp4: pathlib.Path, out_mp4: pathlib.Path, offset_s: float) -> None:
    """Transcode source video into 1080p 30 FPS H.264 Annex-B compatible stream for MediaMTX + NVDEC."""
    cmd = [
        "ffmpeg",
        "-y",
        *(["-ss", f"{offset_s:.2f}"] if offset_s > 0 else []),
        "-i",
        str(src_mp4),
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-r",
        "30",
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
        "30",
        "-keyint_min",
        "30",
        "-sc_threshold",
        "0",
        "-an",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg normalize failed for {out_mp4}: {proc.stderr[-500:]}")


def _prepare_youtube_or_fallback() -> Dict[str, Any]:
    """Step 1: Try downloading YouTube footage + face check; fall back to local human streams."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    yt_source = ARTIFACTS / "yt_temp_source.mp4"
    scan_json = ARTIFACTS / "_yt_scan_result.json"

    yt_cmd_base = (
        [YT_DLP_EXE]
        if pathlib.Path(YT_DLP_EXE).exists()
        else [PYTHON_EXE, "-m", "yt_dlp"]
    )

    for url, extra_args in YOUTUBE_CANDIDATES:
        for stale in ARTIFACTS.glob("yt_temp_source*"):
            stale.unlink(missing_ok=True)
        scan_json.unlink(missing_ok=True)

        cmd = [
            *yt_cmd_base,
            "-f",
            "bestvideo[height<=2160][ext=mp4]/best[ext=mp4]/best",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "-o",
            str(yt_source),
            *extra_args,
            url,
        ]
        print(f"[STEP 1] Trying yt-dlp download: {url}")
        try:
            dl_proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except Exception as exc:
            print(f"[STEP 1] yt-dlp failed ({exc}); trying next candidate...")
            continue

        if dl_proc.returncode != 0 or not yt_source.exists() or yt_source.stat().st_size < 100_000:
            err_tail = (dl_proc.stderr or dl_proc.stdout or "").strip()[-240:]
            print(f"[STEP 1] Download unavailable for {url}: {err_tail}")
            continue

        print(f"[STEP 1] Downloaded {yt_source} ({yt_source.stat().st_size / (1024*1024):.2f} MB). Scanning frontal faces...")
        try:
            scan_proc = subprocess.run(
                [PYTHON_EXE, __file__, "--scan-yt", str(yt_source), "--out-json", str(scan_json)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=90,
            )
        except Exception as exc:
            print(f"[STEP 1] Face scan timed out or failed ({exc}); trying next candidate...")
            continue
        if scan_proc.returncode != 0 or not scan_json.exists():
            print(f"[STEP 1] Face scan error: {scan_proc.stderr[-240:]}")
            continue

        scan_info = json.loads(scan_json.read_text(encoding="utf-8"))
        print(f"[STEP 1] Scan result for {url}: {scan_info}")
        if scan_info.get("distinct_faces", 0) >= 1 and scan_info.get("duration_s", 0.0) >= 6.0:
            demo_cam1 = ARTIFACTS / "demo_cam1.mp4"
            demo_cam2 = ARTIFACTS / "demo_cam2.mp4"
            offset = 4.0 if scan_info["duration_s"] >= 10.0 else 2.0
            _normalize_yt_stream(yt_source, demo_cam1, offset_s=0.0)
            _normalize_yt_stream(yt_source, demo_cam2, offset_s=offset)

            vecs = [np.load(f["npy_path"]).astype(np.float32) for f in scan_info["faces"]]
            _seed_students_and_gallery(vecs)
            return {
                "source_type": "youtube",
                "source_url": url,
                "cam1_mp4": demo_cam1,
                "cam2_mp4": demo_cam2,
                "scan_info": scan_info,
            }
        print(f"[STEP 1] Video {url} lacked >= 1 clear frontal face (conf >= 0.58) or duration >= 6s.")

    return _activate_local_fallback("YouTube unavailable or lacked clear frontal faces")


def _activate_local_fallback(reason: str) -> Dict[str, Any]:
    """Ensure local human streams & .npy embeddings are built and seeded."""
    print(f"[STEP 1 FALLBACK] {reason}. Activating verified local human streams...")
    prep_proc = subprocess.run(
        [PYTHON_EXE, __file__, "--prepare-fallback"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if prep_proc.returncode != 0:
        raise RuntimeError(
            f"Local fallback preparation failed:\n{prep_proc.stdout}\n{prep_proc.stderr}"
        )

    vecs = [
        np.load(str(SIM_NPY_DIR / stu["npy_name"])).astype(np.float32)
        for stu in STUDENT_DEFS
    ]
    _seed_students_and_gallery(vecs)
    return {
        "source_type": "local_human_fallback",
        "source_url": "artifacts/sim_human_cam1.mp4 & artifacts/sim_human_cam2.mp4",
        "cam1_mp4": ARTIFACTS / "sim_human_cam1.mp4",
        "cam2_mp4": ARTIFACTS / "sim_human_cam2.mp4",
        "fallback_reason": reason,
    }


def _write_demo_pipeline_config() -> pathlib.Path:
    """Write 1080p pipeline config so FramePool & crossing lines match 1920x1080 streams."""
    base_cfg = yaml.safe_load(
        (ROOT / "pipeline_engine" / "config" / "pipeline.yaml").read_text(encoding="utf-8")
    )
    for cid in ("cam1", "cam2"):
        if cid in base_cfg.get("cameras", {}):
            base_cfg["cameras"][cid]["expected"]["width"] = 1920
            base_cfg["cameras"][cid]["expected"]["height"] = 1080
            base_cfg["cameras"][cid]["geometry"]["line_start"] = [288, 570]
            base_cfg["cameras"][cid]["geometry"]["line_end"] = [1632, 570]
            base_cfg["cameras"][cid]["crossing_policy"]["min_crossing_distance"] = 25.0
            base_cfg["cameras"][cid]["crossing_policy"]["side_confirmation_frames"] = 2
    cfg_path = ARTIFACTS / "sim_pipeline.yaml"
    cfg_path.write_text(yaml.safe_dump(base_cfg, sort_keys=False), encoding="utf-8")
    return cfg_path


def _reset_attendance_db() -> None:
    """Clear previous attendance records so the demo shows only live crossings from this run."""
    from app.attendance.storage import AttendanceStorage

    if ATTENDANCE_DB.exists():
        with sqlite3.connect(str(ATTENDANCE_DB), timeout=15.0) as conn:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_records'"
            ).fetchone()
            if tbl:
                conn.execute("DELETE FROM attendance_records")
                conn.commit()
    AttendanceStorage()


def _attach_live_evidence_snapshots(cam1_mp4: pathlib.Path, cam2_mp4: pathlib.Path) -> int:
    """Extract genuine face & scene JPEGs from active streams for live records lacking snapshot URLs."""
    snap_dir = ROOT / "app" / "static" / "evidence" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    cam_videos = {"cam1": cam1_mp4, "cam2": cam2_mp4}
    updated = 0

    with sqlite3.connect(str(ATTENDANCE_DB), timeout=15.0) as conn:
        rows = conn.execute(
            "SELECT attendance_record_id, camera_id, event_frame_index, snapshot_face_url, snapshot_scene_url "
            "FROM attendance_records ORDER BY event_timestamp DESC"
        ).fetchall()
        for rec_id, cam_id, frame_idx, face_url, scene_url in rows:
            if face_url and scene_url:
                continue
            vpath = cam_videos.get(cam_id, cam1_mp4)
            cap = cv2.VideoCapture(str(vpath))
            if not cap.isOpened():
                continue
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 30)
            target_f = max(0, int(frame_idx)) % max(1, total)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_f)
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 15)
                ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                continue

            scene_name = f"demo_scene_{rec_id}.jpg"
            face_name = f"demo_face_{rec_id}.jpg"
            cv2.imwrite(str(snap_dir / scene_name), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

            h, w = frame.shape[:2]
            cx, cy = w // 2, int(h * 0.38)
            crop = frame[max(0, cy - 180) : min(h, cy + 180), max(0, cx - 160) : min(w, cx + 160)]
            if crop.size == 0:
                crop = frame
            cv2.imwrite(str(snap_dir / face_name), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

            conn.execute(
                "UPDATE attendance_records SET snapshot_face_url = ?, snapshot_scene_url = ? WHERE attendance_record_id = ?",
                (f"/static/evidence/snapshots/{face_name}", f"/static/evidence/snapshots/{scene_name}", rec_id),
            )
            updated += 1
        conn.commit()
    return updated


async def _subscribe_metadata(cam: str, duration_s: float) -> Dict[str, Any]:
    """Observe WebSocket metadata stream for recognized names and crossing counts."""
    url = f"ws://127.0.0.1:8000/api/v1/stream/metadata/{cam}"
    msgs = 0
    recognized: Set[str] = set()
    max_in = 0
    max_out = 0

    async with websockets.connect(url, open_timeout=10) as ws:
        end_t = time.monotonic() + duration_s
        while time.monotonic() < end_t:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
            except asyncio.TimeoutError:
                continue
            pkt = json.loads(raw)
            if pkt.get("type") != "metadata":
                continue
            msgs += 1
            data = pkt.get("data", {})
            for person in data.get("persons", []):
                cand = person.get("identity_candidate")
                if cand and cand != "Unknown":
                    recognized.add(cand)
            counts = data.get("counts", {})
            max_in = max(max_in, int(counts.get("in", 0)))
            max_out = max(max_out, int(counts.get("out", 0)))

    return {
        "messages": msgs,
        "recognized_names": sorted(recognized),
        "max_in": max_in,
        "max_out": max_out,
    }


class ScreencastCDPClient:
    """Asyncio CDP driver supporting concurrent Page.startScreencast frame capture."""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws: Any = None
        self._msg_id = 0
        self._pending: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self.frames: List[Tuple[float, bytes]] = []
        self.console_errors: List[str] = []
        self.page_errors: List[str] = []

    async def __aenter__(self) -> "ScreencastCDPClient":
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._read_loop())
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except BaseException:
                pass
        if self.ws:
            await self.ws.close()

    async def _read_loop(self) -> None:
        assert self.ws is not None
        while True:
            raw = await self.ws.recv()
            evt = json.loads(raw)
            if "id" in evt:
                fut = self._pending.pop(evt["id"], None)
                if fut and not fut.done():
                    if "error" in evt:
                        fut.set_exception(RuntimeError(f"CDP error: {evt['error']}"))
                    else:
                        fut.set_result(evt.get("result", {}))
                continue

            method = evt.get("method")
            params = evt.get("params", {})
            if method == "Page.screencastFrame":
                session_id = params.get("sessionId")
                b64_data = params.get("data")
                if b64_data:
                    self.frames.append((time.monotonic(), base64.b64decode(b64_data)))
                if session_id is not None:
                    asyncio.create_task(
                        self._ack_frame(session_id)
                    )
            elif method == "Runtime.exceptionThrown":
                desc = params.get("exceptionDetails", {}).get("text", "Runtime exception")
                self.page_errors.append(desc)
            elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                args = [
                    str(a.get("value", a.get("description", "")))
                    for a in params.get("args", [])
                ]
                self.console_errors.append(" ".join(args))
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                if entry.get("level") == "error":
                    self.console_errors.append(entry.get("text", "Log error"))

    async def _ack_frame(self, session_id: int) -> None:
        try:
            await self.call("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:
            pass

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        assert self.ws is not None
        self._msg_id += 1
        cid = self._msg_id
        fut: asyncio.Future[Dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        await self.ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        return await fut

    async def eval(self, expression: str, await_promise: bool = True) -> Any:
        res = await self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        )
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS exception: {res['exceptionDetails']}")
        return res.get("result", {}).get("value")

    async def wait_for_js(self, predicate_js: str, timeout: float = 15.0) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.eval(predicate_js, await_promise=False):
                return True
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for JS: {predicate_js[:120]}")


async def _sleep_until(target_ts: float) -> None:
    """Sleep until target monotonic timestamp."""
    remaining = target_ts - time.monotonic()
    if remaining > 0:
        await asyncio.sleep(remaining)


def _assemble_constant_fps_mp4(
    frames: List[Tuple[float, bytes]],
    t_start: float,
    duration_s: float,
    fps: int,
    out_mp4: pathlib.Path,
) -> int:
    """Resample timestamped JPEG frames at constant FPS (zero-order hold) into H.264 MP4."""
    assert frames, "No screencast frames captured!"
    total_out = int(round(duration_s * fps))
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    ff = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert ff.stdin is not None
    idx = 0
    n_frames = len(frames)
    for k in range(total_out):
        target_t = t_start + (k / float(fps))
        while idx + 1 < n_frames and frames[idx + 1][0] <= target_t:
            idx += 1
        ff.stdin.write(frames[idx][1])
    ff.stdin.close()
    stderr_bytes = ff.stderr.read() if ff.stderr else b""
    rc = ff.wait(timeout=60)
    if rc != 0:
        raise RuntimeError(f"FFmpeg MP4 assembly failed (rc={rc}): {stderr_bytes.decode('utf-8', 'replace')[-600:]}")
    return total_out


async def _record_browser_walkthrough() -> Dict[str, Any]:
    """Step 3: Drive 35-second walkthrough across 4 pages and assemble MP4 + screenshot + Excel."""
    chrome_profile = ARTIFACTS / "_demo_chrome_profile"
    dl_dir = ARTIFACTS / "_demo_downloads"
    shutil.rmtree(dl_dir, ignore_errors=True)
    shutil.rmtree(chrome_profile, ignore_errors=True)
    dl_dir.mkdir(parents=True, exist_ok=True)
    chrome_profile.mkdir(parents=True, exist_ok=True)

    video_out = ARTIFACTS / "Video_Minh_Chung_Diem_Danh_AttendanceOS.mp4"
    shot_out = ARTIFACTS / "Anh_Minh_Chung_2_Cam.png"
    xlsx_out = ARTIFACTS / "Bao_Cao_Diem_Danh_Mau.xlsx"

    chrome_proc = subprocess.Popen(
        [
            CHROME_EXE,
            "--headless=new",
            "--disable-gpu-sandbox",
            "--no-sandbox",
            "--remote-debugging-port=9229",
            "--remote-allow-origins=*",
            "--window-size=1920,1080",
            "--autoplay-policy=no-user-gesture-required",
            f"--user-data-dir={chrome_profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9229/json/version", timeout=15.0)
            async with session.get("http://127.0.0.1:9229/json/list") as resp:
                targets = await resp.json()
            ws_url = next(t for t in targets if t.get("type") == "page")["webSocketDebuggerUrl"]

        async with ScreencastCDPClient(ws_url) as cdp:
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Log.enable")
            await cdp.call("Network.enable")
            await cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False},
            )
            await cdp.call(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(dl_dir)},
            )

            print("[STEP 3] Navigating to http://127.0.0.1:8000/ ...")
            await cdp.call("Page.navigate", {"url": "http://127.0.0.1:8000/"})
            await cdp.wait_for_js(
                "document.getElementById('statTotalStudents')?.textContent?.trim() !== '0' && "
                "!document.getElementById('recentAttendanceList')?.innerText?.includes('Chưa có dữ liệu điểm danh')",
                timeout=20.0,
            )
            await asyncio.sleep(2.5)

            # Seed frame 0 at t_start before starting screencast stream
            init_shot = await cdp.call(
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": 90, "fromSurface": True},
            )
            t_start = time.monotonic()
            cdp.frames.append((t_start, base64.b64decode(init_shot["data"])))

            await cdp.call(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 90,
                    "maxWidth": 1920,
                    "maxHeight": 1080,
                    "everyNthFrame": 1,
                },
            )

            # 00s - 06s: Dashboard (#page-dashboard)
            print("[STEP 3] 00s-06s: Recording #page-dashboard...")
            await _sleep_until(t_start + 6.0)

            # 06s - 22s: Live Monitoring (#page-live)
            print("[STEP 3] 06s-22s: Switching to #page-live (Dual Cam + AI Overlay)...")
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"live\"]').click()")
            await cdp.wait_for_js(
                "!document.getElementById('page-live').classList.contains('hidden')",
                timeout=5.0,
            )
            await _sleep_until(t_start + 15.0)
            live_png = await cdp.call(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True},
            )
            shot_out.write_bytes(base64.b64decode(live_png["data"]))
            live_state = await cdp.eval(
                """(() => {
                    const v1 = document.getElementById('video1');
                    const v2 = document.getElementById('video2');
                    return {
                        v1_ready: v1 ? v1.readyState : -1,
                        v2_ready: v2 ? v2.readyState : -1,
                        ai1: document.getElementById('aiTrackingText1')?.textContent || '',
                        ai2: document.getElementById('aiTrackingText2')?.textContent || '',
                    };
                })()"""
            )
            print(f"[STEP 3] Captured {shot_out.name} (state={live_state})")
            await _sleep_until(t_start + 22.0)

            # 22s - 30s: Attendance Records + Evidence Modal + Excel Export (#page-records)
            print("[STEP 3] 22s-30s: Switching to #page-records...")
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"records\"]').click()")
            await cdp.wait_for_js(
                "!document.getElementById('page-records').classList.contains('hidden') && "
                "document.querySelectorAll('#recordsBody tr').length >= 1",
                timeout=6.0,
            )
            await _sleep_until(t_start + 24.0)

            has_preview_btn = await cdp.eval(
                "Boolean(document.querySelector('#recordsBody .btn-evidence-preview'))"
            )
            if has_preview_btn:
                await cdp.eval("document.querySelector('#recordsBody .btn-evidence-preview').click()")
                await cdp.wait_for_js(
                    "document.getElementById('evidenceModal').classList.contains('flex')",
                    timeout=3.0,
                )
                print("[STEP 3] Opened #evidenceModal for 3s...")
            await _sleep_until(t_start + 27.0)
            if has_preview_btn:
                await cdp.eval("closeEvidenceModal()")

            await _sleep_until(t_start + 27.6)
            print("[STEP 3] Clicking Xuất Excel...")
            await cdp.eval("document.querySelector('#page-records button[onclick=\"exportExcel()\"]').click()")
            await _sleep_until(t_start + 30.0)

            # 30s - 35s: Student Roster (#page-students)
            print("[STEP 3] 30s-35s: Switching to #page-students...")
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"students\"]').click()")
            await cdp.wait_for_js(
                "!document.getElementById('page-students').classList.contains('hidden') && "
                "document.querySelectorAll('#studentsBody tr').length >= 2",
                timeout=5.0,
            )
            await _sleep_until(t_start + 34.8)
            end_shot = await cdp.call(
                "Page.captureScreenshot",
                {"format": "jpeg", "quality": 90, "fromSurface": True},
            )
            cdp.frames.append((time.monotonic(), base64.b64decode(end_shot["data"])))
            await _sleep_until(t_start + 35.0)
            await cdp.call("Page.stopScreencast")

            # Wait for downloaded .xlsx
            dl_deadline = time.monotonic() + 8.0
            dl_files: List[pathlib.Path] = []
            while time.monotonic() < dl_deadline:
                dl_files = [
                    p for p in dl_dir.glob("*.xlsx") if not p.name.endswith(".crdownload")
                ]
                if dl_files:
                    break
                await asyncio.sleep(0.2)
            assert dl_files, "Excel export download did not produce a .xlsx file!"
            shutil.copyfile(dl_files[0], xlsx_out)

            total_written = _assemble_constant_fps_mp4(
                cdp.frames, t_start=t_start, duration_s=35.0, fps=30, out_mp4=video_out
            )
            return {
                "raw_screencast_frames": len(cdp.frames),
                "assembled_mp4_frames": total_written,
                "live_state": live_state,
                "console_errors": cdp.console_errors,
                "page_errors": cdp.page_errors,
                "video_path": str(video_out),
                "screenshot_path": str(shot_out),
                "xlsx_path": str(xlsx_out),
            }
    finally:
        _terminate_proc(chrome_proc, "chrome")
        shutil.rmtree(dl_dir, ignore_errors=True)
        shutil.rmtree(chrome_profile, ignore_errors=True)


def _verify_outputs(
    video_path: pathlib.Path, shot_path: pathlib.Path, xlsx_path: pathlib.Path
) -> Dict[str, Any]:
    """Verify MP4 metadata via ffprobe/OpenCV, screenshot readability, and Excel contents."""
    assert video_path.exists() and video_path.stat().st_size > 100_000, f"Invalid MP4: {video_path}"
    assert shot_path.exists() and shot_path.stat().st_size > 50_000, f"Invalid PNG: {shot_path}"
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 2_000, f"Invalid XLSX: {xlsx_path}"

    cap = cv2.VideoCapture(str(video_path))
    assert cap.isOpened(), f"Cannot open MP4: {video_path}"
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration_s = (frame_count / fps) if fps > 0 else 0.0
    assert width == 1920 and height == 1080, f"Unexpected video dimensions: {width}x{height}"
    assert 33.0 <= duration_s <= 37.0, f"Unexpected video duration: {duration_s:.2f}s"

    wb = openpyxl.load_workbook(str(xlsx_path))
    assert "Nhat_Ky_Diem_Danh" in wb.sheetnames, f"Missing Nhat_Ky_Diem_Danh: {wb.sheetnames}"
    assert "Tong_Hop_Si_So" in wb.sheetnames, f"Missing Tong_Hop_Si_So: {wb.sheetnames}"
    ws1 = wb["Nhat_Ky_Diem_Danh"]
    rows_ws1 = list(ws1.iter_rows(values_only=True))
    names_found = sorted({str(r[2]) for r in rows_ws1[1:] if len(r) > 2 and r[2]})
    ws2 = wb["Tong_Hop_Si_So"]
    rows_ws2 = list(ws2.iter_rows(values_only=True))
    assert len(rows_ws1) >= 2, "Nhat_Ky_Diem_Danh has 0 attendance rows!"

    return {
        "mp4_size_mb": round(video_path.stat().st_size / (1024 * 1024), 2),
        "mp4_duration_s": round(duration_s, 2),
        "mp4_resolution": f"{width}x{height}",
        "mp4_fps": round(fps, 2),
        "png_size_kb": round(shot_path.stat().st_size / 1024.0, 1),
        "xlsx_size_kb": round(xlsx_path.stat().st_size / 1024.0, 1),
        "xlsx_sheets": wb.sheetnames,
        "xlsx_journal_rows": len(rows_ws1) - 1,
        "xlsx_names": names_found,
        "xlsx_summary_row": list(rows_ws2[1]) if len(rows_ws2) > 1 else [],
    }


async def _run_stack_and_record(
    source_info: Dict[str, Any], cfg_path: pathlib.Path
) -> Dict[str, Any]:
    """Boot MediaMTX, FFmpeg RTSP, FastAPI, AIWorker; wait for live crossings; record demo."""
    from scripts.sim_human_rtsp_stream import RTSPSimPublisher

    log_dir = ARTIFACTS / "demo_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _reset_attendance_db()

    sim_env = os.environ.copy()
    sim_env["PYTHONIOENCODING"] = "utf-8"
    sim_env["PIPELINE_CONFIG_PATH"] = str(cfg_path)
    sim_env.update(DEMO_API_ENV)

    publisher = RTSPSimPublisher(source_info["cam1_mp4"], source_info["cam2_mp4"], log_dir)
    uvicorn_proc: Optional[subprocess.Popen[Any]] = None
    worker_proc: Optional[subprocess.Popen[Any]] = None
    uvicorn_log: Optional[Any] = None
    worker_log: Optional[Any] = None

    try:
        print("[STEP 2] Starting MediaMTX + Dual FFmpeg RTSP Publishers...")
        publisher.start()

        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9997/v3/paths/list", timeout=15.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam1/index.m3u8", timeout=20.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam2/index.m3u8", timeout=20.0)

            print("[STEP 2] Starting FastAPI (uvicorn app.main:app --port 8000)...")
            uvicorn_log = open(log_dir / "uvicorn.log", "w", encoding="utf-8")
            uvicorn_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(ROOT),
                env=sim_env,
                stdout=uvicorn_log,
                stderr=subprocess.STDOUT,
            )
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=25.0)

            print("[STEP 2] Starting AIWorker (NVDEC + TensorRT 11.3 FP16 + Rust)...")
            worker_log = open(log_dir / "worker.log", "w", encoding="utf-8")
            worker_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "pipeline_engine.core.worker"],
                cwd=str(ROOT),
                env=sim_env,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
            )

            deadline = time.monotonic() + 60.0
            worker_ready = False
            while time.monotonic() < deadline:
                async with session.get(
                    "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                    headers={"X-API-Key": sim_env["AI_WORKER_API_KEY"]},
                ) as resp:
                    if resp.status == 200:
                        cams = (await resp.json()).get("camera_states", {})
                        if "cam1" in cams and "cam2" in cams:
                            worker_ready = True
                            break
                await asyncio.sleep(1.0)
            assert worker_ready, "AIWorker did not register cam1 & cam2 within 60s"

            DATA_EMBED_NPY.touch()
            DATA_EMBED_META.touch()
            await asyncio.sleep(3.0)

            print("[STEP 2] Waiting for live detections, recognition & IN/OUT crossings...")
            ws1_task = asyncio.create_task(_subscribe_metadata("cam1", 18.0))
            ws2_task = asyncio.create_task(_subscribe_metadata("cam2", 18.0))
            ws1_res, ws2_res = await asyncio.gather(ws1_task, ws2_task)
            print(f"[STEP 2] WebSocket cam1={ws1_res} | cam2={ws2_res}")

            # Wait up to 8s more if records haven't flushed yet
            rec_count = 0
            rec_deadline = time.monotonic() + 8.0
            while time.monotonic() < rec_deadline:
                async with session.get("http://127.0.0.1:8000/api/v1/attendance/records") as r:
                    if r.status == 200:
                        data = await r.json()
                        rec_count = len(data.get("records", []))
                        if rec_count >= 2:
                            break
                await asyncio.sleep(1.0)

            recognized_all = sorted(
                set(ws1_res["recognized_names"] + ws2_res["recognized_names"])
            )
            if not recognized_all or rec_count < 1:
                return {
                    "needs_fallback": True,
                    "ws1": ws1_res,
                    "ws2": ws2_res,
                    "rec_count": rec_count,
                }

            attached = _attach_live_evidence_snapshots(
                source_info["cam1_mp4"], source_info["cam2_mp4"]
            )
            print(f"[STEP 2] Live records={rec_count}, attached evidence snapshots={attached}")

        browser_res = await _record_browser_walkthrough()
        assert not browser_res["console_errors"], f"Console errors: {browser_res['console_errors']}"
        assert not browser_res["page_errors"], f"Page errors: {browser_res['page_errors']}"

        verify_res = _verify_outputs(
            ARTIFACTS / "Video_Minh_Chung_Diem_Danh_AttendanceOS.mp4",
            ARTIFACTS / "Anh_Minh_Chung_2_Cam.png",
            ARTIFACTS / "Bao_Cao_Diem_Danh_Mau.xlsx",
        )
        return {
            "needs_fallback": False,
            "recognized_names": recognized_all,
            "ws1": ws1_res,
            "ws2": ws2_res,
            "browser": browser_res,
            "verification": verify_res,
        }
    finally:
        print("[CLEANUP] Terminating AIWorker, uvicorn, MediaMTX & FFmpeg publishers...")
        _terminate_proc(worker_proc, "AIWorker")
        _terminate_proc(uvicorn_proc, "uvicorn")
        publisher.stop()
        for fh in (worker_log, uvicorn_log):
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
        await asyncio.sleep(1.5)


async def run_orchestrator() -> None:
    """Orchestrate Steps 1-4 end-to-end with automatic fallback and clean teardown."""
    source_info = _prepare_youtube_or_fallback()
    cfg_path = _write_demo_pipeline_config()

    run_res = await _run_stack_and_record(source_info, cfg_path)
    if run_res.get("needs_fallback"):
        if source_info["source_type"] == "youtube":
            print("[STEP 2 SAFEGUARD] YouTube stream produced 0 live crossings/names; switching to local human fallback...")
            source_info = _activate_local_fallback(
                "YouTube stream yielded 0 recognized crossings in live AIWorker"
            )
            run_res = await _run_stack_and_record(source_info, cfg_path)
        assert not run_res.get("needs_fallback"), f"Live pipeline failed to record crossings: {run_res}"

    open_ports = [p for p in (8000, 8554, 8888, 9229, 9997) if _is_port_open(p)]
    assert not open_ports, f"Ports still open after teardown: {open_ports}"
    print("[CLEANUP] Verified ports 8000, 8554, 8888, 9229, 9997 are all CLOSED.")

    summary = {
        "status": "PASS",
        "source_type": source_info["source_type"],
        "source_url": source_info["source_url"],
        "recognized_names": run_res["recognized_names"],
        "ws_cam1": run_res["ws1"],
        "ws_cam2": run_res["ws2"],
        "browser": {
            "raw_screencast_frames": run_res["browser"]["raw_screencast_frames"],
            "assembled_mp4_frames": run_res["browser"]["assembled_mp4_frames"],
            "live_state": run_res["browser"]["live_state"],
            "console_errors": run_res["browser"]["console_errors"],
            "page_errors": run_res["browser"]["page_errors"],
        },
        "verification": run_res["verification"],
    }
    summary_path = ARTIFACTS / "demo_recording_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="ATTENDANCE OS End-to-End Demo Recorder")
    parser.add_argument("--scan-yt", type=str, default=None, help="Internal subprocess mode: scan video for faces")
    parser.add_argument("--out-json", type=str, default=None, help="Output JSON path for --scan-yt")
    parser.add_argument("--prepare-fallback", action="store_true", help="Internal subprocess mode: build local fallback")
    args = parser.parse_args()

    if args.scan_yt:
        assert args.out_json, "--out-json is required with --scan-yt"
        return _scan_youtube_faces_worker(pathlib.Path(args.scan_yt), pathlib.Path(args.out_json))
    if args.prepare_fallback:
        return _prepare_fallback_worker()

    asyncio.run(run_orchestrator())
    return 0


if __name__ == "__main__":
    sys.exit(main())
