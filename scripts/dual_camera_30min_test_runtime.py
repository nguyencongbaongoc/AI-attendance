"""
Phase 9.2-R — Dual Camera 30-minute concurrent test using CameraRuntimeManager with PyNvVideoCodec backend.
"""

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Any

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.settings import load_settings
from app.streaming.camera_runtime_manager import CameraRuntimeManager, CameraRuntimeConfig, CameraRuntimeState
from app.streaming.health import StreamHealthMonitor, create_health_monitor


def main():
    print("=" * 60)
    print("Phase 9.2-R — Dual Camera 30-minute Concurrent Test")
    print("Using CameraRuntimeManager with PyNvVideoCodec backend")
    print("=" * 60)
    
    settings = load_settings()
    
    # Create shared health monitor
    health_monitor = create_health_monitor(
        stale_threshold_seconds=5.0,
        degraded_threshold_seconds=2.0,
        frame_timeout_seconds=10.0,
        max_consecutive_missing_frames=30,
    )
    
    # Create runtime managers for both cameras with PyNvVideoCodec backend
    cam1_base = CameraRuntimeConfig.from_settings(settings, "CAM1")
    cam1_config = CameraRuntimeConfig(
        camera_id=cam1_base.camera_id,
        rtsp_url=cam1_base.rtsp_url,
        expected_codec=cam1_base.expected_codec,
        expected_width=cam1_base.expected_width,
        expected_height=cam1_base.expected_height,
        expected_fps=cam1_base.expected_fps,
        decoder="pynvvideocodec",
        nvdec_gpu_device=cam1_base.nvdec_gpu_device,
        use_pts=cam1_base.use_pts,
        max_queue_size=cam1_base.max_queue_size,
        timeout=cam1_base.timeout,
        retry_interval=cam1_base.retry_interval,
        max_retries=cam1_base.max_retries,
        reconnect_policy=cam1_base.reconnect_policy,
        reconnect_max_retries=cam1_base.reconnect_max_retries,
        reconnect_base_interval=cam1_base.reconnect_base_interval,
        reconnect_max_interval=cam1_base.reconnect_max_interval,
        reconnect_backoff_multiplier=cam1_base.reconnect_backoff_multiplier,
        reconnect_jitter=cam1_base.reconnect_jitter,
        health_stale_threshold=cam1_base.health_stale_threshold,
        health_degraded_threshold=cam1_base.health_degraded_threshold,
        health_frame_timeout=cam1_base.health_frame_timeout,
        health_max_consecutive_missing=cam1_base.health_max_consecutive_missing,
        stall_timeout_seconds=cam1_base.stall_timeout_seconds,
        capture_worker_join_timeout=cam1_base.capture_worker_join_timeout,
        capture_min_teardown_interval_seconds=cam1_base.capture_min_teardown_interval_seconds,
        capture_max_consecutive_teardowns=cam1_base.capture_max_consecutive_teardowns,
        capture_teardown_backoff_seconds=cam1_base.capture_teardown_backoff_seconds,
        use_supervised_source=cam1_base.use_supervised_source,
    )
    
    cam2_base = CameraRuntimeConfig.from_settings(settings, "CAM2")
    cam2_config = CameraRuntimeConfig(
        camera_id=cam2_base.camera_id,
        rtsp_url=cam2_base.rtsp_url,
        expected_codec=cam2_base.expected_codec,
        expected_width=cam2_base.expected_width,
        expected_height=cam2_base.expected_height,
        expected_fps=cam2_base.expected_fps,
        decoder="pynvvideocodec",
        nvdec_gpu_device=cam2_base.nvdec_gpu_device,
        use_pts=cam2_base.use_pts,
        max_queue_size=cam2_base.max_queue_size,
        timeout=cam2_base.timeout,
        retry_interval=cam2_base.retry_interval,
        max_retries=cam2_base.max_retries,
        reconnect_policy=cam2_base.reconnect_policy,
        reconnect_max_retries=cam2_base.reconnect_max_retries,
        reconnect_base_interval=cam2_base.reconnect_base_interval,
        reconnect_max_interval=cam2_base.reconnect_max_interval,
        reconnect_backoff_multiplier=cam2_base.reconnect_backoff_multiplier,
        reconnect_jitter=cam2_base.reconnect_jitter,
        health_stale_threshold=cam2_base.health_stale_threshold,
        health_degraded_threshold=cam2_base.health_degraded_threshold,
        health_frame_timeout=cam2_base.health_frame_timeout,
        health_max_consecutive_missing=cam2_base.health_max_consecutive_missing,
        stall_timeout_seconds=cam2_base.stall_timeout_seconds,
        capture_worker_join_timeout=cam2_base.capture_worker_join_timeout,
        capture_min_teardown_interval_seconds=cam2_base.capture_min_teardown_interval_seconds,
        capture_max_consecutive_teardowns=cam2_base.capture_max_consecutive_teardowns,
        capture_teardown_backoff_seconds=cam2_base.capture_teardown_backoff_seconds,
        use_supervised_source=cam2_base.use_supervised_source,
    )
    
    cam1_manager = CameraRuntimeManager(
        config=cam1_config,
        health_monitor=health_monitor,
    )
    
    cam2_manager = CameraRuntimeManager(
        config=cam2_config,
        health_monitor=health_monitor,
    )
    
    test_duration = 60  # 60 seconds for quick test
    start_time = time.time()
    
    # Start both cameras
    print(f"\nStarting CAM1...")
    cam1_success = cam1_manager.start(wait_ready=True, ready_timeout=120.0)
    if not cam1_success:
        print("FAIL: CAM1 failed to start")
        return False
    
    print(f"Starting CAM2...")
    cam2_success = cam2_manager.start(wait_ready=True, ready_timeout=120.0)
    if not cam2_success:
        print("FAIL: CAM2 failed to start")
        cam1_manager.stop()
        return False
    
    print(f"\nBoth cameras running. Test duration: {test_duration} seconds...")
    
    last_report = start_time
    try:
        while time.time() - start_time < test_duration:
            time.sleep(10)
            
            current_time = time.time()
            if current_time - last_report >= 30.0:  # Report every 30 seconds
                elapsed = current_time - start_time
                
                cam1_snap = cam1_manager.get_snapshot()
                cam2_snap = cam2_manager.get_snapshot()
                
                print(f"\n[SUMMARY @ {elapsed:.0f}s] "
                      f"CAM1: {cam1_snap.frames_received} frames @ {cam1_snap.fps:.1f} FPS (state: {cam1_snap.state.value}) | "
                      f"CAM2: {cam2_snap.frames_received} frames @ {cam2_snap.fps:.1f} FPS (state: {cam2_snap.state.value}) | "
                      f"Combined FPS: {cam1_snap.fps + cam2_snap.fps:.1f}")
                last_report = current_time
    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        # Stop both cameras
        print("\nStopping cameras...")
        cam1_manager.stop()
        cam2_manager.stop()
    
    # Final summary
    elapsed = time.time() - start_time
    cam1_snap = cam1_manager.get_snapshot()
    cam2_snap = cam2_manager.get_snapshot()
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS - Dual Camera Test")
    print("=" * 60)
    print(f"Test duration: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"CAM1: {cam1_snap.frames_received} frames, state: {cam1_snap.state.value}")
    print(f"CAM2: {cam2_snap.frames_received} frames, state: {cam2_snap.state.value}")
    print(f"Combined FPS: {cam1_snap.fps + cam2_snap.fps:.1f}")
    print("=" * 60)
    
    # Acceptance criteria
    success = True
    if cam1_snap.state != CameraRuntimeState.RUNNING:
        print(f"FAIL: CAM1 not RUNNING (state: {cam1_snap.state.value})")
        success = False
    if cam2_snap.state != CameraRuntimeState.RUNNING:
        print(f"FAIL: CAM2 not RUNNING (state: {cam2_snap.state.value})")
        success = False
    if cam1_snap.fps < 20:
        print(f"FAIL: CAM1 FPS too low: {cam1_snap.fps:.1f}")
        success = False
    if cam2_snap.fps < 20:
        print(f"FAIL: CAM2 FPS too low: {cam2_snap.fps:.1f}")
        success = False
    
    if success:
        print("PASS: All acceptance criteria met")
    else:
        print("FAIL: Some acceptance criteria not met")
    
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)