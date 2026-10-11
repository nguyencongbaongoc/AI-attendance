#!/usr/bin/env python3
"""Phase 44.X.4-R2 forensic test — minimal scenario.

Replicates the production AnnotatedPublisher behavior and the live test
environment without bootstrap. Captures the full lifecycle:

    MediaMTX (running)
    ├── live/cam1   <- raw publisher (rtsp_ffmpeg_publisher_1, MP4 loop)
    ├── live/cam2   <- raw publisher (rtsp_ffmpeg_publisher_2, MP4 loop)
    ├── live/cam1-ai  <- AnnotatedFramePublisher(CAM1)  via RTSP
    └── live/cam2-ai  <- AnnotatedFramePublisher(CAM2)  via RTSP

We capture:
- AnnotatedPublisher metrics per camera before/after any failure
- FFmpeg subprocess PIDs, exit codes, stderr tail
- DetectionPipeline frame counters
- MediaMTX path readiness transitions
- HLS response codes
"""

import sys
import os
import time
import subprocess
import threading
import queue as queue_mod
import json
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from app.streaming.annotated_publisher import create_annotated_publisher

T0 = time.time()
LOG = REPO_ROOT / "benchmark_results" / "phase44" / "r2_scenario.jsonl"
LOG.parent.mkdir(parents=True, exist_ok=True)
LOG.write_text("")

def ts(): return f"T+{time.time()-T0:7.2f}s"

def write_event(kind, **kw):
    rec = {"ts": time.time() - T0, "kind": kind, **kw}
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


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


def head(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=1) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def snapshot(label):
    paths = {n: get_path(n) for n in ["cam1", "cam2", "cam1-ai", "cam2-ai"]}
    hls = {n: head(f"http://localhost:8888/live/{n}/index.m3u8") for n in paths}
    # FFmpeg children
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process ffmpeg -ErrorAction SilentlyContinue | Select-Object Id,StartTime,@{n='Cmd';e={$_.CommandLine}} | ConvertTo-Json -Depth 2"],
            text=True, timeout=5)
        ffarr = json.loads(out) if out.strip() else []
        if isinstance(ffarr, dict): ffarr = [ffarr]
    except Exception:
        ffarr = []
    ff_info = []
    for f in ffarr:
        cmd = f.get("Cmd") or ""
        ff_info.append({"pid": f.get("Id"), "start": str(f.get("StartTime")),
                        "target": "cam1-ai" if "cam1-ai" in cmd else ("cam2-ai" if "cam2-ai" in cmd else "raw?")})
    write_event("snapshot", label=label, paths=paths, hls=hls, ffmpegs=ff_info)


def feed_synthetic_frames(publisher, size=(640, 360), duration=120, fps=15, extra=None):
    """Push synthetic annotated frames directly into the publisher queue.

    Mirrors what DetectionPipeline.process_frame() does after AI inference.
    """
    interval = 1.0 / fps
    end = time.time() + duration
    submitted = 0
    while time.time() < end:
        # Synthetic frame with a moving rectangle
        frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        x = (submitted * 4) % size[0]
        frame[:, x:x+50, :] = 255
        cv = int(time.time() * 1000) % 1000
        detections = [{"bbox": [x, 100, x+50, 200], "track_id": f"T-{submitted%5}", "label": "Person"}]
        publisher.submit(frame, detections=detections)
        submitted += 1
        time.sleep(interval)


def monitor_thread(stop):
    while not stop.is_set():
        snapshot("tick")
        time.sleep(1.0)


def publisher_metrics(p):
    return p.get_metrics()


def main():
    print(f"[{ts()}] Starting scenario")
    write_event("start")

    # Start raw publishers (raw camera simulation)
    raw1 = subprocess.Popen(
        ["ffmpeg", "-re", "-stream_loop", "-1", "-i", "test_data/phase20/cam1_test.mp4",
         "-c", "copy", "-f", "flv", "rtmp://localhost:1935/live/cam1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raw2 = subprocess.Popen(
        ["ffmpeg", "-re", "-stream_loop", "-1", "-i", "test_data/phase20/cam2_test.mp4",
         "-c", "copy", "-f", "flv", "rtmp://localhost:1935/live/cam2"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    write_event("raw_publishers_started", pids=[raw1.pid, raw2.pid])
    time.sleep(3)
    snapshot("after_raw_start")

    # Create annotated publishers
    pub1 = create_annotated_publisher(camera_id="CAM1", fps=15.0)
    pub2 = create_annotated_publisher(camera_id="CAM2", fps=15.0)

    if not pub1.start():
        write_event("publisher_start_failed", camera="CAM1")
    if not pub2.start():
        write_event("publisher_start_failed", camera="CAM2")

    write_event("publishers_started",
                cam1_metrics=pub1.get_metrics(),
                cam2_metrics=pub2.get_metrics())

    # Feed frames in background threads
    stop_feed = threading.Event()
    feed_threads = [
        threading.Thread(target=feed_synthetic_frames, args=(pub1, (640, 360), 90, 15), daemon=True),
        threading.Thread(target=feed_synthetic_frames, args=(pub2, (640, 360), 90, 15), daemon=True),
    ]
    for t in feed_threads:
        t.start()
    write_event("feeding_started")

    # Run monitor in background
    stop_mon = threading.Event()
    mt = threading.Thread(target=monitor_thread, args=(stop_mon,), daemon=True)
    mt.start()

    # Sleep for the full observation window
    time.sleep(60)
    write_event("midpoint_metrics",
                cam1_metrics=pub1.get_metrics(),
                cam2_metrics=pub2.get_metrics())
    snapshot("midpoint")

    time.sleep(45)

    write_event("end_metrics",
                cam1_metrics=pub1.get_metrics(),
                cam2_metrics=pub2.get_metrics())
    snapshot("end")

    stop_mon.set()
    pub1.stop()
    pub2.stop()
    raw1.terminate()
    raw2.terminate()
    write_event("stopped")
    print(f"[{ts()}] Scenario complete. See {LOG}")


if __name__ == "__main__":
    main()