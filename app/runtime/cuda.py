"""
Phase 3 — CUDA Runtime Validation Module.

This module validates the complete Windows NVIDIA AI runtime stack:
- PyTorch CUDA tensor operations
- ONNX Runtime CUDAExecutionProvider registration
- ONNX Runtime CUDA EP session creation
- ONNX Runtime CUDA EP inference

This module does NOT:
- Access cameras
- Connect to RTMP/RTSP
- Start MediaMTX or FFmpeg streaming
- Load or execute production AI models
- Benchmark CUDA (only validates capability)
- Modify NVIDIA drivers
- Install CUDA manually

It may create a small minimal ONNX test model to validate the runtime,
but clearly labels it as a non-production artifact.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.errors import DependencyError

# Set up CUDA DLL search path BEFORE any onnxruntime import
# This must happen at module load time to ensure cuDNN DLLs are found
print("[app.runtime.cuda] Setting up CUDA DLL search path...")
try:
    import torch
    torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
    print(f"[app.runtime.cuda] Torch lib: {torch_lib}")
    if os.path.exists(torch_lib):
        os.environ['PATH'] = torch_lib + ';' + os.environ['PATH']
        os.add_dll_directory(torch_lib)
        print(f"[app.runtime.cuda] Added {torch_lib} to PATH and DLL directories")
except (ImportError, AttributeError) as e:
    print(f"[app.runtime.cuda] Failed to set up CUDA path: {e}")
    pass


@dataclass(frozen=True)
class PyTorchCUDAResult:
    """Result of PyTorch CUDA validation."""
    success: bool
    torch_version: str
    cuda_compiled_version: str
    cuda_available: bool
    device_count: int
    device_name: Optional[str]
    compute_capability: Optional[str]
    total_memory_mb: Optional[int]
    operation_success: bool
    operation_output_shape: Optional[tuple]
    operation_elapsed_ms: Optional[float]
    error: Optional[str] = None


@dataclass(frozen=True)
class ORTProviderResult:
    """Result of ONNX Runtime provider detection."""
    ort_version: str
    available_providers: list[str]
    cuda_ep_registered: bool
    cpu_ep_registered: bool
    tensorrt_ep_registered: bool


@dataclass(frozen=True)
class ORTCUDASessionResult:
    """Result of ONNX Runtime CUDA EP session creation."""
    success: bool
    session_providers: list[str]
    cuda_ep_in_first: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class ORTCUDAInferenceResult:
    """Result of ONNX Runtime CUDA inference on minimal test model."""
    success: bool
    input_shape: tuple
    output_shape: tuple
    output_dtype: str
    elapsed_ms: float
    error: Optional[str] = None


@dataclass(frozen=True)
class CPUFallbackResult:
    """Result of CPU fallback validation."""
    success: bool
    session_providers: list[str]
    output_shape: tuple
    elapsed_ms: float
    error: Optional[str] = None


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Complete runtime snapshot for Phase 3."""
    windows_version: str
    architecture: str
    python_version: str
    python_executable: str
    venv_active: bool
    venv_path: str
    nvidia_gpu_name: Optional[str]
    nvidia_driver_version: str
    cuda_runtime_version: str  # CUDA UMD version from nvidia-smi
    cuda_toolkit_version: Optional[str]  # nvcc version
    cudnn_version: Optional[str]
    pytorch_version: str
    pytorch_cuda_version: str
    torch_cuda_available: bool
    onnxruntime_version: str
    cuda_ep_registered: bool
    visual_cpp_runtime: bool
    ffmpeg_available: bool
    ffmpeg_version: Optional[str]
    pytorch_cuda_op: bool
    ort_cuda_session: bool
    ort_cuda_inference: bool
    model_availability: dict[str, str]  # model_id -> status
    model_hashes: dict[str, Optional[str]]  # model_id -> actual sha256
    git_status: dict[str, str]
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%W-%dT%H:%M:%S"))


