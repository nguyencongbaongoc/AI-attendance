"""
Live Interactive UI-to-Backend E2E Verification Suite for ATTENDANCE OS.

Starts a real local FastAPI server (plus MediaMTX + FFmpeg loop if simulation videos
exist so HLS playback produces 0 network errors), seeds clean staging SQLite data +
evidence snapshots, and drives every page, filter, modal, WebSocket, and Excel export
in headless Chromium over Chrome DevTools Protocol (WITHOUT ?offline=1 mocking).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiohttp
import openpyxl
import websockets

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.attendance.contract import AttendanceDirection, AttendanceRecord, IdentityCertainty
from app.attendance.storage import AttendanceStorage

ARTIFACTS = ROOT / "artifacts"
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
UVICORN_LOG = ARTIFACTS / "ui_e2e_uvicorn.log"


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


async def wait_http_200(url: str, timeout: float = 25.0) -> None:
    deadline = time.time() + timeout
    async with aiohttp.ClientSession() as session:
        while time.time() < deadline:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                pass
            await asyncio.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for {url}")


def seed_staging_databases() -> Dict[str, str]:
    """Seed deterministic staging DBs + evidence snapshots."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    data_dir = ROOT / "app" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    evidence_dir = ROOT / "app" / "static" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    face_src = ROOT / "cam1_frame.jpg"
    scene_src = ROOT / "cam1_frame.jpg"
    shutil.copyfile(face_src, evidence_dir / "e2e_face.jpg")
    shutil.copyfile(scene_src, evidence_dir / "e2e_scene.jpg")

    school_db = data_dir / "school.db"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(school_db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classes (
                class_id TEXT PRIMARY KEY,
                class_name TEXT NOT NULL,
                grade_level INTEGER DEFAULT 10,
                shift_start_time TEXT DEFAULT '07:00',
                late_threshold_time TEXT DEFAULT '07:00',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
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
        conn.execute("DELETE FROM students")
        conn.execute("DELETE FROM classes")
        conn.execute(
            "INSERT INTO classes (class_id, class_name, grade_level, shift_start_time, late_threshold_time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("10A1", "10A1", 10, "07:00", "07:00", now_iso),
        )
        conn.execute(
            "INSERT INTO classes (class_id, class_name, grade_level, shift_start_time, late_threshold_time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("10A2", "10A2", 10, "07:00", "07:00", now_iso),
        )

        emb_dir = data_dir / "embeddings"
        emb_dir.mkdir(parents=True, exist_ok=True)
        students = [
            ("SIM_HS_01", "Nguyễn Công Bảo Ngọc", "10A1", str(emb_dir / "SIM_HS_01.npy"), "ENROLLED", 1),
            ("SIM_HS_02", "Trần Minh Quân", "10A1", str(emb_dir / "SIM_HS_02.npy"), "ENROLLED", 1),
            ("SIM_HS_03", "Lê Thị Hương", "10A1", None, "PENDING", 1),
            ("SIM_HS_04", "Phạm Gia Bảo", "10A1", None, "PENDING", 1),
            ("SIM_HS_05", "Võ Minh Khang", "10A2", None, "PENDING", 1),
        ]
        for sid, name, cid, epath, st, active in students:
            conn.execute(
                """
                INSERT INTO students (
                    student_id, full_name, class_id, gender, embedding_path,
                    enrollment_status, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'OTHER', ?, ?, ?, ?, ?)
                """,
                (sid, name, cid, epath, st, active, now_iso, now_iso),
            )
        conn.commit()

    att_db = data_dir / "attendance.db"
    with sqlite3.connect(att_db) as conn:
        conn.execute("DROP TABLE IF EXISTS attendance_records")
        conn.commit()
    storage = AttendanceStorage()

    base_ts = time.time() - 120.0
    seeded_records = [
        AttendanceRecord(
            attendance_record_id="ATT_E2E_01",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="SIM_HS_01",
            identity_confidence=0.92,
            snapshot_face_url="/static/evidence/e2e_face.jpg",
            snapshot_scene_url="/static/evidence/e2e_scene.jpg",
            direction=AttendanceDirection.IN,
            event_timestamp=base_ts,
            event_frame_index=10,
            camera_id="cam1",
            local_track_id="1",
            source_raw_event_id="RAW_E2E_01",
            source_resolution_id="RES_E2E_01",
            previous_state="outside",
            new_state="PRESENT",
        ),
        AttendanceRecord(
            attendance_record_id="ATT_E2E_02",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="SIM_HS_01",
            identity_confidence=0.91,
            snapshot_face_url="/static/evidence/e2e_face.jpg",
            snapshot_scene_url="/static/evidence/e2e_scene.jpg",
            direction=AttendanceDirection.OUT,
            event_timestamp=base_ts + 20.0,
            event_frame_index=20,
            camera_id="cam1",
            local_track_id="1",
            source_raw_event_id="RAW_E2E_02",
            source_resolution_id="RES_E2E_02",
            previous_state="inside",
            new_state="outside",
        ),
        AttendanceRecord(
            attendance_record_id="ATT_E2E_03",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="SIM_HS_01",
            identity_confidence=0.93,
            snapshot_face_url="/static/evidence/e2e_face.jpg",
            snapshot_scene_url="/static/evidence/e2e_scene.jpg",
            direction=AttendanceDirection.IN,
            event_timestamp=base_ts + 40.0,
            event_frame_index=30,
            camera_id="cam1",
            local_track_id="2",
            source_raw_event_id="RAW_E2E_03",
            source_resolution_id="RES_E2E_03",
            previous_state="outside",
            new_state="PRESENT",
        ),
        AttendanceRecord(
            attendance_record_id="ATT_E2E_04",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="SIM_HS_01",
            identity_confidence=0.90,
            snapshot_face_url="/static/evidence/e2e_face.jpg",
            snapshot_scene_url="/static/evidence/e2e_scene.jpg",
            direction=AttendanceDirection.IN,
            event_timestamp=base_ts + 60.0,
            event_frame_index=40,
            camera_id="cam1",
            local_track_id="3",
            source_raw_event_id="RAW_E2E_04",
            source_resolution_id="RES_E2E_04",
            previous_state="outside",
            new_state="PRESENT",
        ),
        AttendanceRecord(
            attendance_record_id="ATT_E2E_05",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="SIM_HS_02",
            identity_confidence=0.88,
            snapshot_face_url="/static/evidence/e2e_face.jpg",
            snapshot_scene_url="/static/evidence/e2e_scene.jpg",
            direction=AttendanceDirection.IN,
            event_timestamp=base_ts + 80.0,
            event_frame_index=50,
            camera_id="cam2",
            local_track_id="4",
            source_raw_event_id="RAW_E2E_05",
            source_resolution_id="RES_E2E_05",
            previous_state="outside",
            new_state="LATE",
        ),
    ]
    for rec in seeded_records:
        storage.insert(rec)

    return {"today": datetime.now().strftime("%Y-%m-%d")}


def create_temp_roster_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["student_id", "full_name", "class_name", "gender"])
    ws.append(["E2E_IMP_01", "Đặng Hoàng Minh", "10A2", "MALE"])
    wb.save(path)


def post_metadata_frame(camera_id: str, seq: int) -> None:
    payload = json.dumps(
        {
            "camera_id": camera_id,
            "frame_sequence": seq,
            "timestamp": time.time(),
            "persons": [
                {
                    "track_id": 1,
                    "bbox": [0.28, 0.14, 0.72, 0.86],
                    "confidence": 0.94,
                    "identity_candidate": "Nguyễn Công Bảo Ngọc",
                    "identity_confidence": 0.93,
                    "state": "active",
                }
            ],
            "faces": [
                {
                    "track_id": 1,
                    "bbox": [0.42, 0.20, 0.58, 0.48],
                    "confidence": 0.91,
                    "identity_candidate": "Nguyễn Công Bảo Ngọc",
                }
            ],
            "counts": {"in": 3, "out": 1},
            "crossing_line": {"coords": [[0.15, 0.62], [0.85, 0.62]], "status": "IN_TRANSITION"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/stream/metadata/ingest",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        assert resp.status == 200


class CDPClient:
    """Minimal asyncio Chrome DevTools Protocol driver with event tracking."""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0
        self._pending: Dict[int, asyncio.Future[Dict[str, Any]]] = {}
        self._reader_task: Optional[asyncio.Task[None]] = None
        self.bad_responses: List[Dict[str, Any]] = []
        self.all_responses: List[Dict[str, Any]] = []
        self.console_errors: List[str] = []
        self.page_errors: List[str] = []

    async def __aenter__(self) -> "CDPClient":
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
            else:
                method = evt.get("method")
                params = evt.get("params", {})
                if method == "Network.responseReceived":
                    resp = params.get("response", {})
                    url = resp.get("url", "")
                    status = int(resp.get("status", 0))
                    rec = {"url": url, "status": status}
                    self.all_responses.append(rec)
                    if (url.startswith("http://127.0.0.1:8000") or url.startswith("http://localhost:8000")) and status >= 400:
                        self.bad_responses.append(rec)
                elif method == "Runtime.exceptionThrown":
                    desc = params.get("exceptionDetails", {}).get("text", "Runtime exception")
                    self.page_errors.append(desc)
                elif method == "Runtime.consoleAPICalled":
                    if params.get("type") == "error":
                        args = [str(a.get("value", a.get("description", ""))) for a in params.get("args", [])]
                        self.console_errors.append(" ".join(args))
                elif method == "Log.entryAdded":
                    entry = params.get("entry", {})
                    if entry.get("level") == "error":
                        self.console_errors.append(entry.get("text", "Log error"))

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
        deadline = time.time() + timeout
        while time.time() < deadline:
            val = await self.eval(predicate_js, await_promise=False)
            if val:
                return val
            await asyncio.sleep(0.2)
        raise TimeoutError(f"Timed out waiting for JS condition: {predicate_js[:140]}")

    async def wait_for_response(self, url_substr: str, action_coro: Callable[[], Any], timeout: float = 15.0) -> Dict[str, Any]:
        start_idx = len(self.all_responses)
        await action_coro()
        deadline = time.time() + timeout
        while time.time() < deadline:
            for rec in self.all_responses[start_idx:]:
                if url_substr in rec["url"]:
                    return rec
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Timed out waiting for response matching '{url_substr}'")

    async def set_file_input(self, selector: str, file_path: Path) -> None:
        doc = await self.call("DOM.getDocument", {"depth": -1})
        node = await self.call("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": selector})
        assert node.get("nodeId", 0) > 0, f"Selector not found for file input: {selector}"
        await self.call("DOM.setFileInputFiles", {"nodeId": node["nodeId"], "files": [str(file_path)]})

    async def drag_mouse(self, x1: float, y1: float, x2: float, y2: float, steps: int = 8) -> None:
        await self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x1, "y": y1})
        await self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x1, "y": y1, "button": "left", "clickCount": 1})
        for i in range(1, steps + 1):
            ix = x1 + (x2 - x1) * (i / steps)
            iy = y1 + (y2 - y1) * (i / steps)
            await self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": ix, "y": iy, "button": "left"})
            await asyncio.sleep(0.02)
        await self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x2, "y": y2, "button": "left", "clickCount": 1})

    async def screenshot(self, out_path: Path) -> None:
        shot = await self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
        out_path.write_bytes(base64.b64decode(shot["data"]))


