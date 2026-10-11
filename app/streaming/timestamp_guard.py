"""
Phase 12 — Timestamp Guard.

Dedicated timestamp validation/sanitization layer for GPU video pipeline.
Tracks media timestamps vs pipeline timestamps, validates continuity,
and generates monotonic output timeline when source timestamps are invalid.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class TimestampAction(Enum):
    """Actions TimestampGuard can take."""
    PASS = "pass"                    # Frame timestamp is valid
    WARN = "warn"                    # Anomaly detected but frame valid
    REBASE = "rebase"                # Switch to generated timeline
    DROP_INVALID_FRAME = "drop"      # Frame integrity invalid
    WAIT_FOR_IDR = "wait_idr"        # Need IDR frame to resync


class TimestampSource(Enum):
    """Source of timestamp."""
    SOURCE_PTS = "source_pts"        # From container/decoder
    PIPELINE_MONOTONIC = "pipeline"  # Generated monotonic timeline


@dataclass
class TimestampSample:
    """Single timestamp measurement point."""
    frame_sequence_id: int
    source_pts: Optional[int] = None
    source_dts: Optional[int] = None
    arrival_time_ns: int = 0        # When frame arrived at pipeline
    decode_time_ns: int = 0         # When decode completed
    ai_time_ns: int = 0             # When AI processing completed
    encode_time_ns: int = 0         # When encode completed
    output_pts: Optional[int] = None
    output_dts: Optional[int] = None


@dataclass
class CameraTimestampState:
    """Per-camera timestamp tracking state."""
    camera_id: str
    
    # Frame sequence
    frame_sequence_id: int = 0
    expected_frame_interval_ticks: int = 3000  # 30 FPS at 90kHz timebase
    
    # Source timestamp tracking
    last_source_pts: Optional[int] = None
    last_source_dts: Optional[int] = None
    last_valid_source_pts: Optional[int] = None
    
    # Pipeline monotonic timeline
    timeline_base_ns: int = 0
    last_output_pts: Optional[int] = None
    output_timebase: int = 90000  # H.264 standard timebase
    
    # Anomaly tracking
    consecutive_anomalies: int = 0
    total_anomalies: int = 0
    rebase_count: int = 0
    last_action: TimestampAction = TimestampAction.PASS
    
    # Measured cadence (for rebase)
    measured_interval_ticks: Optional[int] = None
    interval_samples: List[int] = field(default_factory=list)
    max_interval_samples: int = 30
    
    # PTS history for validation
    pts_history: List[int] = field(default_factory=list)
    max_pts_history: int = 100
    
    def __post_init__(self):
        self.timeline_base_ns = time.monotonic_ns()


class TimestampGuard:
    """
    Validates and sanitizes timestamps for GPU video pipeline.
    
    Distinguishes:
    - MEDIA_TIMESTAMP: source PTS/DTS from container
    - PIPELINE_TIMESTAMP: monotonic runtime clock + frame sequence
    
    Policy:
    - Does not blindly copy source PTS to output
    - Detects anomalies: backward jump, large forward, zero delta, duplicate, missing
    - Rebases to monotonic timeline when source timestamps invalid
    - Per-camera independent state
    """
    
    # Anomaly thresholds
    MAX_FORWARD_JUMP_MULTIPLIER = 10.0    # >10x expected interval
    MAX_BACKWARD_JUMP_TICKS = 90000       # 1 second at 90kHz
    MIN_INTERVAL_TICKS = 90               # 1ms at 90kHz
    
    def __init__(self, expected_fps: float = 30.0, timebase: int = 90000):
        self.expected_fps = expected_fps
        self.timebase = timebase  # Source timestamp timebase (e.g., 90000 for H.264)
        self.expected_interval_ticks = int(timebase / expected_fps)
        self.cameras: Dict[str, CameraTimestampState] = {}
        self._lock = None  # Threading lock if needed
    
    def get_camera_state(self, camera_id: str) -> CameraTimestampState:
        """Get or create per-camera state."""
        if camera_id not in self.cameras:
            self.cameras[camera_id] = CameraTimestampState(
                camera_id=camera_id,
                expected_frame_interval_ticks=self.expected_interval_ticks,
            )
        return self.cameras[camera_id]
    
    def validate_frame(
        self,
        camera_id: str,
        source_pts: Optional[int],
        source_dts: Optional[int] = None,
    ) -> tuple[TimestampAction, int, TimestampSource]:
        """
        Validate a frame's timestamps and determine output PTS.
        
        Args:
            camera_id: Camera identifier
            source_pts: Source presentation timestamp (from decoder)
            source_dts: Source decode timestamp (optional)
            
        Returns:
            (action, output_pts, timestamp_source)
        """
        state = self.get_camera_state(camera_id)
        state.frame_sequence_id += 1
        frame_id = state.frame_sequence_id
        
        # First frame - initialize
        if state.last_source_pts is None:
            if source_pts is not None:
                state.last_source_pts = source_pts
                state.last_source_dts = source_dts
                state.last_valid_source_pts = source_pts
                state.timeline_base_ns = time.monotonic_ns()
                state.last_output_pts = source_pts
                logger.info(f"[{camera_id}] TimestampGuard: INIT source_pts={source_pts}, frame={frame_id}")
                return TimestampAction.PASS, source_pts, TimestampSource.SOURCE_PTS
            else:
                # No source PTS - start monotonic timeline
                state.timeline_base_ns = time.monotonic_ns()
                output_pts = int(state.timeline_base_ns / 1_000_000_000 * state.output_timebase)
                state.last_output_pts = output_pts
                logger.warning(f"[{camera_id}] TimestampGuard: NO_SOURCE_PTS frame={frame_id}, starting monotonic timeline")
                return TimestampAction.REBASE, output_pts, TimestampSource.PIPELINE_MONOTONIC
        
        # Validate source PTS
        if source_pts is not None:
            action = self._validate_source_pts(state, frame_id, source_pts, source_dts)
            
            if action == TimestampAction.PASS:
                # Use source PTS for output
                state.last_source_pts = source_pts
                state.last_source_dts = source_dts
                state.last_valid_source_pts = source_pts
                state.last_output_pts = source_pts
                
                # Update measured interval
                self._update_measured_interval(state, source_pts)
                
                return TimestampAction.PASS, source_pts, TimestampSource.SOURCE_PTS
            
            elif action == TimestampAction.WARN:
                # Anomaly but frame valid - use source PTS but warn
                state.last_source_pts = source_pts
                state.last_source_dts = source_dts
                state.last_output_pts = source_pts
                return TimestampAction.WARN, source_pts, TimestampSource.SOURCE_PTS
            
            elif action == TimestampAction.REBASE:
                # Switch to monotonic timeline
                return self._rebase_to_monotonic(state, frame_id)
            
            elif action == TimestampAction.DROP_INVALID_FRAME:
                return TimestampAction.DROP_INVALID_FRAME, 0, TimestampSource.PIPELINE_MONOTONIC
            
            elif action == TimestampAction.WAIT_FOR_IDR:
                return TimestampAction.WAIT_FOR_IDR, 0, TimestampSource.PIPELINE_MONOTONIC
        
        else:
            # No source PTS - use monotonic timeline
            return self._rebase_to_monotonic(state, frame_id)
    
    def _validate_source_pts(
        self,
        state: CameraTimestampState,
        frame_id: int,
        source_pts: int,
        source_dts: Optional[int],
    ) -> TimestampAction:
        """Validate source PTS against history."""
        
        # Check for duplicate PTS
        if source_pts == state.last_source_pts:
            logger.warning(f"[{state.camera_id}] DUPLICATE_PTS frame={frame_id} pts={source_pts}")
            state.consecutive_anomalies += 1
            state.total_anomalies += 1
            if state.consecutive_anomalies > 5:
                return TimestampAction.REBASE
            return TimestampAction.WARN
        
        # Check for backward jump
        if source_pts < state.last_source_pts:
            backward_jump = state.last_source_pts - source_pts
            logger.warning(f"[{state.camera_id}] BACKWARD_PTS frame={frame_id} pts={source_pts} "
                          f"last={state.last_source_pts} jump={backward_jump}")
            state.consecutive_anomalies += 1
            state.total_anomalies += 1
            
            if backward_jump > self.MAX_BACKWARD_JUMP_TICKS:
                logger.error(f"[{state.camera_id}] LARGE_BACKWARD_JUMP frame={frame_id} "
                           f"jump={backward_jump} ticks > {self.MAX_BACKWARD_JUMP_TICKS} ticks")
                return TimestampAction.REBASE
            return TimestampAction.WARN
        
        # Check delta
        delta = source_pts - state.last_source_pts
        
        # Check for zero/near-zero delta
        if delta < self.MIN_INTERVAL_TICKS:
            logger.warning(f"[{state.camera_id}] ZERO_DELTA frame={frame_id} delta={delta} ticks")
            state.consecutive_anomalies += 1
            state.total_anomalies += 1
            return TimestampAction.WARN
        
        # Check for large forward jump
        if state.measured_interval_ticks:
            expected = state.measured_interval_ticks
        else:
            expected = state.expected_frame_interval_ticks
        
        if delta > expected * self.MAX_FORWARD_JUMP_MULTIPLIER:
            logger.warning(f"[{state.camera_id}] LARGE_FORWARD_JUMP frame={frame_id} "
                          f"delta={delta} ticks expected~{expected} ticks ({delta/expected:.1f}x)")
            state.consecutive_anomalies += 1
            state.total_anomalies += 1
            
            if delta > expected * 100:  # Extreme jump
                return TimestampAction.REBASE
            return TimestampAction.WARN
        
        # Check DTS > PTS anomaly
        if source_dts is not None and source_pts is not None:
            if source_dts > source_pts:
                logger.warning(f"[{state.camera_id}] DTS_GT_PTS frame={frame_id} "
                              f"dts={source_dts} pts={source_pts}")
                state.consecutive_anomalies += 1
                state.total_anomalies += 1
                return TimestampAction.WARN
        
        # Valid frame - reset anomaly counter
        state.consecutive_anomalies = 0
        
        # Track PTS history
        state.pts_history.append(source_pts)
        if len(state.pts_history) > state.max_pts_history:
            state.pts_history.pop(0)
        
        return TimestampAction.PASS
    
    def _update_measured_interval(self, state: CameraTimestampState, source_pts: int) -> None:
        """Update measured frame interval from valid source PTS."""
        if state.last_valid_source_pts is not None:
            interval = source_pts - state.last_valid_source_pts
            if interval > 0:
                state.interval_samples.append(interval)
                if len(state.interval_samples) > state.max_interval_samples:
                    state.interval_samples.pop(0)
                
                # Update measured interval (median for robustness)
                if len(state.interval_samples) >= 5:
                    sorted_samples = sorted(state.interval_samples)
                    mid = len(sorted_samples) // 2
                    state.measured_interval_ticks = sorted_samples[mid]
    
    def _rebase_to_monotonic(
        self,
        state: CameraTimestampState,
        frame_id: int,
    ) -> tuple[TimestampAction, int, TimestampSource]:
        """Generate monotonic output PTS when source timestamps are invalid."""
        
        state.rebase_count += 1
        
        # Determine interval to use (in output timebase ticks)
        if state.measured_interval_ticks:
            # Convert measured interval to output timebase
            interval_output_ticks = state.measured_interval_ticks * state.output_timebase // self.timebase
        else:
            interval_output_ticks = state.expected_frame_interval_ticks * state.output_timebase // self.timebase
        
        # Generate output PTS
        if state.last_output_pts is not None:
            output_pts = state.last_output_pts + interval_output_ticks
        else:
            # First frame after rebase
            output_pts = int(state.timeline_base_ns / 1_000_000_000 * state.output_timebase)
        
        state.last_output_pts = output_pts
        
        measured_str = str(state.measured_interval_ticks) if state.measured_interval_ticks else "None"
        expected_str = str(state.expected_frame_interval_ticks)
        logger.warning(f"[{state.camera_id}] REBASE frame={frame_id} output_pts={output_pts} "
                      f"interval_output_ticks={interval_output_ticks} rebase_count={state.rebase_count} "
                      f"(measured={measured_str}, expected={expected_str})")
        
        return TimestampAction.REBASE, output_pts, TimestampSource.PIPELINE_MONOTONIC
    
    def mark_frame_decoded(self, camera_id: str) -> None:
        """Mark frame decode completion for latency tracking."""
        state = self.get_camera_state(camera_id)
        state.decode_time_ns = time.monotonic_ns()
    
    def mark_ai_completed(self, camera_id: str) -> None:
        """Mark AI processing completion."""
        state = self.get_camera_state(camera_id)
        state.ai_time_ns = time.monotonic_ns()
    
    def mark_encode_completed(self, camera_id: str) -> None:
        """Mark encode completion."""
        state = self.get_camera_state(camera_id)
        state.encode_time_ns = time.monotonic_ns()
    
    def get_output_pts(self, camera_id: str) -> Optional[int]:
        """Get last assigned output PTS for a camera."""
        state = self.get_camera_state(camera_id)
        return state.last_output_pts
    
    def get_state_summary(self, camera_id: str) -> dict:
        """Get timestamp state summary for diagnostics."""
        state = self.get_camera_state(camera_id)
        return {
            "camera_id": camera_id,
            "frame_sequence_id": state.frame_sequence_id,
            "last_source_pts": state.last_source_pts,
            "last_source_dts": state.last_source_dts,
            "last_output_pts": state.last_output_pts,
            "measured_interval_ticks": state.measured_interval_ticks,
            "expected_interval_ticks": state.expected_frame_interval_ticks,
            "consecutive_anomalies": state.consecutive_anomalies,
            "total_anomalies": state.total_anomalies,
            "rebase_count": state.rebase_count,
            "last_action": state.last_action.value,
            "pts_history_size": len(state.pts_history),
            "timebase": self.timebase,
            "output_timebase": state.output_timebase,
        }
    
    def reset_camera(self, camera_id: str) -> None:
        """Reset timestamp state for a camera (e.g., on reconnect)."""
        if camera_id in self.cameras:
            del self.cameras[camera_id]
        logger.info(f"[{camera_id}] TimestampGuard: RESET")


def create_timestamp_guard(expected_fps: float = 30.0) -> TimestampGuard:
    """Factory function."""
    return TimestampGuard(expected_fps=expected_fps)


# Integration helper for pipeline
class PipelineTimestampTracker:
    """
    Integration helper that tracks timestamps through the full pipeline.
    
    Usage:
        tracker = PipelineTimestampTracker()
        
        # At decode
        action, output_pts, source = tracker.on_decode(camera_id, frame.pts, frame.dts)
        
        # At AI completion
        tracker.on_ai_complete(camera_id)
        
        # At encode
        tracker.on_encode_complete(camera_id, output_pts)
    """
    
    def __init__(self, expected_fps: float = 30.0):
        self.guard = TimestampGuard(expected_fps)
        self.pending_frames: Dict[str, Dict[int, TimestampSample]] = {}
    
    def on_decode(
        self,
        camera_id: str,
        frame_sequence_id: int,
        source_pts: Optional[int],
        source_dts: Optional[int] = None,
    ) -> tuple[TimestampAction, int, TimestampSource]:
        """Called when frame is decoded."""
        action, output_pts, source = self.guard.validate_frame(camera_id, source_pts, source_dts)
        
        # Store sample for tracking
        if camera_id not in self.pending_frames:
            self.pending_frames[camera_id] = {}
        
        sample = TimestampSample(
            frame_sequence_id=frame_sequence_id,
            source_pts=source_pts,
            source_dts=source_dts,
            arrival_time_ns=time.monotonic_ns(),
            decode_time_ns=time.monotonic_ns(),
        )
        self.pending_frames[camera_id][frame_sequence_id] = sample
        
        return action, output_pts, source
    
    def on_ai_complete(self, camera_id: str, frame_sequence_id: int) -> None:
        """Called when AI processing completes for a frame."""
        if camera_id in self.pending_frames and frame_sequence_id in self.pending_frames[camera_id]:
            self.pending_frames[camera_id][frame_sequence_id].ai_time_ns = time.monotonic_ns()
    
    def on_encode_complete(
        self,
        camera_id: str,
        frame_sequence_id: int,
        output_pts: int,
        output_dts: Optional[int] = None,
    ) -> Optional[TimestampSample]:
        """Called when frame encoding completes. Returns completed sample."""
        if camera_id in self.pending_frames and frame_sequence_id in self.pending_frames[camera_id]:
            sample = self.pending_frames[camera_id].pop(frame_sequence_id)
            sample.encode_time_ns = time.monotonic_ns()
            sample.output_pts = output_pts
            sample.output_dts = output_dts
            return sample
        return None
    
    def get_latency_stats(self, camera_id: str) -> dict:
        """Get latency statistics for completed frames."""
        # Would need completed samples storage
        return {"camera_id": camera_id, "pending": len(self.pending_frames.get(camera_id, {}))}