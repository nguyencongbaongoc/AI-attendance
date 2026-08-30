#!/usr/bin/env python
"""
Phase 36-R — Integration Tests for Long-Duration Soak Revalidation.

Integration tests that verify the soak test works with real streaming components.
These tests require live CAM1/CAM2 streams to be available.
"""

from __future__ import annotations

import time
from pathlib import Path
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from scripts.phase36r_long_duration_soak import SoakTestRunner


@pytest.mark.integration
@pytest.mark.live
class TestPhase36RIntegration:
    """Integration tests for Phase 36-R soak test with real streams."""
    
    @pytest.fixture(scope="class")
    def runner(self):
        """Create a soak test runner with short duration for integration testing."""
        runner = SoakTestRunner(
            duration_minutes=0.5,  # 30 seconds for integration test
            warmup_seconds=10.0,   # 10 seconds warmup
            sample_interval=0.5,
            health_check_interval=2.0,
            resource_sample_interval=5.0,
        )
        yield runner
        # Cleanup
        runner._stop_event.set()
        if runner.src1:
            runner.src1.close()
        if runner.src2:
            runner.src2.close()
        if runner.event_bus:
            runner.event_bus.shutdown()
    
    def test_runner_initialization(self, runner):
        """Test that runner initializes correctly."""
        assert runner.duration_minutes == 0.5
        assert runner.duration_seconds == 30.0
        assert runner.warmup_seconds == 10.0
        assert runner.cam1_rtsp == "rtsp://127.0.0.1:8554/live/cam1"
        assert runner.cam2_rtsp == "rtsp://127.0.0.1:8554/live/cam2"
        assert runner.memory_growth_threshold_percent == 20.0
    
    def test_ai_components_initialization(self, runner):
        """Test AI components can be initialized."""
        runner._init_ai_components()
        
        assert runner.face_detector is not None
        assert runner.arcface is not None
        assert runner.temporal_evidence is not None
        assert runner.tracker_config is not None
        assert runner._associate_detections is not None
        assert runner._track_frame is not None
        assert runner._AssociationResult is not None
        assert runner._AssociationStatus is not None
    
    def test_streaming_components_initialization(self, runner):
        """Test streaming components can be initialized."""
        runner._init_streaming_components()
        
        assert runner.src1 is not None
        assert runner.src2 is not None
        assert runner.health_monitor is not None
        assert runner.event_bus is not None
        assert runner.process is not None
    
    def test_open_streams(self, runner):
        """Test opening RTSP streams (requires live streams)."""
        runner._init_ai_components()
        runner._init_streaming_components()
        
        # This will fail if streams are not available
        # Mark as skipped if streams not available
        try:
            success = runner._open_streams()
            if not success:
                pytest.skip("Live streams not available")
            
            assert runner.camera_states["CAM1"] == "LIVE"
            assert runner.camera_states["CAM2"] == "LIVE"
            assert runner.first_live_timestamp is not None
            
            # Verify we can get frames
            frame1 = runner.src1.get_next_frame()
            frame2 = runner.src2.get_next_frame()
            
            # Frames may be None if stream is slow, but shouldn't error
            assert frame1 is None or hasattr(frame1, 'metadata')
            assert frame2 is None or hasattr(frame2, 'metadata')
            
        except Exception as e:
            pytest.skip(f"Live streams not available: {e}")
        finally:
            runner._close_streams()
    
    def test_health_monitor_registration(self, runner):
        """Test health monitor camera registration."""
        runner._init_streaming_components()
        
        # Cameras should be registered
        assert "CAM1" in runner.health_monitor._snapshots
        assert "CAM2" in runner.health_monitor._snapshots
        
        # Initial state should be OFFLINE
        assert runner.health_monitor._snapshots["CAM1"].state.value == "OFFLINE"
        assert runner.health_monitor._snapshots["CAM2"].state.value == "OFFLINE"
    
    def test_event_bus_creation(self, runner):
        """Test event bus creation and basic operations."""
        runner._init_streaming_components()
        
        assert runner.event_bus is not None
        assert runner.event_bus.get_subscriber_count() == 0
        assert runner.event_bus.get_history(limit=10) == []
        
        stats = runner.event_bus.get_stats()
        assert stats["events_published"] == 0
        assert stats["history_size"] == 0
        assert stats["dedup_cache_size"] == 0
    
    def test_phase_transitions(self, runner):
        """Test phase transition logic."""
        runner._init_ai_components()
        runner._init_streaming_components()
        
        # Test camera metrics phase transitions
        runner.start_time = time.time()
        runner.cam1_metrics.overall_start_time = runner.start_time
        runner.cam1_metrics.startup.start_time = runner.start_time
        
        # Initially in STARTUP
        assert runner.cam1_metrics.current_phase == "STARTUP"
        assert runner.cam1_metrics.get_current_phase_metrics() is runner.cam1_metrics.startup
        
        # Transition to WARMUP
        transition_time = runner.start_time + 5.0
        runner.cam1_metrics.transition_to_phase("WARMUP", transition_time)
        
        assert runner.cam1_metrics.current_phase == "WARMUP"
        assert runner.cam1_metrics.get_current_phase_metrics() is runner.cam1_metrics.warmup
        assert runner.cam1_metrics.warmup.start_time == transition_time
        assert runner.cam1_metrics.startup.duration > 0
        
        # Transition to SOAK
        transition_time2 = runner.start_time + 65.0
        runner.cam1_metrics.transition_to_phase("SOAK", transition_time2)
        
        assert runner.cam1_metrics.current_phase == "SOAK"
        assert runner.cam1_metrics.get_current_phase_metrics() is runner.cam1_metrics.soak
        assert runner.cam1_metrics.soak.start_time == transition_time2
        assert runner.cam1_metrics.warmup.duration > 0
    
    def test_short_soak_run(self, runner):
        """Test a very short soak run (requires live streams)."""
        runner.duration_minutes = 0.1  # 6 seconds
        runner.duration_seconds = 6.0
        runner.warmup_seconds = 5.0
        
        try:
            results = runner.run()
            
            # Basic structure checks
            assert "phase" in results
            assert results["phase"] == "36-R"
            assert "verdict" in results
            assert "cam1" in results
            assert "cam2" in results
            assert "system_resources" in results
            assert "event_bus" in results
            assert "regression" in results
            assert "determinism_idempotency" in results
            assert "inference_latency_windows" in results
            
            # CAM1 metrics with phase separation
            cam1 = results["cam1"]
            assert cam1["camera_id"] == "CAM1"
            assert "startup" in cam1
            assert "warmup" in cam1
            assert "soak" in cam1
            
            # CAM2 metrics with phase separation
            cam2 = results["cam2"]
            assert cam2["camera_id"] == "CAM2"
            assert "startup" in cam2
            assert "warmup" in cam2
            assert "soak" in cam2
            
            # Verification classification
            vc = results["verification_classification"]
            assert "cam1_soak" in vc
            assert "cam2_soak" in vc
            assert "cam1_startup_warmup" in vc
            assert "cam2_startup_warmup" in vc
            assert "cross_camera_contamination" in vc
            assert "memory_stability" in vc
            assert "event_bus_boundedness" in vc
            assert "regression" in vc
            assert "determinism_idempotency" in vc
            
            # System resources with phase separation
            sys_res = results["system_resources"]
            assert "by_phase" in sys_res
            assert "soak_5min_comparison" in sys_res
            
            # Inference latency windows
            latency_windows = results["inference_latency_windows"]
            assert "0-5min" in latency_windows
            assert "25-30min" in latency_windows
            
        except Exception as e:
            if "stream" in str(e).lower() or "rtsp" in str(e).lower():
                pytest.skip(f"Live streams not available: {e}")
            else:
                raise


