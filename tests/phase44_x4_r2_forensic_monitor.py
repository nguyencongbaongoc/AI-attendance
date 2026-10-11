#!/usr/bin/env python3
"""Phase 44.X.4-R2 forensic monitor.

Polls:
- MediaMTX API for live/cam1, live/cam2, live/cam1-ai, live/cam2-ai
- HLS endpoints via HEAD requests to confirm 200 vs 404 transitions
- FFmpeg child processes (PIDs)
- AnnotatedPublisher metrics via the backend HTTP API (if exposed)

Logs to benchmark_results/phase44/r2_forensic.log
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).parent
LOG = REPO_ROOT / "benchmark_results" / "phase44" / "r2_forensic.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

MTX = "http://localhost:9997"
HLS = "http://localhost:8888"
PATHS = ["cam1", "cam2", "cam1-ai", "cam2-ai"]

T0 = time.time()


def ts():
    return f"T+{time.time()-T0:7.2f}s"


def line(msg):
    s = f"[{ts()}] {msg}"
    print(s, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def http_json(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def http_head(url, timeout=1.5):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def fetch_paths_state():
    out = {}
    for p in PATHS:
        d = http_json(f"{MTX}/v3/paths/list")
        if isinstance(d, dict) and "items" in d:
            item = next((x for x in d["items"] if x.get("name") == p), None)
        else:
            item = None
        out[p] = item
    return out


def fetch_ffmpeg_pids():
    """Find running ffmpeg processes spawned from the python backend."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process ffmpeg -ErrorAction SilentlyContinue | Select-Object Id,StartTime,@{n='Cmd';e={$_.CommandLine}} | ConvertTo-Json -Depth 2"],
            text=True, timeout=5)
        try:
            arr = json.loads(out)
            if isinstance(arr, dict):
                arr = [arr]
            return arr or []
        except Exception:
            return []
    except Exception as e:
        return [{"_error": str(e)}]


def fetch_health():
    """Try the backend health endpoint for ingestion/AI metrics."""
    candidates = []
    # we don't know the port; try several common ones plus scan
    for p in range(16500, 16600):
        try:
            with urllib.request.urlopen(f"http://localhost:{p}/api/v1/health/system", timeout=0.3) as r:
                if r.status == 200:
                    candidates.append(p)
                    break
        except Exception:
            pass
    return candidates


def find_backend_port():
    # scan backend listen ports in 10000-19999
    import subprocess
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -ge 10000 -and $_.LocalPort -lt 20000 } | Select-Object LocalPort,OwningProcess | ConvertTo-Json"],
            text=True, timeout=5)
        arr = json.loads(out) if out.strip() else []
        if isinstance(arr, dict):
            arr = [arr]
        return arr
    except Exception as e:
        return [{"_error": str(e)}]


last_state = {}


def main():
    LOG.write_text("")  # truncate
    line(f"=== FORENSIC MONITOR STARTED ===")
    line(f"MediaMTX={MTX}, HLS={HLS}")
    line(f"Initial backend listeners (10000-19999): {find_backend_port()}")

    poll_count = 0
    while True:
        poll_count += 1
        states = fetch_paths_state()
        hls_codes = {p: http_head(f"{HLS}/live/{p}/index.m3u8") for p in PATHS}
        ffprocs = fetch_ffmpeg_pids()

        snap = {"ts": time.time() - T0, "paths": states, "hls": hls_codes, "ffmpeg_pids": ffprocs}

        # Print compact summary
        short = {}
        for p in PATHS:
            item = states.get(p)
            ready = bool(item) and item.get("ready", False)
            num_readers = (item or {}).get("numReaders", 0)
            short[p] = f"{'R' if ready else '-'} rd={num_readers}"
        line(
            f"poll#{poll_count:03d}  "
            + "  ".join(f"{p}:{short[p]}" for p in PATHS)
            + f"  | HLS="
            + ",".join(f"{p}={hls_codes[p]}" for p in PATHS)
            + f"  | ffmpegs={len(ffprocs)}"
        )

        # Detect transitions
        for p in PATHS:
            cur = states.get(p)
            cur_ready = bool(cur) and cur.get("ready", False)
            prev = last_state.get(p, {}).get("ready")
            if prev is not None and prev != cur_ready:
                line(f"  >> TRANSITION {p}: ready={prev} -> ready={cur_ready}")
                line(f"     detail={json.dumps(cur, default=str)[:300]}")
            last_state[p] = {"ready": cur_ready, "ts": snap["ts"]}

        # Detect HLS transitions
        snap.setdefault("hls_prev", {})
        for p in PATHS:
            cur_code = hls_codes[p]
            prev_code = snap["hls_prev"].get(p)
            if prev_code is not None and prev_code != cur_code:
                line(f"  >> HLS {p}: {prev_code} -> {cur_code}")
            snap["hls_prev"][p] = cur_code
        # carry over
        global last_hls
        last_hls = snap["hls_prev"]

        # Snapshot ffmpeg changes
        snap["ffmpeg_summary"] = [
            {"pid": f.get("Id"), "start": str(f.get("StartTime")),
             "cmd": (f.get("Cmd") or "")[:160]}
            for f in ffprocs if isinstance(f, dict) and "Id" in f
        ]

        with open(LOG.with_suffix(".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": snap["ts"],
                "paths": {p: (states.get(p) or {}) for p in PATHS},
                "hls": hls_codes,
                "ffmpeg": snap["ffmpeg_summary"],
            }, default=str) + "\n")

        time.sleep(1.0)


if __name__ == "__main__":
    main()