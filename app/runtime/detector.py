"""
Runtime detection implementation.

Detects and reports structured runtime information for the Windows native
AI attendance system. This module performs detection only - it does not
modify the environment or start any processes.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RuntimeInfo:
    """Structured runtime information."""

    platform: str
    architecture: str
    python_version: str
    python_executable: str
    venv_active: bool
    venv_path: Optional[str]
    nvidia_available: bool
    cuda_available: bool
    cuda_version: Optional[str]
    ffmpeg_available: bool
    ffmpeg_path: Optional[str]
    ffmpeg_version: Optional[str]
    gpu_info: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "platform": self.platform,
            "architecture": self.architecture,
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "venv_active": self.venv_active,
            "venv_path": self.venv_path,
            "nvidia_available": self.nvidia_available,
            "cuda_available": self.cuda_available,
            "cuda_version": self.cuda_version,
            "ffmpeg_available": self.ffmpeg_available,
            "ffmpeg_path": self.ffmpeg_path,
            "ffmpeg_version": self.ffmpeg_version,
            "gpu_info": self.gpu_info,
        }


def _detect_venv() -> tuple[bool, Optional[str]]:
    """Detect if running inside a virtual environment."""
    venv_active = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    venv_path = sys.prefix if venv_active else None
    return venv_active, venv_path


def _detect_nvidia() -> tuple[bool, list]:
    """Detect NVIDIA GPU availability using nvidia-ml-py if installed."""
    try:
        import pynvml  # type: ignore

        try:
            pynvml.nvmlInit()
            device_count = pynvml.nvmlDeviceGetCount()
            gpu_info = []
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")
                gpu_info.append({"index": i, "name": name})
            pynvml.nvmlShutdown()
            return device_count > 0, gpu_info
        except Exception:
            return False, []
    except ImportError:
        return False, []


def _detect_cuda() -> tuple[bool, Optional[str]]:
    """Detect CUDA availability via PyTorch or other CUDA bindings."""
    # Try PyTorch first
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            version = torch.version.cuda or "unknown"
            return True, str(version)
    except ImportError:
        pass

    # Try nvidia-ml-py as fallback (indicates CUDA runtime)
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        driver_version = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver_version, bytes):
            driver_version = driver_version.decode("utf-8")
        pynvml.nvmlShutdown()
        # NVML available means CUDA driver is present
        return True, f"driver_{driver_version}"
    except Exception:
        pass

    return False, None


def _detect_ffmpeg() -> tuple[bool, Optional[str], Optional[str]]:
    """Detect FFmpeg availability."""
    # Check PATH lookup
    ffmpeg_executable = shutil.which("ffmpeg")

    if ffmpeg_executable is None:
        # Check common Windows locations
        common_paths = [
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "ffmpeg" / "bin" / "ffmpeg.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        ]
        for p in common_paths:
            if p.exists():
                ffmpeg_executable = str(p)
                break

    if ffmpeg_executable is None:
        return False, None, None

    # Try to get version
    version = None
    try:
        result = subprocess.run(
            [ffmpeg_executable, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if result.returncode == 0 and result.stdout:
            # Extract first line which contains version info
            first_line = result.stdout.split("\n")[0]
            version = first_line.strip()
    except Exception:
        pass

    return True, ffmpeg_executable, version


def detect_runtime() -> RuntimeInfo:
    """
    Detect and return structured runtime information.

    This function performs detection only and does not modify the environment.
    """
    venv_active, venv_path = _detect_venv()
    nvidia_available, gpu_info = _detect_nvidia()
    cuda_available, cuda_version = _detect_cuda()
    ffmpeg_available, ffmpeg_path, ffmpeg_version = _detect_ffmpeg()

    return RuntimeInfo(
        platform=platform.system(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        python_executable=sys.executable,
        venv_active=venv_active,
        venv_path=venv_path,
        nvidia_available=nvidia_available,
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        ffmpeg_available=ffmpeg_available,
        ffmpeg_path=ffmpeg_path,
        ffmpeg_version=ffmpeg_version,
        gpu_info=gpu_info,
    )