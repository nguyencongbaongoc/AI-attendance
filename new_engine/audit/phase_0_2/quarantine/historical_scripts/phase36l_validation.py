#!/usr/bin/env python3
"""
Phase 36L: Accuracy Validation and Performance A/B Testing
Validates the best optimization configuration against baseline.
"""

import os
import sys
import time
import json
import numpy as np
import cv2
import torch
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, asdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.vision.gpu_face_detector import create_gpu_face_detector
from app.vision.gpu_preprocessing import create_gpu_preprocessor
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType


@dataclass
class ValidationResult:
    """Results from accuracy validation."""
    config_name: str
    baseline_detections: List[Dict]
    optimized_detections: List[Dict]
    detection_count_match: bool
    bbox_max_diff: float
    confidence_max_diff: float
    landmarks_max_diff: float
    passed: bool


def create_canonical_frame(frame: np.ndarray, frame_index: int = 0) -> CanonicalFrame:
    """Create a CanonicalFrame from numpy array."""
    metadata = FrameMetadata(
        frame_index=frame_index,
        timestamp=0.0,
        source_id="validation",
        source_type=SourceType.VIDEO,
        original_width=frame.shape[1],
        original_height=frame.shape[0],
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
    )
    return CanonicalFrame(data=frame, metadata=metadata)


def detections_to_dict(detections) -> List[Dict]:
    """Convert FaceDetection objects to dictionaries for comparison."""
    result = []
    for det in detections:
        result.append({
            "bbox": det.bbox,
            "confidence": det.confidence,
            "landmarks5": det.landmarks5,
        })
    return result


def compare_detections(baseline: List[Dict], optimized: List[Dict], iou_threshold: float = 0.5) -> Tuple[bool, Dict]:
    """Compare two sets of detections."""
    details = {
        "baseline_count": len(baseline),
        "optimized_count": len(optimized),
        "count_match": len(baseline) == len(optimized),
        "bbox_max_diff": 0.0,
        "confidence_max_diff": 0.0,
        "landmarks_max_diff": 0.0,
        "matched_pairs": 0,
    }
    
    if len(baseline) != len(optimized):
        details["error"] = f"Detection count mismatch: {len(baseline)} vs {len(optimized)}"
        return False, details
    
    # Sort by confidence for consistent matching
    baseline_sorted = sorted(baseline, key=lambda x: x["confidence"], reverse=True)
    optimized_sorted = sorted(optimized, key=lambda x: x["confidence"], reverse=True)
    
    max_bbox_diff = 0.0
    max_conf_diff = 0.0
    max_lm_diff = 0.0
    matched = 0
    
    for b, o in zip(baseline_sorted, optimized_sorted):
        # Compare bbox
        bbox_diff = np.max(np.abs(np.array(b["bbox"]) - np.array(o["bbox"])))
        max_bbox_diff = max(max_bbox_diff, bbox_diff)
        
        # Compare confidence
        conf_diff = abs(b["confidence"] - o["confidence"])
        max_conf_diff = max(max_conf_diff, conf_diff)
        
        # Compare landmarks
        lm_diff = np.max(np.abs(np.array(b["landmarks5"]) - np.array(o["landmarks5"])))
        max_lm_diff = max(max_lm_diff, lm_diff)
        
        matched += 1
    
    details["bbox_max_diff"] = float(max_bbox_diff)
    details["confidence_max_diff"] = float(max_conf_diff)
    details["landmarks_max_diff"] = float(max_lm_diff)
    details["matched_pairs"] = matched
    
    # Pass if all diffs are within tolerance
    passed = (max_bbox_diff <= 1e-3 and 
              max_conf_diff <= 1e-3 and 
              max_lm_diff <= 1e-3)
    
    return passed, details


