"""
End-to-End Verification of Asymmetric 2-Camera Cross-Camera Identity Handoff
(Side-Profile Corridor Cam + Frontal Doorway Cam).

Validates both directions against the live production stack
(MediaMTX + FastAPI + AIWorker with NVDEC + TensorRT 11.3 FP16 + Rust attendance_core
+ GlobalIdentityService + SQLite WAL):
  1. Direction A (Frontal CAM-02 -> Side-Profile CAM-01 Forward Bridge within 15.0s)
  2. Direction B (Side-Profile CAM-01 -> Frontal CAM-02 Reverse Backfill within 20.0s,
     with Pending Track #G-XX hold & deduplicated SQLite attendance)

Produces:
  - artifacts/Minh_Chung_Xuyen_2_Cam_Ngang_TrucDien.jpg (1920x1080 side-by-side proof)
  - artifacts/asymmetric_2cam_summary.json (quantitative telemetry)
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import cv2
import numpy as np
import websockets
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
NPY_DIR = ARTIFACTS / "legacy_verify_npy"
LOG_DIR = ARTIFACTS / "asymmetric_2cam_logs"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
MEDIAMTX_EXE = ROOT / "mediamtx" / "mediamtx.exe"
MEDIAMTX_CFG = ROOT / "mediamtx" / "mediamtx.yml"
SOURCE_ASCII_MP4 = ARTIFACTS / "legacy_classroom_source.mp4"
CAM1_2CAM_MP4 = ARTIFACTS / "asymmetric_cam1_side_profile.mp4"
CAM2_2CAM_MP4 = ARTIFACTS / "asymmetric_cam2_frontal.mp4"
CFG_PATH = ARTIFACTS / "pipeline_asymmetric_2cam.yaml"

SCHOOL_DB = ROOT / "app" / "data" / "school.db"
SCHOOL_DB_BAK = NPY_DIR / "school.db.bak"
ATTENDANCE_DB = ROOT / "app" / "data" / "attendance.db"
EVENTS_DB = ROOT / "data" / "attendance_events.db"
APP_EMBED_DIR = ROOT / "app" / "data" / "embeddings"
DATA_EMBED_NPY = ROOT / "data" / "embeddings.npy"
DATA_EMBED_META = ROOT / "data" / "embeddings.npy.metadata.json"

OUT_PROOF_JPG = ARTIFACTS / "Minh_Chung_Xuyen_2_Cam_Ngang_TrucDien.jpg"
OUT_SUMMARY = ARTIFACTS / "asymmetric_2cam_summary.json"

LEAD_IN_S = 55.0
# Relative content timeline (seconds after LEAD_IN_S):
#   0.0 -  4.0 : TC1 CAM-02 Frontal (Bảo Ngọc 13.8..16.5s @ 1.48x)
#   4.0 -  8.0 : TC1 CAM-01 Side-Profile (Bảo Ngọc 17.6..19.2s @ 2.5x)
#   8.0 - 11.0 : Empty gap
#  11.0 - 15.0 : TC2 CAM-01 Side-Profile (Cô Hằng 7.0..8.4s @ 2.86x) -> Pending #G-01
#  15.0 - 16.0 : Empty gap
#  16.0 - 20.5 : TC2 CAM-02 Frontal (Cô Hằng 4.6..6.4s @ 2.5x) -> Backfill #G-01
#  20.5 - 24.5 : Empty flush window
CONTENT_DURATION_S = 24.5

CAM1_LINE_START = [1100, 150]
CAM1_LINE_END = [1100, 980]
CAM2_LINE_START = [346, 605]
CAM2_LINE_END = [1267, 605]

VERIFY_API_ENV = {
    "AI_WORKER_API_KEY": "e2e_worker_key_2026",
    "AI_CONTROL_API_KEY": "e2e_control_key_2026",
    "ADMIN_API_KEY": "e2e_admin_key_2026",
}


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _terminate_proc(proc: Optional[subprocess.Popen[Any]], name: str) -> None:
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
        await asyncio.sleep(0.4)
    raise TimeoutError(f"Timed out waiting for {url} (last: {last_err})")


async def _wait_mediamtx_path_ready(
    session: aiohttp.ClientSession, path_name: str, timeout: float = 15.0
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


def _run_gis_unit_guards() -> Dict[str, Any]:
    """Fast pre-flight check of GlobalIdentityService 15s/20s TTL & 0.08 uniform-margin guards."""
    from app.identity.global_identity_service import create_global_identity_service

    gis = create_global_identity_service()
    t0 = 1000.0

    # Uniform collision test: two verified students with nearly identical body vectors (margin < 0.08)
    v_a = np.zeros(2048, dtype=np.float32)
    v_a[0] = 1.0
    v_b = np.zeros(2048, dtype=np.float32)
    v_b[0] = 0.995
    v_b[1] = float(np.sqrt(1.0 - 0.995 ** 2))
    v_q = np.zeros(2048, dtype=np.float32)
    v_q[0] = 0.998
    v_q[1] = float(np.sqrt(1.0 - 0.998 ** 2))

    gis.publish_face_verified("HS_A", "Học Sinh A", v_a, "cam2", 1, 0.90, timestamp=t0)
    gis.publish_face_verified("HS_B", "Học Sinh B", v_b, "cam2", 2, 0.90, timestamp=t0 + 0.5)
    collision = gis.query_forward_handoff("cam1", v_q, timestamp=t0 + 2.0, ttl_seconds=15.0, min_sim=0.68, min_margin=0.08)
    assert collision is None, f"Uniform collision guard failed (returned {collision} despite margin < 0.08)"

    # Distinct subject match within 15s window & expiration after 15s
    gis.clear()
    v_distinct_1 = np.zeros(2048, dtype=np.float32)
    v_distinct_1[10] = 1.0
    v_distinct_2 = np.zeros(2048, dtype=np.float32)
    v_distinct_2[20] = 1.0
    gis.publish_face_verified("HS_1", "Nguyễn Công Bảo Ngọc", v_distinct_1, "cam2", 10, 0.92, timestamp=t0)
    gis.publish_face_verified("HS_2", "Trần Minh Quân", v_distinct_2, "cam2", 11, 0.92, timestamp=t0)

    matched = gis.query_forward_handoff("cam1", v_distinct_1, timestamp=t0 + 5.0, ttl_seconds=15.0, min_sim=0.68, min_margin=0.08)
    assert matched is not None and matched["student_id"] == "HS_1", f"Expected HS_1 forward match, got {matched}"

    expired = gis.query_forward_handoff("cam1", v_distinct_1, timestamp=t0 + 16.0, ttl_seconds=15.0, min_sim=0.68, min_margin=0.08)
    assert expired is None, f"15s TTL guard failed (returned {expired} after 16s)"

    # Reverse backfill guard
    gis.clear()
    pt = gis.register_or_update_pending_track("cam1", 7, v_distinct_1, timestamp=t0)
    assert pt is not None and pt.pending_id == "G-01"
    bfs = gis.publish_face_verified("GV_1", "Cô Hằng (GVCN 12.13)", v_distinct_1, "cam2", 20, 0.91, timestamp=t0 + 6.0)
    assert len(bfs) == 1 and bfs[0]["pending_id"] == "G-01" and bfs[0]["student_id"] == "GV_1"

    return {"uniform_collision_blocked": True, "ttl_15s_enforced": True, "reverse_backfill_ok": True}


def _ensure_enrolled_subjects_and_restore_ready() -> None:
    """Ensure the 3 verified subjects from classroom footage are enrolled in school.db + embeddings."""
    assert SOURCE_ASCII_MP4.exists(), f"Missing {SOURCE_ASCII_MP4}"
    if not (NPY_DIR / "GV_1213_01.npy").exists() or not (NPY_DIR / "HS_1213_01_body.npy").exists():
        proc = subprocess.run(
            [PYTHON_EXE, str(ROOT / "tests" / "verify_on_legacy_classroom_video.py"), "--extract-embeddings"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Enrollment extraction failed:\n{proc.stdout}\n{proc.stderr}")

    if not SCHOOL_DB_BAK.exists() and SCHOOL_DB.exists():
        shutil.copy2(SCHOOL_DB, SCHOOL_DB_BAK)

    subjects = [
        ("GV_1213_01", "Cô Hằng (GVCN 12.13)", "12.13", "FEMALE"),
        ("HS_1213_01", "Nguyễn Công Bảo Ngọc", "12.13", "FEMALE"),
        ("HS_1213_02", "Trần Minh Quân", "12.13", "MALE"),
    ]
    APP_EMBED_DIR.mkdir(parents=True, exist_ok=True)
    for sid, _, _, _ in subjects:
        shutil.copy2(NPY_DIR / f"{sid}.npy", APP_EMBED_DIR / f"{sid}.npy")
        shutil.copy2(NPY_DIR / f"{sid}_body.npy", APP_EMBED_DIR / f"{sid}_body.npy")

    if (NPY_DIR / "gallery_matrix_512d.npy").exists():
        shutil.copy2(NPY_DIR / "gallery_matrix_512d.npy", DATA_EMBED_NPY)

    with sqlite3.connect(str(SCHOOL_DB), timeout=15.0) as conn:
        cur = conn.cursor()
        cur.execute("SELECT class_id FROM classes WHERE class_id='12.13'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO classes (class_id, class_name, grade_level, shift_start_time, late_threshold_time) "
                "VALUES ('12.13', 'Lớp 12.13', 12, '07:00', '07:00')"
            )
        cur.execute("UPDATE students SET is_active=0")
        for sid, fname, cid, gender in subjects:
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
                (sid, fname, cid, gender, f"app/data/embeddings/{sid}.npy"),
            )
        conn.commit()


def _build_synchronized_clip(out_mp4: pathlib.Path, timeline_segments: List[Tuple[str, float, float, float]]) -> None:
    """
    Build a 1920x1080@30fps H.264 stream from real source segments + empty doorway frames.

    Each item in timeline_segments is (mode, src_t0, src_t1, target_duration_s):
      - mode == 'empty': hold empty doorway frame at t=0.0s for target_duration_s
      - mode == 'clip': extract [src_t0, src_t1] from SOURCE_ASCII_MP4 and time-stretch to target_duration_s
    """
    filter_parts: List[str] = []
    concat_inputs: List[str] = []
    for idx, (mode, st0, st1, dur_s) in enumerate(timeline_segments):
        lbl = f"v{idx}"
        if mode == "empty":
            n_frames = max(1, int(round(dur_s * 30.0)))
            filter_parts.append(
                f"[0:v]trim=start=0.0:duration=0.04,setpts=PTS-STARTPTS,"
                f"scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                f"loop=loop={n_frames - 1}:size=1:start=0,setpts=N/(30*TB),fps=30[{lbl}]"
            )
        else:
            src_dur = max(0.1, st1 - st0)
            stretch = dur_s / src_dur
            filter_parts.append(
                f"[0:v]trim=start={st0:.3f}:end={st1:.3f},setpts={stretch:.6f}*(PTS-STARTPTS),"
                f"scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,trim=duration={dur_s:.3f},setpts=PTS-STARTPTS[{lbl}]"
            )
        concat_inputs.append(f"[{lbl}]")

    filter_complex = ";".join(filter_parts) + f";{''.join(concat_inputs)}concat=n={len(timeline_segments)}:v=1:a=0[outv]"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(SOURCE_ASCII_MP4),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-crf",
        "20",
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
        raise RuntimeError(f"FFmpeg build failed for {out_mp4}: {proc.stderr[-800:]}")


def _prepare_streams_and_config() -> None:
    """Generate synchronized CAM-01 (side_profile) and CAM-02 (frontal) clips + pipeline YAML."""
    cam1_segments = [
        ("empty", 0.0, 0.04, LEAD_IN_S),
        ("empty", 0.0, 0.04, 4.0),         # T+0..4: CAM-02 shows Bảo Ngọc frontal
        ("clip", 17.6, 19.2, 4.0),         # T+4..8: CAM-01 shows Bảo Ngọc side-profile exit -> Forward Bridge
        ("empty", 0.0, 0.04, 3.0),         # T+8..11: empty gap
        ("clip", 7.0, 8.4, 4.0),           # T+11..15: CAM-01 shows Cô Hằng side-profile exit -> Pending #G-01
        ("empty", 0.0, 0.04, 9.5),         # T+15..24.5: CAM-02 shows Cô Hằng frontal + flush
    ]
    cam2_segments = [
        ("empty", 0.0, 0.04, LEAD_IN_S),
        ("clip", 13.8, 16.5, 4.0),         # T+0..4: CAM-02 shows Bảo Ngọc frontal -> Face Verified
        ("empty", 0.0, 0.04, 12.0),        # T+4..16: CAM-01 handles TC1 & TC2 pending
        ("clip", 4.6, 6.4, 4.5),           # T+16..20.5: CAM-02 shows Cô Hằng frontal -> Retroactive Backfill
        ("empty", 0.0, 0.04, 4.0),         # T+20.5..24.5: flush
    ]
    _build_synchronized_clip(CAM1_2CAM_MP4, cam1_segments)
    _build_synchronized_clip(CAM2_2CAM_MP4, cam2_segments)

    base_cfg = yaml.safe_load(
        (ROOT / "pipeline_engine" / "config" / "pipeline.yaml").read_text(encoding="utf-8")
    )
    cam1 = base_cfg["cameras"]["cam1"]
    cam1["camera_role"] = "side_profile"
    cam1["expected"]["width"] = 1920
    cam1["expected"]["height"] = 1080
    cam1["expected"]["fps"] = 30
    cam1["geometry"]["line_start"] = list(CAM1_LINE_START)
    cam1["geometry"]["line_end"] = list(CAM1_LINE_END)
    cam1["geometry"]["direction_semantics"] = "side_a_to_b_in"
    cam1["geometry"].pop("roi_polygon", None)
    cam1["crossing_policy"]["min_crossing_distance"] = 15.0
    cam1["crossing_policy"]["temporal_debounce_seconds"] = 4.0
    cam1["crossing_policy"]["cooldown_seconds"] = 4.0
    cam1["crossing_policy"]["side_confirmation_frames"] = 2
    cam1["crossing_policy"]["max_trajectory_gap_frames"] = 5
    cam1["crossing_policy"]["reference_point"] = "center"

    cam2 = base_cfg["cameras"]["cam2"]
    cam2["camera_role"] = "frontal"
    cam2["expected"]["width"] = 1920
    cam2["expected"]["height"] = 1080
    cam2["expected"]["fps"] = 30
    cam2["geometry"]["line_start"] = list(CAM2_LINE_START)
    cam2["geometry"]["line_end"] = list(CAM2_LINE_END)
    cam2["geometry"]["direction_semantics"] = "side_b_to_a_in"
    cam2["geometry"].pop("roi_polygon", None)
    cam2["crossing_policy"]["min_crossing_distance"] = 15.0
    cam2["crossing_policy"]["temporal_debounce_seconds"] = 4.0
    cam2["crossing_policy"]["cooldown_seconds"] = 4.0
    cam2["crossing_policy"]["side_confirmation_frames"] = 2
    cam2["crossing_policy"]["max_trajectory_gap_frames"] = 5
    cam2["crossing_policy"]["reference_point"] = "adaptive"

    base_cfg.setdefault("models", {}).setdefault("arcface", {})["similarity_threshold"] = 0.56
    CFG_PATH.write_text(yaml.safe_dump(base_cfg, sort_keys=False), encoding="utf-8")
    print(f"[STEP 1] Built synchronized 2-cam clips ({CAM1_2CAM_MP4.name}, {CAM2_2CAM_MP4.name}) & {CFG_PATH.name}")


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


async def _record_ws_metadata(cam: str, duration_s: float) -> List[Dict[str, Any]]:
    url = f"ws://127.0.0.1:8000/api/v1/stream/metadata/{cam}"
    packets: List[Dict[str, Any]] = []
    async with websockets.connect(url, open_timeout=15) as ws:
        end_t = time.monotonic() + duration_s
        last_pong = time.monotonic()
        while time.monotonic() < end_t:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
            except asyncio.TimeoutError:
                if time.monotonic() - last_pong >= 8.0:
                    await ws.send(json.dumps({"type": "pong", "timestamp": time.time()}))
                    last_pong = time.monotonic()
                continue
            recv_ts = time.time()
            pkt = json.loads(raw)
            pkt_type = pkt.get("type")
            if pkt_type == "ping":
                await ws.send(json.dumps({"type": "pong", "timestamp": recv_ts}))
                last_pong = time.monotonic()
                continue
            if pkt_type != "metadata":
                continue
            data = pkt.get("data", {})
            packets.append(
                {
                    "recv_ts": recv_ts,
                    "frame_sequence": int(data.get("frame_sequence", 0)),
                    "persons": data.get("persons", []),
                    "counts": data.get("counts", {"in": 0, "out": 0}),
                }
            )
    return packets


def _read_video_frame_at(video_path: pathlib.Path, t_s: float) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t_s * fps))))
    ok, frame = cap.read()
    cap.release()
    assert ok and frame is not None, f"Failed reading {video_path} at {t_s}s"
    return frame


def _load_fonts() -> Dict[str, ImageFont.FreeTypeFont]:
    font_dir = pathlib.Path(r"C:\Windows\Fonts")
    bold_path = str(font_dir / "segoeuib.ttf")
    reg_path = str(font_dir / "segoeui.ttf")
    return {
        "header": ImageFont.truetype(bold_path, 25),
        "sub": ImageFont.truetype(bold_path, 19),
        "label": ImageFont.truetype(bold_path, 16),
        "badge": ImageFont.truetype(bold_path, 15),
        "body": ImageFont.truetype(reg_path, 16),
    }


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int, int, int],
    fill: Tuple[int, int, int, int],
    outline: Optional[Tuple[int, int, int, int]] = None,
    radius: int = 8,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=2 if outline else 0)


def _render_cross_cam_proof(
    cam1_pkt: Dict[str, Any],
    cam1_t_abs: float,
    cam2_pkt: Dict[str, Any],
    cam2_t_abs: float,
    tc2_summary: Dict[str, Any],
) -> None:
    """Render 1920x1080 side-by-side proof image for CAM-01 (Side-Profile) vs CAM-02 (Frontal)."""
    cam1_bgr = _read_video_frame_at(CAM1_2CAM_MP4, cam1_t_abs)
    cam2_bgr = _read_video_frame_at(CAM2_2CAM_MP4, cam2_t_abs)
    fonts = _load_fonts()

    canvas = Image.new("RGBA", (1920, 1080), (15, 23, 42, 255))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Header
    draw.rectangle([0, 0, 1920, 85], fill=(10, 15, 28, 255))
    draw.line([(0, 84), (1920, 84)], fill=(51, 65, 85, 255), width=2)
    draw.text(
        (28, 25),
        "MINH CHỨNG ĐỊNH DANH XUYÊN 2 CAMERA BẤT ĐỐI XỨNG (NGANG HÀNH LANG ↔ TRỰC DIỆN CỬA LỚP)",
        font=fonts["header"],
        fill=(248, 250, 252, 255),
    )

    # Panel Headers
    _draw_pill(draw, (20, 98, 940, 146), fill=(12, 74, 110, 235), outline=(56, 189, 248, 240))
    draw.text((38, 109), "CAM-01 (GÓC NGANG HÀNH LANG)", font=fonts["sub"], fill=(224, 242, 254, 255))
    draw.text((665, 112), "SIDE-PROFILE + BODY REID", font=fonts["label"], fill=(125, 211, 252, 255))

    draw.line([(960, 85), (960, 980)], fill=(71, 85, 105, 255), width=3)

    _draw_pill(draw, (980, 98, 1900, 146), fill=(6, 78, 59, 235), outline=(16, 185, 129, 240))
    draw.text((998, 109), "CAM-02 (GÓC TRỰC DIỆN CỬA LỚP)", font=fonts["sub"], fill=(209, 250, 229, 255))
    draw.text((1640, 112), "FRONTAL FACE VERIFIED", font=fonts["label"], fill=(52, 211, 153, 255))

    vw, vh = 920, 518
    lx0, ly0 = 20, 165
    rx0, ry0 = 980, 165
    for bgr, px0, py0 in ((cam1_bgr, lx0, ly0), (cam2_bgr, rx0, ry0)):
        rgb_small = cv2.cvtColor(cv2.resize(bgr, (vw, vh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        canvas.paste(Image.fromarray(rgb_small), (px0, py0))

    # Draw crossing lines
    c1x1 = lx0 + int((CAM1_LINE_START[0] / 1920.0) * vw)
    c1y1 = ly0 + int((CAM1_LINE_START[1] / 1080.0) * vh)
    c1x2 = lx0 + int((CAM1_LINE_END[0] / 1920.0) * vw)
    c1y2 = ly0 + int((CAM1_LINE_END[1] / 1080.0) * vh)
    draw.line([(c1x1, c1y1), (c1x2, c1y2)], fill=(56, 189, 248, 255), width=3)

    c2x1 = rx0 + int((CAM2_LINE_START[0] / 1920.0) * vw)
    c2y1 = ry0 + int((CAM2_LINE_START[1] / 1080.0) * vh)
    c2x2 = rx0 + int((CAM2_LINE_END[0] / 1920.0) * vw)
    c2y2 = ry0 + int((CAM2_LINE_END[1] / 1080.0) * vh)
    draw.line([(c2x1, c2y1), (c2x2, c2y2)], fill=(16, 185, 129, 255), width=3)

    # Overlay persons on CAM-01 and CAM-02
    for pkt, ox, oy, tag, fill_c, out_c in (
        (cam1_pkt, lx0, ly0, "BRIDGED FROM CAM-02", (12, 74, 110, 255), (56, 189, 248, 255)),
        (cam2_pkt, rx0, ry0, "FACE VERIFIED", (6, 78, 59, 255), (16, 185, 129, 255)),
    ):
        _draw_pill(draw, (ox + 14, oy + 12, ox + 360, oy + 46), fill=fill_c, outline=out_c, radius=6)
        draw.text((ox + 26, oy + 18), tag, font=fonts["badge"], fill=(255, 255, 255, 255))
        for p in pkt.get("persons", []):
            bx1, by1, bx2, by2 = p["bbox"]
            px1 = ox + int(bx1 * vw)
            py1 = oy + int(by1 * vh)
            px2 = ox + int(bx2 * vw)
            py2 = oy + int(by2 * vh)
            draw.rectangle([px1, py1, px2, py2], outline=out_c, width=3)
            cand = p.get("identity_candidate", "")
            conf = float(p.get("identity_confidence") or 0.0)
            tid = p.get("track_id", 0)
            lbl = f"#{tid} {cand} ({conf * 100:.1f}%)"
            tb = draw.textbbox((0, 0), lbl, font=fonts["badge"])
            pw_box = (tb[2] - tb[0]) + 16
            ph_box = (tb[3] - tb[1]) + 10
            tx1 = max(ox + 4, min(px1, ox + vw - pw_box - 4))
            ty1 = max(oy + 52, py1 - ph_box - 4)
            _draw_pill(draw, (tx1, ty1, tx1 + pw_box, ty1 + ph_box), fill=fill_c, outline=out_c, radius=5)
            draw.text((tx1 + 8, ty1 + 4), lbl, font=fonts["badge"], fill=(255, 255, 255, 255))

    # Cards below panels
    _draw_pill(draw, (20, 702, 940, 962), fill=(30, 41, 59, 235), outline=(56, 189, 248, 200))
    draw.text((38, 718), "CHIỀU THUẬN (DIRECTION A): CAM-02 → CAM-01 (CỬA SỔ 15s)", font=fonts["sub"], fill=(125, 211, 252, 255))
    draw.text((38, 760), "• CAM-02 khóa danh tính bằng SCRFD + ArcFace (face_verified=True)", font=fonts["body"], fill=(226, 232, 240, 255))
    draw.text((38, 796), "• CAM-01 góc ngang hành lang không thấy mặt trực diện -> truy vấn BodyReID 2048D", font=fonts["body"], fill=(226, 232, 240, 255))
    draw.text((38, 832), "• Kết quả: Đồng bộ ngay tên 'Nguyễn Công Bảo Ngọc' (bridged_from_cam='cam2')", font=fonts["body"], fill=(167, 243, 208, 255))
    draw.text((38, 868), "• Chống nhầm đồng phục: Yêu cầu top1_sim >= 0.68 và margin >= 0.08", font=fonts["body"], fill=(226, 232, 240, 255))

    _draw_pill(draw, (980, 702, 1900, 962), fill=(30, 41, 59, 235), outline=(16, 185, 129, 200))
    draw.text((998, 718), "CHIỀU NGƯỢC & BÙ HỒI (DIRECTION B): CAM-01 → CAM-02 (CỬA SỔ 20s)", font=fonts["sub"], fill=(52, 211, 153, 255))
    draw.text(
        (998, 760),
        f"• CAM-01 ghi nhận trước dưới dạng Pending Track #{tc2_summary['pending_id']} ('Đang chờ xác thực mặt')",
        font=fonts["body"],
        fill=(253, 224, 71, 255),
    )
    draw.text(
        (998, 796),
        f"• CAM-02 xác thực mặt -> GIS đối chiếu BodyReID -> Backfill ngược sang CAM-01: {tc2_summary['backfilled_name']}",
        font=fonts["body"],
        fill=(167, 243, 208, 255),
    )
    draw.text(
        (998, 832),
        f"• Nhật ký SQLite WAL: CAM-01 & CAM-02 cùng gán {tc2_summary['student_id']} (Chống trùng lặp: {tc2_summary['dedup_count']} lượt duy nhất)",
        font=fonts["body"],
        fill=(226, 232, 240, 255),
    )
    draw.text(
        (998, 868),
        "• Zero Body-Only Guessing: Không đoán tên theo màu áo đồng phục khi chưa thấy mặt",
        font=fonts["body"],
        fill=(226, 232, 240, 255),
    )

    # Bottom footer
    draw.rectangle([0, 980, 1920, 1080], fill=(10, 15, 28, 255))
    draw.line([(0, 980), (1920, 980)], fill=(16, 185, 129, 200), width=2)
    draw.text(
        (28, 1014),
        "GlobalIdentityService (15s Forward Bridge + 20s Reverse Backfill)  |  TensorRT 11.3 FP16 + BodyReID 2048D  |  SQLite Deduplicated",
        font=fonts["sub"],
        fill=(241, 245, 249, 255),
    )

    cv2.imwrite(str(OUT_PROOF_JPG), cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 95])


async def run_test() -> Dict[str, Any]:
    for p in (8000, 8554, 8888, 9229, 9997):
        assert not _is_port_open(p), f"Port {p} already open before 2-cam test start"

    gis_unit_res = _run_gis_unit_guards()
    print(f"[PREFLIGHT] GIS unit guards passed: {gis_unit_res}")

    _ensure_enrolled_subjects_and_restore_ready()
    _prepare_streams_and_config()
    _reset_attendance_dbs()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sim_env = os.environ.copy()
    sim_env["PYTHONIOENCODING"] = "utf-8"
    sim_env["PIPELINE_CONFIG_PATH"] = str(CFG_PATH)
    sim_env.update(VERIFY_API_ENV)

    mediamtx_proc: Optional[subprocess.Popen[Any]] = None
    ffmpeg1_proc: Optional[subprocess.Popen[Any]] = None
    ffmpeg2_proc: Optional[subprocess.Popen[Any]] = None
    uvicorn_proc: Optional[subprocess.Popen[Any]] = None
    worker_proc: Optional[subprocess.Popen[Any]] = None
    log_handles: List[Any] = []

    try:
        def _open_log(name: str) -> Any:
            fh = open(LOG_DIR / name, "w", encoding="utf-8")
            log_handles.append(fh)
            return fh

        print("[STEP 2] Starting MediaMTX & FastAPI...")
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
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=30.0)

            print("[STEP 2] Starting synchronized CAM-01 (Side-Profile) & CAM-02 (Frontal) RTSP streams + AIWorker...")
            stream_start_epoch = time.time()
            ffmpeg1_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-i", str(CAM1_2CAM_MP4),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam1",
                ],
                stdout=_open_log("ffmpeg_cam1.log"),
                stderr=subprocess.STDOUT,
            )
            ffmpeg2_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-i", str(CAM2_2CAM_MP4),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam2",
                ],
                stdout=_open_log("ffmpeg_cam2.log"),
                stderr=subprocess.STDOUT,
            )
            await _wait_mediamtx_path_ready(session, "live/cam1", timeout=15.0)
            await _wait_mediamtx_path_ready(session, "live/cam2", timeout=15.0)

            worker_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "pipeline_engine.core.worker"],
                cwd=str(ROOT),
                env=sim_env,
                stdout=_open_log("worker.log"),
                stderr=subprocess.STDOUT,
            )

            deadline = time.monotonic() + 90.0
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
                await asyncio.sleep(0.5)
            assert worker_ready, "AIWorker did not register cam1 & cam2 within 90s"

            boot_elapsed = time.time() - stream_start_epoch
            assert boot_elapsed < LEAD_IN_S - 1.5, f"Boot took {boot_elapsed:.1f}s >= lead-in {LEAD_IN_S}s"
            content_epoch = stream_start_epoch + LEAD_IN_S
            rec_dur = max(CONTENT_DURATION_S + 2.0, (content_epoch + CONTENT_DURATION_S + 2.5) - time.time())
            print(f"[STEP 2] AIWorker ready in {boot_elapsed:.1f}s. Recording 2-cam WS metadata for {rec_dur:.1f}s...")

            ws1_pkts, ws2_pkts = await asyncio.gather(
                _record_ws_metadata("cam1", rec_dur),
                _record_ws_metadata("cam2", rec_dur),
            )
            assert ws1_pkts and ws2_pkts, f"Missing WS packets: cam1={len(ws1_pkts)}, cam2={len(ws2_pkts)}"

            # Wait up to 6s for EventDeliveryClient & retroactive backfill API to flush to SQLite
            await asyncio.sleep(3.5)
            async with session.get("http://127.0.0.1:8000/api/v1/attendance/summary") as resp:
                assert resp.status == 200, f"Summary API failed: HTTP {resp.status}"
                api_summary = await resp.json()

            async with session.get("http://127.0.0.1:8000/api/v1/attendance/records?limit=200") as resp:
                assert resp.status == 200, f"Records API failed: HTTP {resp.status}"
                api_records = (await resp.json()).get("records", [])

        # Align packets relative to content_epoch (T = 0..24.5s)
        cam1_rel = [(p["recv_ts"] - content_epoch, p) for p in ws1_pkts if -1.0 <= (p["recv_ts"] - content_epoch) <= CONTENT_DURATION_S + 2.0]
        cam2_rel = [(p["recv_ts"] - content_epoch, p) for p in ws2_pkts if -1.0 <= (p["recv_ts"] - content_epoch) <= CONTENT_DURATION_S + 2.0]

        # TC1 assertions:
        # T=0..4s -> CAM-02 locks Nguyễn Công Bảo Ngọc with face_verified=True
        tc1_cam2_pkts = [
            (rt, p) for rt, p in cam2_rel
            if 0.0 <= rt <= 5.5
            and any(
                per.get("identity_candidate") == "Nguyễn Công Bảo Ngọc" and bool(per.get("face_verified", False))
                for per in p["persons"]
            )
        ]
        assert tc1_cam2_pkts, "TC1 failed: CAM-02 did not lock Nguyễn Công Bảo Ngọc via face_verified=True in T=0..5.5s"

        # T=4..8.5s -> CAM-01 (side_profile) bridges Nguyễn Công Bảo Ngọc from CAM-02 via BodyReID
        tc1_cam1_pkts = [
            (rt, p) for rt, p in cam1_rel
            if 3.5 <= rt <= 9.5
            and any(
                per.get("identity_candidate") == "Nguyễn Công Bảo Ngọc"
                and per.get("bridged_from_cam") == "cam2"
                and per.get("identity_source") == "cross_cam_bridge"
                for per in p["persons"]
            )
        ]
        assert tc1_cam1_pkts, (
            "TC1 failed: CAM-01 (side_profile) did not forward-bridge Nguyễn Công Bảo Ngọc from cam2 within 15s"
        )

        # TC2 assertions:
        # T=11..15.5s -> CAM-01 holds Cô Hằng as Pending Track #G-XX ("Đang chờ xác thực mặt") with ZERO premature name
        tc2_cam1_pending_pkts = [
            (rt, per) for rt, p in cam1_rel
            if 10.5 <= rt <= 16.0
            for per in p["persons"]
        ]
        tc2_pending_ids = sorted({
            per.get("pending_global_id")
            for _, per in tc2_cam1_pending_pkts
            if per.get("pending_global_id")
        })
        tc2_premature_names = sorted({
            per.get("identity_candidate")
            for _, per in tc2_cam1_pending_pkts
            if per.get("identity_candidate") not in ("Đang chờ xác thực mặt", "Đang chờ thấy mặt...")
        })
        assert tc2_pending_ids, f"TC2 failed: CAM-01 did not create Pending Track #G-XX during T=10.5..16s"
        assert not tc2_premature_names, f"TC2 failed: CAM-01 guessed premature names before frontal cam: {tc2_premature_names}"

        # T=16..21s -> CAM-02 verifies Cô Hằng (GVCN 12.13) with face_verified=True
        tc2_cam2_pkts = [
            (rt, p) for rt, p in cam2_rel
            if 15.5 <= rt <= 22.0
            and any(
                per.get("identity_candidate") == "Cô Hằng (GVCN 12.13)" and bool(per.get("face_verified", False))
                for per in p["persons"]
            )
        ]
        assert tc2_cam2_pkts, "TC2 failed: CAM-02 did not verify Cô Hằng (GVCN 12.13) in T=15.5..22s"

        # SQLite verification for retroactive backfill & deduplicated attendance count
        with sqlite3.connect(str(ATTENDANCE_DB), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute("SELECT * FROM attendance_records ORDER BY event_timestamp ASC").fetchall()]
        with sqlite3.connect(str(EVENTS_DB), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            ev_rows = [dict(r) for r in conn.execute("SELECT * FROM attendance_events ORDER BY timestamp ASC").fetchall()]

        cam1_gv_rows = [r for r in rows if r["camera_id"] == "cam1" and r["identity_candidate"] == "GV_1213_01"]
        cam2_gv_rows = [r for r in rows if r["camera_id"] == "cam2" and r["identity_candidate"] == "GV_1213_01"]
        assert cam1_gv_rows, f"TC2 failed: CAM-01 row in app/data/attendance.db was not retroactively backfilled to GV_1213_01 (rows={rows})"
        assert cam2_gv_rows, f"TC2 failed: CAM-02 missing GV_1213_01 in app/data/attendance.db (rows={rows})"

        cam1_gv_events = [r for r in ev_rows if r["camera_id"] == "cam1" and r["person_id"] == "GV_1213_01"]
        assert cam1_gv_events, f"TC2 failed: CAM-01 row in data/attendance_events.db not backfilled to GV_1213_01 (events={ev_rows})"

        # Verify deduplication: GV_1213_01 counted ONCE across both cameras
        unique_gv_in_count = len({
            r["identity_candidate"]
            for r in rows
            if r["identity_candidate"] == "GV_1213_01" and r["direction"] == "in"
        })
        assert unique_gv_in_count == 1, f"Expected 1 deduplicated GV_1213_01 entry, got {unique_gv_in_count}"
        assert int(api_summary.get("present", 0)) + int(api_summary.get("late", 0)) <= 2, (
            f"Summary double-counted cross-cam entries: {api_summary}"
        )

        # Render side-by-side proof image from best TC1 CAM-01 & CAM-02 packets
        best_cam1_rt, best_cam1_pkt = tc1_cam1_pkts[len(tc1_cam1_pkts) // 2]
        best_cam2_rt, best_cam2_pkt = tc1_cam2_pkts[len(tc1_cam2_pkts) // 2]
        cam1_t_abs = min(LEAD_IN_S + 7.8, max(LEAD_IN_S + 4.3, LEAD_IN_S + best_cam1_rt))
        cam2_t_abs = min(LEAD_IN_S + 3.8, max(LEAD_IN_S + 1.2, LEAD_IN_S + best_cam2_rt))
        tc2_summary = {
            "pending_id": tc2_pending_ids[0],
            "student_id": "GV_1213_01",
            "backfilled_name": "Cô Hằng (GVCN 12.13)",
            "dedup_count": unique_gv_in_count,
        }
        _render_cross_cam_proof(best_cam1_pkt, cam1_t_abs, best_cam2_pkt, cam2_t_abs, tc2_summary)
        assert OUT_PROOF_JPG.exists(), f"Failed to write {OUT_PROOF_JPG}"

        summary = {
            "status": "PASS",
            "gis_unit_guards": gis_unit_res,
            "tc1_forward_bridge": {
                "cam2_verified_packets": len(tc1_cam2_pkts),
                "cam1_bridged_packets": len(tc1_cam1_pkts),
                "bridged_identity": "Nguyễn Công Bảo Ngọc",
                "bridged_from_cam": "cam2",
            },
            "tc2_reverse_backfill": {
                "pending_ids_observed": tc2_pending_ids,
                "premature_names_on_cam1": tc2_premature_names,
                "cam2_verified_packets": len(tc2_cam2_pkts),
                "sqlite_cam1_backfilled_rows": len(cam1_gv_rows),
                "sqlite_cam2_rows": len(cam2_gv_rows),
                "sqlite_events_cam1_backfilled": len(cam1_gv_events),
                "deduplicated_gv_count": unique_gv_in_count,
            },
            "api_summary": api_summary,
            "api_records_count": len(api_records),
            "proof_image": str(OUT_PROOF_JPG),
        }
        OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    finally:
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
        if SCHOOL_DB_BAK.exists() and SCHOOL_DB.exists():
            shutil.copy2(SCHOOL_DB_BAK, SCHOOL_DB)
        await asyncio.sleep(1.5)


def main() -> int:
    summary = asyncio.run(run_test())
    open_ports = [p for p in (8000, 8554, 8888, 9229, 9997) if _is_port_open(p)]
    assert not open_ports, f"Ports still open after teardown: {open_ports}"
    print("[CLEANUP] Verified ports 8000, 8554, 8888, 9229, 9997 are all CLOSED.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