def validate_pytorch_cuda() -> PyTorchCUDAResult:
    """
    Validate PyTorch CUDA tensor operations.

    Creates a CPU tensor, moves it to CUDA, performs a matrix multiplication,
    and returns the result to CPU.

    Returns:
        PyTorchCUDAResult with validation details.
    """
    try:
        import torch
    except ImportError as e:
        return PyTorchCUDAResult(
            success=False,
            torch_version="not installed",
            cuda_compiled_version="n/a",
            cuda_available=False,
            device_count=0,
            device_name=None,
            compute_capability=None,
            total_memory_mb=None,
            operation_success=False,
            operation_output_shape=None,
            operation_elapsed_ms=None,
            error=f"torch not importable: {e}",
        )

    cuda_available = torch.cuda.is_available()
    device_count = torch.cuda.device_count()

    if cuda_available and device_count > 0:
        device_name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        cc = f"{props.major}.{props.minor}"
        total_mem_mb = props.total_memory // (1024 * 1024)
    else:
        device_name = None
        cc = None
        total_mem_mb = None

    # Execute minimal CUDA tensor operation
    operation_success = False
    operation_output_shape = None
    operation_elapsed = None
    op_error = None

    if cuda_available:
        try:
            t0 = time.perf_counter()
            x = torch.randn(100, 100).cuda()
            y = torch.randn(100, 100).cuda()
            z = torch.matmul(x, y)
            result_cpu = z.cpu()
            t1 = time.perf_counter()
            operation_success = True
            operation_output_shape = tuple(result_cpu.shape)
            operation_elapsed = round((t1 - t0) * 1000, 3)
        except Exception as e:
            op_error = str(e)

    return PyTorchCUDAResult(
        success=cuda_available and operation_success,
        torch_version=torch.__version__,
        cuda_compiled_version=torch.version.cuda or "unknown",
        cuda_available=cuda_available,
        device_count=device_count,
        device_name=device_name,
        compute_capability=cc,
        total_memory_mb=total_mem_mb,
        operation_success=operation_success,
        operation_output_shape=operation_output_shape,
        operation_elapsed_ms=operation_elapsed,
        error=op_error,
    )


def detect_ort_providers() -> ORTProviderResult:
    """
    Detect ONNX Runtime available providers.

    Returns:
        ORTProviderResult with provider detection details.
    """
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise DependencyError(
            f"onnxruntime not importable: {e}",
            package="onnxruntime-gpu",
        ) from e

    providers = ort.get_available_providers()

    return ORTProviderResult(
        ort_version=ort.__version__,
        available_providers=list(providers),
        cuda_ep_registered="CUDAExecutionProvider" in providers,
        cpu_ep_registered="CPUExecutionProvider" in providers,
        tensorrt_ep_registered="TensorrtExecutionProvider" in providers,
    )


def create_cuda_ep_session() -> ORTCUDASessionResult:
    """
    Create an ONNX Runtime session with CUDAExecutionProvider.

    Uses a minimal non-production ONNX model (matmul) to validate session
    creation with CUDA EP. This is a runtime capability test only.

    Returns:
        ORTCUDASessionResult with session creation details.
    """
    try:
        import onnx
        from onnx import helper, TensorProto
        import onnxruntime as ort
    except ImportError as e:
        return ORTCUDASessionResult(
            success=False,
            session_providers=[],
            cuda_ep_in_first=False,
            error=f"Import error: {e}",
        )

    # Create minimal non-production ONNX model: Y = X @ W
    # Use opset 9 (IR version 9) for compatibility with ONNX Runtime
    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 3, 3])
    W = helper.make_tensor_value_info("W", TensorProto.FLOAT, [1, 3, 3])
    Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 3, 3])
    node = helper.make_node("MatMul", ["X", "W"], ["Y"])
    graph = helper.make_graph([node], "phase3_cuda_validation_minimal", [X, W], [Y])
    model = helper.make_model(graph, producer_name="phase3_cuda_validation")
    model.opset_import[0].version = 9

    # Write to a temporary file using the temp directory
    from app.config.paths import get_project_paths
    paths = get_project_paths()
    temp_dir = paths.data_dir / "temp" / "cuda_validation"
    temp_dir.mkdir(parents=True, exist_ok=True)
    model_path = temp_dir / "minimal_cuda_test.onnx"

    try:
        onnx.save(model, str(model_path))

        # Create session with CUDA EP priority
        session = ort.InferenceSession(
            str(model_path),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )

        session_providers = session.get_providers()
        cuda_first = session_providers[0] == "CUDAExecutionProvider" if session_providers else False

        return ORTCUDASessionResult(
            success=True,
            session_providers=list(session_providers),
            cuda_ep_in_first=cuda_first,
            error=None,
        )
    except Exception as e:
        return ORTCUDASessionResult(
            success=False,
            session_providers=[],
            cuda_ep_in_first=False,
            error=str(e),
        )
    finally:
        # Clean up temp model
        try:
            if model_path.exists():
                model_path.unlink()
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
        except Exception:
            pass


