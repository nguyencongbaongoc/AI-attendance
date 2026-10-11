#!/usr/bin/env python3
"""Phase 44.X.4-R2 — single combined test: live pub + HLS trigger + bytes growth."""
import sys, time, json, threading, urllib.request, urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import (
    AnnotatedPublisherConfig, AnnotatedFramePublisher,
)

T0 = time.time()
LOG = REPO_ROOT / "benchmark_results" / "phase44" / "r2_final2.log"
LOG.write_text("")
def log(m):
    s = f"[T+{time.time()-T0:7.2f}s] {m}"
    print(s, flush=True)
    with open(LOG, "a") as f:
        f.write(s + "\n")


def api_get(path):
    try:
        with urllib.request.urlopen(f"http://localhost:9997{path}", timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def get_path(name):
    data = api_get("/v3/paths/list")
    if "_error" in data:
        return None
    for it in data.get("items", []):
        if it["name"] == name:
            return it
    return None


def make_pub(cid):
    cfg = AnnotatedPublisherConfig(
        camera_id=cid, rtsp_url=f"rtsp://localhost:8554/live/{cid}-ai",
        width=640, height=360, fps=15.0,
        video_bitrate_kbps=2500, gop_seconds=1.0,
        max_restarts=3, restart_backoff_seconds=1.0,
    )
    pub = AnnotatedFramePublisher(cfg)
    pub.start()
    return pub


# CAM1 only first to keep noise low
pubs = {"cam1": make_pub("cam1")}
log(f"cam1 publisher pid={pubs['cam1']._metrics.ffmpeg_pid}")

stop_feeder = threading.Event()
def feeder(cid):
    pub = pubs[cid]
    n = 0
    while not stop_feeder.is_set():
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:, (n * 4) % 600:(n * 4) % 600 + 40, :] = 255
        pub.submit(frame, lines=[], regions=[])
        n += 1
        time.sleep(1 / 15.0)

t = threading.Thread(target=feeder, args=("cam1",), daemon=True); t.start()

# Wait for path ready
deadline = time.time() + 15
while time.time() < deadline:
    p = get_path("live/cam1-ai")
    if p and p.get("ready"):
        log(f"path live/cam1-ai ready, bytesReceived={p.get('bytesReceived')}")
        break
    time.sleep(0.5)

# Trigger HLS via GET (not HEAD) which should start the on-demand remux
log("Triggering HLS via GET...")
try:
    r = urllib.request.urlopen("http://localhost:8888/live/cam1-ai/index.m3u8", timeout=3)
    log(f"GET HLS HTTP {r.status}")
    body = r.read()[:300]
    log(f"GET HLS body (first 300): {body!r}")
except urllib.error.HTTPError as e:
    log(f"GET HLS HTTPError {e.code}")
except Exception as e:
    log(f"GET HLS err: {type(e).__name__} {e}")

# Wait a few seconds for remuxer to produce segments
for i in range(10):
    time.sleep(1)
    try:
        r = urllib.request.urlopen("http://localhost:8888/live/cam1-ai/index.m3u8", timeout=3)
        body = r.read()
        log(f"+{i+1}s HLS HTTP {r.status} body={body[:200]!r}")
        if r.status == 200 and b"#EXTM3U" in body:
            log("HLS is now serving!")
            break
    except urllib.error.HTTPError as e:
        p = get_path("live/cam1-ai")
        log(f"+{i+1}s HLS HTTP {e.code} ready={p.get('ready') if p else None} bytesReceived={p.get('bytesReceived') if p else None}")
    except Exception as e:
        log(f"+{i+1}s HLS err: {type(e).__name__}")

# Final state
p = get_path("live/cam1-ai")
log(f"final: ready={p.get('ready') if p else None} bytesReceived={p.get('bytesReceived') if p else None}")

stop_feeder.set(); t.join(timeout=3)
pubs["cam1"].stop()
log("done")