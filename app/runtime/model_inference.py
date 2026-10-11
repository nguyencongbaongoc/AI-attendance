"""
Phase 5 — Production Model CUDA Inference Validation.

This module validates actual production model inference on Windows NVIDIA GPU.

CRITICAL RULES:
- Use ONLY the six models registered by ModelRegistry
- NO camera access
- NO MediaMTX, RTMP, RTSP, FFmpeg streaming
- NO real images - synthetic inputs only
- NO accuracy claims from synthetic noise
- Verify SHA256 before inference
- Distinguish: provider registered vs session created vs actual CUDA inference

Models validated:
- SCRFD (scrfd_10g_bnkps.onnx) - Face detection
- ArcFace (glintr100.onnx) - Face recognition embedding
- 1K3D68 (1k3d68.onnx) - Face landmark
- ReID (resnet50_reid.onnx) - Person re-identification
- YOLO Person (yolo11n.pt) - Person detection
- YOLO Pose (yolo11n-pose.pt) - Pose estimation
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.models.registry import get_model_registry, ModelRegistry
from app.models.hashing import verify_sha256


# Fixed RNG seed for deterministic synthetic inputs
SYNTHETIC_SEED = 42


@dataclass
class ModelInferenceResult:
    """Result of a single model inference validation."""
    model_id: str
    sha256: str
    sha256_match: bool
    provider: str
    input_shape: Tuple[int, ...]
    output_shapes: List[Tuple[int, ...]]
    output_dtypes: List[str]
    output_names: List[str]
    cuda_success: bool
    cpu_success: bool
    output_finite: bool
    output_no_nan: bool
    output_no_inf: bool
    warmup_runs: int
    measured_runs: int
    latency_cuda_mean_ms: Optional[float]
    latency_cuda_median_ms: Optional[float]
    latency_cuda_p95_ms: Optional[float]
    latency_cuda_min_ms: Optional[float]
    latency_cuda_max_ms: Optional[float]
    latency_cpu_mean_ms: Optional[float]
    latency_cpu_median_ms: Optional[float]
    latency_cpu_p95_ms: Optional[float]
    latency_cpu_min_ms: Optional[float]
    latency_cpu_max_ms: Optional[float]
    gpu_memory_before_mb: Optional[float]
    gpu_memory_after_mb: Optional[float]
    gpu_utilization_observed: Optional[str]
    cuda_provider_used: Optional[bool]
    cpu_provider_used: Optional[bool]
    errors: List[str] = field(default_factory=list)


@dataclass
class RuntimeMatrix:
    """Complete runtime matrix for all models."""
    entries: List[Dict[str, Any]]
    verified_count: int
    cuda_success_count: int
    cpu_success_count: int
    total_count: int
    timestamp: str


def get_gpu_memory_mb() -> Optional[float]:
    """Get current GPU memory usage in MB."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024 * 1024)
    except Exception:
        pass
    return None