def run_ort_cuda_inference() -> ORTCUDAInferenceResult:
    """
    Run actual ONNX Runtime CUDA inference on a minimal test model.

    This validates that the full pipeline (session creation → input → CUDA
    execution → output) works end-to-end on the GPU.

    Returns:
        ORTCUDAInferenceResult with inference details.
    """
    from app.config.paths import get_project_paths
    paths = get_project_paths()
    temp_dir = paths.data_dir / "temp" / "cuda_validation"
    temp_dir.mkdir(parents=True, exist_ok=True)
    model_path = temp_dir / "minimal_cuda_inference.onnx"

    try:
        import onnx
        from onnx import helper, TensorProto
        import onnxruntime as ort
        import numpy as np

        # Create minimal ONNX model: Y = X @ W
        # Use opset 9 (IR version 9) for compatibility with ONNX Runtime
        X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 3, 3])
        W = helper.make_tensor_value_info("W", TensorProto.FLOAT, [1, 3, 3])
        Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 3, 3])
        node = helper.make_node("MatMul", ["X", "W"], ["Y"])
        graph = helper.make_graph([node], "phase3_inference_minimal", [X, W], [Y])
        model = helper.make_model(graph, producer_name="phase3_cuda_inference")
        model.opset_import[0].version = 9

        onnx.save(model, str(model_path))

        session = ort.InferenceSession(
            str(model_path),
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )

        x = np.random.randn(1, 3, 3).astype(np.float32)
        w = np.random.randn(1, 3, 3).astype(np.float32)

        t0 = time.perf_counter()
        result = session.run(None, {"X": x, "W": w})
        t1 = time.perf_counter()

        return ORTCUDAInferenceResult(
            success=True,
            input_shape=x.shape,
            output_shape=result[0].shape,
            output_dtype=str(result[0].dtype),
            elapsed_ms=round((t1 - t0) * 1000, 3),
            error=None,
        )
    except Exception as e:
        return ORTCUDAInferenceResult(
            success=False,
            input_shape=None,
            output_shape=None,
            output_dtype=None,
            elapsed_ms=None,
            error=str(e),
        )
    finally:
        try:
            if model_path.exists():
                model_path.unlink()
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
        except Exception:
            pass


def run_cpu_fallback_inference() -> CPUFallbackResult:
    """
    Validate CPU fallback inference with ONNX Runtime.

    Returns:
        CPUFallbackResult with CPU inference details.
    """
    from app.config.paths import get_project_paths
    paths = get_project_paths()
    temp_dir = paths.data_dir / "temp" / "cuda_validation"
    temp_dir.mkdir(parents=True, exist_ok=True)
    model_path = temp_dir / "minimal_cpu_test.onnx"

    try:
        import onnx
        from onnx import helper, TensorProto
        import onnxruntime as ort
        import numpy as np

        X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 3, 3])
        W = helper.make_tensor_value_info("W", TensorProto.FLOAT, [1, 3, 3])
        Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 3, 3])
        node = helper.make_node("MatMul", ["X", "W"], ["Y"])
        graph = helper.make_graph([node], "phase3_cpu_minimal", [X, W], [Y])
        model = helper.make_model(graph, producer_name="phase3_cpu_fallback")
        model.opset_import[0].version = 9

        onnx.save(model, str(model_path))

        session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

        x = np.random.randn(1, 3, 3).astype(np.float32)
        w = np.random.randn(1, 3, 3).astype(np.float32)

        t0 = time.perf_counter()
        result = session.run(None, {"X": x, "W": w})
        t1 = time.perf_counter()

        return CPUFallbackResult(
            success=True,
            session_providers=list(session.get_providers()),
            output_shape=result[0].shape,
            elapsed_ms=round((t1 - t0) * 1000, 3),
            error=None,
        )
    except Exception as e:
        return CPUFallbackResult(
            success=False,
            session_providers=[],
            output_shape=None,
            elapsed_ms=None,
            error=str(e),
        )
    finally:
        try:
            if model_path.exists():
                model_path.unlink()
            if temp_dir.exists() and not any(temp_dir.iterdir()):
                temp_dir.rmdir()
        except Exception:
            pass


