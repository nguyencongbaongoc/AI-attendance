"""
Phase 3.1 - GPU Residency Contract

Explicit internal contract describing where data is expected to live.
States: CPU, CUDA, CPU_PINNED, UNKNOWN.
Does NOT create fake GPU pointers.
Does NOT claim GPU residency unless backing storage is actually CUDA.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any


class ResidencyState(str, Enum):
    CPU = "CPU"
    CUDA = "CUDA"
    CPU_PINNED = "CPU_PINNED"
    UNKNOWN = "UNKNOWN"


class ResidencyContract:
    """
    Contract describing expected data residency for the AI pipeline.
    Later phases will determine:
        - frame location
        - tensor location
        - model input location
        - model output location
    without guessing.
    """

    def __init__(self):
        # Frame metadata (not data itself)
        self.frame_location = ResidencyState.CPU  # Current: CPU BGR frame
        self.frame_device_index: Optional[int] = None
        self.frame_shape: Optional[tuple] = None
        self.frame_dtype_str: Optional[str] = None

        # Tensor wrapper metadata (Phase 3.1 introduces wrapper)
        self.tensor_location = ResidencyState.CPU
        self.tensor_device_index: Optional[int] = None

        # Model input/output contracts
        self.model_input_location = ResidencyState.CPU
        self.model_output_location = ResidencyState.CPU
        self.model_input_shape: Optional[tuple] = None
        self.model_output_shape: Optional[tuple] = None

    def set_frame_residency(self, state, device_index=None, shape=None, dtype_str=None):
        if isinstance(state, str):
            state = ResidencyState(state) if state in [s.value for s in ResidencyState] else ResidencyState.CPU
        self.frame_location = state
        self.frame_device_index = device_index
        self.frame_shape = shape
        self.frame_dtype_str = dtype_str

    def set_tensor_residency(self, state: ResidencyState, device_index: Optional[int] = None):
        self.tensor_location = state
        self.tensor_device_index = device_index

    def set_model_input_contract(self, state: ResidencyState, shape: Optional[tuple] = None):
        self.model_input_location = state
        self.model_input_shape = shape

    def set_model_output_contract(self, state: ResidencyState, shape: Optional[tuple] = None):
        self.model_output_location = state
        self.model_output_shape = shape

    def report(self) -> dict:
        def val(s):
            return s.value if hasattr(s, "value") else s
        return {
            "frame_location": val(self.frame_location),
            "frame_device_index": self.frame_device_index,
            "frame_shape": self.frame_shape,
            "frame_dtype_str": self.frame_dtype_str,
            "tensor_location": val(self.tensor_location),
            "tensor_device_index": self.tensor_device_index,
            "model_input_location": val(self.model_input_location),
            "model_input_shape": self.model_input_shape,
            "model_output_location": val(self.model_output_location),
            "model_output_shape": self.model_output_shape,
        }
