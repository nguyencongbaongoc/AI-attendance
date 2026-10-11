"""
Phase 9.4.1 — Reconnect Qualification Test.

Tests reconnect behavior for CAM1 and CAM2 independently, then together.
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


def _run_reconnect_single(camera_id: str, rtsp_url: str):
    """Test reconnect for a single camera."""
    logger.info(f"[{camera_id}] Starting reconnect test...")
    
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
    
    # Initial connection
    backend, actual_backend = DecoderBackendFactory.create_with_fallback(
        primary_backend="pynvvideocodec",
        config=config,
        enable_fallback=True,
    )
    
    logger.info(f"[{camera_id}] Initial backend: {actual_backend}")
    info = backend.open()
    logger.info(f"[{camera_id}] Opened: {info.width}x{info.height}@{info.fps}fps")
    
    # Collect some frames
    for i in range(10):
        wframe = backend.get_frame()
        if wframe and not wframe.stalled:
            pass
        time.sleep(0.03)
    
    logger.info(f"[{camera_id}] Initial frames collected, simulating disconnect...")
    
    # Simulate disconnect by closing
    backend.close()
    logger.info(f"[{camera_id}] Backend closed")
    
    # Wait a moment
    time.sleep(2)
    
    # Reconnect - create new backend instance
    logger.info(f"[{camera_id}] Attempting reconnect...")
    start_reconnect = time.time()
    
    backend2, actual_backend2 = DecoderBackendFactory.create_with_fallback(
        primary_backend="pynvvideocodec",
        config=config,
        enable_fallback=True,
    )
    
    info2 = backend2.open()
    reconnect_time = time.time() - start_reconnect
    
    logger.info(f"[{camera_id}] Reconnected in {reconnect_time:.2f}s, backend: {actual_backend2}")
    
    # Collect frames after reconnect
    post_frames = 0
    for i in range(10):
        wframe = backend2.get_frame()
        if wframe and not wframe.stalled:
            post_frames += 1
        time.sleep(0.03)
    
    backend2.close()
    
    logger.info(f"[{camera_id}] Post-reconnect frames: {post_frames}")
    logger.info(f"[{camera_id}] Reconnect test PASSED")
    
    return {
        "camera_id": camera_id,
        "initial_backend": actual_backend,
        "reconnect_backend": actual_backend2,
        "reconnect_time": reconnect_time,
        "post_frames": post_frames,
        "passed": post_frames > 0,
    }


def test_reconnect_dual():
    """Test reconnect for both cameras sequentially."""
    logger.info("=" * 60)
    logger.info("DUAL-CAMERA RECONNECT TEST (Sequential)")
    logger.info("=" * 60)
    
    results = {}
    
    for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                         ("CAM2", "rtsp://localhost:8554/live/cam2")]:
        try:
            results[cam_id] = _run_reconnect_single(cam_id, url)
        except Exception as e:
            logger.error(f"[{cam_id}] Reconnect test FAILED: {e}", exc_info=True)
            results[cam_id] = {
                "camera_id": cam_id,
                "passed": False,
                "error": str(e),
            }
    
    # Summary
    logger.info("=" * 60)
    logger.info("RECONNECT TEST SUMMARY")
    logger.info("=" * 60)
    
    for cam_id, r in results.items():
        status = "PASS" if r.get("passed", False) else "FAIL"
        if r.get("passed"):
            logger.info(f"{cam_id}: {status} | Initial: {r['initial_backend']} | "
                        f"Reconnect: {r['reconnect_backend']} | "
                        f"Reconnect time: {r['reconnect_time']:.2f}s | "
                        f"Post-frames: {r['post_frames']}")
        else:
            logger.info(f"{cam_id}: {status} | Error: {r.get('error', 'Unknown')}")
    
    return all(r.get("passed", False) for r in results.values())


def test_forced_reconnect_during_stream():
    """Test reconnect while stream is active (simulate network interruption)."""
    logger.info("=" * 60)
    logger.info("FORCED RECONNECT DURING STREAM TEST")
    logger.info("=" * 60)
    
    config = PyNvVideoCodecBackendConfig(
        camera_id="CAM1",
        rtsp_url="rtsp://localhost:8554/live/cam1",
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
    
    logger.info(f"[CAM1] Initial backend: {actual_backend}")
    info = backend.open()
    logger.info(f"[CAM1] Opened: {info.width}x{info.height}@{info.fps}fps")
    
    # Collect frames for a bit
    for i in range(20):
        wframe = backend.get_frame()
        if wframe and not wframe.stalled:
            pass
        time.sleep(0.03)
    
    logger.info(f"[CAM1] Simulating network interruption (close without stop)...")
    # Force close - this simulates unclean disconnect
    backend._stop_event.set()
    if backend._reader_thread:
        backend._reader_thread.join(timeout=2)
    backend._opened = False
    backend._decoder = None
    
    time.sleep(1)
    
    # Reconnect using the reconnect method
    logger.info(f"[CAM1] Calling backend.reconnect()...")
    start = time.time()
    success = backend.reconnect()
    reconnect_time = time.time() - start
    
    if success:
        logger.info(f"[CAM1] Reconnect succeeded in {reconnect_time:.2f}s")
        # Verify frames resume
        post_frames = 0
        for i in range(10):
            wframe = backend.get_frame()
            if wframe and not wframe.stalled:
                post_frames += 1
            time.sleep(0.03)
        logger.info(f"[CAM1] Post-reconnect frames: {post_frames}")
        backend.close()
        return {"passed": post_frames > 0, "reconnect_time": reconnect_time, "post_frames": post_frames}
    else:
        logger.error(f"[CAM1] Reconnect failed")
        return {"passed": False, "reconnect_time": reconnect_time, "post_frames": 0}


def main():
    logger.info("PHASE 9.4.1 — RECONNECT QUALIFICATION")
    logger.info("=" * 60)
    
    # Test 1: Sequential reconnect
    sequential_passed = test_reconnect_dual()
    
    time.sleep(2)
    
    # Test 2: Forced reconnect during stream
    forced_result = test_forced_reconnect_during_stream()
    forced_passed = forced_result.get("passed", False)
    
    # Final verdict
    logger.info("=" * 60)
    logger.info("FINAL RECONNECT VERDICT")
    logger.info("=" * 60)
    logger.info(f"Sequential Reconnect:     {'PASS' if sequential_passed else 'FAIL'}")
    logger.info(f"Forced Reconnect (active): {'PASS' if forced_passed else 'FAIL'}")
    
    overall = sequential_passed and forced_passed
    logger.info(f"OVERALL:                 {'PASS' if overall else 'FAIL'}")
    
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())