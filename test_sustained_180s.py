"""
180s Sustained Single-Camera Qualification Test.
"""

import sys
import os
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    PyNvVideoCodecBackendConfig,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

def run_sustained(camera_id, rtsp_url, duration_seconds):
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
    frame_count = 0
    last_log = start_time
    
    while (time.time() - start_time) < duration_seconds:
        wframe = backend.get_frame()
        if wframe is None:
            time.sleep(0.01)
            continue
        if wframe.stalled:
            break
        frame_count += 1
        
        now = time.time()
        if now - last_log >= 10.0:
            elapsed = now - start_time
            fps = frame_count / elapsed if elapsed > 0 else 0
            logger.info(f'[{camera_id}] {frame_count} frames in {elapsed:.1f}s ({fps:.1f} FPS), queue={backend._frame_queue.qsize()}')
            last_log = now
    
    elapsed = time.time() - start_time
    backend.close()
    fps = frame_count / elapsed if elapsed > 0 else 0
    logger.info(f'[{camera_id}] Sustained test completed: {frame_count} frames in {elapsed:.1f}s ({fps:.1f} FPS)')
    return frame_count, elapsed, fps, actual_backend

if __name__ == "__main__":
    # Run CAM1 for 180 seconds
    print('=== CAM1 180s SUSTAINED TEST ===')
    frames1, elapsed1, fps1, backend1 = run_sustained('CAM1', 'rtsp://localhost:8554/live/cam1', 180)
    
    time.sleep(2)
    
    # Run CAM2 for 180 seconds
    print('=== CAM2 180s SUSTAINED TEST ===')
    frames2, elapsed2, fps2, backend2 = run_sustained('CAM2', 'rtsp://localhost:8554/live/cam2', 180)
    
    print(f'CAM1: {frames1} frames in {elapsed1:.1f}s ({fps1:.1f} FPS), backend={backend1}')
    print(f'CAM2: {frames2} frames in {elapsed2:.1f}s ({fps2:.1f} FPS), backend={backend2}')