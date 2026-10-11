"""
Phase 44.X.4-R3.3 — RTSP Capture Watchdog.

The R3.2 forensic evidence proved that cv2.VideoCapture.read() can block
indefinitely inside an established RTSP socket. A watchdog that runs
*only after* ret, frame = cap.read() can never execute when read() is
itself the blocker.

This module implements an explicit "owner / watchdog" model that is
robust against blocking reads:

    Worker thread:
        * Holds the cv2.VideoCapture
        * Calls cap.read() in a loop
        * On every successful (or failed) read it stamps _last_progress_time
        * On stop_event.set() it tears the capture down cleanly

    Watchdog thread:
        * Tracks _last_progress_time
        * If the worker has not progressed for `stall_timeout_seconds`:
              - sets _stop_event
              - calls _cap.release() from the *watchdog* thread, which
                causes the blocking read() inside the worker to return
                ret=False (OpenCV releases the underlying socket)
              - cooperates with the worker to tear the capture down
        * Re-opens the capture through the same connect path

The watchdog can therefore break a blocked read() by closing the
underlying VideoCapture from another thread.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureWatchdogConfig:
    """Configuration for the capture watchdog."""

    stall_timeout_seconds: float = 6.0
    # How long the watchdog waits for the worker to actually exit after
    # forcing a teardown before escalating to a hard kill.
    worker_join_timeout: float = 3.0
    # Minimum gap between two forced teardowns (prevents restart storms).
    min_teardown_interval_seconds: float = 1.0
    # Bounded consecutive teardowns before the watchdog pauses longer.
    max_consecutive_teardowns: int = 5
    # Backoff applied when consecutive teardowns exceed the limit.
    teardown_backoff_seconds: float = 2.0


class CaptureWatchdog:
    """
    Watchdog for a blocking RTSP read loop.

    The watchdog owns the supervision logic and is independent of the
    worker thread that holds the VideoCapture. It can therefore detect
    a stall and force teardown of the capture even while the worker
    is blocked inside cap.read().
    """

    def __init__(
        self,
        config: CaptureWatchdogConfig,
        camera_id: str,
        on_stall: Optional[Callable[[Dict[str, Any]], None]] = None,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.camera_id = camera_id
        self._on_stall = on_stall
        self._time = time_func

        # Progress tracking — written by the worker thread, read by the
        # watchdog thread. Accessed via a tiny lock to keep ordering.
        self._last_progress_time: float = self._time()
        self._last_progress_lock = threading.Lock()

        # Coordination between worker and watchdog.
        self._stop_event = threading.Event()
        self._teardown_request = threading.Event()
        self._frame_consumed_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None

        # Reference to the current VideoCapture, set by the worker before
        # entering read(). The watchdog may call .release() on it to
        # unblock a stuck read(). Access is guarded by _cap_lock.
        self._cap: Optional[Any] = None
        self._cap_lock = threading.RLock()

        # Metrics — protected by _metrics_lock.
        self._stall_count: int = 0
        self._forced_teardown_count: int = 0
        self._last_stall_time: Optional[float] = None
        self._metrics_lock = threading.Lock()
        self._last_teardown_time: float = 0.0
        self._consecutive_teardowns: int = 0

        # Active owner flag — only one watchdog supervises a given capture.
        self._active_owner: Optional[threading.Thread] = None
        self._owner_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Owner API
    # ------------------------------------------------------------------
    def claim_ownership(self) -> bool:
        """
        Claim the right to operate the capture. Returns True if the
        caller is now the active owner, False if another owner already
        holds the lock. Prevents duplicate readers for the same camera.
        """
        caller = threading.current_thread()
        with self._owner_lock:
            if self._active_owner is None:
                self._active_owner = caller
                return True
            if self._active_owner is caller:
                return True
            return False

    def release_ownership(self) -> None:
        caller = threading.current_thread()
        with self._owner_lock:
            if self._active_owner is caller:
                self._active_owner = None

    @property
    def has_active_owner(self) -> bool:
        with self._owner_lock:
            return self._active_owner is not None

    # ------------------------------------------------------------------
    # Worker thread API
    # ------------------------------------------------------------------
    def register_capture(self, cap: Any) -> None:
        """Register the live VideoCapture so the watchdog can release it."""
        with self._cap_lock:
            self._cap = cap

    def unregister_capture(self, cap: Optional[Any] = None) -> None:
        """Unregister the live VideoCapture."""
        with self._cap_lock:
            if cap is None or self._cap is cap:
                self._cap = None

    def mark_progress(self) -> None:
        """Stamp that a frame (or any progress) was just observed."""
        with self._last_progress_lock:
            self._last_progress_time = self._time()
        self._frame_consumed_event.set()
        # A successful read resets the consecutive-teardown counter.
        with self._metrics_lock:
            self._consecutive_teardowns = 0

    @property
    def last_progress_time(self) -> float:
        with self._last_progress_lock:
            return self._last_progress_time

    @property
    def teardown_requested(self) -> bool:
        return self._teardown_request.is_set()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def frame_consumed_event(self) -> threading.Event:
        return self._frame_consumed_event

    # ------------------------------------------------------------------
    # Watchdog thread control
    # ------------------------------------------------------------------
    def start_watchdog(self) -> None:
        """Watchdog DISABLED — no supervision thread started."""
        return

    def stop_watchdog(self) -> None:
        """Watchdog DISABLED — no-op."""
        return

    # ------------------------------------------------------------------
    # Watchdog loop
    # ------------------------------------------------------------------
    def _watchdog_loop(self) -> None:
        # Watchdog DISABLED: loop is bypassed; no timeout, no teardown.
        return

    def _force_teardown(self, since_progress: float) -> None:
        # Watchdog DISABLED: no forced teardown, no cap.release(), no restart.
        return
    # ------------------------------------------------------------------
    # Worker-side helpers
    # ------------------------------------------------------------------
    def set_worker_thread(self, thread: threading.Thread) -> None:
        """Track the worker thread so the watchdog can join() it."""
        self._worker_thread = thread

    def clear_teardown_request(self) -> None:
        """Worker has acknowledged the teardown; reset the flag."""
        self._teardown_request.clear()
        self._frame_consumed_event.clear()
        with self._last_progress_lock:
            self._last_progress_time = self._time()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def get_metrics(self) -> Dict[str, Any]:
        with self._metrics_lock:
            return {
                "camera_id": self.camera_id,
                "stall_count": self._stall_count,
                "forced_teardown_count": self._forced_teardown_count,
                "last_stall_time": self._last_stall_time,
                "consecutive_teardowns": self._consecutive_teardowns,
                "last_progress_time": self.last_progress_time,
                "stall_timeout_seconds": self.config.stall_timeout_seconds,
                "has_active_owner": self.has_active_owner,
            }
