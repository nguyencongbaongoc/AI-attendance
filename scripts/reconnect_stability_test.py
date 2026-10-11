"""
Reconnect Stability Test - Phase 9.3 Closeout Workstream H
Tests controlled stream interruption/recovery for both cameras independently
and dual-camera scenario where one stream temporarily fails.
"""

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.settings import load_settings
from app.streaming.decoder_backend import DecoderBackendFactory, PyNvVideoCodecBackendConfig


@dataclass
class ReconnectMetrics:
    camera_id: str
    frame_count: int = 0
    decode_errors: int = 0
    reconnect_attempts: int = 0
    successful_reconnects: int = 0
    failed_reconnects: int = 0
    failure_detection_times: list = field(default_factory=list)
    recovery_times: list = field(default_factory=list)
    backend_at_failure: str = "unknown"
    backend_after_recovery: str = "unknown"
    running: bool = True


def reconnect_worker(stats: ReconnectMetrics, rtsp_url: str, test_duration: int, 
                     interrupt_at: float = 60, interruption_duration: float = 10):
    """Worker that tests reconnect by closing/reopening backend."""
    settings = load_settings()
    
    config = PyNvVideoCodecBackendConfig(
        camera_id=stats.camera_id,
        rtsp_url=rtsp_url,
        nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
        expected_width=settings.cameras.expected_width,
        expected_height=settings.cameras.expected_height,
        expected_fps=settings.cameras.expected_fps,
        max_queue_size=10,
        timeout=10.0,
    )
    
    start_time = time.time()
    
    try:
        # Create backend
        backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend=settings.cameras.decoder_backend,
            config=config,
            enable_fallback=True
        )
        
        stats.backend_at_failure = actual_backend
        print(f"[{stats.camera_id}] Backend: {actual_backend}")
        
        # Open stream
        info = backend.open()
        print(f"[{stats.camera_id}] Opened: {info.width}x{info.height} @ {info.fps}fps")
        
        end_time = start_time + test_duration
        interruption_triggered = False
        interruption_start = 0
        
        while time.time() < end_time and stats.running:
            current_time = time.time()
            elapsed = current_time - start_time
            
            # Trigger interruption at specified time
            if not interruption_triggered and elapsed >= interrupt_at:
                print(f"[{stats.camera_id}] [@{elapsed:.1f}s] Simulating stream interruption...")
                interruption_start = current_time
                failure_detect_start = current_time
                
                # Close backend to simulate stream loss
                backend.close()
                print(f"[{stats.camera_id}] Backend closed (simulated stream loss)")
                
                stats.failure_detection_times.append(current_time - failure_detect_start)
                interruption_triggered = True
                
                # Wait for interruption duration
                time.sleep(interruption_duration)
                
                # Attempt recovery
                print(f"[{stats.camera_id}] [@{time.time() - start_time:.1f}s] Attempting reconnect...")
                recovery_start = time.time()
                stats.reconnect_attempts += 1
                
                # Recreate backend
                backend2, actual2 = DecoderBackendFactory.create_with_fallback(
                    primary_backend=settings.cameras.decoder_backend,
                    config=config,
                    enable_fallback=True
                )
                
                stats.backend_after_recovery = actual2
                
                if actual2 != "pynvvideocodec":
                    print(f"[{stats.camera_id}] WARNING: Recovered on {actual2} (fallback)")
                
                info2 = backend2.open()
                recovery_time = time.time() - recovery_start
                stats.recovery_times.append(recovery_time)
                
                if info2:
                    print(f"[{stats.camera_id}] Reconnect SUCCESS in {recovery_time:.3f}s: {info2.width}x{info2.height}")
                    stats.successful_reconnects += 1
                    backend = backend2  # Switch to new backend
                else:
                    print(f"[{stats.camera_id}] Reconnect FAILED")
                    stats.failed_reconnects += 1
                    break
            
            # Normal frame processing
            frame = backend.get_frame()
            if frame is not None:
                with stats.__dict__.setdefault('lock', threading.Lock()):
                    stats.frame_count += 1
            else:
                time.sleep(0.01)
                
                # Check if stream died unexpectedly
                if not backend.is_opened and not interruption_triggered:
                    print(f"[{stats.camera_id}] Unexpected stream closure")
                    break
        
        backend.close()
        print(f"[{stats.camera_id}] Test completed")
        
    except Exception as e:
        print(f"[{stats.camera_id}] Error: {e}")
        import traceback
        traceback.print_exc()


