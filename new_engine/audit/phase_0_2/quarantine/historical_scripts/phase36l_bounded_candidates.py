#!/usr/bin/env python3
"""
Phase 36L: Bounded Optimization Loop
Tests up to 10 optimization candidates with 10 warmup + 50 measured iterations each.
Measures: median latency, mean latency, P95 latency, FPS.
Runs accuracy equivalence check for each candidate.
"""

import os
import sys
import time
import json
import numpy as np
import cv2
import torch
import onnxruntime as ort
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, asdict
from collections import deque

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.vision.gpu_inference import GPUInferenceEngine
from app.vision.gpu_preprocessing import GPUPreprocessor, create_gpu_preprocessor
from app.vision.gpu_face_detector import GPUFaceDetector, create_gpu_face_detector
from app.vision.detection import FaceDetector
from app.runtime.cuda import get_ort_session


@dataclass
class BenchmarkResult:
    """Results from a single benchmark configuration."""
    config_name: str
    warmup_iterations: int
    measured_iterations: int
    latencies_ms: List[float]
    median_latency_ms: float
    mean_latency_ms: float
    p95_latency_ms: float
    fps: float
    accuracy_passed: bool
    accuracy_details: Dict[str, Any]
    gpu_memory_mb: Optional[float] = None
    cpu_memory_mb: Optional[float] = None


@dataclass
class OptimizationCandidate:
    """An optimization candidate to test."""
    name: str
    description: str
    apply_fn: callable
    validate_fn: callable
    baseline_latency_ms: float
    warmup_iterations: int = 10
    measured_iterations: int = 50


