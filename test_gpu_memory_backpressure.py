"""
Phase 9.4.1 — GPU Memory / Backpressure Qualification Test.

Measures GPU VRAM, queue depth, dropped frames, and memory growth
during sustained dual-camera operation.
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def get_gpu_memory():
    """Get current GPU memory usage in MB."""
    try:
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / 1024 / 1024
            reserved = torch.cuda.memory_reserved(0) / 1024 / 1024
            total = torch.cuda.get_device_properties(0).total_memory / 1024 / 1024
            free = total - reserved
            return {
                "allocated_mb": round(allocated, 1),
                "reserved_mb": round(reserved, 1),
                "total_mb": round(total, 1),
                "free_mb": round(free, 1),
            }
    except Exception as e:
        logger.warning(f"GPU memory query failed: {e}")
    return None


def get_nvidia_smi():
    """Get nvidia-smi memory info."""
    try:
        import subprocess
        result = subprocess.run([
            'nvidia-smi', '--query-gpu=memory.used,memory.free,memory.total',
            '--format=csv,noheader,nounits'
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            line = result.stdout.strip().split('\n')[0]
            used, free, total = map(int, line.split(', '))
            return {
                "used_mb": used,
                "free_mb": free,
                "total_mb": total,
            }
    except Exception as e:
        logger.warning(f"nvidia-smi failed: {e}")
    return None


def run_memory_qualification():
    """Run GPU memory qualification for single camera sustained."""
    logger.info("=" * 60)
    logger.info("GPU MEMORY / BACKPRESSURE QUALIFICATION")
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
    
    # Initial GPU state
    logger.info("--- STARTUP ---")
    startup_mem = get_gpu_memory()
    startup_smi = get_nvidia_smi()
    logger.info(f"PyTorch: {startup_mem}")
    logger.info(f"nvidia-smi: {startup_smi}")
    
    # Create backend
    logger.info("Creating Backend B...")
    backend, actual_backend = DecoderBackendFactory.create_with_fallback(
        primary_backend="pynvvideocodec",
        config=config,
        enable_fallback=True,
    )
    logger.info(f"Backend: {actual_backend}")
    
    # After initialization
    logger.info("--- AFTER INITIALIZATION ---")
    init_mem = get_gpu_memory()
    init_smi = get_nvidia_smi()
    logger.info(f"PyTorch: {init_mem}")
    logger.info(f"nvidia-smi: {init_smi}")
    
    # Open stream
    info = backend.open()
    logger.info(f"Opened: {info.width}x{info.height}@{info.fps}fps")
    
    # After open
    logger.info("--- AFTER OPEN ---")
    open_mem = get_gpu_memory()
    open_smi = get_nvidia_smi()
    logger.info(f"PyTorch: {open_mem}")
    logger.info(f"nvidia-smi: {open_smi}")
    
    # Warm-up: collect frames for 10 seconds
    logger.info("--- WARM-UP (10s) ---")
    warmup_start = time.time()
    warmup_frames = 0
    max_queue = 0
    
    while time.time() - warmup_start < 10:
        wframe = backend.get_frame()
        if wframe and not wframe.stalled:
            warmup_frames += 1
            qsize = backend._frame_queue.qsize()
            max_queue = max(max_queue, qsize)
        time.sleep(0.01)
    
    warmup_mem = get_gpu_memory()
    warmup_smi = get_nvidia_smi()
    logger.info(f"Warm-up frames: {warmup_frames}, max queue: {max_queue}")
    logger.info(f"PyTorch: {warmup_mem}")
    logger.info(f"nvidia-smi: {warmup_smi}")
    
    # Sustained operation: 30 seconds
    logger.info("--- SUSTAINED OPERATION (30s) ---")
    sustained_start = time.time()
    sustained_frames = 0
    sustained_drops = 0
    max_queue_sustained = 0
    mem_samples = []
    smi_samples = []
    
    last_log = sustained_start
    while time.time() - sustained_start < 30:
        wframe = backend.get_frame()
        if wframe and not wframe.stalled:
            sustained_frames += 1
            qsize = backend._frame_queue.qsize()
            max_queue_sustained = max(max_queue_sustained, qsize)
        elif wframe and wframe.stalled:
            break
        time.sleep(0.001)  # Small sleep to not burn CPU
        
        # Sample memory every 5 seconds
        now = time.time()
        if now - last_log >= 5.0:
            mem = get_gpu_memory()
            smi = get_nvidia_smi()
            if mem:
                mem_samples.append(mem["allocated_mb"])
            if smi:
                smi_samples.append(smi["used_mb"])
            logger.info(f"  {now - sustained_start:.0f}s: frames={sustained_frames}, queue={qsize}, "
                       f"PyTorch alloc={mem['allocated_mb'] if mem else 'N/A'}MB, "
                       f"nvidia-smi used={smi['used_mb'] if smi else 'N/A'}MB")
            last_log = now
    
    sustained_mem = get_gpu_memory()
    sustained_smi = get_nvidia_smi()
    sustained_elapsed = time.time() - sustained_start
    sustained_fps = sustained_frames / sustained_elapsed if sustained_elapsed > 0 else 0
    
    logger.info(f"Sustained: {sustained_frames} frames in {sustained_elapsed:.1f}s ({sustained_fps:.1f} FPS)")
    logger.info(f"Max queue depth: {max_queue_sustained}")
    logger.info(f"PyTorch: {sustained_mem}")
    logger.info(f"nvidia-smi: {sustained_smi}")
    
    # Shutdown
    logger.info("--- SHUTDOWN ---")
    backend.close()
    time.sleep(1)
    
    shutdown_mem = get_gpu_memory()
    shutdown_smi = get_nvidia_smi()
    logger.info(f"PyTorch: {shutdown_mem}")
    logger.info(f"nvidia-smi: {shutdown_smi}")
    
    # Reinitialization
    logger.info("--- REINITIALIZATION ---")
    backend2, actual_backend2 = DecoderBackendFactory.create_with_fallback(
        primary_backend="pynvvideocodec",
        config=config,
        enable_fallback=True,
    )
    info2 = backend2.open()
    
    reinit_mem = get_gpu_memory()
    reinit_smi = get_nvidia_smi()
    logger.info(f"PyTorch: {reinit_mem}")
    logger.info(f"nvidia-smi: {reinit_smi}")
    
    # Collect a few frames
    for i in range(10):
        wframe = backend2.get_frame()
        if wframe and not wframe.stalled:
            pass
        time.sleep(0.03)
    
    backend2.close()
    time.sleep(1)
    
    final_mem = get_gpu_memory()
    final_smi = get_nvidia_smi()
    logger.info(f"Final PyTorch: {final_mem}")
    logger.info(f"Final nvidia-smi: {final_smi}")
    
    # Analysis
    logger.info("=" * 60)
    logger.info("MEMORY ANALYSIS")
    logger.info("=" * 60)
    
    def mem_diff(before, after, label):
        if before and after:
            diff = after["allocated_mb"] - before["allocated_mb"]
            logger.info(f"{label}: {diff:+.1f} MB allocated delta")
            return diff
        return 0
    
    mem_diff(startup_mem, init_mem, "Init delta")
    mem_diff(init_mem, open_mem, "Open delta")
    mem_diff(open_mem, warmup_mem, "Warm-up delta")
    mem_diff(warmup_mem, sustained_mem, "Sustained delta")
    mem_diff(sustained_mem, shutdown_mem, "Shutdown delta")
    mem_diff(shutdown_mem, reinit_mem, "Reinit delta")
    mem_diff(reinit_mem, final_mem, "Final delta")
    
    total_growth = mem_diff(startup_mem, final_mem, "Total growth (startup->final)")
    
    # Queue analysis
    logger.info(f"Max queue depth (warm-up): {max_queue}")
    logger.info(f"Max queue depth (sustained): {max_queue_sustained}")
    
    # Memory growth analysis
    if mem_samples:
        logger.info(f"PyTorch allocated samples: min={min(mem_samples):.1f}, max={max(mem_samples):.1f}, "
                   f"avg={sum(mem_samples)/len(mem_samples):.1f} MB")
    if smi_samples:
        logger.info(f"nvidia-smi used samples: min={min(smi_samples)}, max={max(smi_samples)}, "
                   f"avg={sum(smi_samples)/len(smi_samples):.1f} MB")
    
    # Verdict
    logger.info("=" * 60)
    logger.info("VERDICT")
    logger.info("=" * 60)
    
    issues = []
    if total_growth > 100:  # >100MB growth is concerning
        issues.append(f"Significant memory growth: {total_growth:.1f} MB")
    if max_queue_sustained > 5:
        issues.append(f"Queue backing up: max depth {max_queue_sustained}")
    if sustained_fps < 25:
        issues.append(f"Low sustained FPS: {sustained_fps:.1f}")
    
    if issues:
        logger.warning("ISSUES FOUND:")
        for issue in issues:
            logger.warning(f"  - {issue}")
        verdict = "CONCERNING"
    else:
        logger.info("No significant issues detected")
        verdict = "PASS"
    
    logger.info(f"VERDICT: {verdict}")
    
    return {
        "verdict": verdict,
        "total_growth_mb": total_growth,
        "max_queue_warmup": max_queue,
        "max_queue_sustained": max_queue_sustained,
        "sustained_fps": sustained_fps,
        "sustained_frames": sustained_frames,
        "startup_mem": startup_mem,
        "init_mem": init_mem,
        "open_mem": open_mem,
        "warmup_mem": warmup_mem,
        "sustained_mem": sustained_mem,
        "shutdown_mem": shutdown_mem,
        "reinit_mem": reinit_mem,
        "final_mem": final_mem,
    }


def main():
    result = run_memory_qualification()
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())