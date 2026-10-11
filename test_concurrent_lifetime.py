"""
Phase 9.4.2 — Decoder Lifetime Timeline Test.

Tests true concurrent decoder lifetime.
"""

import sys
import os
import time
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    PyNvVideoCodecBackendConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

def run_camera(cam_id, url, results, ready_event, stop_event):
    """Run a single camera and report lifecycle events."""
    try:
        config = PyNvVideoCodecBackendConfig(
            camera_id=cam_id,
            rtsp_url=url,
            nvdec_gpu_device=0,
            max_queue_size=10,
            expected_codec="h264",
            expected_width=3840,
            expected_height=2160,
            expected_fps=30.0,
            timeout=10.0,
        )
        
        logger.info(f"[{cam_id}] Creating backend...")
        backend, actual = DecoderBackendFactory.create_with_fallback(
            primary_backend="pynvvideocodec", config=config, enable_fallback=True
        )
        logger.info(f"[{cam_id}] Backend created: {actual}")
        
        init_event = threading.Event()
        
        # Wrap open to signal when reader starts
        original_open = backend.open
        def wrapped_open():
            info = original_open()
            logger.info(f"[{cam_id}] Opened: {info.width}x{info.height}")
            ready_event.set()  # Signal that this camera's reader is running
            return info
        backend.open = wrapped_open
        
        info = backend.open()
        
        # Wait for stop signal
        logger.info(f"[{cam_id}] Running, waiting for stop signal...")
        while not stop_event.is_set():
            wframe = backend.get_frame()
            if wframe and not wframe.stalled:
                pass
            time.sleep(0.01)
        
        logger.info(f"[{cam_id}] Stop signal received, closing...")
        backend.close()
        logger.info(f"[{cam_id}] Closed")
        results[cam_id] = {"success": True, "backend": actual}
        
    except Exception as e:
        logger.error(f"[{cam_id}] Error: {e}", exc_info=True)
        results[cam_id] = {"success": False, "error": str(e)}
        ready_event.set()  # Don't deadlock

def test_true_concurrent():
    """Test: CAM1 active → CAM2 initialize while CAM1 reader running."""
    logger.info("=" * 60)
    logger.info("TEST: True Concurrent Lifetime (CAM1 active, CAM2 init)")
    logger.info("=" * 60)
    
    results = {}
    cam1_ready = threading.Event()
    stop_event = threading.Event()
    
    # Start CAM1
    t1 = threading.Thread(target=run_camera, args=(
        "CAM1", "rtsp://localhost:8554/live/cam1", results, cam1_ready, stop_event
    ))
    t1.start()
    
    # Wait for CAM1 reader to start
    logger.info("Waiting for CAM1 reader to start...")
    cam1_ready.wait(timeout=15)
    logger.info("CAM1 reader started")
    
    # Give CAM1 a moment to establish steady state
    time.sleep(2)
    
    # Now start CAM2 while CAM1 is active
    logger.info("Starting CAM2 while CAM1 is active...")
    cam2_ready = threading.Event()
    t2 = threading.Thread(target=run_camera, args=(
        "CAM2", "rtsp://localhost:8554/live/cam2", results, cam2_ready, stop_event
    ))
    t2.start()
    
    # Wait for CAM2 to either succeed or fail
    cam2_ready.wait(timeout=15)
    logger.info("CAM2 init phase complete")
    
    # Let both run for a bit
    time.sleep(5)
    
    # Stop both
    logger.info("Stopping both cameras...")
    stop_event.set()
    
    t1.join(timeout=10)
    t2.join(timeout=10)
    
    logger.info(f"Results: {results}")
    return results

