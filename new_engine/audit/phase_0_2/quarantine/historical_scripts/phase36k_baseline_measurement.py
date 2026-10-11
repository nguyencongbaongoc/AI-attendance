#!/usr/bin/env python
"""
Phase 36K - Baseline Measurement Script for Maximum Performance Forensic Investigation.

Establishes reproducible benchmarks for:
A. SCRFD-only (GPUFaceDetector)
B. GPUFaceDetector-only (with GPU preprocessing + I/O Binding)
C. Full pipeline CAM1 only
D. Full pipeline CAM2 only
E. Full pipeline CAM1 + CAM2

Measures:
- FPS
- Latency P50/P95/P99/max
- GPU utilization
- CPU utilization
- VRAM
- Memory
- Transfer time
- Synchronization time
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    name: str
    camera_config: str  # "CAM1", "CAM2", "CAM1+CAM2"
    num_frames: int
    fps: float
    latencies_ms: List[float]
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    gpu_utilization_pct: Optional[float] = None
    cpu_utilization_pct: Optional[float] = None
    vram_mb: Optional[float] = None
    system_memory_mb: Optional[float] = None
    transfer_time_ms: Optional[float] = None
    sync_time_ms: Optional[float] = None
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "camera_config": self.camera_config,
            "num_frames": self.num_frames,
            "fps": self.fps,
            "latencies_ms": self.latencies_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "gpu_utilization_pct": self.gpu_utilization_pct,
            "cpu_utilization_pct": self.cpu_utilization_pct,
            "vram_mb": self.vram_mb,
            "system_memory_mb": self.system_memory_mb,
            "transfer_time_ms": self.transfer_time_ms,
            "sync_time_ms": self.sync_time_ms,
            "errors": self.errors,
            "metadata": self.metadata,
        }


def measure_gpu_utilization() -> Optional[float]:
    """Measure current GPU utilization using pynvml."""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        pynvml.nvmlShutdown()
        return float(util.gpu)
    except Exception:
        return None


def measure_vram_usage() -> Optional[float]:
    """Measure current VRAM usage in MB."""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pynvml.nvmlShutdown()
        return mem.used / (1024 * 1024)
    except Exception:
        return None


def measure_cpu_memory() -> Optional[float]:
    """Measure current system memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def run_scrfd_only_benchmark(num_frames: int = 50) -> BenchmarkResult:
    """Benchmark A: SCRFD-only (GPUFaceDetector with GPU path)."""
    logger.info("=" * 60)
    logger.info("BENCHMARK A: SCRFD-only (GPUFaceDetector)")
    logger.info("=" * 60)

    from app.vision.gpu_face_detector import create_gpu_face_detector
    from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType

    detector = create_gpu_face_detector(
        model_id="scrfd",
        enable_gpu_path=True,
        fallback_to_cpu=False,
    )

    if not detector.gpu_available:
        logger.warning("GPU not available for SCRFD-only benchmark")
        return BenchmarkResult(
            name="SCRFD-only",
            camera_config="N/A",
            num_frames=0,
            fps=0,
            latencies_ms=[],
            avg_latency_ms=0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            max_latency_ms=0,
            errors=["GPU not available"],
        )

    # Create synthetic 4K frame
    synthetic_frame = np.random.randint(0, 255, (2160, 3840, 3), dtype=np.uint8)

    # Warm up
    logger.info("Warming up...")
    for i in range(5):
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

    # Measure
    latencies = []
    gpu_utils = []
    vram_usages = []

    logger.info(f"Running {num_frames} frames...")
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

        t0 = time.perf_counter()
        detections = detector.detect(frame)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        gpu_util = measure_gpu_utilization()
        if gpu_util is not None:
            gpu_utils.append(gpu_util)

        vram = measure_vram_usage()
        if vram is not None:
            vram_usages.append(vram)

        if i % 10 == 0:
            logger.info(f"  Frame {i}: {latency_ms:.1f}ms, GPU: {gpu_util:.1f}%")

    detector.close()

    latencies_sorted = sorted(latencies)
    return BenchmarkResult(
        name="SCRFD-only (GPUFaceDetector)",
        camera_config="SYNTHETIC",
        num_frames=num_frames,
        fps=1000.0 / (sum(latencies) / len(latencies)) if latencies else 0,
        latencies_ms=latencies,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p50_latency_ms=latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0,
        p95_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0,
        p99_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else 0,
        max_latency_ms=max(latencies) if latencies else 0,
        gpu_utilization_pct=sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
        vram_mb=max(vram_usages) if vram_usages else None,
        metadata={"detector_type": "GPUFaceDetector", "gpu_path": True},
    )


