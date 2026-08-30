"""
Runtime detection module for Windows native AI attendance system.

Provides structured runtime information including:
- OS and architecture
- Python version and executable path
- Virtual environment status
- NVIDIA GPU availability
- CUDA availability
- FFmpeg availability

Phase 3 additions:
- PyTorch CUDA tensor operations
- ONNX Runtime provider detection
- ONNX Runtime CUDA EP session creation
- ONNX Runtime CUDA inference validation
- CPU fallback validation
"""
from .detector import RuntimeInfo, detect_runtime
from .gpu import CUDAInfo, GPUInfo, detect_cuda, detect_nvidia_gpus, get_cuda_version, get_gpu_count, is_cuda_available
from .ffmpeg import FFmpegInfo, detect_ffmpeg, get_ffmpeg_path, get_ffmpeg_version, is_ffmpeg_available
from .cuda import (
    PyTorchCUDAResult,
    ORTProviderResult,
    ORTCUDASessionResult,
    ORTCUDAInferenceResult,
    CPUFallbackResult,
    RuntimeSnapshot,
    validate_pytorch_cuda,
    detect_ort_providers,
    create_cuda_ep_session,
    run_ort_cuda_inference,
    run_cpu_fallback_inference,
    detect_cudnn,
    detect_visual_cpp_runtime,
    detect_cuda_toolkit_version,
    detect_cuda_driver_version,
    check_production_models,
    collect_runtime_snapshot,
)

__all__ = [
    "RuntimeInfo",
    "detect_runtime",
    "GPUInfo",
    "CUDAInfo",
    "detect_nvidia_gpus",
    "detect_cuda",
    "is_cuda_available",
    "get_cuda_version",
    "get_gpu_count",
    "FFmpegInfo",
    "detect_ffmpeg",
    "is_ffmpeg_available",
    "get_ffmpeg_path",
    "get_ffmpeg_version",
    # Phase 3 CUDA runtime validation
    "PyTorchCUDAResult",
    "ORTProviderResult",
    "ORTCUDASessionResult",
    "ORTCUDAInferenceResult",
    "CPUFallbackResult",
    "RuntimeSnapshot",
    "validate_pytorch_cuda",
    "detect_ort_providers",
    "create_cuda_ep_session",
    "run_ort_cuda_inference",
    "run_cpu_fallback_inference",
    "detect_cudnn",
    "detect_visual_cpp_runtime",
    "detect_cuda_toolkit_version",
    "detect_cuda_driver_version",
    "check_production_models",
    "collect_runtime_snapshot",
]
