"""
TEMPORARY_FORENSIC_TRACE: Phase H.10-C.5 — External-file forensic trace.
Only change: events are written to an external timestamped file.
Does NOT modify encoder config, queue semantics, surface ownership,
CUDA sync, architecture, restart logic, frame format, or MediaMTX.
"""
from __future__ import annotations
import logging, threading, time, json, os
from typing import Optional

logger = logging.getLogger(__name__)

FORENSIC_TRACE_ENABLED = True

_TRACE_FILE = "benchmark_results/phase44/h10_c5_forensic_trace.jsonl"
_TRACE_LOCK = threading.Lock()

SURFACE_ACQUIRE = "SURFACE_ACQUIRE"
ANNOTATE_BEGIN = "ANNOTATE_BEGIN"
ANNOTATE_END = "ANNOTATE_END"
DLPACK_CREATE = "DLPACK_CREATE"
ENCODE_QUEUE_PUT = "ENCODE_QUEUE_PUT"
ENCODE_QUEUE_GET = "ENCODE_QUEUE_GET"
AVFRAME_FROM_DLPACK = "AVFRAME_FROM_DLPACK"
NVENC_ENCODE_BEGIN = "NVENC_ENCODE_BEGIN"
NVENC_ENCODE_RETURN = "NVENC_ENCODE_RETURN"
RTSP_MUX_BEGIN = "RTSP_MUX_BEGIN"
RTSP_MUX_OK = "RTSP_MUX_OK"
RTSP_MUX_ERROR = "RTSP_MUX_ERROR"

def _init_file():
    try:
        d = os.path.dirname(_TRACE_FILE)
        if d: os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def log_event(
    event_name: str,
    camera_id: str = "",
    frame_id: str = "",
    surface_id: str = "UNAVAILABLE",
    storage_pointer_y: str = "UNAVAILABLE",
    storage_pointer_uv: str = "UNAVAILABLE",
    timestamp_ns: Optional[int] = None,
    encoder_instance_id: str = "UNAVAILABLE",
    restart_generation: int = -1,
    thread_id: int = -1,
    **extra,
):
    if not FORENSIC_TRACE_ENABLED:
        return
    entry = {
        "timestamp_ns": timestamp_ns or int(time.time() * 1e9),
        "event": event_name,
        "camera_id": camera_id,
        "frame_id": frame_id,
        "surface_id": surface_id,
        "storage_pointer_y": storage_pointer_y,
        "storage_pointer_uv": storage_pointer_uv,
        "encoder_instance_id": encoder_instance_id,
        "restart_generation": restart_generation,
        "thread_id": thread_id if thread_id >= 0 else threading.current_thread().ident,
    }
    entry.update(extra)
    try:
        _init_file()
        with _TRACE_LOCK:
            with open(_TRACE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug("FORENSIC_TRACE file write failed: %s", e)
    logger.debug("FORENSIC_TRACE %s cam=%s frame=%s surface=%s", event_name, camera_id, frame_id, surface_id)

def get_events():
    """Read all events from external trace file."""
    try:
        if not os.path.exists(_TRACE_FILE):
            return []
        events = []
        with open(_TRACE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events
    except Exception:
        return []

def reset_events():
    try:
        if os.path.exists(_TRACE_FILE):
            open(_TRACE_FILE, "w").close()
    except Exception:
        pass

def disable_trace():
    global FORENSIC_TRACE_ENABLED
    FORENSIC_TRACE_ENABLED = False

def enable_trace():
    global FORENSIC_TRACE_ENABLED
    FORENSIC_TRACE_ENABLED = True