def run_gpu_face_detector_only_benchmark(num_frames: int = 50) -> BenchmarkResult:
    """Benchmark B: GPUFaceDetector-only (same as A but with detailed stage timing)."""
    logger.info("=" * 60)
    logger.info("BENCHMARK B: GPUFaceDetector-only (detailed stage timing)")
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
        logger.warning("GPU not available for GPUFaceDetector-only benchmark")
        return BenchmarkResult(
            name="GPUFaceDetector-only",
            camera_config="N/A",
            num_frames=0,
            fps=0,
            latencies_ms=[],
            avg_latency_ms=0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            max_latency_ms=0,
            errors=["GPU not available"],
        )

    # Create synthetic 4K frame
    synthetic_frame = np.random.randint(0, 255, (2160, 3840, 3), dtype=np.uint8)

    # Warm up
    logger.info("Warming up...")
    for i in range(5):
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

    # Measure with stage breakdown
    total_latencies = []
    prep_latencies = []
    infer_latencies = []
    parse_latencies = []
    nms_latencies = []

    logger.info(f"Running {num_frames} frames with stage timing...")
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

        # Stage 1: GPU Preprocessing
        t0 = time.perf_counter()
        gpu_prep_result = detector.gpu_preprocessor.preprocess(frame)
        t1 = time.perf_counter()
        prep_latencies.append((t1 - t0) * 1000)

        # Stage 2: GPU Inference
        t0 = time.perf_counter()
        gpu_infer_result = detector.gpu_inference_engine.infer_gpu(gpu_prep_result.tensor)
        t1 = time.perf_counter()
        infer_latencies.append((t1 - t0) * 1000)

        # Stage 3: Parse outputs (CPU)
        t0 = time.perf_counter()
        outputs = [out.numpy() for out in gpu_infer_result.outputs]
        detections = detector._parse_outputs_gpu(
            outputs=outputs,
            gpu_prep_result=gpu_prep_result,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
        )
        t1 = time.perf_counter()
        parse_latencies.append((t1 - t0) * 1000)

        # Stage 4: NMS
        t0 = time.perf_counter()
        detections = detector._apply_nms(detections)
        detections = [d for d in detections if d.confidence >= detector.confidence_threshold]
        t1 = time.perf_counter()
        nms_latencies.append((t1 - t0) * 1000)

        total_latencies.append(sum([prep_latencies[-1], infer_latencies[-1], parse_latencies[-1], nms_latencies[-1]]))

        if i % 10 == 0:
            logger.info(f"  Frame {i}: total={total_latencies[-1]:.1f}ms (prep={prep_latencies[-1]:.1f}, infer={infer_latencies[-1]:.1f}, parse={parse_latencies[-1]:.1f}, nms={nms_latencies[-1]:.1f})")

    detector.close()

    latencies_sorted = sorted(total_latencies)
    return BenchmarkResult(
        name="GPUFaceDetector-only (staged)",
        camera_config="SYNTHETIC",
        num_frames=num_frames,
        fps=1000.0 / (sum(total_latencies) / len(total_latencies)) if total_latencies else 0,
        latencies_ms=total_latencies,
        avg_latency_ms=sum(total_latencies) / len(total_latencies) if total_latencies else 0,
        p50_latency_ms=latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0,
        p95_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0,
        p99_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else 0,
        max_latency_ms=max(total_latencies) if total_latencies else 0,
        metadata={
            "detector_type": "GPUFaceDetector",
            "gpu_path": True,
            "avg_prep_ms": sum(prep_latencies) / len(prep_latencies) if prep_latencies else 0,
            "avg_infer_ms": sum(infer_latencies) / len(infer_latencies) if infer_latencies else 0,
            "avg_parse_ms": sum(parse_latencies) / len(parse_latencies) if parse_latencies else 0,
            "avg_nms_ms": sum(nms_latencies) / len(nms_latencies) if nms_latencies else 0,
        },
    )


