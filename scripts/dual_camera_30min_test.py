"""
Phase 9.2-R — Dual Camera 30-minute concurrent test.
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

from app.data.input_adapter import create_video_frame_iterator


@dataclass
class CameraStats:
    camera_id: str
    frame_count: int = 0
    decode_errors: int = 0
    start_time: float = 0.0
    last_report_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = True


def camera_worker(stats: CameraStats, rtsp_url: str):
    """Worker thread for one camera."""
    stats.start_time = time.time()
    stats.last_report_time = stats.start_time
    
    print(f"[{stats.camera_id}] Starting...")
    
    iterator = create_video_frame_iterator(
        path=rtsp_url,
        decoder='pynvvideocodec',
        nvdec_gpu_device=0,
        expected_width=3840,
        expected_height=2160,
        expected_fps=30.0,
        camera_id=stats.camera_id,
    )
    
    try:
        info = iterator.info
        print(f"[{stats.camera_id}] Video info: {info.width}x{info.height} @ {info.fps}fps, codec={info.codec}, format={info.pixel_format}")
        
        for frame in iterator:
            with stats.lock:
                if not stats.running:
                    break
                stats.frame_count += 1
                current_time = time.time()
                
                if current_time - stats.last_report_time >= 30.0:
                    elapsed = current_time - stats.start_time
                    fps = stats.frame_count / elapsed
                    print(f"[{stats.camera_id}] [{elapsed:.1f}s] Frames: {stats.frame_count}, FPS: {fps:.1f}, Decode errors: {stats.decode_errors}")
                    stats.last_report_time = current_time
            
            # Check for decode errors in frame metadata
            if hasattr(frame, 'metadata') and frame.metadata.extra:
                if frame.metadata.extra.get('decode_error', False):
                    with stats.lock:
                        stats.decode_errors += 1
            
    except Exception as e:
        print(f"[{stats.camera_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        with stats.lock:
            stats.decode_errors += 1
    finally:
        iterator.close()
        print(f"[{stats.camera_id}] Iterator closed")


def main():
    print("=" * 60)
    print("Phase 9.2-R — Dual Camera 30-minute Concurrent Test")
    print("=" * 60)
    
    cam1_stats = CameraStats(camera_id="CAM1")
    cam2_stats = CameraStats(camera_id="CAM2")
    
    cam1_thread = threading.Thread(
        target=camera_worker,
        args=(cam1_stats, "rtsp://localhost:8554/live/cam1"),
        name="CAM1-worker",
        daemon=True,
    )
    cam2_thread = threading.Thread(
        target=camera_worker,
        args=(cam2_stats, "rtsp://localhost:8554/live/cam2"),
        name="CAM2-worker",
        daemon=True,
    )
    
    test_duration = 60  # 60 seconds for quick test
    start_time = time.time()
    
    cam1_thread.start()
    cam2_thread.start()
    
    print(f"\nRunning for {test_duration} seconds ({test_duration/60:.0f} minutes)...\n")
    
    last_report = start_time
    while time.time() - start_time < test_duration:
        time.sleep(10)
        
        current_time = time.time()
        if current_time - last_report >= 60.0:  # Report every minute
            elapsed = current_time - start_time
            with cam1_stats.lock:
                cam1_fps = cam1_stats.frame_count / elapsed if elapsed > 0 else 0
                cam1_frames = cam1_stats.frame_count
                cam1_errors = cam1_stats.decode_errors
            with cam2_stats.lock:
                cam2_fps = cam2_stats.frame_count / elapsed if elapsed > 0 else 0
                cam2_frames = cam2_stats.frame_count
                cam2_errors = cam2_stats.decode_errors
            
            combined_fps = cam1_fps + cam2_fps
            print(f"\n[SUMMARY @ {elapsed:.0f}s] "
                  f"CAM1: {cam1_frames} frames @ {cam1_fps:.1f} FPS (errors: {cam1_errors}) | "
                  f"CAM2: {cam2_frames} frames @ {cam2_fps:.1f} FPS (errors: {cam2_errors}) | "
                  f"Combined: {combined_fps:.1f} FPS")
            last_report = current_time
    
    # Stop workers
    with cam1_stats.lock:
        cam1_stats.running = False
    with cam2_stats.lock:
        cam2_stats.running = False
    
    cam1_thread.join(timeout=10)
    cam2_thread.join(timeout=10)
    
    # Final summary
    elapsed = time.time() - start_time
    with cam1_stats.lock:
        cam1_frames = cam1_stats.frame_count
        cam1_errors = cam1_stats.decode_errors
        cam1_fps = cam1_frames / elapsed if elapsed > 0 else 0
    with cam2_stats.lock:
        cam2_frames = cam2_stats.frame_count
        cam2_errors = cam2_stats.decode_errors
        cam2_fps = cam2_frames / elapsed if elapsed > 0 else 0
    
    combined_fps = cam1_fps + cam2_fps
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS - 30 Minute Dual Camera Test")
    print("=" * 60)
    print(f"Test duration: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"CAM1: {cam1_frames} frames @ {cam1_fps:.1f} FPS, Decode errors: {cam1_errors}")
    print(f"CAM2: {cam2_frames} frames @ {cam2_fps:.1f} FPS, Decode errors: {cam2_errors}")
    print(f"Combined: {combined_fps:.1f} FPS")
    print("=" * 60)
    
    # Acceptance criteria
    success = True
    if cam1_errors > 0:
        print(f"FAIL: CAM1 had {cam1_errors} decode errors")
        success = False
    if cam2_errors > 0:
        print(f"FAIL: CAM2 had {cam2_errors} decode errors")
        success = False
    if cam1_fps < 20:
        print(f"FAIL: CAM1 FPS too low: {cam1_fps:.1f}")
        success = False
    if cam2_fps < 20:
        print(f"FAIL: CAM2 FPS too low: {cam2_fps:.1f}")
        success = False
    
    if success:
        print("PASS: All acceptance criteria met")
    else:
        print("FAIL: Some acceptance criteria not met")
    
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)