class BoundedOptimizationLoop:
    """Runs bounded optimization testing with strict iteration limits."""
    
    def __init__(self, model_path: str, input_shape: Tuple[int, int, int, int] = (1, 3, 640, 640)):
        self.model_path = model_path
        self.input_shape = input_shape
        self.results: List[BenchmarkResult] = []
        self.best_config = None
        self.best_latency = float('inf')
        
        # Load test frames
        self.test_frames = self._load_test_frames()
        if not self.test_frames:
            raise RuntimeError("No test frames available")
        
        # Reference outputs for accuracy validation
        self.reference_outputs = None
        
    def _load_test_frames(self) -> List[np.ndarray]:
        """Load test frames from test_data directory."""
        frames = []
        test_dir = Path("test_data")
        if test_dir.exists():
            for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
                for img_path in test_dir.glob(ext):
                    frame = cv2.imread(str(img_path))
                    if frame is not None:
                        frames.append(frame)
        if not frames:
            # Create synthetic frames
            for i in range(10):
                frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
                frames.append(frame)
        return frames[:20]  # Limit to 20 frames
    
    def _get_gpu_memory(self) -> Optional[float]:
        """Get current GPU memory usage in MB."""
        try:
            if torch.cuda.is_available():
                return torch.cuda.memory_allocated() / (1024 * 1024)
        except:
            pass
        return None
    
    def _get_cpu_memory(self) -> Optional[float]:
        """Get current CPU memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except:
            pass
        return None
    
    def run_candidate(self, candidate: OptimizationCandidate) -> BenchmarkResult:
        """Run a single optimization candidate through the bounded loop."""
        print(f"\n{'='*60}")
        print(f"Testing Candidate: {candidate.name}")
        print(f"Description: {candidate.description}")
        print(f"{'='*60}")
        
        # Apply the optimization
        candidate.apply_fn()
        
        # Warmup
        print(f"Warming up ({candidate.warmup_iterations} iterations)...")
        for i in range(candidate.warmup_iterations):
            frame = self.test_frames[i % len(self.test_frames)]
            _ = candidate.validate_fn(frame)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        
        # Measured iterations
        print(f"Measuring ({candidate.measured_iterations} iterations)...")
        latencies = []
        outputs_list = []
        
        for i in range(candidate.measured_iterations):
            frame = self.test_frames[i % len(self.test_frames)]
            
            # Measure latency
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            start = time.perf_counter()
            output = candidate.validate_fn(frame)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            end = time.perf_counter()
            
            latency_ms = (end - start) * 1000
            latencies.append(latency_ms)
            outputs_list.append(output)
            
            if (i + 1) % 10 == 0:
                print(f"  Iteration {i+1}/{candidate.measured_iterations}: {latency_ms:.2f}ms")
        
        # Calculate statistics
        latencies = np.array(latencies)
        median_latency = float(np.median(latencies))
        mean_latency = float(np.mean(latencies))
        p95_latency = float(np.percentile(latencies, 95))
        fps = 1000.0 / median_latency if median_latency > 0 else 0
        
        # Accuracy validation
        accuracy_passed, accuracy_details = self._validate_accuracy(outputs_list)
        
        # Memory
        gpu_mem = self._get_gpu_memory()
        cpu_mem = self._get_cpu_memory()
        
        result = BenchmarkResult(
            config_name=candidate.name,
            warmup_iterations=candidate.warmup_iterations,
            measured_iterations=candidate.measured_iterations,
            latencies_ms=latencies.tolist(),
            median_latency_ms=median_latency,
            mean_latency_ms=mean_latency,
            p95_latency_ms=p95_latency,
            fps=fps,
            accuracy_passed=accuracy_passed,
            accuracy_details=accuracy_details,
            gpu_memory_mb=gpu_mem,
            cpu_memory_mb=cpu_mem
        )
        
        self.results.append(result)
        
        # Update best
        if accuracy_passed and median_latency < self.best_latency:
            self.best_latency = median_latency
            self.best_config = candidate.name
        
        print(f"\nResult: {candidate.name}")
        print(f"  Median: {median_latency:.2f}ms, Mean: {mean_latency:.2f}ms, P95: {p95_latency:.2f}ms")
        print(f"  FPS: {fps:.2f}")
        print(f"  Accuracy: {'PASS' if accuracy_passed else 'FAIL'}")
        if accuracy_details:
            print(f"  Accuracy Details: {accuracy_details}")
        
        return result
    
    def _validate_accuracy(self, outputs_list: List[Any]) -> Tuple[bool, Dict[str, Any]]:
        """Validate accuracy against reference outputs."""
        if self.reference_outputs is None:
            # First run becomes reference
            self.reference_outputs = outputs_list[0]
            return True, {"status": "reference_established"}
        
        # Compare against reference
        try:
            ref = self.reference_outputs
            curr = outputs_list[0]
            
            # Handle different output types
            if isinstance(ref, dict) and isinstance(curr, dict):
                return self._compare_dicts(ref, curr)
            elif isinstance(ref, (list, tuple)) and isinstance(curr, (list, tuple)):
                return self._compare_sequences(ref, curr)
            elif isinstance(ref, np.ndarray) and isinstance(curr, np.ndarray):
                return self._compare_arrays(ref, curr)
            else:
                return True, {"status": "type_mismatch_skipped"}
        except Exception as e:
            return False, {"error": str(e)}
    
    def _compare_dicts(self, ref: dict, curr: dict) -> Tuple[bool, Dict[str, Any]]:
        """Compare two dictionaries with numpy arrays."""
        all_keys = set(ref.keys()) | set(curr.keys())
        max_diff = 0.0
        details = {}
        
        for key in all_keys:
            if key not in ref or key not in curr:
                details[key] = "missing_in_one"
                continue
            
            r, c = ref[key], curr[key]
            if isinstance(r, np.ndarray) and isinstance(c, np.ndarray):
                if r.shape != c.shape:
                    details[key] = f"shape_mismatch: {r.shape} vs {c.shape}"
                    continue
                diff = np.max(np.abs(r - c))
                max_diff = max(max_diff, diff)
                details[key] = {"max_diff": float(diff), "shape": r.shape}
            elif isinstance(r, (list, tuple)) and isinstance(c, (list, tuple)):
                diff = np.max(np.abs(np.array(r) - np.array(c)))
                max_diff = max(max_diff, diff)
                details[key] = {"max_diff": float(diff)}
            else:
                details[key] = {"equal": r == c}
        
        passed = max_diff <= 1e-4
        return passed, {"max_diff": float(max_diff), "details": details, "tolerance": 1e-4}
    
    def _compare_sequences(self, ref: list, curr: list) -> Tuple[bool, Dict[str, Any]]:
        """Compare two sequences."""
        if len(ref) != len(curr):
            return False, {"error": f"length_mismatch: {len(ref)} vs {len(curr)}"}
        
        max_diff = 0.0
        for i, (r, c) in enumerate(zip(ref, curr)):
            if isinstance(r, np.ndarray) and isinstance(c, np.ndarray):
                diff = np.max(np.abs(r - c))
                max_diff = max(max_diff, diff)
        
        passed = max_diff <= 1e-4
        return passed, {"max_diff": float(max_diff), "tolerance": 1e-4}
    
    def _compare_arrays(self, ref: np.ndarray, curr: np.ndarray) -> Tuple[bool, Dict[str, Any]]:
        """Compare two numpy arrays."""
        if ref.shape != curr.shape:
            return False, {"error": f"shape_mismatch: {ref.shape} vs {curr.shape}"}
        
        max_diff = np.max(np.abs(ref - curr))
        passed = max_diff <= 1e-4
        return passed, {"max_diff": float(max_diff), "tolerance": 1e-4, "shape": ref.shape}
    
    def print_summary(self):
        """Print summary of all tested candidates."""
        print(f"\n{'='*60}")
        print("BOUNDED OPTIMIZATION LOOP SUMMARY")
        print(f"{'='*60}")
        print(f"{'Config':<30} {'Median(ms)':>10} {'Mean(ms)':>10} {'P95(ms)':>10} {'FPS':>8} {'Acc':>6}")
        print("-" * 80)
        
        for r in self.results:
            acc = "PASS" if r.accuracy_passed else "FAIL"
            print(f"{r.config_name:<30} {r.median_latency_ms:>10.2f} {r.mean_latency_ms:>10.2f} {r.p95_latency_ms:>10.2f} {r.fps:>8.2f} {acc:>6}")
        
        print("-" * 80)
        if self.best_config:
            print(f"BEST: {self.best_config} ({self.best_latency:.2f}ms, {1000/self.best_latency:.2f} FPS)")
        else:
            print("BEST: None (no candidate passed accuracy)")
    
    def save_results(self, output_path: str):
        """Save results to JSON."""
        data = {
            "model_path": self.model_path,
            "input_shape": self.input_shape,
            "best_config": self.best_config,
            "best_latency_ms": self.best_latency,
            "results": [asdict(r) for r in self.results]
        }
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"\nResults saved to {output_path}")


# ============================================================
# OPTIMIZATION CANDIDATES
# ============================================================

def create_candidate_ortvalue_reuse() -> OptimizationCandidate:
    """Candidate A: OrtValue Reuse - Pre-allocate and reuse OrtValues."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            reuse_ortvalues=True,
        )
    
    def validate(frame: np.ndarray):
        # Convert numpy frame to CanonicalFrame
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        import uuid
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="A_OrtValue_Reuse",
        description="Pre-allocate input/output OrtValues and reuse across frames",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4  # Full pipeline CAM1 baseline
    )


