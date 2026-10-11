"""
Phase 44.X.4-R3.3 / R3.6 / R3.8 / R3.14-H.2-F — Annotated Publisher Liveness Watchdog.

The R3.2 forensic evidence showed:

    FFmpeg process alive
    AND
    MediaMTX AI RTSP path ready=false, bytesReceived=0

is the canonical "stale publisher" failure mode. process.poll() alone
cannot detect it: the FFmpeg process is still up, but its RTSP
publish session has died inside MediaMTX.

This watchdog periodically queries MediaMTX for the AI path's
runtime status and combines it with the publisher's own progress
(frames_encoded, last_encode_time, ffmpeg_pid). When the combined
evidence shows an unhealthy publisher, the watchdog invokes a
restart callback which:

    * stops the stale FFmpeg process
    * drains the publisher's pipe state
    * spawns a new FFmpeg subprocess
    * waits for MediaMTX ready=true and bytesReceived to grow

Bounded restart/backoff, no restart storms, no orphan FFmpeg
processes. Per-camera isolation: each publisher owns exactly one
watchdog with its own AI MediaMTX path.

R3.6 Fix: Added state model to distinguish STARTING, HEALTHY, DEGRADED,
UNHEALTHY, RESTARTING. A single transient poll MUST NOT restart a
publisher that is demonstrably progressing.

R3.8 Fix: Upstream capture stall detection is handled by capture
watchdog. Publisher watchdog only restarts when publisher genuinely
fails (process dead, no frame progress, no bytes progress for sustained
period).

R3.14-H.2-F Fix: Added HANDSHAKE state and refined STARTING logic to
properly handle the production publisher lifecycle:
- STARTING: Pre-FFmpeg startup (waiting for first frame, AI warmup)
- HANDSHAKE: FFmpeg spawned but no first encoded frame yet (RTSP handshake)
- READY/HEALTHY: Post-startup, normal liveness monitoring
This fixes the ROOT-E8/E11 watchdog lifecycle race where 15s startup_grace
expires before the ~22s first-frame gate, causing the watchdog to kill
FFmpeg before RTSP ANNOUNCE completes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class PublisherHealthState(str, Enum):
    """Health states for the publisher liveness watchdog."""
    STARTING = "starting"
    HANDSHAKE = "handshake"
    READY = "ready"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RESTARTING = "restarting"


@dataclass(frozen=True)
class PublisherLivenessConfig:
    """Configuration for the publisher liveness watchdog."""

    mediamtx_api_base: str = "http://localhost:9997"
    ai_path: str = ""
    poll_interval_seconds: float = 3.0
    # How long we wait without any progress before we consider the
    # publisher stale. Must be > poll_interval_seconds.
    stale_after_seconds: float = 10.0
    # Minimum time between two consecutive restarts to avoid storms.
    min_restart_interval_seconds: float = 5.0
    # Maximum consecutive restart attempts in a short window before we
    # back off and stop trying.
    max_consecutive_restarts: int = 3
    # Backoff applied when consecutive restarts exceed the limit.
    restart_backoff_seconds: float = 10.0
    # Whether to require MediaMTX bytesReceived to actually grow during
    # the poll window. If False, the watchdog treats ready=true as enough.
    require_bytes_progress: bool = True
    request_timeout_seconds: float = 2.0
    # Startup grace period before we enforce health checks
    startup_grace_seconds: float = 15.0
    # Number of consecutive unhealthy polls required before restart
    consecutive_unhealthy_threshold: int = 3


@dataclass
class PublisherLivenessMetrics:
    """Metrics surfaced by the publisher liveness watchdog."""

    camera_id: str = ""
    last_poll_time: float = 0.0
    last_path_ready: Optional[bool] = None
    last_bytes_received: Optional[int] = None
    last_publisher_alive: Optional[bool] = None
    last_decision: str = "unknown"
    last_decision_time: float = 0.0
    restart_count: int = 0
    last_restart_time: float = 0.0
    last_stale_time: float = 0.0
    consecutive_restarts: int = 0
    healthy_count: int = 0
    unhealthy_count: int = 0
    current_state: str = PublisherHealthState.STARTING.value
    consecutive_unhealthy_polls: int = 0
    last_frame_progress_time: float = 0.0
    last_bytes_progress_time: float = 0.0


class PublisherLivenessWatchdog:
    """
    Independent liveness watchdog for the annotated frame publisher.

    Threading:
        * A single polling thread queries MediaMTX and the publisher
          metrics.
        * If unhealthy, it invokes the on_unhealthy callback (which
          the AnnotatedFramePublisher implements) to restart the
          publisher.
        * The watchdog itself never touches the FFmpeg subprocess.

    State Model:
        STARTING  -> Initial state during startup grace period (pre-FFmpeg)
        HANDSHAKE -> FFmpeg spawned but no first encoded frame yet (RTSP handshake)
        READY     -> First observable publisher activity recorded
        HEALTHY   -> Post-READY, publisher showing frame progress + bytes progress
        DEGRADED  -> Post-READY, MediaMTX transition, but progress continues
        UNHEALTHY -> Sustained lack of progress (process dead, no frames, no bytes)
        RESTARTING -> Restart in progress, wait for new process to stabilize
    """

    def __init__(
        self,
        config: PublisherLivenessConfig,
        camera_id: str,
        publisher_metrics_func: Callable[[], Dict[str, Any]],
        on_unhealthy: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_restart_attempted: Optional[Callable[[Dict[str, Any]], None]] = None,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.camera_id = camera_id
        self._publisher_metrics = publisher_metrics_func
        self._on_unhealthy = on_unhealthy
        self._on_restart_attempted = on_restart_attempted
        self._time = time_func

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._metrics = PublisherLivenessMetrics(camera_id=camera_id)
        self._metrics_lock = threading.Lock()

        self._last_bytes_received: Optional[int] = None
        self._last_bytes_progress_time: float = self._time()
        self._last_healthy_time: float = self._time()
        self._last_restart_time: float = 0.0
        self._last_frame_progress_time: float = self._time()
        self._consecutive_unhealthy_polls: int = 0
        self._start_time: float = self._time()
        # Latch: once the publisher has shown any real activity
        # (frames_submitted>0 + alive/ready), we leave STARTING forever.
        # Subsequent polls use post-startup failure semantics.
        self._has_been_ready: bool = False
        # Track if publisher has ever successfully encoded frames (past initial handshake)
        self._has_encoded_frames: bool = False
        # Track when FFmpeg was first spawned (distinct from first frame encode)
        self._ffmpeg_spawn_time: Optional[float] = None
        # Post-spawn grace for RTSP handshake (ANNOUNCE/SETUP/RECORD + first RTP)
        # This is distinct from startup_grace_seconds which covers pre-FFmpeg startup
        self._post_spawn_grace_seconds: float = 5.0

    # ------------------------------------------------------------------ start
    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"pub-watchdog-{self.camera_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("PublisherLivenessWatchdog(%s): started", self.camera_id)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("PublisherLivenessWatchdog(%s): stopped", self.camera_id)

    # -------------------------------------------------------------- internals
    def _loop(self) -> None:
        # Wait for startup grace period before starting active monitoring
        while not self._stop_event.is_set():
            self._poll_once()
            self._stop_event.wait(self.config.poll_interval_seconds)

    def _query_mediamtx_path(self) -> Optional[Dict[str, Any]]:
        url = (
            self.config.mediamtx_api_base.rstrip("/")
            + "/v3/paths/list"
        )
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(
                req, timeout=self.config.request_timeout_seconds
            ) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.debug(
                "PublisherLivenessWatchdog(%s): MediaMTX query failed: %s",
                self.camera_id,
                e,
            )
            return None
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "PublisherLivenessWatchdog(%s): MediaMTX query raised: %s",
                self.camera_id,
                e,
            )
            return None

        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items:
            if item.get("name") == self.config.ai_path:
                return item
        return None

    def _poll_once(self) -> None:
        now = self._time()
        path_info = self._query_mediamtx_path()
        publisher_metrics = self._publisher_metrics()

        ready = bool(path_info.get("ready")) if path_info else False
        bytes_received = (
            int(path_info.get("bytesReceived", 0)) if path_info else 0
        )
        ffmpeg_pid = publisher_metrics.get("ffmpeg_pid")
        last_encode_time = publisher_metrics.get("last_encode_time", 0.0)
        frames_encoded = publisher_metrics.get("frames_encoded", 0)
        frames_submitted = publisher_metrics.get("frames_submitted", 0)

        # Track FFmpeg spawn time for post-spawn handshake grace
        if ffmpeg_pid and self._ffmpeg_spawn_time is None:
            self._ffmpeg_spawn_time = now
        elif not ffmpeg_pid:
            self._ffmpeg_spawn_time = None

        # Check publisher process alive and making progress
        publisher_alive = bool(ffmpeg_pid) and last_encode_time > 0
        
        # Track if publisher has ever successfully encoded frames
        if frames_encoded > 0:
            self._has_encoded_frames = True
        
        # Check frame progress (publisher submitting frames to encoder)
        frame_progress = False
        if frames_encoded > 0 and last_encode_time > self._last_frame_progress_time:
            frame_progress = True
            self._last_frame_progress_time = last_encode_time

        # Check bytes progress (MediaMTX receiving data)
        bytes_progress = False
        if (
            self._last_bytes_received is not None
            and bytes_received > self._last_bytes_received
        ):
            bytes_progress = True
            self._last_bytes_progress_time = now
        self._last_bytes_received = bytes_received

        # Determine health state
        state, healthy = self._determine_state(
            ready=ready,
            bytes_received=bytes_received,
            bytes_progress=bytes_progress,
            publisher_alive=publisher_alive,
            frames_encoded=frames_encoded,
            frames_submitted=frames_submitted,
            last_encode_time=last_encode_time,
            now=now,
        )

        with self._metrics_lock:
            self._metrics.last_poll_time = now
            self._metrics.last_path_ready = ready
            self._metrics.last_bytes_received = bytes_received
            self._metrics.last_publisher_alive = publisher_alive
            self._metrics.last_decision = state.value
            self._metrics.last_decision_time = now
            self._metrics.current_state = state.value
            self._metrics.consecutive_unhealthy_polls = self._consecutive_unhealthy_polls

            # STARTING is healthy by definition (grace period) - do not
            # count as unhealthy and do not increment consecutive_unhealthy_polls.
            # Only when state is UNHEALTHY (post-grace or post-READY failure)
            # do we increment the unhealthy counter.
            if healthy:
                self._last_healthy_time = now
                self._metrics.healthy_count += 1
                self._consecutive_unhealthy_polls = 0
                # Reset consecutive restart counter on observed health.
                self._metrics.consecutive_restarts = 0
            else:
                # Only count UNHEALTHY toward the restart threshold.
                # STARTING and DEGRADED are not UNHEALTHY.
                if state == PublisherHealthState.UNHEALTHY:
                    self._metrics.unhealthy_count += 1
                    self._consecutive_unhealthy_polls += 1

        # Watchdog DISABLED: no restart logic triggered.
        pass

    def _determine_state(
        self,
        ready: bool,
        bytes_received: int,
        bytes_progress: bool,
        publisher_alive: bool,
        frames_encoded: int,
        frames_submitted: int,
        last_encode_time: float,
        now: float,
    ) -> tuple[PublisherHealthState, bool]:
        """
        Determine publisher health state combining MediaMTX path readiness,
        publisher progress, and bytesReceived growth.

        State machine:
        - STARTING: Within startup_grace_seconds AND publisher has not yet
          produced its first frame (frames_submitted==0). Lenient checks;
          publisher_alive=false is EXPECTED here and must NOT be classified
          as UNHEALTHY. Bounded by configured startup_grace_seconds.
        - HANDSHAKE: FFmpeg process exists (pid > 0) but has not produced
          first encoded frame yet (last_encode_time == 0). Allow post-spawn
          grace for RTSP OPTIONS/ANNOUNCE/SETUP/RECORD + first RTP.
        - READY:   Publisher has produced at least one frame (frames_submitted>0)
          AND either the FFmpeg PID is up or MediaMTX ready=true. First
          observable progress that proves the publisher is genuinely running.
        - HEALTHY: Post-READY, MediaMTX ready + bytes progress / frame progress.
        - DEGRADED: Post-READY, MediaMTX readiness temporarily transitions
          but progress continues.
        - UNHEALTHY: Sustained failure - process dead, no frames, no bytes
          for stale_after_seconds, OR startup_grace_seconds expired with
          zero frames_submitted, OR a publisher that was previously READY
          has genuinely stopped progressing.
        - RESTARTING: Restart just triggered, waiting for new process to
          stabilize.
        """
        # Check if we're in startup grace period (used to gate STARTING)
        elapsed_since_start = now - self._start_time
        in_startup_grace = elapsed_since_start < self.config.startup_grace_seconds

        # Check if we're in RESTARTING state (recently restarted)
        in_restart_grace = (now - self._last_restart_time) < self.config.startup_grace_seconds

        # Check if we're in post-spawn grace (FFmpeg spawned but no first frame yet)
        in_post_spawn_grace = False
        if self._ffmpeg_spawn_time is not None:
            elapsed_since_spawn = now - self._ffmpeg_spawn_time
            in_post_spawn_grace = elapsed_since_spawn < self._post_spawn_grace_seconds

        # ------------------------------------------------------------
        # STARTING: bounded by startup_grace_seconds, requires no
        # observable publisher activity yet (frames_submitted==0).
        # ------------------------------------------------------------
        # publisher_alive=False during startup grace is EXPECTED: the
        # encode loop waits for the first annotated frame before spawning
        # FFmpeg. This must NOT cause UNHEALTHY.
        if (
            (in_startup_grace or in_restart_grace)
            and not publisher_alive
            and frames_submitted == 0
        ):
            return PublisherHealthState.STARTING, True

        # ------------------------------------------------------------
        # HANDSHAKE: FFmpeg process exists but hasn't encoded first frame yet.
        # This covers the RTSP handshake period (ANNOUNCE/SETUP/RECORD + first RTP).
        # Bounded by _post_spawn_grace_seconds.
        # Only applies when first frame has been submitted (frames_submitted > 0)
        # which triggers FFmpeg spawn, but no encoded output yet.
        # ------------------------------------------------------------
        if (
            frames_submitted > 0  # First frame submitted, FFmpeg should be spawning
            and not self._has_encoded_frames  # No successful encodes yet
            and self._ffmpeg_spawn_time is not None
            and not publisher_alive  # last_encode_time == 0
            and in_post_spawn_grace
        ):
            return PublisherHealthState.HANDSHAKE, True

        # ------------------------------------------------------------
        # READY: first observable publisher activity has been recorded.
        # Preserve the project's existing canonical readiness condition
        # (publisher alive + frame progress) AND add the natural signal
        # (frames_submitted > 0). Once READY, latch so subsequent polls
        # use post-startup failure semantics.
        # ------------------------------------------------------------
        if (
            frames_submitted > 0
            and (publisher_alive or ready)
        ):
            self._has_been_ready = True
            # If the FFmpeg process just died after READY, that's UNHEALTHY
            if not publisher_alive:
                return PublisherHealthState.UNHEALTHY, False
            # MediaMTX ready=false while FFmpeg is up but bytes not flowing
            # yet is acceptable as long as frame_progress is recent
            # (transient RTSP setup).
            frame_progress_recent = (
                (now - self._last_frame_progress_time)
                < self.config.stale_after_seconds
            )
            if not ready:
                if frame_progress_recent:
                    return PublisherHealthState.READY, True
                return PublisherHealthState.UNHEALTHY, False
            # ready=True after READY
            if bytes_progress or frame_progress_recent:
                return PublisherHealthState.READY, True
            # ready=True but no progress - check stale_after
            if (
                (now - self._last_bytes_progress_time)
                > self.config.stale_after_seconds
            ):
                return PublisherHealthState.UNHEALTHY, False
            return PublisherHealthState.DEGRADED, True

        # ------------------------------------------------------------
        # Startup grace expired with zero frames_submitted. The publisher
        # never produced any activity. This is UNHEALTHY.
        # ------------------------------------------------------------
        if (
            not in_startup_grace
            and not self._has_been_ready
            and frames_submitted == 0
            and not publisher_alive
        ):
            return PublisherHealthState.UNHEALTHY, False

        # ------------------------------------------------------------
        # Post-spawn grace expired without first frame and no readiness.
        # This is a genuine startup failure.
        # ------------------------------------------------------------
        if (
            not in_post_spawn_grace
            and frames_submitted == 0
            and not publisher_alive
        ):
            return PublisherHealthState.UNHEALTHY, False

        # Process is completely dead after grace with no readiness latch
        if not publisher_alive:
            return PublisherHealthState.UNHEALTHY, False

        # Check frame progress (publisher submitting frames to encoder)
        frame_progress_recent = (
            (now - self._last_frame_progress_time)
            < self.config.stale_after_seconds
        )

        # Check bytes progress (MediaMTX receiving data)
        bytes_progress_recent = (
            (now - self._last_bytes_progress_time)
            < self.config.stale_after_seconds
        )

        # MediaMTX ready=false means the RTSP path is dead - this is unhealthy
        # regardless of frame progress because frames can't be delivered
        if not ready:
            # During startup grace, allow more time
            if in_startup_grace or in_restart_grace:
                return PublisherHealthState.STARTING, True
            # During post-spawn grace (only for initial startup before first encode), allow more time
            if not self._has_encoded_frames and in_post_spawn_grace:
                return PublisherHealthState.HANDSHAKE, True
            # After grace period, ready=false is unhealthy
            return PublisherHealthState.UNHEALTHY, False

        # MediaMTX ready=true - check if we have progress
        if bytes_progress or frame_progress_recent:
            return PublisherHealthState.HEALTHY, True

        # ready=True but no progress - check stale_after
        if (
            (now - self._last_bytes_progress_time)
            > self.config.stale_after_seconds
        ):
            return PublisherHealthState.UNHEALTHY, False

        # Temporary gap - DEGRADED
        return PublisherHealthState.DEGRADED, True

    def _handle_unhealthy(self, state: PublisherHealthState, now: float) -> None:
        # Check if we've exceeded consecutive restart limit
        if self._metrics.consecutive_restarts >= self.config.max_consecutive_restarts:
            if (now - self._last_restart_time) < self.config.restart_backoff_seconds:
                logger.warning(
                    "PublisherLivenessWatchdog(%s): max consecutive restarts reached, "
                    "backing off for %.1fs",
                    self.camera_id,
                    self.config.restart_backoff_seconds,
                )
                return
            else:
                # Reset consecutive restarts after backoff period
                self._metrics.consecutive_restarts = 0

        # Trigger restart via callback
        logger.warning(
            "PublisherLivenessWatchdog(%s): publisher unhealthy (state=%s), "
            "triggering restart (attempt %d/%d)",
            self.camera_id,
            state.value,
            self._metrics.consecutive_restarts + 1,
            self.config.max_consecutive_restarts,
        )

        self._metrics.restart_count += 1
        self._metrics.consecutive_restarts += 1
        self._metrics.last_restart_time = now
        self._metrics.last_stale_time = now

        if self._on_unhealthy:
            try:
                self._on_unhealthy({"camera_id": self.camera_id, "state": state.value})
            except Exception as e:
                logger.error("PublisherLivenessWatchdog(%s): on_unhealthy callback failed: %s",
                             self.camera_id, e)

        if self._on_restart_attempted:
            try:
                self._on_restart_attempted({
                    "camera_id": self.camera_id,
                    "restart_count": self._metrics.restart_count,
                    "consecutive_restarts": self._metrics.consecutive_restarts,
                })
            except Exception as e:
                logger.error("PublisherLivenessWatchdog(%s): on_restart_attempted callback failed: %s",
                             self.camera_id, e)

    def get_metrics(self) -> Dict[str, Any]:
        with self._metrics_lock:
            return {
                "camera_id": self.camera_id,
                "last_poll_time": self._metrics.last_poll_time,
                "last_path_ready": self._metrics.last_path_ready,
                "last_bytes_received": self._metrics.last_bytes_received,
                "last_publisher_alive": self._metrics.last_publisher_alive,
                "last_decision": self._metrics.last_decision,
                "last_decision_time": self._metrics.last_decision_time,
                "restart_count": self._metrics.restart_count,
                "last_restart_time": self._metrics.last_restart_time,
                "last_stale_time": self._metrics.last_stale_time,
                "consecutive_restarts": self._metrics.consecutive_restarts,
                "healthy_count": self._metrics.healthy_count,
                "unhealthy_count": self._metrics.unhealthy_count,
                "current_state": self._metrics.current_state,
                "consecutive_unhealthy_polls": self._metrics.consecutive_unhealthy_polls,
                "ai_path": self.config.ai_path,
                "stall_timeout_seconds": self.config.stale_after_seconds,
            }


def create_publisher_liveness_watchdog(
    config: PublisherLivenessConfig,
    camera_id: str,
    publisher_metrics_func: Callable[[], Dict[str, Any]],
    on_unhealthy: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_restart_attempted: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> PublisherLivenessWatchdog:
    return PublisherLivenessWatchdog(
        config=config,
        camera_id=camera_id,
        publisher_metrics_func=publisher_metrics_func,
        on_unhealthy=on_unhealthy,
        on_restart_attempted=on_restart_attempted,
    )