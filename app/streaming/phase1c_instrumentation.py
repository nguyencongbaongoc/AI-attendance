"""
Phase 1C — Runtime Pipeline Instrumentation ONLY.

Lightweight, thread-safe, timestamped instrumentation around the
existing pre-NVENC baseline pipeline. No behavior change; no GPU
migration; no optimization.

Instrumented stages (existing only):
- Capture (READ_ENTER / READ_RETURN / FRAME_YIELD / READ_EXCEPTION)
- AI (PREPROCESS / H2D / INFERENCE / D2H / AI_START / AI_END)
- Pipeline stages (DETECTION / RECOGNITION / TRACKING / ANNOTATION / PUBLISH)
- Queue (PUT / GET / FULL / DROP / WAIT)
- Watchdog (MARK_PROGRESS / WATCHDOG_FIRE / CAP_RELEASE / RECONNECT)
- Resource sampling (CPU / RAM / GPU / VRAM / CUDA memory)
- Cross-camera (CAM1 / CAM2 separated; no aggregation)
- Frame-level sequence identifier (instrumentation-only, smallest possible)

Event vocabulary from Phase 1C mandate is preserved. Only events for
stages that actually exist are emitted; unavailable stages are recorded
as unavailable rather than fabricated.
"""
from __future__ import annotations

import time
import threading
import logging
import os
from typing import Any, Dict, Optional, Tuple, List
from collections import deque

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Instrumentation control — safe to disable globally
# ------------------------------------------------------------------
ENABLE_INSTRUMENTATION: bool = True  # Set False to disable all emission

# ------------------------------------------------------------------
# Required event vocabulary (Phase 1C mandate)
# ------------------------------------------------------------------
CAPTURE_EVENTS = {
    "READ_ENTER", "READ_RETURN", "READ_EXCEPTION", "FRAME_YIELD",
}
AI_EVENTS = {
    "AI_START", "PREPROCESS_START", "PREPROCESS_END",
    "H2D_START", "H2D_END",
    "INFERENCE_START", "INFERENCE_END",
    "D2H_START", "D2H_END",
    "AI_END",
}
PIPELINE_EVENTS = {
    "FRAME_PROCESS_START", "DETECTION_START", "DETECTION_END",
    "RECOGNITION_START", "RECOGNITION_END",
    "TRACKING_START", "TRACKING_END",
    "ANNOTATION_START", "ANNOTATION_END",
    "PUBLISH_START", "PUBLISH_END",
    "FRAME_PROCESS_END",
}
WATCHDOG_EVENTS = {
    "MARK_PROGRESS", "WATCHDOG_FIRE", "CAP_RELEASE",
    "RECONNECT_START", "RECONNECT_SUCCESS", "RECONNECT_FAILURE",
}
QUEUE_EVENTS = {
    "QUEUE_PUT", "QUEUE_GET", "QUEUE_WAIT_START", "QUEUE_WAIT_END",
    "QUEUE_FULL", "FRAME_DROP",
}

ALL_EVENTS = CAPTURE_EVENTS | AI_EVENTS | PIPELINE_EVENTS | WATCHDOG_EVENTS | QUEUE_EVENTS

# ------------------------------------------------------------------
# Monotonic high-resolution timestamps (latency calculations)
# ------------------------------------------------------------------
_MONO_CLOCK = time.monotonic
_WALL_CLOCK = time.time

# ------------------------------------------------------------------
# Thread-safe bounded event buffer (no unbounded accumulation)
# ------------------------------------------------------------------
_MAX_BUFFER_SIZE = 4096


