#!/usr/bin/env python
"""
Phase 36K Subagent 2 - GPU vs Host Time Analysis.

Separates:
- GPU kernel execution time
- CPU host time
- ORT enqueue time
- CUDA synchronization time
- H2D transfer time
- D2H transfer time
- CPU preprocessing
- CPU postprocessing

Key question: Is the GPU actually busy computing, or is the CPU waiting/orchestrating?
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class GPUTiming:
    """Detailed GPU/CPU timing breakdown."""
    # GPU kernel time (measured via CUDA events)
    gpu_kernel_ms: List[float] = field(default_factory=list)
    # CPU host time (total - GPU)
    cpu_host_ms: List[float] = field(default_factory=list)
    # ORT enqueue time
    ort_enqueue_ms: List[float] = field(default_factory=list)
    # CUDA sync time
    cuda_sync_ms: List[float] = field(default_factory=list)
    # H2D transfer
    h2d_ms: List[float] = field(default_factory=list)
    # D2H transfer
    d2h_ms: List[float] = field(default_factory=list)
    # CPU preprocessing
    cpu_prep_ms: List[float] = field(default_factory=list)
    # CPU postprocessing
    cpu_post_ms: List[float] = field(default_factory=list)
    
    def stats(self, name: str, data: List[float]) -> Dict[str, float]:
        if not data:
            return {}
        sorted_d = sorted(data)
        return {
            "name": name,
            "mean": sum(data) / len(data),
            "p50": sorted_d[len(sorted_d) // 2],
            "p95": sorted_d[int(len(sorted_d) * 0.95)],
            "p99": sorted_d[int(len(sorted_d) * 0.99)],
            "max": max(data),
            "count": len(data),
        }
    
    def report(self) -> Dict[str, Any]:
        return {
            "gpu_kernel": self.stats("gpu_kernel", self.gpu_kernel_ms),
            "cpu_host": self.stats("cpu_host", self.cpu_host_ms),
            "ort_enqueue": self.stats("ort_enqueue", self.ort_enqueue_ms),
            "cuda_sync": self.stats("cuda_sync", self.cuda_sync_ms),
            "h2d_transfer": self.stats("h2d_transfer", self.h2d_ms),
            "d2h_transfer": self.stats("d2h_transfer", self.d2h_ms),
            "cpu_preprocessing": self.stats("cpu_preprocessing", self.cpu_prep_ms),
            "cpu_postprocessing": self.stats("cpu_postprocessing", self.cpu_post_ms),
        }


def run_gpu_vs_host_analysis(num_frames: int = 50) -> Dict[str, Any]:
    """Run detailed GPU vs Host timing analysis."""
    logger.info("=" * 60)
    logger.info("SUBAGENT 2: GPU vs Host Time Analysis")
    logger.info("=" * 60)
    
    from app.vision.gpu_face_detector import create_gpu_face_detector
    from app.vision.gpu_preprocessing import GPUPreprocessor
    from app.vision.gpu_inference import GPUInferenceEngine
    from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
    
    detector = create_gpu_face_detector(
        model_id="scrfd",
        enable_gpu_path=True,
        fallback_to_cpu=False,
    )
    
    if not detector.gpu_available:
        logger.error("GPU not available")
        return {"error": "GPU not available"}
    
    # Create synthetic 4K frame
    synthetic_frame = np.random.randint(0, 255, (2160, 3840, 3), dtype=np.uint8)
    
    # CUDA events for precise GPU timing
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)
    
    timing = GPUTiming()
    
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
    
    logger.info(f"Running {num_frames} frames with CUDA event timing...")
    
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
        
        # ===== CPU PREPROCESSING (upload to GPU) =====
        cpu_prep_start = time.perf_counter()
        # This includes: CPU->GPU upload, color convert, resize, normalize, transpose
        gpu_prep_result = detector.gpu_preprocessor.preprocess(frame)
        cpu_prep_end = time.perf_counter()
        timing.cpu_prep_ms.append((cpu_prep_end - cpu_prep_start) * 1000)
        
        # ===== GPU INFERENCE with CUDA events =====
        # Record start event
        start_event.record()
        
        ort_enqueue_start = time.perf_counter()
        gpu_infer_result = detector.gpu_inference_engine.infer_gpu(gpu_prep_result.tensor)
        ort_enqueue_end = time.perf_counter()
        timing.ort_enqueue_ms.append((ort_enqueue_end - ort_enqueue_start) * 1000)
        
        # Record end event and synchronize
        end_event.record()
        torch.cuda.synchronize()
        
        # GPU kernel time from CUDA events
        gpu_kernel_ms = start_event.elapsed_time(end_event)
        timing.gpu_kernel_ms.append(gpu_kernel_ms)
        
        # ===== CPU POSTPROCESSING =====
        cpu_post_start = time.perf_counter()
        outputs = [out.numpy() for out in gpu_infer_result.outputs]  # D2H transfer
        d2h_end = time.perf_counter()
        timing.d2h_ms.append((d2h_end - cpu_post_start) * 1000)
        
        detections = detector._parse_outputs_gpu(
            outputs=outputs,
            gpu_prep_result=gpu_prep_result,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
        )
        detections = detector._apply_nms(detections)
        detections = [d for d in detections if d.confidence >= detector.confidence_threshold]
        cpu_post_end = time.perf_counter()
        timing.cpu_post_ms.append((cpu_post_end - d2h_end) * 1000)
        
        frame_end = time.perf_counter()
        total_frame_ms = (frame_end - frame_start) * 1000
        timing.cpu_host_ms.append(total_frame_ms - gpu_kernel_ms)
        
        if i % 10 == 0:
            logger.info(f"  Frame {i}: total={total_frame_ms:.1f}ms, "
                       f"GPU_kernel={gpu_kernel_ms:.1f}ms, "
                       f"CPU_host={total_frame_ms - gpu_kernel_ms:.1f}ms, "
                       f"ORT_enqueue={timing.ort_enqueue_ms[-1]:.1f}ms, "
                       f"CPU_prep={timing.cpu_prep_ms[-1]:.1f}ms, "
                       f"D2H={timing.d2h_ms[-1]:.1f}ms, "
                       f"CPU_post={timing.cpu_post_ms[-1]:.1f}ms")
    
    detector.close()
    
    report = timing.report()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("GPU vs HOST TIMING RESULTS")
    logger.info("=" * 60)
    for category, stats in report.items():
        if stats:
            logger.info(f"  {stats['name']:20s}: mean={stats['mean']:6.1f}ms, "
                       f"P50={stats['p50']:6.1f}ms, P95={stats['p95']:6.1f}ms, "
                       f"P99={stats['p99']:6.1f}ms")
    
    # Calculate percentages
    total_mean = sum(stats.get('mean', 0) for stats in report.values() if stats)
    logger.info(f"\n  Total mean frame time: {total_mean:.1f}ms")
    for category, stats in report.items():
        if stats and stats.get('mean', 0) > 0:
            pct = (stats['mean'] / total_mean) * 100
            logger.info(f"  {stats['name']:20s}: {pct:.1f}% of total")
    
    return report


if __name__ == "__main__":
    report = run_gpu_vs_host_analysis(50)
    
    # Save report
    reports_dir = Path("benchmark_results")
    reports_dir.mkdir(exist_ok=True)
    
    json_path = reports_dir / "PHASE_36K_SUBAGENT2_GPU_VS_HOST.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\nReport saved to {json_path}")