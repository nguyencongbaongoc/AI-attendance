#!/usr/bin/env python3
"""Phase 44.X.4-R2 forensic — single-publisher long observation with stderr file capture."""

import sys
import time
import subprocess
import json
import os
import signal
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import create_annotated_publisher

T0 = time.time()
LOG = REPO_ROOT / "tests" / "benchmark_results" / "phase44" / "r2_long.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
LOG.write_text("")

def log(msg):
    s = f"[T+{time.time()-T0:7.2f}s] {msg}"
    print(s, flush=True)
    with open(LOG, "a") as f:
        f.write(s + "\n")


def get_path(name):
    try:
        with urllib.request.urlopen(f"http://localhost:9997/v3/paths/list", timeout=1) as r:
            data = json.loads(r.read())
        for it in data.get("items", []):
            if it["name"] == name:
                return it
    except Exception as e:
        return {"_error": str(e)}
    return None


import urllib.request
import urllib.error

def head(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=1) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def feed(pub, dur):
    end = time.time() + dur
    n = 0
    while time.time() < end:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        x = (n * 4) % 640
        frame[:, x:x+50, :] = 255
        pub.submit(frame, detections=[{"bbox": [x, 100, x+50, 200], "label": "X"}])
        n += 1
        time.sleep(1/15)


def main():
    log("=== Starting long observation ===")
    pub = create_annotated_publisher(camera_id="CAM1", fps=15.0)
    pub.start()
    log(f"pub started: {pub.get_metrics()}")

    # Direct subprocess to capture stderr ourselves
    # Re-implement the publisher's _open_ffmpeg to redirect stderr to a file
    # Save the subprocess.Popen call to a file
    log_dir = REPO_ROOT / "tests" / "benchmark_results" / "phase44"
    log_dir.mkdir(parents=True, exist_ok=True)
    stderr_file = open(log_dir / "ffmpeg_ai.log", "wb")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", "640x360", "-r", "15.000",
        "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-tune", "zerolatency",
        "-g", "15", "-keyint_min", "15",
        "-sc_threshold", "0", "-pix_fmt", "yuv420p",
        "-b:v", "2500k", "-bufsize", "5000k",
        "-f", "rtsp", "-rtsp_transport", "tcp",
        "rtsp://localhost:8554/live/cam1-ai",
    ]
    log(f"Direct ffmpeg command: {cmd}")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    log(f"Direct ffmpeg pid={proc.pid}")

    def feed_stdin():
        end = time.time() + 30
        n = 0
        while time.time() < end:
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            x = (n * 4) % 640
            frame[:, x:x+50, :] = 255
            try:
                proc.stdin.write(frame.tobytes())
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                log(f"  pipe broken: {e}")
                return
            n += 1
            time.sleep(1/15)
        log(f"feed_stdin done n={n}")

    threading.Thread(target=feed_stdin, daemon=True).start()

    # Observe
    for i in range(30):
        time.sleep(1.0)
        path = get_path("cam1-ai")
        hls_code = head("http://localhost:8888/live/cam1-ai/index.m3u8")
        ret = proc.poll()
        log(f"  t+{i+1}s: ffmpeg.poll={ret}  HLS={hls_code}  mtx_ready={path.get('ready') if path else 'n/a'}  src={(path.get('source') or {}).get('type') if path else 'n/a'}  bytes={path.get('bytesReceived') if path else 'n/a'}")

    proc.terminate()
    stderr_file.close()
    pub.stop()
    log(f"=== Done. ffmpeg exit={proc.returncode} ===")
    # Show ffmpeg stderr
    log("--- ffmpeg stderr (last 30 lines) ---")
    fl = (REPO_ROOT / "tests" / "benchmark_results" / "phase44" / "ffmpeg_ai.log").read_text(encoding="utf-8", errors="replace")
    for line in fl.splitlines()[-30:]:
        log("  " + line)


if __name__ == "__main__":
    main()