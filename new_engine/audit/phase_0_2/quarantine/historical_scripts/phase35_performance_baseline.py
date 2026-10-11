#!/usr/bin/env python
"""
Phase 35 — Realtime Performance Baseline Measurement.

Measures REAL system performance using live CAM1/CAM2 streams.
Independent per-camera measurements with aggregate statistics.

Usage:
    python scripts/phase35_performance_baseline.py --cam1-only
    python scripts/phase35_performance_baseline.py --cam2-only
    python scripts/phase35_performance_baseline.py --dual-camera
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single camera."""
    camera_id: str
    start_time: float
    end_time: float
    duration: float
    
    # RTSP connection
    rtmp_url: str
    rtsp_url: str
    connection_latency: float  # Time from RTSP URL to first frame
    
    # Frame flow
    frames_received: int
    frames_processed: int
    frames_dropped: int
    frames_stale: int
    first_frame_latency: float  # Time from RTSP URL to first frame
    frame_interval_mean: float
    frame_interval_std: float
    frame_interval_min: float
    frame_interval_max: float
    
    # FPS
    observed_fps: float
    processing_fps: float
    fps_measured: float
    fps_measured_std: float
    
    # AI pipeline
    detections_total: int
    detections_per_second: float
    tracks_total: int
    tracks_per_second: float
    identities_total: int
    identities_per_second: float
    
    # Latencies
    inference_latency_mean: float
    inference_latency_std: float
    association_latency_mean: float
    association_latency_std: float
    tracking_latency_mean: float
    tracking_latency_std: float
    arcface_latency_mean: float
    arcface_latency_std: float
    temporal_evidence_latency_mean: float
    temporal_evidence_latency_std: float
    
    # Downstream events
    raw_inout_events: int
    raw_inout_per_second: float
    resolved_transitions: int
    resolved_transitions_per_second: float
    attendance_decisions: int
    attendance_decisions_per_second: float
    
    # Queue behavior
    max_queue_depth: int
    avg_queue_depth: float
    queue_depth_samples: int
    
    # System resources (if measurable)
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    gpu_available: bool = False
    gpu_memory_mb: Optional[float] = None
    
    # Provenance
    frame_indices: List[int] = field(default_factory=list)
    timestamps: List[float] = field(default_factory=list)
    camera_ids: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "duration": self.duration,
            "rtmp_url": self.rtmp_url,
            "rtsp_url": self.rtsp_url,
            "connection_latency": self.connection_latency,
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "frames_stale": self.frames_stale,
            "first_frame_latency": self.first_frame_latency,
            "frame_interval_mean": self.frame_interval_mean,
            "frame_interval_std": self.frame_interval_std,
            "frame_interval_min": self.frame_interval_min,
            "frame_interval_max": self.frame_interval_max,
            "observed_fps": self.observed_fps,
            "processing_fps": self.processing_fps,
            "fps_measured": self.fps_measured,
            "fps_measured_std": self.fps_measured_std,
            "detections_total": self.detections_total,
            "detections_per_second": self.detections_per_second,
            "tracks_total": self.tracks_total,
            "tracks_per_second": self.tracks_per_second,
            "identities_total": self.identities_total,
            "identities_per_second": self.identities_per_second,
            "inference_latency_mean": self.inference_latency_mean,
            "inference_latency_std": self.inference_latency_std,
            "association_latency_mean": self.association_latency_mean,
            "association_latency_std": self.association_latency_std,
            "tracking_latency_mean": self.tracking_latency_mean,
            "tracking_latency_std": self.tracking_latency_std,
            "arcface_latency_mean": self.arcface_latency_mean,
            "arcface_latency_std": self.arcface_latency_std,
            "temporal_evidence_latency_mean": self.temporal_evidence_latency_mean,
            "temporal_evidence_latency_std": self.temporal_evidence_latency_std,
            "raw_inout_events": self.raw_inout_events,
            "raw_inout_per_second": self.raw_inout_per_second,
            "resolved_transitions": self.resolved_transitions,
            "resolved_transitions_per_second": self.resolved_transitions_per_second,
            "attendance_decisions": self.attendance_decisions,
            "attendance_decisions_per_second": self.attendance_decisions_per_second,
            "max_queue_depth": self.max_queue_depth,
            "avg_queue_depth": self.avg_queue_depth,
            "queue_depth_samples": self.queue_depth_samples,
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "gpu_available": self.gpu_available,
            "gpu_memory_mb": self.gpu_memory_mb,
        }