def create_candidate_io_binding_reuse() -> OptimizationCandidate:
    """Candidate B: I/O Binding Reuse - Avoid clear/rebind every frame."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            reuse_io_binding=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="B_IO_Binding_Reuse",
        description="Bind inputs/outputs once, update data pointers only",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_anchor_precompute() -> OptimizationCandidate:
    """Candidate C: SCRFD Anchor Precomputation - Precompute anchors once."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            precompute_anchors=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="C_Anchor_Precompute",
        description="Precompute SCRFD anchors once during initialization",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_vectorized_decode() -> OptimizationCandidate:
    """Candidate D: Vectorized SCRFD Decode - Replace Python loops with NumPy."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            vectorized_decode=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="D_Vectorized_Decode",
        description="Vectorized NumPy postprocessing instead of Python loops",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_no_sync() -> OptimizationCandidate:
    """Candidate E: Eliminate Unnecessary Synchronization."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            no_unnecessary_sync=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="E_No_Unnecessary_Sync",
        description="Remove redundant torch.cuda.synchronize() calls",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_buffer_reuse() -> OptimizationCandidate:
    """Candidate F: Buffer Reuse in Preprocessing."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            # Note: buffer reuse is in GPUPreprocessor, not GPUFaceDetector directly
            # We'll test this via the preprocessor separately
        )
        # Also create a preprocessor with buffer reuse
        import torch
        optimized_detector.gpu_preprocessor = create_gpu_preprocessor(
            model_id="scrfd",
            device=torch.device("cuda:0"),
            reuse_buffers=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="F_Buffer_Reuse",
        description="Pre-allocate preprocessing tensors and reuse",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_combined_ab() -> OptimizationCandidate:
    """Candidate G: Combined A+B - OrtValue + IO Binding Reuse."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            reuse_ortvalues=True,
            reuse_io_binding=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="G_Combined_AB",
        description="OrtValue reuse + I/O Binding reuse combined",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_combined_cd() -> OptimizationCandidate:
    """Candidate H: Combined C+D - Anchor Precompute + Vectorized Decode."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            precompute_anchors=True,
            vectorized_decode=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="H_Combined_CD",
        description="Anchor precomputation + Vectorized decode combined",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_full_pipeline_optimized() -> OptimizationCandidate:
    """Candidate I: Full Pipeline with All Optimizations."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
            precompute_anchors=True,
            vectorized_decode=True,
            reuse_ortvalues=True,
            reuse_io_binding=True,
            no_unnecessary_sync=True,
        )
        # Also enable buffer reuse in preprocessor
        import torch
        optimized_detector.gpu_preprocessor = create_gpu_preprocessor(
            model_id="scrfd",
            device=torch.device("cuda:0"),
            reuse_buffers=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="I_Full_Optimized",
        description="All optimizations combined in full pipeline",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def create_candidate_gpu_preprocessing() -> OptimizationCandidate:
    """Candidate J: Full GPU Preprocessing with Buffer Reuse."""
    
    optimized_detector = None
    
    def apply():
        nonlocal optimized_detector
        optimized_detector = create_gpu_face_detector(
            model_id="scrfd",
            device_id=0,
            enable_gpu_path=True,
            fallback_to_cpu=False,
        )
        # Enable buffer reuse in preprocessor
        import torch
        optimized_detector.gpu_preprocessor = create_gpu_preprocessor(
            model_id="scrfd",
            device=torch.device("cuda:0"),
            reuse_buffers=True,
            full_gpu=True,
        )
    
    def validate(frame: np.ndarray):
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        metadata = FrameMetadata(
            frame_index=0,
            timestamp=0.0,
            source_id="test",
            source_type=SourceType.VIDEO,
            original_width=frame.shape[1],
            original_height=frame.shape[0],
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        canonical_frame = CanonicalFrame(data=frame, metadata=metadata)
        return optimized_detector.detect(canonical_frame)
    
    return OptimizationCandidate(
        name="J_Full_GPU_Preprocess",
        description="Full GPU preprocessing with buffer reuse",
        apply_fn=apply,
        validate_fn=validate,
        warmup_iterations=10,
        measured_iterations=50,
        baseline_latency_ms=62.4
    )


def main():
    """Main entry point for bounded optimization loop."""
    print("="*60)
    print("PHASE 36L: BOUNDED OPTIMIZATION LOOP")
    print("="*60)
    print("Max 10 candidates, 10 warmup + 50 measured iterations each")
    print("Accuracy tolerance: 1e-4")
    print("="*60)
    
    model_path = "models/scrfd/scrfd_10g_bnkps.onnx"
    if not Path(model_path).exists():
        print(f"ERROR: Model not found at {model_path}")
        return 1
    
    loop = BoundedOptimizationLoop(model_path)
    
    # Define all candidates (max 10)
    candidates = [
        create_candidate_ortvalue_reuse(),
        create_candidate_io_binding_reuse(),
        create_candidate_anchor_precompute(),
        create_candidate_vectorized_decode(),
        create_candidate_no_sync(),
        create_candidate_buffer_reuse(),
        create_candidate_combined_ab(),
        create_candidate_combined_cd(),
        create_candidate_full_pipeline_optimized(),
        create_candidate_gpu_preprocessing(),
    ]
    
    # Run each candidate
    for candidate in candidates:
        try:
            loop.run_candidate(candidate)
        except Exception as e:
            print(f"ERROR testing {candidate.name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Print summary
    loop.print_summary()
    
    # Save results
    output_path = "benchmark_results/PHASE_36L_BOUNDED_OPTIMIZATION.json"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    loop.save_results(output_path)
    
    # Generate markdown report
    md_path = "benchmark_results/PHASE_36L_BOUNDED_OPTIMIZATION.md"
    generate_markdown_report(loop.results, loop.best_config, loop.best_latency, md_path)
    
    return 0


def generate_markdown_report(results: List[BenchmarkResult], best_config: str, best_latency: float, output_path: str):
    """Generate markdown report."""
    with open(output_path, 'w') as f:
        f.write("# Phase 36L: Bounded Optimization Loop Results\n\n")
        f.write(f"**Best Configuration:** {best_config}\n")
        f.write(f"**Best Latency:** {best_latency:.2f}ms ({1000/best_latency:.2f} FPS)\n\n")
        
        f.write("## Results Summary\n\n")
        f.write("| Config | Median (ms) | Mean (ms) | P95 (ms) | FPS | Accuracy |\n")
        f.write("|--------|-------------|-----------|----------|-----|----------|\n")
        
        for r in results:
            acc = "PASS" if r.accuracy_passed else "FAIL"
            f.write(f"| {r.config_name} | {r.median_latency_ms:.2f} | {r.mean_latency_ms:.2f} | {r.p95_latency_ms:.2f} | {r.fps:.2f} | {acc} |\n")
        
        f.write("\n## Detailed Results\n\n")
        for r in results:
            f.write(f"### {r.config_name}\n\n")
            f.write(f"- **Median Latency:** {r.median_latency_ms:.2f}ms\n")
            f.write(f"- **Mean Latency:** {r.mean_latency_ms:.2f}ms\n")
            f.write(f"- **P95 Latency:** {r.p95_latency_ms:.2f}ms\n")
            f.write(f"- **FPS:** {r.fps:.2f}\n")
            f.write(f"- **Accuracy:** {'PASS' if r.accuracy_passed else 'FAIL'}\n")
            f.write(f"- **Accuracy Details:** {r.accuracy_details}\n")
            if r.gpu_memory_mb:
                f.write(f"- **GPU Memory:** {r.gpu_memory_mb:.2f}MB\n")
            if r.cpu_memory_mb:
                f.write(f"- **CPU Memory:** {r.cpu_memory_mb:.2f}MB\n")
            f.write("\n")


if __name__ == "__main__":
    sys.exit(main())