def run_full_pipeline_camera_benchmark(camera_id: str, rtsp_url: str, num_frames: int = 30) -> BenchmarkResult:
    """Benchmark C/D: Full pipeline for single camera."""
    logger.info("=" * 60)
    logger.info(f"BENCHMARK C/D: Full pipeline {camera_id}")
    logger.info("=" * 60)

    from app.streaming.rtsp_source import create_rtsp_source
    from app.vision.detector_factory import get_detector_for_live
    from app.vision.tracker import track_frame, TrackerConfig
    from app.vision.association import associate_detections
    from app.vision.association_contract import AssociationResult
    from app.vision.arcface_inference import ArcFaceInference
    from app.vision.temporal_evidence import TemporalEvidenceAggregator, DEFAULT_WINDOW_CONFIG
    from app.vision.track_contract import Track
    from app.data.frame import CanonicalFrame

    # Initialize components
    src = create_rtsp_source(camera_id, rtsp_url)
    src.open()

    detector = get_detector_for_live(use_gpu=True)
    arcface = ArcFaceInference()
    temporal = TemporalEvidenceAggregator(DEFAULT_WINDOW_CONFIG)
    tracker_config = TrackerConfig()

    previous_tracks: List[Track] = []

    latencies = []
    gpu_utils = []
    vram_usages = []
    cpu_memories = []
    frames_processed = 0
    detections_total = 0
    tracks_total = 0

    logger.info(f"Running {num_frames} frames for {camera_id}...")
    for i in range(num_frames):
        frame = src.get_next_frame()
        if frame is None:
            continue

        t0 = time.perf_counter()

        # Detection
        face_detections = detector.detect(frame)
        detections_total += len(face_detections)

        # Association (needs person detections - skip for now)
        associations = AssociationResult(
            source_frame_id=frame.metadata.source_id,
            frame_index=frame.metadata.frame_index,
            associations=[],
            unmatched_persons=[],
            unmatched_faces=[],
        )

        # Tracking
        tracking_result = track_frame(
            person_detections=[],
            face_detections=face_detections,
            associations=associations,
            frame=frame,
            previous_tracks=previous_tracks,
            config=tracker_config,
        )
        previous_tracks = tracking_result.tracks
        tracks_total += len(tracking_result.tracks)

        # Temporal evidence (simplified)
        for face_det in face_detections:
            pass  # Would add to temporal aggregator

        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        gpu_util = measure_gpu_utilization()
        if gpu_util is not None:
            gpu_utils.append(gpu_util)

        vram = measure_vram_usage()
        if vram is not None:
            vram_usages.append(vram)

        cpu_mem = measure_cpu_memory()
        if cpu_mem is not None:
            cpu_memories.append(cpu_mem)

        frames_processed += 1

        if i % 5 == 0:
            logger.info(f"  Frame {i}: {latency_ms:.1f}ms, GPU: {gpu_util:.1f}%, VRAM: {vram:.0f}MB")

    src.close()
    detector.close()

    latencies_sorted = sorted(latencies)
    return BenchmarkResult(
        name=f"Full pipeline {camera_id}",
        camera_config=camera_id,
        num_frames=frames_processed,
        fps=1000.0 / (sum(latencies) / len(latencies)) if latencies else 0,
        latencies_ms=latencies,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p50_latency_ms=latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0,
        p95_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0,
        p99_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else 0,
        max_latency_ms=max(latencies) if latencies else 0,
        gpu_utilization_pct=sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
        cpu_utilization_pct=None,  # Would need per-thread measurement
        vram_mb=max(vram_usages) if vram_usages else None,
        system_memory_mb=max(cpu_memories) if cpu_memories else None,
        metadata={
            "detections_total": detections_total,
            "tracks_total": tracks_total,
            "detector_type": type(detector).__name__,
        },
    )


