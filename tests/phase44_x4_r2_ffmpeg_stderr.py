#!/usr/bin/env python3
"""Phase 44.X.4-R2 forensic — capture FFmpeg stderr per publisher."""

import sys
import time
import threading
import subprocess
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from app.streaming.annotated_publisher import create_annotated_publisher

T0 = time.time()
LOG = REPO_ROOT / "tests" / "benchmark_results" / "phase44" / "r2_ffmpeg_stderr.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
LOG.write_text("")


def log(msg):
    s = f"[T+{time.time()-T0:7.2f}s] {msg}"
    print(s, flush=True)
    with open(LOG, "a") as f:
        f.write(s + "\n")


def hook_publisher(pub, label):
    """Patch _open_ffmpeg to capture stderr of the subprocess."""
    orig = pub._open_ffmpeg
    def wrapped():
        log(f"  wrapped _open_ffmpeg called for {label}")
        orig()
        proc = pub._ffmpeg_proc
        if proc and proc.stderr:
            log(f"  {label}: hooking drain_stderr, proc.stderr = {type(proc.stderr).__name__}")
            threading.Thread(
                target=drain_stderr, args=(proc, label),
                daemon=True, name=f"stderr-{label}"
            ).start()
        else:
            log(f"  {label}: NO stderr available! proc={proc}")
    pub._open_ffmpeg = wrapped

def drain_stderr(proc, label):
    try:
        log(f"drain_stderr[{label}] starting")
        for line in iter(proc.stderr.readline, b""):
            if not line:
                break
            msg = line.decode("utf-8", errors="replace").rstrip()
            log(f"ffmpeg[{label}]: {msg}")
            if any(k in msg.lower() for k in ["error", "failed", "refused", "unreachable", "tcp"]):
                log(f"  ** ffmpeg[{label}] error indicator: {msg}")
    except Exception as e:
        log(f"  ffmpeg[{label}] stderr drain ended: {e}")


def feed(pub, label, dur):
    end = time.time() + dur
    n = 0
    while time.time() < end:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        x = (n * 4) % 640
        frame[:, x:x+50, :] = 255
        pub.submit(frame, detections=[{"bbox": [x, 100, x+50, 200], "label": "X"}])
        n += 1
        time.sleep(1/15)
    log(f"feed[{label}] submitted {n} frames")


def main():
    log("=== Starting FFmpeg stderr capture scenario ===")
    pub1 = create_annotated_publisher(camera_id="CAM1", fps=15.0)
    pub2 = create_annotated_publisher(camera_id="CAM2", fps=15.0)
    hook_publisher(pub1, "cam1-ai")
    hook_publisher(pub2, "cam2-ai")

    log(f"pub1 hook installed, calling start()")
    pub1.start()
    log(f"pub2 hook installed, calling start()")
    pub2.start()
    log(f"pub1 started: {pub1.get_metrics()}")
    log(f"pub2 started: {pub2.get_metrics()}")

    threading.Thread(target=feed, args=(pub1, "cam1-ai", 20), daemon=True).start()
    threading.Thread(target=feed, args=(pub2, "cam2-ai", 20), daemon=True).start()

    for i in range(20):
        time.sleep(1.0)
        log(f"  t+{i+1}s: pub1=enc:{pub1._metrics.frames_encoded} sub:{pub1._metrics.frames_submitted} drops:{pub1._metrics.frames_dropped} restarts:{pub1._metrics.encoder_restarts} ffmpeg_pid:{pub1._metrics.ffmpeg_pid} last_err:{pub1._metrics.last_error!r}")
        log(f"  t+{i+1}s: pub2=enc:{pub2._metrics.frames_encoded} sub:{pub2._metrics.frames_submitted} drops:{pub2._metrics.frames_dropped} restarts:{pub2._metrics.encoder_restarts} ffmpeg_pid:{pub2._metrics.ffmpeg_pid} last_err:{pub2._metrics.last_error!r}")

    pub1.stop()
    pub2.stop()
    log("=== Done ===")

if __name__ == "__main__":
    main()