def run_accuracy_validation():
    """Run accuracy validation comparing baseline vs optimized."""
    print("="*60)
    print("PHASE 36L: ACCURACY VALIDATION")
    print("="*60)
    
    # Load test frames
    test_frames = []
    test_dir = Path("test_data")
    if test_dir.exists():
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
            for img_path in test_dir.glob(ext):
                frame = cv2.imread(str(img_path))
                if frame is not None:
                    test_frames.append(frame)
    if not test_frames:
        for i in range(10):
            frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
            test_frames.append(frame)
    test_frames = test_frames[:10]
    
    # Create baseline detector (no optimizations)
    print("Creating baseline detector...")
    baseline_detector = create_gpu_face_detector(
        model_id="scrfd",
        device_id=0,
        enable_gpu_path=True,
        fallback_to_cpu=True,
        precompute_anchors=False,
        vectorized_decode=False,
        reuse_ortvalues=False,
        reuse_io_binding=False,
        no_unnecessary_sync=False,
    )
    
    # Create optimized detector (best config: H_Combined_CD)
    print("Creating optimized detector (H_Combined_CD)...")
    optimized_detector = create_gpu_face_detector(
        model_id="scrfd",
        device_id=0,
        enable_gpu_path=True,
        fallback_to_cpu=True,  # Enable fallback for validation
        precompute_anchors=True,
        vectorized_decode=True,
    )
    import torch
    optimized_detector.gpu_preprocessor = create_gpu_preprocessor(
        model_id="scrfd",
        device=torch.device("cuda:0"),
        reuse_buffers=True,
    )
    
    results = []
    
    for i, frame in enumerate(test_frames):
        print(f"\nValidating frame {i+1}/{len(test_frames)}...")
        canonical_frame = create_canonical_frame(frame, i)
        
        # Run baseline
        baseline_dets = baseline_detector.detect(canonical_frame)
        baseline_dict = detections_to_dict(baseline_dets)
        
        # Run optimized
        optimized_dets = optimized_detector.detect(canonical_frame)
        optimized_dict = detections_to_dict(optimized_dets)
        
        # Compare
        passed, details = compare_detections(baseline_dict, optimized_dict)
        
        result = ValidationResult(
            config_name=f"frame_{i}",
            baseline_detections=baseline_dict,
            optimized_detections=optimized_dict,
            detection_count_match=details["count_match"],
            bbox_max_diff=details["bbox_max_diff"],
            confidence_max_diff=details["confidence_max_diff"],
            landmarks_max_diff=details["landmarks_max_diff"],
            passed=passed,
        )
        results.append(result)
        
        print(f"  Baseline: {len(baseline_dict)} detections")
        print(f"  Optimized: {len(optimized_dict)} detections")
        print(f"  Count match: {details['count_match']}")
        print(f"  Bbox max diff: {details['bbox_max_diff']:.6f}")
        print(f"  Confidence max diff: {details['confidence_max_diff']:.6f}")
        print(f"  Landmarks max diff: {details['landmarks_max_diff']:.6f}")
        print(f"  PASSED: {passed}")
    
    # Summary
    all_passed = all(r.passed for r in results)
    print(f"\n{'='*60}")
    print("ACCURACY VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Frames tested: {len(results)}")
    print(f"All passed: {all_passed}")
    
    if all_passed:
        max_bbox = max(r.bbox_max_diff for r in results)
        max_conf = max(r.confidence_max_diff for r in results)
        max_lm = max(r.landmarks_max_diff for r in results)
        print(f"Max bbox diff: {max_bbox:.6f}")
        print(f"Max confidence diff: {max_conf:.6f}")
        print(f"Max landmarks diff: {max_lm:.6f}")
    
    # Save results
    output_path = "benchmark_results/PHASE_36L_ACCURACY_VALIDATION.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    data = {
        "all_passed": all_passed,
        "frames_tested": len(results),
        "results": [asdict(r) for r in results]
    }
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {output_path}")
    
    return all_passed


