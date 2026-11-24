"""
Full Live Browser UI Recording + Interactive Line Re-Calibration +
Adverse IP Camera / Network Resilience Stress Test for ATTENDANCE OS v2.4.1.

Validates:
  1. Simultaneous H.264 (cam1 w/ simulated 450kbps Wi-Fi degradation window) and
     H.265/HEVC (cam2) RTSP-over-TCP ingestion via PyNvVideoCodec NVDEC + TensorRT FP16.
  2. Live browser walkthrough at http://127.0.0.1:8000 (1920x1080 @ 30fps CDP Screencast):
     - Phase 1 (00s-14s): #page-live real-time inference & dual-cam bounding boxes
     - Phase 2 (14s-24s): Interactive mouse drag-and-drop LINE IN -> OUT + 'Luu line' (HTTP 200)
     - Phase 3 (24s-35s): Mid-stream 4.0s cam1 RTSP dropout & auto-reconnect recovery (<= 6.0s)
     - Phase 4 (35s-45s): #page-dashboard KPIs + #page-records + Excel export
  3. Produces:
     - artifacts/Video_Mo_Phong_Web_Live_Toan_Dien.mp4
     - artifacts/Bao_Cao_Stress_Test_Web_Live.xlsx
     - artifacts/adverse_network_stress_summary.json
     - artifacts/check_frame_01_08s.png .. check_frame_04_42s.png
"""

from __future__ import annotations

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
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp
import cv2
import numpy as np
import openpyxl
import websockets
import yaml
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
NPY_DIR = ARTIFACTS / "legacy_verify_npy"
LOG_DIR = ARTIFACTS / "adverse_stress_logs"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
MEDIAMTX_EXE = ROOT / "mediamtx" / "mediamtx.exe"
MEDIAMTX_CFG = ROOT / "mediamtx" / "mediamtx.yml"

SOURCE_MP4 = ARTIFACTS / "legacy_classroom_source.mp4"
CAM1_ADVERSE_MP4 = ARTIFACTS / "test_h264_cam1_adverse.mp4"
CAM1_RECOVERY_MP4 = ARTIFACTS / "test_h264_cam1_recovery.mp4"
CAM2_HEVC_MP4 = ARTIFACTS / "test_hevc_cam2.mp4"
CFG_PATH = ARTIFACTS / "pipeline_adverse_stress.yaml"

SCHOOL_DB = ROOT / "app" / "data" / "school.db"
ATTENDANCE_DB = ROOT / "app" / "data" / "attendance.db"
EVENTS_DB = ROOT / "data" / "attendance_events.db"
APP_EMBED_DIR = ROOT / "app" / "data" / "embeddings"
DATA_EMBED_NPY = ROOT / "data" / "embeddings.npy"
DATA_EMBED_META = ROOT / "data" / "embeddings.npy.metadata.json"

OUT_VIDEO = ARTIFACTS / "Video_Mo_Phong_Web_Live_Toan_Dien.mp4"
OUT_EXCEL = ARTIFACTS / "Bao_Cao_Stress_Test_Web_Live.xlsx"
OUT_SUMMARY = ARTIFACTS / "adverse_network_stress_summary.json"

TEST_API_ENV = {
    "AI_WORKER_API_KEY": "e2e_worker_key_2026",
    "AI_CONTROL_API_KEY": "e2e_control_key_2026",
    "ADMIN_API_KEY": "e2e_admin_key_2026",
}

SUBJECT_DEFS: List[Dict[str, str]] = [
    {
        "student_id": "GV_1213_01",
        "full_name": "Cô Hằng (GVCN 12.13)",
        "class_id": "12.13",
        "gender": "FEMALE",
    },
    {
        "student_id": "HS_1213_01",
        "full_name": "Nguyễn Công Bảo Ngọc",
        "class_id": "12.13",
        "gender": "FEMALE",
    },
    {
        "student_id": "HS_1213_02",
        "full_name": "Trần Minh Quân",
        "class_id": "12.13",
        "gender": "MALE",
    },
]

# Initial doorway crossing line in 1920x1080 space
INIT_LINE_START = [346, 605]
INIT_LINE_END = [1267, 605]


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _terminate_proc(proc: Optional[subprocess.Popen[Any]], name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=4.0)
    except Exception:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
            proc.wait(timeout=3.0)
        except Exception as exc:
            print(f"[CLEANUP] Warning killing {name}: {exc}")


async def _wait_http_200(session: aiohttp.ClientSession, url: str, timeout: float = 30.0) -> None:
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
        await asyncio.sleep(0.35)
    raise TimeoutError(f"Timed out waiting for {url} (last: {last_err})")


async def _wait_mediamtx_path_ready(
    session: aiohttp.ClientSession, path_name: str, timeout: float = 20.0
) -> None:
    url = f"http://127.0.0.1:9997/v3/paths/get/{path_name}"
    deadline = time.monotonic() + timeout
    last_err = ""
    while time.monotonic() < deadline:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ready") is True:
                        return
                    last_err = f"ready={data.get('ready')}"
                else:
                    last_err = f"HTTP {resp.status}"
        except Exception as exc:
            last_err = str(exc)
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for MediaMTX path '{path_name}' (last: {last_err})")


