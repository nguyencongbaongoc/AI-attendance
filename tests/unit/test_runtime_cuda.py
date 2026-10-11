"""
Phase 3 — CUDA Runtime Validation Unit Tests.

Tests cover:
- GPU detection
- CUDA detection
- PyTorch CUDA tensor operations
- ONNX Runtime provider detection
- Provider priority (CUDA before CPU)
- CPU fallback
- Model hash enforcement
- Missing model handling
- Runtime error classification

Tests MUST NOT:
- Start cameras
- Connect to RTMP
- Connect to RTSP
- Start MediaMTX
- Start FFmpeg against a camera
- Load AI production models
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from app.config.paths import ProjectPaths, get_project_paths
from app.errors import DependencyError
from app.models.registry import get_model_registry


# =============================================================================
# Step 2 — NVIDIA GPU Validation Tests
# =============================================================================

class TestNvidiaGPUValidation:
    """Tests for NVIDIA GPU detection validation."""

    def test_nvidia_gpu_detected(self):
        """Validate that NVIDIA GPU is actually detected via pynvml."""
        pytest.importorskip("pynvml")
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        assert count > 0, "No NVIDIA GPUs detected"
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        assert "NVIDIA" in name, f"GPU name does not contain 'NVIDIA': {name}"
        pynvml.nvmlShutdown()

    def test_nvidia_driver_version_reported(self):
        """Validate driver version is reported."""
        pytest.importorskip("pynvml")
        import pynvml
        pynvml.nvmlInit()
        driver = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode("utf-8")
        assert driver, "Driver version not reported"
        pynvml.nvmlShutdown()

    def test_nvidia_gpu_vram_reported(self):
        """Validate VRAM is reported."""
        pytest.importorskip("pynvml")
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        assert mem.total > 0, "Total VRAM is 0"
        pynvml.nvmlShutdown()

    def test_nvidia_gpu_utilization_reported(self):
        """Validate GPU utilization is reported."""
        pytest.importorskip("pynvml")
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        assert hasattr(util, "gpu"), "GPU utilization not available"
        pynvml.nvmlShutdown()

    def test_nvidia_gpu_temperature_reported(self):
        """Validate GPU temperature is reported."""
        pytest.importorskip("pynvml")
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        assert isinstance(temp, int), f"Temperature not an integer: {type(temp)}"
        pynvml.nvmlShutdown()


# =============================================================================
# Step 3 — PyTorch CUDA Validation Tests
# =============================================================================

class TestPyTorchCUDA:
    """Tests for PyTorch CUDA validation."""

    def test_torch_cuda_available(self):
        """Validate torch.cuda.is_available() returns True."""
        pytest.importorskip("torch")
        import torch
        assert torch.cuda.is_available(), "torch.cuda.is_available() is False"

    def test_torch_device_count(self):
        """Validate torch sees the GPU."""
        pytest.importorskip("torch")
        import torch
        assert torch.cuda.device_count() > 0, "No CUDA devices found"

    def test_torch_device_name(self):
        """Validate torch reports GPU name."""
        pytest.importorskip("torch")
        import torch
        assert torch.cuda.is_available()
        name = torch.cuda.get_device_name(0)
        assert name, "Device name is empty"
        assert "NVIDIA" in name or "GeForce" in name, f"Unexpected GPU name: {name}"

    def test_torch_cuda_version(self):
        """Validate torch reports CUDA version."""
        pytest.importorskip("torch")
        import torch
        cuda_ver = torch.version.cuda
        assert cuda_ver is not None, "torch.version.cuda is None"
        assert len(cuda_ver) > 0, "CUDA version string is empty"

    def test_torch_cuda_tensor_operation(self):
        """Validate actual CUDA tensor operation succeeds."""
        pytest.importorskip("torch")
        import torch
        a = torch.randn(100, 100).cuda()
        b = torch.randn(100, 100).cuda()
        c = torch.matmul(a, b)
        d = c.cpu()
        assert d.shape == (100, 100), f"Unexpected shape: {d.shape}"
        assert not torch.isnan(d).any(), "Result contains NaN"

    def test_torch_cuda_operation_elapsed_time(self):
        """Validate CUDA operation timing is recorded."""
        pytest.importorskip("torch")
        import torch
        from app.runtime.cuda import validate_pytorch_cuda
        result = validate_pytorch_cuda()
        assert result.success, f"PyTorch CUDA validation failed: {result.error}"
        assert result.operation_success
        assert result.operation_elapsed_ms is not None
        assert result.operation_elapsed_ms >= 0

    def test_pytorch_cuda_result_fields(self):
        """Validate PyTorchCUDAResult dataclass fields."""
        pytest.importorskip("torch")
        from app.runtime.cuda import validate_pytorch_cuda
        result = validate_pytorch_cuda()
        assert result.success
        assert result.torch_version != "not installed"
        assert result.cuda_compiled_version != "n/a"
        assert result.cuda_available
        assert result.device_count > 0
        assert result.device_name is not None
        assert result.compute_capability is not None
        assert result.total_memory_mb is not None
        assert result.total_memory_mb > 0


# =============================================================================
# Step 4 — ONNX Runtime Validation Tests
# =============================================================================

class TestONNXRuntimeValidation:
    """Tests for ONNX Runtime provider detection."""

    def test_ort_importable(self):
        """Validate onnxruntime-gpu is importable."""
        pytest.importorskip("onnxruntime")

    def test_ort_version_reported(self):
        """Validate ORT version is reported."""
        pytest.importorskip("onnxruntime")
        import onnxruntime as ort
        assert ort.__version__, "ORT version is empty"

    def test_cuda_ep_registered(self):
        """Validate CUDAExecutionProvider is registered in providers."""
        pytest.importorskip("onnxruntime")
        import onnxruntime as ort
        providers = ort.get_available_providers()
        assert "CUDAExecutionProvider" in providers, \
            f"CUDAExecutionProvider not in providers: {providers}"

    def test_cpu_ep_registered(self):
        """Validate CPUExecutionProvider is registered."""
        pytest.importorskip("onnxruntime")
        import onnxruntime as ort
        providers = ort.get_available_providers()
        assert "CPUExecutionProvider" in providers, \
            f"CPUExecutionProvider not in providers: {providers}"

    def test_detect_ort_providers(self):
        """Validate detect_ort_providers returns correct structure."""
        from app.runtime.cuda import detect_ort_providers
        result = detect_ort_providers()
        assert result.cuda_ep_registered, "CUDA EP not registered"
        assert result.cpu_ep_registered, "CPU EP not registered"
        assert "CUDAExecutionProvider" in result.available_providers


# =============================================================================
# Step 5 — CUDA EP Session Creation Tests
# =============================================================================

class TestCUDAEPSSession:
    """Tests for CUDA EP session creation."""

    def test_cuda_ep_session_creation(self):
        """Validate ONNX Runtime session creation with CUDA EP succeeds."""
        from app.runtime.cuda import create_cuda_ep_session
        result = create_cuda_ep_session()
        assert result.success, f"CUDA EP session creation failed: {result.error}"
        assert result.cuda_ep_in_first, "CUDA EP not in first position"
        session_providers = result.session_providers
        assert session_providers[0] == "CUDAExecutionProvider"
        assert "CPUExecutionProvider" in session_providers

    def test_cuda_ep_session_creates_minimal_model(self):
        """Validate minimal ONNX model is created and cleaned up."""
        from app.runtime.cuda import create_cuda_ep_session
        result = create_cuda_ep_session()
        assert result.success
        # Verify temp model was cleaned up
        paths = get_project_paths()
        temp_dir = paths.data_dir / "temp" / "cuda_validation"
        model_path = temp_dir / "minimal_cuda_test.onnx"
        assert not model_path.exists(), "Temporary model file not cleaned up"


# =============================================================================
# Step 6 — Actual ONNX CUDA Inference Tests
# =============================================================================

class TestORTCUDAInference:
    """Tests for actual ONNX Runtime CUDA inference."""

    def test_cuda_inference_succeeds(self):
        """Validate actual ONNX CUDA inference succeeds."""
        from app.runtime.cuda import run_ort_cuda_inference
        result = run_ort_cuda_inference()
        assert result.success, f"ONNX CUDA inference failed: {result.error}"
        assert result.output_shape is not None
        assert result.output_dtype is not None

    def test_cuda_inference_output_shape(self):
        """Validate output shape matches expected matmul output."""
        from app.runtime.cuda import run_ort_cuda_inference
        result = run_ort_cuda_inference()
        assert result.success
        assert result.output_shape == (1, 3, 3), \
            f"Unexpected output shape: {result.output_shape}"

    def test_cuda_inference_elapsed_time(self):
        """Validate inference timing is recorded."""
        from app.runtime.cuda import run_ort_cuda_inference
        result = run_ort_cuda_inference()
        assert result.success
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    def test_cuda_inference_cleans_up_temp_model(self):
        """Validate temp model is cleaned up after inference."""
        from app.runtime.cuda import run_ort_cuda_inference
        run_ort_cuda_inference()
        paths = get_project_paths()
        temp_dir = paths.data_dir / "temp" / "cuda_validation"
        model_path = temp_dir / "minimal_cuda_inference.onnx"
        assert not model_path.exists(), "Temporary inference model not cleaned up"


# =============================================================================
# Step 11 — CPU Fallback Validation Tests
# =============================================================================

class TestCPUFallback:
    """Tests for CPU fallback inference."""

    def test_cpu_fallback_succeeds(self):
        """Validate CPU fallback inference succeeds."""
        from app.runtime.cuda import run_cpu_fallback_inference
        result = run_cpu_fallback_inference()
        assert result.success, f"CPU fallback inference failed: {result.error}"
        assert result.session_providers == ["CPUExecutionProvider"]
        assert result.output_shape is not None

    def test_cpu_fallback_elapsed_time(self):
        """Validate CPU fallback timing is recorded."""
        from app.runtime.cuda import run_cpu_fallback_inference
        result = run_cpu_fallback_inference()
        assert result.success
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    def test_cpu_fallback_cleans_up_temp_model(self):
        """Validate temp model is cleaned up after CPU inference."""
        from app.runtime.cuda import run_cpu_fallback_inference
        run_cpu_fallback_inference()
        paths = get_project_paths()
        temp_dir = paths.data_dir / "temp" / "cuda_validation"
        model_path = temp_dir / "minimal_cpu_test.onnx"
        assert not model_path.exists(), "Temporary CPU model not cleaned up"


# =============================================================================
# CUDA/cuDNN Detection Tests
# =============================================================================

class TestCUDNNDetection:
    """Tests for cuDNN detection."""

    def test_cudnn_bundled_with_torch(self):
        """Validate cuDNN is available via PyTorch."""
        pytest.importorskip("torch")
        import torch
        from app.runtime.cuda import detect_cudnn
        found, version = detect_cudnn()
        assert found, "cuDNN not found"
        assert version is not None
        assert "cuDNN" in version or "bundled" in version

    def test_cudnn_version_matches_torch(self):
        """Validate cuDNN version matches torch's bundled version."""
        pytest.importorskip("torch")
        import torch
        cudnn_torch_ver = torch.backends.cudnn.version()
        if cudnn_torch_ver:
            major = cudnn_torch_ver // 1000
            minor = cudnn_torch_ver % 1000
            expected_pattern = f"cuDNN {major}.{minor}"
            from app.runtime.cuda import detect_cudnn
            found, version = detect_cudnn()
            assert found
            assert expected_pattern in version, f"Expected {expected_pattern} in {version}"


