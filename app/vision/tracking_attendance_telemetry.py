"""
Phase 11 WP3/WP4 — Tracking, Line Crossing, Attendance Persistence & Telemetry.

Integrates AI inference outputs into:
- Tracker (ByteTrack) with per-camera isolation
- CrossingEngine (IN/OUT line crossing)
- AttendanceEngine (policy-based decisions)
- End-to-end latency telemetry (nanosecond precision)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.geometry.contract import load_geometry_config
from app.geometry.crossing import CrossingEngine, create_crossing_engine
from app.in_out.raw_event import RawEventEngine, create_raw_event_engine
from app.in_out.resolver import RepeatedInOutResolver, create_repeated_in_out_resolver
from app.in_out.resolver_contract import ResolvedTransition
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.attendance.engine import AttendanceEngine, AttendanceDecisionContext
from app.attendance.timetable import Timetable
from app.attendance.policy import AttendancePolicy
from app.vision.tracker import TrackerConfig, track_frame
from app.vision.association import associate_detections, AssociationConfig
from app.vision.association_contract import AssociationResult
from app.vision.yolo_person_detector import PersonDetection
from app.vision.gpu_ai_bridge import GPUAIOutput
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract

logger = logging.getLogger(__name__)


@dataclass
class TrackingAttendanceResult:
    """Result of tracking + attendance processing for a frame."""
    frame_index: int
    timestamp: float
    camera_id: str
    
    # Tracking
    tracks: List[Any] = field(default_factory=list)
    active_tracks: List[Any] = field(default_factory=list)
    
    # Crossing
    crossing_events: List[Any] = field(default_factory=list)
    
    # Attendance
    raw_events: List[Any] = field(default_factory=list)
    transitions: List[ResolvedTransition] = field(default_factory=list)
    attendance_decisions: List[Any] = field(default_factory=list)
    
    # Latency (nanoseconds)
    t_ai_inference_done_ns: int = 0
    t_tracking_start_ns: int = 0
    t_tracking_done_ns: int = 0
    t_crossing_done_ns: int = 0
    t_attendance_persisted_ns: int = 0
    
    # Latency breakdowns (milliseconds)
    latency_tracking_ms: float = 0.0
    latency_crossing_ms: float = 0.0
    latency_attendance_ms: float = 0.0
    latency_total_post_ai_ms: float = 0.0


class TrackingAttendanceProcessor:
    """
    Processes AI inference outputs through tracking, crossing, and attendance.
    
    Maintains per-camera isolation for tracker state.
    Implements event debouncing for crossing events.
    Decouples attendance persistence from video pipeline.
    """
    
    def __init__(
        self,
        camera_id: str,
        config: Optional[Dict] = None,
        timetable: Optional[Timetable] = None,
        attendance_policy: Optional[AttendancePolicy] = None,
    ):
        self.camera_id = camera_id
        self.config = config or {}
        
        # Tracker state (per-camera isolation - Invariant #3, #10)
        self._tracker_state: List[Any] = []
        self._tracker_config = TrackerConfig()
        self._association_config = AssociationConfig()
        
        # Crossing engine
        self._crossing_engine: Optional[CrossingEngine] = None
        self._geometry = load_geometry_config(camera_id)
        if self._geometry:
            self._crossing_engine = create_crossing_engine(self._geometry)
        
        # Attendance pipeline
        self._raw_event_engine: Optional[RawEventEngine] = None
        self._resolver: Optional[RepeatedInOutResolver] = None
        self._attendance_repo: Optional[AttendanceRepository] = None
        self._attendance_engine: Optional[AttendanceEngine] = None
        
        if timetable and attendance_policy:
            self._raw_event_engine = create_raw_event_engine()
            self._resolver = create_repeated_in_out_resolver()
            self._attendance_repo = create_attendance_repository()
            self._attendance_engine = AttendanceEngine(attendance_policy)
            self._timetable = timetable
            self._attendance_policy = attendance_policy
        
        # Crossing event debouncing (prevent duplicate events near boundary)
        self._last_crossing_events: Dict[str, Dict] = {}  # track_id -> {event, timestamp}
        self._debounce_seconds = 2.0  # Minimum time between same-direction crossings
        
        # Telemetry
        self._latency_history: List[TrackingAttendanceResult] = []
        self._lock = threading.Lock()
        
        logger.info(f"TrackingAttendanceProcessor({camera_id}): initialized")
    
    def process(
        self,
        gpu_ai_output: GPUAIOutput,
        frame: GPUFrameContract,
        t_ai_inference_done_ns: int,
    ) -> TrackingAttendanceResult:
        """
        Process AI outputs through tracking -> crossing -> attendance pipeline.
        
        Args:
            gpu_ai_output: Outputs from GPU AI Bridge (SCRFD, ArcFace, YOLO, ReID)
            frame: Original GPUFrameContract with timestamps
            t_ai_inference_done_ns: Timestamp when AI inference completed
            
        Returns:
            TrackingAttendanceResult with all pipeline outputs and latency metrics
        """
        # Handle both GPUFrameContract and CanonicalFrame
        if hasattr(frame, 'frame_id'):
            # GPUFrameContract
            frame_index = frame.frame_id
            frame_timestamp = frame.timestamp
        elif hasattr(frame, 'metadata') and frame.metadata is not None:
            # CanonicalFrame
            frame_index = frame.metadata.frame_index
            frame_timestamp = frame.metadata.timestamp
        else:
            frame_index = 0
            frame_timestamp = time.time()
        
        result = TrackingAttendanceResult(
            frame_index=frame_index,
            timestamp=frame_timestamp,
            camera_id=self.camera_id,
            t_ai_inference_done_ns=t_ai_inference_done_ns,
        )
        
        # ===== TIMING: Tracking Start =====
        result.t_tracking_start_ns = time.time_ns()
        t_tracking_start = time.perf_counter()
        
        # Step 1: Parse AI outputs to detections
        face_detections = self._parse_scrfd_outputs(gpu_ai_output)
        person_detections = self._parse_yolo_outputs(gpu_ai_output)
        
        # Step 2: Association (person <-> face)
        association_result = associate_detections(
            person_detections=list(person_detections),
            face_detections=list(face_detections),
            frame=frame,  # Pass GPUFrameContract which has width/height
            config=self._association_config,
        )
        
        # Step 3: Tracking (ByteTrack)
        tracking_result = track_frame(
            list(person_detections),
            list(face_detections),
            association_result,
            frame,  # Pass GPUFrameContract for metadata
            self._tracker_state or [],
            self._tracker_config,
        )
        self._tracker_state = list(tracking_result.tracks)
        
        result.tracks = self._tracker_state
        result.active_tracks = [t for t in self._tracker_state if t.is_active]
        
        result.t_tracking_done_ns = time.time_ns()
        result.latency_tracking_ms = (time.perf_counter() - t_tracking_start) * 1000
        
        # ===== TIMING: Crossing Start =====
        t_crossing_start = time.perf_counter()
        
        # Step 4: Line Crossing Detection
        if self._crossing_engine and result.active_tracks:
            for track in result.active_tracks:
                events = self._crossing_engine.process_track(
                    track=track,
                    frame_index=frame_index,
                    timestamp=frame_timestamp,
                    global_observation_id=getattr(track, 'global_observation_id', None),
                )
                
                # Debounce crossing events
                debounced_events = self._debounce_crossing_events(track.track_id, events)
                result.crossing_events.extend(debounced_events)
        
        result.t_crossing_done_ns = time.time_ns()
        result.latency_crossing_ms = (time.perf_counter() - t_crossing_start) * 1000
        
        # ===== TIMING: Attendance Start =====
        t_attendance_start = time.perf_counter()
        
        # Step 5: Attendance Pipeline (decoupled from video encoding)
        if result.crossing_events and self._raw_event_engine and self._resolver and self._attendance_repo:
            # Convert crossing events to raw events
            raw_results = self._raw_event_engine.process_crossing_events(result.crossing_events)
            raw_events = [r.event for r in raw_results if r.success and r.event]
            result.raw_events = raw_events
            
            if raw_events:
                # Resolve to transitions
                resolution_result = self._resolver.resolve_events(raw_events)
                result.transitions = list(resolution_result.transitions)
                
                # Persist to attendance repository (decoupled)
                persistence_result = self._attendance_repo.persist_resolution_result(resolution_result)
                
                logger.debug(
                    f"{self.camera_id}: {len(result.crossing_events)} crossings -> "
                    f"{len(raw_events)} raw -> {resolution_result.accepted_transitions} transitions -> "
                    f"{persistence_result.transitions_persisted} persisted"
                )
                
                # Make attendance decisions
                if self._attendance_engine and self._timetable and self._attendance_policy:
                    for transition in resolution_result.transitions:
                        try:
                            # Convert Unix timestamp to seconds-from-midnight
                            # This is a simplification - in production use calendar engine
                            event_timestamp_sfm = self._unix_to_sfm(transition.source_timestamp)
                            
                            context = AttendanceDecisionContext(
                                resolved_transition=transition,
                                timetable=self._timetable,
                                attendance_policy=self._attendance_policy,
                            )
                            # Temporarily override timestamp for decision logic
                            # The engine expects seconds-from-midnight
                            decision = self._attendance_engine.make_decision(context)
                            result.attendance_decisions.append(decision)
                        except Exception as e:
                            logger.warning(f"{self.camera_id}: Attendance decision failed: {e}")
        
        result.t_attendance_persisted_ns = time.time_ns()
        result.latency_attendance_ms = (time.perf_counter() - t_attendance_start) * 1000
        result.latency_total_post_ai_ms = (
            result.latency_tracking_ms + 
            result.latency_crossing_ms + 
            result.latency_attendance_ms
        )
        
        # Record telemetry
        self._record_latency(result)
        
        return result
    
    def _parse_scrfd_outputs(self, gpu_ai_output: GPUAIOutput) -> List[Any]:
        """Parse SCRFD ONNX outputs to face detections."""
        # Get outputs as numpy for parsing
        outputs_np = [out.numpy() for out in gpu_ai_output.scrfd_outputs]
        
        # SCRFD 10G has 9 outputs
        if len(outputs_np) != 9:
            logger.warning(f"Unexpected SCRFD output count: {len(outputs_np)}")
            return []
        
        # Use parsing logic from GPUFaceDetector
        # This is a simplified version - full implementation in gpu_face_detector.py
        from app.vision.gpu_face_detector import GPUFaceDetector, GPUFaceDetectorConfig
        
        # Create temporary detector for parsing (or reuse parsing logic)
        # For now return empty - full integration in pipeline
        return []
    
    def _parse_yolo_outputs(self, gpu_ai_output: GPUAIOutput) -> List[PersonDetection]:
        """Parse YOLO outputs to person detections."""
        # YOLO detector returns PersonDetection directly
        # In gpu_ai_bridge, YOLO detections are returned as list
        return []  # Would be populated from YOLO output
    
    def _debounce_crossing_events(self, track_id: str, events: List[Any]) -> List[Any]:
        """
        Debounce crossing events to prevent duplicate IN/OUT when dwelling near boundary.
        
        Rules:
        - Same track, same direction: require minimum time gap
        - Different direction: allow immediately (IN then OUT is valid)
        """
        debounced = []
        current_time = time.time()
        
        for event in events:
            direction = getattr(event, 'direction', None)
            key = f"{track_id}:{direction}"
            
            if key in self._last_crossing_events:
                last_time = self._last_crossing_events[key]['timestamp']
                if current_time - last_time < self._debounce_seconds:
                    logger.debug(f"Debounced {direction} for track {track_id} (gap: {current_time - last_time:.1f}s)")
                    continue
            
            debounced.append(event)
            self._last_crossing_events[key] = {'event': event, 'timestamp': current_time}
        
        return debounced
    
    def _unix_to_sfm(self, unix_timestamp: float) -> int:
        """Convert Unix timestamp to seconds-from-midnight (simplified)."""
        from datetime import datetime
        import pytz
        dt = datetime.fromtimestamp(unix_timestamp, tz=pytz.UTC)
        dt_local = dt.astimezone(pytz.timezone('Asia/Ho_Chi_Minh'))  # Or configured timezone
        return dt_local.hour * 3600 + dt_local.minute * 60 + dt_local.second
    
    def _record_latency(self, result: TrackingAttendanceResult):
        """Record latency for telemetry."""
        with self._lock:
            self._latency_history.append(result)
            # Keep last 1000 frames
            if len(self._latency_history) > 1000:
                self._latency_history = self._latency_history[-1000:]
    
    def get_latency_percentiles(self) -> Dict[str, Dict]:
        """Get rolling percentile latencies."""
        with self._lock:
            if not self._latency_history:
                return {}
            
            import numpy as np
            
            latencies = {
                'tracking': [r.latency_tracking_ms for r in self._latency_history],
                'crossing': [r.latency_crossing_ms for r in self._latency_history],
                'attendance': [r.latency_attendance_ms for r in self._latency_history],
                'total_post_ai': [r.latency_total_post_ai_ms for r in self._latency_history],
            }
            
            summary = {}
            for name, values in latencies.items():
                if values:
                    summary[name] = {
                        'count': len(values),
                        'p50': float(np.percentile(values, 50)),
                        'p95': float(np.percentile(values, 95)),
                        'p99': float(np.percentile(values, 99)),
                        'min': float(np.min(values)),
                        'max': float(np.max(values)),
                        'jitter': float(np.percentile(values, 99) - np.percentile(values, 50)),
                        'mean': float(np.mean(values)),
                    }
            
            return summary
    
    def reset_tracker(self):
        """Reset tracker state (for camera restart)."""
        self._tracker_state = []
        self._last_crossing_events = {}
        logger.info(f"TrackingAttendanceProcessor({self.camera_id}): tracker state reset")


class EndToEndTelemetry:
    """
    End-to-end latency telemetry with nanosecond precision.
    
    Tracks all processing stages from packet ingress to attendance persistence.
    Logs rolling window percentiles (p50, p95, p99, Min, Max, Jitter) every 10 seconds.
    """
    
    def __init__(
        self,
        camera_id: str,
        window_seconds: float = 10.0,
        log_interval_seconds: float = 10.0,
    ):
        self.camera_id = camera_id
        self.window_seconds = window_seconds
        self.log_interval_seconds = log_interval_seconds
        
        # Rolling window data
        self._samples: List[Dict] = []
        self._lock = threading.Lock()
        self._last_log_time = time.time()
        
        # Counters
        self._total_frames = 0
        self._dropped_frames = 0
    
    def record_frame(
        self,
        timestamps: Dict[str, int],
        vram_allocated_mb: int = 0,
        vram_reserved_mb: int = 0,
    ):
        """
        Record a complete frame's timestamps.
        
        Expected timestamp keys:
        - t_packet_ingress_ns
        - t_decode_submit_ns
        - t_gpu_frame_ready_ns
        - t_pipeline_egress_ns (or t_ai_preprocess_start_ns)
        - t_ai_preprocess_start_ns
        - t_ai_inference_start_ns
        - t_ai_inference_done_ns
        - t_tracking_start_ns
        - t_tracking_done_ns
        - t_crossing_done_ns
        - t_attendance_persisted_ns
        """
        with self._lock:
            # Calculate all latency components (nanoseconds -> milliseconds)
            sample = {
                'timestamp': time.time(),
                'frame_index': self._total_frames,
                'vram_allocated_mb': vram_allocated_mb,
                'vram_reserved_mb': vram_reserved_mb,
            }
            
            # Decoder latencies
            if 't_packet_ingress_ns' in timestamps and 't_gpu_frame_ready_ns' in timestamps:
                sample['decode_ms'] = (timestamps['t_gpu_frame_ready_ns'] - timestamps['t_packet_ingress_ns']) / 1_000_000
            if 't_packet_ingress_ns' in timestamps and 't_decode_submit_ns' in timestamps:
                sample['queue_ms'] = (timestamps['t_decode_submit_ns'] - timestamps['t_packet_ingress_ns']) / 1_000_000
            if 't_decode_submit_ns' in timestamps and 't_gpu_frame_ready_ns' in timestamps:
                sample['decode_only_ms'] = (timestamps['t_gpu_frame_ready_ns'] - timestamps['t_decode_submit_ns']) / 1_000_000
            
            # AI preprocessing
            if 't_ai_preprocess_start_ns' in timestamps and 't_ai_inference_start_ns' in timestamps:
                sample['preprocess_ms'] = (timestamps['t_ai_inference_start_ns'] - timestamps['t_ai_preprocess_start_ns']) / 1_000_000
            
            # AI inference
            if 't_ai_inference_start_ns' in timestamps and 't_ai_inference_done_ns' in timestamps:
                sample['inference_ms'] = (timestamps['t_ai_inference_done_ns'] - timestamps['t_ai_inference_start_ns']) / 1_000_000
            
            # Tracking
            if 't_tracking_start_ns' in timestamps and 't_tracking_done_ns' in timestamps:
                sample['tracking_ms'] = (timestamps['t_tracking_done_ns'] - timestamps['t_tracking_start_ns']) / 1_000_000
            
            # Crossing
            if 't_tracking_done_ns' in timestamps and 't_crossing_done_ns' in timestamps:
                sample['crossing_ms'] = (timestamps['t_crossing_done_ns'] - timestamps['t_tracking_done_ns']) / 1_000_000
            
            # Attendance
            if 't_crossing_done_ns' in timestamps and 't_attendance_persisted_ns' in timestamps:
                sample['attendance_ms'] = (timestamps['t_attendance_persisted_ns'] - timestamps['t_crossing_done_ns']) / 1_000_000
            
            # Total E2E
            if 't_packet_ingress_ns' in timestamps and 't_attendance_persisted_ns' in timestamps:
                sample['total_e2e_ms'] = (timestamps['t_attendance_persisted_ns'] - timestamps['t_packet_ingress_ns']) / 1_000_000
            
            self._samples.append(sample)
            self._total_frames += 1
            
            # Trim window
            cutoff = time.time() - self.window_seconds
            self._samples = [s for s in self._samples if s['timestamp'] > cutoff]
            
            # Log if interval elapsed
            if time.time() - self._last_log_time > self.log_interval_seconds:
                self._log_percentiles()
                self._last_log_time = time.time()
    
    def _log_percentiles(self):
        """Log rolling percentile table."""
        if not self._samples:
            return
        
        import numpy as np
        
        # Collect all latency types
        latency_types = [
            'decode_ms', 'queue_ms', 'decode_only_ms',
            'preprocess_ms', 'inference_ms',
            'tracking_ms', 'crossing_ms', 'attendance_ms',
            'total_e2e_ms'
        ]
        
        log_lines = [
            f"[{self.camera_id}] E2E TELEMETRY (window={self.window_seconds}s, frames={len(self._samples)}):",
            "  Component         | Count |   p50 |   p95 |   p99 |  Min  |  Max  | Jitter",
            "  ------------------|-------|-------|-------|-------|-------|-------|-------"
        ]
        
        for lt in latency_types:
            values = [s.get(lt, 0) for s in self._samples if lt in s and s[lt] > 0]
            if values:
                p50 = np.percentile(values, 50)
                p95 = np.percentile(values, 95)
                p99 = np.percentile(values, 99)
                min_v = np.min(values)
                max_v = np.max(values)
                jitter = p99 - p50
                log_lines.append(
                    f"  {lt:18s} | {len(values):5d} | {p50:5.1f} | {p95:5.1f} | {p99:5.1f} | "
                    f"{min_v:5.1f} | {max_v:5.1f} | {jitter:5.1f}"
                )
        
        # VRAM
        if self._samples:
            vram_alloc = [s['vram_allocated_mb'] for s in self._samples if s['vram_allocated_mb'] > 0]
            vram_res = [s['vram_reserved_mb'] for s in self._samples if s['vram_reserved_mb'] > 0]
            if vram_alloc:
                log_lines.append(f"  VRAM Allocated:  p50={np.percentile(vram_alloc,50):.0f} p95={np.percentile(vram_alloc,95):.0f} max={np.max(vram_alloc):.0f} MB")
            if vram_res:
                log_lines.append(f"  VRAM Reserved:   p50={np.percentile(vram_res,50):.0f} p95={np.percentile(vram_res,95):.0f} max={np.max(vram_res):.0f} MB")
        
        log_lines.append(f"  Frames: total={self._total_frames} dropped={self._dropped_frames}")
        
        logger.info("\n".join(log_lines))
    
    def record_drop(self):
        """Record a dropped frame."""
        with self._lock:
            self._dropped_frames += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get telemetry summary for reporting."""
        with self._lock:
            if not self._samples:
                return {'camera_id': self.camera_id, 'frames': 0}
            
            import numpy as np
            
            latency_types = [
                'decode_ms', 'queue_ms', 'decode_only_ms',
                'preprocess_ms', 'inference_ms',
                'tracking_ms', 'crossing_ms', 'attendance_ms',
                'total_e2e_ms'
            ]
            
            summary = {
                'camera_id': self.camera_id,
                'frames_in_window': len(self._samples),
                'total_frames': self._total_frames,
                'dropped_frames': self._dropped_frames,
                'drop_rate': self._dropped_frames / max(1, self._total_frames),
                'latencies': {},
            }
            
            for lt in latency_types:
                values = [s.get(lt, 0) for s in self._samples if lt in s and s[lt] > 0]
                if values:
                    summary['latencies'][lt] = {
                        'count': len(values),
                        'p50': float(np.percentile(values, 50)),
                        'p95': float(np.percentile(values, 95)),
                        'p99': float(np.percentile(values, 99)),
                        'min': float(np.min(values)),
                        'max': float(np.max(values)),
                        'jitter': float(np.percentile(values, 99) - np.percentile(values, 50)),
                        'mean': float(np.mean(values)),
                    }
            
            # VRAM stats
            vram_alloc = [s['vram_allocated_mb'] for s in self._samples if s['vram_allocated_mb'] > 0]
            vram_res = [s['vram_reserved_mb'] for s in self._samples if s['vram_reserved_mb'] > 0]
            if vram_alloc:
                summary['vram_allocated_mb'] = {
                    'p50': float(np.percentile(vram_alloc, 50)),
                    'p95': float(np.percentile(vram_alloc, 95)),
                    'max': float(np.max(vram_alloc)),
                }
            if vram_res:
                summary['vram_reserved_mb'] = {
                    'p50': float(np.percentile(vram_res, 50)),
                    'p95': float(np.percentile(vram_res, 95)),
                    'max': float(np.max(vram_res)),
                }
            
            return summary
    
    def export_jsonl(self, filepath: str):
        """Export telemetry samples to JSONL file."""
        import json
        with open(filepath, 'w') as f:
            for sample in self._samples:
                f.write(json.dumps(sample) + '\n')


def create_tracking_attendance_processor(
    camera_id: str,
    timetable: Optional[Timetable] = None,
    attendance_policy: Optional[AttendancePolicy] = None,
) -> TrackingAttendanceProcessor:
    """Factory for TrackingAttendanceProcessor."""
    return TrackingAttendanceProcessor(
        camera_id=camera_id,
        timetable=timetable,
        attendance_policy=attendance_policy,
    )


def create_telemetry(camera_id: str, **kwargs) -> EndToEndTelemetry:
    """Factory for EndToEndTelemetry."""
    return EndToEndTelemetry(camera_id=camera_id, **kwargs)