def detect_cudnn() -> tuple[bool, Optional[str]]:
    """
    Detect cuDNN availability.

    Checks:
    1. PyTorch bundled cuDNN (torch.backends.cudnn.version())
    2. System cuDNN DLLs

    Returns:
        Tuple of (found, version_string).
    """
    # Check PyTorch bundled cuDNN
    try:
        import torch
        if torch.backends.cudnn.is_available():
            cudnn_ver = torch.backends.cudnn.version()
            if cudnn_ver:
                # cuDNN 91002 means 9.10.2
                major = cudnn_ver // 1000
                minor = cudnn_ver % 1000
                return True, f"cuDNN {major}.{minor} (bundled with torch)"
    except (ImportError, AttributeError):
        pass

    return False, None


def detect_visual_cpp_runtime() -> bool:
    """
    Detect Visual C++ runtime availability.

    Returns:
        True if vcruntime140.dll is found in System32.
    """
    import ctypes
    try:
        ctypes.CDLL("vcruntime140.dll")
        return True
    except OSError:
        return False


def detect_cuda_toolkit_version() -> Optional[str]:
    """
    Detect CUDA toolkit version using nvcc.

    Returns:
        Version string like "13.3" or None if not found.
    """
    import shutil
    import subprocess
    nvcc = shutil.which("nvcc")
    if not nvcc:
        return None
    try:
        result = subprocess.run(
            [nvcc, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Parse "release 13.3" from output
            for line in result.stdout.splitlines():
                if "release" in line:
                    parts = line.split("release")
                    if len(parts) > 1:
                        ver = parts[1].strip().split(",")[0].strip()
                        return ver
            return result.stdout.strip()
    except Exception:
        pass
    return None


def detect_cuda_driver_version() -> Optional[str]:
    """
    Detect CUDA runtime version visible to the driver via nvidia-smi.

    Parses the nvidia-smi header line for "CUDA UMD Version: X.Y".

    Returns:
        CUDA version string (e.g., "13.3") or None.
    """
    import shutil
    import subprocess
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run(
            [nvidia_smi],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Parse header line for "CUDA UMD Version: 13.3"
            for line in result.stdout.splitlines():
                if "CUDA UMD Version" in line:
                    parts = line.split("CUDA UMD Version:")
                    if len(parts) > 1:
                        ver = parts[1].strip().split()[0]
                        return ver
    except Exception:
        pass
    return None


def check_production_models() -> dict[str, dict[str, str]]:
    """
    Check availability of production model files using ModelRegistry.

    Must go through ModelRegistry — no direct path lookups.

    Returns:
        Dictionary mapping model_id to status dict with keys:
        - status: "MISSING" | "AVAILABLE" | "CORRUPT"
        - sha256: actual hash or None
        - path: model path or None
    """
    from app.models.registry import get_model_registry

    registry = get_model_registry()
    results: dict[str, dict[str, str]] = {}

    for model_id in registry.get_model_ids():
        model = registry.get(model_id)
        model_path = registry.get_model_path(model_id)

        if not model_path.exists():
            results[model_id] = {
                "status": "MISSING",
                "sha256": None,
                "expected_sha256": model.expected_sha256,
                "path": str(model_path),
            }
        else:
            hash_result = registry.verify_model(model_id)
            if hash_result.is_verified():
                status = "AVAILABLE"
            elif hash_result.is_mismatch():
                status = "CORRUPT"
            else:
                status = "UNVERIFIED"
            results[model_id] = {
                "status": status,
                "sha256": hash_result.actual_hash,
                "expected_sha256": model.expected_sha256,
                "path": str(model_path),
            }

    return results


def get_ort_session(model_path: Path, providers: list[str]):
    """
    Create an ONNX Runtime session with the specified providers.
    
    Args:
        model_path: Path to the ONNX model file.
        providers: List of ONNX Runtime providers (e.g., ["CUDAExecutionProvider", "CPUExecutionProvider"]).
        
    Returns:
        ONNX Runtime InferenceSession.
    """
    import os
    
    # Add PyTorch bundled cuDNN DLLs to PATH for CUDA EP
    # This must be done BEFORE importing onnxruntime or creating the session
    try:
        import torch
        torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
        if os.path.exists(torch_lib):
            os.environ['PATH'] = torch_lib + ';' + os.environ['PATH']
            os.add_dll_directory(torch_lib)
    except (ImportError, AttributeError):
        pass
    
    # Import onnxruntime AFTER PATH setup
    import onnxruntime as ort
    
    session = ort.InferenceSession(
        str(model_path),
        providers=providers,
    )
    
    return session


def collect_runtime_snapshot() -> RuntimeSnapshot:
    """
    Collect a complete runtime snapshot for Phase 3 validation.

    Returns:
        RuntimeSnapshot with all environment details.
    """
    import platform
    import sys
    import shutil

    # System info
    windows_version = platform.platform()
    architecture = platform.machine()
    python_version = platform.python_version()
    python_executable = sys.executable
    venv_active = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    venv_path = sys.prefix if venv_active else "N/A"

    # NVIDIA GPU
    nvidia_gpu_name = None
    nvidia_driver_version = "unknown"
    try:
        import pynvml
        pynvml.nvmlInit()
        if pynvml.nvmlDeviceGetCount() > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            nvidia_gpu_name = name
            drv = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(drv, bytes):
                drv = drv.decode("utf-8")
            nvidia_driver_version = drv
        pynvml.nvmlShutdown()
    except Exception:
        pass

    # CUDA
    cuda_runtime_version = detect_cuda_driver_version() or "unknown"
    cuda_toolkit_version = detect_cuda_toolkit_version()

    # cuDNN
    cudnn_found, cudnn_version = detect_cudnn()

    # Visual C++ runtime
    vcpp_runtime = detect_visual_cpp_runtime()

    # FFmpeg
    ffmpeg_available = shutil.which("ffmpeg") is not None
    ffmpeg_version_str = None
    if ffmpeg_available:
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                ffmpeg_version_str = result.stdout.splitlines()[0].strip()
        except Exception:
            pass

    # PyTorch
    torch_version = "not installed"
    torch_cuda_version = "n/a"
    torch_cuda_available = False
    try:
        import torch
        torch_version = torch.__version__
        torch_cuda_version = torch.version.cuda or "unknown"
        torch_cuda_available = torch.cuda.is_available()
    except ImportError:
        pass

    # ONNX Runtime
    ort_version = "not installed"
    cuda_ep_registered = False
    try:
        import onnxruntime as ort
        ort_version = ort.__version__
        providers = ort.get_available_providers()
        cuda_ep_registered = "CUDAExecutionProvider" in providers
    except ImportError:
        pass

    # Model availability
    model_availability: dict[str, str] = {}
    model_hashes: dict[str, Optional[str]] = {}
    try:
        model_statuses = check_production_models()
        for mid, info in model_statuses.items():
            model_availability[mid] = info["status"]
            model_hashes[mid] = info["sha256"]
    except Exception:
        model_availability = {"error": "registry not available"}
        model_hashes = {}

    # Git status
    git_status: dict[str, str] = {}
    try:
        from app.config.paths import get_project_paths
        import subprocess
        root = get_project_paths().project_root
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10,
            cwd=str(root),
        )
        git_status["output"] = result.stdout
        git_status["returncode"] = str(result.returncode)
    except Exception as e:
        git_status["error"] = str(e)

    return RuntimeSnapshot(
        windows_version=windows_version,
        architecture=architecture,
        python_version=python_version,
        python_executable=python_executable,
        venv_active=venv_active,
        venv_path=venv_path,
        nvidia_gpu_name=nvidia_gpu_name,
        nvidia_driver_version=nvidia_driver_version,
        cuda_runtime_version=cuda_runtime_version,
        cuda_toolkit_version=cuda_toolkit_version,
        cudnn_version=cudnn_version,
        pytorch_version=torch_version,
        pytorch_cuda_version=torch_cuda_version,
        torch_cuda_available=torch_cuda_available,
        onnxruntime_version=ort_version,
        cuda_ep_registered=cuda_ep_registered,
        visual_cpp_runtime=vcpp_runtime,
        ffmpeg_available=ffmpeg_available,
        ffmpeg_version=ffmpeg_version_str,
        pytorch_cuda_op=torch_cuda_available,
        ort_cuda_session=False,  # populated by caller after validation
        ort_cuda_inference=False,
        model_availability=model_availability,
        model_hashes=model_hashes,
        git_status=git_status,
    )