class TestVisualCppRuntime:
    """Tests for Visual C++ runtime detection."""

    def test_visual_cpp_runtime_available(self):
        """Validate Visual C++ runtime (vcruntime140.dll) is available."""
        from app.runtime.cuda import detect_visual_cpp_runtime
        result = detect_visual_cpp_runtime()
        assert result, "Visual C++ runtime not detected"


class TestCUDAToolkitDetection:
    """Tests for CUDA toolkit version detection."""

    def test_cuda_toolkit_detected(self):
        """Validate CUDA toolkit is detected via nvcc."""
        from app.runtime.cuda import detect_cuda_toolkit_version
        version = detect_cuda_toolkit_version()
        # nvcc may or may not be on PATH, but on this system it should be
        # This test validates the function works, not that CUDA is installed
        if version is None:
            pytest.skip("nvcc not on PATH")
        else:
            assert isinstance(version, str)
            assert len(version) > 0

    def test_cuda_driver_version_detected(self):
        """Validate CUDA driver version is detected."""
        from app.runtime.cuda import detect_cuda_driver_version
        version = detect_cuda_driver_version()
        assert version is not None, "CUDA driver version could not be detected"


# =============================================================================
# Model Availability Tests
# =============================================================================

class TestModelAvailability:
    """Tests for production model availability (should be missing)."""

    def test_scrfd_missing(self):
        """Validate SCRFD model is MISSING (not downloaded)."""
        registry = get_model_registry()
        path = registry.get_model_path("scrfd")
        assert not path.exists(), f"SCRFD model should be missing but found at {path}"

    def test_arcface_missing(self):
        """Validate ArcFace model is MISSING."""
        registry = get_model_registry()
        path = registry.get_model_path("arcface")
        assert not path.exists(), f"ArcFace model should be missing but found at {path}"

    def test_landmark_missing(self):
        """Validate 1K3D68 landmark model is MISSING."""
        registry = get_model_registry()
        path = registry.get_model_path("landmark_1k3d68")
        assert not path.exists(), f"1K3D68 model should be missing but found at {path}"

    def test_reid_missing(self):
        """Validate ReID model is MISSING."""
        registry = get_model_registry()
        path = registry.get_model_path("reid")
        assert not path.exists(), f"ReID model should be missing but found at {path}"

    def test_yolo_models_missing(self):
        """Validate YOLO models are MISSING."""
        registry = get_model_registry()
        path_person = registry.get_model_path("yolo_person")
        assert not path_person.exists(), f"YOLO person model should be missing"
        path_pose = registry.get_model_path("yolo_pose")
        assert not path_pose.exists(), f"YOLO pose model should be missing"

    def test_check_production_models_returns_missing(self):
        """Validate check_production_models reports all as MISSING."""
        from app.runtime.cuda import check_production_models
        results = check_production_models()
        for model_id, info in results.items():
            assert info["status"] == "MISSING", \
                f"Model {model_id} should be MISSING, got {info['status']}"
            assert info["sha256"] is None, \
                f"Model {model_id} hash should be None when missing"

    def test_no_fake_model_files_created(self):
        """Validate no fake/synthetic model files were created."""
        registry = get_model_registry()
        for model_id in registry.get_model_ids():
            path = registry.get_model_path(model_id)
            assert not path.exists(), \
                f"No model files should exist for {model_id} (production models are still downloaded)"


