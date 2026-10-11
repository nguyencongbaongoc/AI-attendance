#!/usr/bin/env python3
"""Phase 44.X.4-R2 fix verification — long-running CAM1+2 publisher vs MediaMTX."""
import sys, time, json, urllib.request, urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import (
    AnnotatedPublisherConfig, AnnotatedFramePublisher,
)

T0 = time.time()
OUT = REPO_ROOT / "benchmark_results" / "phase44" / "r2_fix_verify2.log"
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("")
def log(m):
    s = f"[T+{time.time()-T0:7.2f}s] {m}"
    print(s, flush=True)
    with open(OUT, "a") as f:
        f.write(s + "\n")


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


def main():
    pubs = {}
    for cid in ("cam1", "cam2"):
        pubs[cid] = make_pub(cid)
        log(f"{cid} publisher started pid={pubs[cid]._metrics.ffmpeg_pid}")

    # Feed for 45s.
    end = time.time() + 45
    n = 0
    while time.time() < end:
        for cid, p in pubs.items():
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            frame[:, (n * 4) % 600:(n * 4) % 600 + 40, :] = 255
            p.submit(frame, lines=[], regions=[])
        n += 1
        time.sleep(1 / 15.0)

    log(f"feed loop ended after {n} frames per camera")

    # Poll HLS / path state for 8 seconds while still feeding.
    last_hls = {}
    samples = []
    poll_end = time.time() + 8
    while time.time() < poll_end:
        # keep submitting so encoders don't go idle
        for cid, p in pubs.items():
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            frame[:, 10:50, :] = 255
            p.submit(frame, lines=[], regions=[])
        for cid in ("cam1", "cam2"):
            h = head(f"http://localhost:8888/live/{cid}-ai/index.m3u8")
            if h not in last_hls.get(cid, []):
                log(f"HLS /live/{cid}-ai/index.m3u8: HTTP {h}")
                last_hls.setdefault(cid, []).append(h)
        time.sleep(0.5)

    # Final snapshot.
    for cid in ("cam1", "cam2"):
        p = get_path(f"live/{cid}-ai")
        log(f"path live/{cid}-ai: ready={p.get('ready') if p else 'NONE'} "
            f"bytesReceived={p.get('bytesReceived') if p else 'N/A'} "
            f"source_type={(p.get('source') or {}).get('type') if p else None}")

    for cid, pub in pubs.items():
        m = pub._metrics
        log(f"{cid} publisher: submitted={m.frames_submitted} "
            f"encoded={m.frames_encoded} dropped={m.frames_dropped} "
            f"restarts={m.encoder_restarts}")
        log(f"{cid} ffmpeg alive: {pub._ffmpeg_proc and pub._ffmpeg_proc.poll() is None} "
            f"pid={pub._ffmpeg_proc.pid if pub._ffmpeg_proc else None}")

    raw1 = get_path("live/cam1"); raw2 = get_path("live/cam2")
    log(f"raw cam1 ready={raw1.get('ready')} bytesReceived={raw1.get('bytesReceived')}")
    log(f"raw cam2 ready={raw2.get('ready')} bytesReceived={raw2.get('bytesReceived')}")

    for pub in pubs.values():
        pub.stop()


if __name__ == "__main__":
    main()