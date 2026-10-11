"""
Phase 56A.2: Controlled Ownership Telemetry Instrumentation.

Provides a thread-safe, bounded telemetry buffer for emitting ownership and
surface events without blocking the production pipeline.
"""

import queue
import threading
import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from collections import deque


@dataclass
class TelemetryEvent:
    """A single telemetry event."""
    camera: str
    frame_id: int
    surface_key: str
    data_ptr: int
    generation: int
    ownership_state: str
    ref_count: int
    timestamp_monotonic: float
    timestamp_wall: float
    event: str
    # Optional fields for specific events
    annotation_start: Optional[float] = None
    annotation_end: Optional[float] = None
    queue_depth: Optional[int] = None
    cuda_event_id: Optional[int] = None
    cuda_event_status: Optional[str] = None


class Telemetry:
    """
    Thread-safe telemetry emitter with bounded buffer.

    Events are placed in a queue and consumed by a background thread that
    writes them to a log file. If the queue is full, events are dropped and
    the drop count is recorded.
    """

    def __init__(self, maxsize: int = 1024, log_file: str = "benchmark_results/phase56a2/phase56a2.log"):
        self._queue = queue.Queue(maxsize=maxsize)
        self._log_file = log_file
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._events_emitted = 0
        self._events_dropped = 0
        self._lock = threading.Lock()
        self._started = False
        # Ensure log directory exists
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    def start(self):
        """Start the background thread."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread.start()

    def stop(self):
        """Stop the background thread."""
        self._stop_event.set()
        self._thread.join(timeout=5.0)

    def emit(self, event: TelemetryEvent) -> bool:
        """
        Emit a telemetry event.

        Returns True if the event was queued, False if dropped.
        """
        try:
            self._queue.put_nowait(event)
            with self._lock:
                self._events_emitted += 1
            return True
        except queue.Full:
            with self._lock:
                self._events_dropped += 1
            return False

    def _run(self):
        """Background thread that writes events to the log file."""
        with open(self._log_file, 'a') as f:
            while not self._stop_event.is_set():
                try:
                    # Wait for an event with a timeout to check for stop event
                    event = self._queue.get(timeout=0.1)
                    # Write event as JSON line
                    import json
                    # Convert event to dict, handling None values
                    event_dict = {
                        'camera': event.camera,
                        'frame_id': event.frame_id,
                        'surface_key': event.surface_key,
                        'data_ptr': event.data_ptr,
                        'generation': event.generation,
                        'ownership_state': event.ownership_state,
                        'ref_count': event.ref_count,
                        'timestamp_monotonic': event.timestamp_monotonic,
                        'timestamp_wall': event.timestamp_wall,
                        'event': event.event,
                    }
                    # Add optional fields if present
                    if event.annotation_start is not None:
                        event_dict['annotation_start'] = event.annotation_start
                    if event.annotation_end is not None:
                        event_dict['annotation_end'] = event.annotation_end
                    if event.queue_depth is not None:
                        event_dict['queue_depth'] = event.queue_depth
                    if event.cuda_event_id is not None:
                        event_dict['cuda_event_id'] = event.cuda_event_id
                    if event.cuda_event_status is not None:
                        event_dict['cuda_event_status'] = event.cuda_event_status
                    f.write(json.dumps(event_dict) + '\n')
                    f.flush()
                    self._queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    # Avoid crashing the telemetry thread
                    logging.error(f"Telemetry thread error: {e}")

    @property
    def events_emitted(self) -> int:
        with self._lock:
            return self._events_emitted

    @property
    def events_dropped(self) -> int:
        with self._lock:
            return self._events_dropped

    @property
    def buffer_capacity(self) -> int:
        return self._queue.maxsize


# Global telemetry instance
_telemetry_instance: Optional[Telemetry] = None


def get_telemetry() -> Telemetry:
    """Get or create the global telemetry instance."""
    global _telemetry_instance
    if _telemetry_instance is None:
        _telemetry_instance = Telemetry()
        _telemetry_instance.start()
    return _telemetry_instance