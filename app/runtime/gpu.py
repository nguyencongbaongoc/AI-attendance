"""
GPU/CUDA detection contract for Windows native AI attendance system.

This module provides ONLY the detection contract.
It answers:
- NVIDIA GPU present?
- CUDA runtime visible?
- CUDA-capable Python stack available?

This module does NOT:
- Implement model inference
- Benchmark CUDA
- Modify NVIDIA drivers
- Install CUDA manually
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GPUInfo:
    """Information about a detected GPU."""

    index: int
    name: str
    memory_total_mb: Optional[int] = None
    driver_version: Optional[str] = None
    cuda_compute_capability: Optional[str] = None


@dataclass(frozen=True)
class CUDAInfo:
    """CUDA availability information."""

    available: bool
    version: Optional[str] = None
    driver_version: Optional[str] = None
    runtime_version: Optional[str] = None
    devices: tuple[GPUInfo, ...] = ()

def detect_nvidia_gpus() -> tuple[bool, list[GPUInfo]]:
    """
    Detect NVIDIA GPUs using nvidia-ml-py (NVML).

    Returns:
        Tuple of (gpus_found, list_of_gpu_info).
    """
    try:
        import pynvml  # type: ignore

        try:
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            gpus = []

            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                # Get name
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")

                # Get memory info
                memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                memory_total_mb = memory_info.total // (1024 * 1024)

                # Get driver version
                driver_version = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver_version, bytes):
                    driver_version = driver_version.decode("utf-8")

                gpus.append(
                    GPUInfo(
                        index=i,
                        name=name,
                        memory_total_mb=memory_total_mb,
                        driver_version=driver_version,
                    )
                )

            pynvml.nvmlShutdown()
            return device_count > 0, gpus

        except Exception:
            return False, []

    except ImportError:
        return False, []


def detect_cuda() -> CUDAInfo:
    """
    Detect CUDA availability.

    Checks multiple sources:
    1. PyTorch CUDA availability
    2. NVML (indicates CUDA driver present)
    3. TensorFlow CUDA (if available)

    Returns:
        CUDAInfo with availability and version details.
    """
    # Try PyTorch first
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            gpus = []

            for i in range(device_count):
                props = torch.cuda.get_device_properties(i)
                gpus.append(
                    GPUInfo(
                        index=i,
                        name=props.name,
                        memory_total_mb=props.total_memory // (1024 * 1024),
                        cuda_compute_capability=f"{props.major}.{props.minor}",
                    )
                )

            return CUDAInfo(
                available=True,
                version=torch.version.cuda,
                runtime_version=torch.version.cuda,
                devices=tuple(gpus),
            )
    except ImportError:
        pass
    except Exception:
        pass

    # Try NVML as fallback (indicates CUDA driver)
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        driver_version = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver_version, bytes):
            driver_version = driver_version.decode("utf-8")

        device_count = pynvml.nvmlDeviceGetCount()
        gpus = []

        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")

            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            memory_total_mb = memory_info.total // (1024 * 1024)

            gpus.append(
                GPUInfo(
                    index=i,
                    name=name,
                    memory_total_mb=memory_total_mb,
                    driver_version=driver_version,
                )
            )

        pynvml.nvmlShutdown()

        return CUDAInfo(
            available=device_count > 0,
            version=f"driver_{driver_version}",
            driver_version=driver_version,
            devices=tuple(gpus),
        )

    except ImportError:
        pass
    except Exception:
        pass

    # No CUDA detected
    return CUDAInfo(available=False)


def is_cuda_available() -> bool:
    """Quick check if CUDA is available."""
    return detect_cuda().available


def get_cuda_version() -> Optional[str]:
    """Get CUDA version if available."""
    return detect_cuda().version


def get_gpu_count() -> int:
    """Get number of detected NVIDIA GPUs."""
    return len(detect_cuda().devices)


@dataclass(frozen=True)
class GPUMemoryInfo:
    """GPU memory information."""
    total_mb: int
    used_mb: int
    free_mb: int


def get_gpu_memory_info(device_index: int = 0) -> Optional[GPUMemoryInfo]:
    """
    Get GPU memory information for a specific device.
    
    Args:
        device_index: GPU device index (default 0)
        
    Returns:
        GPUMemoryInfo with total, used, and free memory in MB, or None if unavailable.
    """
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pynvml.nvmlShutdown()
        
        return GPUMemoryInfo(
            total_mb=mem_info.total // (1024 * 1024),
            used_mb=mem_info.used // (1024 * 1024),
            free_mb=mem_info.free // (1024 * 1024),
        )
    except Exception:
        return None
