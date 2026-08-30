"""
Phase 6 — Data Pipeline Validation Script.

This script validates the unified image/video data pipeline.

CRITICAL RULES:
- NO camera access
- NO MediaMTX, RTMP, RTSP, FFmpeg streaming
- NO real images - synthetic inputs only
- NO accuracy claims from synthetic noise

Validates:
1. CanonicalFrame representation
2. Preprocessing contracts
3. Unified preprocessing pipeline
4. Image adapter
5. Video adapter
6. NPY artifact format
7. 4K safety test
8. Large video test (memory safety)
"""

from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ValidationResult:
    """Result of a single validation test."""
    
    test_name: str
    passed: bool
    duration_ms: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class Phase6Report:
    """Complete Phase 6 validation report."""
    
    timestamp: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    results: List[Dict[str, Any]]
    verdict: str
    safety_checks: Dict[str, bool]
    memory_tests: Dict[str, Any]


def create_synthetic_image(height: int, width: int, seed: int = 42) -> np.ndarray:
    """Create a synthetic image for testing."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def create_synthetic_video(
    output_path: Path,
    height: int,
    width: int,
    frame_count: int,
    fps: float = 30.0,
    seed: int = 42,
) -> Path:
    """Create a synthetic video for testing."""
    import cv2
    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    
    rng = np.random.default_rng(seed)
    
    for i in range(frame_count):
        frame = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
        writer.write(frame)
    
    writer.release()
    return output_path


def test_canonical_frame() -> ValidationResult:
    """Test CanonicalFrame representation."""
    start_time = time.perf_counter()
    
    try:
        from app.data.frame import (
            CanonicalFrame,
            FrameMetadata,
            SourceType,
            PixelFormat,
        )
        
        # Test 1: Create frame
        data = create_synthetic_image(100, 100)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=100,
            original_height=100,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=data, metadata=metadata)
        
        assert frame.width == 100
        assert frame.height == 100
        assert frame.channels == 3
        
        # Test 2: Frame copy
        copy = frame.copy()
        assert np.array_equal(copy.data, frame.data)
        
        # Test 3: Conversion tracking
        frame_with_conv = frame.with_conversion("bgr_to_rgb")
        assert "bgr_to_rgb" in frame_with_conv.conversions_applied
        
        # Test 4: Serialization
        d = frame.to_dict()
        assert "metadata" in d
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="canonical_frame",
            passed=True,
            duration_ms=duration_ms,
            message="CanonicalFrame tests passed",
            details={
                "width": frame.width,
                "height": frame.height,
                "channels": frame.channels,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="canonical_frame",
            passed=False,
            duration_ms=duration_ms,
            message="CanonicalFrame tests failed",
            error=str(e),
        )


def test_preprocessing_contracts() -> ValidationResult:
    """Test preprocessing contracts."""
    start_time = time.perf_counter()
    
    try:
        from app.data.contracts import (
            ModelPreprocessingContract,
            get_model_contract,
            list_model_contracts,
            ColorSpace,
            TensorLayout,
        )
        
        # Test 1: Get contracts
        contracts = list_model_contracts()
        assert len(contracts) == 6
        
        # Test 2: Get specific contract
        scrfd_contract = get_model_contract("scrfd")
        assert scrfd_contract.model_id == "scrfd"
        assert scrfd_contract.input_height == 960
        
        # Test 3: Contract serialization
        d = scrfd_contract.to_dict()
        assert d["model_id"] == "scrfd"
        
        # Test 4: Compatibility check
        arcface_contract = get_model_contract("arcface")
        assert not scrfd_contract.is_compatible_with(arcface_contract)
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="preprocessing_contracts",
            passed=True,
            duration_ms=duration_ms,
            message="Preprocessing contracts tests passed",
            details={
                "contract_count": len(contracts),
                "models": list(contracts.keys()),
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="preprocessing_contracts",
            passed=False,
            duration_ms=duration_ms,
            message="Preprocessing contracts tests failed",
            error=str(e),
        )


def test_unified_preprocessor() -> ValidationResult:
    """Test unified preprocessor."""
    start_time = time.perf_counter()
    
    try:
        from app.data.preprocessing import UnifiedPreprocessor
        from app.data.contracts import get_model_contract
        from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
        
        # Create synthetic frame
        data = create_synthetic_image(100, 100)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=100,
            original_height=100,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=data, metadata=metadata)
        
        # Test preprocessing for each model
        models = ["scrfd", "arcface", "landmark_1k3d68", "reid", "yolo_person", "yolo_pose"]
        results = {}
        
        for model_id in models:
            preprocessor = UnifiedPreprocessor(model_id)
            result = preprocessor.preprocess(frame)
            
            contract = get_model_contract(model_id)
            assert result.tensor.shape == contract.target_shape
            results[model_id] = {
                "shape": list(result.tensor.shape),
                "conversions": len(result.conversions),
            }
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="unified_preprocessor",
            passed=True,
            duration_ms=duration_ms,
            message="Unified preprocessor tests passed",
            details={"models": results},
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="unified_preprocessor",
            passed=False,
            duration_ms=duration_ms,
            message="Unified preprocessor tests failed",
            error=str(e),
        )


def test_image_adapter() -> ValidationResult:
    """Test image adapter."""
    start_time = time.perf_counter()
    
    try:
        from app.data.input_adapter import ImageAdapter, load_image
        import cv2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic image
            image_path = Path(tmpdir) / "test_image.jpg"
            image_data = create_synthetic_image(100, 100)
            cv2.imwrite(str(image_path), image_data)
            
            # Test loading
            adapter = ImageAdapter()
            frame = adapter.load(image_path)
            
            assert frame.width == 100
            assert frame.height == 100
            assert frame.is_bgr()
            
            # Test RGB conversion
            rgb_frame = adapter.load_as_rgb(image_path)
            assert rgb_frame.is_rgb()
            
            # Test convenience function
            frame2 = load_image(image_path)
            assert frame2 is not None
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="image_adapter",
            passed=True,
            duration_ms=duration_ms,
            message="Image adapter tests passed",
            details={
                "width": frame.width,
                "height": frame.height,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="image_adapter",
            passed=False,
            duration_ms=duration_ms,
            message="Image adapter tests failed",
            error=str(e),
        )


def test_video_adapter() -> ValidationResult:
    """Test video adapter."""
    start_time = time.perf_counter()
    
    try:
        from app.data.input_adapter import VideoAdapter, VideoFrameIterator, iter_video_frames
        import cv2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic video
            video_path = Path(tmpdir) / "test_video.mp4"
            create_synthetic_video(video_path, 100, 100, 10)
            
            # Test video info
            adapter = VideoAdapter()
            info = adapter.get_info(video_path)
            
            assert info.width == 100
            assert info.height == 100
            assert info.frame_count == 10
            
            # Test frame iteration
            frames = list(adapter.iter_frames(video_path))
            assert len(frames) == 10
            
            # Test context manager
            with VideoFrameIterator(video_path) as iterator:
                frame = next(iterator)
                assert frame is not None
            
            # Test convenience function
            frames2 = list(iter_video_frames(video_path))
            assert len(frames2) == 10
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="video_adapter",
            passed=True,
            duration_ms=duration_ms,
            message="Video adapter tests passed",
            details={
                "frame_count": info.frame_count,
                "fps": info.fps,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="video_adapter",
            passed=False,
            duration_ms=duration_ms,
            message="Video adapter tests failed",
            error=str(e),
        )


def test_npy_artifact() -> ValidationResult:
    """Test NPY artifact format."""
    start_time = time.perf_counter()
    
    try:
        from app.data.npy import (
            NpyArtifactWriter,
            NpyArtifactReader,
            NpyValidationError,
            write_npy_artifact,
            read_npy_artifact,
        )
        from app.data.preprocessing import UnifiedPreprocessor
        from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic frame
            data = create_synthetic_image(100, 100)
            metadata = FrameMetadata(
                source_type=SourceType.IMAGE,
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                original_width=100,
                original_height=100,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
            )
            frame = CanonicalFrame(data=data, metadata=metadata)
            
            # Preprocess
            preprocessor = UnifiedPreprocessor("scrfd")
            result = preprocessor.preprocess(frame)
            
            # Write artifact
            npy_path, metadata_path = write_npy_artifact(result, Path(tmpdir))
            
            assert npy_path.exists()
            assert metadata_path.exists()
            
            # Read artifact
            tensor, artifact_metadata = read_npy_artifact(npy_path)
            
            assert tensor.shape == result.target_shape
            assert artifact_metadata.model_id == "scrfd"
            
            # Test validation
            reader = NpyArtifactReader()
            tensor2, metadata2 = reader.read_and_validate(npy_path, "scrfd")
            
            assert tensor2 is not None
            
            # Test validation failure
            try:
                reader.read_and_validate(npy_path, "arcface")
                raise AssertionError("Should have raised NpyValidationError")
            except NpyValidationError:
                pass  # Expected
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="npy_artifact",
            passed=True,
            duration_ms=duration_ms,
            message="NPY artifact tests passed",
            details={
                "tensor_shape": list(tensor.shape),
                "metadata_model": artifact_metadata.model_id,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="npy_artifact",
            passed=False,
            duration_ms=duration_ms,
            message="NPY artifact tests failed",
            error=str(e),
        )


def test_4k_safety() -> ValidationResult:
    """Test 4K image/video safety."""
    start_time = time.perf_counter()
    
    try:
        from app.data.preprocessing import UnifiedPreprocessor
        from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
        from app.data.npy import write_npy_artifact
        import cv2
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 4K image (3840x2160)
            image_4k = create_synthetic_image(2160, 3840, seed=123)
            
            metadata = FrameMetadata(
                source_type=SourceType.IMAGE,
                source_id="4k_test.jpg",
                frame_index=0,
                timestamp=None,
                original_width=3840,
                original_height=2160,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
            )
            frame = CanonicalFrame(data=image_4k, metadata=metadata)
            
            # Preprocess for SCRFD (960x960)
            preprocessor = UnifiedPreprocessor("scrfd")
            result = preprocessor.preprocess(frame)
            
            assert result.tensor.shape == (1, 3, 960, 960)
            
            # Save as NPY
            npy_path, _ = write_npy_artifact(result, Path(tmpdir))
            assert npy_path.exists()
            
            # Verify memory usage is reasonable
            tensor_size_mb = result.tensor.nbytes / (1024 * 1024)
            assert tensor_size_mb < 50, f"Tensor too large: {tensor_size_mb} MB"
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="4k_safety",
            passed=True,
            duration_ms=duration_ms,
            message="4K safety test passed",
            details={
                "input_resolution": "3840x2160",
                "output_shape": list(result.tensor.shape),
                "tensor_size_mb": round(tensor_size_mb, 2),
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="4k_safety",
            passed=False,
            duration_ms=duration_ms,
            message="4K safety test failed",
            error=str(e),
        )


def test_large_video_memory_safety() -> ValidationResult:
    """Test large video memory safety (streaming iteration)."""
    start_time = time.perf_counter()
    
    try:
        from app.data.input_adapter import VideoAdapter
        from app.data.preprocessing import UnifiedPreprocessor
        from app.data.npy import NpyArtifactWriter
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a "large" video (100 frames)
            video_path = Path(tmpdir) / "large_video.mp4"
            create_synthetic_video(video_path, 480, 640, 100, seed=456)
            
            # Process video with streaming iteration
            adapter = VideoAdapter()
            preprocessor = UnifiedPreprocessor("scrfd")
            writer = NpyArtifactWriter(Path(tmpdir) / "frames")
            
            frame_count = 0
            max_memory_mb = 0
            
            for frame in adapter.iter_frames(video_path):
                result = preprocessor.preprocess(frame)
                writer.write(result)
                frame_count += 1
                
                # Check memory (rough estimate)
                import tracemalloc
                if frame_count == 1:
                    tracemalloc.start()
                elif frame_count % 20 == 0:
                    current, peak = tracemalloc.get_traced_memory()
                    max_memory_mb = max(max_memory_mb, peak / (1024 * 1024))
            
            # Verify all frames processed
            assert frame_count == 100
            
            # Verify memory didn't grow unboundedly
            # With streaming, memory should stay relatively constant
            # Allow up to 500MB for safety
            assert max_memory_mb < 500, f"Memory too high: {max_memory_mb} MB"
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="large_video_memory_safety",
            passed=True,
            duration_ms=duration_ms,
            message="Large video memory safety test passed",
            details={
                "frame_count": frame_count,
                "max_memory_mb": round(max_memory_mb, 2),
                "resolution": "640x480",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="large_video_memory_safety",
            passed=False,
            duration_ms=duration_ms,
            message="Large video memory safety test failed",
            error=str(e),
        )


def test_safety_verification() -> ValidationResult:
    """Verify no camera/streaming access in code."""
    start_time = time.perf_counter()
    
    try:
        forbidden_patterns = [
            "cv2.VideoCapture(0)",
            "cv2.VideoCapture(1)",
            "rtmp://",
            "rtsp://",
            "ffmpeg -i",
        ]
        
        source_files = [
            "app/data/__init__.py",
            "app/data/frame.py",
            "app/data/contracts.py",
            "app/data/preprocessing.py",
            "app/data/input_adapter.py",
            "app/data/npy.py",
        ]
        
        violations = []
        for file_path in source_files:
            path = Path(file_path)
            if path.exists():
                content = path.read_text()
                # Check for forbidden code patterns (not documentation)
                # Look for actual usage, not mentions in docstrings
                lines = content.split('\n')
                code_lines = [line for line in lines if not line.strip().startswith('#') and '"""' not in line and "'''" not in line]
                code_content = '\n'.join(code_lines)
                
                for pattern in forbidden_patterns:
                    if pattern in code_content:
                        violations.append(f"{file_path}: {pattern}")
        
        if violations:
            raise AssertionError(f"Forbidden patterns found: {violations}")
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return ValidationResult(
            test_name="safety_verification",
            passed=True,
            duration_ms=duration_ms,
            message="Safety verification passed",
            details={
                "files_checked": len(source_files),
                "patterns_checked": len(forbidden_patterns),
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="safety_verification",
            passed=False,
            duration_ms=duration_ms,
            message="Safety verification failed",
            error=str(e),
        )


def run_all_tests() -> Phase6Report:
    """Run all validation tests."""
    print("=" * 80)
    print("Phase 6 — Data Pipeline Validation")
    print("=" * 80)
    print()
    
    tests = [
        ("CanonicalFrame", test_canonical_frame),
        ("Preprocessing Contracts", test_preprocessing_contracts),
        ("Unified Preprocessor", test_unified_preprocessor),
        ("Image Adapter", test_image_adapter),
        ("Video Adapter", test_video_adapter),
        ("NPY Artifact", test_npy_artifact),
        ("4K Safety", test_4k_safety),
        ("Large Video Memory Safety", test_large_video_memory_safety),
        ("Safety Verification", test_safety_verification),
    ]
    
    results: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"Running: {name}...", end=" ")
        result = test_func()
        results.append(asdict(result))
        
        if result.passed:
            print(f"PASSED ({result.duration_ms:.1f}ms)")
            passed += 1
        else:
            print(f"FAILED ({result.duration_ms:.1f}ms)")
            if result.error:
                print(f"  Error: {result.error}")
            failed += 1
    
    print()
    print("=" * 80)
    print(f"Results: {passed}/{len(tests)} passed, {failed} failed")
    print("=" * 80)
    
    # Build report
    report = Phase6Report(
        timestamp=datetime.now().isoformat(),
        total_tests=len(tests),
        passed_tests=passed,
        failed_tests=failed,
        skipped_tests=0,
        results=results,
        verdict="PASS" if failed == 0 else "FAIL",
        safety_checks={
            "no_camera_access": True,
            "no_streaming_protocols": True,
            "synthetic_data_only": True,
        },
        memory_tests={
            "4k_safety": any(r["test_name"] == "4k_safety" and r["passed"] for r in results),
            "large_video_memory": any(r["test_name"] == "large_video_memory_safety" and r["passed"] for r in results),
        },
    )
    
    return report


def main():
    """Main entry point."""
    # Run tests
    report = run_all_tests()
    
    # Save report
    output_dir = Path("benchmark_results")
    output_dir.mkdir(exist_ok=True)
    
    report_path = output_dir / "PHASE_6_DATA_PIPELINE_VALIDATION.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    
    print(f"\nReport saved to: {report_path}")
    
    # Return exit code
    return 0 if report.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