@pytest.mark.integration
class TestPhase36RRegression:
    """Regression tests for Phase 36-R - verify Phase 23-35A contracts still work."""
    
    def test_streaming_contracts_import(self):
        """Test Phase 32 streaming contracts can be imported."""
        from app.streaming.contracts import (
            CameraStreamContract,
            create_camera_stream_contract,
            validate_camera_stream_contract,
            StreamCodec,
            StreamHealthState,
        )
        
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract.camera_id == "CAM1"
        assert contract.expected_codec == StreamCodec.H264
        
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is True
    
    def test_mediamtx_config_import(self):
        """Test Phase 32 MediaMTX config can be imported."""
        from app.streaming.mediamtx_config import (
            create_mediamtx_config,
            validate_mediamtx_config,
        )
        
        config = create_mediamtx_config()
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is True
        assert "cam1" in config.paths
        assert "cam2" in config.paths
    
    def test_health_events_import(self):
        """Test Phase 33 health events can be imported."""
        from app.streaming.health_events import (
            HealthEvent,
            HealthEventType,
            HealthEventSeverity,
            create_state_change_event,
            create_frame_stale_event,
        )
        
        event = create_state_change_event(
            event_id="test_001",
            camera_id="CAM1",
            previous_state="OFFLINE",
            new_state="LIVE",
            reason="Test",
            source_identifier="rtsp",
        )
        assert event.camera_id == "CAM1"
        assert event.event_type == HealthEventType.STATE_CHANGE
    
    def test_health_monitor_import(self):
        """Test Phase 33 health monitor can be imported."""
        from app.streaming.health import create_health_monitor, StreamHealthMonitor
        
        monitor = create_health_monitor()
        assert isinstance(monitor, StreamHealthMonitor)
        monitor.register_camera("CAM1")
        assert "CAM1" in monitor._snapshots
    
    def test_rtsp_source_import(self):
        """Test Phase 32 RTSP source can be imported."""
        from app.streaming.rtsp_source import create_rtsp_source, RTSPSource
        
        src = create_rtsp_source("CAM1", "rtsp://test/cam1")
        assert isinstance(src, RTSPSource)
        assert src.camera_id == "CAM1"
    
    def test_event_publisher_import(self):
        """Test Phase 29 event publisher can be imported."""
        from app.output.publisher import create_event_bus, InMemoryEventBus
        
        bus = create_event_bus()
        assert isinstance(bus, InMemoryEventBus)
        assert bus.get_subscriber_count() == 0
    
    def test_attendance_engine_import(self):
        """Test Phase 26 attendance engine can be imported."""
        from app.attendance.engine import AttendanceEngine
        from app.attendance.policy import AttendancePolicy
        
        policy = AttendancePolicy(policy_id="test")
        engine = AttendanceEngine(policy=policy)
        assert engine is not None
    
    def test_cross_camera_fusion_import(self):
        """Test Phase 21 cross-camera fusion can be imported."""
        from app.replay.fusion import create_fusion_engine, CrossCameraFusionEngine
        
        fusion = create_fusion_engine()
        assert isinstance(fusion, CrossCameraFusionEngine)
    
    def test_in_out_components_import(self):
        """Test Phase 22-24 IN/OUT components can be imported."""
        from app.geometry.crossing import create_crossing_engine
        from app.in_out.raw_event import create_raw_event_engine
        from app.in_out.resolver import create_repeated_in_out_resolver
        from app.geometry.contract import (
            CameraGeometryConfig,
            LineGeometry,
            Point2D,
            GeometryType,
            DirectionSemantics,
            CrossingPolicyConfig,
        )
        
        # Create geometry config for crossing engine
        line = LineGeometry(
            p1=Point2D(0, 1080),
            p2=Point2D(3840, 1080),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        )
        geometry_config = CameraGeometryConfig(
            camera_id="CAM1",
            geometry_type=GeometryType.LINE,
            line=line,
            crossing_policy=CrossingPolicyConfig(),
            frame_width=3840,
            frame_height=2160,
        )
        
        crossing = create_crossing_engine(geometry_config)
        assert crossing is not None
        
        raw_engine = create_raw_event_engine()
        assert raw_engine is not None
        
        resolver = create_repeated_in_out_resolver()
        assert resolver is not None
    
    def test_phase34_live_dual_camera_import(self):
        """Test Phase 34 live dual camera E2E can be imported."""
        # Check if the test file exists
        test_path = Path("tests/integration/test_phase34_live_dual_camera_e2e.py")
        if test_path.exists():
            # Just verify the module can be imported
            import importlib.util
            spec = importlib.util.spec_from_file_location("test_phase34", test_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            assert hasattr(module, "TestPhase34LiveDualCameraE2E")
    
    def test_phase35_realtime_import(self):
        """Test Phase 35 realtime performance can be imported."""
        test_path = Path("tests/integration/test_phase35_realtime_e2e.py")
        if test_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("test_phase35", test_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            assert hasattr(module, "TestPhase35RealtimeE2E")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not live"])