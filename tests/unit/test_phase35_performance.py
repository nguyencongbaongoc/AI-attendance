#!/usr/bin/env python
"""
Phase 35 — Unit Tests for Realtime Performance.

Tests performance measurement components and invariants.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Add project root to path
import sys
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestPerformanceMetrics:
    """Test performance metrics data structures."""

    def test_performance_metrics_creation(self):
        """Test PerformanceMetrics can be created with all fields."""
        from scripts.phase35_realtime_performance import PerformanceMetrics

        metrics = PerformanceMetrics(
            camera_id="CAM1",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        assert metrics.camera_id == "CAM1"
        assert metrics.duration == 10.0
        assert metrics.frames_received == 300

    def test_performance_metrics_to_dict(self):
        """Test PerformanceMetrics serialization."""
        from scripts.phase35_realtime_performance import PerformanceMetrics

        metrics = PerformanceMetrics(
            camera_id="CAM1",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        d = metrics.to_dict()
        assert d["camera_id"] == "CAM1"
        assert d["duration"] == 10.0
        assert d["frames_received"] == 300
        assert "inference_latency_mean" in d


class TestDualCameraMetrics:
    """Test dual-camera metrics aggregation."""

    def test_dual_camera_metrics_creation(self):
        """Test DualCameraMetrics can be created."""
        from scripts.phase35_realtime_performance import PerformanceMetrics, DualCameraMetrics

        cam1 = PerformanceMetrics(
            camera_id="CAM1",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        cam2 = PerformanceMetrics(
            camera_id="CAM2",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        dual = DualCameraMetrics(
            cam1_metrics=cam1,
            cam2_metrics=cam2,
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
        )

        assert dual.cam1_metrics.camera_id == "CAM1"
        assert dual.cam2_metrics.camera_id == "CAM2"
        assert dual.duration == 10.0

    def test_dual_camera_metrics_to_dict(self):
        """Test DualCameraMetrics serialization."""
        from scripts.phase35_realtime_performance import PerformanceMetrics, DualCameraMetrics

        cam1 = PerformanceMetrics(
            camera_id="CAM1",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        cam2 = PerformanceMetrics(
            camera_id="CAM2",
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
            rtmp_url="rtmp://test",
            rtsp_url="rtsp://test",
            connection_latency=1.0,
            frames_received=300,
            frames_processed=300,
            frames_dropped=0,
            frames_stale=0,
            first_frame_latency=1.5,
            frame_interval_mean=0.033,
            frame_interval_std=0.001,
            frame_interval_min=0.032,
            frame_interval_max=0.034,
            observed_fps=30.0,
            processing_fps=25.0,
            fps_measured=30.0,
            fps_measured_std=0.5,
            detections_total=100,
            detections_per_second=10.0,
            tracks_total=50,
            tracks_per_second=5.0,
            identities_total=10,
            identities_per_second=1.0,
            inference_latency_mean=200.0,
            inference_latency_std=20.0,
            association_latency_mean=1.0,
            association_latency_std=0.5,
            tracking_latency_mean=2.0,
            tracking_latency_std=1.0,
            arcface_latency_mean=50.0,
            arcface_latency_std=10.0,
            temporal_evidence_latency_mean=5.0,
            temporal_evidence_latency_std=2.0,
            raw_inout_events=5,
            raw_inout_per_second=0.5,
            resolved_transitions=3,
            resolved_transitions_per_second=0.3,
            attendance_decisions=2,
            attendance_decisions_per_second=0.2,
            max_queue_depth=10,
            avg_queue_depth=5.0,
            queue_depth_samples=100,
        )

        dual = DualCameraMetrics(
            cam1_metrics=cam1,
            cam2_metrics=cam2,
            start_time=time.time(),
            end_time=time.time() + 10,
            duration=10.0,
        )

        d = dual.to_dict()
        assert d["duration"] == 10.0
        assert "cam1" in d
        assert "cam2" in d
        assert d["simultaneous_operation"] is True
        assert d["cam1_active"] is True
        assert d["cam2_active"] is True


class TestLatencyCalculations:
    """Test latency calculation utilities."""

    def test_calculate_fps(self):
        """Test FPS calculation from timestamps."""
        from scripts.phase35_realtime_performance import calculate_fps

        # 30 FPS = 33.33ms intervals
        timestamps = [0.0, 0.03333, 0.06666, 0.09999, 0.13332]
        mean_fps, std_fps, min_fps, max_fps = calculate_fps(timestamps)

        assert mean_fps > 29.0
        assert mean_fps < 31.0

    def test_calculate_fps_insufficient_samples(self):
        """Test FPS calculation with insufficient samples."""
        from scripts.phase35_realtime_performance import calculate_fps

        timestamps = [0.0]
        mean_fps, std_fps, min_fps, max_fps = calculate_fps(timestamps)

        assert mean_fps == 0.0
        assert std_fps == 0.0

    def test_calculate_latency(self):
        """Test latency calculation."""
        from scripts.phase35_realtime_performance import calculate_latency

        latencies = [100.0, 110.0, 90.0, 105.0, 95.0]
        mean_lat, std_lat = calculate_latency(latencies)

        assert mean_lat == 100.0
        assert std_lat > 0.0

    def test_calculate_latency_empty(self):
        """Test latency calculation with empty list."""
        from scripts.phase35_realtime_performance import calculate_latency

        mean_lat, std_lat = calculate_latency([])

        assert mean_lat == 0.0
        assert std_lat == 0.0


class TestPerformanceInvariants:
    """Test performance invariant verification logic."""

    def test_frame_continuity_check(self):
        """Test frame index monotonicity check."""
        frame_indices = [0, 1, 2, 3, 4, 5]
        continuous = all(frame_indices[i] < frame_indices[i+1] for i in range(len(frame_indices)-1))
        assert continuous is True

        frame_indices_bad = [0, 1, 3, 2, 4]  # Not monotonic
        continuous = all(frame_indices_bad[i] < frame_indices_bad[i+1] for i in range(len(frame_indices_bad)-1))
        assert continuous is False

    def test_timestamp_monotonicity_check(self):
        """Test timestamp monotonicity check."""
        timestamps = [0.0, 0.033, 0.066, 0.099, 0.132]
        monotonic = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))
        assert monotonic is True

        timestamps_bad = [0.0, 0.066, 0.033, 0.099]  # Not monotonic
        monotonic = all(timestamps_bad[i] <= timestamps_bad[i+1] for i in range(len(timestamps_bad)-1))
        assert monotonic is False

    def test_camera_id_integrity_check(self):
        """Test camera ID integrity check."""
        cam1_ids = ["CAM1", "CAM1", "CAM1"]
        cam2_ids = ["CAM2", "CAM2", "CAM2"]

        cam1_integrity = all(cid == "CAM1" for cid in cam1_ids)
        cam2_integrity = all(cid == "CAM2" for cid in cam2_ids)

        assert cam1_integrity is True
        assert cam2_integrity is True

        # Cross contamination
        cam1_bad = ["CAM1", "CAM2", "CAM1"]
        cam1_integrity_bad = all(cid == "CAM1" for cid in cam1_bad)
        assert cam1_integrity_bad is False

    def test_bounded_queue_check(self):
        """Test bounded queue check."""
        max_depth = 100
        bounded = max_depth < 1000
        assert bounded is True

        max_depth_unbounded = 5000
        bounded = max_depth_unbounded < 1000
        assert bounded is False

    def test_uncontrolled_retry_check(self):
        """Test uncontrolled retry check."""
        reconnect_count = 3
        no_uncontrolled = reconnect_count < 10
        assert no_uncontrolled is True

        reconnect_count_high = 15
        no_uncontrolled = reconnect_count_high < 10
        assert no_uncontrolled is False


class TestRealtimePerformanceMeasurement:
    """Test the RealtimePerformanceMeasurement class."""

    def test_initialization(self):
        """Test RealtimePerformanceMeasurement initialization."""
        from scripts.phase35_realtime_performance import RealtimePerformanceMeasurement

        measurement = RealtimePerformanceMeasurement(
            duration=10.0,
            max_frames=50,
        )

        assert measurement.duration == 10.0
        assert measurement.max_frames == 50
        assert measurement.cam1_rtmp == "rtmp://100.119.23.86:1935/live/cam1"
        assert measurement.cam2_rtmp == "rtmp://100.119.23.86:1935/live/cam2"

    def test_custom_urls(self):
        """Test RealtimePerformanceMeasurement with custom URLs."""
        from scripts.phase35_realtime_performance import RealtimePerformanceMeasurement

        measurement = RealtimePerformanceMeasurement(
            cam1_rtmp="rtmp://custom:1935/live/cam1",
            cam2_rtmp="rtmp://custom:1935/live/cam2",
            cam1_rtsp="rtsp://custom:8554/live/cam1",
            cam2_rtsp="rtsp://custom:8554/live/cam2",
            duration=5.0,
            max_frames=20,
        )

        assert measurement.cam1_rtmp == "rtmp://custom:1935/live/cam1"
        assert measurement.cam2_rtmp == "rtmp://custom:1935/live/cam2"
        assert measurement.duration == 5.0
        assert measurement.max_frames == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])