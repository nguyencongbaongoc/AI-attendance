#!/usr/bin/env python3
"""Phase 44.X.4-R2 HLS trigger test — explicitly request HLS to start remux."""
import sys, time, json, urllib.request, urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import (
    AnnotatedPublisherConfig, AnnotatedFramePublisher,
)

T0 = time.time()
def log(m):
    s = f"[T+{time.time()-T0:7.2f}s] {m}"
    print(s, flush=True)


def api_get(path):
    try:
        with urllib.request.urlopen(f"http://localhost:9997{path}", timeout=2) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def head(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def get_path(name):
    data = api_get("/v3/paths/list")
    if "_error" in data:
        return None
    for it in data.get("items", []):
        if it["name"] == name:
            return it
    return None


def make_pub(cid, w=640, h=360, fps=15.0):
    cfg = AnnotatedPublisherConfig(
        camera_id=cid, rtsp_url=f"rtsp://localhost:8554/live/{cid}-ai",
        width=w, height=h, fps=fps,
        video_bitrate_kbps=2500, gop_seconds=1.0,
        max_restarts=3, restart_backoff_seconds=1.0,
    )
    pub = AnnotatedFramePublisher(cfg)
    pub.start()
    return pub


# Start both publishers
pubs = {}
for cid in ("cam1", "cam2"):
    pubs[cid] = make_pub(cid)
    log(f"{cid} publisher started pid={pubs[cid]._metrics.ffmpeg_pid}")

# Feed for 30s
end = time.time() + 30
n = 0
while time.time() < end:
    for cid, p in pubs.items():
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:, (n * 4) % 600:(n * 4) % 600 + 40, :] = 255
        p.submit(frame, lines=[], regions=[])
    n += 1
    time.sleep(1 / 15.0)

log(f"feed loop ended after {n} frames per camera")

# Now explicitly request HLS (this triggers hlsAlwaysRemux behavior)
for cid in ("cam1", "cam2"):
    url = f"http://localhost:8888/live/{cid}-ai/index.m3u8"
    log(f"Requesting HLS: {url}")
    for i in range(15):
        st = head(url)
        log(f"  {cid} HLS HTTP {st}")
        if st == 200:
            break
        time.sleep(0.5)

# Final path state
for cid in ("cam1", "cam2"):
    p = get_path(f"live/{cid}-ai")
    log(f"path live/{cid}-ai: ready={p.get('ready')} bytesReceived={p.get('bytesReceived')} source_type={(p.get('source') or {}).get('type')}")

# Cleanup
for pub in pubs.values():
    pub.stop()
log("done")