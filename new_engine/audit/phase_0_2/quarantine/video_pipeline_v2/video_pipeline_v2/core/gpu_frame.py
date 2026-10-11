"""
GPUFrame Contract - V2 GPU-first video pipeline.

Single unified contract for GPU-resident frames throughout the pipeline.
No CPU staging, no format conversions between stages.
"""

from __future__ import annotations

import torch
from dataclasses import dataclass, field
from typing import Optional, Any, Tuple, Dict
from enum import Enum


class PixelFormat(str, Enum):
    """Supported pixel formats for GPU frames."""
    NV12 = "nv12"
    NV16 = "nv16"
    BGR = "bgr"
    RGB = "rgb"


class FrameOwnership(str, Enum):
    """Frame memory ownership."""
    DECODER = "decoder"
    AI = "ai"
    ENCODER = "encoder"
    ANNOTATION = "annotation"
    EXTERNAL = "external"


@dataclass
class CUDAContext:
    """CUDA context and stream information."""
    device_id: int = 0
    context_ptr: int = 0
    stream_ptr: int = 0
    stream: Optional[torch.cuda.Stream] = None
    
    @classmethod
    def current(cls, device_id: int = 0) -> "CUDAContext":
        """Get current CUDA context and stream."""
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available")
        torch.cuda.set_device(device_id)
        stream = torch.cuda.current_stream(device_id)
        return cls(
            device_id=device_id,
            context_ptr=torch.cuda.device(device_id).idx,
            stream_ptr=stream.cuda_stream,
            stream=stream,
        )
    
    def synchronize(self) -> None:
        """Synchronize the CUDA stream."""
        if self.stream:
            self.stream.synchronize()
        else:
            torch.cuda.synchronize(self.device_id)


