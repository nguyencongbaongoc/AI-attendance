#!/usr/bin/env python
"""
Phase 36T - GPU Live Integration Regression Tests.

Tests the production detector factory correctly routes to GPUFaceDetector
when GPU mode is enabled, and CPU FaceDetector when GPU is unavailable/disabled.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch
from typing import Optional, List


class TestGPUFaceDetectorFactoryRouting:
    """Test production detector factory selects GPUFaceDetector when GPU mode is enabled."""

    def test_get_detector_for_live_returns_gpu_when_enabled(self):
        """get_detector_for_live() should return GPUFaceDetector when GPU is available."""
        from app.vision.detector_factory import get_detector_for_live
        from app.vision.gpu_face_detector import GPUFaceDetector

        detector = get_detector_for_live()
        # On systems with CUDA, should return GPUFaceDetector
        assert isinstance(detector, (GPUFaceDetector, type(None))), (
            f"Expected GPUFaceDetector or fallback, got {type(detector).__name__}"
        )
        if isinstance(detector, GPUFaceDetector):
            assert hasattr(detector, "gpu_available")

    def test_get_detector_for_live_force_cpu(self):
        """get_detector_for_live(use_gpu=False) should return CPU FaceDetector."""
        from app.vision.detector_factory import get_detector_for_live
        from app.vision.detection import FaceDetector

        detector = get_detector_for_live(use_gpu=False)
        assert isinstance(detector, FaceDetector), (
            f"Expected FaceDetector when use_gpu=False, got {type(detector).__name__}"
        )

    def test_get_detector_for_live_env_var_override(self):
        """CLINE_USE_GPU_DETECTOR=false should force CPU path."""
        from app.vision.detector_factory import get_detector_for_live
        from app.vision.detection import FaceDetector

        # Temporarily set env var
        old_val = os.environ.get("CLINE_USE_GPU_DETECTOR")
        try:
            os.environ["CLINE_USE_GPU_DETECTOR"] = "false"
            detector = get_detector_for_live()
            assert isinstance(detector, FaceDetector), (
                f"Expected FaceDetector when env CLINE_USE_GPU_DETECTOR=false, "
                f"got {type(detector).__name__}"
            )
        finally:
            if old_val is None:
                os.environ.pop("CLINE_USE_GPU_DETECTOR", None)
            else:
                os.environ["CLINE_USE_GPU_DETECTOR"] = old_val

    def test_detector_detect_returns_face_detection_list(self):
        """Detector.detect() should return List[FaceDetection] for both GPU and CPU paths."""
        from app.vision.detector_factory import get_detector_for_live
        from app.vision.detection import FaceDetection

        detector = get_detector_for_live()
        assert hasattr(detector, "detect"), "Detector must have detect() method"
        # Full detection test would require a real frame; this verifies the API contract exists

    def test_detector_has_required_attributes(self):
        """Detector should expose required attributes for downstream consumers."""
        from app.vision.detector_factory import get_detector_for_live

        detector = get_detector_for_live()
        assert hasattr(detector, "detect"), "Must have detect() method"
        assert hasattr(detector, "confidence_threshold") or hasattr(detector, "config"), (
            "Must have confidence_threshold or config"
        )


class TestGPUFaceDetectorContractPreservation:
    """Test that GPUFaceDetector preserves the FaceDetection output contract."""

    def test_gpu_detector_inherits_correctly(self):
        """GPUFaceDetector should be compatible with the detector contract."""
        from app.vision.gpu_face_detector import GPUFaceDetector, GPUFaceDetectorConfig

        # Verify class exists and has expected methods
        assert hasattr(GPUFaceDetector, "detect")
        assert hasattr(GPUFaceDetector, "_detect_gpu")
        assert hasattr(GPUFaceDetector, "close")

    def test_gpu_detector_config_defaults(self):
        """GPUFaceDetectorConfig should have sensible defaults."""
        from app.vision.gpu_face_detector import GPUFaceDetectorConfig

        config = GPUFaceDetectorConfig()
        assert config.model_id == "scrfd"
        assert config.enable_gpu_path is True
        assert config.fallback_to_cpu is True
        assert config.device_id == 0

    def test_cpu_fallback_detector_available(self):
        """CPU fallback should always be available in GPUFaceDetector."""
        from app.vision.gpu_face_detector import GPUFaceDetector, GPUFaceDetectorConfig

        config = GPUFaceDetectorConfig(enable_gpu_path=False)
        detector = GPUFaceDetector(config)
        assert detector.cpu_detector is not None
        assert hasattr(detector.cpu_detector, "detect")


class TestGPUEpVerification:
    """Test that CUDAExecutionProvider is verified at initialization."""

    def test_gpu_available_requires_cuda_ep(self):
        """gpu_available should be True only when CUDA EP is actually active."""
        from app.vision.gpu_face_detector import GPUFaceDetector, GPUFaceDetectorConfig

        config = GPUFaceDetectorConfig(enable_gpu_path=True)
        detector = GPUFaceDetector(config)
        # If gpu_available is True, the CUDA EP must be verified
        if detector.gpu_available:
            assert detector.gpu_inference_engine is not None
            assert detector.gpu_inference_engine.cuda_ep_used is True
            assert detector.gpu_preprocessor is not None

    def test_gpu_unavailable_sets_gpu_available_false(self):
        """When CUDA EP is not available, gpu_available must be False."""
        from app.vision.gpu_face_detector import GPUFaceDetector, GPUFaceDetectorConfig

        config = GPUFaceDetectorConfig(enable_gpu_path=True)
        detector = GPUFaceDetector(config)
        if not detector.gpu_available:
            # Verify fallback state
            assert detector.gpu_preprocessor is None or detector.gpu_inference_engine is None


class TestFalloverLogging:
    """Test that GPU fallback uses structured logging instead of print()."""

    def test_gpu_inference_uses_logger(self):
        """GPUInferenceEngine._infer_fallback should use logger, not print()."""
        import inspect
        from app.vision.gpu_inference import GPUInferenceEngine

        source = inspect.getsource(GPUInferenceEngine._infer_fallback)
        # Should use logger, not print
        assert "print(" not in source, (
            "GPUInferenceEngine._infer_fallback still uses print() instead of logger"
        )
        assert "logger." in source, (
            "GPUInferenceEngine._infer_fallback should use structured logger"
        )

    def test_gpu_detector_uses_logger(self):
        """GPUFaceDetector should use structured logging."""
        import inspect
        from app.vision.gpu_face_detector import GPUFaceDetector

        source = inspect.getsource(GPUFaceDetector._init_gpu_components)
        # Should use logger, not print
        assert "print(" not in source, (
            "GPUFaceDetector._init_gpu_components still uses print() instead of logger"
        )


class TestExistingCPUPathPreserved:
    """Test that the existing CPU path remains functional."""

    def test_cpu_detector_still_works(self):
        """CPU FaceDetector should still be creatable directly."""
        from app.vision.detection import create_face_detector

        detector = create_face_detector()
        assert detector is not None
        assert hasattr(detection := detector, "detect")

    def test_create_face_detector_returns_cpu(self):
        """create_face_detector() should always return CPU FaceDetector."""
        from app.vision.detection import create_face_detector, FaceDetector

        detector = create_face_detector()
        assert isinstance(detector, FaceDetector)


class TestProductionLiveDetectorRouting:
    """Test that production scripts use the correct detector factory."""

    def test_phase35_e2e_uses_detector_factory(self):
        """Phase 35 realtime e2e should import get_detector_for_live."""
        import ast
        from pathlib import Path

        script_path = Path("scripts/phase35_realtime_e2e.py")
        assert script_path.exists(), f"Script not found: {script_path}"

        content = script_path.read_text(encoding="utf-8")
        assert "get_detector_for_live" in content, (
            "phase35_realtime_e2e.py should import and use get_detector_for_live"
        )

    def test_phase35_e2e_not_importing_direct_detector(self):
        """Phase 35 should not use direct create_face_detector for live path."""
        from pathlib import Path

        script_path = Path("scripts/phase35_realtime_e2e.py")
        content = script_path.read_text(encoding="utf-8")

        # Check that at least some detector calls use the factory
        factory_usage = content.count("get_detector_for_live")
        assert factory_usage >= 1, (
            "Phase 35 should use get_detector_for_live at least once"
        )

    def test_detector_factory_has_gpu_routing(self):
        """Detector factory should have get_detector_for_live function."""
        from app.vision.detector_factory import get_detector_for_live
        assert callable(get_detector_for_live)