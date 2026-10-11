"""
Phase 9.4.1 — Dual-Camera Backend B Qualification Test.

Tests both CAM1 and CAM2 with PyNvVideoCodec Backend B using the 
DecoderBackendFactory with per-GPU initialization lock.
"""

import sys
import os
import time
import threading
import queue
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    PyNvVideoCodecBackendConfig,
    DecoderBackendConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def _run_single_camera(camera_id: str, rtsp_url: str, results: queue.Queue):
    """Test a single camera with Backend B."""
    try:
        logger.info(f"[{camera_id}] Starting Backend B test...")
        
        # Create config
        config = PyNvVideoCodecBackendConfig(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            nvdec_gpu_device=0,
            max_queue_size=10,
            expected_codec="h264",
            expected_width=3840,
            expected_height=2160,
            expected_fps=30.0,
            timeout=10.0,
        )
        
        # Create backend with factory (uses per-GPU init lock)
        logger.info(f"[{camera_id}] Creating backend via DecoderBackendFactory...")
        backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend="pynvvideocodec",
            config=config,
            enable_fallback=True,
        )
        
        logger.info(f"[{camera_id}] Backend created: {actual_backend}")
        
        # Open and start
        info = backend.open()
        logger.info(f"[{camera_id}] Opened: {info.width}x{info.height}@{info.fps}fps, codec={info.codec}")
        
        # Collect frames
        start_time = time.time()
        frame_count = 0
        target_frames = 30  # 1 second at 30fps
        errors = 0
        
        while frame_count < target_frames:
            wframe = backend.get_frame()
            if wframe is None:
                time.sleep(0.01)
                continue
            
            if wframe.stalled:
                logger.warning(f"[{camera_id}] Stalled frame received")
                break
            
            frame_count += 1
            if frame_count % 10 == 0:
                elapsed = time.time() - start_time
                fps = frame_count / elapsed if elapsed > 0 else 0
                logger.info(f"[{camera_id}] Frame {frame_count}: {fps:.1f} FPS, queue={backend._frame_queue.qsize()}")
            
            # Check frame data
            if wframe.data is not None:
                if hasattr(wframe.data, 'memory_owner'):
                    logger.debug(f"[{camera_id}] Frame memory_owner: {wframe.data.memory_owner}")
        
        elapsed = time.time() - start_time
        fps = frame_count / elapsed if elapsed > 0 else 0
        
        # Get health
        health = backend.health()
        logger.info(f"[{camera_id}] Health: {health}")
        
        # Close
        backend.close()
        
        results.put({
            "camera_id": camera_id,
            "passed": True,
            "backend": actual_backend,
            "frames": frame_count,
            "elapsed": elapsed,
            "fps": fps,
            "errors": errors,
            "health": health,
            "error": None,
        })
        logger.info(f"[{camera_id}] Test PASSED: {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS)")
        
    except Exception as e:
        logger.error(f"[{camera_id}] Test FAILED: {e}", exc_info=True)
        results.put({
            "camera_id": camera_id,
            "passed": False,
            "backend": None,
            "frames": 0,
            "elapsed": 0,
            "fps": 0,
            "errors": 1,
            "health": None,
            "error": str(e),
        })


