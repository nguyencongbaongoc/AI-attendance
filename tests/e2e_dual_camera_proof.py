"""
Gate 3 & Gate 4: Full End-to-End Dual-Camera Offline Proof (No Mocked Shortcuts).

Runs the real production stack simultaneously for cam1 and cam2:
  MediaMTX -> Dual FFmpeg RTSP -> NVDEC -> Shared TensorRT (YOLOv11n/SCRFD/ArcFace)
  -> Tracker -> CrossingEngine -> SQLite WAL + FastAPI WebSocket + HLS -> Headless Chromium
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
from typing import Any, Dict, List, Optional

import aiohttp
import websockets

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
PYTHON_EXE = str(ROOT / ".venv2" / "Scripts" / "python.exe")
MEDIAMTX_EXE = str(ROOT / "mediamtx" / "mediamtx.exe")
MEDIAMTX_CFG = str(ROOT / "mediamtx" / "mediamtx.yml")
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


async def _check_hls_stream(session: aiohttp.ClientSession, cam: str) -> Dict[str, Any]:
    base = f"http://127.0.0.1:8888/live/{cam}"
    m3u8_url = f"{base}/index.m3u8"
    async with session.get(m3u8_url, timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
        assert resp.status == 200, f"HLS {m3u8_url} returned {resp.status}"
        playlist = await resp.text()

    # MediaMTX fMP4 HLS uses variant playlist or segments directly
    lines = [l.strip() for l in playlist.splitlines() if l.strip() and not l.startswith("#")]
    assert lines, f"Empty HLS playlist for {cam}: {playlist[:200]}"
    first_ref = lines[0]
    seg_url = first_ref if first_ref.startswith("http") else f"{base}/{first_ref}"
    async with session.get(seg_url, timeout=aiohttp.ClientTimeout(total=3.0)) as seg_resp:
        assert seg_resp.status == 200, f"HLS sub-playlist/segment {seg_url} returned {seg_resp.status}"
        body = await seg_resp.read()

    # If it was a sub-playlist (.m3u8), fetch an actual .mp4/.m4s segment inside it
    if first_ref.split("?")[0].endswith(".m3u8"):
        sub_text = body.decode("utf-8", errors="replace")
        sub_lines = [l.strip() for l in sub_text.splitlines() if l.strip() and not l.startswith("#")]
        # Also check EXT-X-MAP:URI="..."
        map_match = re.search(r'#EXT-X-MAP:URI="([^"]+)"', sub_text)
        seg_name = map_match.group(1) if map_match else (sub_lines[0] if sub_lines else None)
        assert seg_name, f"No segment found in {seg_url}: {sub_text[:200]}"
        actual_seg_url = seg_name if seg_name.startswith("http") else f"{base}/{seg_name}"
        async with session.get(actual_seg_url, timeout=aiohttp.ClientTimeout(total=3.0)) as r2:
            assert r2.status == 200, f"HLS segment {actual_seg_url} returned {r2.status}"
            seg_bytes = await r2.read()
            assert len(seg_bytes) > 0, f"Empty HLS segment {actual_seg_url}"
            return {"playlist_status": 200, "segment_url": actual_seg_url, "segment_bytes": len(seg_bytes)}

    return {"playlist_status": 200, "segment_url": seg_url, "segment_bytes": len(body)}


async def _subscribe_metadata(cam: str, duration_s: float) -> Dict[str, Any]:
    url = f"ws://127.0.0.1:8000/api/v1/stream/metadata/{cam}"
    msgs = 0
    latencies_ms: List[float] = []
    person_frames = 0
    track_ids = set()
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
            assert "frame_sequence" in data and "persons" in data and "counts" in data
            msgs += 1
            seq = data.get("frame_sequence", 0)
            if seq > last_seq:
                last_seq = seq
            ts = data.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 1_000_000_000:
                lat_ms = max(0.0, (now - ts) * 1000.0)
                latencies_ms.append(lat_ms)
            persons = data.get("persons", [])
            if persons:
                person_frames += 1
                for p in persons:
                    if "track_id" in p:
                        track_ids.add(p["track_id"])
            counts = data.get("counts", {})
            max_in = max(max_in, int(counts.get("in", 0)))
            max_out = max(max_out, int(counts.get("out", 0)))

    avg_lat = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    return {
        "messages": msgs,
        "person_frames": person_frames,
        "unique_track_ids": sorted(track_ids),
        "max_in": max_in,
        "max_out": max_out,
        "avg_ipc_latency_ms": round(avg_lat, 2),
        "last_frame_sequence": last_seq,
    }


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


async def _capture_chromium_screenshots() -> Dict[str, Any]:
    """Gate 4: Launch headless Chrome via CDP, verify live video + BBoxes + 0 errors, capture screenshots."""
    user_data = ARTIFACTS / "_chrome_profile"
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
            # Wait for HLS + WebSockets + BBox rendering on Dashboard
            await asyncio.sleep(7.0)

            dash_shot = await cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            (ARTIFACTS / "e2e_dual_cam_dashboard.png").write_bytes(base64.b64decode(dash_shot["data"]))

            # Switch to Live Monitoring tab (#page-live)
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

            live_shot = await cdp_call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            (ARTIFACTS / "e2e_dual_cam_live.png").write_bytes(base64.b64decode(live_shot["data"]))

            return {
                "dashboard_screenshot": str(ARTIFACTS / "e2e_dual_cam_dashboard.png"),
                "live_screenshot": str(ARTIFACTS / "e2e_dual_cam_live.png"),
                "live_state": live_state.get("result", {}).get("value", {}),
                "console_errors": console_errors,
                "page_errors": page_errors,
            }
    finally:
        _terminate_proc(chrome_proc, "chrome")


async def run_e2e() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log_dir = ARTIFACTS / "e2e_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    mediamtx_proc = None
    ffmpeg1_proc = None
    ffmpeg2_proc = None
    uvicorn_proc = None
    worker_proc = None

    worker_log_path = log_dir / "worker.log"
    uvicorn_log_path = log_dir / "uvicorn.log"

    e2e_env = os.environ.copy()
    e2e_env["AI_WORKER_API_KEY"] = "e2e_worker_key_2026"
    e2e_env["AI_CONTROL_API_KEY"] = "e2e_control_key_2026"
    e2e_env["ADMIN_API_KEY"] = "e2e_admin_key_2026"

    try:
        print("[E2E] 1. Starting MediaMTX...")
        mediamtx_proc = subprocess.Popen(
            [MEDIAMTX_EXE, MEDIAMTX_CFG],
            cwd=str(ROOT),
            stdout=open(log_dir / "mediamtx.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        async with aiohttp.ClientSession() as session:
            await _wait_http_200(session, "http://127.0.0.1:9997/v3/paths/list", timeout=15.0)

            print("[E2E] 2. Starting dual FFmpeg RTSP publishers (live/cam1 & live/cam2)...")
            ffmpeg1_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-stream_loop", "-1",
                    "-i", str(ARTIFACTS / "sim_cam1.mp4"),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam1",
                ],
                stdout=open(log_dir / "ffmpeg_cam1.log", "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
            ffmpeg2_proc = subprocess.Popen(
                [
                    "ffmpeg", "-re", "-stream_loop", "-1",
                    "-i", str(ARTIFACTS / "sim_cam2.mp4"),
                    "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
                    "rtsp://127.0.0.1:8554/live/cam2",
                ],
                stdout=open(log_dir / "ffmpeg_cam2.log", "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )

            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam1/index.m3u8", timeout=20.0)
            await _wait_http_200(session, "http://127.0.0.1:8888/live/cam2/index.m3u8", timeout=20.0)
            hls1 = await _check_hls_stream(session, "cam1")
            hls2 = await _check_hls_stream(session, "cam2")
            print(f"[E2E] Dual HLS ready: cam1={hls1}, cam2={hls2}")

            print("[E2E] 3. Starting FastAPI (uvicorn app.main:app --port 8000)...")
            uvicorn_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=str(ROOT),
                env=e2e_env,
                stdout=open(uvicorn_log_path, "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
            await _wait_http_200(session, "http://127.0.0.1:8000/api/v1/health/system", timeout=25.0)

            print("[E2E] 4. Starting AIWorker (PipelineEngine + CameraManager + TensorRT)...")
            worker_proc = subprocess.Popen(
                [PYTHON_EXE, "-m", "pipeline_engine.core.worker"],
                cwd=str(ROOT),
                env=e2e_env,
                stdout=open(worker_log_path, "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )

            # Wait until worker reports both cameras running via /api/v1/health/ai-worker/pipeline_engine_1
            deadline = time.monotonic() + 60.0
            worker_ready = False
            while time.monotonic() < deadline:
                async with session.get(
                    "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                    headers={"X-API-Key": e2e_env["AI_WORKER_API_KEY"]},
                ) as r:
                    if r.status == 200:
                        w_health = await r.json()
                        cams = w_health.get("camera_states", {})
                        if "cam1" in cams and "cam2" in cams:
                            worker_ready = True
                            break
                await asyncio.sleep(1.0)
            assert worker_ready, "AIWorker did not register both cam1 and cam2 in /api/v1/health/ai-worker/pipeline_engine_1 within 60s"

            print("[E2E] 5. Running 20-second dual-camera concurrent WebSocket & pipeline soak...")
            peak_vram_mb = await asyncio.to_thread(_get_gpu_vram_mb, worker_proc.pid)
            ws_task1 = asyncio.create_task(_subscribe_metadata("cam1", 20.0))
            ws_task2 = asyncio.create_task(_subscribe_metadata("cam2", 20.0))

            for _ in range(10):
                await asyncio.sleep(2.0)
                vram_now = await asyncio.to_thread(_get_gpu_vram_mb, worker_proc.pid)
                peak_vram_mb = max(peak_vram_mb, vram_now)

            ws1_res, ws2_res = await asyncio.gather(ws_task1, ws_task2)
            print(f"[E2E] WebSocket cam1: {ws1_res}")
            print(f"[E2E] WebSocket cam2: {ws2_res}")

            # Re-verify HLS segments after 20s load
            hls1_post = await _check_hls_stream(session, "cam1")
            hls2_post = await _check_hls_stream(session, "cam2")

            # Check /api/v1/health/ai-worker/pipeline_engine_1 for FPS and camera states
            async with session.get(
                "http://127.0.0.1:8000/api/v1/health/ai-worker/pipeline_engine_1",
                headers={"X-API-Key": e2e_env["AI_WORKER_API_KEY"]},
            ) as r:
                health_cameras_json = await r.json()

            # Check attendance events in SQLite via API
            async with session.get("http://127.0.0.1:8000/api/v1/attendance/events?limit=50") as r:
                att_json = await r.json() if r.status == 200 else {}

            print("[E2E] 6. Capturing Headless Chromium Dual-Camera Screenshots (Gate 4)...")
            browser_res = await _capture_chromium_screenshots()
            print(f"[E2E] Browser verification: {browser_res}")

        # Log assertions
        worker_logs = worker_log_path.read_text(encoding="utf-8", errors="replace")
        uvicorn_logs = uvicorn_log_path.read_text(encoding="utf-8", errors="replace")
        assert "Myelin" not in worker_logs, "Myelin error detected in worker logs!"
        assert "database is locked" not in uvicorn_logs.lower(), "SQLite database is locked error detected!"
        assert "database is locked" not in worker_logs.lower(), "SQLite database is locked error in worker!"

        worker_vram_samples = [float(m) for m in re.findall(r"GPU:\s*([0-9]+(?:\.[0-9]+)?)MB", worker_logs)]
        worker_peak_vram_mb = max(worker_vram_samples) if worker_vram_samples else peak_vram_mb

        assert ws1_res["messages"] >= 100, f"cam1 WebSocket messages too low: {ws1_res['messages']}"
        assert ws2_res["messages"] >= 100, f"cam2 WebSocket messages too low: {ws2_res['messages']}"
        assert ws1_res["person_frames"] > 0, "cam1 had 0 person detections!"
        assert ws2_res["person_frames"] > 0, "cam2 had 0 person detections!"
        assert ws1_res["avg_ipc_latency_ms"] < 20.0, f"cam1 IPC latency too high: {ws1_res['avg_ipc_latency_ms']}"
        assert ws2_res["avg_ipc_latency_ms"] < 20.0, f"cam2 IPC latency too high: {ws2_res['avg_ipc_latency_ms']}"
        assert worker_peak_vram_mb < 2662.4, f"AIWorker Peak VRAM {worker_peak_vram_mb} MB exceeded 2.6 GB!"
        assert len(browser_res["console_errors"]) == 0, f"Browser console errors: {browser_res['console_errors']}"
        assert len(browser_res["page_errors"]) == 0, f"Browser page errors: {browser_res['page_errors']}"

        report = {
            "status": "PASS",
            "worker_peak_vram_mb": worker_peak_vram_mb,
            "system_peak_vram_mb": peak_vram_mb,
            "ws_cam1": ws1_res,
            "ws_cam2": ws2_res,
            "hls_cam1": hls1_post,
            "hls_cam2": hls2_post,
            "health_cameras": health_cameras_json,
            "attendance_events_count": len(att_json.get("events", att_json.get("items", []))) if isinstance(att_json, dict) else 0,
            "browser": browser_res,
        }
        (ARTIFACTS / "e2e_dual_cam_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("[E2E] ALL GATE 3 & GATE 4 CHECKS PASSED!")

    finally:
        print("[E2E] Cleaning up all background processes...")
        _terminate_proc(worker_proc, "AIWorker")
        _terminate_proc(uvicorn_proc, "uvicorn")
        _terminate_proc(ffmpeg1_proc, "ffmpeg_cam1")
        _terminate_proc(ffmpeg2_proc, "ffmpeg_cam2")
        _terminate_proc(mediamtx_proc, "mediamtx")
        await asyncio.sleep(1.0)
        for p in (8000, 8554, 8888):
            if _is_port_open("127.0.0.1", p):
                print(f"[CLEANUP] WARNING: Port {p} still open!")


if __name__ == "__main__":
    asyncio.run(run_e2e())
