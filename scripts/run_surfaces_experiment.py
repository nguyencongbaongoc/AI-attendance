"""
Supplemental Test — NVDEC Surfaces 8/10 Controlled Experiment Runner.

Executes controlled trials across:
- Config A: Current / Default (no surfaces override)
- Config B: surfaces = 10
- Config C: surfaces = 8

Measures:
- Stage 1: av.open()
- Stage 2: first decoded frame
- Stage 3: 30s sustained decode
- Stage 4: 180s sustained decode
- Stage 5: CAM1, CAM2, and CAM1+CAM2 concurrent

Tracks VRAM via NVML (baseline, post-open, peak, post-shutdown) and ensures CUDA initialization ordering invariant.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pynvml
import torch

from app.streaming.pyav_nvdec_decoder import PyAVNVDECDecoderConfig, PyAVNVDECDecoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("surfaces_experiment")


@dataclass
class RunMetrics:
    config_name: str
    camera_id: str
    run_index: int
    rtsp_url: str
    target_duration: float
    
    # Pre-open checks
    cuda_init_before_open: bool
    vram_baseline_mb: float
    
    # Stage 1: av.open()
    stage1_open_success: bool
    stage1_open_time_s: float
    vram_post_open_mb: float
    open_error: Optional[str] = None
    
    # Stage 2: First frame
    stage2_first_frame_success: bool = False
    stage2_first_frame_time_s: float = 0.0
    frame_width: int = 0
    frame_height: int = 0
    frame_format: str = ""
    is_gpu_frame: bool = False
    
    # Stage 3/4: Sustained decode
    stage_sustained_success: bool = False
    actual_duration_s: float = 0.0
    frames_decoded: int = 0
    decode_fps: float = 0.0
    decode_errors: int = 0
    vram_peak_mb: float = 0.0
    vram_delta_mb: float = 0.0
    vram_after_shutdown_mb: float = 0.0
    vram_samples: Optional[List[float]] = None
    sustained_error: Optional[str] = None


class NVMLTracker:
    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        pynvml.nvmlInit()
        self.handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        
    def get_vram_mb(self) -> float:
        info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
        return float(info.used / (1024**2))
    
    def get_device_name(self) -> str:
        return pynvml.nvmlDeviceGetName(self.handle)
    
    def get_driver_version(self) -> str:
        return pynvml.nvmlSystemGetDriverVersion()
    
    def get_total_vram_mb(self) -> float:
        info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
        return float(info.total / (1024**2))


def run_single_trial(
    config_name: str,
    camera_id: str,
    rtsp_url: str,
    run_index: int,
    target_duration_s: float,
    nvdec_surfaces: int,
    tracker: NVMLTracker,
) -> RunMetrics:
    logger.info(f"=== Starting Trial: Config={config_name}, Camera={camera_id}, Run={run_index}, Duration={target_duration_s}s ===")
    
    # Check CUDA ordering invariant BEFORE opening
    cuda_init_before = torch.cuda.is_initialized()
    vram_baseline = tracker.get_vram_mb()
    
    # Build decoder config
    config = PyAVNVDECDecoderConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        nvdec_gpu_device=0,
        expected_width=3840,
        expected_height=2160,
        expected_fps=30.0,
        nvdec_surfaces=nvdec_surfaces,
    )
    decoder = PyAVNVDECDecoder(config)
    
    metrics = RunMetrics(
        config_name=config_name,
        camera_id=camera_id,
        run_index=run_index,
        rtsp_url=rtsp_url,
        target_duration=target_duration_s,
        cuda_init_before_open=cuda_init_before,
        vram_baseline_mb=vram_baseline,
        stage1_open_success=False,
        stage1_open_time_s=0.0,
        vram_post_open_mb=0.0,
    )
    
    # Stage 1: av.open()
    t_start = time.perf_counter()
    try:
        decoder.open()
        t_open = time.perf_counter() - t_start
        metrics.stage1_open_success = True
        metrics.stage1_open_time_s = t_open
        metrics.vram_post_open_mb = tracker.get_vram_mb()
        logger.info(f"Stage 1 PASS: open time = {t_open*1000:.1f}ms, VRAM post-open = {metrics.vram_post_open_mb:.1f}MB")
    except Exception as e:
        metrics.stage1_open_time_s = time.perf_counter() - t_start
        metrics.open_error = str(e)
        metrics.vram_after_shutdown_mb = tracker.get_vram_mb()
        logger.error(f"Stage 1 FAIL: {e}")
        return metrics
    
    # Stage 2: First decoded frame
    t_first_start = time.perf_counter()
    first_frame = None
    try:
        first_frame = decoder.get_next_frame()
        t_first = time.perf_counter() - t_first_start
        if first_frame and not first_frame.stalled and first_frame.data is not None:
            metrics.stage2_first_frame_success = True
            metrics.stage2_first_frame_time_s = t_first
            metrics.frame_width = first_frame.data.get("width", 0)
            metrics.frame_height = first_frame.data.get("height", 0)
            metrics.frame_format = first_frame.data.get("format", "")
            metrics.is_gpu_frame = first_frame.is_gpu_frame
            logger.info(
                f"Stage 2 PASS: first frame in {t_first*1000:.1f}ms "
                f"({metrics.frame_width}x{metrics.frame_height}, fmt={metrics.frame_format}, gpu={metrics.is_gpu_frame})"
            )
        else:
            logger.error("Stage 2 FAIL: first frame is None or stalled")
            decoder.close()
            metrics.vram_after_shutdown_mb = tracker.get_vram_mb()
            return metrics
    except Exception as e:
        logger.error(f"Stage 2 FAIL: exception retrieving first frame: {e}")
        metrics.sustained_error = str(e)
        decoder.close()
        metrics.vram_after_shutdown_mb = tracker.get_vram_mb()
        return metrics

    # Stage 3/4: Sustained decode
    vram_samples: List[float] = [metrics.vram_post_open_mb]
    vram_peak = metrics.vram_post_open_mb
    frames_count = 1  # including the first frame
    decode_errors = 0
    t_decode_start = time.perf_counter()
    last_sample_time = t_decode_start
    
    try:
        while True:
            now = time.perf_counter()
            elapsed = now - t_decode_start
            if elapsed >= target_duration_s:
                break
            
            # Sample VRAM every 1s
            if now - last_sample_time >= 1.0:
                cur_vram = tracker.get_vram_mb()
                vram_samples.append(cur_vram)
                if cur_vram > vram_peak:
                    vram_peak = cur_vram
                last_sample_time = now
            
            frame = decoder.get_next_frame()
            if frame is None:
                decode_errors += 1
                time.sleep(0.005)
                continue
            if frame.stalled:
                decode_errors += 1
                logger.warning("Received stalled frame during decode loop")
                continue
            
            frames_count += 1
            
        metrics.stage_sustained_success = True
    except Exception as e:
        logger.error(f"Sustained decode crashed at {time.perf_counter() - t_decode_start:.1f}s: {e}")
        metrics.sustained_error = str(e)
    finally:
        total_decode_time = time.perf_counter() - t_decode_start
        decoder.close()
        time.sleep(0.5)  # brief settle
        vram_after = tracker.get_vram_mb()
        
    metrics.actual_duration_s = total_decode_time
    metrics.frames_decoded = frames_count
    metrics.decode_fps = frames_count / total_decode_time if total_decode_time > 0 else 0.0
    metrics.decode_errors = decode_errors
    metrics.vram_peak_mb = max(vram_peak, max(vram_samples) if vram_samples else 0.0)
    metrics.vram_delta_mb = metrics.vram_peak_mb - metrics.vram_baseline_mb
    metrics.vram_after_shutdown_mb = vram_after
    metrics.vram_samples = vram_samples
    
    logger.info(
        f"Sustained decode completed: duration={total_decode_time:.1f}s, frames={frames_count}, "
        f"FPS={metrics.decode_fps:.2f}, errors={decode_errors}, peak VRAM={metrics.vram_peak_mb:.1f}MB, delta={metrics.vram_delta_mb:+.1f}MB"
    )
    return metrics


def run_concurrent_dual_camera(
    config_name: str,
    duration_s: float,
    surfaces: int,
    tracker: NVMLTracker,
) -> Dict[str, Any]:
    logger.info(f"=== Starting Concurrent Dual-Camera Test: Config={config_name}, Duration={duration_s}s ===")
    vram_baseline = tracker.get_vram_mb()
    
    cfg1 = PyAVNVDECDecoderConfig(
        camera_id="CAM1",
        rtsp_url="rtsp://localhost:8554/live/cam1?transport=tcp",
        expected_width=3840,
        expected_height=2160,
        expected_fps=30.0,
        nvdec_surfaces=surfaces,
    )
    cfg2 = PyAVNVDECDecoderConfig(
        camera_id="CAM2",
        rtsp_url="rtsp://localhost:8554/live/cam2?transport=tcp",
        expected_width=3840,
        expected_height=2160,
        expected_fps=30.0,
        nvdec_surfaces=surfaces,
    )
    
    d1 = PyAVNVDECDecoder(cfg1)
    d2 = PyAVNVDECDecoder(cfg2)
    
    t0 = time.perf_counter()
    d1.open()
    d2.open()
    t_open = time.perf_counter() - t0
    
    vram_post_open = tracker.get_vram_mb()
    vram_peak = vram_post_open
    vram_samples = [vram_post_open]
    
    frames_cam1 = 0
    frames_cam2 = 0
    errors_cam1 = 0
    errors_cam2 = 0
    
    t_decode_start = time.perf_counter()
    last_sample = t_decode_start
    
    while time.perf_counter() - t_decode_start < duration_s:
        now = time.perf_counter()
        if now - last_sample >= 1.0:
            cur = tracker.get_vram_mb()
            vram_samples.append(cur)
            if cur > vram_peak:
                vram_peak = cur
            last_sample = now
            
        f1 = d1.get_next_frame()
        if f1 and not f1.stalled:
            frames_cam1 += 1
        else:
            errors_cam1 += 1
            
        f2 = d2.get_next_frame()
        if f2 and not f2.stalled:
            frames_cam2 += 1
        else:
            errors_cam2 += 1
            
    total_time = time.perf_counter() - t_decode_start
    d1.close()
    d2.close()
    time.sleep(0.5)
    vram_after = tracker.get_vram_mb()
    
    fps1 = frames_cam1 / total_time
    fps2 = frames_cam2 / total_time
    
    res = {
        "config_name": config_name,
        "duration_s": total_time,
        "open_time_s": t_open,
        "vram_baseline_mb": vram_baseline,
        "vram_post_open_mb": vram_post_open,
        "vram_peak_mb": vram_peak,
        "vram_delta_mb": vram_peak - vram_baseline,
        "vram_after_shutdown_mb": vram_after,
        "cam1_frames": frames_cam1,
        "cam1_fps": fps1,
        "cam1_errors": errors_cam1,
        "cam2_frames": frames_cam2,
        "cam2_fps": fps2,
        "cam2_errors": errors_cam2,
        "total_fps": fps1 + fps2,
        "vram_samples": vram_samples,
    }
    logger.info(
        f"Concurrent test completed: CAM1={frames_cam1} frames ({fps1:.1f} fps), "
        f"CAM2={frames_cam2} frames ({fps2:.1f} fps), Peak VRAM={vram_peak:.1f}MB (+{res['vram_delta_mb']:.1f}MB)"
    )
    return res


def main():
    parser = argparse.ArgumentParser(description="NVDEC Surfaces Controlled Experiment")
    parser.add_argument("--out-dir", type=str, default="benchmark_results/surfaces_experiment", help="Output directory")
    parser.add_argument("--runs", type=int, default=3, help="Number of 30s trials per configuration")
    parser.add_argument("--include-180s", action="store_true", help="Include 180s sustained decode qualification run")
    parser.add_argument("--include-dual", action="store_true", help="Include CAM2 and concurrent dual-cam test")
    args = parser.parse_args()

    tracker = NVMLTracker(0)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    env_info = {
        "gpu_name": tracker.get_device_name(),
        "driver_version": tracker.get_driver_version(),
        "total_vram_mb": tracker.get_total_vram_mb(),
        "cuda_version": torch.version.cuda,
        "torch_version": torch.__version__,
        "python_version": sys.version,
    }
    try:
        import av
        env_info["pyav_version"] = av.__version__
        env_info["av_library_versions"] = {k: list(v) for k, v in av.library_versions.items()}
    except Exception as e:
        env_info["pyav_error"] = str(e)

    logger.info(f"Environment: {json.dumps(env_info, indent=2)}")

    configs = [
        {"name": "Default", "surfaces": 32},     # 32 is default, preserves untouched codec context
        {"name": "surfaces=10", "surfaces": 10},
        {"name": "surfaces=8", "surfaces": 8},
    ]

    results_path = out_dir / "experiment_raw_data.json"
    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            logger.info("Loaded existing experiment data from raw JSON")
        except Exception as e:
            logger.warning(f"Failed to load existing results: {e}")
            all_results = {
                "env_info": env_info,
                "trials": [],
                "qualification_180s": [],
                "cam2_trials": [],
                "dual_concurrent": [],
            }
    else:
        all_results = {
            "env_info": env_info,
            "trials": [],
            "qualification_180s": [],
            "cam2_trials": [],
            "dual_concurrent": [],
        }

    all_results["env_info"] = env_info

    cam1_url = "rtsp://localhost:8554/live/cam1?transport=tcp"
    cam2_url = "rtsp://localhost:8554/live/cam2?transport=tcp"

    # 1. Run 30s trials for CAM1 (3 runs each for A, B, C)
    for cfg in configs:
        for run_idx in range(1, args.runs + 1):
            res = run_single_trial(
                config_name=cfg["name"],
                camera_id="CAM1",
                rtsp_url=cam1_url,
                run_index=run_idx,
                target_duration_s=30.0,
                nvdec_surfaces=cfg["surfaces"],
                tracker=tracker,
            )
            all_results["trials"].append(asdict(res))
            time.sleep(3.0)

    # 2. Stage 4: 180s sustained decode qualification run for each configuration
    if args.include_180s:
        logger.info("=== Running Stage 4: 180s Sustained Decode Qualification ===")
        for cfg in configs:
            res_180 = run_single_trial(
                config_name=cfg["name"],
                camera_id="CAM1",
                rtsp_url=cam1_url,
                run_index=1,
                target_duration_s=180.0,
                nvdec_surfaces=cfg["surfaces"],
                tracker=tracker,
            )
            all_results["qualification_180s"].append(asdict(res_180))
            time.sleep(2.0)

    # 3. Stage 5: CAM2 qualification and CAM1+CAM2 concurrent
    if args.include_dual:
        logger.info("=== Running Stage 5: CAM2 qualification ===")
        for cfg in configs:
            res_cam2 = run_single_trial(
                config_name=cfg["name"],
                camera_id="CAM2",
                rtsp_url=cam2_url,
                run_index=1,
                target_duration_s=30.0,
                nvdec_surfaces=cfg["surfaces"],
                tracker=tracker,
            )
            all_results["cam2_trials"].append(asdict(res_cam2))
            time.sleep(1.0)

        logger.info("=== Running Stage 5: Concurrent CAM1 + CAM2 ===")
        for cfg in configs:
            res_dual = run_concurrent_dual_camera(
                config_name=cfg["name"],
                duration_s=30.0,
                surfaces=cfg["surfaces"],
                tracker=tracker,
            )
            all_results["dual_concurrent"].append(res_dual)
            time.sleep(2.0)

    # Save raw results JSON
    results_path = out_dir / "experiment_raw_data.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    logger.info(f"Raw experiment results saved to: {results_path}")


if __name__ == "__main__":
    main()
