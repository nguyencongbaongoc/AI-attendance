"""
GPU Memory / Backpressure Stability Test - Phase 9.3 Closeout Workstream J
Monitors GTX 1660 Ti during sustained operation to verify no memory leaks or unbounded queues.
"""

import os
import sys
import time
import threading
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Any, List

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from app.config.settings import load_settings
from app.streaming.decoder_backend import DecoderBackendFactory, PyNvVideoCodecBackendConfig


@dataclass
class GPUMetrics:
    camera_id: str
    frame_count: int = 0
    decode_errors: int = 0
    gpu_memory_samples: List[float] = field(default_factory=list)  # MB
    queue_depth_samples: List[int] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    running: bool = True


def get_gpu_memory_mb() -> float:
    """Get current GPU memory usage in MB using nvidia-smi."""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse first GPU (index 0)
            lines = result.stdout.strip().split('\n')
            if lines:
                return float(lines[0].strip())
    except Exception as e:
        pass
    return 0.0


def gpu_monitor_worker(stats: GPUMetrics, interval: float = 5.0):
    """Background thread to sample GPU memory."""
    while stats.running:
        mem_mb = get_gpu_memory_mb()
        if mem_mb > 0:
            stats.gpu_memory_samples.append(mem_mb)
        time.sleep(interval)


