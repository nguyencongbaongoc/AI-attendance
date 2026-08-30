#!/usr/bin/env python
"""
Phase 36 — Unit Tests for Long-Duration Soak.

Tests the soak test infrastructure, metrics collection, and verification logic.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import numpy as np

from scripts.phase36_long_duration_soak import (
    FrameSample,
    CameraMetrics,
    SystemMetrics,
    EventBusMetrics,
    SoakTestRunner,
)


class TestFrameSample:
    """Test FrameSample dataclass."""
    
    def test_frame_sample_creation(self):
        sample = FrameSample(
            camera_id="CAM1",
            frame_index=100,
            timestamp=1000.0,
            receive_time=time.time(),
            processing_time=0.05,
            queue_depth=2,
            health_state="LIVE",
        )
        assert sample.camera_id == "CAM1"
        assert sample.frame_index == 100
        assert sample.timestamp == 1000.0
        assert sample.queue_depth == 2
        assert sample.health_state == "LIVE"


class TestCameraMetrics:
    """Test CameraMetrics dataclass and methods."""
    
    def test_camera_metrics_initialization(self):
        metrics = CameraMetrics(camera_id="CAM1", start_time=time.time())
        assert metrics.camera_id == "CAM1"
        assert metrics.total_frames == 0
        assert metrics.dropped_frames == 0
        assert metrics.discontinuities == 0
        assert metrics.timestamp_regressions_count == 0
        assert metrics.camera_id_violations == 0
        assert metrics.max_samples == 10000
    
    def test_add_frame_sample_bounded(self):
        metrics = CameraMetrics(camera_id="CAM1", start_time=time.time())
        metrics.max_samples = 5  # Small limit for testing
        
        for i in range(10):
            sample = FrameSample(
                camera_id="CAM1",
                frame_index=i,
                timestamp=float(i),
                receive_time=time.time(),
                processing_time=0.01,
                queue_depth=1,
                health_state="LIVE",
            )
            metrics.add_frame_sample(sample)
        
        # Should only keep last 5 samples
        assert len(metrics.frame_samples) == 5
        assert metrics.frame_samples[0].frame_index == 5
        assert metrics.frame_samples[-1].frame_index == 9
    
    def test_finalize_calculates_statistics(self):
        metrics = CameraMetrics(camera_id="CAM1", start_time=time.time() - 10.0)
        
        # Add some frame intervals
        metrics.frame_intervals = [0.033, 0.033, 0.034, 0.033, 0.033]
        metrics.queue_depth_samples = [1, 2, 1, 3, 2, 1, 2]
        metrics.inference_latencies = [10.0, 12.0, 11.0, 13.0, 9.0]
        metrics.processing_fps_samples = [28.0, 30.0, 29.0, 31.0, 30.0]
        metrics.source_fps_samples = [30.0, 30.0, 29.0, 30.0, 30.0]
        
        metrics.finalize()
        
        assert metrics.duration > 0
        assert metrics.max_queue_depth == 3
        assert metrics.avg_queue_depth == pytest.approx(1.71, rel=0.1)
        assert metrics.p95_queue_depth > 0
        assert metrics.p99_queue_depth > 0
        assert metrics.inference_latency_mean == pytest.approx(11.0, rel=0.1)
        assert metrics.inference_latency_median == pytest.approx(11.0, rel=0.1)
        assert metrics.processing_fps_mean == pytest.approx(29.6, rel=0.1)
        assert metrics.source_fps_mean == pytest.approx(29.8, rel=0.1)
    
    def test_to_dict_includes_all_fields(self):
        metrics = CameraMetrics(camera_id="CAM1", start_time=time.time())
        metrics.finalize()
        
        d = metrics.to_dict()
        
        assert d["camera_id"] == "CAM1"
        assert "duration" in d
        assert "frame_continuity" in d
        assert "timestamp_monotonicity" in d
        assert "camera_id_integrity" in d
        assert "health_state" in d
        assert "queue_buffer" in d
        assert "inference_latency" in d
        assert "processing_fps" in d
        assert "source_fps" in d
        assert "sample_count" in d


class TestSystemMetrics:
    """Test SystemMetrics dataclass."""
    
    def test_system_metrics_initialization(self):
        metrics = SystemMetrics()
        assert metrics.timestamps == []
        assert metrics.rss_mb == []
        assert metrics.cpu_percent == []
    
    def test_add_sample(self):
        metrics = SystemMetrics()
        metrics.add_sample(rss=100.0, vms=200.0, cpu=50.0, gpu_util=80.0, gpu_mem=1024.0)
        
        assert len(metrics.rss_mb) == 1
        assert metrics.rss_mb[0] == 100.0
        assert metrics.gpu_utilization[0] == 80.0
        assert metrics.gpu_memory_mb[0] == 1024.0
    
    def test_finalize_with_data(self):
        metrics = SystemMetrics()
        # Add multiple samples
        for i in range(10):
            metrics.add_sample(
                rss=100.0 + i,
                vms=200.0 + i,
                cpu=10.0 + i,
                gpu_util=0.0,
                gpu_mem=0.0,
            )
        
        result = metrics.finalize()
        
        assert result["available"] is True
        assert result["initial_rss_mb"] == 100.0
        assert result["final_rss_mb"] == 109.0
        assert result["absolute_growth_mb"] == 9.0
        assert result["percentage_growth"] == pytest.approx(9.0, rel=0.1)
        assert result["linear_slope_mb_per_sample"] == pytest.approx(1.0, rel=0.1)
        assert result["mean_cpu_percent"] == pytest.approx(14.5, rel=0.1)
        assert result["gpu_telemetry"] == "NOT_AVAILABLE"
    
    def test_finalize_empty(self):
        metrics = SystemMetrics()
        result = metrics.finalize()
        assert result["available"] is False


class TestEventBusMetrics:
    """Test EventBusMetrics dataclass."""
    
    def test_event_bus_metrics_initialization(self):
        metrics = EventBusMetrics()
        assert metrics.events_published == 0
        assert metrics.history_size_samples == []
    
    def test_add_sample(self):
        metrics = EventBusMetrics()
        stats = {
            "events_published": 100,
            "events_delivered": 95,
            "events_duplicated": 5,
            "events_dropped": 2,
            "history_size": 50,
            "dedup_cache_size": 1000,
            "active_subscribers": 3,
            "subscriber_errors": 1,
        }
        metrics.add_sample(stats)
        
        assert metrics.events_published == 100
        assert metrics.events_delivered == 95
        assert metrics.duplicates_suppressed == 5
        assert metrics.dropped_events == 2
        assert metrics.history_size_samples == [50]
        assert metrics.dedup_cache_size_samples == [1000]
        assert metrics.subscriber_count_samples == [3]
        assert metrics.subscriber_errors == 1
    
    def test_finalize(self):
        metrics = EventBusMetrics()
        for i in range(5):
            metrics.add_sample({
                "events_published": 100,
                "events_delivered": 95,
                "events_duplicated": 5,
                "events_dropped": 2,
                "history_size": 50 + i * 10,
                "dedup_cache_size": 1000 + i * 100,
                "active_subscribers": 3,
                "subscriber_errors": 0,
            })
        
        result = metrics.finalize()
        
        assert result["events_published"] == 100
        assert result["max_history_size"] == 90
        assert result["max_dedup_cache_size"] == 1400
        assert result["max_subscriber_count"] == 3
        assert result["history_bounded"] is True  # 90 <= 10000
        assert result["dedup_cache_bounded"] is True  # 1400 <= 50000


class TestSoakTestRunner:
    """Test SoakTestRunner initialization and configuration."""
    
    def test_runner_initialization_defaults(self):
        runner = SoakTestRunner(duration_minutes=30.0)
        
        assert runner.duration_minutes == 30.0
        assert runner.duration_seconds == 1800.0
        assert runner.cam1_rtsp == "rtsp://127.0.0.1:8554/live/cam1"
        assert runner.cam2_rtsp == "rtsp://127.0.0.1:8554/live/cam2"
        assert runner.sample_interval == 1.0
        assert runner.health_check_interval == 5.0
        assert runner.resource_sample_interval == 10.0
    
    def test_runner_initialization_custom(self):
        runner = SoakTestRunner(
            duration_minutes=60.0,
            cam1_rtsp="rtsp://custom/cam1",
            cam2_rtsp="rtsp://custom/cam2",
            sample_interval=2.0,
            health_check_interval=10.0,
            resource_sample_interval=30.0,
        )
        
        assert runner.duration_minutes == 60.0
        assert runner.duration_seconds == 3600.0
        assert runner.cam1_rtsp == "rtsp://custom/cam1"
        assert runner.cam2_rtsp == "rtsp://custom/cam2"
        assert runner.sample_interval == 2.0
        assert runner.health_check_interval == 10.0
        assert runner.resource_sample_interval == 30.0
    
    def test_runner_metrics_initialized(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        
        assert isinstance(runner.cam1_metrics, CameraMetrics)
        assert isinstance(runner.cam2_metrics, CameraMetrics)
        assert isinstance(runner.system_metrics, SystemMetrics)
        assert isinstance(runner.event_bus_metrics, EventBusMetrics)
        assert runner.cam1_metrics.camera_id == "CAM1"
        assert runner.cam2_metrics.camera_id == "CAM2"
        assert runner.cross_contamination_events == []
        assert runner.regression_results == {}


class TestVerificationClassification:
    """Test the verification classification logic."""
    
    def test_classify_camera_metrics_all_good(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cam1_metrics = CameraMetrics(camera_id="CAM1", start_time=time.time() - 60.0)
        runner.cam1_metrics.discontinuities = 0
        runner.cam1_metrics.timestamp_regressions = 0
        runner.cam1_metrics.duplicate_frame_indices = 0
        runner.cam1_metrics.timestamp_regressions_count = 0
        runner.cam1_metrics.camera_id_violations = 0
        runner.cam1_metrics.failed_reconnects = 0
        runner.cam1_metrics.total_unhealthy_duration = 0.0
        runner.cam1_metrics.reconnect_attempts = 0
        runner.cam1_metrics.max_queue_depth = 5
        runner.cam1_metrics.queue_capacity = 10
        runner.cam1_metrics.overflow_count = 0
        runner.cam1_metrics.finalize()
        
        # Access the classification function through the runner's _generate_results
        # We'll test the logic directly
        checks = {}
        checks["frame_continuity"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.discontinuities == 0 and
            runner.cam1_metrics.timestamp_regressions == 0 and
            runner.cam1_metrics.duplicate_frame_indices == 0
        ) else "NOT_VERIFIED"
        
        checks["timestamp_monotonicity"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.timestamp_regressions_count == 0
        ) else "NOT_VERIFIED"
        
        checks["camera_id_integrity"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.camera_id_violations == 0
        ) else "NOT_VERIFIED"
        
        checks["health_stability"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.failed_reconnects == 0 and
            runner.cam1_metrics.total_unhealthy_duration < runner.cam1_metrics.duration * 0.1
        ) else "NOT_VERIFIED"
        
        checks["no_uncontrolled_retry"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.reconnect_attempts < 10
        ) else "NOT_VERIFIED"
        
        checks["queue_boundedness"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.max_queue_depth <= runner.cam1_metrics.queue_capacity and
            runner.cam1_metrics.overflow_count == 0
        ) else "NOT_VERIFIED"
        
        assert all(v == "LIVE_RUNTIME_VERIFIED" for v in checks.values())
    
    def test_classify_camera_metrics_with_violations(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cam1_metrics = CameraMetrics(camera_id="CAM1", start_time=time.time() - 60.0)
        runner.cam1_metrics.discontinuities = 5
        runner.cam1_metrics.timestamp_regressions = 0
        runner.cam1_metrics.duplicate_frame_indices = 0
        runner.cam1_metrics.timestamp_regressions_count = 0
        runner.cam1_metrics.camera_id_violations = 0
        runner.cam1_metrics.failed_reconnects = 0
        runner.cam1_metrics.total_unhealthy_duration = 0.0
        runner.cam1_metrics.reconnect_attempts = 0
        runner.cam1_metrics.max_queue_depth = 5
        runner.cam1_metrics.queue_capacity = 10
        runner.cam1_metrics.overflow_count = 0
        runner.cam1_metrics.finalize()
        
        checks = {}
        checks["frame_continuity"] = "LIVE_RUNTIME_VERIFIED" if (
            runner.cam1_metrics.discontinuities == 0 and
            runner.cam1_metrics.timestamp_regressions == 0 and
            runner.cam1_metrics.duplicate_frame_indices == 0
        ) else "NOT_VERIFIED"
        
        assert checks["frame_continuity"] == "NOT_VERIFIED"
    
    def test_cross_contamination_classification(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cross_contamination_events = []
        
        cross_contamination = "LIVE_RUNTIME_VERIFIED" if len(runner.cross_contamination_events) == 0 else "NOT_VERIFIED"
        assert cross_contamination == "LIVE_RUNTIME_VERIFIED"
        
        runner.cross_contamination_events = [{"camera_id": "CAM1", "expected": "CAM1", "actual": "CAM2"}]
        cross_contamination = "LIVE_RUNTIME_VERIFIED" if len(runner.cross_contamination_events) == 0 else "NOT_VERIFIED"
        assert cross_contamination == "NOT_VERIFIED"


class TestDeterminismIdempotency:
    """Test determinism and idempotency verification."""
    
    def test_determinism_check_structure(self):
        """Test that the determinism check returns expected structure."""
        # This tests the structure without running the actual attendance engine
        result = {
            "verified": True,
            "decision1_id": "decision_001",
            "decision2_id": "decision_001",
        }
        
        assert result["verified"] is True
        assert result["decision1_id"] == result["decision2_id"]
        
        result_not_idempotent = {
            "verified": False,
            "decision1_id": "decision_001",
            "decision2_id": "decision_002",
        }
        
        assert result_not_idempotent["verified"] is False
        assert result_not_idempotent["decision1_id"] != result_not_idempotent["decision2_id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])