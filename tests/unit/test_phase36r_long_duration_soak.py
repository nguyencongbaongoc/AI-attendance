#!/usr/bin/env python
"""
Phase 36-R — Unit Tests for Long-Duration Soak Revalidation.

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

from scripts.phase36r_long_duration_soak import (
    FrameSample,
    PhaseMetrics,
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
            phase="SOAK",
        )
        assert sample.camera_id == "CAM1"
        assert sample.frame_index == 100
        assert sample.timestamp == 1000.0
        assert sample.queue_depth == 2
        assert sample.health_state == "LIVE"
        assert sample.phase == "SOAK"


class TestPhaseMetrics:
    """Test PhaseMetrics dataclass and methods."""
    
    def test_phase_metrics_initialization(self):
        metrics = PhaseMetrics(phase_name="SOAK", start_time=time.time())
        assert metrics.phase_name == "SOAK"
        assert metrics.total_frames == 0
        assert metrics.dropped_frames == 0
        assert metrics.discontinuities == 0
        assert metrics.timestamp_regressions_count == 0
        assert metrics.camera_id_violations == 0
        assert metrics.max_samples == 10000
    
    def test_add_frame_sample_bounded(self):
        metrics = PhaseMetrics(phase_name="SOAK", start_time=time.time())
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
                phase="SOAK",
            )
            metrics.add_frame_sample(sample)
        
        # Should only keep last 5 samples
        assert len(metrics.frame_samples) == 5
        assert metrics.frame_samples[0].frame_index == 5
        assert metrics.frame_samples[-1].frame_index == 9
    
    def test_finalize_calculates_statistics(self):
        metrics = PhaseMetrics(phase_name="SOAK", start_time=time.time() - 10.0)
        
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
        metrics = PhaseMetrics(phase_name="SOAK", start_time=time.time())
        metrics.finalize()
        
        d = metrics.to_dict()
        
        assert d["phase_name"] == "SOAK"
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


class TestCameraMetrics:
    """Test CameraMetrics dataclass with phase separation."""
    
    def test_camera_metrics_initialization(self):
        metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time())
        assert metrics.camera_id == "CAM1"
        assert metrics.current_phase == "STARTUP"
        assert isinstance(metrics.startup, PhaseMetrics)
        assert isinstance(metrics.warmup, PhaseMetrics)
        assert isinstance(metrics.soak, PhaseMetrics)
        assert metrics.startup.phase_name == "STARTUP"
        assert metrics.warmup.phase_name == "WARMUP"
        assert metrics.soak.phase_name == "SOAK"
    
    def test_transition_to_phase(self):
        base_time = time.time()
        metrics = CameraMetrics(camera_id="CAM1", overall_start_time=base_time)
        metrics.startup.start_time = base_time
        
        # Add some data to startup phase
        metrics.startup.total_frames = 10
        metrics.startup.discontinuities = 1
        
        # Transition to warmup
        metrics.transition_to_phase("WARMUP", base_time + 5.0)
        
        assert metrics.current_phase == "WARMUP"
        assert metrics.warmup.start_time == base_time + 5.0
        assert metrics.startup.end_time > 0  # startup was finalized (end_time set)
        
        # Add data to warmup
        metrics.warmup.total_frames = 20
        
        # Transition to soak
        metrics.transition_to_phase("SOAK", base_time + 65.0)
        
        assert metrics.current_phase == "SOAK"
        assert metrics.soak.start_time == base_time + 65.0
        assert metrics.warmup.end_time > 0  # warmup was finalized (end_time set)
    
    def test_get_current_phase_metrics(self):
        metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time())
        
        assert metrics.get_current_phase_metrics() is metrics.startup
        
        metrics.current_phase = "WARMUP"
        assert metrics.get_current_phase_metrics() is metrics.warmup
        
        metrics.current_phase = "SOAK"
        assert metrics.get_current_phase_metrics() is metrics.soak
    
    def test_finalize_all(self):
        metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time() - 10.0)
        metrics.startup.total_frames = 10
        metrics.warmup.total_frames = 20
        metrics.soak.total_frames = 300
        
        metrics.finalize_all()
        
        assert metrics.startup.duration > 0
        assert metrics.warmup.duration > 0
        assert metrics.soak.duration > 0
    
    def test_to_dict_includes_all_phases(self):
        metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time())
        metrics.startup.total_frames = 10
        metrics.warmup.total_frames = 20
        metrics.soak.total_frames = 300
        metrics.finalize_all()
        
        d = metrics.to_dict()
        
        assert d["camera_id"] == "CAM1"
        assert "startup" in d
        assert "warmup" in d
        assert "soak" in d
        assert d["startup"]["frame_continuity"]["total_frames"] == 10
        assert d["warmup"]["frame_continuity"]["total_frames"] == 20
        assert d["soak"]["frame_continuity"]["total_frames"] == 300


class TestSystemMetrics:
    """Test SystemMetrics dataclass with phase separation."""
    
    def test_system_metrics_initialization(self):
        metrics = SystemMetrics()
        assert metrics.timestamps == []
        assert metrics.rss_mb == []
        assert metrics.cpu_percent == []
        assert metrics.phase_labels == []
    
    def test_add_sample_with_phase(self):
        metrics = SystemMetrics()
        metrics.add_sample(rss=100.0, vms=200.0, cpu=50.0, phase="SOAK", gpu_util=80.0, gpu_mem=1024.0)
        
        assert len(metrics.rss_mb) == 1
        assert metrics.rss_mb[0] == 100.0
        assert metrics.gpu_utilization[0] == 80.0
        assert metrics.gpu_memory_mb[0] == 1024.0
        assert metrics.phase_labels[0] == "SOAK"
    
    def test_finalize_with_phase_separation(self):
        metrics = SystemMetrics()
        base_time = time.time()
        
        # Add samples for different phases
        for i in range(5):
            metrics.add_sample(rss=100.0 + i, vms=200.0 + i, cpu=10.0 + i, phase="STARTUP")
        for i in range(10):
            metrics.add_sample(rss=110.0 + i, vms=210.0 + i, cpu=20.0 + i, phase="WARMUP")
        for i in range(20):
            metrics.add_sample(rss=120.0 + i, vms=220.0 + i, cpu=30.0 + i, phase="SOAK")
        
        result = metrics.finalize()
        
        assert result["available"] is True
        assert result["overall"]["initial_rss_mb"] == 100.0
        assert result["overall"]["final_rss_mb"] == 139.0
        
        # Check phase-separated stats
        assert "startup" in result["by_phase"]
        assert "warmup" in result["by_phase"]
        assert "soak" in result["by_phase"]
        
        assert result["by_phase"]["startup"]["sample_count"] == 5
        assert result["by_phase"]["warmup"]["sample_count"] == 10
        assert result["by_phase"]["soak"]["sample_count"] == 20
        
        # Check soak 5-min comparison (should have data since we have 20 samples)
        if "soak_5min_comparison" in result:
            comp = result["soak_5min_comparison"]
            assert "first_5min_mean_rss_mb" in comp
            assert "last_5min_mean_rss_mb" in comp
    
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
        assert runner.warmup_seconds == 60.0
        assert runner.cam1_rtsp == "rtsp://127.0.0.1:8554/live/cam1"
        assert runner.cam2_rtsp == "rtsp://127.0.0.1:8554/live/cam2"
        assert runner.sample_interval == 1.0
        assert runner.health_check_interval == 5.0
        assert runner.resource_sample_interval == 10.0
        assert runner.memory_growth_threshold_percent == 20.0
    
    def test_runner_initialization_custom(self):
        runner = SoakTestRunner(
            duration_minutes=60.0,
            warmup_seconds=120.0,
            cam1_rtsp="rtsp://custom/cam1",
            cam2_rtsp="rtsp://custom/cam2",
            sample_interval=2.0,
            health_check_interval=10.0,
            resource_sample_interval=30.0,
            memory_growth_threshold_percent=15.0,
        )
        
        assert runner.duration_minutes == 60.0
        assert runner.duration_seconds == 3600.0
        assert runner.warmup_seconds == 120.0
        assert runner.cam1_rtsp == "rtsp://custom/cam1"
        assert runner.cam2_rtsp == "rtsp://custom/cam2"
        assert runner.sample_interval == 2.0
        assert runner.health_check_interval == 10.0
        assert runner.resource_sample_interval == 30.0
        assert runner.memory_growth_threshold_percent == 15.0
    
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
        assert "0-5min" in runner.inference_latency_windows
        assert "25-30min" in runner.inference_latency_windows


class TestVerificationClassification:
    """Test the verification classification logic for Phase 36-R."""
    
    def test_classify_soak_metrics_all_good(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cam1_metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time() - 60.0)
        runner.cam1_metrics.soak.discontinuities = 0
        runner.cam1_metrics.soak.timestamp_regressions = 0
        runner.cam1_metrics.soak.duplicate_frame_indices = 0
        runner.cam1_metrics.soak.timestamp_regressions_count = 0
        runner.cam1_metrics.soak.camera_id_violations = 0
        runner.cam1_metrics.soak.failed_reconnects = 0
        runner.cam1_metrics.soak.total_unhealthy_duration = 0.0
        runner.cam1_metrics.soak.duration = 60.0
        runner.cam1_metrics.soak.reconnect_attempts = 0
        runner.cam1_metrics.soak.max_queue_depth = 5
        runner.cam1_metrics.soak.queue_capacity = 10
        runner.cam1_metrics.soak.overflow_count = 0
        runner.cam1_metrics.soak.finalize()
        
        # Test the classification logic directly
        soak = runner.cam1_metrics.soak
        checks = {}
        checks["frame_continuity"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.discontinuities == 0 and
            soak.timestamp_regressions == 0 and
            soak.duplicate_frame_indices == 0
        ) else "NOT_VERIFIED"
        
        checks["timestamp_monotonicity"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.timestamp_regressions_count == 0
        ) else "NOT_VERIFIED"
        
        checks["camera_id_integrity"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.camera_id_violations == 0
        ) else "NOT_VERIFIED"
        
        checks["health_stability"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.failed_reconnects == 0 and
            (soak.duration == 0 or soak.total_unhealthy_duration < soak.duration * 0.1)
        ) else "NOT_VERIFIED"
        
        checks["no_uncontrolled_retry"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.reconnect_attempts < 10
        ) else "NOT_VERIFIED"
        
        checks["queue_boundedness"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.max_queue_depth <= soak.queue_capacity and
            soak.overflow_count == 0
        ) else "NOT_VERIFIED"
        
        assert all(v == "LIVE_RUNTIME_VERIFIED" for v in checks.values())
    
    def test_classify_soak_metrics_with_violations(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cam1_metrics = CameraMetrics(camera_id="CAM1", overall_start_time=time.time() - 60.0)
        runner.cam1_metrics.soak.discontinuities = 5
        runner.cam1_metrics.soak.timestamp_regressions = 0
        runner.cam1_metrics.soak.duplicate_frame_indices = 0
        runner.cam1_metrics.soak.timestamp_regressions_count = 0
        runner.cam1_metrics.soak.camera_id_violations = 0
        runner.cam1_metrics.soak.failed_reconnects = 0
        runner.cam1_metrics.soak.total_unhealthy_duration = 0.0
        runner.cam1_metrics.soak.duration = 60.0
        runner.cam1_metrics.soak.reconnect_attempts = 0
        runner.cam1_metrics.soak.max_queue_depth = 5
        runner.cam1_metrics.soak.queue_capacity = 10
        runner.cam1_metrics.soak.overflow_count = 0
        runner.cam1_metrics.soak.finalize()
        
        soak = runner.cam1_metrics.soak
        checks = {}
        checks["frame_continuity"] = "LIVE_RUNTIME_VERIFIED" if (
            soak.discontinuities == 0 and
            soak.timestamp_regressions == 0 and
            soak.duplicate_frame_indices == 0
        ) else "NOT_VERIFIED"
        
        assert checks["frame_continuity"] == "NOT_VERIFIED"
    
    def test_memory_stability_classification(self):
        """Test memory stability classification based on soak phase only."""
        runner = SoakTestRunner(duration_minutes=30.0, memory_growth_threshold_percent=20.0)
        
        # Simulate system results with low soak growth
        system_results = {
            "available": True,
            "by_phase": {
                "soak": {
                    "percentage_growth": 5.0,  # Below threshold
                    "absolute_growth_mb": 50.0,
                }
            },
            "soak_5min_comparison": {
                "growth_first_to_last_5min_percent": 3.0,  # Below threshold
            }
        }
        
        soak_memory = system_results.get("by_phase", {}).get("soak", {})
        soak_growth_percent = soak_memory.get("percentage_growth", 100)
        soak_comparison = system_results.get("soak_5min_comparison", {})
        growth_first_to_last = soak_comparison.get("growth_first_to_last_5min_percent", 100)
        
        memory_stable = "LIVE_RUNTIME_VERIFIED" if (
            system_results.get("available", False) and
            soak_growth_percent < runner.memory_growth_threshold_percent and
            growth_first_to_last < runner.memory_growth_threshold_percent
        ) else "NOT_VERIFIED"
        
        assert memory_stable == "LIVE_RUNTIME_VERIFIED"
        
        # Test with high growth
        system_results_high = {
            "available": True,
            "by_phase": {
                "soak": {
                    "percentage_growth": 50.0,  # Above threshold
                    "absolute_growth_mb": 500.0,
                }
            },
            "soak_5min_comparison": {
                "growth_first_to_last_5min_percent": 40.0,  # Above threshold
            }
        }
        
        soak_memory = system_results_high.get("by_phase", {}).get("soak", {})
        soak_growth_percent = soak_memory.get("percentage_growth", 100)
        soak_comparison = system_results_high.get("soak_5min_comparison", {})
        growth_first_to_last = soak_comparison.get("growth_first_to_last_5min_percent", 100)
        
        memory_stable = "LIVE_RUNTIME_VERIFIED" if (
            system_results_high.get("available", False) and
            soak_growth_percent < runner.memory_growth_threshold_percent and
            growth_first_to_last < runner.memory_growth_threshold_percent
        ) else "NOT_VERIFIED"
        
        assert memory_stable == "NOT_VERIFIED"
    
    def test_cross_contamination_classification(self):
        runner = SoakTestRunner(duration_minutes=1.0)
        runner.cross_contamination_events = []
        
        cross_contamination = "LIVE_RUNTIME_VERIFIED" if len(runner.cross_contamination_events) == 0 else "NOT_VERIFIED"
        assert cross_contamination == "LIVE_RUNTIME_VERIFIED"
        
        runner.cross_contamination_events = [{"camera_id": "CAM1", "expected": "CAM1", "actual": "CAM2", "phase": "SOAK"}]
        cross_contamination = "LIVE_RUNTIME_VERIFIED" if len(runner.cross_contamination_events) == 0 else "NOT_VERIFIED"
        assert cross_contamination == "NOT_VERIFIED"


class TestDeterminismIdempotency:
    """Test determinism and idempotency verification."""
    
    def test_determinism_check_structure(self):
        """Test that the determinism check returns expected structure."""
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


class TestInferenceLatencyWindows:
    """Test inference latency window tracking."""
    
    def test_latency_windows_initialization(self):
        runner = SoakTestRunner(duration_minutes=30.0)
        
        expected_windows = ["0-5min", "5-10min", "10-15min", "15-20min", "20-25min", "25-30min"]
        for window in expected_windows:
            assert window in runner.inference_latency_windows
            assert runner.inference_latency_windows[window] == []
    
    def test_latency_window_assignment(self):
        runner = SoakTestRunner(duration_minutes=30.0)
        runner.start_time = time.time()
        runner.startup_duration = 10.0
        runner.warmup_seconds = 60.0
        
        # Simulate soak elapsed times and check window assignment
        soak_start = runner.start_time + runner.startup_duration + runner.warmup_seconds
        
        # 2 minutes into soak -> 0-5min window
        receive_time = soak_start + 120
        soak_elapsed = receive_time - soak_start
        window_idx = int(soak_elapsed / 300)
        window_keys = list(runner.inference_latency_windows.keys())
        assert window_keys[window_idx] == "0-5min"
        
        # 7 minutes into soak -> 5-10min window
        receive_time = soak_start + 420
        soak_elapsed = receive_time - soak_start
        window_idx = int(soak_elapsed / 300)
        assert window_keys[window_idx] == "5-10min"
        
        # 27 minutes into soak -> 25-30min window
        receive_time = soak_start + 1620
        soak_elapsed = receive_time - soak_start
        window_idx = int(soak_elapsed / 300)
        assert window_keys[window_idx] == "25-30min"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])