def test_cam1_reconnect():
    """Test CAM1 stream loss and recovery independently."""
    print("\n" + "=" * 60)
    print("TEST: CAM1 Reconnect Stability")
    print("=" * 60)
    
    settings = load_settings()
    stats = ReconnectMetrics(camera_id="CAM1")
    
    # Short test: 120s total, interrupt at 30s for 10s
    test_duration = 120
    interrupt_at = 30
    interruption_duration = 10
    
    print(f"Duration: {test_duration}s, Interrupt at: {interrupt_at}s for {interruption_duration}s")
    
    thread = threading.Thread(
        target=reconnect_worker,
        args=(stats, settings.cameras.get_cam1_rtsp_url(), test_duration, interrupt_at, interruption_duration),
        name="CAM1-reconnect",
        daemon=True,
    )
    
    thread.start()
    thread.join(timeout=test_duration + 30)
    
    # Results
    print(f"\nCAM1 Reconnect Results:")
    print(f"  Frames processed: {stats.frame_count}")
    print(f"  Reconnect attempts: {stats.reconnect_attempts}")
    print(f"  Successful reconnects: {stats.successful_reconnects}")
    print(f"  Failed reconnects: {stats.failed_reconnects}")
    print(f"  Backend at failure: {stats.backend_at_failure}")
    print(f"  Backend after recovery: {stats.backend_after_recovery}")
    if stats.failure_detection_times:
        print(f"  Failure detection time: {stats.failure_detection_times[0]:.3f}s")
    if stats.recovery_times:
        print(f"  Recovery time: {stats.recovery_times[0]:.3f}s")
    
    success = stats.successful_reconnects > 0 and stats.failed_reconnects == 0
    print(f"  Result: {'PASS' if success else 'FAIL'}")
    return success, stats


def test_cam2_reconnect():
    """Test CAM2 stream loss and recovery independently."""
    print("\n" + "=" * 60)
    print("TEST: CAM2 Reconnect Stability")
    print("=" * 60)
    
    settings = load_settings()
    stats = ReconnectMetrics(camera_id="CAM2")
    
    test_duration = 120
    interrupt_at = 30
    interruption_duration = 10
    
    print(f"Duration: {test_duration}s, Interrupt at: {interrupt_at}s for {interruption_duration}s")
    
    thread = threading.Thread(
        target=reconnect_worker,
        args=(stats, settings.cameras.get_cam2_rtsp_url(), test_duration, interrupt_at, interruption_duration),
        name="CAM2-reconnect",
        daemon=True,
    )
    
    thread.start()
    thread.join(timeout=test_duration + 30)
    
    print(f"\nCAM2 Reconnect Results:")
    print(f"  Frames processed: {stats.frame_count}")
    print(f"  Reconnect attempts: {stats.reconnect_attempts}")
    print(f"  Successful reconnects: {stats.successful_reconnects}")
    print(f"  Failed reconnects: {stats.failed_reconnects}")
    print(f"  Backend at failure: {stats.backend_at_failure}")
    print(f"  Backend after recovery: {stats.backend_after_recovery}")
    if stats.failure_detection_times:
        print(f"  Failure detection time: {stats.failure_detection_times[0]:.3f}s")
    if stats.recovery_times:
        print(f"  Recovery time: {stats.recovery_times[0]:.3f}s")
    
    success = stats.successful_reconnects > 0 and stats.failed_reconnects == 0
    print(f"  Result: {'PASS' if success else 'FAIL'}")
    return success, stats


