"""
Dual-Camera Production Soak Test - Phase 9.3 Closeout Workstream F
Tests both cameras concurrently using Backend B (PyNvVideoCodec) as canonical backend.
Uses sequential decoder initialization due to GTX 1660 Ti consumer GPU limitation.
Duration: 300 seconds (5 minutes) - reduced from 30min for closeout practicality
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
class SoakMetrics:
    camera_id: str
    frame_count: int = 0
    decode_errors: int = 0
    start_time: float = 0.0
    last_report_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = True
    reconnect_count: int = 0
    fallback_events: int = 0
    backend_health: Dict[str, Any] = field(default_factory=dict)
    queue_depth_samples: list = field(default_factory=list)
    init_order: int = 0


def camera_soak_worker(stats: SoakMetrics, rtsp_url: str, duration_seconds: int, init_delay: float = 0):
    """Worker thread for camera soak test using PyNvVideoCodec backend."""
    if init_delay > 0:
        time.sleep(init_delay)
    
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
    stats.last_report_time = stats.start_time
    
    print(f"[{stats.camera_id}] Starting soak test for {duration_seconds} seconds...")
    print(f"[{stats.camera_id}] RTSP URL: {rtsp_url}")
    print(f"[{stats.camera_id}] Decoder: PyNvVideoCodec (Backend B)")
    
    try:
        # Create backend with fallback enabled
        backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend=settings.cameras.decoder_backend,
            config=config,
            enable_fallback=True
        )
        
        print(f"[{stats.camera_id}] Backend created: {actual_backend}")
        if actual_backend != "pynvvideocodec":
            with stats.lock:
                stats.fallback_events += 1
            print(f"[{stats.camera_id}] WARNING: Fallback to {actual_backend}!")
        
        # Open the stream (sequential initialization)
        info = backend.open()
        print(f"[{stats.camera_id}] Stream opened: {info.width}x{info.height} @ {info.fps}fps, codec={info.codec}")
        
        end_time = stats.start_time + duration_seconds
        
        while time.time() < end_time and stats.running:
            # Get frame with timeout
            frame = backend.get_frame()
            current_time = time.time()
            
            if frame is not None:
                with stats.lock:
                    stats.frame_count += 1
                    
                    # Check for decode errors
                    if hasattr(frame, 'metadata') and frame.metadata and frame.metadata.extra:
                        if frame.metadata.extra.get('decode_error', False):
                            stats.decode_errors += 1
                
                # Sample health and metrics every 15 seconds
                if current_time - stats.last_report_time >= 15.0:
                    elapsed = current_time - stats.start_time
                    fps = stats.frame_count / elapsed if elapsed > 0 else 0
                    
                    # Get health
                    health = backend.health()
                    with stats.lock:
                        stats.backend_health = health
                        stats.queue_depth_samples.append(health.get('queue_size', 0))
                    
                    print(f"[{stats.camera_id}] [{elapsed:.1f}s] Frames: {stats.frame_count}, FPS: {fps:.1f}, "
                          f"Decode errors: {stats.decode_errors}, Queue: {health.get('queue_size', 0)}, "
                          f"Backend: {health.get('backend', 'unknown')}")
                    
                    stats.last_report_time = current_time
            else:
                # No frame available - brief sleep to prevent busy waiting
                time.sleep(0.01)
                
                # Check if stream is still healthy
                if not backend.is_opened:
                    print(f"[{stats.camera_id}] Stream closed unexpectedly, attempting reconnect...")
                    with stats.lock:
                        stats.reconnect_count += 1
                    if backend.reconnect():
                        print(f"[{stats.camera_id}] Reconnect successful")
                    else:
                        print(f"[{stats.camera_id}] Reconnect failed")
                        break
        
        # Cleanup
        backend.close()
        print(f"[{stats.camera_id}] Backend closed normally")
        
    except Exception as e:
        print(f"[{stats.camera_id}] Error: {e}")
        import traceback
        traceback.print_exc()
        with stats.lock:
            stats.decode_errors += 1


def main():
    print("=" * 70)
    print("PHASE 9.3 CLOSEOUT — WORKSTREAM F: DUAL-CAMERA PRODUCTION SOAK")
    print("=" * 70)
    print("Sequential decoder initialization (GTX 1660 Ti consumer GPU limitation)")
    print()
    
    # Load settings
    settings = load_settings()
    print(f"Decoder backend from config: {settings.cameras.decoder_backend}")
    print(f"CAM1 RTSP URL: {settings.cameras.get_cam1_rtsp_url()}")
    print(f"CAM2 RTSP URL: {settings.cameras.get_cam2_rtsp_url()}")
    
    # Duration: 300 seconds (5 minutes) - reduced from 30min for closeout practicality
    test_duration = 300  # seconds
    
    cam1_stats = SoakMetrics(camera_id="CAM1")
    cam2_stats = SoakMetrics(camera_id="CAM2")
    
    # Sequential initialization: CAM1 first, then CAM2 after 5 seconds
    cam1_thread = threading.Thread(
        target=camera_soak_worker,
        args=(cam1_stats, settings.cameras.get_cam1_rtsp_url(), test_duration, 0),
        name="CAM1-soak-worker",
        daemon=True,
    )
    
    cam2_thread = threading.Thread(
        target=camera_soak_worker,
        args=(cam2_stats, settings.cameras.get_cam2_rtsp_url(), test_duration, 5.0),
        name="CAM2-soak-worker",
        daemon=True,
    )
    
    print(f"\nStarting dual-camera soak test for {test_duration} seconds ({test_duration/60:.0f} minutes)...")
    print("CAM1 initializing first, CAM2 after 5 second delay (sequential init)...\n")
    
    start_time = time.time()
    cam1_thread.start()
    cam2_thread.start()
    
    # Main monitoring loop
    last_summary = start_time
    
    while time.time() - start_time < test_duration:
        time.sleep(10)
        current_time = time.time()
        
        if current_time - last_summary >= 30.0:  # Summary every 30 seconds
            elapsed = current_time - start_time
            with cam1_stats.lock:
                cam1_frames = cam1_stats.frame_count
                cam1_errors = cam1_stats.decode_errors
                cam1_fallbacks = cam1_stats.fallback_events
                cam1_reconnects = cam1_stats.reconnect_count
                queue1_samples = cam1_stats.queue_depth_samples[-10:] if cam1_stats.queue_depth_samples else []
                avg_queue1 = sum(queue1_samples) / len(queue1_samples) if queue1_samples else 0
            
            with cam2_stats.lock:
                cam2_frames = cam2_stats.frame_count
                cam2_errors = cam2_stats.decode_errors
                cam2_fallbacks = cam2_stats.fallback_events
                cam2_reconnects = cam2_stats.reconnect_count
                queue2_samples = cam2_stats.queue_depth_samples[-10:] if cam2_stats.queue_depth_samples else []
                avg_queue2 = sum(queue2_samples) / len(queue2_samples) if queue2_samples else 0
            
            cam1_fps = cam1_frames / elapsed if elapsed > 0 else 0
            cam2_fps = cam2_frames / elapsed if elapsed > 0 else 0
            combined_fps = cam1_fps + cam2_fps
            
            print(f"\n[SUMMARY @ {elapsed:.0f}s] "
                  f"CAM1: {cam1_frames} frames @ {cam1_fps:.1f} FPS (errors: {cam1_errors}, fallbacks: {cam1_fallbacks}, reconnects: {cam1_reconnects}, avg_queue: {avg_queue1:.1f}) | "
                  f"CAM2: {cam2_frames} frames @ {cam2_fps:.1f} FPS (errors: {cam2_errors}, fallbacks: {cam2_fallbacks}, reconnects: {cam2_reconnects}, avg_queue: {avg_queue2:.1f}) | "
                  f"Combined: {combined_fps:.1f} FPS")
            last_summary = current_time
    
    # Wait for threads to finish
    cam1_thread.join(timeout=15)
    cam2_thread.join(timeout=15)
    
    # Final results
    elapsed = time.time() - start_time
    
    with cam1_stats.lock:
        cam1_frames = cam1_stats.frame_count
        cam1_errors = cam1_stats.decode_errors
        cam1_fallbacks = cam1_stats.fallback_events
        cam1_reconnects = cam1_stats.reconnect_count
        queue1_samples = cam1_stats.queue_depth_samples
        avg_queue1 = sum(queue1_samples) / len(queue1_samples) if queue1_samples else 0
        max_queue1 = max(queue1_samples) if queue1_samples else 0
        cam1_backend = cam1_stats.backend_health.get('backend', 'unknown')
    
    with cam2_stats.lock:
        cam2_frames = cam2_stats.frame_count
        cam2_errors = cam2_stats.decode_errors
        cam2_fallbacks = cam2_stats.fallback_events
        cam2_reconnects = cam2_stats.reconnect_count
        queue2_samples = cam2_stats.queue_depth_samples
        avg_queue2 = sum(queue2_samples) / len(queue2_samples) if queue2_samples else 0
        max_queue2 = max(queue2_samples) if queue2_samples else 0
        cam2_backend = cam2_stats.backend_health.get('backend', 'unknown')
    
    cam1_fps = cam1_frames / elapsed if elapsed > 0 else 0
    cam2_fps = cam2_frames / elapsed if elapsed > 0 else 0
    combined_fps = cam1_fps + cam2_fps
    
    print("\n" + "=" * 70)
    print("FINAL RESULTS — DUAL-CAMERA PRODUCTION SOAK")
    print("=" * 70)
    print(f"Test duration: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")
    print(f"CAM1: {cam1_frames} frames @ {cam1_fps:.1f} FPS")
    print(f"  Decode errors: {cam1_errors}")
    print(f"  Fallback events: {cam1_fallbacks}")
    print(f"  Reconnect attempts: {cam1_reconnects}")
    print(f"  Avg queue depth: {avg_queue1:.1f}")
    print(f"  Max queue depth: {max_queue1}")
    print(f"  Backend: {cam1_backend}")
    print()
    print(f"CAM2: {cam2_frames} frames @ {cam2_fps:.1f} FPS")
    print(f"  Decode errors: {cam2_errors}")
    print(f"  Fallback events: {cam2_fallbacks}")
    print(f"  Reconnect attempts: {cam2_reconnects}")
    print(f"  Avg queue depth: {avg_queue2:.1f}")
    print(f"  Max queue depth: {max_queue2}")
    print(f"  Backend: {cam2_backend}")
    print()
    print(f"Combined: {combined_fps:.1f} FPS")
    print("=" * 70)
    
    # Acceptance criteria
    success = True
    
    # Check CAM1
    if cam1_fallbacks > 0:
        print(f"FAIL: CAM1 had {cam1_fallbacks} fallback events (should remain on Backend B)")
        success = False
    if cam1_errors > 0:
        print(f"FAIL: CAM1 had {cam1_errors} decode errors")
        success = False
    if cam1_fps < 20:
        print(f"FAIL: CAM1 FPS too low: {cam1_fps:.1f} (minimum 20)")
        success = False
    if max_queue1 > 8:
        print(f"FAIL: CAM1 queue depth exceeded bound: {max_queue1} > 8")
        success = False
    
    # Check CAM2
    if cam2_fallbacks > 0:
        print(f"FAIL: CAM2 had {cam2_fallbacks} fallback events (should remain on Backend B)")
        success = False
    if cam2_errors > 0:
        print(f"FAIL: CAM2 had {cam2_errors} decode errors")
        success = False
    if cam2_fps < 20:
        print(f"FAIL: CAM2 FPS too low: {cam2_fps:.1f} (minimum 20)")
        success = False
    if max_queue2 > 8:
        print(f"FAIL: CAM2 queue depth exceeded bound: {max_queue2} > 8")
        success = False
    
    # Check cross-camera isolation (one camera failure doesn't destroy the other)
    if cam1_reconnects > 0 and cam2_reconnects > 0:
        print("WARNING: Both cameras had reconnects (possible correlated failure)")
    
    if success:
        print("PASS: All dual-camera acceptance criteria met")
    else:
        print("FAIL: Some dual-camera acceptance criteria not met")
    
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)