def run_performance_ab_test():
    """Run performance A/B test: baseline vs best optimized."""
    print("\n" + "="*60)
    print("PHASE 36L: PERFORMANCE A/B TEST")
    print("="*60)
    
    # Load test frames
    test_frames = []
    test_dir = Path("test_data")
    if test_dir.exists():
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
            for img_path in test_dir.glob(ext):
                frame = cv2.imread(str(img_path))
                if frame is not None:
                    test_frames.append(frame)
    if not test_frames:
        for i in range(20):
            frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
            test_frames.append(frame)
    test_frames = test_frames[:20]
    
    # Create baseline detector
    print("Creating baseline detector...")
    baseline_detector = create_gpu_face_detector(
        model_id="scrfd",
        device_id=0,
        enable_gpu_path=True,
        fallback_to_cpu=True,
        precompute_anchors=False,
        vectorized_decode=False,
        reuse_ortvalues=False,
        reuse_io_binding=False,
        no_unnecessary_sync=False,
    )
    
    # Create optimized detector (best config)
    print("Creating optimized detector (H_Combined_CD)...")
    optimized_detector = create_gpu_face_detector(
        model_id="scrfd",
        device_id=0,
        enable_gpu_path=True,
        fallback_to_cpu=True,  # Enable fallback for performance test
        precompute_anchors=True,
        vectorized_decode=True,
    )
    import torch
    optimized_detector.gpu_preprocessor = create_gpu_preprocessor(
        model_id="scrfd",
        device=torch.device("cuda:0"),
        reuse_buffers=True,
    )
    
    # Warmup
    print("Warming up...")
    for i in range(10):
        frame = test_frames[i % len(test_frames)]
        canonical_frame = create_canonical_frame(frame, i)
        _ = baseline_detector.detect(canonical_frame)
        _ = optimized_detector.detect(canonical_frame)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
    
    # Measure baseline
    print("Measuring baseline (100 iterations)...")
    baseline_latencies = []
    for i in range(100):
        frame = test_frames[i % len(test_frames)]
        canonical_frame = create_canonical_frame(frame, i)
        
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        start = time.perf_counter()
        _ = baseline_detector.detect(canonical_frame)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        end = time.perf_counter()
        
        baseline_latencies.append((end - start) * 1000)
    
    # Measure optimized
    print("Measuring optimized (100 iterations)...")
    optimized_latencies = []
    for i in range(100):
        frame = test_frames[i % len(test_frames)]
        canonical_frame = create_canonical_frame(frame, i)
        
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        start = time.perf_counter()
        _ = optimized_detector.detect(canonical_frame)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        end = time.perf_counter()
        
        optimized_latencies.append((end - start) * 1000)
    
    # Statistics
    baseline_latencies = np.array(baseline_latencies)
    optimized_latencies = np.array(optimized_latencies)
    
    baseline_median = float(np.median(baseline_latencies))
    baseline_mean = float(np.mean(baseline_latencies))
    baseline_p95 = float(np.percentile(baseline_latencies, 95))
    baseline_fps = 1000.0 / baseline_median
    
    optimized_median = float(np.median(optimized_latencies))
    optimized_mean = float(np.mean(optimized_latencies))
    optimized_p95 = float(np.percentile(optimized_latencies, 95))
    optimized_fps = 1000.0 / optimized_median
    
    speedup = baseline_median / optimized_median
    fps_improvement = (optimized_fps - baseline_fps) / baseline_fps * 100
    
    print(f"\n{'='*60}")
    print("PERFORMANCE A/B TEST RESULTS")
    print(f"{'='*60}")
    print(f"Baseline (no optimizations):")
    print(f"  Median: {baseline_median:.2f}ms, Mean: {baseline_mean:.2f}ms, P95: {baseline_p95:.2f}ms")
    print(f"  FPS: {baseline_fps:.2f}")
    print(f"\nOptimized (H_Combined_CD):")
    print(f"  Median: {optimized_median:.2f}ms, Mean: {optimized_mean:.2f}ms, P95: {optimized_p95:.2f}ms")
    print(f"  FPS: {optimized_fps:.2f}")
    print(f"\nImprovement:")
    print(f"  Speedup: {speedup:.2f}x")
    print(f"  FPS improvement: {fps_improvement:.1f}%")
    print(f"  Latency reduction: {(1 - optimized_median/baseline_median)*100:.1f}%")
    
    # Save results
    output_path = "benchmark_results/PHASE_36L_PERFORMANCE_AB_TEST.json"
    data = {
        "baseline": {
            "median_ms": baseline_median,
            "mean_ms": baseline_mean,
            "p95_ms": baseline_p95,
            "fps": baseline_fps,
            "latencies_ms": baseline_latencies.tolist(),
        },
        "optimized": {
            "median_ms": optimized_median,
            "mean_ms": optimized_mean,
            "p95_ms": optimized_p95,
            "fps": optimized_fps,
            "latencies_ms": optimized_latencies.tolist(),
        },
        "improvement": {
            "speedup": speedup,
            "fps_improvement_pct": fps_improvement,
            "latency_reduction_pct": (1 - optimized_median/baseline_median)*100,
        }
    }
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {output_path}")
    
    return speedup, fps_improvement


def main():
    """Main entry point."""
    print("="*60)
    print("PHASE 36L: VALIDATION AND A/B TESTING")
    print("="*60)
    
    # Run accuracy validation
    accuracy_passed = run_accuracy_validation()
    
    # Run performance A/B test
    speedup, fps_improvement = run_performance_ab_test()
    
    # Final verdict
    print(f"\n{'='*60}")
    print("PHASE 36L FINAL VERDICT")
    print(f"{'='*60}")
    print(f"Accuracy Validation: {'PASS' if accuracy_passed else 'FAIL'}")
    print(f"Performance Speedup: {speedup:.2f}x")
    print(f"FPS Improvement: {fps_improvement:.1f}%")
    
    if accuracy_passed and speedup >= 2.0:
        print("\nVERDICT: PASS - Optimization meets all criteria")
        return 0
    elif accuracy_passed and speedup >= 1.5:
        print("\nVERDICT: PASS_WITH_DOCUMENTED_LIMITATION - Good speedup but below 2x target")
        return 0
    else:
        print("\nVERDICT: FAIL - Does not meet criteria")
        return 1


if __name__ == "__main__":
    sys.exit(main())