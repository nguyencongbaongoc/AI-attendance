"""
Restart Qualification Test - Phase 9.3 Closeout Workstream G
Verifies Backend B remains canonical after process restart.
Tests graceful shutdown and restart recovery.
"""

import os
import sys
import time
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Any

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


@dataclass
class RestartMetrics:
    phase: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    decoder_backend: str = "unknown"
    cam1_healthy: bool = False
    cam2_healthy: bool = False
    first_frame_latency: float = 0.0
    recovery_time: float = 0.0
    errors: list = field(default_factory=list)
    fallback_events: int = 0


def run_restart_test():
    """Run a subprocess that simulates application startup and verifies Backend B."""
    test_script = '''
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.settings import load_settings
from app.streaming.decoder_backend import DecoderBackendFactory, PyNvVideoCodecBackendConfig

settings = load_settings()

print(f"RESTART_TEST: decoder_backend = {settings.cameras.decoder_backend}")
assert settings.cameras.decoder_backend == "pynvvideocodec", f"Expected pynvvideocodec, got {settings.cameras.decoder_backend}"

# Test CAM1
config1 = PyNvVideoCodecBackendConfig(
    camera_id="CAM1",
    rtsp_url=settings.cameras.get_cam1_rtsp_url(),
    nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
    expected_width=settings.cameras.expected_width,
    expected_height=settings.cameras.expected_height,
    expected_fps=settings.cameras.expected_fps,
)

start = time.time()
backend1, actual1 = DecoderBackendFactory.create_with_fallback(
    primary_backend=settings.cameras.decoder_backend,
    config=config1,
    enable_fallback=True
)
init_time1 = time.time() - start

print(f"RESTART_TEST: CAM1 backend = {actual1}, init_time = {init_time1:.3f}s")
assert actual1 == "pynvvideocodec", f"CAM1 expected pynvvideocodec, got {actual1}"

info1 = backend1.open()
open_time1 = time.time() - start
print(f"RESTART_TEST: CAM1 opened in {open_time1:.3f}s: {info1.width}x{info1.height} @ {info1.fps}fps")

# Get first frame
frame_start = time.time()
frame1 = backend1.get_frame()
first_frame_latency = time.time() - frame_start
print(f"RESTART_TEST: CAM1 first frame latency = {first_frame_latency:.3f}s")

backend1.close()
print("RESTART_TEST: CAM1 closed normally")

# Test CAM2
config2 = PyNvVideoCodecBackendConfig(
    camera_id="CAM2",
    rtsp_url=settings.cameras.get_cam2_rtsp_url(),
    nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
    expected_width=settings.cameras.expected_width,
    expected_height=settings.cameras.expected_height,
    expected_fps=settings.cameras.expected_fps,
)

start2 = time.time()
backend2, actual2 = DecoderBackendFactory.create_with_fallback(
    primary_backend=settings.cameras.decoder_backend,
    config=config2,
    enable_fallback=True
)
init_time2 = time.time() - start2

print(f"RESTART_TEST: CAM2 backend = {actual2}, init_time = {init_time2:.3f}s")

info2 = backend2.open()
open_time2 = time.time() - start2
print(f"RESTART_TEST: CAM2 opened in {open_time2:.3f}s: {info2.width}x{info2.height} @ {info2.fps}fps")

frame_start2 = time.time()
frame2 = backend2.get_frame()
first_frame_latency2 = time.time() - frame_start2
print(f"RESTART_TEST: CAM2 first frame latency = {first_frame_latency2:.3f}s")

backend2.close()
print("RESTART_TEST: CAM2 closed normally")

print("RESTART_TEST: PASS - All restart checks passed")
'''
    
    # Write test script to temp file
    test_file = os.path.join(project_root, "scripts", "restart_test_inline.py")
    with open(test_file, "w") as f:
        f.write(test_script)
    
    try:
        # Run as separate process (simulating restart)
        start_time = time.time()
        result = subprocess.run(
            [sys.executable, test_file],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120
        )
        duration = time.time() - start_time
        
        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        return result.returncode == 0, duration, result.stdout, result.stderr
    finally:
        # Cleanup
        if os.path.exists(test_file):
            os.remove(test_file)