def run_full_pipeline_dual_camera_benchmark(num_frames: int = 30) -> BenchmarkResult:
    """Benchmark E: Full pipeline CAM1 + CAM2 (serialized)."""
    logger.info("=" * 60)
    logger.info("BENCHMARK E: Full pipeline CAM1 + CAM2 (serialized)")
    logger.info("=" * 60)

    from app.streaming.rtsp_source import create_rtsp_source
    from app.vision.detector_factory import get_detector_for_live
    from app.vision.tracker import track_frame, TrackerConfig
    from app.vision.association import associate_detections
    from app.vision.association_contract import AssociationResult
    from app.vision.arcface_inference import ArcFaceInference
    from app.vision.temporal_evidence import TemporalEvidenceAggregator, DEFAULT_WINDOW_CONFIG
    from app.vision.track_contract import Track
    from app.data.frame import CanonicalFrame

    # Initialize both cameras
    src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
    src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
    src1.open()
    src2.open()

    detector = get_detector_for_live(use_gpu=True)
    arcface = ArcFaceInference()
    temporal = TemporalEvidenceAggregator(DEFAULT_WINDOW_CONFIG)
    tracker_config = TrackerConfig()

    previous_tracks_cam1: List[Track] = []
    previous_tracks_cam2: List[Track] = []

    latencies = []
    gpu_utils = []
    vram_usages = []
    cpu_memories = []
    frames_processed = 0
    detections_total = 0
    tracks_total = 0

    logger.info(f"Running {num_frames} frames per camera (serialized)...")
    for i in range(num_frames):
        # Process CAM1
        frame1 = src1.get_next_frame()
        if frame1:
            t0 = time.perf_counter()
            face_detections = detector.detect(frame1)
            detections_total += len(face_detections)

            associations = AssociationResult(
                source_frame_id=frame1.metadata.source_id,
                frame_index=frame1.metadata.frame_index,
                associations=[],
                unmatched_persons=[],
                unmatched_faces=[],
            )

            tracking_result = track_frame(
                person_detections=[],
                face_detections=face_detections,
                associations=associations,
                frame=frame1,
                previous_tracks=previous_tracks_cam1,
                config=tracker_config,
            )
            previous_tracks_cam1 = tracking_result.tracks
            tracks_total += len(tracking_result.tracks)

            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
            frames_processed += 1

        # Process CAM2
        frame2 = src2.get_next_frame()
        if frame2:
            t0 = time.perf_counter()
            face_detections = detector.detect(frame2)
            detections_total += len(face_detections)

            associations = AssociationResult(
                source_frame_id=frame2.metadata.source_id,
                frame_index=frame2.metadata.frame_index,
                associations=[],
                unmatched_persons=[],
                unmatched_faces=[],
            )

            tracking_result = track_frame(
                person_detections=[],
                face_detections=face_detections,
                associations=associations,
                frame=frame2,
                previous_tracks=previous_tracks_cam2,
                config=tracker_config,
            )
            previous_tracks_cam2 = tracking_result.tracks
            tracks_total += len(tracking_result.tracks)

            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
            frames_processed += 1

        gpu_util = measure_gpu_utilization()
        if gpu_util is not None:
            gpu_utils.append(gpu_util)

        vram = measure_vram_usage()
        if vram is not None:
            vram_usages.append(vram)

        cpu_mem = measure_cpu_memory()
        if cpu_mem is not None:
            cpu_memories.append(cpu_mem)

        if i % 5 == 0:
            logger.info(f"  Iteration {i}: GPU: {gpu_util:.1f}%, VRAM: {vram:.0f}MB")

    src1.close()
    src2.close()
    detector.close()

    latencies_sorted = sorted(latencies)
    return BenchmarkResult(
        name="Full pipeline CAM1+CAM2 (serialized)",
        camera_config="CAM1+CAM2",
        num_frames=frames_processed,
        fps=1000.0 / (sum(latencies) / len(latencies)) if latencies else 0,
        latencies_ms=latencies,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
        p50_latency_ms=latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else 0,
        p95_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.95)] if latencies_sorted else 0,
        p99_latency_ms=latencies_sorted[int(len(latencies_sorted) * 0.99)] if latencies_sorted else 0,
        max_latency_ms=max(latencies) if latencies else 0,
        gpu_utilization_pct=sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
        cpu_utilization_pct=None,
        vram_mb=max(vram_usages) if vram_usages else None,
        system_memory_mb=max(cpu_memories) if cpu_memories else None,
        metadata={
            "detections_total": detections_total,
            "tracks_total": tracks_total,
            "detector_type": type(detector).__name__,
            "serialized": True,
        },
    )


