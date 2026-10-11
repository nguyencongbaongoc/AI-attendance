"""
Phase H.10-C.2 — GPU NV12 to BGR Conversion.

CUDA kernel for converting NV12 2-plane format to BGR 3-channel format.
Used for backward compatibility when BGR is needed (e.g., some model preprocessing).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def nv12_to_bgr_gpu(y_plane, uv_plane):
    """
    Convert NV12 (Y + interleaved UV) to BGR on GPU using PyTorch operations.
    
    Args:
        y_plane: PyTorch CUDA tensor (H, W) uint8
        uv_plane: PyTorch CUDA tensor (H/2, W/2, 2) uint8 (interleaved U,V)
    
    Returns:
        PyTorch CUDA tensor (H, W, 3) uint8 BGR
    """
    import torch
    
    H, W = y_plane.shape
    H2, W2 = H // 2, W // 2
    
    # Upsample UV planes to full resolution
    # uv_plane is (H/2, W/2, 2) -> separate U and V
    u = uv_plane[:, :, 0]  # (H/2, W/2)
    v = uv_plane[:, :, 1]  # (H/2, W/2)
    
    # Upsample using nearest neighbor (fastest on GPU)
    u_up = u.repeat_interleave(2, dim=0).repeat_interleave(2, dim=1)  # (H, W)
    v_up = v.repeat_interleave(2, dim=0).repeat_interleave(2, dim=1)  # (H, W)
    
    # Convert to float for computation
    y = y_plane.float()
    u_up = u_up.float() - 128.0
    v_up = v_up.float() - 128.0
    
    # BT.601 YUV -> RGB conversion
    # R = Y + 1.402 * V
    # G = Y - 0.344136 * U - 0.714136 * V
    # B = Y + 1.772 * U
    r = y + 1.402 * v_up
    g = y - 0.344136 * u_up - 0.714136 * v_up
    b = y + 1.772 * u_up
    
    # Clamp to [0, 255] and convert to uint8
    bgr = torch.stack([b.clamp(0, 255), g.clamp(0, 255), r.clamp(0, 255)], dim=2).to(torch.uint8)
    
    return bgr


def nv12_to_rgb_gpu(y_plane, uv_plane):
    """
    Convert NV12 (Y + interleaved UV) to RGB on GPU using PyTorch operations.
    
    Args:
        y_plane: PyTorch CUDA tensor (H, W) uint8
        uv_plane: PyTorch CUDA tensor (H/2, W/2, 2) uint8 (interleaved U,V)
    
    Returns:
        PyTorch CUDA tensor (H, W, 3) uint8 RGB
    """
    import torch
    
    H, W = y_plane.shape
    
    # Upsample UV planes to full resolution
    u = uv_plane[:, :, 0]  # (H/2, W/2)
    v = uv_plane[:, :, 1]  # (H/2, W/2)
    
    u_up = u.repeat_interleave(2, dim=0).repeat_interleave(2, dim=1)  # (H, W)
    v_up = v.repeat_interleave(2, dim=0).repeat_interleave(2, dim=1)  # (H, W)
    
    # Convert to float for computation
    y = y_plane.float()
    u_up = u_up.float() - 128.0
    v_up = v_up.float() - 128.0
    
    # BT.601 YUV -> RGB conversion
    r = y + 1.402 * v_up
    g = y - 0.344136 * u_up - 0.714136 * v_up
    b = y + 1.772 * u_up
    
    # Clamp to [0, 255] and convert to uint8
    rgb = torch.stack([r.clamp(0, 255), g.clamp(0, 255), b.clamp(0, 255)], dim=2).to(torch.uint8)
    
    return rgb


def nv12_to_bgr_tensor_letterbox(y_plane, uv_plane, target_size: int, padding_value: int = 114):
    """
    Convert NV12 to BGR with letterbox resize to target_size x target_size on GPU.
    
    Args:
        y_plane: PyTorch CUDA tensor (H, W) uint8
        uv_plane: PyTorch CUDA tensor (H/2, W/2, 2) uint8
        target_size: Target square size (e.g., 640)
        padding_value: Padding value for letterbox
    
    Returns:
        tuple: (bgr_tensor, scale, (pad_w, pad_h))
        - bgr_tensor: (target_size, target_size, 3) uint8 BGR
        - scale: float scaling factor applied
        - pad_w, pad_h: padding amounts
    """
    import torch
    import torch.nn.functional as F
    
    H, W = y_plane.shape
    
    # First convert NV12 to BGR
    bgr = nv12_to_bgr_gpu(y_plane, uv_plane)  # (H, W, 3)
    
    # Letterbox resize
    scale = min(target_size / W, target_size / H)
    new_w = int(W * scale)
    new_h = int(H * scale)
    
    # Resize using bilinear interpolation
    # bgr is HWC, need CHW for interpolate
    bgr_chw = bgr.permute(2, 0, 1).unsqueeze(0).float() / 255.0  # (1, 3, H, W)
    resized = F.interpolate(bgr_chw, size=(new_h, new_w), mode='bilinear', align_corners=False)
    resized = (resized * 255).clamp(0, 255).to(torch.uint8).squeeze(0).permute(1, 2, 0)  # (new_h, new_w, 3)
    
    # Create padded canvas
    canvas = torch.full((target_size, target_size, 3), padding_value, dtype=torch.uint8, device=bgr.device)
    
    # Calculate padding
    pad_h = (target_size - new_h) // 2
    pad_w = (target_size - new_w) // 2
    
    # Place resized image in center
    canvas[pad_h:pad_h+new_h, pad_w:pad_w+new_w] = resized
    
    return canvas, scale, (pad_w, pad_h)


def nv12_crop_and_resize_gpu(y_plane, uv_plane, bbox, target_h, target_w):
    """
    Crop ROI from NV12 planes and resize to target size on GPU.
    
    Args:
        y_plane: PyTorch CUDA tensor (H, W) uint8
        uv_plane: PyTorch CUDA tensor (H/2, W/2, 2) uint8
        bbox: (x1, y1, x2, y2) in full-frame coordinates
        target_h: Target height
        target_w: Target width
    
    Returns:
        PyTorch CUDA tensor (target_h, target_w, 3) uint8 BGR
    """
    import torch
    import torch.nn.functional as F
    
    x1, y1, x2, y2 = map(int, bbox)
    x1 = max(0, min(x1, y_plane.shape[1] - 1))
    y1 = max(0, min(y1, y_plane.shape[0] - 1))
    x2 = max(0, min(x2, y_plane.shape[1]))
    y2 = max(0, min(y2, y_plane.shape[0]))
    
    if x2 <= x1 or y2 <= y1:
        # Return empty tensor of target size
        return torch.zeros((target_h, target_w, 3), dtype=torch.uint8, device=y_plane.device)
    
    # Crop Y plane
    y_crop = y_plane[y1:y2, x1:x2]
    
    # Crop UV plane (UV is half resolution)
    uv_x1, uv_y1 = x1 // 2, y1 // 2
    uv_x2, uv_y2 = (x2 + 1) // 2, (y2 + 1) // 2
    uv_crop = uv_plane[uv_y1:uv_y2, uv_x1:uv_x2]
    
    # Convert cropped NV12 to BGR
    bgr_crop = nv12_to_bgr_gpu(y_crop, uv_crop)
    
    # Resize to target
    bgr_chw = bgr_crop.permute(2, 0, 1).unsqueeze(0).float() / 255.0
    resized = F.interpolate(bgr_chw, size=(target_h, target_w), mode='bilinear', align_corners=False)
    result = (resized * 255).clamp(0, 255).to(torch.uint8).squeeze(0).permute(1, 2, 0)
    
    return result