#!/usr/bin/env python3
"""Phase 44.X.4-R2 final verification — continuous feed + HLS trigger + bytes growth."""
import sys, time, json, threading, urllib.request, urllib.error
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


pubs = {cid: make_pub(cid) for cid in ("cam1", "cam2")}
for cid, p in pubs.items():
    log(f"{cid} publisher started pid={p._metrics.ffmpeg_pid}")

# Background feeder thread for each camera
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
    log(f"feeder[{cid}] stopped after {n} frames")

threads = [threading.Thread(target=feeder, args=(cid,), daemon=True) for cid in ("cam1", "cam2")]
for t in threads: t.start()

# Let RTSP settle and bytes flow for 8s
time.sleep(8)
for cid in ("cam1", "cam2"):
    p = get_path(f"live/{cid}-ai")
    log(f"after 8s feed: live/{cid}-ai ready={p.get('ready') if p else None} bytesReceived={p.get('bytesReceived') if p else None} source_type={(p.get('source') or {}).get('type') if p else None}")

# Trigger HLS for both cameras while still feeding
for cid in ("cam1", "cam2"):
    url = f"http://localhost:8888/live/{cid}-ai/index.m3u8"
    log(f"Triggering HLS for {cid}: {url}")
    got_200 = False
    for i in range(30):
        st = head(url)
        if st == 200:
            log(f"  {cid} HLS HTTP 200 at iter {i}")
            got_200 = True
            break
        if i % 5 == 0:
            log(f"  {cid} HLS HTTP {st} iter {i}")
        time.sleep(0.5)
    if not got_200:
        log(f"  {cid} HLS NEVER became 200 in 15s")

# Let it run another 5s for more bytes
time.sleep(5)
for cid in ("cam1", "cam2"):
    p = get_path(f"live/{cid}-ai")
    log(f"final: live/{cid}-ai ready={p.get('ready') if p else None} bytesReceived={p.get('bytesReceived') if p else None}")

for cid, p in pubs.items():
    m = p._metrics
    log(f"{cid} metrics: submitted={m.frames_submitted} encoded={m.frames_encoded} dropped={m.frames_dropped} restarts={m.encoder_restarts} alive={p._ffmpeg_proc and p._ffmpeg_proc.poll() is None}")

raw1 = get_path("live/cam1"); raw2 = get_path("live/cam2")
log(f"raw cam1 ready={raw1.get('ready')} bytesReceived={raw1.get('bytesReceived')}")
log(f"raw cam2 ready={raw2.get('ready')} bytesReceived={raw2.get('bytesReceived')}")

stop_feeder.set()
for t in threads: t.join(timeout=2)
for pub in pubs.values(): pub.stop()
log("done")