"""
STREAM 3: Full End-to-End Camera-Free Simulation Runner (100% Offline).

Orchestrates all 3 synchronized simulation streams simultaneously:
  Stream 1: Simulated Human Video -> MediaMTX -> Dual FFmpeg RTSP (cam1 & cam2)
  Stream 2: Simulated .NPY 512D Embeddings -> SQLite + ArcFace + Rust GalleryIndexRs
  Stream 3: FastAPI + AIWorker (NVDEC + TensorRT 11.3 FP16) + WebSocket + Chromium UI + .xlsx
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set

import aiohttp
import openpyxl
import websockets

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sim_human_rtsp_stream import (
    RTSPSimPublisher,
    generate_human_videos,
    probe_generated_videos,
)
from scripts.sim_npy_stream import (
    generate_npy_artifacts,
    seed_database_and_hot_reload_files,
    verify_rust_gallery_and_arcface_reload,
)

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
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {url} (last: {last_err})")


def _get_gpu_vram_mb(pid: Optional[int] = None) -> float:
    if pid is not None:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            text=True,
        )
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == pid:
                try:
                    return float(parts[1])
                except ValueError:
                    pass
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True,
    )
    return float(out.strip().splitlines()[0])


async def _subscribe_metadata(cam: str, duration_s: float) -> Dict[str, Any]:
    url = f"ws://127.0.0.1:8000/api/v1/stream/metadata/{cam}"
    msgs = 0
    latencies_ms: List[float] = []
    person_frames = 0
    recognized_names: Set[str] = set()
    track_ids: Set[int] = set()
    max_in = 0
    max_out = 0
    last_seq = -1

    async with websockets.connect(url, open_timeout=10) as ws:
        end_t = time.monotonic() + duration_s
        while time.monotonic() < end_t:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            now = time.time()
            pkt = json.loads(raw)
            if pkt.get("type") != "metadata":
                continue
            data = pkt.get("data", {})
            assert data.get("camera_id") == cam, f"Unexpected camera_id: {data.get('camera_id')}"
            msgs += 1
            seq = data.get("frame_sequence", 0)
            if seq > last_seq:
                last_seq = seq
            ts = data.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                latencies_ms.append(max(0.0, (now - ts) * 1000.0))
            persons = data.get("persons", [])
            if persons:
                person_frames += 1
                for p in persons:
                    if "track_id" in p:
                        track_ids.add(p["track_id"])
                    cand = p.get("identity_candidate")
                    if cand and cand != "Unknown":
                        recognized_names.add(cand)
            counts = data.get("counts", {})
            max_in = max(max_in, int(counts.get("in", 0)))
            max_out = max(max_out, int(counts.get("out", 0)))

    avg_lat = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    return {
        "messages": msgs,
        "person_frames": person_frames,
        "recognized_names": sorted(recognized_names),
        "unique_track_ids": sorted(track_ids),
        "max_in": max_in,
        "max_out": max_out,
        "avg_ipc_latency_ms": round(avg_lat, 2),
        "last_frame_sequence": last_seq,
    }


async def _capture_chromium_screenshots() -> Dict[str, Any]:
    user_data = ARTIFACTS / "_sim_chrome_profile"
    user_data.mkdir(parents=True, exist_ok=True)
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
            f"--user-data-dir={user_data}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    console_errors: List[str] = []
    page_errors: List[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9229/json/version", timeout=15.0)
            async with session.get("http://127.0.0.1:9229/json/list") as resp:
                targets = await resp.json()
            page_target = next(t for t in targets if t.get("type") == "page")
            ws_url = page_target["webSocketDebuggerUrl"]

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
                        desc = evt.get("params", {}).get("exceptionDetails", {}).get("text", "exception")
                        page_errors.append(desc)
                    elif evt.get("method") == "Log.entryAdded":
                        entry = evt.get("params", {}).get("entry", {})
                        if entry.get("level") == "error":
                            console_errors.append(entry.get("text", "console error"))

            await cdp_call("Page.enable")
            await cdp_call("Runtime.enable")
            await cdp_call("Log.enable")
            await cdp_call("Emulation.setDeviceMetricsOverride", {
                "width": 1920,
                "height": 1080,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            await cdp_call("Page.navigate", {"url": "http://127.0.0.1:8000/"})
            await asyncio.sleep(7.0)

            dash_path = ARTIFACTS / "sim_no_cam_dashboard.png"
            dash_shot = await cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            dash_path.write_bytes(base64.b64decode(dash_shot["data"]))

            await cdp_call("Runtime.evaluate", {
                "expression": "if (typeof switchPage === 'function') { switchPage('live'); } else { document.querySelector('[data-page=\"live\"]')?.click(); }",
                "returnByValue": True,
            })
            await asyncio.sleep(6.0)

            live_state = await cdp_call("Runtime.evaluate", {
                "expression": """(() => {
                    const v1 = document.getElementById('video1');
                    const v2 = document.getElementById('video2');
                    const p1 = document.getElementById('preview1');
                    const p2 = document.getElementById('preview2');
                    return {
                        video1_ready: v1 ? v1.readyState : -1,
                        video2_ready: v2 ? v2.readyState : -1,
                        preview1_ready: p1 ? p1.readyState : -1,
                        preview2_ready: p2 ? p2.readyState : -1,
                        vramText: document.getElementById('vramUsed')?.textContent || '',
                        wsStatus: document.getElementById('wsStatusText')?.textContent || '',
                    };
                })()""",
                "returnByValue": True,
            })

            live_path = ARTIFACTS / "sim_no_cam_live.png"
            live_shot = await cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            live_path.write_bytes(base64.b64decode(live_shot["data"]))

            return {
                "dashboard_screenshot": str(dash_path),
                "live_screenshot": str(live_path),
                "live_state": live_state.get("result", {}).get("value", {}),
                "console_errors": console_errors,
                "page_errors": page_errors,
            }
    finally:
        _terminate_proc(chrome_proc, "chrome")


def _verify_excel_report(xlsx_path: pathlib.Path) -> Dict[str, Any]:
    wb = openpyxl.load_workbook(str(xlsx_path))
    assert "Nhat_Ky_Diem_Danh" in wb.sheetnames, f"Missing Nhat_Ky_Diem_Danh in {wb.sheetnames}"
    assert "Tong_Hop_Si_So" in wb.sheetnames, f"Missing Tong_Hop_Si_So in {wb.sheetnames}"

    ws1 = wb["Nhat_Ky_Diem_Danh"]
    rows_ws1 = list(ws1.iter_rows(values_only=True))
    names_found = {str(r[2]) for r in rows_ws1[1:] if len(r) > 2 and r[2]}

    ws2 = wb["Tong_Hop_Si_So"]
    rows_ws2 = list(ws2.iter_rows(values_only=True))

    assert "Nguyễn Công Bảo Ngọc" in names_found or "Trần Minh Quân" in names_found, (
        f"Expected simulated Vietnamese names with intact diacritics in Excel, got: {names_found}"
    )
    return {
        "sheetnames": wb.sheetnames,
        "journal_rows": len(rows_ws1) - 1,
        "names_found": sorted(names_found),
        "summary_row": list(rows_ws2[1]) if len(rows_ws2) > 1 else [],
    }


async def run_simulation() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log_dir = ARTIFACTS / "sim_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Stream 1: Ensure 1080p human simulation videos exist & pass offline YOLO/SCRFD probe
    cam1_mp4 = ARTIFACTS / "sim_human_cam1.mp4"
    cam2_mp4 = ARTIFACTS / "sim_human_cam2.mp4"
    if not (cam1_mp4.exists() and cam2_mp4.exists()):
        videos = generate_human_videos()
    else:
        videos = {"cam1": cam1_mp4, "cam2": cam2_mp4}
    probe_res = probe_generated_videos(videos)

    # Write 1080p simulation pipeline config so FramePool & crossing lines match 1920x1080
    import yaml
    base_cfg = yaml.safe_load((ROOT / "pipeline_engine" / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
    for cid in ("cam1", "cam2"):
        if cid in base_cfg.get("cameras", {}):
            base_cfg["cameras"][cid]["expected"]["width"] = 1920
            base_cfg["cameras"][cid]["expected"]["height"] = 1080
            base_cfg["cameras"][cid]["geometry"]["line_start"] = [288, 570]
            base_cfg["cameras"][cid]["geometry"]["line_end"] = [1632, 570]
            base_cfg["cameras"][cid]["crossing_policy"]["min_crossing_distance"] = 25.0
            base_cfg["cameras"][cid]["crossing_policy"]["side_confirmation_frames"] = 2
    sim_cfg_path = ARTIFACTS / "sim_pipeline.yaml"
    sim_cfg_path.write_text(yaml.safe_dump(base_cfg, sort_keys=False), encoding="utf-8")

    # 2. Stream 2: Generate .npy embeddings, seed SQLite, verify Rust GalleryIndexRs
    npy_info = generate_npy_artifacts()
    seed_database_and_hot_reload_files()
    gallery_verify = verify_rust_gallery_and_arcface_reload()

    sim_env = os.environ.copy()
    sim_env["AI_WORKER_API_KEY"] = "e2e_worker_key_2026"
    sim_env["AI_CONTROL_API_KEY"] = "e2e_control_key_2026"
    sim_env["ADMIN_API_KEY"] = "e2e_admin_key_2026"
    sim_env["PIPELINE_CONFIG_PATH"] = str(sim_cfg_path)

    publisher = RTSPSimPublisher(videos["cam1"], videos["cam2"], log_dir)
    uvicorn_proc: Optional[subprocess.Popen] = None
    worker_proc: Optional[subprocess.Popen] = None
    uvicorn_log_path = log_dir / "uvicorn.log"
    worker_log_path = log_dir / "worker.log"

    try:
        print("[SIM 3] 1. Starting MediaMTX + Dual FFmpeg Human RTSP Streams...")
        publisher.start()

        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9997/v3/paths/list", timeout=15.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam1/index.m3u8", timeout=20.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam2/index.m3u8", timeout=20.0)

            print("[SIM 3] 2. Starting FastAPI (uvicorn app.main:app --port 8000)...")
            uvicorn_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(ROOT),
                env=sim_env,
                stdout=open(uvicorn_log_path, "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=25.0)

            print("[SIM 3] 3. Starting AIWorker (NVDEC + TensorRT 11.3 FP16 + Rust attendance_core)...")
            worker_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "pipeline_engine.core.worker"],
                cwd=str(ROOT),
                env=sim_env,
                stdout=open(worker_log_path, "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )

            deadline = time.monotonic() + 60.0
            worker_ready = False
            while time.monotonic() < deadline:
                async with session.get(
                    "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                    headers={"X-API-Key": sim_env["AI_WORKER_API_KEY"]},
                ) as r:
                    if r.status == 200:
                        w_health = await r.json()
                        cams = w_health.get("camera_states", {})
                        if "cam1" in cams and "cam2" in cams:
                            worker_ready = True
                            break
                await asyncio.sleep(1.0)
            assert worker_ready, "AIWorker did not register cam1 and cam2 within 60s"

            # Trigger hot-reload of .npy gallery into running AIWorker via file watcher
            (ROOT / "data" / "embeddings.npy").touch()
            (ROOT / "data" / "embeddings.npy.metadata.json").touch()
            await asyncio.sleep(5.0)

            print("[SIM 3] 4. Running 25-second integrated simulation soak (all 3 streams active)...")
            peak_vram_mb = await asyncio.to_thread(_get_gpu_vram_mb, worker_proc.pid)
            ws_task1 = asyncio.create_task(_subscribe_metadata("cam1", 25.0))
            ws_task2 = asyncio.create_task(_subscribe_metadata("cam2", 25.0))

            for _ in range(12):
                await asyncio.sleep(2.0)
                vram_now = await asyncio.to_thread(_get_gpu_vram_mb, worker_proc.pid)
                peak_vram_mb = max(peak_vram_mb, vram_now)

            ws1_res, ws2_res = await asyncio.gather(ws_task1, ws_task2)
            print(f"[SIM 3] WebSocket cam1: {ws1_res}")
            print(f"[SIM 3] WebSocket cam2: {ws2_res}")

            async with session.get(
                "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                headers={"X-API-Key": sim_env["AI_WORKER_API_KEY"]},
            ) as r:
                health_json = await r.json()

            print("[SIM 3] 5. Capturing Headless Chromium UI Screenshots...")
            browser_res = await _capture_chromium_screenshots()
            print(f"[SIM 3] Browser result: {browser_res}")

            print("[SIM 3] 6. Exporting .xlsx Attendance Report...")
            xlsx_path = ARTIFACTS / "sim_no_cam_report.xlsx"
            async with session.get("http://127.0.0.1:8000/api/v1/attendance/export?format=xlsx") as r:
                assert r.status == 200, f"Excel export failed with HTTP {r.status}"
                xlsx_path.write_bytes(await r.read())
            excel_res = _verify_excel_report(xlsx_path)
            print(f"[SIM 3] Excel verification: {excel_res}")

        # Log & telemetry assertions
        worker_logs = worker_log_path.read_text(encoding="utf-8", errors="replace")
        uvicorn_logs = uvicorn_log_path.read_text(encoding="utf-8", errors="replace")
        assert "Myelin" not in worker_logs, "Myelin error detected in worker logs!"
        assert "database is locked" not in uvicorn_logs.lower(), "SQLite database is locked in uvicorn!"
        assert "database is locked" not in worker_logs.lower(), "SQLite database is locked in worker!"

        worker_vram_samples = [float(m) for m in re.findall(r"GPU:\s*([0-9]+(?:\.[0-9]+)?)MB", worker_logs)]
        worker_peak_vram_mb = max(worker_vram_samples) if worker_vram_samples else peak_vram_mb

        cam_states = health_json.get("camera_states", {})
        cam1_fps = float(cam_states.get("cam1", {}).get("decode_fps", cam_states.get("cam1", {}).get("fps", 0.0)))
        cam2_fps = float(cam_states.get("cam2", {}).get("decode_fps", cam_states.get("cam2", {}).get("fps", 0.0)))
        assert cam1_fps >= 25.0, f"cam1 FPS {cam1_fps} < 25.0 (state={cam_states.get('cam1')})"
        assert cam2_fps >= 25.0, f"cam2 FPS {cam2_fps} < 25.0 (state={cam_states.get('cam2')})"
        assert worker_peak_vram_mb < 2662.4, f"AIWorker Peak VRAM {worker_peak_vram_mb} MB >= 2.6 GB!"

        assert ws1_res["messages"] >= 100 and ws2_res["messages"] >= 100
        assert ws1_res["avg_ipc_latency_ms"] < 10.0, f"cam1 IPC latency {ws1_res['avg_ipc_latency_ms']} >= 10ms"
        assert ws2_res["avg_ipc_latency_ms"] < 10.0, f"cam2 IPC latency {ws2_res['avg_ipc_latency_ms']} >= 10ms"
        assert "Nguyễn Công Bảo Ngọc" in ws1_res["recognized_names"], f"cam1 missed Nguyễn Công Bảo Ngọc: {ws1_res}"
        assert "Trần Minh Quân" in ws2_res["recognized_names"], f"cam2 missed Trần Minh Quân: {ws2_res}"
        assert (ws1_res["max_in"] + ws1_res["max_out"]) >= 1, f"cam1 had 0 crossings: {ws1_res}"
        assert (ws2_res["max_in"] + ws2_res["max_out"]) >= 1, f"cam2 had 0 crossings: {ws2_res}"
        assert len(browser_res["console_errors"]) == 0, f"Browser console errors: {browser_res['console_errors']}"
        assert len(browser_res["page_errors"]) == 0, f"Browser page errors: {browser_res['page_errors']}"

        report = {
            "status": "PASS",
            "stream1_probe": probe_res,
            "stream2_npy": npy_info,
            "stream2_gallery": gallery_verify,
            "cam1_fps": cam1_fps,
            "cam2_fps": cam2_fps,
            "worker_peak_vram_mb": worker_peak_vram_mb,
            "ws_cam1": ws1_res,
            "ws_cam2": ws2_res,
            "browser": browser_res,
            "excel": excel_res,
        }
        (ARTIFACTS / "sim_no_cam_summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("[SIM 3] ALL CAMERA-FREE SIMULATION CHECKS PASSED!")

    finally:
        print("[CLEANUP] Terminating all child processes...")
        _terminate_proc(worker_proc, "AIWorker")
        _terminate_proc(uvicorn_proc, "uvicorn")
        publisher.stop()
        await asyncio.sleep(1.5)
        open_ports = [p for p in (8000, 8554, 8888, 9229, 9997) if _is_port_open("127.0.0.1", p)]
        if open_ports:
            raise RuntimeError(f"Ports still open after cleanup: {open_ports}")
        print("[CLEANUP] Verified ports 8000, 8554, 8888, 9229, 9997 are all CLOSED.")


if __name__ == "__main__":
    asyncio.run(run_simulation())
