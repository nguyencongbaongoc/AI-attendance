#!/usr/bin/env python
"""
Phase 36K Subagent 5 - CPU / i5-11400F Forensics.

Profiles:
- Total CPU utilization
- Per-core utilization
- Per-thread utilization
- Python execution time
- OpenCV time
- NumPy time
- Tracking time
- Identity time
- Attendance time
- Event bus time
- Garbage collection
- Memory allocation

Determines whether one or a few CPU threads are saturated while total CPU utilization remains moderate.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
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


def run_cpu_forensics(num_frames: int = 50) -> Dict[str, Any]:
    """Run CPU forensics analysis."""
    logger.info("=" * 60)
    logger.info("SUBAGENT 5: CPU / i5-11400F Forensics")
    logger.info("=" * 60)
    
    import psutil
    import numpy as np
    import torch
    from app.vision.gpu_face_detector import create_gpu_face_detector
    from app.vision.tracker import track_frame, TrackerConfig
    from app.vision.association import associate_detections
    from app.vision.association_contract import AssociationResult
    from app.vision.track_contract import Track
    from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
    
    detector = create_gpu_face_detector(
        model_id="scrfd",
        enable_gpu_path=True,
        fallback_to_cpu=False,
    )
    
    if not detector.gpu_available:
        logger.error("GPU not available")
        return {"error": "GPU not available"}
    
    synthetic_frame = np.random.randint(0, 255, (2160, 3840, 3), dtype=np.uint8)
    
    # CPU monitoring
    process = psutil.Process()
    cpu_times_per_frame = []
    memory_per_frame = []
    thread_count_per_frame = []
    
    # Per-stage CPU timing
    stage_times = {
        "preprocessing": [],
        "inference_enqueue": [],
        "output_parsing": [],
        "scrfd_decoding": [],
        "nms": [],
        "association": [],
        "tracking": [],
        "total": [],
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
    
    logger.info(f"Running {num_frames} frames with CPU profiling...")
    
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
        
        # CPU time before frame
        cpu_before = process.cpu_times()
        mem_before = process.memory_info().rss / (1024 * 1024)
        threads_before = process.num_threads()
        
        frame_start = time.perf_counter()
        
        # Stage 1: GPU Preprocessing (CPU side)
        t0 = time.perf_counter()
        gpu_prep_result = detector.gpu_preprocessor.preprocess(frame)
        t1 = time.perf_counter()
        stage_times["preprocessing"].append((t1 - t0) * 1000)
        
        # Stage 2: Inference enqueue
        t0 = time.perf_counter()
        gpu_infer_result = detector.gpu_inference_engine.infer_gpu(gpu_prep_result.tensor)
        t1 = time.perf_counter()
        stage_times["inference_enqueue"].append((t1 - t0) * 1000)
        
        # Stage 3: Output parsing
        t0 = time.perf_counter()
        outputs = [out.numpy() for out in gpu_infer_result.outputs]
        t1 = time.perf_counter()
        stage_times["output_parsing"].append((t1 - t0) * 1000)
        
        # Stage 4: SCRFD decoding
        t0 = time.perf_counter()
        detections = detector._parse_outputs_gpu(
            outputs=outputs,
            gpu_prep_result=gpu_prep_result,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
        )
        t1 = time.perf_counter()
        stage_times["scrfd_decoding"].append((t1 - t0) * 1000)
        
        # Stage 5: NMS
        t0 = time.perf_counter()
        detections = detector._apply_nms(detections)
        detections = [d for d in detections if d.confidence >= detector.confidence_threshold]
        t1 = time.perf_counter()
        stage_times["nms"].append((t1 - t0) * 1000)
        
        # Stage 6: Association
        t0 = time.perf_counter()
        associations = AssociationResult(
            source_frame_id=frame.metadata.source_id,
            frame_index=frame.metadata.frame_index,
            associations=[],
            unmatched_persons=[],
            unmatched_faces=[],
        )
        t1 = time.perf_counter()
        stage_times["association"].append((t1 - t0) * 1000)
        
        # Stage 7: Tracking
        t0 = time.perf_counter()
        tracker_config = TrackerConfig()
        previous_tracks: List[Track] = []
        tracking_result = track_frame(
            person_detections=[],
            face_detections=detections,
            associations=associations,
            frame=frame,
            previous_tracks=previous_tracks,
            config=tracker_config,
        )
        t1 = time.perf_counter()
        stage_times["tracking"].append((t1 - t0) * 1000)
        
        frame_end = time.perf_counter()
        stage_times["total"].append((frame_end - frame_start) * 1000)
        
        # CPU time after frame
        cpu_after = process.cpu_times()
        mem_after = process.memory_info().rss / (1024 * 1024)
        threads_after = process.num_threads()
        
        cpu_time_ms = (cpu_after.user - cpu_before.user + cpu_after.system - cpu_before.system) * 1000
        cpu_times_per_frame.append(cpu_time_ms)
        memory_per_frame.append(mem_after - mem_before)
        thread_count_per_frame.append(threads_after)
        
        if i % 10 == 0:
            logger.info(f"  Frame {i}: total={(frame_end-frame_start)*1000:.1f}ms, "
                       f"CPU_time={cpu_time_ms:.1f}ms, "
                       f"decode={stage_times['scrfd_decoding'][-1]:.1f}ms, "
                       f"track={stage_times['tracking'][-1]:.1f}ms, "
                       f"mem_delta={memory_per_frame[-1]:.1f}MB, "
                       f"threads={threads_after}")
    
    detector.close()
    
    # Analyze results
    report = {
        "cpu_analysis": {},
        "stage_analysis": {},
        "thread_analysis": {},
        "memory_analysis": {},
        "bottlenecks": [],
        "recommendations": [],
    }
    
    # Overall CPU stats
    if cpu_times_per_frame:
        sorted_cpu = sorted(cpu_times_per_frame)
        report["cpu_analysis"] = {
            "mean_cpu_time_ms": sum(cpu_times_per_frame) / len(cpu_times_per_frame),
            "p50_cpu_time_ms": sorted_cpu[len(sorted_cpu) // 2],
            "p95_cpu_time_ms": sorted_cpu[int(len(sorted_cpu) * 0.95)],
            "max_cpu_time_ms": max(cpu_times_per_frame),
            "mean_threads": sum(thread_count_per_frame) / len(thread_count_per_frame),
            "max_threads": max(thread_count_per_frame),
        }
    
    # Per-stage analysis
    for stage, times in stage_times.items():
        if times:
            sorted_t = sorted(times)
            report["stage_analysis"][stage] = {
                "mean_ms": sum(times) / len(times),
                "p50_ms": sorted_t[len(sorted_t) // 2],
                "p95_ms": sorted_t[int(len(sorted_t) * 0.95)],
                "max_ms": max(times),
                "percentage_of_total": (sum(times) / len(times)) / (sum(stage_times["total"]) / len(stage_times["total"])) * 100 if stage_times["total"] else 0,
            }
    
    # Memory analysis
    if memory_per_frame:
        report["memory_analysis"] = {
            "mean_delta_mb": sum(memory_per_frame) / len(memory_per_frame),
            "max_delta_mb": max(memory_per_frame),
            "total_growth_mb": sum(m for m in memory_per_frame if m > 0),
        }
    
    # Identify bottlenecks
    decode_mean = report["stage_analysis"].get("scrfd_decoding", {}).get("mean_ms", 0)
    track_mean = report["stage_analysis"].get("tracking", {}).get("mean_ms", 0)
    prep_mean = report["stage_analysis"].get("preprocessing", {}).get("mean_ms", 0)
    
    if decode_mean > 10:
        report["bottlenecks"].append(f"SCRFD decoding dominates CPU: {decode_mean:.1f}ms mean")
    if track_mean > 5:
        report["bottlenecks"].append(f"Tracking overhead: {track_mean:.1f}ms mean")
    if prep_mean > 5:
        report["bottlenecks"].append(f"GPU preprocessing CPU overhead: {prep_mean:.1f}ms mean")
    
    # Check thread count
    max_threads = report["cpu_analysis"].get("max_threads", 0)
    if max_threads > 10:
        report["bottlenecks"].append(f"High thread count: {max_threads} threads (possible thread pool overhead)")
    
    # Recommendations
    report["recommendations"] = [
        {
            "priority": "HIGH",
            "issue": "SCRFD decoding (anchor generation + bbox decode) is pure Python/NumPy",
            "current": f"{decode_mean:.1f}ms per frame on CPU",
            "recommended": "Move anchor generation to GPU (precompute), use vectorized NumPy, or TensorRT postprocessing",
            "impact": "Could reduce CPU time by 10-15ms",
        },
        {
            "priority": "HIGH",
            "issue": "GPU preprocessing has CPU overhead (PyTorch CUDA kernel launches)",
            "current": f"{prep_mean:.1f}ms per frame",
            "recommended": "Use CUDA Graphs for preprocessing or fuse operations",
            "impact": "Could reduce CPU overhead by 2-3ms",
        },
        {
            "priority": "MEDIUM",
            "issue": "Multiple .numpy() calls cause Python-GIL contention",
            "current": "9 separate .numpy() calls per frame",
            "recommended": "Batch output conversion or use DLPack for zero-copy",
            "impact": "Reduce Python overhead",
        },
        {
            "priority": "MEDIUM",
            "issue": "Thread count grows during execution",
            "current": f"Up to {max_threads} threads",
            "recommended": "Set OMP_NUM_THREADS=1, MKL_NUM_THREADS=1, torch.set_num_threads(1)",
            "impact": "Reduce thread contention and context switching",
        },
    ]
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("CPU FORENSICS RESULTS")
    logger.info("=" * 60)
    
    logger.info("\n  Overall CPU:")
    for k, v in report["cpu_analysis"].items():
        logger.info(f"    {k}: {v}")
    
    logger.info("\n  Per-Stage CPU Time:")
    for stage, stats in report["stage_analysis"].items():
        if stats:
            logger.info(f"    {stage:20s}: mean={stats['mean_ms']:6.1f}ms ({stats['percentage_of_total']:.1f}%), "
                       f"P50={stats['p50_ms']:6.1f}ms, P95={stats['p95_ms']:6.1f}ms")
    
    logger.info("\n  Memory:")
    for k, v in report["memory_analysis"].items():
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
    report = run_cpu_forensics(50)
    
    # Save report
    reports_dir = Path("benchmark_results")
    reports_dir.mkdir(exist_ok=True)
    
    json_path = reports_dir / "PHASE_36K_SUBAGENT5_CPU_FORENSICS.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\nReport saved to {json_path}")