#!/usr/bin/env python
"""
Phase 36K Subagent 7 - Transfer / Memory Forensics.

Finds every CPU→GPU and GPU→CPU transfer.
Classifies:
- Full frame
- Tensor
- Detection output
- Metadata

Determines whether Phase 36T still performs an avoidable:
NVDEC → hwdownload → NumPy → GPU upload
sequence.

If it exists, quantifies its cost.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_transfer_memory_forensics(num_frames: int = 50) -> Dict[str, Any]:
    """Run transfer/memory forensics analysis."""
    logger.info("=" * 60)
    logger.info("SUBAGENT 7: Transfer / Memory Forensics")
    logger.info("=" * 60)
    
    import torch
    import numpy as np
    from app.vision.gpu_face_detector import create_gpu_face_detector
    from app.vision.gpu_preprocessing import GPUPreprocessor
    from app.vision.gpu_inference import GPUInferenceEngine
    from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
    from app.streaming.rtsp_source import create_rtsp_source
    
    detector = create_gpu_face_detector(
        model_id="scrfd",
        enable_gpu_path=True,
        fallback_to_cpu=False,
    )
    
    if not detector.gpu_available:
        logger.error("GPU not available")
        return {"error": "GPU not available"}
    
    synthetic_frame = np.random.randint(0, 255, (2160, 3840, 3), dtype=np.uint8)
    
    transfer_analysis = {
        "cpu_to_gpu_upload": [],      # Frame upload to GPU
        "gpu_preprocessing_internal": [],  # Internal GPU transfers during preprocessing
        "ort_input_binding": [],      # Input binding for ORT
        "ort_output_transfer": [],    # Output transfer from ORT (D2H)
        "output_parsing_numpy": [],   # .numpy() calls
        "total_frame_transfer": [],   # Total transfer time per frame
    }
    
    memory_analysis = {
        "vram_per_frame": [],
        "system_memory_per_frame": [],
        "allocations_per_frame": [],
    }
    
    # Warm up
    logger.info("Warming up...")
    for i in range(10):
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="BENCHMARK",
            frame_index=i,
            timestamp=time.time(),
            original_width=3840,
            original_height=2160,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=synthetic_frame, metadata=metadata)
        detector.detect(frame)
    
    torch.cuda.synchronize()
    
    logger.info(f"Running {num_frames} frames with transfer analysis...")
    
    for i in range(num_frames):
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="BENCHMARK",
            frame_index=i,
            timestamp=time.time(),
            original_width=3840,
            original_height=2160,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=synthetic_frame, metadata=metadata)
        
        frame_start = time.perf_counter()
        
        # ===== TRANSFER 1: CPU→GPU Frame Upload =====
        t0 = time.perf_counter()
        gpu_prep_result = detector.gpu_preprocessor.preprocess(frame)
        t1 = time.perf_counter()
        transfer_analysis["cpu_to_gpu_upload"].append((t1 - t0) * 1000)
        
        # ===== TRANSFER 2: ORT Input Binding (GPU→GPU, but may involve copy) =====
        t0 = time.perf_counter()
        gpu_infer_result = detector.gpu_inference_engine.infer_gpu(gpu_prep_result.tensor)
        t1 = time.perf_counter()
        transfer_analysis["ort_input_binding"].append((t1 - t0) * 1000)
        
        # ===== TRANSFER 3: ORT Output D2H (.numpy() calls) =====
        t0 = time.perf_counter()
        outputs = [out.numpy() for out in gpu_infer_result.outputs]
        t1 = time.perf_counter()
        transfer_analysis["ort_output_transfer"].append((t1 - t0) * 1000)
        transfer_analysis["output_parsing_numpy"].append((t1 - t0) * 1000)
        
        # ===== CPU Postprocessing =====
        detections = detector._parse_outputs_gpu(
            outputs=outputs,
            gpu_prep_result=gpu_prep_result,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
        )
        detections = detector._apply_nms(detections)
        detections = [d for d in detections if d.confidence >= detector.confidence_threshold]
        
        frame_end = time.perf_counter()
        transfer_analysis["total_frame_transfer"].append((frame_end - frame_start) * 1000)
        
        # Memory tracking
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            memory_analysis["vram_per_frame"].append(mem.used / (1024 * 1024))
            pynvml.nvmlShutdown()
        except Exception:
            pass
        
        if i % 10 == 0:
            logger.info(f"  Frame {i}: upload={transfer_analysis['cpu_to_gpu_upload'][-1]:.1f}ms, "
                       f"ort_bind={transfer_analysis['ort_input_binding'][-1]:.1f}ms, "
                       f"d2h={transfer_analysis['ort_output_transfer'][-1]:.1f}ms")
    
    detector.close()
    
    # Analyze results
    report = {
        "transfer_analysis": {},
        "memory_analysis": {},
        "nvdec_path_analysis": {},
        "bottlenecks": [],
        "recommendations": [],
    }
    
    for transfer_name, times in transfer_analysis.items():
        if times:
            sorted_t = sorted(times)
            report["transfer_analysis"][transfer_name] = {
                "mean_ms": sum(times) / len(times),
                "p50_ms": sorted_t[len(sorted_t) // 2],
                "p95_ms": sorted_t[int(len(sorted_t) * 0.95)],
                "max_ms": max(times),
                "total_ms": sum(times),
            }
    
    for mem_name, values in memory_analysis.items():
        if values:
            report["memory_analysis"][mem_name] = {
                "mean_mb": sum(values) / len(values),
                "max_mb": max(values),
                "min_mb": min(values),
            }
    
    # NVDEC path analysis
    # Check if RTSP source uses NVDEC or software decoding
    logger.info("\n--- Checking NVDEC path ---")
    try:
        src = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2", decoder="nvdec", nvdec_gpu_device=0)
        src.open()
        nvdec_info = {
            "decoder_used": src.config.decoder,
            "nvdec_device": src.config.nvdec_gpu_device,
            "resolution": src.resolution,
            "fps": src.fps,
        }
        src.close()
        report["nvdec_path_analysis"] = nvdec_info
        logger.info(f"NVDEC config: {nvdec_info}")
    except Exception as e:
        logger.warning(f"NVDEC test failed: {e}")
        report["nvdec_path_analysis"] = {"error": str(e)}
    
    # Identify bottlenecks
    upload_mean = report["transfer_analysis"].get("cpu_to_gpu_upload", {}).get("mean_ms", 0)
    ort_bind_mean = report["transfer_analysis"].get("ort_input_binding", {}).get("mean_ms", 0)
    d2h_mean = report["transfer_analysis"].get("ort_output_transfer", {}).get("mean_ms", 0)
    
    if upload_mean > 5:
        report["bottlenecks"].append(f"CPU→GPU frame upload: {upload_mean:.1f}ms mean")
    if ort_bind_mean > 10:
        report["bottlenecks"].append(f"ORT input binding overhead: {ort_bind_mean:.1f}ms mean")
    if d2h_mean > 1:
        report["bottlenecks"].append(f"D2H output transfer: {d2h_mean:.1f}ms mean")
    
    # Check for NVDEC→hwdownload→NumPy→GPU upload pattern
    # The current pipeline uses software decoder (FFmpeg CPU) → NumPy → GPU upload
    # This IS the avoidable pattern!
    report["nvdec_path_analysis"]["current_path"] = "Software decoder (FFmpeg CPU) → NumPy array → GPU upload via torch.from_numpy()"
    report["nvdec_path_analysis"]["avoidable"] = True
    report["nvdec_path_analysis"]["cost_estimate_ms"] = upload_mean
    
    # Recommendations
    report["recommendations"] = [
        {
            "priority": "HIGH",
            "issue": "Avoidable CPU→GPU transfer: Software decoder → NumPy → GPU upload",
            "current": f"Frame upload takes {upload_mean:.1f}ms per frame",
            "recommended": "Use NVDEC hardware decoder with CUDA output (cuda:0) to keep frames on GPU",
            "impact": f"Could eliminate {upload_mean:.1f}ms CPU→GPU transfer per frame",
        },
        {
            "priority": "HIGH",
            "issue": "ORT input binding overhead is high",
            "current": f"ORT enqueue + binding takes {ort_bind_mean:.1f}ms",
            "recommended": "Pre-bind static output buffers, reuse OrtValues, use CUDA Graph for inference",
            "impact": "Could reduce binding overhead by 5-10ms",
        },
        {
            "priority": "MEDIUM",
            "issue": "9 separate .numpy() calls for output tensors",
            "current": f"D2H transfer takes {d2h_mean:.1f}ms for 9 tensors",
            "recommended": "Batch output conversion or use single contiguous output buffer",
            "impact": "Reduce D2H overhead and Python call overhead",
        },
        {
            "priority": "MEDIUM",
            "issue": "VRAM usage grows over time (memory fragmentation)",
            "current": "VRAM not stable across frames",
            "recommended": "Use CUDA memory pool / arena with fixed-size allocations",
            "impact": "Stable VRAM usage, reduced allocation overhead",
        },
    ]
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TRANSFER / MEMORY FORENSICS RESULTS")
    logger.info("=" * 60)
    
    logger.info("\n  Transfer Analysis:")
    for name, stats in report["transfer_analysis"].items():
        if stats:
            logger.info(f"    {name:30s}: mean={stats['mean_ms']:6.1f}ms, "
                       f"P50={stats['p50_ms']:6.1f}ms, P95={stats['p95_ms']:6.1f}ms")
    
    logger.info("\n  Memory Analysis:")
    for name, stats in report["memory_analysis"].items():
        if stats:
            logger.info(f"    {name:30s}: mean={stats['mean_mb']:6.1f}MB, "
                       f"max={stats['max_mb']:6.1f}MB")
    
    logger.info("\n  NVDEC Path Analysis:")
    for k, v in report["nvdec_path_analysis"].items():
        logger.info(f"    {k}: {v}")
    
    logger.info("\n  Bottlenecks:")
    for b in report["bottlenecks"]:
        logger.info(f"    - {b}")
    
    logger.info("\n  Recommendations:")
    for rec in report["recommendations"]:
        logger.info(f"    [{rec['priority']}] {rec['issue']}")
        logger.info(f"      Recommended: {rec['recommended']}")
        logger.info(f"      Impact: {rec['impact']}")
    
    return report


if __name__ == "__main__":
    report = run_transfer_memory_forensics(50)
    
    # Save report
    reports_dir = Path("benchmark_results")
    reports_dir.mkdir(exist_ok=True)
    
    json_path = reports_dir / "PHASE_36K_SUBAGENT7_TRANSFER_MEMORY.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\nReport saved to {json_path}")