def camera_worker(stats: GPUMetrics, rtsp_url: str, duration_seconds: int):
    """Worker thread for camera soak test with metrics collection."""
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
    
    stats.start_time = time.time()
    
    try:
        # Create backend
        backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend=settings.cameras.decoder_backend,
            config=config,
            enable_fallback=True
        )
        
        print(f"[{stats.camera_id}] Backend: {actual_backend}")
        
        # Open stream
        info = backend.open()
        print(f"[{stats.camera_id}] Opened: {info.width}x{info.height} @ {info.fps}fps")
        
        end_time = stats.start_time + duration_seconds
        
        last_report = stats.start_time
        
        while time.time() < end_time and stats.running:
            # Get frame
            frame = backend.get_frame()
            current_time = time.time()
            
            if frame is not None:
                stats.frame_count += 1
                
                # Sample queue depth
                health = backend.health()
                stats.queue_depth_samples.append(health.get('queue_size', 0))
                
                # Report every 30 seconds
                if current_time - last_report >= 30.0:
                    elapsed = current_time - stats.start_time
                    fps = stats.frame_count / elapsed if elapsed > 0 else 0
                    avg_queue = sum(stats.queue_depth_samples[-10:]) / min(10, len(stats.queue_depth_samples)) if stats.queue_depth_samples else 0
                    print(f"[{stats.camera_id}] [{elapsed:.0f}s] Frames: {stats.frame_count}, FPS: {fps:.1f}, "
                          f"Avg queue (last 10): {avg_queue:.1f}, Backend: {health.get('backend')}")
                    last_report = current_time
            else:
                time.sleep(0.01)
                
                # Check if stream died
                if not backend.is_opened:
                    print(f"[{stats.camera_id}] Stream closed unexpectedly")
                    break
        
        stats.end_time = time.time()
        backend.close()
        print(f"[{stats.camera_id}] Completed: {stats.frame_count} frames")
        
    except Exception as e:
        stats.end_time = time.time()
        print(f"[{stats.camera_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        stats.decode_errors += 1


def main():
    print("=" * 70)
    print("PHASE 9.3 CLOSEOUT — WORKSTREAM J: GPU MEMORY / BACKPRESSURE STABILITY")
    print("=" * 70)
    
    # Load settings
    settings = load_settings()
    print(f"Decoder backend: {settings.cameras.decoder_backend}")
    print(f"GPU: GTX 1660 Ti (device {settings.cameras.nvdec_gpu_device})")
    
    # Duration: 300 seconds (5 minutes) for memory trend analysis
    test_duration = 300  # seconds
    
    cam1_stats = GPUMetrics(camera_id="CAM1")
    cam2_stats = GPUMetrics(camera_id="CAM2")
    
    # Start GPU monitor
    gpu_monitor_stats = GPUMetrics(camera_id="GPU_MONITOR")
    gpu_monitor_thread = threading.Thread(
        target=gpu_monitor_worker,
        args=(gpu_monitor_stats, 5.0),  # Sample every 5 seconds
        name="GPU-Monitor",
        daemon=True,
    )
    
    # Sequential initialization: CAM1 first, CAM2 after 10s
    cam1_thread = threading.Thread(
        target=camera_worker,
        args=(cam1_stats, settings.cameras.get_cam1_rtsp_url(), test_duration),
        name="CAM1-memory",
        daemon=True,
    )
    
    cam2_thread = threading.Thread(
        target=camera_worker,
        args=(cam2_stats, settings.cameras.get_cam2_rtsp_url(), test_duration),
        name="CAM2-memory",
        daemon=True,
    )
    
    print(f"\nStarting dual-camera memory test for {test_duration} seconds ({test_duration/60:.0f} minutes)...")
    print("CAM1 initializing first, CAM2 after 10 second delay...\n")
    
    start_time = time.time()
    gpu_monitor_thread.start()
    cam1_thread.start()
    
    time.sleep(10)  # Sequential init delay
    cam2_thread.start()
    
    # Wait for completion
    cam1_thread.join(timeout=test_duration + 30)
    cam2_thread.join(timeout=test_duration + 30)
    
    gpu_monitor_stats.running = False
    gpu_monitor_thread.join(timeout=5)
    
    # Analysis
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS — GPU MEMORY / BACKPRESSURE STABILITY")
    print("=" * 70)
    
    # CAM1 Analysis
    print(f"\nCAM1:")
    print(f"  Duration: {cam1_stats.end_time - cam1_stats.start_time:.1f}s")
    print(f"  Frames: {cam1_stats.frame_count}")
    print(f"  Errors: {cam1_stats.decode_errors}")
    if cam1_stats.queue_depth_samples:
        print(f"  Queue depth - Avg: {sum(cam1_stats.queue_depth_samples)/len(cam1_stats.queue_depth_samples):.2f}, "
              f"Max: {max(cam1_stats.queue_depth_samples)}, Min: {min(cam1_stats.queue_depth_samples)}")
    
    # CAM2 Analysis
    print(f"\nCAM2:")
    print(f"  Duration: {cam2_stats.end_time - cam2_stats.start_time:.1f}s")
    print(f"  Frames: {cam2_stats.frame_count}")
    print(f"  Errors: {cam2_stats.decode_errors}")
    if cam2_stats.queue_depth_samples:
        print(f"  Queue depth - Avg: {sum(cam2_stats.queue_depth_samples)/len(cam2_stats.queue_depth_samples):.2f}, "
              f"Max: {max(cam2_stats.queue_depth_samples)}, Min: {min(cam2_stats.queue_depth_samples)}")
    
    # GPU Memory Analysis
    print(f"\nGPU Memory (GTX 1660 Ti):")
    if gpu_monitor_stats.gpu_memory_samples:
        mem_start = gpu_monitor_stats.gpu_memory_samples[0]
        mem_end = gpu_monitor_stats.gpu_memory_samples[-1]
        mem_avg = sum(gpu_monitor_stats.gpu_memory_samples) / len(gpu_monitor_stats.gpu_memory_samples)
        mem_max = max(gpu_monitor_stats.gpu_memory_samples)
        mem_min = min(gpu_monitor_stats.gpu_memory_samples)
        mem_growth = mem_end - mem_start
        mem_growth_rate = mem_growth / (elapsed / 60) if elapsed > 0 else 0  # MB/min
        
        print(f"  Samples: {len(gpu_monitor_stats.gpu_memory_samples)}")
        print(f"  Start: {mem_start:.0f} MB")
        print(f"  End: {mem_end:.0f} MB")
        print(f"  Min: {mem_min:.0f} MB")
        print(f"  Max: {mem_max:.0f} MB")
        print(f"  Avg: {mem_avg:.0f} MB")
        print(f"  Growth: {mem_growth:.1f} MB over {elapsed/60:.1f} min")
        print(f"  Growth rate: {mem_growth_rate:.2f} MB/min")
        
        # Check for monotonic growth (leak indicator)
        # Compare first quarter vs last quarter
        q1_end = len(gpu_monitor_stats.gpu_memory_samples) // 4
        q4_start = 3 * len(gpu_monitor_stats.gpu_memory_samples) // 4
        q1_avg = sum(gpu_monitor_stats.gpu_memory_samples[:q1_end]) / q1_end if q1_end > 0 else mem_start
        q4_avg = sum(gpu_monitor_stats.gpu_memory_samples[q4_start:]) / (len(gpu_monitor_stats.gpu_memory_samples) - q4_start)
        q_growth = q4_avg - q1_avg
        
        print(f"  Q1 avg: {q1_avg:.1f} MB, Q4 avg: {q4_avg:.1f} MB")
        print(f"  Q4-Q1 growth: {q_growth:.1f} MB")
        
        # Acceptance criteria
        success = True
        
        # Queue depth should be bounded (max < 8 for queue size 10)
        max_queue_cam1 = max(cam1_stats.queue_depth_samples) if cam1_stats.queue_depth_samples else 0
        max_queue_cam2 = max(cam2_stats.queue_depth_samples) if cam2_stats.queue_depth_samples else 0
        
        if max_queue_cam1 > 8:
            print(f"[FAIL] CAM1 max queue depth {max_queue_cam1} > 8")
            success = False
        else:
            print(f"[PASS] CAM1 max queue depth {max_queue_cam1} <= 8")
        
        if max_queue_cam2 > 8:
            print(f"[FAIL] CAM2 max queue depth {max_queue_cam2} > 8")
            success = False
        else:
            print(f"[PASS] CAM2 max queue depth {max_queue_cam2} <= 8")
        
        # GPU memory growth should be minimal (< 10 MB over test or < 5 MB/min)
        if abs(mem_growth_rate) > 5.0:
            print(f"[FAIL] GPU memory growth rate {mem_growth_rate:.2f} MB/min > 5 MB/min")
            success = False
        else:
            print(f"[PASS] GPU memory growth rate {mem_growth_rate:.2f} MB/min <= 5 MB/min")
        
        # Q4-Q1 growth should be minimal
        if q_growth > 20:
            print(f"[FAIL] Q4-Q1 memory growth {q_growth:.1f} MB > 20 MB")
            success = False
        else:
            print(f"[PASS] Q4-Q1 memory growth {q_growth:.1f} MB <= 20 MB")
        
        # No decode errors
        if cam1_stats.decode_errors > 0:
            print(f"[FAIL] CAM1 decode errors: {cam1_stats.decode_errors}")
            success = False
        else:
            print(f"[PASS] CAM1 decode errors: 0")
        
        if cam2_stats.decode_errors > 0:
            print(f"[FAIL] CAM2 decode errors: {cam2_stats.decode_errors}")
            success = False
        else:
            print(f"[PASS] CAM2 decode errors: 0")
        
        print("\n" + "=" * 70)
        if success:
            print("GPU MEMORY / BACKPRESSURE STABILITY: PASS")
        else:
            print("GPU MEMORY / BACKPRESSURE STABILITY: FAIL")
        print("=" * 70)
        
        return success
    else:
        print("No GPU memory samples collected")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)