def test_dual_camera_one_fails():
    """Test dual-camera where one stream fails temporarily."""
    print("\n" + "=" * 60)
    print("TEST: Dual-Camera - CAM2 Fails, CAM1 Continues")
    print("=" * 60)
    
    settings = load_settings()
    
    cam1_stats = ReconnectMetrics(camera_id="CAM1")
    cam2_stats = ReconnectMetrics(camera_id="CAM2")
    
    test_duration = 120
    interrupt_at = 30
    interruption_duration = 10
    
    # CAM1 runs continuously
    def cam1_continuous(stats, rtsp_url, duration):
        config = PyNvVideoCodecBackendConfig(
            camera_id=stats.camera_id,
            rtsp_url=rtsp_url,
            nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
            expected_width=settings.cameras.expected_width,
            expected_height=settings.cameras.expected_height,
            expected_fps=settings.cameras.expected_fps,
            max_queue_size=10,
            timeout=10.0,
        )
        
        backend, actual = DecoderBackendFactory.create_with_fallback(
            primary_backend=settings.cameras.decoder_backend,
            config=config,
            enable_fallback=True
        )
        
        info = backend.open()
        print(f"[CAM1] Continuous: {actual}, {info.width}x{info.height}")
        
        end_time = time.time() + duration
        while time.time() < end_time and stats.running:
            frame = backend.get_frame()
            if frame:
                with stats.__dict__.setdefault('lock', threading.Lock()):
                    stats.frame_count += 1
            else:
                time.sleep(0.01)
        
        backend.close()
        print(f"[CAM1] Completed: {stats.frame_count} frames")
    
    # CAM2 with interruption
    cam2_thread = threading.Thread(
        target=reconnect_worker,
        args=(cam2_stats, settings.cameras.get_cam2_rtsp_url(), test_duration, interrupt_at, interruption_duration),
        name="CAM2-reconnect-dual",
        daemon=True,
    )
    
    cam1_thread = threading.Thread(
        target=cam1_continuous,
        args=(cam1_stats, settings.cameras.get_cam1_rtsp_url(), test_duration),
        name="CAM1-continuous",
        daemon=True,
    )
    
    cam1_thread.start()
    cam2_thread.start()
    
    cam1_thread.join(timeout=test_duration + 30)
    cam2_thread.join(timeout=test_duration + 30)
    
    print(f"\nDual-Camera Reconnect Results:")
    print(f"  CAM1 frames: {cam1_stats.frame_count} (continuous)")
    print(f"  CAM2 frames: {cam2_stats.frame_count} (with interruption)")
    print(f"  CAM2 reconnect attempts: {cam2_stats.reconnect_attempts}")
    print(f"  CAM2 successful: {cam2_stats.successful_reconnects}")
    print(f"  CAM2 failed: {cam2_stats.failed_reconnects}")
    print(f"  CAM2 backend at failure: {cam2_stats.backend_at_failure}")
    print(f"  CAM2 backend after recovery: {cam2_stats.backend_after_recovery}")
    
    # Verify isolation
    cam1_continued = cam1_stats.frame_count > 1000  # Should process many frames
    cam2_recovered = cam2_stats.successful_reconnects > 0
    
    print(f"  CAM1 continued: {'YES' if cam1_continued else 'NO'}")
    print(f"  CAM2 recovered: {'YES' if cam2_recovered else 'NO'}")
    
    success = cam1_continued and cam2_recovered and cam2_stats.failed_reconnects == 0
    print(f"  Result: {'PASS' if success else 'FAIL'}")
    return success, cam1_stats, cam2_stats


def main():
    print("=" * 70)
    print("PHASE 9.3 CLOSEOUT — WORKSTREAM H: RECONNECT STABILITY")
    print("=" * 70)
    
    all_pass = True
    
    # Test 1: CAM1 independent reconnect
    cam1_success, cam1_stats = test_cam1_reconnect()
    all_pass = all_pass and cam1_success
    
    # Small delay between tests
    time.sleep(5)
    
    # Test 2: CAM2 independent reconnect
    cam2_success, cam2_stats = test_cam2_reconnect()
    all_pass = all_pass and cam2_success
    
    # Small delay between tests
    time.sleep(5)
    
    # Test 3: Dual-camera with one failure
    dual_success, d_cam1, d_cam2 = test_dual_camera_one_fails()
    all_pass = all_pass and dual_success
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS — RECONNECT STABILITY")
    print("=" * 70)
    print(f"CAM1 Independent Reconnect: {'PASS' if cam1_success else 'FAIL'}")
    print(f"CAM2 Independent Reconnect: {'PASS' if cam2_success else 'FAIL'}")
    print(f"Dual-Camera Isolation: {'PASS' if dual_success else 'FAIL'}")
    print("=" * 70)
    
    if all_pass:
        print("RECONNECT STABILITY: PASS")
    else:
        print("RECONNECT STABILITY: FAIL")
    
    return all_pass


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)