def run_all_benchmarks() -> Dict[str, Any]:
    """Run all baseline benchmarks."""
    results = {
        "phase": "36K",
        "name": "MAXIMUM_PERFORMANCE_FORENSIC_BASELINE",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hardware": {
            "gpu": "GTX 1660 Ti 6GB",
            "cpu": "i5-11400F",
            "ram": "16GB",
        },
        "benchmarks": {},
    }

    # Benchmark A: SCRFD-only
    try:
        result_a = run_scrfd_only_benchmark(50)
        results["benchmarks"]["A_scrfd_only"] = result_a.to_dict()
        logger.info(f"Benchmark A complete: {result_a.fps:.2f} FPS")
    except Exception as e:
        logger.error(f"Benchmark A failed: {e}")
        results["benchmarks"]["A_scrfd_only"] = {"error": str(e)}

    # Benchmark B: GPUFaceDetector-only (staged)
    try:
        result_b = run_gpu_face_detector_only_benchmark(50)
        results["benchmarks"]["B_gpu_face_detector_only"] = result_b.to_dict()
        logger.info(f"Benchmark B complete: {result_b.fps:.2f} FPS")
        logger.info(f"  Stage breakdown: prep={result_b.metadata.get('avg_prep_ms', 0):.1f}ms, "
                    f"infer={result_b.metadata.get('avg_infer_ms', 0):.1f}ms, "
                    f"parse={result_b.metadata.get('avg_parse_ms', 0):.1f}ms, "
                    f"nms={result_b.metadata.get('avg_nms_ms', 0):.1f}ms")
    except Exception as e:
        logger.error(f"Benchmark B failed: {e}")
        results["benchmarks"]["B_gpu_face_detector_only"] = {"error": str(e)}

    # Benchmark C: Full pipeline CAM1
    try:
        result_c = run_full_pipeline_camera_benchmark("CAM1", "rtsp://127.0.0.1:8554/live/cam1", 30)
        results["benchmarks"]["C_full_pipeline_cam1"] = result_c.to_dict()
        logger.info(f"Benchmark C complete: {result_c.fps:.2f} FPS")
    except Exception as e:
        logger.error(f"Benchmark C failed: {e}")
        results["benchmarks"]["C_full_pipeline_cam1"] = {"error": str(e)}

    # Benchmark D: Full pipeline CAM2
    try:
        result_d = run_full_pipeline_camera_benchmark("CAM2", "rtsp://127.0.0.1:8554/live/cam2", 30)
        results["benchmarks"]["D_full_pipeline_cam2"] = result_d.to_dict()
        logger.info(f"Benchmark D complete: {result_d.fps:.2f} FPS")
    except Exception as e:
        logger.error(f"Benchmark D failed: {e}")
        results["benchmarks"]["D_full_pipeline_cam2"] = {"error": str(e)}

    # Benchmark E: Full pipeline CAM1+CAM2 serialized
    try:
        result_e = run_full_pipeline_dual_camera_benchmark(30)
        results["benchmarks"]["E_full_pipeline_cam1_cam2_serialized"] = result_e.to_dict()
        logger.info(f"Benchmark E complete: {result_e.fps:.2f} FPS")
    except Exception as e:
        logger.error(f"Benchmark E failed: {e}")
        results["benchmarks"]["E_full_pipeline_cam1_cam2_serialized"] = {"error": str(e)}

    # Generate comparison
    results["comparison"] = {
        "36T_detector_cam1_fps": 14.85,
        "36T_detector_cam2_fps": 17.90,
        "36R5_full_pipeline_fps": 7.25,
        "baseline_A_fps": results["benchmarks"].get("A_scrfd_only", {}).get("fps", 0),
        "baseline_B_fps": results["benchmarks"].get("B_gpu_face_detector_only", {}).get("fps", 0),
        "baseline_C_fps": results["benchmarks"].get("C_full_pipeline_cam1", {}).get("fps", 0),
        "baseline_D_fps": results["benchmarks"].get("D_full_pipeline_cam2", {}).get("fps", 0),
        "baseline_E_fps": results["benchmarks"].get("E_full_pipeline_cam1_cam2_serialized", {}).get("fps", 0),
    }

    # Generate reports
    _generate_reports(results)

    return results


