"""
Autonomous UI Audit & Screenshot Capture (Phase 4: Gate 5).

Starts FastAPI in offline mode on 127.0.0.1:8000, launches headless Chrome (1920x1080),
draws a realistic synthetic person silhouette at [0.25, 0.18, 0.60, 0.88] onto the
video stages, injects canonical WebSocket metadata via POST /api/v1/stream/metadata/ingest,
captures full-page screenshots:
  - artifacts/ui_audit_dashboard.png (#page-dashboard)
  - artifacts/ui_audit_live_monitoring.png (#page-live)
and verifies zero console / CSP errors.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    py312_site = Path(r"C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312\Lib\site-packages")
    if py312_site.exists():
        sys.path.insert(0, str(py312_site))
    from playwright.sync_api import sync_playwright

import httpx
import uvicorn
from app.main import app

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


STAGE_RENDER_JS = r"""
() => {
  function drawScene(canvas, withPerson) {
    const W = canvas.width = 1280;
    const H = canvas.height = 720;
    const ctx = canvas.getContext('2d');

    // Ceiling & walls gradient
    const bgGrad = ctx.createLinearGradient(0, 0, 0, H);
    bgGrad.addColorStop(0, '#1e2430');
    bgGrad.addColorStop(0.55, '#2b3342');
    bgGrad.addColorStop(0.56, '#39414f');
    bgGrad.addColorStop(1, '#1d222b');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    // Ceiling lights
    ctx.fillStyle = 'rgba(226, 232, 240, 0.42)';
    for (let x = 220; x <= 960; x += 360) {
      ctx.fillRect(x, 28, 120, 14);
    }

    // Back lobby doorway & glass frame
    ctx.fillStyle = '#151a22';
    ctx.fillRect(390, 88, 500, 320);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 5;
    ctx.strokeRect(390, 88, 500, 320);
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(640, 88);
    ctx.lineTo(640, 408);
    ctx.stroke();

    // Perspective corridor floor grid
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)';
    ctx.lineWidth = 1.5;
    for (let i = -3; i <= 3; i++) {
      ctx.beginPath();
      ctx.moveTo(W * 0.5 + i * 75, H * 0.56);
      ctx.lineTo(W * 0.5 + i * 260, H);
      ctx.stroke();
    }
    for (let row = 0; row < 5; row++) {
      const y = H * 0.58 + Math.pow(row / 4, 1.35) * (H * 0.40);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }

    if (withPerson) {
      // Target bbox [0.25, 0.18, 0.60, 0.88] -> x in [320, 768], y in [129.6, 633.6]
      const bx1 = W * 0.25;
      const by1 = H * 0.18;
      const bx2 = W * 0.60;
      const by2 = H * 0.88;
      const cx = (bx1 + bx2) / 2;
      const bw = bx2 - bx1;
      const bh = by2 - by1;

      // Ground shadow under feet
      ctx.fillStyle = 'rgba(0, 0, 0, 0.50)';
      ctx.beginPath();
      ctx.ellipse(cx, by2 - 6, bw * 0.28, 14, 0, 0, Math.PI * 2);
      ctx.fill();

      // Trousers / Legs (deep navy slacks)
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(cx - bw * 0.18, by1 + bh * 0.56, bw * 0.15, bh * 0.38);
      ctx.fillRect(cx + bw * 0.03, by1 + bh * 0.56, bw * 0.15, bh * 0.38);

      // Shoes
      ctx.fillStyle = '#09090b';
      ctx.beginPath();
      ctx.roundRect(cx - bw * 0.20, by2 - 22, bw * 0.18, 20, 6);
      ctx.roundRect(cx + bw * 0.02, by2 - 22, bw * 0.18, 20, 6);
      ctx.fill();

      // Torso (school white shirt + dark sweater vest)
      ctx.fillStyle = '#f1f5f9';
      ctx.beginPath();
      ctx.roundRect(cx - bw * 0.32, by1 + bh * 0.22, bw * 0.64, bh * 0.36, 28);
      ctx.fill();

      // Backpack / uniform sweater vest center
      ctx.fillStyle = '#0f172a';
      ctx.beginPath();
      ctx.roundRect(cx - bw * 0.21, by1 + bh * 0.23, bw * 0.42, bh * 0.34, 14);
      ctx.fill();

      // Backpack shoulder straps
      ctx.fillStyle = '#334155';
      ctx.fillRect(cx - bw * 0.20, by1 + bh * 0.22, 18, bh * 0.28);
      ctx.fillRect(cx + bw * 0.20 - 18, by1 + bh * 0.22, 18, bh * 0.28);

      // Arms & hands
      ctx.fillStyle = '#e2e8f0';
      ctx.fillRect(cx - bw * 0.36, by1 + bh * 0.25, bw * 0.10, bh * 0.26);
      ctx.fillRect(cx + bw * 0.26, by1 + bh * 0.25, bw * 0.10, bh * 0.26);
      ctx.fillStyle = '#e8be9e';
      ctx.beginPath();
      ctx.arc(cx - bw * 0.31, by1 + bh * 0.53, 15, 0, Math.PI * 2);
      ctx.arc(cx + bw * 0.31, by1 + bh * 0.53, 15, 0, Math.PI * 2);
      ctx.fill();

      // Neck
      ctx.fillStyle = '#dba988';
      ctx.fillRect(cx - 18, by1 + bh * 0.16, 36, 36);

      // Head & facial detail (high clarity so it looks realistic)
      ctx.fillStyle = '#ecc5a8';
      ctx.beginPath();
      ctx.ellipse(cx, by1 + bh * 0.11, bw * 0.13, bh * 0.095, 0, 0, Math.PI * 2);
      ctx.fill();

      // Hair
      ctx.fillStyle = '#18181b';
      ctx.beginPath();
      ctx.ellipse(cx, by1 + bh * 0.065, bw * 0.135, bh * 0.055, 0, Math.PI, Math.PI * 2);
      ctx.fill();
      ctx.fillRect(cx - bw * 0.132, by1 + bh * 0.06, bw * 0.03, bh * 0.05);
      ctx.fillRect(cx + bw * 0.102, by1 + bh * 0.06, bw * 0.03, bh * 0.05);

      // Eyes & expression
      ctx.fillStyle = '#1e293b';
      ctx.beginPath();
      ctx.arc(cx - 16, by1 + bh * 0.105, 3.5, 0, Math.PI * 2);
      ctx.arc(cx + 16, by1 + bh * 0.105, 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#9a6b54';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx, by1 + bh * 0.128, 10, 0.15 * Math.PI, 0.85 * Math.PI);
      ctx.stroke();
    }
  }

  function attachStage(videoId, withPerson) {
    const vid = document.getElementById(videoId);
    if (!vid) return false;
    const stage = document.createElement('canvas');
    drawScene(stage, withPerson);
    try {
      vid.poster = stage.toDataURL('image/png');
    } catch (e) {}
    try {
      if (stage.captureStream) {
        vid.srcObject = stage.captureStream(10);
        vid.play().catch(() => {});
      }
    } catch (e) {}
    return true;
  }

  attachStage('preview1', true);
  attachStage('preview2', false);
  attachStage('video1', true);
  attachStage('video2', false);
}
"""


def _start_server(port: int = 8000):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.perf_counter() + 12.0
    while time.perf_counter() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=1.0)
            if r.status_code == 200:
                return server, thread
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("FastAPI failed to start for visual audit")


def _ingest_canonical_frames(port: int = 8000, frame_seq: int = 100) -> None:
    now = time.time()
    payload_cam1 = {
        "camera_id": "cam1",
        "frame_sequence": frame_seq,
        "timestamp": now,
        "persons": [
            {
                "track_id": 1,
                "bbox": [0.25, 0.18, 0.60, 0.88],
                "confidence": 0.95,
                "identity_candidate": "Hoc Sinh Test",
                "identity_confidence": 0.95,
                "state": "active",
            }
        ],
        "counts": {"in": 1, "out": 0},
    }
    payload_cam2 = {
        "camera_id": "cam2",
        "frame_sequence": frame_seq,
        "timestamp": now,
        "persons": [],
        "counts": {"in": 0, "out": 0},
    }
    r1 = httpx.post(f"http://127.0.0.1:{port}/api/v1/stream/metadata/ingest", json=payload_cam1, timeout=2.0)
    r2 = httpx.post(f"http://127.0.0.1:{port}/api/v1/stream/metadata/ingest", json=payload_cam2, timeout=2.0)
    r1.raise_for_status()
    r2.raise_for_status()


def run_visual_audit() -> int:
    port = 8000
    server, thread = _start_server(port)
    artifacts_dir = REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dash_shot = artifacts_dir / "ui_audit_dashboard.png"
    live_shot = artifacts_dir / "ui_audit_live_monitoring.png"

    console_errors: List[str] = []
    page_errors: List[str] = []

    try:
        with sync_playwright() as p:
            launch_kwargs: Dict[str, Any] = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage"],
            }
            if Path(CHROME_PATH).exists():
                launch_kwargs["executable_path"] = CHROME_PATH
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            page.goto(f"http://127.0.0.1:{port}/?offline=1", wait_until="load", timeout=25000)

            # Wait until MetadataWebSocket connects, badges show LIVE, and health gauge finishes loading
            try:
                page.wait_for_function(
                    """() => {
                      const ws = document.getElementById('wsStatusDashboard');
                      const b1 = document.getElementById('badgeCam1');
                      const b2 = document.getElementById('badgeCam2');
                      const gpu = document.getElementById('gaugeGpuStats');
                      return (
                        ws && ws.textContent.trim() === 'connected' &&
                        b1 && b1.textContent.includes('LIVE') &&
                        b2 && b2.textContent.includes('LIVE') &&
                        gpu && !gpu.textContent.includes('Đang tải')
                      );
                    }""",
                    timeout=20000,
                )
            except Exception as wait_exc:
                snap = page.evaluate(
                    """() => ({
                      ws: document.getElementById('wsStatusDashboard')?.textContent,
                      b1: document.getElementById('badgeCam1')?.textContent,
                      b2: document.getElementById('badgeCam2')?.textContent,
                      gpu: document.getElementById('gaugeGpuStats')?.textContent,
                      apiInfo: document.getElementById('apiInfo')?.textContent,
                    })"""
                )
                print(f"[DEBUG_SNAP] {snap} | console_errors={console_errors} | page_errors={page_errors}")
                raise wait_exc

            # Seed Dashboard recent attendance & KPI state in UI if local DB has 0 records today
            page.evaluate(
                """() => {
                  if (typeof appState !== 'undefined' && (!appState.attendanceRecords || appState.attendanceRecords.length === 0)) {
                    const nowSec = Date.now() / 1000;
                    appState.attendanceRecords = [
                      {
                        person_id: 'HS001',
                        person_name: 'Hoc Sinh Test',
                        class_id: '10A1',
                        camera_id: 'cam1',
                        direction: 'in',
                        confidence: 0.95,
                        identity_confidence: 0.95,
                        timestamp: nowSec - 12
                      },
                      {
                        person_id: 'HS002',
                        person_name: 'Nguyen Van A',
                        class_id: '10A1',
                        camera_id: 'cam1',
                        direction: 'in',
                        confidence: 0.94,
                        identity_confidence: 0.94,
                        timestamp: nowSec - 65
                      }
                    ];
                    if (typeof renderRecentAttendance === 'function') renderRecentAttendance();
                    const totEl = document.getElementById('statTotalStudents');
                    const total = Math.max(parseInt(totEl?.textContent || '0', 10) || 0, 12);
                    if (typeof applyAttendanceSummaryToDashboard === 'function') {
                      applyAttendanceSummaryToDashboard({ present: 2, late: 0, absent: Math.max(0, total - 2), total: 2 }, total);
                    }
                  }
                }"""
            )

            # Draw synthetic corridor & person silhouette onto video stages
            page.evaluate(STAGE_RENDER_JS)

            # Inject canonical metadata over HTTP -> FastAPI WebSocket broadcaster
            for seq in (100, 101):
                _ingest_canonical_frames(port, frame_seq=seq)
                time.sleep(0.12)

            # Verify Dashboard overlay & status updates
            page.wait_for_function(
                """() => {
                  const ls = document.getElementById('lineStatusCam1');
                  const r = window.overlayRenderers && window.overlayRenderers['canvas-cam1'];
                  return ls && ls.textContent.includes('1 IN / 0 OUT') && r && r.lastMetadata && r.lastMetadata.persons.length === 1;
                }""",
                timeout=5000,
            )
            time.sleep(0.25)
            page.screenshot(path=str(dash_shot), full_page=True)
            print(f"[CAPTURE] Saved {dash_shot}")

            # Switch to #page-live and verify Live Monitoring view + bounding boxes
            page.evaluate("() => window.switchPage('live')")
            page.wait_for_function(
                """() => {
                  const liveSec = document.getElementById('page-live');
                  return liveSec && !liveSec.classList.contains('hidden');
                }""",
                timeout=5000,
            )
            page.evaluate(STAGE_RENDER_JS)
            for seq in (102, 103):
                _ingest_canonical_frames(port, frame_seq=seq)
                time.sleep(0.1)

            page.wait_for_function(
                """() => {
                  const t1 = document.getElementById('aiTrackingText1');
                  const c1 = document.getElementById('canvas1');
                  return t1 && t1.textContent.includes('AI Tracking: 1 persons') && t1.textContent.includes('IN: 1 / OUT: 0') && c1 && c1.width > 300;
                }""",
                timeout=5000,
            )
            time.sleep(0.25)
            page.screenshot(path=str(live_shot), full_page=True)
            print(f"[CAPTURE] Saved {live_shot}")

            browser.close()

        print(f"Console errors: {len(console_errors)} -> {console_errors}")
        print(f"Page errors: {len(page_errors)} -> {page_errors}")
        assert len(console_errors) == 0, f"Console/CSP errors detected: {console_errors}"
        assert len(page_errors) == 0, f"Uncaught page errors detected: {page_errors}"
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


if __name__ == "__main__":
    sys.exit(run_visual_audit())
