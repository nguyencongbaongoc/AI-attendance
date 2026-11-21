"""
Task 4: Offline Verification for Rotating UTF-8 Logging, Attendance Journal Filters,
Snapshot Static Serving, and Real .xlsx / UTF-8 BOM .csv Export via Headless Chromium.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import openpyxl
import websockets

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "artifacts"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _terminate_proc(proc: Optional[subprocess.Popen], name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception as exc:
            print(f"[CLEANUP] Warning killing {name}: {exc}")


async def _wait_http_200(session: aiohttp.ClientSession, url: str, timeout: float = 25.0) -> None:
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


def _seed_staging_data() -> Dict[str, Any]:
    """Seed Vietnamese students, attendance WAL records, and a real snapshot image."""
    from app.config.settings import load_settings
    from app.attendance.contract import AttendanceRecord, AttendanceDirection, IdentityCertainty
    from app.attendance.repository import create_attendance_repository

    settings = load_settings()
    data_dir = settings.paths.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Seed snapshot image in app/static/evidence/ (matching /static/evidence mount)
    evidence_dir = ROOT / "app" / "static" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    snap_path = evidence_dir / "test_snap_ngoc.jpg"
    src_jpg = ROOT / "PersonA.jpg"
    if src_jpg.exists():
        shutil.copyfile(src_jpg, snap_path)
    else:
        snap_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9")

    # 2. Seed Vietnamese students in school.db
    school_db = data_dir / "school.db"
    with sqlite3.connect(school_db) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                class_id TEXT NOT NULL,
                enrolled INTEGER DEFAULT 1
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO students (student_id, full_name, class_id, gender, enrollment_status, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            ("HS_TEST_001", "Nguyễn Công Bảo Ngọc", "Lớp 12.13", "Nữ", "enrolled", 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO students (student_id, full_name, class_id, gender, enrollment_status, is_active) VALUES (?, ?, ?, ?, ?, ?)",
            ("HS_TEST_002", "Trần Minh Khôi", "Lớp 12.13", "Nam", "enrolled", 1),
        )
        conn.commit()

    # 3. Seed attendance IN / OUT events via AttendanceRepository (SQLite WAL)
    repo = create_attendance_repository()
    now_ts = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")
    records = [
        AttendanceRecord(
            attendance_record_id="rec_audit_001",
            source_resolution_id="res_audit_001",
            source_raw_event_id="raw_audit_001",
            camera_id="cam1",
            local_track_id="101",
            global_observation_id="obs_audit_001",
            direction=AttendanceDirection.IN,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS_TEST_001",
            identity_confidence=0.96,
            event_timestamp=now_ts - 120.0,
            previous_state="unknown",
            new_state="inside",
            snapshot_face_url="/static/evidence/test_snap_ngoc.jpg",
            created_at=datetime.now().isoformat(),
            persisted_at=datetime.now().isoformat(),
        ),
        AttendanceRecord(
            attendance_record_id="rec_audit_002",
            source_resolution_id="res_audit_002",
            source_raw_event_id="raw_audit_002",
            camera_id="cam2",
            local_track_id="102",
            global_observation_id="obs_audit_002",
            direction=AttendanceDirection.OUT,
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="HS_TEST_002",
            identity_confidence=0.91,
            event_timestamp=now_ts - 60.0,
            previous_state="inside",
            new_state="outside",
            snapshot_face_url="/static/evidence/test_snap_ngoc.jpg",
            created_at=datetime.now().isoformat(),
            persisted_at=datetime.now().isoformat(),
        ),
    ]
    for r in records:
        repo.storage.insert(r)

    return {
        "today": today_str,
        "seeded_ids": ["rec_audit_001", "rec_audit_002"],
        "snapshot_url": "/static/evidence/test_snap_ngoc.jpg",
    }


def _cleanup_staging_data() -> None:
    from app.config.settings import load_settings
    settings = load_settings()
    data_dir = settings.paths.data_dir
    att_db = data_dir / "attendance.db"
    if att_db.exists():
        with sqlite3.connect(att_db) as conn:
            conn.execute("DELETE FROM attendance_records WHERE attendance_record_id IN ('rec_audit_001', 'rec_audit_002')")
            conn.commit()
    school_db = data_dir / "school.db"
    if school_db.exists():
        with sqlite3.connect(school_db) as conn:
            conn.execute("DELETE FROM students WHERE student_id IN ('HS_TEST_001', 'HS_TEST_002')")
            conn.commit()
    snap_path = ROOT / "app" / "static" / "evidence" / "test_snap_ngoc.jpg"
    if snap_path.exists():
        snap_path.unlink()


async def _run_ui_export_and_screenshot(download_dir: pathlib.Path, today_str: str) -> Dict[str, Any]:
    download_dir.mkdir(parents=True, exist_ok=True)
    for f in download_dir.glob("*"):
        f.unlink()

    user_data = ARTIFACTS / "_chrome_profile_audit"
    user_data.mkdir(parents=True, exist_ok=True)

    chrome_proc = subprocess.Popen(
        [
            CHROME_EXE,
            "--headless=new",
            "--disable-gpu-sandbox",
            "--no-sandbox",
            "--remote-debugging-port=9230",
            "--remote-allow-origins=*",
            "--window-size=1920,1080",
            f"--user-data-dir={user_data}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    console_errors: List[str] = []
    page_errors: List[str] = []
    http_errors: List[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9230/json/version", timeout=15.0)
            async with session.get("http://127.0.0.1:9230/json/list") as resp:
                targets = await resp.json()
            ws_url = next(t for t in targets if t.get("type") == "page")["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as cdp:
            msg_id = 0

            async def cdp_call(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
                nonlocal msg_id
                msg_id += 1
                cid = msg_id
                await cdp.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
                while True:
                    raw = await cdp.recv()
                    evt = json.loads(raw)
                    if evt.get("id") == cid:
                        if "error" in evt:
                            raise RuntimeError(f"CDP {method} error: {evt['error']}")
                        return evt.get("result", {})
                    elif evt.get("method") == "Runtime.exceptionThrown":
                        page_errors.append(evt.get("params", {}).get("exceptionDetails", {}).get("text", "exception"))
                    elif evt.get("method") == "Log.entryAdded":
                        entry = evt.get("params", {}).get("entry", {})
                        if entry.get("level") == "error":
                            console_errors.append(entry.get("text", "console error"))
                    elif evt.get("method") == "Network.responseReceived":
                        resp_obj = evt.get("params", {}).get("response", {})
                        if resp_obj.get("status", 200) >= 400:
                            http_errors.append(f"{resp_obj.get('status')} {resp_obj.get('url')}")

            await cdp_call("Page.enable")
            await cdp_call("Runtime.enable")
            await cdp_call("Log.enable")
            await cdp_call("Network.enable")
            await cdp_call("Browser.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": str(download_dir),
            })
            await cdp_call("Emulation.setDeviceMetricsOverride", {
                "width": 1920,
                "height": 1080,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            await cdp_call("Page.navigate", {"url": "http://127.0.0.1:8000/?offline=1"})
            await asyncio.sleep(3.0)

            # Navigate to Records page (#page-records) and filter by today
            await cdp_call("Runtime.evaluate", {
                "expression": f"""(() => {{
                    if (typeof switchPage === 'function') switchPage('records');
                    const d = document.getElementById('recDate');
                    if (d) d.value = '{today_str}';
                    if (typeof applyRecordsFilter === 'function') applyRecordsFilter();
                }})()""",
                "returnByValue": True,
            })
            await asyncio.sleep(2.5)

            # Capture screenshot of Attendance Journal & Export UI
            shot = await cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            (ARTIFACTS / "ui_journal_export_audit.png").write_bytes(base64.b64decode(shot["data"]))

            # Click the Export Excel button in #page-records
            await cdp_call("Runtime.evaluate", {
                "expression": "document.querySelector('#page-records button[onclick*=\"exportExcel\"]')?.click();",
                "returnByValue": True,
            })

            # Wait up to 10s for downloaded .xlsx file
            downloaded_xlsx: Optional[pathlib.Path] = None
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                cands = [p for p in download_dir.glob("*.xlsx") if not p.name.endswith(".crdownload")]
                if cands:
                    downloaded_xlsx = cands[0]
                    break
                await asyncio.sleep(0.3)

            assert downloaded_xlsx is not None, f"Excel download did not complete in {download_dir}"
            dest_xlsx = ARTIFACTS / "test_attendance_export.xlsx"
            shutil.copyfile(downloaded_xlsx, dest_xlsx)

            return {
                "downloaded_xlsx": str(dest_xlsx),
                "screenshot": str(ARTIFACTS / "ui_journal_export_audit.png"),
                "console_errors": console_errors,
                "page_errors": page_errors,
                "http_errors": http_errors,
            }
    finally:
        _terminate_proc(chrome_proc, "chrome")


async def run_audit() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log_file = ARTIFACTS / "test_backend_rotating.log"
    if log_file.exists():
        log_file.unlink()

    # Verify Task 1: RotatingFileHandler + UTF-8 logging
    from app.logging.logger import setup_logging
    import logging
    setup_logging(log_level="INFO", log_file=log_file)
    test_logger = logging.getLogger("audit.utf8")
    test_logger.info("Kiểm tra tiếng Việt: Nguyễn Công Bảo Ngọc — Lớp 12.13")
    for h in logging.getLogger().handlers:
        if hasattr(h, "flush"):
            h.flush()
    log_text = log_file.read_text(encoding="utf-8")
    assert "Nguyễn Công Bảo Ngọc — Lớp 12.13" in log_text, "UTF-8 Vietnamese log text missing!"
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) and h.maxBytes == 10 * 1024 * 1024 and h.backupCount == 5 for h in logging.getLogger().handlers), "RotatingFileHandler(10MB, backupCount=5) not active!"
    print("[TASK 1] RotatingFileHandler + UTF-8 Vietnamese logging PASSED")

    seeded = _seed_staging_data()
    uvicorn_proc = None
    try:
        env = os.environ.copy()
        env["LOG_FILE"] = str(log_file)
        uvicorn_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=25.0)

            # Task 2: Verify journal query filters + snapshot URL
            async with session.get(f"http://127.0.0.1:8000/api/v1/attendance/records?date={seeded['today']}&camera_id=cam1&direction=IN&status=PRESENT") as r:
                assert r.status == 200
                j1 = await r.json()
                ids1 = [x["attendance_record_id"] for x in j1["records"]]
                assert "rec_audit_001" in ids1 and "rec_audit_002" not in ids1, f"cam1/IN/PRESENT filter mismatch: {ids1}"

            async with session.get(f"http://127.0.0.1:8000/api/v1/attendance/records?start_date={seeded['today']}&end_date={seeded['today']}&camera_id=cam2&direction=OUT") as r:
                assert r.status == 200
                j2 = await r.json()
                ids2 = [x["attendance_record_id"] for x in j2["records"]]
                assert "rec_audit_002" in ids2 and "rec_audit_001" not in ids2, f"cam2/OUT filter mismatch: {ids2}"

            # Verify snapshot static route returns HTTP 200
            async with session.get(f"http://127.0.0.1:8000{seeded['snapshot_url']}") as sr:
                assert sr.status == 200, f"Snapshot URL returned {sr.status}"
                snap_bytes = await sr.read()
                assert len(snap_bytes) > 0
            print("[TASK 2] Journal filters (date/range/cam/direction/status) & snapshot HTTP 200 PASSED")

            # Task 3: Verify UTF-8 BOM CSV export
            async with session.get(f"http://127.0.0.1:8000/api/v1/attendance/export?format=csv&date={seeded['today']}") as cr:
                assert cr.status == 200
                csv_raw = await cr.read()
                assert csv_raw.startswith(b"\xef\xbb\xbf"), "CSV export missing UTF-8 BOM!"
                csv_text = csv_raw.decode("utf-8-sig")
                assert "Nguyễn Công Bảo Ngọc" in csv_text and "Lớp 12.13" in csv_text
            print("[TASK 3] UTF-8 BOM CSV export PASSED")

            # Task 4: Headless Chromium UI Export + openpyxl validation
            ui_res = await _run_ui_export_and_screenshot(ARTIFACTS / "_downloads", seeded["today"])
            assert len(ui_res["console_errors"]) == 0, f"Console errors: {ui_res['console_errors']}"
            assert len(ui_res["page_errors"]) == 0, f"Page errors: {ui_res['page_errors']}"
            assert len(ui_res["http_errors"]) == 0, f"HTTP errors: {ui_res['http_errors']}"

            wb = openpyxl.load_workbook(ui_res["downloaded_xlsx"])
            assert "Nhat_Ky_Diem_Danh" in wb.sheetnames, f"Missing Nhat_Ky_Diem_Danh in {wb.sheetnames}"
            assert "Tong_Hop_Si_So" in wb.sheetnames, f"Missing Tong_Hop_Si_So in {wb.sheetnames}"

            ws1 = wb["Nhat_Ky_Diem_Danh"]
            assert ws1.freeze_panes == "A2", f"Unexpected freeze_panes: {ws1.freeze_panes}"
            rows_text = "\n".join(str([c.value for c in row]) for row in ws1.iter_rows(min_row=1))
            assert "Nguyễn Công Bảo Ngọc" in rows_text, "Vietnamese name missing in .xlsx!"
            assert "Lớp 12.13" in rows_text, "Vietnamese class missing in .xlsx!"
            assert ws1.max_row >= 3, f"Expected >= 3 rows (header + 2 seeded), got {ws1.max_row}"

            ws2 = wb["Tong_Hop_Si_So"]
            sum_headers = [c.value for c in ws2[1]]
            assert sum_headers == ["Tổng số", "Có mặt", "Đi trễ", "Vắng mặt", "Tỷ lệ chuyên cần %"], f"Unexpected summary headers: {sum_headers}"
            print(f"[TASK 4] Real .xlsx UI download & openpyxl audit PASSED (sheets={wb.sheetnames}, rows={ws1.max_row})")

    finally:
        _terminate_proc(uvicorn_proc, "uvicorn")
        _cleanup_staging_data()
        await asyncio.sleep(0.5)
        assert not _is_port_open("127.0.0.1", 8000), "Port 8000 still open after cleanup!"


if __name__ == "__main__":
    asyncio.run(run_audit())