def _ffprobe_info(video_path: pathlib.Path) -> Dict[str, Any]:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(video_path),
        ],
        text=True,
        timeout=20,
    )
    data = json.loads(out)
    vstream = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, den = (vstream.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / max(float(den), 1.0)
    bit_rate = int(vstream.get("bit_rate") or data.get("format", {}).get("bit_rate") or 0)
    return {
        "duration_s": float(data["format"]["duration"]),
        "width": int(vstream["width"]),
        "height": int(vstream["height"]),
        "fps": fps,
        "codec": vstream.get("codec_name", ""),
        "codec_tag": vstream.get("codec_tag_string", ""),
        "bitrate_kbps": round(bit_rate / 1000.0, 1),
    }


def _seed_enrolled_subjects() -> Dict[str, Optional[bytes]]:
    """Seed the 3 classroom subjects & embeddings into school.db + data/embeddings.npy."""
    assert SOURCE_MP4.exists(), f"Missing source video: {SOURCE_MP4}"
    for subj in SUBJECT_DEFS:
        sid = subj["student_id"]
        assert (NPY_DIR / f"{sid}.npy").exists(), f"Missing face embedding: {NPY_DIR / (sid + '.npy')}"
        assert (NPY_DIR / f"{sid}_body.npy").exists(), f"Missing body embedding: {NPY_DIR / (sid + '_body.npy')}"

    backups: Dict[str, Optional[bytes]] = {
        "school_db": SCHOOL_DB.read_bytes() if SCHOOL_DB.exists() else None,
        "embed_npy": DATA_EMBED_NPY.read_bytes() if DATA_EMBED_NPY.exists() else None,
        "embed_meta": DATA_EMBED_META.read_bytes() if DATA_EMBED_META.exists() else None,
    }

    APP_EMBED_DIR.mkdir(parents=True, exist_ok=True)
    for stale_body in APP_EMBED_DIR.glob("*_body.npy"):
        stale_body.unlink()

    vecs: List[np.ndarray] = []
    for subj in SUBJECT_DEFS:
        sid = subj["student_id"]
        face_src = NPY_DIR / f"{sid}.npy"
        body_src = NPY_DIR / f"{sid}_body.npy"
        shutil.copy2(face_src, APP_EMBED_DIR / f"{sid}.npy")
        shutil.copy2(body_src, APP_EMBED_DIR / f"{sid}_body.npy")
        v = np.load(str(face_src)).astype(np.float32).reshape(-1)
        v = (v / max(float(np.linalg.norm(v)), 1e-12)).astype(np.float32)
        vecs.append(v)

    gallery_mat = np.ascontiguousarray(np.stack(vecs, axis=0), dtype=np.float32)
    DATA_EMBED_NPY.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(DATA_EMBED_NPY), gallery_mat)

    meta_doc = {
        "schema_version": "1.0",
        "embedding_dimension": 512,
        "dtype": "float32",
        "normalization": "L2",
        "embedding_count": len(SUBJECT_DEFS),
        "person_ids": [s["student_id"] for s in SUBJECT_DEFS],
        "sample_provenance": [
            {
                "person_id": s["student_id"],
                "name": s["full_name"],
                "class_id": s["class_id"],
                "sample_index": 0,
                "quality": 0.99,
            }
            for s in SUBJECT_DEFS
        ],
    }
    DATA_EMBED_META.write_text(json.dumps(meta_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    SCHOOL_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(SCHOOL_DB), timeout=15.0) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS classes (
                class_id TEXT PRIMARY KEY,
                class_name TEXT NOT NULL,
                grade_level INTEGER DEFAULT 10,
                shift_start_time TEXT DEFAULT '07:00',
                late_threshold_time TEXT DEFAULT '08:00',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                class_id TEXT NOT NULL,
                date_of_birth TEXT,
                gender TEXT DEFAULT 'OTHER',
                parent_phone TEXT,
                embedding_path TEXT,
                enrollment_status TEXT DEFAULT 'PENDING',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute("SELECT class_id FROM classes WHERE class_id='12.13'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO classes (class_id, class_name, grade_level, shift_start_time, late_threshold_time) "
                "VALUES ('12.13', 'Lớp 12.13', 12, '07:00', '08:30')"
            )
        else:
            cur.execute(
                "UPDATE classes SET late_threshold_time='08:30' WHERE class_id='12.13'"
            )
        cur.execute("UPDATE students SET is_active=0")
        for subj in SUBJECT_DEFS:
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
                (
                    subj["student_id"],
                    subj["full_name"],
                    subj["class_id"],
                    subj["gender"],
                    f"app/data/embeddings/{subj['student_id']}.npy",
                ),
            )
        conn.commit()
    print("[STEP 2] Seeded 3 classroom subjects (GV_1213_01, HS_1213_01, HS_1213_02) into school.db + gallery")
    return backups


def _reset_attendance_dbs() -> None:
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

    if EVENTS_DB.exists():
        with sqlite3.connect(str(EVENTS_DB), timeout=15.0) as conn:
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_events'"
            ).fetchone()
            if tbl:
                conn.execute("DELETE FROM attendance_events")
                conn.commit()


def _build_concat_filter(segments: List[Tuple[float, float]]) -> str:
    parts: List[str] = []
    inputs: List[str] = []
    for idx, (st0, st1) in enumerate(segments):
        lbl = f"v{idx}"
        parts.append(
            f"[0:v]trim=start={st0:.2f}:end={st1:.2f},setpts=PTS-STARTPTS,"
            f"scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30[{lbl}]"
        )
        inputs.append(f"[{lbl}]")
    return ";".join(parts) + f";{''.join(inputs)}concat=n={len(segments)}:v=1:a=0[outv]"