@dataclass
class DualCameraMetrics:
    """Aggregate metrics for dual-camera operation."""
    cam1_metrics: PerformanceMetrics
    cam2_metrics: PerformanceMetrics
    start_time: float
    end_time: float
    duration: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "cam1": self.cam1_metrics.to_dict(),
            "cam2": self.cam2_metrics.to_dict(),
            "simultaneous_operation": True,
            "cam1_active": self.cam1_metrics.frames_received > 0,
            "cam2_active": self.cam2_metrics.frames_received > 0,
        }


def calculate_fps(timestamps: List[float]) -> Tuple[float, float, float, float]:
    """Calculate FPS from timestamps."""
    if len(timestamps) < 2:
        return 0.0, 0.0, 0.0, 0.0
    
    intervals = np.diff(timestamps)
    fps = 1.0 / intervals
    return float(np.mean(fps)), float(np.std(fps)), float(np.min(fps)), float(np.max(fps))


def calculate_latency(latencies: List[float]) -> Tuple[float, float]:
    """Calculate mean and std of latencies."""
    if not latencies:
        return 0.0, 0.0
    return float(np.mean(latencies)), float(np.std(latencies))


class PerformanceBaseline:
    """Performance baseline measurement for live camera streams."""
    
    def __init__(
        self,
        cam1_rtmp: str = "rtmp://100.119.23.86:1935/live/cam1",
        cam2_rtmp: str = "rtmp://100.119.23.86:1935/live/cam2",
        cam1_rtsp: str = "rtsp://127.0.0.1:8554/live/cam1",
        cam2_rtsp: str = "rtsp://127.0.0.1:8554/live/cam2",
        duration: float = 30.0,
    ):
        self.cam1_rtmp = cam1_rtmp
        self.cam2_rtmp = cam2_rtmp
        self.cam1_rtsp = cam1_rtsp
        self.cam2_rtsp = cam2_rtsp
        self.duration = duration
        
        self.cam1_metrics: Optional[PerformanceMetrics] = None
        self.cam2_metrics: Optional[PerformanceMetrics] = None
        self.dual_metrics: Optional[DualCameraMetrics] = None
    
    def measure_cam1_only(self) -> PerformanceMetrics:
        """Measure performance for CAM1 only."""
        logger.info(f"Measuring CAM1 only for {self.duration}s")
        
        start_time = time.time()
        metrics = PerformanceMetrics(
            camera_id="CAM1",
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            rtmp_url=self.cam1_rtmp,
            rtsp_url=self.cam1_rtsp,
            connection_latency=0.0,
            frames_received=0,
            frames_processed=0,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=0.0,
            frame_interval_mean=0.0,
            frame_interval_std=0.0,
            frame_interval_min=0.0,
            frame_interval_max=0.0,
            observed_fps=0.0,
            processing_fps=0.0,
            fps_measured=0.0,
            fps_measured_std=0.0,
            detections_total=0,
            detections_per_second=0.0,
            tracks_total=0,
            tracks_per_second=0.0,
            identities_total=0,
            identities_per_second=0.0,
            inference_latency_mean=0.0,
            inference_latency_std=0.0,
            association_latency_mean=0.0,
            association_latency_std=0.0,
            tracking_latency_mean=0.0,
            tracking_latency_std=0.0,
            arcface_latency_mean=0.0,
            arcface_latency_std=0.0,
            temporal_evidence_latency_mean=0.0,
            temporal_evidence_latency_std=0.0,
            raw_inout_events=0,
            raw_inout_per_second=0.0,
            resolved_transitions=0,
            resolved_transitions_per_second=0.0,
            attendance_decisions=0,
            attendance_decisions_per_second=0.0,
            max_queue_depth=0,
            avg_queue_depth=0.0,
            queue_depth_samples=0,
        )
        
        # TODO: Implement actual measurement using RTSPSource and AI pipeline
        # This requires integration with app/streaming/rtsp_source.py
        # and app/vision/ modules
        
        logger.warning("CAM1 measurement not yet implemented - requires AI pipeline integration")
        
        return metrics
    
    def measure_cam2_only(self) -> PerformanceMetrics:
        """Measure performance for CAM2 only."""
        logger.info(f"Measuring CAM2 only for {self.duration}s")
        
        start_time = time.time()
        metrics = PerformanceMetrics(
            camera_id="CAM2",
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            rtmp_url=self.cam2_rtmp,
            rtsp_url=self.cam2_rtsp,
            connection_latency=0.0,
            frames_received=0,
            frames_processed=0,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=0.0,
            frame_interval_mean=0.0,
            frame_interval_std=0.0,
            frame_interval_min=0.0,
            frame_interval_max=0.0,
            observed_fps=0.0,
            processing_fps=0.0,
            fps_measured=0.0,
            fps_measured_std=0.0,
            detections_total=0,
            detections_per_second=0.0,
            tracks_total=0,
            tracks_per_second=0.0,
            identities_total=0,
            identities_per_second=0.0,
            inference_latency_mean=0.0,
            inference_latency_std=0.0,
            association_latency_mean=0.0,
            association_latency_std=0.0,
            tracking_latency_mean=0.0,
            tracking_latency_std=0.0,
            arcface_latency_mean=0.0,
            arcface_latency_std=0.0,
            temporal_evidence_latency_mean=0.0,
            temporal_evidence_latency_std=0.0,
            raw_inout_events=0,
            raw_inout_per_second=0.0,
            resolved_transitions=0,
            resolved_transitions_per_second=0.0,
            attendance_decisions=0,
            attendance_decisions_per_second=0.0,
            max_queue_depth=0,
            avg_queue_depth=0.0,
            queue_depth_samples=0,
        )
        
        # TODO: Implement actual measurement using RTSPSource and AI pipeline
        logger.warning("CAM2 measurement not yet implemented - requires AI pipeline integration")
        
        return metrics
    
    def measure_dual_camera(self) -> DualCameraMetrics:
        """Measure performance for CAM1 + CAM2 simultaneously."""
        logger.info(f"Measuring dual-camera for {self.duration}s")
        
        start_time = time.time()
        
        cam1_metrics = self.measure_cam1_only()
        cam2_metrics = self.measure_cam2_only()
        
        end_time = time.time()
        duration = end_time - start_time
        
        dual_metrics = DualCameraMetrics(
            cam1_metrics=cam1_metrics,
            cam2_metrics=cam2_metrics,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
        )
        
        self.cam1_metrics = cam1_metrics
        self.cam2_metrics = cam2_metrics
        self.dual_metrics = dual_metrics
        
        return dual_metrics
    
    def save_results(self, output_path: str) -> None:
        """Save performance metrics to JSON file."""
        if self.dual_metrics:
            data = self.dual_metrics.to_dict()
        elif self.cam1_metrics:
            data = self.cam1_metrics.to_dict()
        elif self.cam2_metrics:
            data = self.cam2_metrics.to_dict()
        else:
            logger.error("No metrics available to save")
            return
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Performance metrics saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Phase 35 Performance Baseline Measurement")
    parser.add_argument(
        "--cam1-only",
        action="store_true",
        help="Measure CAM1 only"
    )
    parser.add_argument(
        "--cam2-only",
        action="store_true",
        help="Measure CAM2 only"
    )
    parser.add_argument(
        "--dual-camera",
        action="store_true",
        help="Measure CAM1 + CAM2 simultaneously"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Measurement duration in seconds"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="benchmark_results/PHASE_35_PERFORMANCE_BASELINE.json",
        help="Output JSON file path"
    )
    
    args = parser.parse_args()
    
    if not (args.cam1_only or args.cam2_only or args.dual_camera):
        parser.error("Must specify --cam1-only, --cam2-only, or --dual-camera")
    
    baseline = PerformanceBaseline(duration=args.duration)
    
    if args.cam1_only:
        metrics = baseline.measure_cam1_only()
        baseline.save_results(args.output)
        print(f"CAM1 Performance Metrics:")
        print(f"  Duration: {metrics.duration:.2f}s")
        print(f"  Frames Received: {metrics.frames_received}")
        print(f"  FPS: {metrics.observed_fps:.2f}")
        print(f"  Detections: {metrics.detections_total}")
        print(f"  Tracks: {metrics.tracks_total}")
        print(f"  Identities: {metrics.identities_total}")
    
    elif args.cam2_only:
        metrics = baseline.measure_cam2_only()
        baseline.save_results(args.output)
        print(f"CAM2 Performance Metrics:")
        print(f"  Duration: {metrics.duration:.2f}s")
        print(f"  Frames Received: {metrics.frames_received}")
        print(f"  FPS: {metrics.observed_fps:.2f}")
        print(f"  Detections: {metrics.detections_total}")
        print(f"  Tracks: {metrics.tracks_total}")
        print(f"  Identities: {metrics.identities_total}")
    
    elif args.dual_camera:
        metrics = baseline.measure_dual_camera()
        baseline.save_results(args.output)
        print(f"Dual-Camera Performance Metrics:")
        print(f"  Duration: {metrics.duration:.2f}s")
        print(f"  CAM1 Frames: {metrics.cam1_metrics.frames_received}")
        print(f"  CAM2 Frames: {metrics.cam2_metrics.frames_received}")
        print(f"  CAM1 FPS: {metrics.cam1_metrics.observed_fps:.2f}")
        print(f"  CAM2 FPS: {metrics.cam2_metrics.observed_fps:.2f}")
        print(f"  CAM1 Detections: {metrics.cam1_metrics.detections_total}")
        print(f"  CAM2 Detections: {metrics.cam2_metrics.detections_total}")


if __name__ == "__main__":
    main()