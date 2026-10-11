"""
Phase R3.14-H.9 — GPU ROI Crop Operations.

Provides GPU-resident ROI crop and resize operations for ArcFace (112x112)
and ReID (256x128) model inputs. All operations stay on CUDA.

Pipeline:
    4K GPU Surface (CUDA)
         │
         ├──> Crop ROI (H,W coords from 4K master)
         │         │
         │         ├──> Resize to 112x112 (ArcFace)
         │         └──> Resize to 256x128 (ReID)
         │                │
         │                └──> GPU tensor ready for model input

The crop coordinates are in ORIGINAL_FRAME space (the same space as
the 4K master). The GPU crop uses PyTorch tensor indexing (no copy to CPU).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GPUROIResult:
    """Result of GPU ROI crop + resize operation."""
    tensor: "torch.Tensor"  # GPU tensor, shape depends on target_size
    original_bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2) in 4K coords
    crop_size: Tuple[int, int]  # (H, W) after crop
    target_size: Tuple[int, int]  # (H, W) after resize
    scale_factor: float
    pad_applied: Tuple[int, int, int, int]  # (top, bottom, left, right)
    crop_time_ms: float = 0.0
    resize_time_ms: float = 0.0


def crop_and_resize_gpu(
    gpu_surface: "torch.Tensor",  # (H, W, C) uint8 on CUDA
    bbox: Tuple[float, float, float, float],  # (x1, y1, x2, y2) in 4K coords
    target_h: int,
    target_w: int,
    padding_value: int = 0,
    clamp: bool = True,
) -> GPUROIResult:
    """
    Crop a region from GPU surface and resize to target dimensions.
    
    All operations stay on CUDA. The crop uses tensor indexing (no copy).
    The resize uses bilinear interpolation on GPU.
    
    Args:
        gpu_surface: 4K GPU surface, shape (H, W, C), uint8, on CUDA
        bbox: (x1, y1, x2, y2) in original frame coordinates
        target_h: Target height after resize
        target_w: Target width after resize
        padding_value: Value for padding if bbox extends beyond frame
        clamp: If True, clamp bbox to frame boundaries
    
    Returns:
        GPUROIResult with GPU tensor and metadata
    """
    import torch
    import torch.nn.functional as F
    
    t0 = time.perf_counter()
    
    H, W = gpu_surface.shape[:2]
    x1, y1, x2, y2 = bbox
    
    if clamp:
        x1 = max(0, min(int(round(x1)), W - 1))
        y1 = max(0, min(int(round(y1)), H - 1))
        x2 = max(0, min(int(round(x2)), W))
        y2 = max(0, min(int(round(y2)), H))
    
    if x2 <= x1 or y2 <= y1:
        # Empty bbox: return zero tensor
        result = torch.zeros(
            (target_h, target_w, gpu_surface.shape[2] if gpu_surface.ndim == 3 else 3),
            dtype=torch.uint8, device=gpu_surface.device,
        )
        return GPUROIResult(
            tensor=result,
            original_bbox=(x1, y1, x2, y2),
            crop_size=(0, 0),
            target_size=(target_h, target_w),
            scale_factor=0.0,
            pad_applied=(0, 0, 0, 0),
            crop_time_ms=0.0,
            resize_time_ms=0.0,
        )
    
    # GPU crop (no copy, just a view)
    crop = gpu_surface[y1:y2, x1:x2, :]
    crop_h, crop_w = crop.shape[0], crop.shape[1]
    
    t1 = time.perf_counter()
    
    # Convert to CHW for interpolate, add batch dim
    crop_chw = crop.permute(2, 0, 1).unsqueeze(0).float()  # (1, C, H, W)
    
    # GPU resize with bilinear interpolation
    resized_chw = F.interpolate(
        crop_chw,
        size=(target_h, target_w),
        mode='bilinear',
        align_corners=False,
    )
    
    # Convert back to HWC
    resized = resized_chw.squeeze(0).permute(1, 2, 0)
    
    # Clamp and convert to uint8
    resized = resized.clamp(0, 255).to(torch.uint8)
    
    t2 = time.perf_counter()
    
    crop_time_ms = (t1 - t0) * 1000
    resize_time_ms = (t2 - t1) * 1000
    
    scale_factor = min(target_w / crop_w, target_h / crop_h)
    
    return GPUROIResult(
        tensor=resized,
        original_bbox=(float(x1), float(y1), float(x2), float(y2)),
        crop_size=(crop_h, crop_w),
        target_size=(target_h, target_w),
        scale_factor=scale_factor,
        pad_applied=(0, 0, 0, 0),
        crop_time_ms=crop_time_ms,
        resize_time_ms=resize_time_ms,
    )


def gpu_resize_letterbox(
    gpu_surface: "torch.Tensor",  # (H, W, C) uint8 on CUDA
    target_h: int,
    target_w: int,
    padding_value: int = 114,
) -> Tuple["torch.Tensor", float, Tuple[int, int, int, int]]:
    """
    Resize GPU surface to target dimensions with letterbox (aspect-preserving).
    
    Args:
        gpu_surface: GPU tensor, shape (H, W, C), uint8
        target_h: Target height
        target_w: Target width
        padding_value: Padding value (0-255 for uint8)
    
    Returns:
        Tuple of (resized tensor, scale factor, padding (top, bottom, left, right))
    """
    import torch
    import torch.nn.functional as F
    
    H, W = gpu_surface.shape[:2]
    
    # Calculate scale factor
    scale = min(target_w / W, target_h / H)
    new_w = int(round(W * scale))
    new_h = int(round(H * scale))
    
    # Resize using bilinear interpolation
    tensor_chw = gpu_surface.permute(2, 0, 1).unsqueeze(0).float()
    resized_chw = F.interpolate(
        tensor_chw,
        size=(new_h, new_w),
        mode='bilinear',
        align_corners=False,
    )
    resized = resized_chw.squeeze(0).permute(1, 2, 0)
    
    if gpu_surface.dtype == torch.uint8:
        resized = resized.clamp(0, 255).to(torch.uint8)
    
    # Calculate padding
    pad_h = target_h - new_h
    pad_w = target_w - new_w
    pad_top = pad_h // 2
    pad_bottom = pad_h - pad_top
    pad_left = pad_w // 2
    pad_right = pad_w - pad_left
    
    # Apply padding
    padded = F.pad(
        resized,
        (0, 0, pad_left, pad_right, pad_top, pad_bottom),
        mode='constant',
        value=float(padding_value),
    )
    
    return padded, scale, (pad_top, pad_bottom, pad_left, pad_right)
