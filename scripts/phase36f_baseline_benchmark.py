"""
Phase 36F - Baseline CPU Path Benchmark

This script benchmarks the current CPU/NumPy preprocessing path for SCRFD.
"""

import time
import statistics
import numpy as np
import cv2
from pathlib import Path

from app.data.input_adapter import ImageAdapter
from app.data.preprocessing import UnifiedPreprocessor
from app.vision.scrfd_adapter import create_scrfd_adapter
from app.vision.detector_contract import FaceDetectorInterface


def benchmark_preprocessing(frames, model_id="scrfd", iterations=100):
    """Benchmark preprocessing only."""
    preprocessor = UnifiedPreprocessor(model_id)
    
    # Warmup
    for frame in frames[:5]:
        _ = preprocessor.preprocess(frame)
    
    latencies = []
    for _ in range(iterations):
        for frame in frames:
            t0 = time.perf_counter()
            result = preprocessor.preprocess(frame)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
    
    return latencies


def benchmark_scrfd_inference(frames, iterations=100):
    """Benchmark SCRFD inference with current CPU path."""
    detector = create_scrfd_adapter(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    
    # Warmup
    for frame in frames[:5]:
        _ = detector.detect(frame)
    
    latencies = []
    for _ in range(iterations):
        for frame in frames:
            t0 = time.perf_counter()
            detections = detector.detect(frame)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
    
    return latencies


def benchmark_full_pipeline(frames, iterations=50):
    """Benchmark full pipeline: preprocessing + inference."""
    preprocessor = UnifiedPreprocessor("scrfd")
    detector = create_scrfd_adapter(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    
    # Warmup
    for frame in frames[:5]:
        prep_result = preprocessor.preprocess(frame)
        _ = detector.detect(frame)
    
    latencies = []
    for _ in range(iterations):
        for frame in frames:
            t0 = time.perf_counter()
            prep_result = preprocessor.preprocess(frame)
            detections = detector.detect(frame)
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
    
    return latencies


def print_stats(name, latencies):
    """Print latency statistics."""
    if not latencies:
        print(f"{name}: No data")
        return
    
    latencies = np.array(latencies)
    print(f"\n{name}:")
    print(f"  Count: {len(latencies)}")
    print(f"  Mean: {np.mean(latencies):.2f} ms")
    print(f"  Median: {np.median(latencies):.2f} ms")
    print(f"  P50: {np.percentile(latencies, 50):.2f} ms")
    print(f"  P95: {np.percentile(latencies, 95):.2f} ms")
    print(f"  P99: {np.percentile(latencies, 99):.2f} ms")
    print(f"  Min: {np.min(latencies):.2f} ms")
    print(f"  Max: {np.max(latencies):.2f} ms")
    print(f"  Std: {np.std(latencies):.2f} ms")


def main():
    print("=" * 60)
    print("Phase 36F - Baseline CPU Path Benchmark")
    print("=" * 60)
    
    # Load test frames
    adapter = ImageAdapter()
    test_frames = []
    
    # Use the saved frame
    frame_path = Path("test_data/phase20/first_frame_cam1.jpg")
    if frame_path.exists():
        frame = adapter.load(frame_path)
        test_frames.append(frame)
        print(f"Loaded test frame: {frame.data.shape}, {frame.metadata.pixel_format}")
    
    # Also load from video
    from app.data.input_adapter import VideoAdapter
    video_adapter = VideoAdapter()
    for frame in video_adapter.iter_frames("test_data/phase20/cam1_short.mp4"):
        test_frames.append(frame)
        if len(test_frames) >= 10:
            break
    
    print(f"Total test frames: {len(test_frames)}")
    
    # Benchmark preprocessing
    print("\n--- Preprocessing Benchmark ---")
    prep_latencies = benchmark_preprocessing(test_frames, iterations=50)
    print_stats("Preprocessing (SCRFD 640x640 letterbox)", prep_latencies)
    
    # Benchmark SCRFD inference
    print("\n--- SCRFD Inference Benchmark ---")
    infer_latencies = benchmark_scrfd_inference(test_frames, iterations=50)
    print_stats("SCRFD Inference (CUDA EP)", infer_latencies)
    
    # Benchmark full pipeline
    print("\n--- Full Pipeline Benchmark ---")
    full_latencies = benchmark_full_pipeline(test_frames, iterations=30)
    print_stats("Full Pipeline (Preprocess + Inference)", full_latencies)
    
    # Calculate FPS
    mean_full = np.mean(full_latencies)
    fps = 1000 / mean_full if mean_full > 0 else 0
    print(f"\nEstimated FPS: {fps:.2f}")
    
    # Save results
    import json
    results = {
        "phase": "36F_baseline",
        "test_frames": len(test_frames),
        "preprocessing": {
            "mean_ms": float(np.mean(prep_latencies)),
            "median_ms": float(np.median(prep_latencies)),
            "p50_ms": float(np.percentile(prep_latencies, 50)),
            "p95_ms": float(np.percentile(prep_latencies, 95)),
            "p99_ms": float(np.percentile(prep_latencies, 99)),
            "min_ms": float(np.min(prep_latencies)),
            "max_ms": float(np.max(prep_latencies)),
            "std_ms": float(np.std(prep_latencies)),
        },
        "inference": {
            "mean_ms": float(np.mean(infer_latencies)),
            "median_ms": float(np.median(infer_latencies)),
            "p50_ms": float(np.percentile(infer_latencies, 50)),
            "p95_ms": float(np.percentile(infer_latencies, 95)),
            "p99_ms": float(np.percentile(infer_latencies, 99)),
            "min_ms": float(np.min(infer_latencies)),
            "max_ms": float(np.max(infer_latencies)),
            "std_ms": float(np.std(infer_latencies)),
        },
        "full_pipeline": {
            "mean_ms": float(np.mean(full_latencies)),
            "median_ms": float(np.median(full_latencies)),
            "p50_ms": float(np.percentile(full_latencies, 50)),
            "p95_ms": float(np.percentile(full_latencies, 95)),
            "p99_ms": float(np.percentile(full_latencies, 99)),
            "min_ms": float(np.min(full_latencies)),
            "max_ms": float(np.max(full_latencies)),
            "std_ms": float(np.std(full_latencies)),
            "fps": float(fps),
        }
    }
    
    output_path = Path("benchmark_results/PHASE_36F_BASELINE_CPU.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()