@dataclass
class GPUFrame:
    """
    GPU-resident frame contract.
    
    All stages in the V2 pipeline (decoder, AI, encoder, annotation)
    pass this contract. No CPU numpy conversion in production path.
    """
    # Identity / provenance
    camera_id: str
    frame_id: int
    source_provenance: str = "rtsp"
    
    # Media timing
    timestamp: float = 0.0
    pts: Optional[int] = None
    dts: Optional[int] = None
    
    # Dimensions
    width: int = 0
    height: int = 0
    actual_width: Optional[int] = None
    actual_height: Optional[int] = None
    pixel_format: PixelFormat = PixelFormat.NV12
    
    # CUDA context
    cuda_context: CUDAContext = field(default_factory=CUDAContext)
    
    # GPU memory - NV12 two-plane format
    # y_plane: (H, W) uint8
    # uv_plane: (H/2, W/2, 2) uint8 interleaved UV
    y_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    uv_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    
    # Cached pointers for NVENC
    _y_ptr: Optional[int] = field(default=None, repr=False)
    _uv_ptr: Optional[int] = field(default=None, repr=False)
    
    # Ownership / lifetime
    memory_owner: FrameOwnership = FrameOwnership.DECODER
    released: bool = False
    ref_count: int = 0
    
    # Encoder reference (set by encoder when registered)
    _encoder_ref: Optional[Any] = field(default=None, repr=False)
    
    # Annotation overlay (BGR tensor for GPU annotation)
    _annotation_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    
    def __post_init__(self):
        if self.actual_width is None:
            self.actual_width = self.width
        if self.actual_height is None:
            self.actual_height = self.height
        self._cache_pointers()
    
    @classmethod
    def from_pyav_nvdec(
        cls,
        y_tensor: torch.Tensor,
        uv_tensor: torch.Tensor,
        camera_id: str,
        frame_id: int,
        timestamp: float,
        pts: int,
        width: int,
        height: int,
        cuda_context: Optional[CUDAContext] = None,
    ) -> "GPUFrame":
        """
        Create GPUFrame from PyAV NVDEC output tensors.
        
        Args:
            y_tensor: Y plane tensor (H, W) uint8 on CUDA
            uv_tensor: UV plane tensor (H/2, W/2, 2) uint8 on CUDA
            camera_id: Camera identifier
            frame_id: Monotonic frame counter
            timestamp: Wall-clock timestamp
            pts: Presentation timestamp
            width: Frame width
            height: Frame height
            cuda_context: CUDA context (defaults to current)
        """
        # Validate tensors
        assert y_tensor.is_cuda, f"y_plane must be on CUDA, got {y_tensor.device}"
        assert uv_tensor.is_cuda, f"uv_plane must be on CUDA, got {uv_tensor.device}"
        assert y_tensor.dtype == torch.uint8, f"y_plane must be uint8, got {y_tensor.dtype}"
        assert uv_tensor.dtype == torch.uint8, f"uv_plane must be uint8, got {uv_tensor.dtype}"
        
        y_ptr = y_tensor.data_ptr()
        uv_ptr = uv_tensor.data_ptr()
        assert y_ptr != 0, "y_plane data_ptr is 0"
        assert uv_ptr != 0, "uv_plane data_ptr is 0"
        
        ctx = cuda_context or CUDAContext.current()
        
        return cls(
            camera_id=camera_id,
            frame_id=frame_id,
            source_provenance="rtsp",
            timestamp=timestamp,
            pts=pts,
            dts=pts,
            width=width,
            height=height,
            actual_width=width,
            actual_height=height,
            pixel_format=PixelFormat.NV12,
            cuda_context=ctx,
            y_tensor=y_tensor,
            uv_tensor=uv_tensor,
            memory_owner=FrameOwnership.DECODER,
        )
    
    def _cache_pointers(self):
        """Cache GPU pointers from tensors."""
        if self.y_tensor is not None:
            self._y_ptr = self.y_tensor.data_ptr()
        if self.uv_tensor is not None:
            self._uv_ptr = self.uv_tensor.data_ptr()
    
    @property
    def nbytes(self) -> int:
        """Production payload size for the pixel format."""
        w = self.actual_width or self.width
        h = self.actual_height or self.height
        if self.pixel_format == PixelFormat.NV12:
            return int(w * h * 1.5)
        elif self.pixel_format == PixelFormat.NV16:
            return int(w * h * 2)
        elif self.pixel_format in (PixelFormat.BGR, PixelFormat.RGB):
            return int(w * h * 3)
        return int(w * h * 2)
    
    def is_device_memory(self) -> bool:
        return True
    
    def get_gpu_pointers(self) -> Tuple[int, int]:
        """Get GPU device pointers for NV12 planes. Returns (y_ptr, uv_ptr)."""
        if self._y_ptr is None or self._uv_ptr is None:
            self._cache_pointers()
        if self._y_ptr is None or self._uv_ptr is None:
            raise RuntimeError("GPU pointers not available")
        return (self._y_ptr, self._uv_ptr)
    
    def get_tensors(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """Get the underlying PyTorch CUDA tensors (Y, UV)."""
        if self.y_tensor is None or self.uv_tensor is None:
            raise RuntimeError("Tensors not available")
        return (self.y_tensor, self.uv_tensor)
    
    def get_annotation_tensor(self) -> Optional[torch.Tensor]:
        """Get annotation overlay tensor (BGR format)."""
        return self._annotation_tensor
    
    def set_annotation_tensor(self, tensor: torch.Tensor) -> None:
        """Set annotation overlay tensor. Must be BGR on same CUDA device."""
        assert tensor.is_cuda, "Annotation tensor must be on CUDA"
        assert tensor.dtype == torch.uint8, "Annotation tensor must be uint8"
        assert tensor.shape[-1] == 3, "Annotation tensor must be 3-channel (BGR)"
        self._annotation_tensor = tensor
    
    def add_ref(self) -> None:
        """Increment reference count."""
        self.ref_count += 1
    
    def release(self) -> bool:
        """
        Decrement reference count and release if zero.
        Returns True if actually released.
        """
        self.ref_count -= 1
        if self.ref_count <= 0:
            self._release_internal()
            return True
        return False
    
    def _release_internal(self) -> None:
        """Internal release - clears tensor references."""
        self.y_tensor = None
        self.uv_tensor = None
        self._y_ptr = None
        self._uv_ptr = None
        self._annotation_tensor = None
        self.released = True
    
    def transfer_ownership(self, new_owner: FrameOwnership) -> None:
        """Transfer frame ownership to another pipeline stage."""
        self.memory_owner = new_owner
    
    def validate(self) -> bool:
        """Validate frame integrity."""
        if self.released:
            return False
        if self.y_tensor is None or self.uv_tensor is None:
            return False
        if not self.y_tensor.is_cuda or not self.uv_tensor.is_cuda:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/debugging (no tensor data)."""
        return {
            "camera_id": self.camera_id,
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "pts": self.pts,
            "dts": self.dts,
            "width": self.width,
            "height": self.height,
            "pixel_format": self.pixel_format.value,
            "cuda_device": self.cuda_context.device_id,
            "memory_owner": self.memory_owner.value,
            "released": self.released,
            "ref_count": self.ref_count,
            "nbytes": self.nbytes,
        }


def nv12_to_bgr_cuda(
    y_tensor: torch.Tensor,
    uv_tensor: torch.Tensor,
    limited_range: bool = True,
) -> torch.Tensor:
    """
    Convert NV12 CUDA tensors to BGR CUDA tensor using PyTorch CUDA operations.
    Zero-copy GPU-only conversion.
    
    Args:
        y_tensor: (H, W) uint8 on CUDA
        uv_tensor: (H/2, W/2, 2) uint8 on CUDA
        limited_range: If True, use limited range (16-235/240), else full range (0-255)
        
    Returns:
        BGR tensor: (H, W, 3) uint8 on CUDA
    """
    import torch.nn.functional as F
    
    H, W = y_tensor.shape
    
    # Upsample UV to match Y resolution
    uv_upsampled = F.interpolate(
        uv_tensor.permute(2, 0, 1).unsqueeze(0).float(),  # (1, 2, H/2, W/2)
        size=(H, W),
        mode='bilinear',
        align_corners=False
    ).squeeze(0).permute(1, 2, 0)  # (H, W, 2)
    
    # YUV to BGR conversion (BT.601)
    y = y_tensor.float()
    u = uv_upsampled[:, :, 0].float()
    v = uv_upsampled[:, :, 1].float()
    
    if limited_range:
        y = (y - 16.0) * 255.0 / 219.0
        u = (u - 128.0) * 255.0 / 224.0
        v = (v - 128.0) * 255.0 / 224.0
    else:
        u = u - 128.0
        v = v - 128.0
    
    r = torch.clamp(y + 1.402 * v, 0, 255)
    g = torch.clamp(y - 0.344136 * u - 0.714136 * v, 0, 255)
    b = torch.clamp(y + 1.772 * u, 0, 255)
    
    bgr = torch.stack([b, g, r], dim=2).byte()
    
    return bgr


def bgr_to_nv12_cuda(bgr_tensor: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Convert BGR CUDA tensor to NV12 planes (Y + UV).
    Used for GPU annotation -> encoder path.
    
    Args:
        bgr_tensor: (H, W, 3) uint8 on CUDA
        
    Returns:
        Tuple of (y_tensor, uv_tensor)
    """
    import torch.nn.functional as F
    
    H, W, _ = bgr_tensor.shape
    
    bgr_float = bgr_tensor.float()
    b = bgr_float[:, :, 0]
    g = bgr_float[:, :, 1]
    r = bgr_float[:, :, 2]
    
    # BGR to YUV (BT.601, limited range)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.168736 * r - 0.331264 * g + 0.5 * b + 128
    v = 0.5 * r - 0.418688 * g - 0.081312 * b + 128
    
    y = torch.clamp(y, 16, 235).byte()
    u = torch.clamp(u, 16, 240).byte()
    v = torch.clamp(v, 16, 240).byte()
    
    # Downsample UV
    uv = torch.stack([u, v], dim=2)  # (H, W, 2)
    uv_downsampled = F.interpolate(
        uv.permute(2, 0, 1).unsqueeze(0).float(),
        size=(H // 2, W // 2),
        mode='bilinear',
        align_corners=False
    ).squeeze(0).permute(1, 2, 0).byte()  # (H/2, W/2, 2)
    
    return y, uv_downsampled


if __name__ == "__main__":
    # Quick validation
    import numpy as np
    import cv2
    
    H, W = 480, 640
    y_cpu = np.random.randint(16, 236, (H, W), dtype=np.uint8)
    uv_cpu = np.random.randint(16, 241, (H//2, W//2, 2), dtype=np.uint8)
    
    # CPU reference
    uv_interleaved = uv_cpu.reshape(H//2, W)
    nv12_cpu = np.concatenate([y_cpu, uv_interleaved], axis=0)
    bgr_cpu = cv2.cvtColor(nv12_cpu, cv2.COLOR_YUV2BGR_NV12)
    
    # CUDA conversion
    y_cuda = torch.from_numpy(y_cpu).cuda()
    uv_cuda = torch.from_numpy(uv_cpu).cuda()
    bgr_cuda = nv12_to_bgr_cuda(y_cuda, uv_cuda)
    bgr_cuda_cpu = bgr_cuda.cpu().numpy()
    
    diff = np.abs(bgr_cpu.astype(np.float32) - bgr_cuda_cpu.astype(np.float32))
    print(f"Max error: {diff.max():.2f}, Mean: {diff.mean():.4f}")
    print("GPUFrame contract validated!")