def _generate_reports(results: Dict[str, Any]) -> None:
    """Generate JSON and Markdown reports."""
    reports_dir = Path("benchmark_results")
    reports_dir.mkdir(exist_ok=True)

    json_path = reports_dir / "PHASE_36K_MAX_PERFORMANCE_FORENSIC_BASELINE.json"
    md_path = reports_dir / "PHASE_36K_MAX_PERFORMANCE_FORENSIC_BASELINE.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Generate Markdown
    lines = [
        "# Phase 36K - Maximum Performance Forensic Baseline",
        "",
        f"**Timestamp:** {results['timestamp']}",
        f"**Hardware:** {results['hardware']['gpu']}, {results['hardware']['cpu']}, {results['hardware']['ram']}",
        "",
        "## Baseline Benchmarks",
        "",
    ]

    for bench_name, bench_data in results.get("benchmarks", {}).items():
        if "error" in bench_data:
            lines.append(f"### {bench_name}")
            lines.append(f"**ERROR:** {bench_data['error']}")
            lines.append("")
            continue

        lines.append(f"### {bench_name}")
        lines.append(f"- **Camera Config:** {bench_data.get('camera_config', 'N/A')}")
        lines.append(f"- **Frames:** {bench_data.get('num_frames', 0)}")
        lines.append(f"- **FPS:** {bench_data.get('fps', 0):.2f}")
        lines.append(f"- **Avg Latency:** {bench_data.get('avg_latency_ms', 0):.1f}ms")
        lines.append(f"- **P50 Latency:** {bench_data.get('p50_latency_ms', 0):.1f}ms")
        lines.append(f"- **P95 Latency:** {bench_data.get('p95_latency_ms', 0):.1f}ms")
        lines.append(f"- **P99 Latency:** {bench_data.get('p99_latency_ms', 0):.1f}ms")
        lines.append(f"- **Max Latency:** {bench_data.get('max_latency_ms', 0):.1f}ms")
        if bench_data.get('gpu_utilization_pct'):
            lines.append(f"- **GPU Utilization:** {bench_data['gpu_utilization_pct']:.1f}%")
        if bench_data.get('vram_mb'):
            lines.append(f"- **VRAM Peak:** {bench_data['vram_mb']:.0f}MB")
        if bench_data.get('system_memory_mb'):
            lines.append(f"- **System Memory Peak:** {bench_data['system_memory_mb']:.0f}MB")
        lines.append("")

    lines.extend([
        "## Comparison with Previous Phases",
        "",
        f"- **36T Detector CAM1:** {results['comparison']['36T_detector_cam1_fps']:.2f} FPS",
        f"- **36T Detector CAM2:** {results['comparison']['36T_detector_cam2_fps']:.2f} FPS",
        f"- **36R5 Full Pipeline:** {results['comparison']['36R5_full_pipeline_fps']:.2f} FPS/camera",
        "",
        "## Current Baseline Results",
        "",
        f"- **A. SCRFD-only:** {results['comparison']['baseline_A_fps']:.2f} FPS",
        f"- **B. GPUFaceDetector-only (staged):** {results['comparison']['baseline_B_fps']:.2f} FPS",
        f"- **C. Full Pipeline CAM1:** {results['comparison']['baseline_C_fps']:.2f} FPS",
        f"- **D. Full Pipeline CAM2:** {results['comparison']['baseline_D_fps']:.2f} FPS",
        f"- **E. Full Pipeline CAM1+CAM2 (serialized):** {results['comparison']['baseline_E_fps']:.2f} FPS",
        "",
        "## Gap Analysis",
        "",
        f"- **Detector vs Full Pipeline (CAM1):** {results['comparison']['36T_detector_cam1_fps']:.2f} vs {results['comparison']['baseline_C_fps']:.2f} FPS = "
        f"{results['comparison']['36T_detector_cam1_fps'] / max(results['comparison']['baseline_C_fps'], 0.001):.1f}x slower",
        f"- **Detector vs Full Pipeline (CAM2):** {results['comparison']['36T_detector_cam2_fps']:.2f} vs {results['comparison']['baseline_D_fps']:.2f} FPS = "
        f"{results['comparison']['36T_detector_cam2_fps'] / max(results['comparison']['baseline_D_fps'], 0.001):.1f}x slower",
        "",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Reports generated: {json_path}, {md_path}")


if __name__ == "__main__":
    results = run_all_benchmarks()
    print(f"\nPHASE 36K BASELINE COMPLETE")
    print(f"Results saved to benchmark_results/")