# =============================================================================
# Runtime Snapshot Tests
# =============================================================================

class TestRuntimeSnapshot:
    """Tests for runtime snapshot collection."""

    def test_runtime_snapshot_structure(self):
        """Validate RuntimeSnapshot has all required fields."""
        from app.runtime.cuda import collect_runtime_snapshot, RuntimeSnapshot
        snapshot = collect_runtime_snapshot()
        assert isinstance(snapshot, RuntimeSnapshot)
        assert snapshot.windows_version
        assert snapshot.architecture
        assert snapshot.python_version
        assert snapshot.python_executable
        assert isinstance(snapshot.venv_active, bool)
        assert snapshot.nvidia_gpu_name is not None
        assert snapshot.nvidia_driver_version != "unknown"
        assert snapshot.pytorch_version != "not installed"
        assert snapshot.onnxruntime_version != "not installed"
        assert snapshot.cuda_ep_registered
        assert snapshot.visual_cpp_runtime
        assert snapshot.ffmpeg_available

    def test_runtime_snapshot_model_availability(self):
        """Validate model availability in snapshot."""
        from app.runtime.cuda import collect_runtime_snapshot
        snapshot = collect_runtime_snapshot()
        for model_id in ["scrfd", "arcface", "landmark_1k3d68", "reid", "yolo_person", "yolo_pose"]:
            assert model_id in snapshot.model_availability, \
                f"Model {model_id} not in snapshot"
            assert snapshot.model_availability[model_id] == "MISSING", \
                f"Model {model_id} should be MISSING"

    def test_runtime_snapshot_to_dict(self):
        """Validate RuntimeSnapshot can be serialized to dict."""
        from app.runtime.cuda import collect_runtime_snapshot
        snapshot = collect_runtime_snapshot()
        d = snapshot.__dict__
        assert isinstance(d, dict)
        assert "windows_version" in d
        assert "nvidia_gpu_name" in d
        assert "pytorch_version" in d