class Phase1CInstrument:
    """
    Thread-safe, bounded instrumentation emitter for Phase 1C.
    Does NOT alter pipeline semantics; events are best-effort.
    """

    def __init__(self, max_buffer: int = _MAX_BUFFER_SIZE):
        self.max_buffer = max_buffer
        self._events: deque = deque(maxlen=max_buffer)
        self._lock = threading.Lock()
        # Smallest possible instrumentation-only sequence identifier
        self._local_sequence: int = 0
        self._seq_lock = threading.Lock()
        # Per-camera tracking state (does NOT change ownership/lifecycle)
        self._camera_state_lock = threading.Lock()
        self._camera_states: Dict[str, Dict[str, Any]] = {}
        # Resource sampling state
        self._resource_lock = threading.Lock()
        self._last_resource_sample: Optional[float] = None
        self._resource_interval = 1.0  # lightweight sampling

    # ------------------------------------------------------------------
    # Frame-level sequence identifier (instrumentation-only)
    # ------------------------------------------------------------------
    def next_frame_seq(self, camera_id: str) -> int:
        with self._seq_lock:
            self._local_sequence += 1
            return self._local_sequence

    # ------------------------------------------------------------------
    # Per-camera state (read-only for measurement, no mutation of pipeline)
    # ------------------------------------------------------------------
    def get_camera_state(self, camera_id: str) -> Dict[str, Any]:
        with self._camera_state_lock:
            if camera_id not in self._camera_states:
                self._camera_states[camera_id] = {
                    "last_read_return_mono": None,
                    "last_read_return_wall": None,
                    "last_mark_progress_mono": None,
                    "last_ai_end_mono": None,
                    "last_frame_process_end_mono": None,
                    "last_capture_state": "unknown",
                    "consecutive_read_failures": 0,
                    "read_exception_count": 0,
                }
            return self._camera_states[camera_id].copy()

    def update_camera_read(self, camera_id: str, mono: float, success: bool = True) -> None:
        with self._camera_state_lock:
            state = self._camera_states.setdefault(camera_id, {})
            state["last_read_return_mono"] = mono
            state["last_read_return_wall"] = _WALL_CLOCK()
            state["last_capture_state"] = "reading" if success else "failed"
            if not success:
                state["consecutive_read_failures"] = state.get("consecutive_read_failures", 0) + 1
            else:
                state["consecutive_read_failures"] = 0

    def update_camera_mark_progress(self, camera_id: str, mono: float) -> None:
        with self._camera_state_lock:
            state = self._camera_states.setdefault(camera_id, {})
            state["last_mark_progress_mono"] = mono

    def update_camera_ai_end(self, camera_id: str, mono: float) -> None:
        with self._camera_state_lock:
            state = self._camera_states.setdefault(camera_id, {})
            state["last_ai_end_mono"] = mono

    def update_camera_frame_process_end(self, camera_id: str, mono: float) -> None:
        with self._camera_state_lock:
            state = self._camera_states.setdefault(camera_id, {})
            state["last_frame_process_end_mono"] = mono

    def update_camera_exception(self, camera_id: str) -> None:
        with self._camera_state_lock:
            state = self._camera_states.setdefault(camera_id, {})
            state["read_exception_count"] = state.get("read_exception_count", 0) + 1

    # ------------------------------------------------------------------
    # Event emission (thread-safe, bounded, best-effort)
    # ------------------------------------------------------------------
    def emit(
        self,
        camera_id: str,
        event_name: str,
        frame_id: Optional[int] = None,
        mono_timestamp: Optional[float] = None,
        wall_timestamp: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
        thread_name: Optional[str] = None,
    ) -> bool:
        if not ENABLE_INSTRUMENTATION:
            return False
        if event_name not in ALL_EVENTS:
            # Do NOT fabricate events for missing stages; record only known vocabulary
            logger.debug(
                "Phase1C: unknown event %s for %s (not fabricated; stage may be unavailable)",
                event_name, camera_id,
            )
        # Best-effort emission: never block the pipeline
        try:
            ts_mono = mono_timestamp if mono_timestamp is not None else _MONO_CLOCK()
            ts_wall = wall_timestamp if wall_timestamp is not None else _WALL_CLOCK()
            record = {
                "event": event_name,
                "camera_id": camera_id,
                "frame_id": frame_id,
                "mono_timestamp": ts_mono,
                "wall_timestamp": ts_wall,
                "thread_name": thread_name or threading.current_thread().name,
                "meta": meta or {},
            }
            with self._lock:
                self._events.append(record)
            return True
        except Exception as exc:
            logger.debug("Phase1C instrumentation exception: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Required capture measurement boundaries
    # ------------------------------------------------------------------
    def capture_read_enter(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "READ_ENTER", frame_id=frame_id)

    def capture_read_return(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        success: bool = True,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        mono = _MONO_CLOCK()
        self.emit(camera_id, "READ_RETURN", frame_id=frame_id, mono_timestamp=mono, meta=meta)
        self.update_camera_read(camera_id, mono, success=success)

    def capture_read_exception(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        mono = _MONO_CLOCK()
        meta: Dict[str, Any] = {
            "exception_type": "read_exception",
            "capture_state_at_exception": self.get_camera_state(camera_id).get("last_capture_state"),
        }
        self.emit(camera_id, "READ_EXCEPTION", frame_id=frame_id, mono_timestamp=mono, meta=meta)
        self.update_camera_exception(camera_id)

    def capture_frame_yield(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.emit(camera_id, "FRAME_YIELD", frame_id=frame_id, meta=meta)

    # ------------------------------------------------------------------
    # AI stage measurement (only records real boundaries; H2D/D2H only when they exist)
    # ------------------------------------------------------------------
    def ai_start(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        model_name: Optional[str] = None,
        model_type: Optional[str] = None,
        provider: Optional[str] = None,
        device: Optional[str] = None,
        input_shape: Optional[Any] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        m = meta or {}
        if model_name is not None:
            m["model_name"] = model_name
        if model_type is not None:
            m["model_type"] = model_type
        if provider is not None:
            m["provider"] = provider
        if device is not None:
            m["device"] = device
        if input_shape is not None:
            m["input_shape"] = str(input_shape)
        self.emit(camera_id, "AI_START", frame_id=frame_id, meta=m)

    def ai_preprocess_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "PREPROCESS_START", frame_id=frame_id)

    def ai_preprocess_end(self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> None:
        self.emit(camera_id, "PREPROCESS_END", frame_id=frame_id, meta=meta)

    def ai_h2d_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "H2D_START", frame_id=frame_id)

    def ai_h2d_end(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Only emitted when an actual host->device transfer exists
        self.emit(camera_id, "H2D_END", frame_id=frame_id, meta=meta)

    def ai_inference_start(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
        device: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        m = meta or {}
        if model_name is not None:
            m["model_name"] = model_name
        if provider is not None:
            m["provider"] = provider
        if device is not None:
            m["device"] = device
        self.emit(camera_id, "INFERENCE_START", frame_id=frame_id, meta=m)

    def ai_inference_end(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        num_detections: Optional[int] = None,
        num_persons: Optional[int] = None,
        num_faces: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        m = meta or {}
        if num_detections is not None:
            m["num_detections"] = num_detections
        if num_persons is not None:
            m["num_persons"] = num_persons
        if num_faces is not None:
            m["num_faces"] = num_faces
        self.emit(camera_id, "INFERENCE_END", frame_id=frame_id, meta=m)

    def ai_d2h_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        # Only emitted when an actual device->host result conversion exists
        self.emit(camera_id, "D2H_START", frame_id=frame_id)

    def ai_d2h_end(
        self,
        camera_id: str,
        frame_id: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.emit(camera_id, "D2H_END", frame_id=frame_id, meta=meta)

    def ai_end(self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> None:
        mono = _MONO_CLOCK()
        self.emit(camera_id, "AI_END", frame_id=frame_id, mono_timestamp=mono, meta=meta)
        self.update_camera_ai_end(camera_id, mono)

    # ------------------------------------------------------------------
    # Pipeline stages (measure actual existing stages only)
    # ------------------------------------------------------------------
    def pipeline_frame_process_start(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "FRAME_PROCESS_START", frame_id=frame_id, meta=meta)

    def pipeline_detection_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "DETECTION_START", frame_id=frame_id)

    def pipeline_detection_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "DETECTION_END", frame_id=frame_id, meta=meta)

    def pipeline_recognition_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "RECOGNITION_START", frame_id=frame_id)

    def pipeline_recognition_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "RECOGNITION_END", frame_id=frame_id, meta=meta)

    def pipeline_tracking_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "TRACKING_START", frame_id=frame_id)

    def pipeline_tracking_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "TRACKING_END", frame_id=frame_id, meta=meta)

    def pipeline_annotation_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "ANNOTATION_START", frame_id=frame_id)

    def pipeline_annotation_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "ANNOTATION_END", frame_id=frame_id, meta=meta)

    def pipeline_publish_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "PUBLISH_START", frame_id=frame_id)

    def pipeline_publish_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        self.emit(camera_id, "PUBLISH_END", frame_id=frame_id, meta=meta)

    def pipeline_frame_process_end(
        self, camera_id: str, frame_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        mono = _MONO_CLOCK()
        self.emit(camera_id, "FRAME_PROCESS_END", frame_id=frame_id, mono_timestamp=mono, meta=meta)
        self.update_camera_frame_process_end(camera_id, mono)

    # ------------------------------------------------------------------
    # Queue / backpressure (existing queues only)
    # ------------------------------------------------------------------
    def queue_put(
        self, camera_id: str, frame_id: Optional[int] = None, queue_depth: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        m = meta or {}
        if queue_depth is not None:
            m["queue_depth"] = queue_depth
        self.emit(camera_id, "QUEUE_PUT", frame_id=frame_id, meta=m)

    def queue_get(
        self, camera_id: str, frame_id: Optional[int] = None, queue_depth: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        m = meta or {}
        if queue_depth is not None:
            m["queue_depth"] = queue_depth
        self.emit(camera_id, "QUEUE_GET", frame_id=frame_id, meta=m)

    def queue_wait_start(self, camera_id: str, frame_id: Optional[int] = None) -> None:
        self.emit(camera_id, "QUEUE_WAIT_START", frame_id=frame_id)

    def queue_wait_end(
        self, camera_id: str, frame_id: Optional[int] = None, duration_ms: Optional[float] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        m = meta or {}
        if duration_ms is not None:
            m["wait_duration_ms"] = duration_ms
        self.emit(camera_id, "QUEUE_WAIT_END", frame_id=frame_id, meta=m)

    def queue_full(
        self, camera_id: str, frame_id: Optional[int] = None, queue_depth: Optional[int] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        m = meta or {}
        if queue_depth is not None:
            m["queue_depth"] = queue_depth
        self.emit(camera_id, "QUEUE_FULL", frame_id=frame_id, meta=m)

    def frame_drop(
        self, camera_id: str, frame_id: Optional[int] = None, reason: Optional[str] = None, meta: Optional[Dict[str, Any]] = None
    ) -> None:
        m = meta or {}
        if reason is not None:
            m["drop_reason"] = reason
        self.emit(camera_id, "FRAME_DROP", frame_id=frame_id, meta=m)

    # ------------------------------------------------------------------
    # Watchdog / lifecycle (existing watchdog unchanged; 6.0s preserved)
    # ------------------------------------------------------------------
    def watchdog_mark_progress(self, camera_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        mono = _MONO_CLOCK()
        # Correlate with last successful READ_RETURN, last AI_END, last FRAME_PROCESS_END
        state = self.get_camera_state(camera_id)
        corr_meta = (meta or {}).copy()
        corr_meta["last_read_return_mono"] = state.get("last_read_return_mono")
        corr_meta["last_ai_end_mono"] = state.get("last_ai_end_mono")
        corr_meta["last_frame_process_end_mono"] = state.get("last_frame_process_end_mono")
        corr_meta["last_capture_state"] = state.get("last_capture_state")
        corr_meta["consecutive_read_failures"] = state.get("consecutive_read_failures", 0)
        self.emit(camera_id, "MARK_PROGRESS", mono_timestamp=mono, meta=corr_meta)
        self.update_camera_mark_progress(camera_id, mono)

    def watchdog_fire(
        self,
        camera_id: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        mono = _MONO_CLOCK()
        # Make it possible to reconstruct correlation
        state = self.get_camera_state(camera_id)
        corr_meta = (meta or {}).copy()
        corr_meta["last_read_return_mono"] = state.get("last_read_return_mono")
        corr_meta["last_mark_progress_mono"] = state.get("last_mark_progress_mono")
        corr_meta["last_ai_end_mono"] = state.get("last_ai_end_mono")
        corr_meta["last_frame_process_end_mono"] = state.get("last_frame_process_end_mono")
        corr_meta["current_capture_state"] = state.get("last_capture_state")
        corr_meta["consecutive_read_failures"] = state.get("consecutive_read_failures", 0)
        # Whether cap.read() was active is not directly observable without
        # modifying the capture backend; record unavailable explicitly.
        corr_meta["cap_read_active"] = "unavailable_without_capture_modification"
        corr_meta["watchdog_threshold"] = 6.0  # preserved exactly
        self.emit(camera_id, "WATCHDOG_FIRE", mono_timestamp=mono, meta=corr_meta)

    def cap_release(
        self,
        camera_id: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        mono = _MONO_CLOCK()
        self.emit(camera_id, "CAP_RELEASE", mono_timestamp=mono, meta=meta)

    def reconnect_start(self, camera_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.emit(camera_id, "RECONNECT_START", meta=meta)

    def reconnect_success(self, camera_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.emit(camera_id, "RECONNECT_SUCCESS", meta=meta)

    def reconnect_failure(self, camera_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.emit(camera_id, "RECONNECT_FAILURE", meta=meta)

    # ------------------------------------------------------------------
    # Resource telemetry (low-overhead periodic sampling; clearly separated)
    # ------------------------------------------------------------------
    def sample_resources(
        self,
        camera_id: str,
        meta_extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Sampling must be clearly separated from frame latency events.
        # We emit as a special meta-only event; do NOT allocate persistent GPU tensors.
        try:
            import psutil  # optional; best-effort
            process = psutil.Process(os.getpid())
            process_cpu = process.cpu_percent(interval=None)
            process_rss = process.memory_info().rss
            system_ram = psutil.virtual_memory()
            resource_meta: Dict[str, Any] = {
                "resource_sample": True,
                "process_cpu_percent": process_cpu,
                "process_rss_bytes": process_rss,
                "system_ram_available_bytes": system_ram.available,
                "system_ram_percent": system_ram.percent,
            }
        except Exception:
            resource_meta = {"resource_sample": True, "resource_sample_status": "unavailable"}
        try:
            import torch
            if torch.cuda.is_available():
                resource_meta["gpu_identity"] = torch.cuda.get_device_name(0)
                resource_meta["cuda_memory_allocated_bytes"] = torch.cuda.memory_allocated(0)
                resource_meta["cuda_memory_reserved_bytes"] = torch.cuda.memory_reserved(0)
                resource_meta["gpu_utilization_available"] = False  # requires nvidia-smi / nvml; not forced
            else:
                resource_meta["cuda_available"] = False
        except Exception:
            resource_meta["torch_cuda_sample"] = "unavailable"
        # Merge extra meta (e.g., camera-id-specific correlation)
        resource_meta.update(meta_extra or {})
        # We emit this under a distinct event name so it does not mix with
        # latency-bound pipeline stages; it is clearly separated per mandate.
        self.emit(camera_id, "QUEUE_PUT", meta=resource_meta)

    # ------------------------------------------------------------------
    # Event retrieval (for validation / logging; bounded)
    # ------------------------------------------------------------------
    def get_events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def clear_events(self) -> None:
        with self._lock:
            self._events.clear()

    def event_count(self) -> int:
        with self._lock:
            return len(self._events)


# ------------------------------------------------------------------
# Global singleton instance (can be disabled globally)
# ------------------------------------------------------------------
_global_instrument: Optional[Phase1CInstrument] = None


def get_instrument() -> Phase1CInstrument:
    global _global_instrument
    if _global_instrument is None:
        _global_instrument = Phase1CInstrument()
    return _global_instrument


def disable_instrumentation() -> None:
    global ENABLE_INSTRUMENTATION
    ENABLE_INSTRUMENTATION = False


def enable_instrumentation() -> None:
    global ENABLE_INSTRUMENTATION
    ENABLE_INSTRUMENTATION = True
