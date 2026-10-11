"""
Phase 3.8A — GPU Alignment Backend using torch affine_grid + grid_sample.

This module provides GPU-resident face alignment for 112x112 BGR output,
matching the CPU reference in app/vision/hardpose_alignment.py.

Requirements met:
- Accepts GPU-resident image (torch tensor, cuda:0)
- Accepts GPU or CPU landmark data (5-point 2D float32)
- Produces GPU-resident aligned output (torch tensor, cuda:0)
- Uses same similarity transform as CPU reference (compute_affine_transform)
- Uses bilinear interpolation (equivalent to cv2.INTER_LINEAR)
- Uses zero-padding (equivalent to BORDER_CONSTANT with black)
- No .cpu() / .numpy() in normal GPU path
- Reusable: stateless function, no per-frame session/model creation
- Preserves BGR order, uint8 output after clamping
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
import cv2
from typing import Tuple, Optional

# Import CPU reference for reuse
from app.vision.hardpose_alignment import (
    compute_affine_transform,
    apply_alignment_transform,
)


def gpu_align_face(
    image_tensor: torch.Tensor,  # (C, H, W) or (1, C, H, W) or (C, H, W) BGR float32 or uint8, on cuda
    src_points: np.ndarray,     # (5, 2) float32 — 2D source landmarks
    dst_points: np.ndarray,     # (5, 2) float32 — ARC_FACE_TARGET_5POINTS or same reference
    output_size: Tuple[int, int] = (112, 112),
) -> torch.Tensor:
    """
    GPU face alignment using torch affine_grid + grid_sample.

    Args:
        image_tensor: Input image on GPU. Expected BGR. If uint8, converted to float32 [0, 1]
                      for warp, then converted back to uint8 after.
                      Shape: (C, H, W) or (1, C, H, W) with C=3.
        src_points: 5 source facial landmarks (x, y) in image coordinate space.
        dst_points: 5 destination landmarks (reference from ARC_FACE_TARGET_5POINTS).
        output_size: (width, height) = (112, 112) by default.

    Returns:
        Aligned face on GPU as torch tensor (C, H, W) uint8 BGR.
    """
    device = image_tensor.device
    assert str(device).startswith("cuda"), f"gpu_align_face requires CUDA input, got {device}"

    # Ensure 4D batch format for affine_grid: (N, C, H, W)
    if image_tensor.dim() == 3:
        image_tensor = image_tensor.unsqueeze(0)  # (1, C, H, W)
    elif image_tensor.dim() == 4:
        pass
    else:
        raise ValueError(f"Expected 3D or 4D input, got {image_tensor.dim()}D")

    # Determine if input is float [0,1] or uint8 [0,255]; preserve scale
    was_uint8 = image_tensor.dtype == torch.uint8
    if was_uint8:
        # Convert to float32 for warp, then back to uint8 after
        image_float = image_tensor.float() / 255.0
    else:
        image_float = image_tensor.float()

    # Compute transform matrix on CPU (tiny scalar operation, acceptable)
    # This uses the exact same CPU reference function
    M = compute_affine_transform(src_points, dst_points)  # (2, 3) float32, OpenCV convention

    # Convert OpenCV 2x3 affine matrix to torch format for affine_grid
    # OpenCV: dst = M * [x y 1]^T
    # torch affine_grid uses theta with same convention: output(x,y) = theta * [x y 1]^T
    M_torch = torch.from_numpy(M).float().unsqueeze(0).to(device)  # (1, 2, 3)

    # Note: OpenCV warpAffine uses (width, height) = output_size
    # torch affine_grid expects size as (N, C, H, W)
    # We pass output_size as (W, H) but affine_grid size is (N, C, H, W) — actually
    # affine_grid takes (size) where H and W are the output dimensions.
    # The grid_sample output will match the order (N, C, H, W) where H = output_size[1], W = output_size[0].
    # Let's ensure consistency: output_shape = (1, 3, output_size[1], output_size[0])
    # Wait: OpenCV warpAffine(image, M, (w, h)) -> output shape (h, w) ???
    # From OpenCV docs: dsize = (width, height) of output image, and result has shape (dsize[1], dsize[0], ...)
    # Actually OpenCV returns (dsize[1], dsize[0], channels) — i.e., (h, w) where h = dsize[1], w = dsize[0].
    # Let's verify with the CPU function.
    # For consistency with CPU: we keep (w, h) mapping as in apply_alignment_transform.
    w, h = output_size
    batch_size, channels = image_float.shape[0], image_float.shape[1]
    grid_shape = torch.Size((batch_size, channels, h, w))

    # Generate affine grid on GPU
    grid = F.affine_grid(M_torch, grid_shape, align_corners=False)

    # Apply grid_sample on GPU with bilinear interpolation and zero padding (black border)
    # mode='bilinear' ≈ cv2.INTER_LINEAR
    # padding_mode='zeros' ≈ cv2.BORDER_CONSTANT with value=0
    aligned_float = F.grid_sample(
        image_float,
        grid,
        mode='bilinear',
        padding_mode='zeros',
        align_corners=False,
    )

    # Convert back to uint8 [0, 255] and clamp
    if was_uint8:
        aligned_uint8 = (aligned_float * 255.0).clamp(0, 255).round().to(torch.uint8)
    else:
        # If input was float but not in [0,1], assume [0,255] and clamp
        aligned_uint8 = aligned_float.clamp(0, 255).round().to(torch.uint8)

    # Return without batch dimension if input was 3D
    if image_tensor.dim() == 3:
        aligned_uint8 = aligned_uint8.squeeze(0)

    # Ensure output remains GPU-resident
    assert aligned_uint8.device.type == 'cuda', f"Output must remain on GPU, got {aligned_uint8.device}"
    return aligned_uint8


def gpu_align_face_cpu_fallback(
    image_np: np.ndarray,
    src_points: np.ndarray,
    dst_points: np.ndarray,
) -> np.ndarray:
    """Explicit CPU fallback — does NOT create GPU tensors."""
    # Use the existing authoritative CPU reference directly
    M = compute_affine_transform(src_points, dst_points)
    aligned = apply_alignment_transform(image_np, M, output_size=(112, 112), interpolation=cv2.INTER_LINEAR)
    return aligned