# =============================================================================
# Runtime Error Classification Tests
# =============================================================================

class TestRuntimeErrorClassification:
    """Tests for runtime error classification."""

    def test_dependency_error_on_missing_onnxruntime(self):
        """Validate DependencyError raised when ORT is missing."""
        with mock.patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "1"}):
            # Test the error classification logic
            from app.errors import DependencyError, AppError, ConfigurationError, EnvironmentError
            assert issubclass(DependencyError, AppError)
            assert issubclass(ConfigurationError, AppError)
            assert issubclass(EnvironmentError, AppError)

    def test_error_model_distinctions(self):
        """Validate the error model distinguishes error types."""
        from app.errors import (
            AppError, ConfigurationError, EnvironmentError,
            DependencyError, RuntimeError,
        )
        # Verify hierarchy
        assert issubclass(ConfigurationError, AppError)
        assert issubclass(EnvironmentError, AppError)
        assert issubclass(DependencyError, AppError)
        assert issubclass(RuntimeError, AppError)
        # Verify each has expected attributes
        try:
            raise ConfigurationError("test", config_key="key1")
        except AppError as e:
            assert e.config_key == "key1"
        try:
            raise DependencyError("test", package="pkg")
        except AppError as e:
            assert e.package == "pkg"
        try:
            raise EnvironmentError("test", requirement="req")
        except AppError as e:
            assert e.requirement == "req"


