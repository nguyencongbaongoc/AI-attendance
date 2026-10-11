"""Phase 47B.2 diagnostic instrumentation for pyav_nvenc_encoder.

Extended for Phase 56A.2: surface correlation and ownership telemetry.
"""
import time
import logging
from typing import Optional, Dict, Any

# Try to import the new telemetry module
try:
    from app.streaming.telemetry import get_telemetry, TelemetryEvent
    _TELEMETRY_AVAILABLE = True
except ImportError:
    _TELEMETRY_AVAILABLE = False

logger = logging.getLogger(__name__)

def emit_event(
    camera: str,
    session_id: str,
    event: str,
    meta: Optional[Dict[str, Any]] = None,
    monotonic: Optional[float] = None,
    wall: Optional[float] = None,
    # Surface correlation fields (Phase 56A.2)
    surface_key: Optional[str] = None,
    data_ptr: Optional[int] = None,
    generation: Optional[int] = None,
    ownership_state: Optional[str] = None,
    ref_count: Optional[int] = None,
    frame_id: Optional[str] = None,
) -> None:
    """Lightweight diagnostic event emission with surface correlation."""
    ts_mono = monotonic if monotonic is not None else time.monotonic()
    ts_wall = wall if wall is not None else time.time()
    meta_str = ""
    if meta:
        meta_str = " " + " ".join(f"{k}={v}" for k, v in meta.items())
    logger.info(
        f"{camera} {session_id} {event} mono={ts_mono:.6f} wall={ts_wall:.6f}{meta_str}"
    )

    # Emit to telemetry buffer if available
    if _TELEMETRY_AVAILABLE and surface_key is not None:
        telemetry = get_telemetry()
        telemetry_event = TelemetryEvent(
            camera=camera,
            frame_id=frame_id if frame_id is not None else session_id,
            surface_key=surface_key,
            data_ptr=data_ptr if data_ptr is not None else 0,
            generation=generation if generation is not None else 0,
            ownership_state=ownership_state if ownership_state is not None else "unknown",
            ref_count=ref_count if ref_count is not None else 0,
            timestamp_monotonic=ts_mono,
            timestamp_wall=ts_wall,
            event=event,
        )
        telemetry.emit(telemetry_event)
