"""
Phase 3.1 - GPU Device Abstraction

Explicit GPU runtime/device abstraction for AI attendance pipeline.
Exposes CUDA availability, selected device, memory info, without
initializing unnecessary model instances.
Works when CUDA is unavailable (preserves CPU fallback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class GPUDeviceInfo:
    """Explicit GPU device metadata."""
    cuda_available: bool = False
    device_index: int = -1
    device_name: str = "unknown"
    compute_capability_major: int = 0
    compute_capability_minor: int = 0
    total_vram_mb: int = 0
    pytorch_cuda_available: bool = False
    ort_cuda_ep_available: bool = False


class GPUDeviceAbstraction:
    """
    Small, explicit GPU runtime abstraction.

    Must NOT initialize unnecessary model instances.
    Must work when CUDA unavailable.
    """

    def __init__(self, preferred_device_index: int = 0):
        self.preferred_device_index = preferred_device_index
        self.info: GPUDeviceInfo = self._discover()

    def _discover(self) -> GPUDeviceInfo:
        info = GPUDeviceInfo()
        info.device_index = self.preferred_device_index

        # PyTorch CUDA
        try:
            import torch
            info.pytorch_cuda_available = torch.cuda.is_available()
            if info.pytorch_cuda_available:
                info.cuda_available = True
                count = torch.cuda.device_count()
                if count > 0:
                    idx = min(self.preferred_device_index, count - 1)
                    info.device_index = idx
                    info.device_name = torch.cuda.get_device_name(idx)
                    props = torch.cuda.get_device_properties(idx)
                    info.compute_capability_major = props.major
                    info.compute_capability_minor = props.minor
                    info.total_vram_mb = props.total_memory // (1024 * 1024)
        except Exception as exc:
            logger.debug("PyTorch CUDA discovery failed: %s", exc)
            info.pytorch_cuda_available = False

        # ONNX Runtime CUDA EP
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            info.ort_cuda_ep_available = "CUDAExecutionProvider" in providers
            # Do NOT claim CUDA available solely from EP registration
            # Only set cuda_available if PyTorch also confirms
        except Exception as exc:
            logger.debug("ORT CUDA EP discovery failed: %s", exc)
            info.ort_cuda_ep_available = False

        return info

    def is_cuda_available(self) -> bool:
        return self.info.cuda_available

    def get_info(self) -> GPUDeviceInfo:
        return self.info

    def get_device_index(self) -> int:
        return self.info.device_index

    def get_device_name(self) -> str:
        return self.info.device_name

    def get_compute_capability(self) -> tuple:
        return (self.info.compute_capability_major, self.info.compute_capability_minor)

    def get_total_vram_mb(self) -> int:
        return self.info.total_vram_mb

    def get_vram_report(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "device_index": self.info.device_index,
            "device_name": self.info.device_name,
            "cuda_available": self.info.cuda_available,
            "total_vram_mb": self.info.total_vram_mb,
        }
        if self.info.pytorch_cuda_available:
            try:
                import torch
                idx = self.info.device_index
                if torch.cuda.device_count() > 0:
                    allocated = torch.cuda.memory_allocated(idx) // (1024 * 1024)
                    reserved = torch.cuda.memory_reserved(idx) // (1024 * 1024)
                    report["allocated_vram_mb"] = allocated
                    report["reserved_vram_mb"] = reserved
                    report["free_approx_mb"] = max(0, self.info.total_vram_mb - reserved)
            except Exception:
                pass
        return report
