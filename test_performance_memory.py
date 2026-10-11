"""
Performance, Memory, and Backpressure Measurement Test.
"""

import sys
import os
import time
import threading
import logging
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    PyNvVideoCodecBackendConfig,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

def run_camera(cam_id, url):
    results[cam_id] = measure_performance(cam_id, url, duration_seconds, stop_event, stats, stats_lock, gpu_stats, gpu_lock)

def measure_performance(camera_id, rtsp_url, duration_seconds, stop_event, stats, stats_lock, gpu_stats, gpu_lock):
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
        last_gpu_log = start_time
        
        # Initial GPU memory
        torch.cuda.synchronize()
        init_allocated = torch.cuda.memory_allocated(0)
        init_reserved = torch.cuda.memory_reserved(0)
        
        max_allocated = init_allocated
        max_reserved = init_reserved
        
        while not stop_event.is_set() and (time.time() - start_time) < duration_seconds:
            wframe = backend.get_frame()
            if wframe is None:
                time.sleep(0.01)
                continue
            
            if wframe.stalled:
                break
            
            with stats_lock:
                stats[camera_id]["frames"] += 1
                stats[camera_id]["queue_depth"] = backend._frame_queue.qsize()
            
            now = time.time()
            
            # Log frame progress every 10 seconds
            if now - last_log >= 10.0:
                with stats_lock:
                    cam_frames = stats[camera_id]["frames"]
                elapsed = now - start_time
                fps = cam_frames / elapsed if elapsed > 0 else 0
                queue_depth = backend._frame_queue.qsize()
                logger.info(f'[{camera_id}] {cam_frames} frames in {elapsed:.1f}s ({fps:.1f} FPS), queue={queue_depth}')
                last_log = now
            
            # Log GPU memory every 30 seconds
            if now - last_gpu_log >= 30.0:
                torch.cuda.synchronize()
                allocated = torch.cuda.memory_allocated(0)
                reserved = torch.cuda.memory_reserved(0)
                max_allocated = max(max_allocated, allocated)
                max_reserved = max(max_reserved, reserved)
                logger.info(f'[{camera_id}] GPU Memory: allocated={allocated/1024/1024:.1f}MB, reserved={reserved/1024/1024:.1f}MB')
                last_gpu_log = now
        
        elapsed = time.time() - start_time
        
        # Final GPU memory
        torch.cuda.synchronize()
        final_allocated = torch.cuda.memory_allocated(0)
        final_reserved = torch.cuda.memory_reserved(0)
        max_allocated = max(max_allocated, final_allocated)
        max_reserved = max(max_reserved, final_reserved)
        
        backend.close()
        
        with stats_lock:
            final_frames = stats[camera_id]["frames"]
        
        fps = final_frames / elapsed if elapsed > 0 else 0
        logger.info(f'[{camera_id}] Completed: {final_frames} frames in {elapsed:.1f}s ({fps:.1f} FPS)')
        logger.info(f'[{camera_id}] GPU Memory: init_alloc={init_allocated/1024/1024:.1f}MB, final_alloc={final_allocated/1024/1024:.1f}MB, max_alloc={max_allocated/1024/1024:.1f}MB')
        
        with gpu_lock:
            gpu_stats[camera_id] = {
                "init_allocated_mb": init_allocated / 1024 / 1024,
                "final_allocated_mb": final_allocated / 1024 / 1024,
                "max_allocated_mb": max_allocated / 1024 / 1024,
                "init_reserved_mb": init_reserved / 1024 / 1024,
                "final_reserved_mb": final_reserved / 1024 / 1024,
                "max_reserved_mb": max_reserved / 1024 / 1024,
            }
        
        return {"camera_id": camera_id, "passed": True, "backend": actual_backend, "frames": final_frames, "fps": fps, "elapsed": elapsed}
        
    except Exception as e:
        logger.error(f'[{camera_id}] Performance test FAILED: {e}', exc_info=True)
        return {"camera_id": camera_id, "passed": False, "error": str(e)}

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("PERFORMANCE, MEMORY, BACKPRESSURE MEASUREMENT (60s)")
    logger.info("=" * 60)
    
    # Clear GPU cache first
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    
    duration_seconds = 60
    stop_event = threading.Event()
    stats = {"CAM1": {"frames": 0, "queue_depth": 0}, "CAM2": {"frames": 0, "queue_depth": 0}}
    stats_lock = threading.Lock()
    gpu_stats = {}
    gpu_lock = threading.Lock()
    results = {}
    
    threads = []
    for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                         ("CAM2", "rtsp://localhost:8554/live/cam2")]:
        t = threading.Thread(target=run_camera, args=(cam_id, url))
        threads.append(t)
        t.start()
        time.sleep(0.5)
    
    time.sleep(duration_seconds)
    stop_event.set()
    
    for t in threads:
        t.join(timeout=10)
    
    # Final summary
    logger.info("=" * 60)
    logger.info("PERFORMANCE & MEMORY SUMMARY")
    logger.info("=" * 60)
    
    with stats_lock:
        for cam_id in ["CAM1", "CAM2"]:
            frames = stats[cam_id]["frames"]
            fps = frames / duration_seconds if duration_seconds > 0 else 0
            logger.info(f'{cam_id}: {frames} frames ({fps:.1f} FPS)')
    
    for cam_id in ["CAM1", "CAM2"]:
        if cam_id in gpu_stats:
            g = gpu_stats[cam_id]
            logger.info(f'{cam_id} GPU Memory:')
            logger.info(f'  Initial Allocated: {g["init_allocated_mb"]:.1f} MB')
            logger.info(f'  Final Allocated: {g["final_allocated_mb"]:.1f} MB')
            logger.info(f'  Max Allocated: {g["max_allocated_mb"]:.1f} MB')
            logger.info(f'  Initial Reserved: {g["init_reserved_mb"]:.1f} MB')
            logger.info(f'  Final Reserved: {g["final_reserved_mb"]:.1f} MB')
            logger.info(f'  Max Reserved: {g["max_reserved_mb"]:.1f} MB')
            logger.info(f'  Growth (Max - Init): {(g["max_allocated_mb"] - g["init_allocated_mb"]):.1f} MB')
    
    all_passed = all(r.get("passed", False) for r in results.values())
    logger.info(f"OVERALL: {'PASSED' if all_passed else 'FAILED'}")