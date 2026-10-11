"""
300s Sustained Dual-Camera Qualification Test.
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

def sustained_test(camera_id, rtsp_url, duration_seconds, stop_event, stats, stats_lock):
    try:
        config = PyNvVideoCodecBackendConfig(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            nvdec_gpu_device=0,
            max_queue_size=10,
            expected_codec='h264',
            expected_width=3840,
            expected_height=2160,
            expected_fps=30.0,
            timeout=10.0,
        )
        
        backend, actual_backend = DecoderBackendFactory.create_with_fallback(
            primary_backend='pynvvideocodec',
            config=config,
            enable_fallback=True,
        )
        
        logger.info(f'[{camera_id}] Backend created: {actual_backend}')
        info = backend.open()
        logger.info(f'[{camera_id}] Opened: {info.width}x{info.height}@{info.fps}fps')
        
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
            
            now = time.time()
            if now - last_log >= 10.0:
                with stats_lock:
                    cam_frames = stats[camera_id]["frames"]
                elapsed = now - start_time
                fps = cam_frames / elapsed if elapsed > 0 else 0
                logger.info(f'[{camera_id}] {cam_frames} frames in {elapsed:.1f}s ({fps:.1f} FPS), queue={backend._frame_queue.qsize()}')
                last_log = now
        
        elapsed = time.time() - start_time
        backend.close()
        
        with stats_lock:
            final_frames = stats[camera_id]["frames"]
        
        logger.info(f'[{camera_id}] Sustained test completed: {final_frames} frames in {elapsed:.1f}s')
        return {"camera_id": camera_id, "passed": True, "backend": actual_backend, "frames": final_frames}
        
    except Exception as e:
        logger.error(f'[{camera_id}] Sustained test FAILED: {e}', exc_info=True)
        return {"camera_id": camera_id, "passed": False, "error": str(e)}

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("SUSTAINED DUAL-CAMERA BACKEND B TEST (300s)")
    logger.info("=" * 60)
    
    duration_seconds = 300
    stop_event = threading.Event()
    stats = {"CAM1": {"frames": 0}, "CAM2": {"frames": 0}}
    stats_lock = threading.Lock()
    results = {}
    
    def run_camera(cam_id, url):
        results[cam_id] = sustained_test(cam_id, url, duration_seconds, stop_event, stats, stats_lock)
    
    threads = []
    for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                         ("CAM2", "rtsp://localhost:8554/live/cam2")]:
        t = threading.Thread(target=run_camera, args=(cam_id, url))
        threads.append(t)
        t.start()
        time.sleep(0.5)
    
    # Wait for duration
    time.sleep(duration_seconds)
    stop_event.set()
    
    # Wait for threads
    for t in threads:
        t.join(timeout=10)
    
    # Final summary
    logger.info("=" * 60)
    logger.info("SUSTAINED DUAL-CAMERA TEST SUMMARY (300s)")
    logger.info("=" * 60)
    with stats_lock:
        for cam_id in ["CAM1", "CAM2"]:
            frames = stats[cam_id]["frames"]
            fps = frames / duration_seconds if duration_seconds > 0 else 0
            logger.info(f'{cam_id}: {frames} frames ({fps:.1f} FPS)')
    
    all_passed = all(r.get("passed", False) for r in results.values())
    logger.info(f"OVERALL: {'PASSED' if all_passed else 'FAILED'}")