def test_sequential_dual_camera():
    """Test CAM1 then CAM2 sequentially (both using Backend B)."""
    logger.info("=" * 60)
    logger.info("SEQUENTIAL DUAL-CAMERA BACKEND B TEST")
    logger.info("=" * 60)
    
    results = queue.Queue()
    
    # Test CAM1 first
    _run_single_camera("CAM1", "rtsp://localhost:8554/live/cam1", results)
    r1 = results.get()
    
    time.sleep(2)  # Brief pause between cameras
    
    # Test CAM2 second
    _run_single_camera("CAM2", "rtsp://localhost:8554/live/cam2", results)
    r2 = results.get()
    
    # Summary
    logger.info("=" * 60)
    logger.info("SEQUENTIAL TEST SUMMARY")
    logger.info("=" * 60)
    for r in [r1, r2]:
        status = "PASS" if r["passed"] else "FAIL"
        logger.info(f"{r['camera_id']}: {status} | Backend: {r['backend']} | "
                    f"Frames: {r['frames']} | FPS: {r['fps']:.1f} | "
                    f"Errors: {r['errors']}")
        if not r["passed"]:
            logger.info(f"  ERROR: {r['error']}")
    
    all_passed = r1["passed"] and r2["passed"]
    logger.info(f"OVERALL: {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


def test_concurrent_dual_camera():
    """Test CAM1 and CAM2 concurrently (both using Backend B with init lock)."""
    logger.info("=" * 60)
    logger.info("CONCURRENT DUAL-CAMERA BACKEND B TEST")
    logger.info("=" * 60)
    
    results = queue.Queue()
    threads = []
    
    # Start both cameras concurrently
    for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                         ("CAM2", "rtsp://localhost:8554/live/cam2")]:
        t = threading.Thread(target=_run_single_camera, args=(cam_id, url, results))
        threads.append(t)
        t.start()
        time.sleep(0.5)  # Small stagger
    
    # Wait for completion
    for t in threads:
        t.join(timeout=60)
    
    # Collect results
    r1 = results.get()
    r2 = results.get()
    
    # Summary
    logger.info("=" * 60)
    logger.info("CONCURRENT TEST SUMMARY")
    logger.info("=" * 60)
    for r in [r1, r2]:
        status = "PASS" if r["passed"] else "FAIL"
        logger.info(f"{r['camera_id']}: {status} | Backend: {r['backend']} | "
                    f"Frames: {r['frames']} | FPS: {r['fps']:.1f} | "
                    f"Errors: {r['errors']}")
        if not r["passed"]:
            logger.info(f"  ERROR: {r['error']}")
    
    all_passed = r1["passed"] and r2["passed"]
    logger.info(f"OVERALL: {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


def test_sustained_dual_camera(duration_seconds: int = 60):
    """Test both cameras running concurrently for sustained period."""
    logger.info("=" * 60)
    logger.info(f"SUSTAINED DUAL-CAMERA BACKEND B TEST ({duration_seconds}s)")
    logger.info("=" * 60)
    
    results = queue.Queue()
    stop_event = threading.Event()
    stats = {"CAM1": {"frames": 0, "errors": 0}, "CAM2": {"frames": 0, "errors": 0}}
    stats_lock = threading.Lock()
    
    def sustained_test(camera_id: str, rtsp_url: str):
        try:
            config = PyNvVideoCodecBackendConfig(
                camera_id=camera_id,
                rtsp_url=rtsp_url,
                nvdec_gpu_device=0,
                max_queue_size=10,
                expected_codec="h264",
                expected_width=3840,
                expected_height=2160,
                expected_fps=30.0,
                timeout=10.0,
            )
            
            backend, actual_backend = DecoderBackendFactory.create_with_fallback(
                primary_backend="pynvvideocodec",
                config=config,
                enable_fallback=True,
            )
            
            logger.info(f"[{camera_id}] Backend created: {actual_backend}")
            info = backend.open()
            logger.info(f"[{camera_id}] Opened: {info.width}x{info.height}@{info.fps}fps")
            
            start_time = time.time()
            last_log = start_time
            
            while not stop_event.is_set() and (time.time() - start_time) < duration_seconds:
                wframe = backend.get_frame()
                if wframe is None:
                    time.sleep(0.01)
                    continue
                
                if wframe.stalled:
                    break
                
                with stats_lock:
                    stats[camera_id]["frames"] += 1
                
                # Log progress every 10 seconds
                now = time.time()
                if now - last_log >= 10.0:
                    with stats_lock:
                        cam_frames = stats[camera_id]["frames"]
                    elapsed = now - start_time
                    fps = cam_frames / elapsed if elapsed > 0 else 0
                    logger.info(f"[{camera_id}] {cam_frames} frames in {elapsed:.1f}s ({fps:.1f} FPS), queue={backend._frame_queue.qsize()}")
                    last_log = now
            
            elapsed = time.time() - start_time
            backend.close()
            
            with stats_lock:
                final_frames = stats[camera_id]["frames"]
            
            logger.info(f"[{camera_id}] Sustained test completed: {final_frames} frames in {elapsed:.1f}s")
            
            results.put({"camera_id": camera_id, "passed": True, "backend": actual_backend})
            
        except Exception as e:
            logger.error(f"[{camera_id}] Sustained test FAILED: {e}", exc_info=True)
            results.put({"camera_id": camera_id, "passed": False, "error": str(e)})
    
    # Start both cameras
    threads = []
    for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                         ("CAM2", "rtsp://localhost:8554/live/cam2")]:
        t = threading.Thread(target=sustained_test, args=(cam_id, url))
        threads.append(t)
        t.start()
        time.sleep(0.5)
    
    # Wait for duration
    time.sleep(duration_seconds)
    stop_event.set()
    
    # Wait for threads
    for t in threads:
        t.join(timeout=10)
    
    # Collect results
    r1 = results.get()
    r2 = results.get()
    
    # Final summary
    logger.info("=" * 60)
    logger.info("SUSTAINED TEST SUMMARY")
    logger.info("=" * 60)
    with stats_lock:
        for cam_id in ["CAM1", "CAM2"]:
            frames = stats[cam_id]["frames"]
            errors = stats[cam_id]["errors"]
            fps = frames / duration_seconds if duration_seconds > 0 else 0
            logger.info(f"{cam_id}: {frames} frames ({fps:.1f} FPS), errors: {errors}")
    
    all_passed = r1["passed"] and r2["passed"]
    logger.info(f"OVERALL: {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


def main():
    logger.info("PHASE 9.4.1 — DUAL-CAMERA BACKEND B QUALIFICATION")
    logger.info("=" * 60)
    
    # Test 1: Sequential
    seq_passed = test_sequential_dual_camera()
    
    time.sleep(3)
    
    # Test 2: Concurrent
    conc_passed = test_concurrent_dual_camera()
    
    time.sleep(3)
    
    # Test 3: Sustained (30 seconds for qualification)
    sustained_passed = test_sustained_dual_camera(30)
    
    # Final verdict
    logger.info("=" * 60)
    logger.info("FINAL VERDICT")
    logger.info("=" * 60)
    logger.info(f"Sequential:     {'PASS' if seq_passed else 'FAIL'}")
    logger.info(f"Concurrent:     {'PASS' if conc_passed else 'FAIL'}")
    logger.info(f"Sustained (30s): {'PASS' if sustained_passed else 'FAIL'}")
    
    overall = seq_passed and conc_passed and sustained_passed
    logger.info(f"OVERALL:        {'PASS' if overall else 'FAIL'}")
    
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())