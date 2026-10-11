#!/usr/bin/env python3
"""Phase 44.X.4-R2 fix verification — single CAM1 publisher vs MediaMTX."""
import sys, time, json, subprocess, urllib.request, urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import (
    AnnotatedPublisherConfig, AnnotatedFramePublisher,
)

T0 = time.time()
OUT = REPO_ROOT / "benchmark_results" / "phase44" / "r2_fix_verify.log"
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


def main():
    cfg = AnnotatedPublisherConfig(
        camera_id="cam1",
        rtsp_url="rtsp://localhost:8554/live/cam1-ai",
        width=640, height=360, fps=15.0,
        video_bitrate_kbps=2500, gop_seconds=1.0,
        max_restarts=3, restart_backoff_seconds=1.0,
    )
    pub = AnnotatedFramePublisher(cfg)
    pub.start()
    log(f"publisher started, pid={pub._metrics.ffmpeg_pid}")

    # Feed synthetic frames for 20s.
    end = time.time() + 20
    n = 0
    while time.time() < end:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:, (n * 4) % 600:(n * 4) % 600 + 40, :] = 255
        pub.submit(frame, lines=[], regions=[])
        n += 1
        time.sleep(1 / cfg.fps)
    log(f"fed {n} synthetic frames")

    # Let ffmpeg flush.
    time.sleep(3)

    # Read final state.
    p = get_path("live/cam1-ai")
    log(f"path live/cam1-ai: ready={p.get('ready') if p else 'NONE'} "
        f"source={(p.get('source') if p else None)} "
        f"bytesReceived={p.get('bytesReceived') if p else 'N/A'}")

    m = pub._metrics
    log(f"publisher metrics: submitted={m.frames_submitted} "
        f"encoded={m.frames_encoded} dropped={m.frames_dropped} "
        f"restarts={m.encoder_restarts} pid={m.ffmpeg_pid}")

    if pub._ffmpeg_proc:
        alive = pub._ffmpeg_proc.poll() is None
        log(f"ffmpeg alive: {alive} pid={pub._ffmpeg_proc.pid}")

    hls_status = head("http://localhost:8888/live/cam1-ai/index.m3u8")
    log(f"HLS /live/cam1-ai/index.m3u8: HTTP {hls_status}")

    raw1 = get_path("live/cam1")
    raw2 = get_path("live/cam2")
    log(f"raw cam1 ready={raw1.get('ready') if raw1 else None} "
        f"bytesReceived={raw1.get('bytesReceived') if raw1 else None}")
    log(f"raw cam2 ready={raw2.get('ready') if raw2 else None} "
        f"bytesReceived={raw2.get('bytesReceived') if raw2 else None}")

    pub.stop()


if __name__ == "__main__":
    main()