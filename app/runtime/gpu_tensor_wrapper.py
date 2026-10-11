"""
Phase 3.1 - AI Tensor / Frame Wrapper

Lightweight wrapper or metadata mechanism for AI tensors/frames.
Makes shape, dtype, device, ownership/lifetime explicit without
copying data merely to inspect metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class TensorMeta:
    """Lightweight metadata wrapper for AI tensors."""
    shape: tuple
    dtype_str: str  # e.g. float32, uint8
    device_str: str  # e.g. CPU, CUDA:0
    batch_dim: Optional[int] = None
    ownership_note: str = "cpu_numpy"  # Conceptual: actual backing storage


class AITensorWrapper:
    """
    Minimal wrapper making tensor properties explicit.
    Does NOT copy data merely to inspect metadata.
    Keeps hot path lightweight.
    """

    def __init__(self, array, device_str: Optional[str] = None, batch_dim: Optional[int] = None):
        # array is expected to be numpy array or similar
        self._array = array
        self.meta = TensorMeta(
            shape=tuple(getattr(array, 'shape', ()) or ()),
            dtype_str=str(getattr(array, 'dtype', 'unknown')),
            device_str=device_str or self._infer_device_str(),
            batch_dim=batch_dim,
        )

    def _infer_device_str(self) -> str:
        # Actual backing storage inspection
        # If this were PyTorch CUDA tensor: array.device.type == 'cuda'
        # If numpy array: CPU
        # For Phase 3.1 we report based on actual backing storage only.
        if hasattr(self._array, 'device'):
            # PyTorch tensor
            import torch
            if isinstance(self._array.device, torch.device):
                return f"CUDA:{self._array.device.index}" if self._array.device.type == 'cuda' else f"CPU"
        # Default: CPU backing for numpy arrays
        return "CPU"

    def get_shape(self) -> tuple:
        return self.meta.shape

    def get_dtype(self) -> str:
        return self.meta.dtype_str

    def get_device_str(self) -> str:
        return self.meta.device_str

    def get_batch_dim(self) -> Optional[int]:
        return self.meta.batch_dim

    def get_ownership_note(self) -> str:
        return self.meta.ownership_note

    def is_cpu_resident(self) -> bool:
        return self.meta.device_str.startswith("CPU")

    def is_cuda_resident(self) -> bool:
        return self.meta.device_str.startswith("CUDA")

    def get_array(self):
        # Returns the actual backing array without copy
        return self._array