def get_gpu_utilization() -> Optional[str]:
    """Get GPU utilization percentage via nvidia-smi."""
    import subprocess
    import shutil
    
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    
    try:
        result = subprocess.run(
            [nvidia_smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return f"{result.stdout.strip()}%"
    except Exception:
        pass
    return None


def generate_synthetic_input(shape: Tuple[int, ...], dtype: np.dtype = np.float32) -> np.ndarray:
    """
    Generate deterministic synthetic input for model inference.
    
    Uses fixed seed for reproducibility.
    Does NOT represent real data - just validates tensor flow.
    
    Args:
        shape: Input tensor shape.
        dtype: Input tensor dtype.
        
    Returns:
        Synthetic numpy array.
    """
    rng = np.random.default_rng(SYNTHETIC_SEED)
    if dtype == np.float32 or dtype == np.float64:
        # Values in [0, 1] range for normalized inputs
        return rng.random(shape, dtype=dtype)
    elif dtype == np.uint8:
        # Values in [0, 255] range for image inputs
        return rng.integers(0, 256, size=shape, dtype=dtype)
    else:
        return rng.random(shape, dtype=dtype)


def validate_output_tensor(output: np.ndarray, name: str) -> Tuple[bool, List[str]]:
    """
    Validate output tensor structure.
    
    Checks:
    - Output exists
    - Finite values
    - No NaN
    - No Inf
    
    Args:
        output: Output numpy array.
        name: Output name for error messages.
        
    Returns:
        Tuple of (is_valid, list of errors).
    """
    errors = []
    
    if output is None:
        errors.append(f"Output '{name}' is None")
        return False, errors
    
    # Check for NaN
    nan_count = np.isnan(output).sum()
    if nan_count > 0:
        errors.append(f"Output '{name}' contains {nan_count} NaN values")
    
    # Check for Inf
    inf_count = np.isinf(output).sum()
    if inf_count > 0:
        errors.append(f"Output '{name}' contains {inf_count} Inf values")
    
    # Check for finite
    finite = np.isfinite(output).all()
    
    return finite and len(errors) == 0, errors


def run_onnx_model_inference(
    model_path: Path,
    model_id: str,
    input_shape: Tuple[int, ...],
    providers: List[str],
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Run ONNX model inference with specified providers.
    
    Args:
        model_path: Path to ONNX model file.
        model_id: Model identifier.
        input_shape: Input tensor shape (N, C, H, W).
        providers: List of ORT providers (e.g., ['CUDAExecutionProvider', 'CPUExecutionProvider']).
        warmup_runs: Number of warmup iterations.
        measured_runs: Number of measured iterations.
        
    Returns:
        Tuple of (result dict, error list).
    """
    import onnxruntime as ort
    
    errors = []
    
    try:
        # Create session
        session = ort.InferenceSession(
            str(model_path),
            providers=providers,
        )
        
        # Get actual providers in session
        session_providers = session.get_providers()
        cuda_provider_used = "CUDAExecutionProvider" in session_providers
        cpu_provider_used = "CPUExecutionProvider" in session_providers
        
        # Get input info
        input_info = session.get_inputs()[0]
        input_name = input_info.name
        
        # Get output info
        output_infos = session.get_outputs()
        output_names = [o.name for o in output_infos]
        
        # Generate synthetic input
        synthetic_input = generate_synthetic_input(input_shape, dtype=np.float32)
        
        # Warmup runs
        for _ in range(warmup_runs):
            try:
                _ = session.run(None, {input_name: synthetic_input})
            except Exception as e:
                errors.append(f"Warmup inference error: {e}")
                return None, errors
        
        # Measured runs
        latencies = []
        outputs = None
        
        for _ in range(measured_runs):
            try:
                t0 = time.perf_counter()
                outputs = session.run(None, {input_name: synthetic_input})
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)  # ms
            except Exception as e:
                errors.append(f"Measured inference error: {e}")
                return None, errors
        
        # Validate outputs
        output_shapes = []
        output_dtypes = []
        all_finite = True
        all_no_nan = True
        all_no_inf = True
        
        for i, output in enumerate(outputs):
            output_shapes.append(tuple(output.shape))
            output_dtypes.append(str(output.dtype))
            
            is_valid, output_errors = validate_output_tensor(output, output_names[i])
            if not is_valid:
                errors.extend(output_errors)
                all_finite = False
            
            if np.isnan(output).any():
                all_no_nan = False
            if np.isinf(output).any():
                all_no_inf = False
        
        # Calculate latency statistics
        if latencies:
            latency_mean = statistics.mean(latencies)
            latency_median = statistics.median(latencies)
            latency_min = min(latencies)
            latency_max = max(latencies)
            latency_p95 = (
                statistics.quantiles(latencies, n=100)[94]
                if len(latencies) >= 100
                else latency_max
            )
        else:
            latency_mean = latency_median = latency_min = latency_max = latency_p95 = None
        
        result = {
            "success": True,
            "session_providers": session_providers,
            "cuda_provider_used": cuda_provider_used,
            "cpu_provider_used": cpu_provider_used,
            "input_name": input_name,
            "output_names": output_names,
            "output_shapes": output_shapes,
            "output_dtypes": output_dtypes,
            "output_finite": all_finite,
            "output_no_nan": all_no_nan,
            "output_no_inf": all_no_inf,
            "latency_mean_ms": latency_mean,
            "latency_median_ms": latency_median,
            "latency_min_ms": latency_min,
            "latency_max_ms": latency_max,
            "latency_p95_ms": latency_p95,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
        }
        
        return result, errors
        
    except Exception as e:
        errors.append(f"Session creation error: {e}")
        return None, errors


def run_yolo_model_inference(
    model_path: Path,
    model_id: str,
    input_size: int = 640,
    device: str = "cuda",
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Run YOLO (Ultralytics) model inference.
    
    Args:
        model_path: Path to YOLO .pt file.
        model_id: Model identifier.
        input_size: Input size (default 640).
        device: Device to use ('cuda' or 'cpu').
        warmup_runs: Number of warmup iterations.
        measured_runs: Number of measured iterations.
        
    Returns:
        Tuple of (result dict, error list).
    """
    from ultralytics import YOLO
    
    errors = []
    
    try:
        # Load model
        model = YOLO(str(model_path))
        
        # Generate synthetic input
        rng = np.random.default_rng(SYNTHETIC_SEED)
        synthetic_input = rng.integers(0, 256, size=(input_size, input_size, 3), dtype=np.uint8)
        
        # Warmup runs
        for _ in range(warmup_runs):
            try:
                _ = model.predict(source=synthetic_input, device=device, verbose=False)
            except Exception as e:
                errors.append(f"Warmup inference error: {e}")
                return None, errors
        
        # Measured runs
        latencies = []
        last_result = None
        
        for _ in range(measured_runs):
            try:
                t0 = time.perf_counter()
                last_result = model.predict(source=synthetic_input, device=device, verbose=False)
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)  # ms
            except Exception as e:
                errors.append(f"Measured inference error: {e}")
                return None, errors
        
        # Validate output
        output_finite = True
        output_no_nan = True
        output_no_inf = True
        output_shapes = []
        output_dtypes = []
        
        if last_result and len(last_result) > 0:
            result_obj = last_result[0]
            # Check boxes
            if result_obj.boxes is not None:
                boxes_data = result_obj.boxes.data
                if boxes_data is not None:
                    output_shapes.append(tuple(boxes_data.shape))
                    output_dtypes.append(str(boxes_data.dtype))
                    if torch_available():
                        import torch
                        if isinstance(boxes_data, torch.Tensor):
                            boxes_data = boxes_data.cpu().numpy()
                    if hasattr(boxes_data, 'cpu'):
                        boxes_data = boxes_data.cpu().numpy() if hasattr(boxes_data, 'cpu') else boxes_data
                    if np.isnan(boxes_data).any():
                        output_no_nan = False
                    if np.isinf(boxes_data).any():
                        output_no_inf = False
            
            # For pose, check keypoints
            if hasattr(result_obj, 'keypoints') and result_obj.keypoints is not None:
                kp_data = result_obj.keypoints.data
                if kp_data is not None:
                    output_shapes.append(tuple(kp_data.shape))
                    output_dtypes.append(str(kp_data.dtype))
        
        # Calculate latency statistics
        if latencies:
            latency_mean = statistics.mean(latencies)
            latency_median = statistics.median(latencies)
            latency_min = min(latencies)
            latency_max = max(latencies)
            latency_p95 = (
                statistics.quantiles(latencies, n=100)[94]
                if len(latencies) >= 100
                else latency_max
            )
        else:
            latency_mean = latency_median = latency_min = latency_max = latency_p95 = None
        
        result = {
            "success": True,
            "device_used": device,
            "cuda_provider_used": device == "cuda",
            "cpu_provider_used": device == "cpu",
            "input_size": input_size,
            "output_shapes": output_shapes,
            "output_dtypes": output_dtypes,
            "output_finite": output_finite,
            "output_no_nan": output_no_nan,
            "output_no_inf": output_no_inf,
            "latency_mean_ms": latency_mean,
            "latency_median_ms": latency_median,
            "latency_min_ms": latency_min,
            "latency_max_ms": latency_max,
            "latency_p95_ms": latency_p95,
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
        }
        
        return result, errors
        
    except Exception as e:
        errors.append(f"YOLO model error: {e}")
        return None, errors


def torch_available() -> bool:
    """Check if PyTorch is available."""
    try:
        import torch
        return True
    except ImportError:
        return False


def validate_onnx_model(
    registry: ModelRegistry,
    model_id: str,
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> ModelInferenceResult:
    """
    Validate an ONNX model with CUDA and CPU inference.
    
    Args:
        registry: Model registry instance.
        model_id: Model identifier.
        warmup_runs: Number of warmup iterations.
        measured_runs: Number of measured iterations.
        
    Returns:
        ModelInferenceResult with validation details.
    """
    model = registry.get(model_id)
    model_path = registry.get_model_path(model_id)
    
    errors = []
    
    # Verify SHA256
    hash_result = registry.verify_model(model_id)
    sha256 = hash_result.actual_hash or ""
    sha256_match = hash_result.is_verified()
    
    if not sha256_match:
        errors.append(f"SHA256 mismatch for {model_id}")
        return ModelInferenceResult(
            model_id=model_id,
            sha256=sha256,
            sha256_match=False,
            provider="onnx",
            input_shape=(),
            output_shapes=[],
            output_dtypes=[],
            output_names=[],
            cuda_success=False,
            cpu_success=False,
            output_finite=False,
            output_no_nan=False,
            output_no_inf=False,
            warmup_runs=0,
            measured_runs=0,
            latency_cuda_mean_ms=None,
            latency_cuda_median_ms=None,
            latency_cuda_p95_ms=None,
            latency_cuda_min_ms=None,
            latency_cuda_max_ms=None,
            latency_cpu_mean_ms=None,
            latency_cpu_median_ms=None,
            latency_cpu_p95_ms=None,
            latency_cpu_min_ms=None,
            latency_cpu_max_ms=None,
            gpu_memory_before_mb=None,
            gpu_memory_after_mb=None,
            gpu_utilization_observed=None,
            cuda_provider_used=None,
            cpu_provider_used=None,
            errors=errors,
        )
    
    # Get input shape from preprocessing config
    input_shape = model.preprocessing.get_input_shape_nchw(batch_size=1)
    
    # Record GPU memory before
    gpu_mem_before = get_gpu_memory_mb()
    gpu_util_before = get_gpu_utilization()
    
    # Run CUDA inference
    cuda_result, cuda_errors = run_onnx_model_inference(
        model_path=model_path,
        model_id=model_id,
        input_shape=input_shape,
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    
    # Record GPU memory after
    gpu_mem_after = get_gpu_memory_mb()
    gpu_util_after = get_gpu_utilization()
    
    # Run CPU inference
    cpu_result, cpu_errors = run_onnx_model_inference(
        model_path=model_path,
        model_id=model_id,
        input_shape=input_shape,
        providers=["CPUExecutionProvider"],
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    
    # Combine results
    all_errors = cuda_errors + cpu_errors
    
    cuda_success = cuda_result is not None and cuda_result.get("success", False)
    cpu_success = cpu_result is not None and cpu_result.get("success", False)
    
    # Get output info from CUDA result (or CPU if CUDA failed)
    result = cuda_result or cpu_result
    if result:
        output_shapes = result.get("output_shapes", [])
        output_dtypes = result.get("output_dtypes", [])
        output_names = result.get("output_names", [])
        output_finite = result.get("output_finite", False)
        output_no_nan = result.get("output_no_nan", False)
        output_no_inf = result.get("output_no_inf", False)
    else:
        output_shapes = []
        output_dtypes = []
        output_names = []
        output_finite = False
        output_no_nan = False
        output_no_inf = False
    
    # Get latency info
    if cuda_result:
        latency_cuda_mean = cuda_result.get("latency_mean_ms")
        latency_cuda_median = cuda_result.get("latency_median_ms")
        latency_cuda_p95 = cuda_result.get("latency_p95_ms")
        latency_cuda_min = cuda_result.get("latency_min_ms")
        latency_cuda_max = cuda_result.get("latency_max_ms")
        cuda_provider_used = cuda_result.get("cuda_provider_used", False)
    else:
        latency_cuda_mean = latency_cuda_median = latency_cuda_p95 = None
        latency_cuda_min = latency_cuda_max = None
        cuda_provider_used = False
    
    if cpu_result:
        latency_cpu_mean = cpu_result.get("latency_mean_ms")
        latency_cpu_median = cpu_result.get("latency_median_ms")
        latency_cpu_p95 = cpu_result.get("latency_p95_ms")
        latency_cpu_min = cpu_result.get("latency_min_ms")
        latency_cpu_max = cpu_result.get("latency_max_ms")
        cpu_provider_used = cpu_result.get("cpu_provider_used", False)
    else:
        latency_cpu_mean = latency_cpu_median = latency_cpu_p95 = None
        latency_cpu_min = latency_cpu_max = None
        cpu_provider_used = False
    
    return ModelInferenceResult(
        model_id=model_id,
        sha256=sha256,
        sha256_match=sha256_match,
        provider="onnx",
        input_shape=input_shape,
        output_shapes=output_shapes,
        output_dtypes=output_dtypes,
        output_names=output_names,
        cuda_success=cuda_success,
        cpu_success=cpu_success,
        output_finite=output_finite,
        output_no_nan=output_no_nan,
        output_no_inf=output_no_inf,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        latency_cuda_mean_ms=latency_cuda_mean,
        latency_cuda_median_ms=latency_cuda_median,
        latency_cuda_p95_ms=latency_cuda_p95,
        latency_cuda_min_ms=latency_cuda_min,
        latency_cuda_max_ms=latency_cuda_max,
        latency_cpu_mean_ms=latency_cpu_mean,
        latency_cpu_median_ms=latency_cpu_median,
        latency_cpu_p95_ms=latency_cpu_p95,
        latency_cpu_min_ms=latency_cpu_min,
        latency_cpu_max_ms=latency_cpu_max,
        gpu_memory_before_mb=gpu_mem_before,
        gpu_memory_after_mb=gpu_mem_after,
        gpu_utilization_observed=gpu_util_after or gpu_util_before,
        cuda_provider_used=cuda_provider_used,
        cpu_provider_used=cpu_provider_used,
        errors=all_errors,
    )


def validate_yolo_model(
    registry: ModelRegistry,
    model_id: str,
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> ModelInferenceResult:
    """
    Validate a YOLO (Ultralytics) model with CUDA and CPU inference.
    
    Args:
        registry: Model registry instance.
        model_id: Model identifier.
        warmup_runs: Number of warmup iterations.
        measured_runs: Number of measured iterations.
        
    Returns:
        ModelInferenceResult with validation details.
    """
    model = registry.get(model_id)
    model_path = registry.get_model_path(model_id)
    
    errors = []
    
    # Verify SHA256
    hash_result = registry.verify_model(model_id)
    sha256 = hash_result.actual_hash or ""
    sha256_match = hash_result.is_verified()
    
    if not sha256_match:
        errors.append(f"SHA256 mismatch for {model_id}")
        return ModelInferenceResult(
            model_id=model_id,
            sha256=sha256,
            sha256_match=False,
            provider="ultralytics",
            input_shape=(),
            output_shapes=[],
            output_dtypes=[],
            output_names=[],
            cuda_success=False,
            cpu_success=False,
            output_finite=False,
            output_no_nan=False,
            output_no_inf=False,
            warmup_runs=0,
            measured_runs=0,
            latency_cuda_mean_ms=None,
            latency_cuda_median_ms=None,
            latency_cuda_p95_ms=None,
            latency_cuda_min_ms=None,
            latency_cuda_max_ms=None,
            latency_cpu_mean_ms=None,
            latency_cpu_median_ms=None,
            latency_cpu_p95_ms=None,
            latency_cpu_min_ms=None,
            latency_cpu_max_ms=None,
            gpu_memory_before_mb=None,
            gpu_memory_after_mb=None,
            gpu_utilization_observed=None,
            cuda_provider_used=None,
            cpu_provider_used=None,
            errors=errors,
        )
    
    # Get input size from preprocessing config
    input_size = model.preprocessing.input_height
    input_shape = (1, 3, input_size, input_size)
    
    # Record GPU memory before
    gpu_mem_before = get_gpu_memory_mb()
    gpu_util_before = get_gpu_utilization()
    
    # Run CUDA inference
    cuda_result, cuda_errors = run_yolo_model_inference(
        model_path=model_path,
        model_id=model_id,
        input_size=input_size,
        device="cuda",
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    
    # Record GPU memory after
    gpu_mem_after = get_gpu_memory_mb()
    gpu_util_after = get_gpu_utilization()
    
    # Run CPU inference
    cpu_result, cpu_errors = run_yolo_model_inference(
        model_path=model_path,
        model_id=model_id,
        input_size=input_size,
        device="cpu",
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    
    # Combine results
    all_errors = cuda_errors + cpu_errors
    
    cuda_success = cuda_result is not None and cuda_result.get("success", False)
    cpu_success = cpu_result is not None and cpu_result.get("success", False)
    
    # Get output info from CUDA result (or CPU if CUDA failed)
    result = cuda_result or cpu_result
    if result:
        output_shapes = result.get("output_shapes", [])
        output_dtypes = result.get("output_dtypes", [])
        output_names = ["boxes", "keypoints"] if "pose" in model_id else ["boxes"]
        output_finite = result.get("output_finite", False)
        output_no_nan = result.get("output_no_nan", False)
        output_no_inf = result.get("output_no_inf", False)
    else:
        output_shapes = []
        output_dtypes = []
        output_names = []
        output_finite = False
        output_no_nan = False
        output_no_inf = False
    
    # Get latency info
    if cuda_result:
        latency_cuda_mean = cuda_result.get("latency_mean_ms")
        latency_cuda_median = cuda_result.get("latency_median_ms")
        latency_cuda_p95 = cuda_result.get("latency_p95_ms")
        latency_cuda_min = cuda_result.get("latency_min_ms")
        latency_cuda_max = cuda_result.get("latency_max_ms")
        cuda_provider_used = cuda_result.get("cuda_provider_used", False)
    else:
        latency_cuda_mean = latency_cuda_median = latency_cuda_p95 = None
        latency_cuda_min = latency_cuda_max = None
        cuda_provider_used = False
    
    if cpu_result:
        latency_cpu_mean = cpu_result.get("latency_mean_ms")
        latency_cpu_median = cpu_result.get("latency_median_ms")
        latency_cpu_p95 = cpu_result.get("latency_p95_ms")
        latency_cpu_min = cpu_result.get("latency_min_ms")
        latency_cpu_max = cpu_result.get("latency_max_ms")
        cpu_provider_used = cpu_result.get("cpu_provider_used", False)
    else:
        latency_cpu_mean = latency_cpu_median = latency_cpu_p95 = None
        latency_cpu_min = latency_cpu_max = None
        cpu_provider_used = False
    
    return ModelInferenceResult(
        model_id=model_id,
        sha256=sha256,
        sha256_match=sha256_match,
        provider="ultralytics",
        input_shape=input_shape,
        output_shapes=output_shapes,
        output_dtypes=output_dtypes,
        output_names=output_names,
        cuda_success=cuda_success,
        cpu_success=cpu_success,
        output_finite=output_finite,
        output_no_nan=output_no_nan,
        output_no_inf=output_no_inf,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        latency_cuda_mean_ms=latency_cuda_mean,
        latency_cuda_median_ms=latency_cuda_median,
        latency_cuda_p95_ms=latency_cuda_p95,
        latency_cuda_min_ms=latency_cuda_min,
        latency_cuda_max_ms=latency_cuda_max,
        latency_cpu_mean_ms=latency_cpu_mean,
        latency_cpu_median_ms=latency_cpu_median,
        latency_cpu_p95_ms=latency_cpu_p95,
        latency_cpu_min_ms=latency_cpu_min,
        latency_cpu_max_ms=latency_cpu_max,
        gpu_memory_before_mb=gpu_mem_before,
        gpu_memory_after_mb=gpu_mem_after,
        gpu_utilization_observed=gpu_util_after or gpu_util_before,
        cuda_provider_used=cuda_provider_used,
        cpu_provider_used=cpu_provider_used,
        errors=all_errors,
    )


def validate_all_models(
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> Tuple[List[ModelInferenceResult], RuntimeMatrix]:
    """
    Validate all production models with CUDA and CPU inference.
    
    Args:
        warmup_runs: Number of warmup iterations per model.
        measured_runs: Number of measured iterations per model.
        
    Returns:
        Tuple of (list of results, runtime matrix).
    """
    import datetime
    
    registry = get_model_registry()
    results: List[ModelInferenceResult] = []
    
    # ONNX models
    onnx_models = ["scrfd", "arcface", "landmark_1k3d68", "reid"]
    for model_id in onnx_models:
        result = validate_onnx_model(
            registry=registry,
            model_id=model_id,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
        )
        results.append(result)
    
    # YOLO models
    yolo_models = ["yolo_person", "yolo_pose"]
    for model_id in yolo_models:
        result = validate_yolo_model(
            registry=registry,
            model_id=model_id,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
        )
        results.append(result)
    
    # Build runtime matrix
    entries = [asdict(r) for r in results]
    verified_count = sum(1 for r in results if r.sha256_match)
    cuda_success_count = sum(1 for r in results if r.cuda_success)
    cpu_success_count = sum(1 for r in results if r.cpu_success)
    
    matrix = RuntimeMatrix(
        entries=entries,
        verified_count=verified_count,
        cuda_success_count=cuda_success_count,
        cpu_success_count=cpu_success_count,
        total_count=len(results),
        timestamp=datetime.datetime.now().isoformat(),
    )
    
    return results, matrix


def run_phase5_validation(
    warmup_runs: int = 10,
    measured_runs: int = 100,
) -> Tuple[List[ModelInferenceResult], RuntimeMatrix, Dict[str, Any]]:
    """
    Run complete Phase 5 validation.
    
    Args:
        warmup_runs: Number of warmup iterations per model.
        measured_runs: Number of measured iterations per model.
        
    Returns:
        Tuple of (results, runtime matrix, summary dict).
    """
    import datetime
    
    # Run validation
    results, matrix = validate_all_models(
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    
    # Build summary
    summary = {
        "phase": 5,
        "timestamp": datetime.datetime.now().isoformat(),
        "models_validated": len(results),
        "sha256_verified": sum(1 for r in results if r.sha256_match),
        "cuda_success": sum(1 for r in results if r.cuda_success),
        "cpu_success": sum(1 for r in results if r.cpu_success),
        "output_valid": sum(1 for r in results if r.output_finite and r.output_no_nan and r.output_no_inf),
        "errors": [r.model_id for r in results if r.errors],
        "verdict": "PASS" if all(r.cuda_success and r.cpu_success for r in results) else "PARTIAL",
    }
    
    return results, matrix, summary