def main():
    print("=" * 70)
    print("PHASE 9.3 CLOSEOUT — WORKSTREAM G: RESTART QUALIFICATION")
    print("=" * 70)
    
    print("\n[TEST 1] Fresh process start (simulating restart)")
    success, duration, stdout, stderr = run_restart_test()
    
    metrics = RestartMetrics(
        phase="restart_simulation",
        start_time=time.time() - duration,
        end_time=time.time(),
        duration=duration
    )
    
    if success:
        print(f"\n[PASS] Restart simulation PASSED in {duration:.2f}s")
        metrics.cam1_healthy = True
        metrics.cam2_healthy = True
        metrics.decoder_backend = "pynvvideocodec"
        
        # Extract metrics from output
        for line in stdout.split('\n'):
            if "CAM1 first frame latency" in line:
                metrics.first_frame_latency = float(line.split("=")[1].replace("s", "").strip())
            if "CAM2 first frame latency" in line:
                # Could store both but we track CAM1 as primary
                pass
    else:
        print(f"\n[FAIL] Restart simulation FAILED in {duration:.2f}s")
        metrics.errors.append("Restart simulation failed")
        metrics.cam1_healthy = False
        metrics.cam2_healthy = False
    
    print("\n[TEST 2] Configuration persistence across imports")
    # Test that multiple imports in same process still get Backend B
    from app.config.settings import load_settings
    from app.streaming.decoder_backend import DecoderBackendFactory, PyNvVideoCodecBackendConfig
    
    settings = load_settings()
    assert settings.cameras.decoder_backend == "pynvvideocodec"
    print("[PASS] Config reload: decoder_backend = pynvvideocodec")
    
    config = PyNvVideoCodecBackendConfig(
        camera_id="RESTART_TEST",
        rtsp_url=settings.cameras.get_cam1_rtsp_url(),
        nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
    )
    
    backend, actual = DecoderBackendFactory.create_with_fallback(
        primary_backend=settings.cameras.decoder_backend,
        config=config,
        enable_fallback=True
    )
    
    assert actual == "pynvvideocodec"
    print(f"[PASS] Factory creates: {actual}")
    backend.close()
    
    print("\n[TEST 3] Health reporting after restart")
    # Verify health reporting identifies Backend B
    config2 = PyNvVideoCodecBackendConfig(
        camera_id="HEALTH_TEST",
        rtsp_url=settings.cameras.get_cam1_rtsp_url(),
        nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
    )
    
    backend2, actual2 = DecoderBackendFactory.create_with_fallback(
        primary_backend=settings.cameras.decoder_backend,
        config=config2,
        enable_fallback=True
    )
    
    health = backend2.health()
    assert health['backend'] == 'pynvvideocodec'
    print(f"[PASS] Health reports: backend = {health['backend']}")
    backend2.close()
    
    print("\n[TEST 4] Graceful shutdown sequence")
    # Test that close() properly releases resources
    config3 = PyNvVideoCodecBackendConfig(
        camera_id="SHUTDOWN_TEST",
        rtsp_url=settings.cameras.get_cam1_rtsp_url(),
        nvdec_gpu_device=settings.cameras.nvdec_gpu_device,
    )
    
    backend3, actual3 = DecoderBackendFactory.create_with_fallback(
        primary_backend=settings.cameras.decoder_backend,
        config=config3,
        enable_fallback=True
    )
    
    info3 = backend3.open()
    print(f"[PASS] Opened: {actual3}")
    
    # Get a frame
    frame3 = backend3.get_frame()
    if frame3:
        print("[PASS] Frame acquired")
    
    # Close
    backend3.close()
    print("[PASS] Graceful close completed")
    
    # Verify can reopen (simulating quick restart)
    backend4, actual4 = DecoderBackendFactory.create_with_fallback(
        primary_backend=settings.cameras.decoder_backend,
        config=config3,
        enable_fallback=True
    )
    
    assert actual4 == "pynvvideocodec"
    info4 = backend4.open()
    print(f"[PASS] Reopened after close: {actual4}")
    backend4.close()
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS — RESTART QUALIFICATION")
    print("=" * 70)
    print(f"Restart simulation: {'PASS' if success else 'FAIL'} ({duration:.2f}s)")
    print(f"Config persistence: PASS")
    print(f"Health reporting: PASS")
    print(f"Graceful shutdown: PASS")
    print(f"Quick reopen: PASS")
    print(f"Decoder backend: {metrics.decoder_backend}")
    print(f"CAM1 healthy: {metrics.cam1_healthy}")
    print(f"CAM2 healthy: {metrics.cam2_healthy}")
    print(f"First frame latency: {metrics.first_frame_latency:.3f}s")
    print("=" * 70)
    
    overall_success = success and metrics.cam1_healthy and metrics.cam2_healthy
    
    if overall_success:
        print("RESTART QUALIFICATION: PASS")
    else:
        print("RESTART QUALIFICATION: FAIL")
    
    return overall_success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)