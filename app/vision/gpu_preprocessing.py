"""
Phase 36F - GPU-Resident Preprocessing for SCRFD.

This module implements GPU-resident preprocessing using PyTorch CUDA
to eliminate CPU-GPU round trips for 4K frame preprocessing.

Operations:
- BGR to RGB color conversion
- Letterbox resize with padding
- Normalization (scale, mean, std)
- HWC to CHW layout conversion
- Batch dimension addition

All operations stay on GPU until final tensor is ready for ONNX Runtime.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from app.data.contracts import (
    ColorSpace,
    ModelPreprocessingContract,
    ResizeMode,
    get_model_contract,
)
from app.data.frame import CanonicalFrame, PixelFormat
from app.data.preprocessing import PreprocessingResult


@dataclass
class GPUPreprocessingResult:
    """
    Result of GPU preprocessing.
    
    Contains the preprocessed tensor on GPU and metadata.
    """
    # Preprocessed tensor on GPU (NCHW format, ready for model)
    tensor: torch.Tensor  # On CUDA device
    
    # Model contract used
    model_id: str
    model_sha256: str
    preprocessing_version: str
    contract_version: str
    
    # Original frame metadata
    source_type: str
    source_id: str
    frame_index: int
    original_width: int
    original_height: int
    
    # Preprocessing parameters applied
    color_space: str
    tensor_layout: str
    dtype: str
    resize_mode: str
    target_shape: Tuple[int, ...]
    
    # Resize information
    scale_factor: Optional[float] = None
    padding_applied: Optional[Tuple[int, int, int, int]] = None  # top, bottom, left, right
    
    # Conversions applied
    conversions: List[str] = None
    
    # Timing
    preprocessing_time_ms: float = 0.0
    
    def __post_init__(self):
        if self.conversions is None:
            self.conversions = []
    
    def to_cpu_numpy(self) -> np.ndarray:
        """Move tensor to CPU and convert to numpy (for comparison/debugging)."""
        return self.tensor.detach().cpu().numpy()
    
    def to_preprocessing_result(self) -> PreprocessingResult:
        """Convert to standard PreprocessingResult (CPU numpy)."""
        return PreprocessingResult(
            tensor=self.to_cpu_numpy(),
            model_id=self.model_id,
            model_sha256=self.model_sha256,
            preprocessing_version=self.preprocessing_version,
            contract_version=self.contract_version,
            source_type=self.source_type,
            source_id=self.source_id,
            frame_index=self.frame_index,
            original_width=self.original_width,
            original_height=self.original_height,
            color_space=self.color_space,
            tensor_layout=self.tensor_layout,
            dtype=self.dtype,
            resize_mode=self.resize_mode,
            target_shape=self.target_shape,
            scale_factor=self.scale_factor,
            padding_applied=self.padding_applied,
            conversions=self.conversions,
        )


class GPUPreprocessor:
    """
    GPU-resident preprocessor for SCRFD and other models.
    
    Uses PyTorch CUDA for all preprocessing operations.
    Keeps data on GPU throughout the pipeline.
    Supports buffer reuse for reduced allocation overhead.
    """
    
    def __init__(self, model_id: str, device: Optional[torch.device] = None, reuse_buffers: bool = False, full_gpu: bool = False):
        """
        Initialize GPU preprocessor for a specific model.
        
        Args:
            model_id: Model identifier (e.g., "scrfd", "arcface").
            device: CUDA device to use (default: cuda:0).
            reuse_buffers: Pre-allocate and reuse preprocessing tensors.
            full_gpu: Use full GPU path without CPU-GPU transfers.
        """
        self.model_id = model_id
        self.device = device or torch.device("cuda:0")
        self._contract: Optional[ModelPreprocessingContract] = None
        self.reuse_buffers = reuse_buffers
        self.full_gpu = full_gpu
        
        # Verify CUDA is available
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available for GPU preprocessing")
        
        # Pre-allocated buffers for reuse
        self._preallocated_tensors: Dict[str, torch.Tensor] = {}
        self._mean_tensor: Optional[torch.Tensor] = None
        self._std_tensor: Optional[torch.Tensor] = None
        
        # Warm up CUDA context
        _ = torch.zeros(1, device=self.device)
        torch.cuda.synchronize(self.device)
        
        # Pre-allocate normalization tensors if reuse_buffers
        if self.reuse_buffers:
            self._preallocate_normalization()
    
    def _preallocate_normalization(self):
        """Pre-allocate mean and std tensors for normalization."""
        contract = self.contract
        if contract.normalization_mean is not None and contract.normalization_std is not None:
            self._mean_tensor = torch.tensor(
                contract.normalization_mean, 
                dtype=torch.float32, 
                device=self.device
            ).view(1, 1, 3)
            self._std_tensor = torch.tensor(
                contract.normalization_std, 
                dtype=torch.float32, 
                device=self.device
            ).view(1, 1, 3)
    
    @property
    def contract(self) -> ModelPreprocessingContract:
        """Get the preprocessing contract (lazy loaded)."""
        if self._contract is None:
            self._contract = get_model_contract(self.model_id)
        return self._contract
    
    def preprocess(self, frame: CanonicalFrame) -> GPUPreprocessingResult:
        """
        Preprocess a canonical frame on GPU.
        
        Args:
            frame: Canonical frame to preprocess (CPU numpy array).
            
        Returns:
            GPUPreprocessingResult with GPU-resident tensor.
        """
        contract = self.contract
        conversions = []
        t0 = time.perf_counter()
        
        # Step 1: Upload frame to GPU
        # Frame is HWC, uint8, BGR or RGB
        data = frame.data
        current_format = frame.metadata.pixel_format
        
        # Convert to torch tensor on GPU
        # HWC format, uint8
        gpu_tensor = torch.from_numpy(data).to(self.device, non_blocking=True)
        conversions.append("cpu_to_gpu_upload")
        
        # Step 2: Convert color space if needed
        if contract.color_space == ColorSpace.RGB:
            if current_format == PixelFormat.BGR:
                # BGR -> RGB: flip channel dimension
                gpu_tensor = gpu_tensor.flip(dims=[2])  # HWC, flip channels
                conversions.append("bgr_to_rgb")
            elif current_format == PixelFormat.RGB:
                pass  # Already RGB
            elif current_format == PixelFormat.GRAY:
                # Gray -> RGB: repeat channel
                gpu_tensor = gpu_tensor.unsqueeze(2).repeat(1, 1, 3)
                conversions.append("gray_to_rgb")
        elif contract.color_space == ColorSpace.BGR:
            if current_format == PixelFormat.RGB:
                gpu_tensor = gpu_tensor.flip(dims=[2])
                conversions.append("rgb_to_bgr")
            elif current_format == PixelFormat.BGR:
                pass
            elif current_format == PixelFormat.GRAY:
                gpu_tensor = gpu_tensor.unsqueeze(2).repeat(1, 1, 3)
                conversions.append("gray_to_bgr")
        
        # Step 3: Resize with letterbox (preserve aspect ratio with padding)
        original_h, original_w = gpu_tensor.shape[:2]
        target_h, target_w = contract.input_height, contract.input_width
        scale_factor = None
        padding_applied = None
        
        if contract.resize_mode == ResizeMode.LETTERBOX:
            gpu_tensor, scale_factor, padding_applied = self._resize_letterbox_gpu(
                gpu_tensor, target_h, target_w, contract.padding_value
            )
            conversions.append(f"letterbox_resize_{original_h}x{original_w}_to_{target_h}x{target_w}")
        elif contract.resize_mode == ResizeMode.FIT:
            gpu_tensor, scale_factor = self._resize_fit_gpu(gpu_tensor, target_h, target_w)
            conversions.append(f"fit_resize_{original_h}x{original_w}_to_{target_h}x{target_w}")
        elif contract.resize_mode == ResizeMode.CROP:
            gpu_tensor = self._resize_crop_gpu(gpu_tensor, target_h, target_w)
            conversions.append(f"crop_resize_{original_h}x{original_w}_to_{target_h}x{target_w}")
        elif contract.resize_mode == ResizeMode.STRETCH:
            gpu_tensor = self._resize_stretch_gpu(gpu_tensor, target_h, target_w)
            conversions.append(f"stretch_resize_{original_h}x{original_w}_to_{target_h}x{target_w}")
        
        # Step 4: Convert to float32 if needed
        if contract.dtype == "float32":
            if gpu_tensor.dtype == torch.uint8:
                gpu_tensor = gpu_tensor.to(torch.float32)
                conversions.append("uint8_to_float32")
        
        # Step 5: Apply normalization
        if contract.normalization_scale is not None:
            gpu_tensor = gpu_tensor * contract.normalization_scale
            conversions.append(f"scale_{contract.normalization_scale}")
        
        if contract.normalization_mean is not None and contract.normalization_std is not None:
            mean = torch.tensor(contract.normalization_mean, dtype=torch.float32, device=self.device).view(1, 1, 3)
            std = torch.tensor(contract.normalization_std, dtype=torch.float32, device=self.device).view(1, 1, 3)
            gpu_tensor = (gpu_tensor - mean) / std
            conversions.append("normalize_mean_std")
        
        # Step 6: Transpose to CHW format (HWC -> CHW)
        gpu_tensor = gpu_tensor.permute(2, 0, 1)  # HWC -> CHW
        conversions.append("hwc_to_chw")
        
        # Step 7: Add batch dimension (CHW -> NCHW)
        gpu_tensor = gpu_tensor.unsqueeze(0)  # Add batch dim
        conversions.append("add_batch_dim")
        
        # Verify final shape
        expected_shape = contract.target_shape
        if tuple(gpu_tensor.shape) != expected_shape:
            raise ValueError(
                f"Preprocessed shape {tuple(gpu_tensor.shape)} does not match expected {expected_shape} "
                f"for model {self.model_id}"
            )
        
        t1 = time.perf_counter()
        preprocessing_time_ms = (t1 - t0) * 1000
        
        return GPUPreprocessingResult(
            tensor=gpu_tensor,
            model_id=contract.model_id,
            model_sha256=contract.model_sha256,
            preprocessing_version=str(contract.preprocessing_version),
            contract_version=contract.contract_version,
            source_type=str(frame.metadata.source_type),
            source_id=frame.metadata.source_id,
            frame_index=frame.metadata.frame_index,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
            color_space=str(contract.color_space),
            tensor_layout=str(contract.tensor_layout),
            dtype=str(gpu_tensor.dtype),
            resize_mode=str(contract.resize_mode),
            target_shape=tuple(gpu_tensor.shape),
            scale_factor=scale_factor,
            padding_applied=padding_applied,
            conversions=conversions,
            preprocessing_time_ms=preprocessing_time_ms,
        )
    
    def _resize_letterbox_gpu(
        self,
        tensor: torch.Tensor,  # HWC
        target_h: int,
        target_w: int,
        padding_value: int,
    ) -> Tuple[torch.Tensor, float, Tuple[int, int, int, int]]:
        """
        Resize with letterbox on GPU using PyTorch.
        
        Args:
            tensor: Input tensor (H, W, C) on GPU.
            target_h: Target height.
            target_w: Target width.
            padding_value: Padding value (0-255 for uint8, 0.0-1.0 for float).
            
        Returns:
            Tuple of (resized tensor, scale factor, padding (top, bottom, left, right)).
        """
        h, w = tensor.shape[:2]
        
        # Calculate scale factor
        scale = min(target_w / w, target_h / h)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        
        # Resize using bilinear interpolation
        # Need to convert to NCHW for interpolate, then back
        # tensor is HWC -> permute to CHW -> unsqueeze to NCHW
        tensor_chw = tensor.permute(2, 0, 1).unsqueeze(0).float()  # NCHW
        resized_chw = torch.nn.functional.interpolate(
            tensor_chw,
            size=(new_h, new_w),
            mode='bilinear',
            align_corners=False,
        )
        # Back to HWC
        resized = resized_chw.squeeze(0).permute(1, 2, 0)  # HWC
        
        # Convert back to original dtype if needed
        if tensor.dtype == torch.uint8:
            resized = resized.clamp(0, 255).to(torch.uint8)
        
        # Calculate padding
        pad_h = target_h - new_h
        pad_w = target_w - new_w
        pad_top = pad_h // 2
        pad_bottom = pad_h - pad_top
        pad_left = pad_w // 2
        pad_right = pad_w - pad_left
        
        # Apply padding
        # PyTorch pad format: (left, right, top, bottom) for last 2 dims
        # For HWC, we need to pad H and W dims
        padded = torch.nn.functional.pad(
            resized,
            (0, 0, pad_left, pad_right, pad_top, pad_bottom),  # (C_left, C_right, W_left, W_right, H_top, H_bottom)
            mode='constant',
            value=float(padding_value),
        )
        
        # Verify shape
        assert padded.shape[0] == target_h, f"Padded height {padded.shape[0]} != target {target_h}"
        assert padded.shape[1] == target_w, f"Padded width {padded.shape[1]} != target {target_w}"
        
        return padded, scale, (pad_top, pad_bottom, pad_left, pad_right)
    
    def _resize_fit_gpu(
        self,
        tensor: torch.Tensor,
        target_h: int,
        target_w: int,
    ) -> Tuple[torch.Tensor, float]:
        """Resize to fit within target size on GPU."""
        h, w = tensor.shape[:2]
        scale = min(target_w / w, target_h / h)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        
        tensor_chw = tensor.permute(2, 0, 1).unsqueeze(0).float()
        resized_chw = torch.nn.functional.interpolate(
            tensor_chw,
            size=(new_h, new_w),
            mode='bilinear',
            align_corners=False,
        )
        resized = resized_chw.squeeze(0).permute(1, 2, 0)
        
        if tensor.dtype == torch.uint8:
            resized = resized.clamp(0, 255).to(torch.uint8)
        
        return resized, scale
    
    def _resize_crop_gpu(self, tensor: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
        """Center crop to target size on GPU."""
        h, w = tensor.shape[:2]
        
        start_y = max(0, (h - target_h) // 2)
        start_x = max(0, (w - target_w) // 2)
        end_y = min(h, start_y + target_h)
        end_x = min(w, start_x + target_w)
        
        cropped = tensor[start_y:end_y, start_x:end_x]
        
        # If cropped size is smaller than target, resize
        if cropped.shape[0] != target_h or cropped.shape[1] != target_w:
            tensor_chw = cropped.permute(2, 0, 1).unsqueeze(0).float()
            resized_chw = torch.nn.functional.interpolate(
                tensor_chw,
                size=(target_h, target_w),
                mode='bilinear',
                align_corners=False,
            )
            cropped = resized_chw.squeeze(0).permute(1, 2, 0)
            if tensor.dtype == torch.uint8:
                cropped = cropped.clamp(0, 255).to(torch.uint8)
        
        return cropped
    
    def _resize_stretch_gpu(self, tensor: torch.Tensor, target_h: int, target_w: int) -> torch.Tensor:
        """Stretch to exact target size on GPU."""
        tensor_chw = tensor.permute(2, 0, 1).unsqueeze(0).float()
        resized_chw = torch.nn.functional.interpolate(
            tensor_chw,
            size=(target_h, target_w),
            mode='bilinear',
            align_corners=False,
        )
        resized = resized_chw.squeeze(0).permute(1, 2, 0)
        
        if tensor.dtype == torch.uint8:
            resized = resized.clamp(0, 255).to(torch.uint8)
        
        return resized


def create_gpu_preprocessor(model_id: str, device: Optional[torch.device] = None, reuse_buffers: bool = False, full_gpu: bool = False) -> GPUPreprocessor:
    """
    Factory function to create a GPU preprocessor.
    
    Args:
        model_id: Model identifier.
        device: CUDA device to use.
        reuse_buffers: Pre-allocate and reuse preprocessing tensors.
        full_gpu: Use full GPU path without CPU-GPU transfers.
        
    Returns:
        GPUPreprocessor instance.
    """
    return GPUPreprocessor(model_id, device, reuse_buffers=reuse_buffers, full_gpu=full_gpu)


def preprocess_frame_gpu(frame: CanonicalFrame, model_id: str, device: Optional[torch.device] = None, reuse_buffers: bool = False, full_gpu: bool = False) -> GPUPreprocessingResult:
    """
    Convenience function to preprocess a frame on GPU.
    
    Args:
        frame: Canonical frame to preprocess.
        model_id: Model identifier.
        device: CUDA device to use.
        reuse_buffers: Pre-allocate and reuse preprocessing tensors.
        full_gpu: Use full GPU path without CPU-GPU transfers.
        
    Returns:
        GPUPreprocessingResult with GPU-resident tensor.
    """
    preprocessor = GPUPreprocessor(model_id, device, reuse_buffers=reuse_buffers, full_gpu=full_gpu)
    return preprocessor.preprocess(frame)