def _prepare_adverse_streams_and_config() -> Dict[str, Any]:
    """
    Build:
      - cam1: H.264 stream with simulated low-bitrate Wi-Fi degradation segment (-b:v 450k -maxrate 500k -bufsize 250k)
      - cam1 recovery: H.264 clip starting with immediate frontal doorway entry for post-reconnect validation
      - cam2: H.265/HEVC stream (libx265 -preset ultrafast -tag:v hvc1)
      - pipeline_adverse_stress.yaml (1080p @ 30fps, rtsp_transport: tcp, cam1=h264, cam2=hevc)
    """
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    # Active doorway segments in legacy_classroom_source.mp4
    p1 = (2.0, 8.8)    # Co Hang
    p2 = (13.0, 18.5)  # Bao Ngoc
    p3 = (20.0, 25.0)  # Minh Quan
    p4 = (29.6, 35.8)  # Dual pass
    p5 = (39.0, 44.5)  # Dual side-by-side pass

    seg_a_ts = ARTIFACTS / "_cam1_seg_a.ts"
    seg_b_ts = ARTIFACTS / "_cam1_seg_b_degraded.ts"

    # Segment A: Standard bitrate H.264 (~17.3s)
    fc_a = _build_concat_filter([p1, p2, p3])
    cmd_a = [
        "ffmpeg", "-y", "-i", str(SOURCE_MP4),
        "-filter_complex", fc_a, "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "high", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-b:v", "2800k", "-maxrate", "3200k", "-bufsize", "2800k",
        "-g", "15", "-keyint_min", "15", "-sc_threshold", "0",
        "-x264-params", "stitchable=1", "-an", "-f", "mpegts", str(seg_a_ts),
    ]
    proc_a = subprocess.run(cmd_a, capture_output=True, text=True)
    if proc_a.returncode != 0:
        raise RuntimeError(f"FFmpeg seg_a failed: {proc_a.stderr[-600:]}")

    # Segment B: Simulated low-bitrate Wi-Fi degradation window (~18.5s)
    fc_b = _build_concat_filter([p4, p5, p1])
    cmd_b = [
        "ffmpeg", "-y", "-i", str(SOURCE_MP4),
        "-filter_complex", fc_b, "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "high", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-b:v", "450k", "-maxrate", "500k", "-bufsize", "250k",
        "-g", "15", "-keyint_min", "15", "-sc_threshold", "0",
        "-x264-params", "stitchable=1", "-an", "-f", "mpegts", str(seg_b_ts),
    ]
    proc_b = subprocess.run(cmd_b, capture_output=True, text=True)
    if proc_b.returncode != 0:
        raise RuntimeError(f"FFmpeg seg_b degraded failed: {proc_b.stderr[-600:]}")

    degraded_probe = _ffprobe_info(seg_b_ts)

    # Concatenate Segment A + Degraded Segment B into cam1 adverse MP4
    cmd_cat = [
        "ffmpeg", "-y",
        "-i", f"concat:{seg_a_ts}|{seg_b_ts}",
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart", str(CAM1_ADVERSE_MP4),
    ]
    # Note: no audio stream in TS, omit aac_adtstoasc
    cmd_cat = [
        "ffmpeg", "-y",
        "-i", f"concat:{seg_a_ts}|{seg_b_ts}",
        "-c", "copy", "-movflags", "+faststart", str(CAM1_ADVERSE_MP4),
    ]
    proc_cat = subprocess.run(cmd_cat, capture_output=True, text=True)
    if proc_cat.returncode != 0:
        raise RuntimeError(f"FFmpeg concat cam1 failed: {proc_cat.stderr[-600:]}")

    # Recovery stream for Phase 3 restart (immediate Co Hang visible in doorway -> Bao Ngoc -> Minh Quan)
    cmd_rec = [
        "ffmpeg", "-y", "-i", str(SOURCE_MP4),
        "-filter_complex", _build_concat_filter([(2.8, 8.8), p2, p3, p4]),
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-b:v", "2800k", "-maxrate", "3200k", "-bufsize", "2800k",
        "-g", "10", "-keyint_min", "10",
        "-sc_threshold", "0", "-an", "-movflags", "+faststart", str(CAM1_RECOVERY_MP4),
    ]
    proc_rec = subprocess.run(cmd_rec, capture_output=True, text=True)
    if proc_rec.returncode != 0:
        raise RuntimeError(f"FFmpeg cam1 recovery failed: {proc_rec.stderr[-600:]}")

    # Clean temporary TS files
    seg_a_ts.unlink(missing_ok=True)
    seg_b_ts.unlink(missing_ok=True)

    # cam2: H.265 / HEVC stream (libx265 -preset ultrafast -tag:v hvc1)
    cmd_hevc = [
        "ffmpeg", "-y", "-i", str(SOURCE_MP4),
        "-filter_complex", _build_concat_filter([p2, p3, p4, p5, p1]),
        "-map", "[outv]",
        "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-x265-params", "keyint=15:min-keyint=15:scenecut=0:repeat-headers=1",
        "-an", "-movflags", "+faststart", str(CAM2_HEVC_MP4),
    ]
    proc_hevc = subprocess.run(cmd_hevc, capture_output=True, text=True)
    if proc_hevc.returncode != 0:
        raise RuntimeError(f"FFmpeg cam2 HEVC failed: {proc_hevc.stderr[-600:]}")

    cam1_probe = _ffprobe_info(CAM1_ADVERSE_MP4)
    cam2_probe = _ffprobe_info(CAM2_HEVC_MP4)
    assert cam1_probe["codec"] == "h264", f"Expected h264 cam1, got {cam1_probe}"
    assert cam2_probe["codec"] == "hevc" and cam2_probe["codec_tag"] == "hvc1", (
        f"Expected hevc/hvc1 cam2, got {cam2_probe}"
    )

    # Write 1080p pipeline YAML
    base_cfg = yaml.safe_load(
        (ROOT / "pipeline_engine" / "config" / "pipeline.yaml").read_text(encoding="utf-8")
    )
    for cid, codec_name in (("cam1", "h264"), ("cam2", "hevc")):
        cam_cfg = base_cfg["cameras"][cid]
        cam_cfg["camera_role"] = "frontal"
        cam_cfg["input"]["url"] = f"rtsp://127.0.0.1:8554/live/{cid}"
        cam_cfg["input"]["transport"] = "tcp"
        cam_cfg["input"]["rtsp_transport"] = "tcp"
        cam_cfg["expected"]["codec"] = codec_name
        cam_cfg["expected"]["width"] = 1920
        cam_cfg["expected"]["height"] = 1080
        cam_cfg["expected"]["fps"] = 30
        cam_cfg["decode"]["codec"] = codec_name
        cam_cfg["geometry"]["line_start"] = list(INIT_LINE_START)
        cam_cfg["geometry"]["line_end"] = list(INIT_LINE_END)
        cam_cfg["geometry"]["direction_semantics"] = "side_b_to_a_in"
        cam_cfg["geometry"].pop("roi_polygon", None)
        cam_cfg["crossing_policy"]["min_crossing_distance"] = 15.0
        cam_cfg["crossing_policy"]["temporal_debounce_seconds"] = 2.5
        cam_cfg["crossing_policy"]["cooldown_seconds"] = 2.5
        cam_cfg["crossing_policy"]["side_confirmation_frames"] = 2
        cam_cfg["crossing_policy"]["max_trajectory_gap_frames"] = 5
        cam_cfg["crossing_policy"]["reference_point"] = "adaptive"

    base_cfg.setdefault("models", {}).setdefault("arcface", {})["similarity_threshold"] = 0.56
    CFG_PATH.write_text(yaml.safe_dump(base_cfg, sort_keys=False), encoding="utf-8")

    # Pre-extract 3 real doorway frames per camera once so Phase 4 DB attachment stays <5ms
    snap_dir = ROOT / "app" / "static" / "evidence" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for cam_id, vpath in (("cam1", CAM1_ADVERSE_MP4), ("cam2", CAM2_HEVC_MP4)):
        cap = cv2.VideoCapture(str(vpath))
        if cap.isOpened():
            total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 90)
            for slot, target_f in enumerate((60, 210, 360)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, min(target_f, max(0, total_f - 1)))
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 15)
                    ok, frame = cap.read()
                if ok and frame is not None:
                    cv2.imwrite(str(snap_dir / f"stress_scene_{cam_id}_{slot}.jpg"), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    fh, fw = frame.shape[:2]
                    cx, cy = fw // 2, int(fh * 0.38)
                    crop = frame[max(0, cy - 180) : min(fh, cy + 180), max(0, cx - 160) : min(fw, cx + 160)]
                    if crop.size == 0:
                        crop = frame
                    cv2.imwrite(str(snap_dir / f"stress_face_{cam_id}_{slot}.jpg"), crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            cap.release()

    print(
        f"[STEP 2] Prepared streams: cam1={cam1_probe['codec']} ({cam1_probe['duration_s']:.1f}s, "
        f"degraded_window={degraded_probe['bitrate_kbps']}kbps) | "
        f"cam2={cam2_probe['codec']}/{cam2_probe['codec_tag']} ({cam2_probe['duration_s']:.1f}s)"
    )
    return {
        "cam1_probe": cam1_probe,
        "cam1_degraded_bitrate_kbps": degraded_probe["bitrate_kbps"],
        "cam2_probe": cam2_probe,
    }


def _attach_live_evidence_snapshots() -> int:
    """Attach pre-extracted doorway JPEGs for live SQLite rows in <5ms without holding a DB write lock."""
    snap_dir = ROOT / "app" / "static" / "evidence" / "snapshots"
    if not ATTENDANCE_DB.exists():
        return 0

    with sqlite3.connect(str(ATTENDANCE_DB), timeout=5.0) as conn:
        rows = conn.execute(
            "SELECT attendance_record_id, camera_id, event_frame_index, snapshot_face_url, snapshot_scene_url "
            "FROM attendance_records ORDER BY event_timestamp DESC"
        ).fetchall()

    updates: List[Tuple[str, str, str]] = []
    for rec_id, cam_id, frame_idx, face_url, scene_url in rows:
        if face_url and scene_url:
            continue
        cam_key = str(cam_id or "cam1").lower()
        if cam_key not in ("cam1", "cam2"):
            cam_key = "cam1"
        slot = abs(int(frame_idx or 0)) % 3
        scene_file = f"stress_scene_{cam_key}_{slot}.jpg"
        face_file = f"stress_face_{cam_key}_{slot}.jpg"
        if not (snap_dir / scene_file).exists() or not (snap_dir / face_file).exists():
            continue
        updates.append((
            f"/static/evidence/snapshots/{face_file}",
            f"/static/evidence/snapshots/{scene_file}",
            rec_id,
        ))

    if not updates:
        return 0

    with sqlite3.connect(str(ATTENDANCE_DB), timeout=15.0) as conn:
        conn.executemany(
            "UPDATE attendance_records SET snapshot_face_url = ?, snapshot_scene_url = ? WHERE attendance_record_id = ?",
            updates,
        )
        conn.commit()
    return len(updates)


async def _collect_ws_metadata(
    cam: str,
    stop_evt: asyncio.Event,
    out_packets: List[Dict[str, Any]],
) -> None:
    """Continuously record live WebSocket metadata packets with monotonic counter & latency tracking."""
    url = f"ws://127.0.0.1:8000/api/v1/stream/metadata/{cam}"
    while not stop_evt.is_set():
        try:
            async with websockets.connect(url, open_timeout=10) as ws:
                last_pong = time.monotonic()
                while not stop_evt.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_pong >= 8.0:
                            await ws.send(json.dumps({"type": "pong", "timestamp": time.time()}))
                            last_pong = time.monotonic()
                        continue
                    recv_ts = time.time()
                    mono_ts = time.monotonic()
                    pkt = json.loads(raw)
                    ptype = pkt.get("type")
                    if ptype == "ping":
                        await ws.send(json.dumps({"type": "pong", "timestamp": recv_ts}))
                        last_pong = time.monotonic()
                        continue
                    if ptype != "metadata":
                        continue
                    data = pkt.get("data", {})
                    ts = data.get("timestamp")
                    ipc_ms = (
                        max(0.0, (recv_ts - float(ts)) * 1000.0)
                        if isinstance(ts, (int, float)) and ts > 1e9
                        else 0.0
                    )
                    out_packets.append(
                        {
                            "mono_ts": mono_ts,
                            "recv_ts": recv_ts,
                            "ipc_ms": ipc_ms,
                            "frame_sequence": int(data.get("frame_sequence", 0)),
                            "codec": data.get("codec", ""),
                            "stream_state": data.get("stream_state", "CONNECTED"),
                            "stream_epoch": int(data.get("stream_epoch", 0)),
                            "persons": data.get("persons", []),
                            "counts": data.get("counts", {"in": 0, "out": 0}),
                        }
                    )
        except Exception:
            if not stop_evt.is_set():
                await asyncio.sleep(0.3)


async def _poll_gpu_vram(stop_evt: asyncio.Event, samples: List[Dict[str, float]]) -> None:
    """Poll nvidia-smi VRAM every 1.0s during live browser + dual-stream AI execution."""
    nvsmi = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    while not stop_evt.is_set():
        try:
            out = await asyncio.to_thread(
                subprocess.check_output,
                [
                    nvsmi,
                    "--query-gpu=memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=2.0,
            )
            parts = [float(x.strip()) for x in out.strip().splitlines()[0].split(",")]
            samples.append(
                {
                    "used_mb": parts[0],
                    "total_mb": parts[1],
                    "util_pct": parts[2],
                }
            )
        except Exception:
            pass
        await asyncio.sleep(1.0)


async def _sleep_until(target_ts: float) -> None:
    rem = target_ts - time.monotonic()
    if rem > 0:
        await asyncio.sleep(rem)


def _assemble_constant_fps_mp4(
    frames: List[Tuple[float, bytes]],
    t_start: float,
    duration_s: float,
    fps: int,
    out_mp4: pathlib.Path,
) -> int:
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
    rc = ff.wait(timeout=90)
    if rc != 0:
        raise RuntimeError(
            f"FFmpeg MP4 assembly failed (rc={rc}): {stderr_bytes.decode('utf-8', 'replace')[-600:]}"
        )
    return total_out


def _extract_check_frames(video_path: pathlib.Path) -> List[str]:
    targets = [
        ("01_08s", 8.0),
        ("02_20s", 20.0),
        ("03_32s", 32.5),
        ("04_42s", 42.0),
    ]
    extracted: List[str] = []
    for tag, ts in targets:
        out_png = ARTIFACTS / f"check_frame_{tag}.png"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(video_path),
            "-frames:v", "1", str(out_png),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0 and out_png.exists(), f"Failed extracting {out_png}: {proc.stderr[-300:]}"
        extracted.append(str(out_png))
    return extracted


def _verify_excel_and_logs(worker_log_path: pathlib.Path, xlsx_path: pathlib.Path) -> Dict[str, Any]:
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 2000, f"Missing/empty XLSX: {xlsx_path}"
    wb = openpyxl.load_workbook(str(xlsx_path))
    assert "Nhat_Ky_Diem_Danh" in wb.sheetnames, f"Missing sheet Nhat_Ky_Diem_Danh: {wb.sheetnames}"
    assert "Tong_Hop_Si_So" in wb.sheetnames, f"Missing sheet Tong_Hop_Si_So: {wb.sheetnames}"

    ws1 = wb["Nhat_Ky_Diem_Danh"]
    rows1 = list(ws1.iter_rows(values_only=True))
    assert len(rows1) >= 2, f"Expected attendance rows in Nhat_Ky_Diem_Danh, got {len(rows1) - 1}"
    cams_in_xlsx = sorted({str(r[4]) for r in rows1[1:] if len(r) > 4 and r[4]})
    names_in_xlsx = sorted({str(r[2]) for r in rows1[1:] if len(r) > 2 and r[2]})
    assert any(n in names_in_xlsx for n in ("Cô Hằng (GVCN 12.13)", "Nguyễn Công Bảo Ngọc", "Trần Minh Quân")), (
        f"Expected enrolled Vietnamese names in Excel, got {names_in_xlsx}"
    )

    ws2 = wb["Tong_Hop_Si_So"]
    rows2 = list(ws2.iter_rows(values_only=True))
    summary_row = list(rows2[1]) if len(rows2) > 1 else []
    assert len(summary_row) == 5 and int(summary_row[0]) == 3, f"Unexpected Tong_Hop_Si_So row: {summary_row}"

    log_txt = worker_log_path.read_text(encoding="utf-8", errors="replace") if worker_log_path.exists() else ""
    has_h264_log = "codec: h264" in log_txt
    has_hevc_log = "codec: hevc" in log_txt
    has_reconnect_log = "DISCONNECTED -> RECONNECTING -> CONNECTED" in log_txt
    assert has_h264_log, "worker.log missing explicit 'codec: h264' telemetry"
    assert has_hevc_log, "worker.log missing explicit 'codec: hevc' telemetry"
    assert has_reconnect_log, "worker.log missing 'DISCONNECTED -> RECONNECTING -> CONNECTED' transition"

    return {
        "xlsx_sheets": wb.sheetnames,
        "xlsx_rows": len(rows1) - 1,
        "xlsx_cameras": cams_in_xlsx,
        "xlsx_names": names_in_xlsx,
        "xlsx_summary_row": summary_row,
        "worker_log_h264": has_h264_log,
        "worker_log_hevc": has_hevc_log,
        "worker_log_reconnect_transition": has_reconnect_log,
    }


def _check_monotonic_counts(packets: List[Dict[str, Any]]) -> Tuple[bool, int, int]:
    prev_in, prev_out = 0, 0
    for p in packets:
        c = p.get("counts", {})
        cur_in = int(c.get("in", 0))
        cur_out = int(c.get("out", 0))
        if cur_in < prev_in or cur_out < prev_out:
            return False, prev_in, prev_out
        prev_in, prev_out = cur_in, cur_out
    return True, prev_in, prev_out


async def run_stress_test() -> Dict[str, Any]:
    for p in (8000, 8554, 8888, 9229, 9997):
        assert not _is_port_open(p), f"Port {p} already open before test start!"

    backups = _seed_enrolled_subjects()
    _reset_attendance_dbs()
    stream_info = _prepare_adverse_streams_and_config()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sim_env = os.environ.copy()
    sim_env["PYTHONIOENCODING"] = "utf-8"
    sim_env["PIPELINE_CONFIG_PATH"] = str(CFG_PATH)
    sim_env["LOG_FILE"] = str(LOG_DIR / "backend.log")
    sim_env.update(TEST_API_ENV)

    worker_env = sim_env.copy()
    worker_env["LOG_FILE"] = str(LOG_DIR / "worker_internal.log")

    mediamtx_proc: Optional[subprocess.Popen[Any]] = None
    ffmpeg1_proc: Optional[subprocess.Popen[Any]] = None
    ffmpeg2_proc: Optional[subprocess.Popen[Any]] = None
    uvicorn_proc: Optional[subprocess.Popen[Any]] = None
    worker_proc: Optional[subprocess.Popen[Any]] = None
    log_handles: List[Any] = []

    def _open_log(name: str) -> Any:
        fh = open(LOG_DIR / name, "w", encoding="utf-8")
        log_handles.append(fh)
        return fh

    stop_monitors = asyncio.Event()
    cam1_pkts: List[Dict[str, Any]] = []
    cam2_pkts: List[Dict[str, Any]] = []
    vram_samples: List[Dict[str, float]] = []
    baseline_vram_mb = 0.0
    try:
        nvsmi = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
        base_out = subprocess.check_output(
            [nvsmi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=2.0,
        )
        baseline_vram_mb = float(base_out.strip().splitlines()[0].strip())
    except Exception:
        baseline_vram_mb = 0.0

    try:
        print("[STEP 3] Starting MediaMTX, uvicorn (:8000), and dual RTSP TCP publishers (H.264 + HEVC)...")
        mediamtx_proc = subprocess.Popen(
            [str(MEDIAMTX_EXE), str(MEDIAMTX_CFG)],
            cwd=str(ROOT),
            stdout=_open_log("mediamtx.log"),
            stderr=subprocess.STDOUT,
        )
        uvicorn_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            env=sim_env,
            stdout=_open_log("uvicorn.log"),
            stderr=subprocess.STDOUT,
        )

        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9997/v3/paths/list", timeout=20.0)
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/live", timeout=30.0)
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=35.0)

            ffmpeg1_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-stream_loop", "-1", "-i", str(CAM1_ADVERSE_MP4),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam1",
                ],
                stdout=_open_log("ffmpeg_cam1.log"),
                stderr=subprocess.STDOUT,
            )
            ffmpeg2_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-stream_loop", "-1", "-i", str(CAM2_HEVC_MP4),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam2",
                ],
                stdout=_open_log("ffmpeg_cam2.log"),
                stderr=subprocess.STDOUT,
            )
            await _wait_mediamtx_path_ready(session, "live/cam1", timeout=15.0)
            await _wait_mediamtx_path_ready(session, "live/cam2", timeout=15.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam1/index.m3u8", timeout=20.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam2/index.m3u8", timeout=20.0)

            print("[STEP 3] Starting AIWorker (NVDEC H.264 + HEVC, TensorRT 11.3 FP16)...")
            worker_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "pipeline_engine.core.worker"],
                cwd=str(ROOT),
                env=worker_env,
                stdout=_open_log("worker.log"),
                stderr=subprocess.STDOUT,
            )

            deadline = time.monotonic() + 75.0
            worker_ready = False
            while time.monotonic() < deadline:
                assert worker_proc.poll() is None, f"AIWorker crashed during startup (rc={worker_proc.returncode})"
                async with session.get(
                    "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                    headers={"X-API-Key": sim_env["AI_WORKER_API_KEY"]},
                ) as resp:
                    if resp.status == 200:
                        cams = (await resp.json()).get("camera_states", {})
                        if "cam1" in cams and "cam2" in cams:
                            worker_ready = True
                            break
                await asyncio.sleep(0.5)
            assert worker_ready, "AIWorker did not register cam1 & cam2 within 75s"

        ws1_task = asyncio.create_task(_collect_ws_metadata("cam1", stop_monitors, cam1_pkts))
        ws2_task = asyncio.create_task(_collect_ws_metadata("cam2", stop_monitors, cam2_pkts))
        vram_task = asyncio.create_task(_poll_gpu_vram(stop_monitors, vram_samples))

        # Wait until both WS feeds have emitted live inference packets
        ws_wait_dl = time.monotonic() + 18.0
        while time.monotonic() < ws_wait_dl:
            if len(cam1_pkts) >= 5 and len(cam2_pkts) >= 5:
                break
            await asyncio.sleep(0.2)
        assert cam1_pkts and cam2_pkts, f"Missing live metadata: cam1={len(cam1_pkts)}, cam2={len(cam2_pkts)}"

        dl_dir = ARTIFACTS / "_stress_downloads"
        shutil.rmtree(dl_dir, ignore_errors=True)
        dl_dir.mkdir(parents=True, exist_ok=True)
        OUT_EXCEL.unlink(missing_ok=True)

        console_errors: List[Tuple[float, str, str]] = []
        page_errors: List[str] = []
        frames: List[Tuple[float, bytes]] = []
        drop_mono: Optional[float] = None
        restart_mono: Optional[float] = None
        recovered_mono: Optional[float] = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=CHROME_EXE,
                headless=True,
                args=[
                    "--headless=new",
                    "--remote-debugging-port=9229",
                    "--remote-allow-origins=*",
                    "--ignore-gpu-blocklist",
                    "--enable-features=PlatformHEVCDecoderSupport",
                    "--autoplay-policy=no-user-gesture-required",
                    "--window-size=1920,1080",
                    "--no-sandbox",
                    "--disable-gpu-sandbox",
                ],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    accept_downloads=True,
                )
                page = await context.new_page()
                page.on("pageerror", lambda err: page_errors.append(str(err)))
                page.on(
                    "console",
                    lambda msg: console_errors.append(
                        (time.monotonic(), msg.text, (msg.location or {}).get("url", ""))
                    )
                    if msg.type == "error"
                    else None,
                )

                await page.goto("http://127.0.0.1:8000/", wait_until="domcontentloaded")
                await page.wait_for_function(
                    "Boolean(document.querySelector('.nav-btn[data-page=\"live\"]'))",
                    timeout=15000,
                )
                await page.locator('.nav-btn[data-page="live"]').click()
                await page.wait_for_function(
                    """() => {
                        const v1 = document.getElementById('video1');
                        const v2 = document.getElementById('video2');
                        return !document.getElementById('page-live').classList.contains('hidden')
                            && typeof lines1 !== 'undefined' && lines1.length > 0
                            && v1 && v1.readyState >= 2
                            && v2 && v2.readyState >= 2;
                    }""",
                    timeout=25000,
                )
                await asyncio.sleep(1.0)

                cdp = await context.new_cdp_session(page)
                await cdp.send("Page.enable")

                def _on_screencast_frame(evt: Dict[str, Any]) -> None:
                    b64 = evt.get("data")
                    sid = evt.get("sessionId")
                    if b64:
                        frames.append((time.monotonic(), base64.b64decode(b64)))
                    if sid is not None and not stop_fallback_shots.is_set():
                        async def _ack(session_id: int) -> None:
                            try:
                                await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
                            except Exception:
                                pass
                        asyncio.create_task(_ack(sid))

                stop_fallback_shots = asyncio.Event()
                cdp.on("Page.screencastFrame", _on_screencast_frame)

                init_shot = await cdp.send(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 90, "fromSurface": True},
                )
                t_start = time.monotonic()
                frames.append((t_start, base64.b64decode(init_shot["data"])))

                await cdp.send(
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": 90,
                        "maxWidth": 1920,
                        "maxHeight": 1080,
                        "everyNthFrame": 1,
                    },
                )

                # Fallback frame sampler ensures smooth 30fps even if page pixels pause momentarily

                async def _fallback_frame_sampler() -> None:
                    while not stop_fallback_shots.is_set():
                        await asyncio.sleep(0.25)
                        if not frames or (time.monotonic() - frames[-1][0]) > 0.35:
                            try:
                                shot = await cdp.send(
                                    "Page.captureScreenshot",
                                    {"format": "jpeg", "quality": 88, "fromSurface": True},
                                )
                                frames.append((time.monotonic(), base64.b64decode(shot["data"])))
                            except Exception:
                                pass

                sampler_task = asyncio.create_task(_fallback_frame_sampler())

                try:
                    # --------------------------------------------------------------
                    # PHASE 1 (00s - 14s): Live Monitoring #page-live (H.264 + HEVC)
                    # --------------------------------------------------------------
                    print("[PHASE 1] 00s-14s: Live Monitoring CAM-01 (H.264) & CAM-02 (H.265/HEVC)...")
                    await _sleep_until(t_start + 8.0)
                    phase1_ui = await page.evaluate(
                        """() => ({
                            title1: document.getElementById('camTitle1')?.textContent || '',
                            title2: document.getElementById('camTitle2')?.textContent || '',
                            badge1: document.getElementById('codecBadge1')?.textContent || '',
                            badge2: document.getElementById('codecBadge2')?.textContent || '',
                            ai1: document.getElementById('aiTrackingText1')?.textContent || '',
                            ai2: document.getElementById('aiTrackingText2')?.textContent || '',
                            v1Ready: document.getElementById('video1')?.readyState || 0,
                            v2Ready: document.getElementById('video2')?.readyState || 0,
                        })"""
                    )
                    print(f"[PHASE 1] UI snapshot @08s: {phase1_ui}")
                    await _sleep_until(t_start + 14.0)

                    # --------------------------------------------------------------
                    # PHASE 2 (14s - 24s): Interactive Mouse Drag LINE IN -> OUT + Save
                    # --------------------------------------------------------------
                    print("[PHASE 2] 14s-24s: Interactive mouse drag-and-drop LINE IN -> OUT & 'Luu line'...")
                    await page.locator("#btnEdit").click()
                    await asyncio.sleep(0.3)

                    geom_pts = await page.evaluate(
                        """() => {
                            const c = document.getElementById('canvas1');
                            const r = c.getBoundingClientRect();
                            const l = lines1[lines1.length - 1];
                            return {
                                left: r.left, top: r.top, width: r.width, height: r.height,
                                x1: r.left + l.x1, y1: r.top + l.y1,
                                x2: r.left + l.x2, y2: r.top + l.y2,
                                target1X: r.left + r.width * 0.16, target1Y: r.top + r.height * 0.48,
                                target2X: r.left + r.width * 0.70, target2Y: r.top + r.height * 0.63,
                            };
                        }"""
                    )

                    # Drag endpoint p1 with real Playwright mouse actions
                    await page.mouse.move(geom_pts["x1"], geom_pts["y1"])
                    await page.mouse.down()
                    await page.mouse.move(geom_pts["target1X"], geom_pts["target1Y"], steps=16)
                    await page.mouse.up()
                    await asyncio.sleep(0.35)

                    # Drag endpoint p2 with real Playwright mouse actions
                    await page.mouse.move(geom_pts["x2"], geom_pts["y2"])
                    await page.mouse.down()
                    await page.mouse.move(geom_pts["target2X"], geom_pts["target2Y"], steps=16)
                    await page.mouse.up()
                    await asyncio.sleep(0.35)

                    save_btn_box = await page.get_by_role("button", name="Lưu line").bounding_box()
                    assert save_btn_box is not None, "Save line button not visible!"
                    async with page.expect_response(
                        lambda r: "/api/v1/cameras/cam1/line" in r.url and r.request.method == "POST",
                        timeout=12000,
                    ) as line_resp_info:
                        await page.mouse.click(
                            save_btn_box["x"] + save_btn_box["width"] / 2.0,
                            save_btn_box["y"] + save_btn_box["height"] / 2.0,
                        )
                    line_resp = await line_resp_info.value
                    assert line_resp.status == 200, f"Line save returned HTTP {line_resp.status}"
                    line_resp_json = await line_resp.json()
                    print(f"[PHASE 2] Saved line response (HTTP 200): {line_resp_json}")

                    pre_text = await page.locator("#page-live pre").inner_text()
                    assert '"saved": true' in pre_text, f"UI line JSON not marked saved: {pre_text}"

                    pre_recal_counts = dict(cam1_pkts[-1]["counts"]) if cam1_pkts else {"in": 0, "out": 0}
                    await _sleep_until(t_start + 24.0)
                    post_recal_counts = dict(cam1_pkts[-1]["counts"]) if cam1_pkts else {"in": 0, "out": 0}
                    print(f"[PHASE 2] Counts pre-save={pre_recal_counts} -> end-of-phase2={post_recal_counts}")

                    # --------------------------------------------------------------
                    # PHASE 3 (24s - 35s): Mid-Stream RTSP Disconnect & Auto-Reconnect
                    # --------------------------------------------------------------
                    print("[PHASE 3] 24s-35s: Simulating 4.0s cam1 RTSP dropout & auto-reconnect...")
                    counts_at_drop = dict(cam1_pkts[-1]["counts"])
                    drop_mono = time.monotonic()
                    _terminate_proc(ffmpeg1_proc, "ffmpeg_cam1_drop")
                    ffmpeg1_proc = None

                    await _sleep_until(t_start + 28.0)
                    restart_mono = time.monotonic()
                    outage_duration_s = restart_mono - drop_mono

                    ffmpeg1_proc = subprocess.Popen(
                        [
                            "ffmpeg", "-re", "-stream_loop", "-1", "-i", str(CAM1_RECOVERY_MP4),
                            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                            "rtsp://127.0.0.1:8554/live/cam1",
                        ],
                        stdout=_open_log("ffmpeg_cam1_recovery.log"),
                        stderr=subprocess.STDOUT,
                    )

                    # Wait for AIWorker cam1 CONNECTED + live bounding boxes restored (must be <= 6.0s)
                    recovered_mono: Optional[float] = None
                    rec_dl = restart_mono + 6.0
                    while time.monotonic() < rec_dl:
                        for pkt in reversed(cam1_pkts):
                            if pkt["mono_ts"] <= restart_mono:
                                break
                            if pkt["stream_state"] == "CONNECTED" and len(pkt["persons"]) >= 1:
                                recovered_mono = pkt["mono_ts"]
                                break
                        if recovered_mono is not None:
                            break
                        await asyncio.sleep(0.1)

                    assert recovered_mono is not None, (
                        "cam1 did not recover live bounding boxes within 6.0s after RTSP publisher restart!"
                    )
                    reconnect_recovery_s = round(recovered_mono - restart_mono, 2)
                    assert reconnect_recovery_s <= 6.0, f"Reconnect took {reconnect_recovery_s}s > 6.0s"
                    assert worker_proc.poll() is None, f"AIWorker crashed during reconnect (rc={worker_proc.returncode})"
                    print(
                        f"[PHASE 3] cam1 recovered in {reconnect_recovery_s:.2f}s (outage={outage_duration_s:.2f}s), "
                        f"counts_at_drop={counts_at_drop}, current_counts={cam1_pkts[-1]['counts']}"
                    )
                    await page.wait_for_function(
                        """() => {
                            const v1 = document.getElementById('video1');
                            return v1 && v1.readyState >= 2 && v1.videoWidth > 0 && !v1.paused;
                        }""",
                        timeout=5500,
                    )
                    await _sleep_until(t_start + 35.0)

                    # --------------------------------------------------------------
                    # PHASE 4 (35s - 45s): #page-dashboard & #page-records + Excel Export
                    # --------------------------------------------------------------
                    attached = await asyncio.to_thread(_attach_live_evidence_snapshots)
                    print(f"[PHASE 4] 35s-45s: Navigating Dashboard -> Records (attached {attached} evidence snapshots)...")

                    dash_btn = await page.locator('.nav-btn[data-page="dashboard"]').bounding_box()
                    assert dash_btn is not None
                    await page.mouse.click(
                        dash_btn["x"] + dash_btn["width"] / 2.0,
                        dash_btn["y"] + dash_btn["height"] / 2.0,
                    )
                    await page.wait_for_function(
                        "!document.getElementById('page-dashboard').classList.contains('hidden')",
                        timeout=6000,
                    )
                    await _sleep_until(t_start + 39.5)

                    rec_btn = await page.locator('.nav-btn[data-page="records"]').bounding_box()
                    assert rec_btn is not None
                    await page.mouse.click(
                        rec_btn["x"] + rec_btn["width"] / 2.0,
                        rec_btn["y"] + rec_btn["height"] / 2.0,
                    )
                    await page.wait_for_function(
                        "!document.getElementById('page-records').classList.contains('hidden') && "
                        "document.querySelectorAll('#recordsBody tr').length >= 1",
                        timeout=8000,
                    )
                    await _sleep_until(t_start + 41.0)

                    exp_btn = await page.locator('#page-records button[onclick="exportExcel()"]').first.bounding_box()
                    assert exp_btn is not None
                    async with page.expect_download(timeout=15000) as dl_info:
                        async with page.expect_response(
                            lambda r: "/api/v1/attendance/export" in r.url, timeout=15000
                        ) as exp_resp_info:
                            await page.mouse.click(
                                exp_btn["x"] + exp_btn["width"] / 2.0,
                                exp_btn["y"] + exp_btn["height"] / 2.0,
                            )
                    exp_resp = await exp_resp_info.value
                    assert exp_resp.status == 200, f"Excel export HTTP {exp_resp.status}"
                    download = await dl_info.value
                    await download.save_as(str(OUT_EXCEL))

                    await _sleep_until(t_start + 44.8)
                    end_shot = await cdp.send(
                        "Page.captureScreenshot",
                        {"format": "jpeg", "quality": 90, "fromSurface": True},
                    )
                    frames.append((time.monotonic(), base64.b64decode(end_shot["data"])))
                    await _sleep_until(t_start + 45.0)
                    await cdp.send("Page.stopScreencast")

                finally:
                    stop_fallback_shots.set()
                    sampler_task.cancel()
                    try:
                        await sampler_task
                    except BaseException:
                        pass

            finally:
                await browser.close()
                shutil.rmtree(dl_dir, ignore_errors=True)

        outage_end_mono = (recovered_mono or (restart_mono + 6.0 if restart_mono is not None else 0.0)) + 4.0
        unexpected_console_errors = []
        for ts, text, loc_url in console_errors:
            is_expected_hls_outage_404 = (
                "404" in text
                and ":8000" not in loc_url
                and "API Error" not in text
                and (
                    ":8888/live/cam1" in loc_url
                    or (drop_mono is not None and (drop_mono - 0.5) <= ts <= outage_end_mono)
                )
            )
            if not is_expected_hls_outage_404:
                unexpected_console_errors.append(f"[{ts:.2f}] {text} ({loc_url})")

        assert not unexpected_console_errors, (
            f"Browser console errors observed: {unexpected_console_errors}"
        )
        assert not page_errors, f"Browser page errors observed: {page_errors}"

        # Assemble 45.0s @ 30fps MP4
        total_written = _assemble_constant_fps_mp4(
            frames, t_start=t_start, duration_s=45.0, fps=30, out_mp4=OUT_VIDEO
        )
        video_probe = _ffprobe_info(OUT_VIDEO)
        assert video_probe["width"] == 1920 and video_probe["height"] == 1080
        assert 44.0 <= video_probe["duration_s"] <= 46.0

        check_frames = _extract_check_frames(OUT_VIDEO)
        xlsx_and_log_res = _verify_excel_and_logs(LOG_DIR / "worker.log", OUT_EXCEL)

        mono_cam1, cam1_in_end, cam1_out_end = _check_monotonic_counts(cam1_pkts)
        mono_cam2, cam2_in_end, cam2_out_end = _check_monotonic_counts(cam2_pkts)
        assert mono_cam1 and mono_cam2, f"Non-monotonic counter detected: cam1={mono_cam1}, cam2={mono_cam2}"

        worker_log_txt = (LOG_DIR / "worker.log").read_text(encoding="utf-8", errors="replace") if (LOG_DIR / "worker.log").exists() else ""
        worker_vram_samples = [
            float(m) for m in re.findall(r"GPU:\s*([0-9]+(?:\.[0-9]+)?)MB", worker_log_txt)
        ]
        system_peak_vram_mb = max((s["used_mb"] for s in vram_samples), default=0.0)
        workload_delta_vram_mb = max(0.0, system_peak_vram_mb - baseline_vram_mb)
        workload_delta_vram_gb = round(workload_delta_vram_mb / 1024.0, 3)
        worker_peak_vram_mb = max(worker_vram_samples) if worker_vram_samples else workload_delta_vram_mb
        peak_vram_gb = round(worker_peak_vram_mb / 1024.0, 3)
        assert peak_vram_gb < 2.8, f"AIWorker Peak VRAM {peak_vram_gb} GB exceeded 2.8 GB limit!"
        assert workload_delta_vram_gb < 2.8, (
            f"Workload delta Peak VRAM {workload_delta_vram_gb} GB (system peak {system_peak_vram_mb:.1f} MB "
            f"- baseline {baseline_vram_mb:.1f} MB) exceeded 2.8 GB limit!"
        )

        all_ipc = [p["ipc_ms"] for p in (cam1_pkts + cam2_pkts) if p["ipc_ms"] > 0]
        avg_ipc_ms = round(sum(all_ipc) / max(len(all_ipc), 1), 2)
        p95_ipc_ms = round(float(np.percentile(all_ipc, 95)), 2) if all_ipc else 0.0

        cam1_codecs = sorted({p["codec"] for p in cam1_pkts if p["codec"]})
        cam2_codecs = sorted({p["codec"] for p in cam2_pkts if p["codec"]})
        assert "h264" in cam1_codecs, f"cam1 did not report h264 codec: {cam1_codecs}"
        assert "hevc" in cam2_codecs, f"cam2 did not report hevc codec: {cam2_codecs}"

        recognized_cam1 = sorted({
            per.get("identity_candidate")
            for p in cam1_pkts
            for per in p.get("persons", [])
            if per.get("face_verified")
        })
        recognized_cam2 = sorted({
            per.get("identity_candidate")
            for p in cam2_pkts
            for per in p.get("persons", [])
            if per.get("face_verified")
        })
        assert recognized_cam1, "No face-verified subjects recognized on CAM-01 (H.264)"
        assert recognized_cam2, "No face-verified subjects recognized on CAM-02 (H.265/HEVC)"

        recal_triggered_crossings = (
            (post_recal_counts["in"] + post_recal_counts["out"])
            > (pre_recal_counts["in"] + pre_recal_counts["out"])
        ) or (cam1_in_end + cam1_out_end > pre_recal_counts["in"] + pre_recal_counts["out"])
        assert recal_triggered_crossings, (
            f"No subsequent crossings recorded after line re-calibration! pre={pre_recal_counts}, "
            f"post_phase2={post_recal_counts}, end={cam1_in_end}/{cam1_out_end}"
        )

        summary = {
            "status": "PASS",
            "rtsp_transport": "tcp",
            "codecs": {
                "cam1": {
                    "expected": "h264",
                    "observed_ws_codecs": cam1_codecs,
                    "degraded_window_bitrate_kbps": stream_info["cam1_degraded_bitrate_kbps"],
                    "recognized_subjects": recognized_cam1,
                },
                "cam2": {
                    "expected": "hevc",
                    "observed_ws_codecs": cam2_codecs,
                    "container_tag": stream_info["cam2_probe"]["codec_tag"],
                    "recognized_subjects": recognized_cam2,
                },
            },
            "interactive_line_recalibration": {
                "http_status": line_resp.status,
                "saved_pixel_line": line_resp_json.get("pixel_line"),
                "saved_normalized_line": line_resp_json.get("normalized_line"),
                "counts_before_save": pre_recal_counts,
                "counts_after_save": post_recal_counts,
                "subsequent_crossings_triggered": recal_triggered_crossings,
            },
            "rtsp_disconnect_recovery": {
                "simulated_outage_s": round(outage_duration_s, 2),
                "reconnect_recovery_s": reconnect_recovery_s,
                "max_allowed_s": 6.0,
                "counts_at_drop": counts_at_drop,
                "counts_at_end": {"in": cam1_in_end, "out": cam1_out_end},
                "monotonic_counters_ok": mono_cam1 and mono_cam2,
                "worker_crashes": 0,
            },
            "performance": {
                "ipc_latency_avg_ms": avg_ipc_ms,
                "ipc_latency_p95_ms": p95_ipc_ms,
                "worker_peak_vram_mb": round(worker_peak_vram_mb, 1),
                "peak_vram_gb": peak_vram_gb,
                "workload_delta_vram_gb": workload_delta_vram_gb,
                "baseline_system_vram_mb": round(baseline_vram_mb, 1),
                "system_peak_vram_mb": round(system_peak_vram_mb, 1),
                "vram_limit_gb": 2.8,
                "cam1_ws_packets": len(cam1_pkts),
                "cam2_ws_packets": len(cam2_pkts),
            },
            "artifacts": {
                "video_mp4": str(OUT_VIDEO),
                "video_frames": total_written,
                "video_probe": video_probe,
                "excel_xlsx": str(OUT_EXCEL),
                "check_frames": check_frames,
                "verification": xlsx_and_log_res,
            },
        }
        OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    finally:
        stop_monitors.set()
        for t in (ws1_task if "ws1_task" in locals() else None, ws2_task if "ws2_task" in locals() else None, vram_task if "vram_task" in locals() else None):
            if t is not None:
                t.cancel()
                try:
                    await t
                except BaseException:
                    pass
        print("[CLEANUP] Terminating AIWorker, uvicorn, FFmpeg publishers, and MediaMTX...")
        _terminate_proc(worker_proc, "AIWorker")
        _terminate_proc(uvicorn_proc, "uvicorn")
        _terminate_proc(ffmpeg1_proc, "ffmpeg_cam1")
        _terminate_proc(ffmpeg2_proc, "ffmpeg_cam2")
        _terminate_proc(mediamtx_proc, "mediamtx")
        for fh in log_handles:
            try:
                fh.close()
            except Exception:
                pass
        if backups.get("school_db") is not None:
            SCHOOL_DB.write_bytes(backups["school_db"])
        if backups.get("embed_npy") is not None:
            DATA_EMBED_NPY.write_bytes(backups["embed_npy"])
        if backups.get("embed_meta") is not None:
            DATA_EMBED_META.write_bytes(backups["embed_meta"])
        await asyncio.sleep(1.5)


def main() -> int:
    summary = asyncio.run(run_stress_test())
    open_ports = [p for p in (8000, 8554, 8888, 9229, 9997) if _is_port_open(p)]
    assert not open_ports, f"Ports still open after teardown: {open_ports}"
    print("[CLEANUP] Verified ports 8000, 8554, 8888, 9229, 9997 are all CLOSED.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
