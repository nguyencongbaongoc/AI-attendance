"""
Phase 9.4.2 — Context Thread Matrix Test.

Instruments CUDA context identity across threads.
"""

import sys
import os
import time
import threading
import ctypes
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

# Load CUDA driver
try:
    nvcuda = ctypes.CDLL('nvcuda.dll')
    CUDA_AVAILABLE = True
except Exception as e:
    logger.warning(f"CUDA driver not available: {e}")
    CUDA_AVAILABLE = False

def get_cuda_context():
    """Get current CUDA context for calling thread."""
    if not CUDA_AVAILABLE:
        return None
    try:
        ctx = ctypes.c_void_p()
        result = nvcuda.cuCtxGetCurrent(ctypes.byref(ctx))
        return {"result": result, "context": ctx.value}
    except Exception as e:
        return {"error": str(e)}

def get_cuda_device():
    """Get current CUDA device."""
    if not CUDA_AVAILABLE:
        return None
    try:
        dev = ctypes.c_int()
        result = nvcuda.cuCtxGetDevice(ctypes.byref(dev))
        return {"result": result, "device": dev.value}
    except Exception as e:
        return {"error": str(e)}

# Monkey-patch the reader loop to log context
original_reader_loop = None

def instrumented_reader_loop(self):
    """Instrumented reader loop that logs CUDA context."""
    thread_id = threading.get_ident()
    thread_name = threading.current_thread().name
    
    ctx_info = get_cuda_context()
    dev_info = get_cuda_device()
    
    logger.info(f"[READER THREAD START] camera={self.camera_id} thread={thread_name} "
                f"thread_id={thread_id} ctx_result={ctx_info.get('result')} "
                f"ctx={ctx_info.get('context')} dev_result={dev_info.get('result')} "
                f"dev={dev_info.get('device')}")
    
    # Call original
    try:
        original_reader_loop(self)
    finally:
        ctx_info = get_cuda_context()
        dev_info = get_cuda_device()
        logger.info(f"[READER THREAD END] camera={self.camera_id} thread={thread_name} "
                    f"ctx_result={ctx_info.get('result')} ctx={ctx_info.get('context')} "
                    f"dev_result={dev_info.get('result')} dev={dev_info.get('device')}")

def test_single_camera_context():
    """Test CUDA context in single camera operation."""
    logger.info("=" * 60)
    logger.info("TEST: Single Camera Context Thread Matrix")
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
    
    # Log main thread context
    main_ctx = get_cuda_context()
    main_dev = get_cuda_device()
    logger.info(f"[MAIN THREAD] ctx_result={main_ctx.get('result')} ctx={main_ctx.get('context')} "
                f"dev_result={main_dev.get('result')} dev={main_dev.get('device')}")
    
    # Create backend
    backend, actual = DecoderBackendFactory.create_with_fallback(
        primary_backend="pynvvideocodec", config=config, enable_fallback=True
    )
    logger.info(f"Backend created: {actual}")
    
    # Log context after initialize (before open)
    init_ctx = get_cuda_context()
    init_dev = get_cuda_device()
    logger.info(f"[AFTER INIT] ctx_result={init_ctx.get('result')} ctx={init_ctx.get('context')} "
                f"dev_result={init_dev.get('result')} dev={init_dev.get('device')}")
    
    # Open stream
    info = backend.open()
    logger.info(f"Opened: {info.width}x{info.height}@{info.fps}fps")
    
    # Log context after open (reader thread should be running)
    open_ctx = get_cuda_context()
    open_dev = get_cuda_device()
    logger.info(f"[AFTER OPEN] ctx_result={open_ctx.get('result')} ctx={open_ctx.get('context')} "
                f"dev_result={open_dev.get('result')} dev={open_dev.get('device')}")
    
    # Collect some frames
    for i in range(5):
        wframe = backend.get_frame()
        if wframe and not wframe.stalled:
            logger.info(f"Frame {i}: queue={backend._frame_queue.qsize()}")
        time.sleep(0.1)
    
    # Log context before close
    pre_close_ctx = get_cuda_context()
    pre_close_dev = get_cuda_device()
    logger.info(f"[BEFORE CLOSE] ctx_result={pre_close_ctx.get('result')} ctx={pre_close_ctx.get('context')} "
                f"dev_result={pre_close_dev.get('result')} dev={pre_close_dev.get('device')}")
    
    # Close
    backend.close()
    
    # Log context after close
    post_close_ctx = get_cuda_context()
    post_close_dev = get_cuda_device()
    logger.info(f"[AFTER CLOSE] ctx_result={post_close_ctx.get('result')} ctx={post_close_ctx.get('context')} "
                f"dev_result={post_close_dev.get('result')} dev={post_close_dev.get('device')}")

def test_concurrent_context():
    """Test CUDA context with concurrent cameras."""
    logger.info("=" * 60)
    logger.info("TEST: Concurrent Cameras Context Thread Matrix")
    logger.info("=" * 60)
    
    results = {}
    errors = {}
    
    def run_camera(cam_id, url):
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
            
            thread_id = threading.get_ident()
            main_ctx = get_cuda_context()
            logger.info(f"[{cam_id} MAIN] thread_id={thread_id} ctx={main_ctx.get('context')}")
            
            backend, actual = DecoderBackendFactory.create_with_fallback(
                primary_backend="pynvvideocodec", config=config, enable_fallback=True
            )
            logger.info(f"[{cam_id}] Backend: {actual}")
            
            info = backend.open()
            logger.info(f"[{cam_id}] Opened: {info.width}x{info.height}")
            
            # Collect frames
            for i in range(3):
                wframe = backend.get_frame()
                if wframe and not wframe.stalled:
                    pass
                time.sleep(0.05)
            
            backend.close()
            results[cam_id] = {"backend": actual, "success": True}
            
        except Exception as e:
            logger.error(f"[{cam_id}] Error: {e}")
            errors[cam_id] = str(e)
            results[cam_id] = {"success": False, "error": str(e)}
    
    # Run sequentially first
    logger.info("--- Sequential ---")
    run_camera("CAM1", "rtsp://localhost:8554/live/cam1")
    time.sleep(1)
    run_camera("CAM2", "rtsp://localhost:8554/live/cam2")
    
    logger.info(f"Sequential results: {results}")

def main():
    logger.info("PHASE 9.4.2 — CONTEXT THREAD MATRIX")
    logger.info("=" * 60)
    
    # Install instrumentation
    global original_reader_loop
    from app.streaming import pynvvideocodec_backend
    original_reader_loop = pynvvideocodec_backend.PyNvVideoCodecBackend._reader_loop
    pynvvideocodec_backend.PyNvVideoCodecBackend._reader_loop = instrumented_reader_loop
    
    try:
        test_single_camera_context()
        time.sleep(2)
        test_concurrent_context()
    finally:
        # Restore
        pynvvideocodec_backend.PyNvVideoCodecBackend._reader_loop = original_reader_loop
    
    logger.info("=" * 60)
    logger.info("CONTEXT THREAD MATRIX COMPLETE")
    logger.info("=" * 60)

if __name__ == "__main__":
    sys.exit(main())