def terminate_proc(proc: Optional[subprocess.Popen[Any]]) -> None:
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


async def run_e2e_async() -> None:
    pipeline_yaml = ROOT / "pipeline_engine" / "config" / "pipeline.yaml"
    original_pipeline_yaml = pipeline_yaml.read_text(encoding="utf-8") if pipeline_yaml.exists() else None

    procs: List[subprocess.Popen[Any]] = []
    temp_roster_xlsx = ARTIFACTS / "_e2e_roster_import.xlsx"
    dl_dir = ARTIFACTS / "_e2e_downloads"
    chrome_profile = ARTIFACTS / "_e2e_chrome_profile"
    if dl_dir.exists():
        shutil.rmtree(dl_dir, ignore_errors=True)
    dl_dir.mkdir(parents=True, exist_ok=True)
    chrome_profile.mkdir(parents=True, exist_ok=True)
    create_temp_roster_xlsx(temp_roster_xlsx)

    try:
        seed_info = seed_staging_databases()
        today_str = seed_info["today"]

        mediamtx_exe = ROOT / "mediamtx" / "mediamtx.exe"
        mediamtx_yml = ROOT / "mediamtx" / "mediamtx.yml"
        cam1_mp4 = ARTIFACTS / "sim_human_cam1.mp4"
        cam2_mp4 = ARTIFACTS / "sim_human_cam2.mp4"
        ffmpeg_bin = shutil.which("ffmpeg")
        if mediamtx_exe.exists() and mediamtx_yml.exists() and cam1_mp4.exists() and cam2_mp4.exists() and ffmpeg_bin:
            procs.append(
                subprocess.Popen(
                    [str(mediamtx_exe), str(mediamtx_yml)],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            await asyncio.sleep(1.2)
            for cid, mp4 in (("cam1", cam1_mp4), ("cam2", cam2_mp4)):
                procs.append(
                    subprocess.Popen(
                        [ffmpeg_bin, "-re", "-stream_loop", "-1", "-i", str(mp4), "-c", "copy", "-f", "rtsp", f"rtsp://127.0.0.1:8554/live/{cid}"],
                        cwd=str(ROOT),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                )
            await asyncio.sleep(2.0)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        uvicorn_log_f = open(UVICORN_LOG, "w", encoding="utf-8")
        uvicorn_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            env=env,
            stdout=uvicorn_log_f,
            stderr=subprocess.STDOUT,
        )
        procs.append(uvicorn_proc)
        await wait_http_200("http://127.0.0.1:8000/api/v1/health/live", timeout=30.0)

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
        procs.append(chrome_proc)
        await wait_http_200("http://127.0.0.1:9229/json/version", timeout=15.0)
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:9229/json/list") as r:
                targets = await r.json()
            ws_url = next(t for t in targets if t.get("type") == "page")["webSocketDebuggerUrl"]

        async with CDPClient(ws_url) as cdp:
            await cdp.call("Page.enable")
            await cdp.call("DOM.enable")
            await cdp.call("Network.enable")
            await cdp.call("Runtime.enable")
            await cdp.call("Log.enable")
            await cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False},
            )
            await cdp.call(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(dl_dir)},
            )

            # A. DASHBOARD (#page-dashboard)
            await cdp.call("Page.navigate", {"url": "http://127.0.0.1:8000/"})
            await cdp.wait_for_js("document.getElementById('statTotalStudents')?.textContent?.trim() === '5'", timeout=15.0)
            await cdp.wait_for_js("document.getElementById('recentAttendanceList')?.innerText?.includes('Nguyễn Công Bảo Ngọc')", timeout=10.0)
            dash_kpis = await cdp.eval(
                """({
                    total: document.getElementById('statTotalStudents')?.textContent?.trim(),
                    present: document.getElementById('statPresent')?.textContent?.trim(),
                    late: document.getElementById('statLate')?.textContent?.trim(),
                    absent: document.getElementById('statAbsent')?.textContent?.trim(),
                    gpu: document.getElementById('gaugeGpuName')?.textContent?.trim(),
                    cam1fps: document.getElementById('cam1Fps')?.textContent?.trim(),
                })"""
            )
            assert dash_kpis["total"] == "5", dash_kpis
            assert dash_kpis["present"] == "1", dash_kpis
            assert dash_kpis["late"] == "1", dash_kpis
            assert dash_kpis["absent"] == "3", dash_kpis
            assert dash_kpis["gpu"], dash_kpis
            await asyncio.sleep(1.5)
            await cdp.screenshot(ARTIFACTS / "ui_e2e_dashboard.png")
            print("[E2E A] Dashboard verified:", dash_kpis)

            # B. LIVE MONITORING (#page-live)
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"live\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-live').classList.contains('hidden') && lines1.length > 0", timeout=10.0)

            # Drag crossing line in edit mode & click Save Lines
            await cdp.eval("document.getElementById('btnEdit').click()")
            drag_info = await cdp.eval(
                """(() => {
                    const c = document.getElementById('canvas1');
                    const r = c.getBoundingClientRect();
                    const l = lines1[lines1.length - 1];
                    const midX = r.left + (l.x1 + l.x2) / 2;
                    const midY = r.top + (l.y1 + l.y2) / 2;
                    const targetY = r.top + r.height * 0.62;
                    const dy = Math.abs(targetY - midY) < 35 ? -45 : (targetY - midY);
                    return { midX, midY, toY: midY + dy };
                })()"""
            )
            await cdp.drag_mouse(drag_info["midX"], drag_info["midY"], drag_info["midX"], drag_info["toY"])
            await asyncio.sleep(0.2)
            expected_ny = await cdp.eval(
                "(() => { const r = document.getElementById('canvas1').getBoundingClientRect(); const l = lines1[lines1.length - 1]; return Number((l.y1 / r.height).toFixed(4)); })()"
            )

            save_resp = await cdp.wait_for_response(
                "/api/v1/cameras/cam1/line",
                lambda: cdp.eval("document.querySelector('button[onclick=\"saveLines()\"]').click()"),
            )
            assert save_resp["status"] == 200, save_resp
            await asyncio.sleep(0.3)

            # Reload page & verify backend persistence re-rendered on #canvas1
            await cdp.call("Page.reload", {"ignoreCache": True})
            await cdp.wait_for_js(
                "Boolean(document.querySelector('.nav-btn[data-page=\"live\"]')) && Boolean(appState?.geometryConfigs?.cam1)",
                timeout=15.0,
            )
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"live\"]').click()")
            await cdp.wait_for_js(
                "!document.getElementById('page-live').classList.contains('hidden') && appState.geometryConfigs?.cam1 && lines1.length > 0",
                timeout=10.0,
            )
            persisted_ny = await cdp.eval("appState.geometryConfigs.cam1.normalized_line[0][1]")
            assert abs(float(persisted_ny) - float(expected_ny)) < 0.02, f"Expected persisted ny={expected_ny}, got {persisted_ny}"

            # Inject WebSocket metadata frame & verify #10b981 box + Vietnamese name + IN/OUT counter
            stop_inj = threading.Event()

            def injector() -> None:
                seq = 1
                while not stop_inj.is_set():
                    try:
                        post_metadata_frame("cam1", seq)
                        seq += 1
                    except Exception:
                        pass
                    time.sleep(0.15)

            inj_thread = threading.Thread(target=injector, daemon=True)
            inj_thread.start()
            try:
                await cdp.wait_for_js(
                    "document.getElementById('aiTrackingText1')?.textContent?.includes('IN: 3 / OUT: 1')",
                    timeout=10.0,
                )
                await asyncio.sleep(0.4)
                await cdp.screenshot(ARTIFACTS / "ui_e2e_live.png")
            finally:
                stop_inj.set()
                inj_thread.join(timeout=2.0)
            print(f"[E2E B] Live Monitoring & line persistence verified: saved ny={expected_ny}, persisted={persisted_ny}")

            # C. RECORDS, FILTERS, EVIDENCE & EXCEL EXPORT (#page-records)
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"records\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-records').classList.contains('hidden') && document.querySelectorAll('#recordsBody tr').length >= 4", timeout=10.0)

            for label, js_expr, expected_substr in [
                ("date", f"(() => {{ const el = document.getElementById('recDate'); el.value = '{today_str}'; el.dispatchEvent(new Event('change')); }})()", ""),
                ("cam1", "(() => { const el = document.getElementById('recCam'); el.value = 'cam1'; el.dispatchEvent(new Event('change')); })()", "cam1"),
                ("in", "(() => { const el = document.getElementById('recType'); el.value = 'in'; el.dispatchEvent(new Event('change')); })()", "IN"),
                ("PRESENT", "(() => { const el = document.getElementById('recStatus'); el.value = 'PRESENT'; el.dispatchEvent(new Event('change')); })()", "Nguyễn Công Bảo Ngọc"),
            ]:
                resp = await cdp.wait_for_response("/api/v1/attendance/records", lambda e=js_expr: cdp.eval(e))
                assert resp["status"] == 200, resp
                await asyncio.sleep(0.25)
                if expected_substr:
                    txt = await cdp.eval("document.getElementById('recordsBody').innerText")
                    assert expected_substr in txt, f"Filter {label} missing '{expected_substr}': {txt}"

            # Check LATE filter
            resp_late = await cdp.wait_for_response(
                "/api/v1/attendance/records",
                lambda: cdp.eval(
                    "(() => { document.getElementById('recCam').value = ''; const s = document.getElementById('recStatus'); s.value = 'LATE'; s.dispatchEvent(new Event('change')); })()"
                ),
            )
            assert resp_late["status"] == 200
            await asyncio.sleep(0.25)
            late_txt = await cdp.eval("document.getElementById('recordsBody').innerText")
            assert "Trần Minh Quân" in late_txt, late_txt

            # Clear filters back to view full records table
            resp_clr = await cdp.wait_for_response(
                "/api/v1/attendance/records",
                lambda: cdp.eval(
                    "(() => { document.getElementById('recType').value = ''; document.getElementById('recStatus').value = ''; document.getElementById('recStatus').dispatchEvent(new Event('change')); })()"
                ),
            )
            assert resp_clr["status"] == 200
            await cdp.wait_for_js("document.querySelectorAll('#recordsBody tr').length >= 5", timeout=10.0)
            await cdp.screenshot(ARTIFACTS / "ui_e2e_records.png")

            # Click snapshot evidence preview button and verify image loads HTTP 200
            ev_resp = await cdp.wait_for_response(
                "/static/evidence/",
                lambda: cdp.eval("document.querySelector('#recordsBody .btn-evidence-preview').click()"),
            )
            assert ev_resp["status"] == 200, ev_resp
            await cdp.wait_for_js(
                "document.getElementById('evidenceModal').classList.contains('flex') && Array.from(document.querySelectorAll('#evidenceImages img')).every(i => i.complete && i.naturalWidth > 0)",
                timeout=8.0,
            )
            await cdp.eval("closeEvidenceModal()")

            # Click Export Excel & verify downloaded workbook
            exp_resp = await cdp.wait_for_response(
                "/api/v1/attendance/export",
                lambda: cdp.eval("exportExcel()"),
            )
            assert exp_resp["status"] == 200, exp_resp
            deadline = time.time() + 10.0
            dl_files: List[Path] = []
            while time.time() < deadline:
                dl_files = [p for p in dl_dir.glob("*.xlsx") if not p.name.endswith(".crdownload")]
                if dl_files:
                    break
                await asyncio.sleep(0.2)
            assert dl_files, "No downloaded .xlsx file found"
            verified_xlsx = ARTIFACTS / "ui_verified_export.xlsx"
            shutil.copyfile(dl_files[0], verified_xlsx)

            wb = openpyxl.load_workbook(verified_xlsx)
            assert wb.sheetnames == ["Nhat_Ky_Diem_Danh", "Tong_Hop_Si_So"], wb.sheetnames
            ws1, ws2 = wb["Nhat_Ky_Diem_Danh"], wb["Tong_Hop_Si_So"]
            row2 = [ws2.cell(2, col).value for col in range(1, ws2.max_column + 1)]
            assert row2 == [5, 1, 1, 3, 40.0], f"Unexpected Tong_Hop_Si_So: {row2}"
            names_xlsx = {ws1.cell(r, 3).value for r in range(2, ws1.max_row + 1)}
            assert "Nguyễn Công Bảo Ngọc" in names_xlsx and "Trần Minh Quân" in names_xlsx, names_xlsx
            print("[E2E C] Records, evidence modal, and Excel export verified:", row2)

            # D. STUDENT ROSTER, SEARCH, ENROLLMENT MODAL & EXCEL IMPORT (#page-students)
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"students\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-students').classList.contains('hidden') && document.querySelectorAll('#studentsBody tr').length >= 5", timeout=10.0)

            # Backend search query
            s_resp = await cdp.wait_for_response(
                "/api/v1/students",
                lambda: cdp.eval("(() => { const el = document.getElementById('studentSearch'); el.value = 'Quân'; filterStudents(); })()"),
            )
            assert s_resp["status"] == 200
            await asyncio.sleep(0.2)
            assert "Trần Minh Quân" in await cdp.eval("document.getElementById('studentsBody').innerText")
            await cdp.wait_for_response(
                "/api/v1/students",
                lambda: cdp.eval("(() => { const el = document.getElementById('studentSearch'); el.value = ''; filterStudents(); })()"),
            )
            await cdp.wait_for_js("document.querySelectorAll('#studentsBody tr').length >= 5", timeout=8.0)

            # Face photo enrollment via #enrollmentModal on SIM_HS_03
            await cdp.eval(
                "Array.from(document.querySelectorAll('#studentsBody tr')).find(tr => tr.textContent.includes('SIM_HS_03')).querySelector('button').click()"
            )
            await cdp.wait_for_js("document.getElementById('enrollmentModal').classList.contains('flex')", timeout=5.0)
            await cdp.eval("openPhotoUpload()")
            await cdp.set_file_input("#enrollPhotoInput", ROOT / "cam1_frame.jpg")
            await cdp.wait_for_js("!document.getElementById('btnSubmitEnrollment').disabled", timeout=5.0)
            enr_resp = await cdp.wait_for_response(
                "/api/v1/enrollment/persons",
                lambda: cdp.eval("submitEnrollment()"),
                timeout=20.0,
            )
            assert enr_resp["status"] == 200, enr_resp
            await cdp.wait_for_js(
                "!document.getElementById('enrollResult').classList.contains('hidden') && document.getElementById('enrollResult').innerText.includes('Đăng ký thành công')",
                timeout=10.0,
            )
            await cdp.eval("closeEnrollmentModal()")
            await cdp.wait_for_js(
                "Array.from(document.querySelectorAll('#studentsBody tr')).find(tr => tr.textContent.includes('SIM_HS_03'))?.innerText?.includes('ĐÃ ĐĂNG KÝ')",
                timeout=10.0,
            )

            # Excel Roster Import modal (tests multipart FormData fix)
            await cdp.eval("openImportModal()")
            await cdp.wait_for_js("document.getElementById('importModal').classList.contains('flex')", timeout=5.0)
            await cdp.set_file_input("#excelFileInput", temp_roster_xlsx)
            await cdp.wait_for_js("!document.getElementById('btnConfirmImport').disabled", timeout=10.0)
            imp_resp = await cdp.wait_for_response(
                "/api/v1/students/import",
                lambda: cdp.eval("confirmImport()"),
                timeout=15.0,
            )
            assert imp_resp["status"] == 200, imp_resp
            await cdp.wait_for_js("document.getElementById('studentsBody').innerText.includes('Đặng Hoàng Minh')", timeout=10.0)
            await cdp.eval("closeImportModal()")
            await cdp.screenshot(ARTIFACTS / "ui_e2e_students.png")
            print("[E2E D] Student search, face enrollment, and multipart Excel import verified!")

            # E. REMAINING TABS (ArcFace, Video Review, Backend Health, Worker Control)
            await cdp.eval("document.querySelector('.nav-btn[data-page=\"arcface\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-arcface').classList.contains('hidden')", timeout=8.0)
            await cdp.set_file_input("#fileInput", ROOT / "cam1_frame.jpg")
            await asyncio.sleep(0.2)
            det_resp = await cdp.wait_for_response(
                "/api/v1/enrollment/detect",
                lambda: cdp.eval("document.getElementById('btnDetect').click()"),
                timeout=20.0,
            )
            assert det_resp["status"] == 200, det_resp

            await cdp.eval("document.querySelector('.nav-btn[data-page=\"video\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-review').classList.contains('hidden')", timeout=8.0)
            await asyncio.sleep(0.3)

            await cdp.eval("document.querySelector('.nav-btn[data-page=\"health\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-health').classList.contains('hidden')", timeout=8.0)
            await asyncio.sleep(0.3)

            await cdp.eval("document.querySelector('.nav-btn[data-page=\"worker\"]').click()")
            await cdp.wait_for_js("!document.getElementById('page-worker').classList.contains('hidden')", timeout=8.0)
            ctrl_resp = await cdp.wait_for_response(
                "/api/v1/ai-worker/control/GET_STATUS",
                lambda: cdp.eval("document.getElementById('getStatusBtn').click()"),
                timeout=10.0,
            )
            assert ctrl_resp["status"] == 200, ctrl_resp
            await asyncio.sleep(0.3)

            assert not cdp.bad_responses, f"HTTP >= 400 responses observed: {cdp.bad_responses}"
            assert not cdp.console_errors, f"Browser console errors: {cdp.console_errors}"
            assert not cdp.page_errors, f"Uncaught page errors: {cdp.page_errors}"
            print(f"[E2E E] Remaining tabs verified! Total HTTP responses={len(cdp.all_responses)}, errors=0.")

    finally:
        for proc in reversed(procs):
            terminate_proc(proc)
        if original_pipeline_yaml is not None:
            pipeline_yaml.write_text(original_pipeline_yaml, encoding="utf-8")
        if temp_roster_xlsx.exists():
            temp_roster_xlsx.unlink()
        shutil.rmtree(dl_dir, ignore_errors=True)
        shutil.rmtree(chrome_profile, ignore_errors=True)

        open_ports = [p for p in (8000, 8554, 8888, 9229, 9997) if is_port_open(p)]
        assert not open_ports, f"Ports still open after teardown: {open_ports}"
        print("Verified ports 8000, 8554, 8888, 9229, 9997 are all CLOSED.")


if __name__ == "__main__":
    asyncio.run(run_e2e_async())