def test_concurrent_init_only():
    """Test: Both cameras initialize concurrently (before any open)."""
    logger.info("=" * 60)
    logger.info("TEST: Concurrent Initialization Only")
    logger.info("=" * 60)
    
    results = {}
    
    def init_only(cam_id, url):
        try:
            config = PyNvVideoCodecBackendConfig(
                camera_id=cam_id,
                rtsp_url=url,
                nvdec_gpu_device=0,
                max_queue_size=10,
                expected_codec="h264",
                expected_width=3840,
                expected_height=2160,
                expected_fps=30.0,
                timeout=10.0,
            )
            
            logger.info(f"[{cam_id}] Creating backend...")
            backend, actual = DecoderBackendFactory.create_with_fallback(
                primary_backend="pynvvideocodec", config=config, enable_fallback=True
            )
            logger.info(f"[{cam_id}] Backend created: {actual}")
            
            # Don't open - just test init
            results[cam_id] = {"success": True, "backend": actual, "phase": "init"}
            
        except Exception as e:
            logger.error(f"[{cam_id}] Error: {e}", exc_info=True)
            results[cam_id] = {"success": False, "error": str(e), "phase": "init"}
    
    t1 = threading.Thread(target=init_only, args=("CAM1", "rtsp://localhost:8554/live/cam1"))
    t2 = threading.Thread(target=init_only, args=("CAM2", "rtsp://localhost:8554/live/cam2"))
    
    t1.start()
    t2.start()
    
    t1.join(timeout=30)
    t2.join(timeout=30)
    
    logger.info(f"Concurrent init results: {results}")
    return results

def test_overlapping_lifecycle():
    """Test: CAM1 init → CAM1 open → CAM2 init → CAM2 open → both run."""
    logger.info("=" * 60)
    logger.info("TEST: Overlapping Lifecycle (staggered init/open)")
    logger.info("=" * 60)
    
    results = {}
    
    def camera_worker(cam_id, url, delay_before_init, delay_before_open):
        try:
            if delay_before_init:
                time.sleep(delay_before_init)
            
            config = PyNvVideoCodecBackendConfig(
                camera_id=cam_id,
                rtsp_url=url,
                nvdec_gpu_device=0,
                max_queue_size=10,
                expected_codec="h264",
                expected_width=3840,
                expected_height=2160,
                expected_fps=30.0,
                timeout=10.0,
            )
            
            logger.info(f"[{cam_id}] Creating backend...")
            backend, actual = DecoderBackendFactory.create_with_fallback(
                primary_backend="pynvvideocodec", config=config, enable_fallback=True
            )
            logger.info(f"[{cam_id}] Backend created: {actual}")
            
            if delay_before_open:
                time.sleep(delay_before_open)
            
            logger.info(f"[{cam_id}] Opening...")
            info = backend.open()
            logger.info(f"[{cam_id}] Opened: {info.width}x{info.height}")
            
            # Run for a bit
            for i in range(10):
                wframe = backend.get_frame()
                if wframe and not wframe.stalled:
                    pass
                time.sleep(0.05)
            
            backend.close()
            logger.info(f"[{cam_id}] Closed")
            results[cam_id] = {"success": True, "backend": actual}
            
        except Exception as e:
            logger.error(f"[{cam_id}] Error: {e}", exc_info=True)
            results[cam_id] = {"success": False, "error": str(e)}
    
    # CAM1: init immediately, open immediately
    # CAM2: init after 1s, open after 1s
    t1 = threading.Thread(target=camera_worker, args=("CAM1", "rtsp://localhost:8554/live/cam1", 0, 0))
    t2 = threading.Thread(target=camera_worker, args=("CAM2", "rtsp://localhost:8554/live/cam2", 1, 1))
    
    t1.start()
    t2.start()
    
    t1.join(timeout=30)
    t2.join(timeout=30)
    
    logger.info(f"Overlapping results: {results}")
    return results

def main():
    logger.info("PHASE 9.4.2 — DECODER LIFETIME TIMELINE")
    logger.info("=" * 60)
    
    # Test 1: Concurrent initialization only
    logger.info("\n>>> TEST 1: Concurrent Initialization Only")
    r1 = test_concurrent_init_only()
    
    time.sleep(2)
    
    # Test 2: True concurrent (CAM1 active, CAM2 init)
    logger.info("\n>>> TEST 2: True Concurrent (CAM1 active, CAM2 init)")
    r2 = test_true_concurrent()
    
    time.sleep(2)
    
    # Test 3: Overlapping lifecycle
    logger.info("\n>>> TEST 3: Overlapping Lifecycle")
    r3 = test_overlapping_lifecycle()
    
    # Summary
    logger.info("=" * 60)
    logger.info("DECODER LIFETIME TIMELINE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Concurrent Init Only: {r1}")
    logger.info(f"True Concurrent: {r2}")
    logger.info(f"Overlapping: {r3}")

if __name__ == "__main__":
    sys.exit(main())