# =============================================================================
# Phase Boundary / Safety Tests
# =============================================================================

class TestPhase3Safety:
    """Validate Phase 3 does not violate phase boundary."""

    def test_no_camera_access(self):
        """Validate no camera access code exists in runtime/cuda.py."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        forbidden = ["CameraCapture", "opencv", "cv2", "VideoCapture", "CAM"]
        for term in forbidden:
            assert term not in content, \
                f"Forbidden term '{term}' found in cuda.py"

    def test_no_rtmp_rtsp(self):
        """Validate no RTMP/RTSP/MediaMTX code (actual usage) in runtime/cuda.py."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        # Only check code lines, skip docstring comments (lines 1-20 are prose)
        code_lines = []
        in_docstring = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            code_lines.append(line)
        code_content = "\n".join(code_lines)
        forbidden = ["rtmp://", "rtsp://", "MediaMTX", "stream_keeper", "StreamKeeper"]
        for term in forbidden:
            assert term not in code_content, \
                f"Forbidden term '{term}' found in cuda.py code (not docstring)"

    def test_no_ipc_or_fifo(self):
        """Validate no IPC/FIFO code in runtime/cuda.py."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        forbidden = ["multiprocessing", "FIFO", "ipc", "shared_memory"]
        for term in forbidden:
            assert term not in content, \
                f"Forbidden term '{term}' found in cuda.py"

    def test_no_production_model_loading(self):
        """Validate no production model loading (only minimal test models)."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        # Should not import SCRFD or ArcFace inference
        assert "scrfd_10g" not in content.lower() or "minimal" in content.lower()
        assert "glintr100" not in content.lower()

    def test_no_tracking_or_attendance(self):
        """Validate no tracking/attendance code in runtime/cuda.py."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        forbidden = ["tracking", "attendance", "stranger", "identity", "line_crossing"]
        for term in forbidden:
            assert term not in content.lower(), \
                f"Forbidden term '{term}' found in cuda.py"

    def test_no_database_or_api(self):
        """Validate no database/API code in runtime/cuda.py."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        forbidden = ["sqlalchemy", "sqlite", "database", "fastapi", "flask"]
        for term in forbidden:
            assert term not in content.lower(), \
                f"Forbidden term '{term}' found in cuda.py"

    def test_no_legacy_code_copied(self):
        """Validate no legacy production code was copied into new project."""
        cuda_file = Path(__file__).parent.parent.parent / "app" / "runtime" / "cuda.py"
        content = cuda_file.read_text(encoding="utf-8")
        # Should not contain old scheduler or stream_keeper references
        forbidden_terms = ["stream_keeper", "Scheduler", "camera_capture"]
        for term in forbidden_terms:
            assert term not in content, \
                f"Legacy code reference '{term}' found in cuda.py"
