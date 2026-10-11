# GPU FrameContract Adapter for PyAV NVDEC
# Wraps PyTorch CUDA tensors from PyAV into FrameContract interface for Native NVENC

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any, Tuple
import time
import torch
import numpy as np


@dataclass
class GPUFrameContract:
    """
    GPU FrameContract adapter for PyAV NVDEC output.
    
    Wraps PyTorch CUDA tensors (y_plane, uv_plane) from PyAV NVDEC decoder
    and provides the FrameContract interface required by Native NVENC Bridge.
    """
    
    # Identity / provenance
    frame_id: int
    camera_id: str
    source_provenance: str = "RTSP"
    
    # Media timing
    timestamp: Optional[float] = None
    pts: Optional[int] = None
    dts: Optional[int] = None
    
    # Dimensions
    width: int = 0
    height: int = 0
    actual_width: Optional[int] = None
    actual_height: Optional[int] = None
    pixel_format: str = "NV12"
    device_id: int = 0
    
    # Metadata compatibility for association pipeline
    @property
    def metadata(self):
        """Compatibility metadata for association pipeline."""
        class SimpleMetadata:
            def __init__(self, frame_contract):
                self.original_width = frame_contract.width
                self.original_height = frame_contract.height
                self.source_id = frame_contract.camera_id
                self.frame_index = frame_contract.frame_id
                self.timestamp = frame_contract.timestamp
        return SimpleMetadata(self)
    
    # Memory identity - PyTorch CUDA tensors
    cuda_stream: Optional[int] = None
    cuda_memory_ref: Optional[Any] = None  # Dict with y_plane, uv_plane tensors
    
    # Ownership / lifetime
    memory_owner: str = "pyav_nvdec"
    released: bool = False
    
    # Internal tensors for pointer access
    _y_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    _uv_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    _y_ptr: Optional[int] = field(default=None, repr=False)
    _uv_ptr: Optional[int] = field(default=None, repr=False)
    
    # Encoder reference for NVENC (set by encoder when registered)
    _encoder_ref: Optional[Any] = field(default=None, repr=False)
    
    # ===== PHASE 10 DEBT: Zero-copy latency instrumentation =====
    # High-resolution monotonic timestamps (nanoseconds) - no GPU-to-CPU copies
    t_packet_ingress_ns: int = 0        # Compressed packet demuxed from RTSP socket
    t_decode_submit_ns: int = 0         # Packet submitted to PyNvDecoder.Decode()
    t_gpu_frame_ready_ns: int = 0       # Decoded CUDA surface validated & wrapped
    t_pipeline_egress_ns: int = 0       # GPUFrame dispatched to downstream consumers
    
    def __post_init__(self):
        if self.actual_width is None:
            self.actual_width = self.width
        if self.actual_height is None:
            self.actual_height = self.height
        
        # Cache tensor pointers for NVENC
        if self._y_tensor is not None and self._uv_tensor is not None:
            self._cache_pointers()
    
    @classmethod
    def from_pyav_frame_data(
        cls,
        frame_data: dict,
        frame_id: int,
        camera_id: str,
        timestamp: float,
        pts: int,
        cuda_stream: Optional[int] = None,
    ) -> "GPUFrameContract":
        """
        Create GPUFrameContract from PyAV NVDEC frame_data dict.
        
        Args:
            frame_data: Dict from PyAV NVDEC with keys:
                - y_plane: PyTorch CUDA tensor (H, W) uint8
                - uv_plane: PyTorch CUDA tensor (H/2, W/2, 2) uint8
                - width: int
                - height: int
                - format: str
                - pts: int
            frame_id: Monotonic frame counter
            camera_id: Camera identifier
            timestamp: Wall-clock timestamp
            pts: Presentation timestamp
            cuda_stream: CUDA stream handle
        """
        y_tensor = frame_data["y_plane"]
        uv_tensor = frame_data["uv_plane"]
        width = frame_data["width"]
        height = frame_data["height"]
        
        # Validate tensors are on CUDA
        assert y_tensor.is_cuda, f"y_plane must be on CUDA, got {y_tensor.device}"
        assert uv_tensor.is_cuda, f"uv_plane must be on CUDA, got {uv_tensor.device}"
        assert y_tensor.dtype == torch.uint8, f"y_plane must be uint8, got {y_tensor.dtype}"
        assert uv_tensor.dtype == torch.uint8, f"uv_plane must be uint8, got {uv_tensor.dtype}"
        
        # Get CUDA pointers
        y_ptr = y_tensor.data_ptr()
        uv_ptr = uv_tensor.data_ptr()
        
        assert y_ptr != 0, "y_plane data_ptr is 0"
        assert uv_ptr != 0, "uv_plane data_ptr is 0"
        
        return cls(
            frame_id=frame_id,
            camera_id=camera_id,
            source_provenance="RTSP",
            timestamp=timestamp,
            pts=pts,
            dts=pts,
            width=width,
            height=height,
            actual_width=width,
            actual_height=height,
            pixel_format="NV12",
            device_id=0,
            cuda_stream=cuda_stream or 0,
            cuda_memory_ref={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
            },
            memory_owner="pyav_nvdec",
            _y_tensor=y_tensor,
            _uv_tensor=uv_tensor,
            _y_ptr=y_ptr,
            _uv_ptr=uv_ptr,
        )
    
    def _cache_pointers(self):
        """Cache GPU pointers from tensors."""
        if self._y_tensor is not None:
            self._y_ptr = self._y_tensor.data_ptr()
        if self._uv_tensor is not None:
            self._uv_ptr = self._uv_tensor.data_ptr()
    
    @property
    def nbytes(self) -> int:
        """Production payload size for NV12."""
        w = self.actual_width or self.width
        h = self.actual_height or self.height
        if self.pixel_format == "NV12":
            return int(w * h * 1.5)
        elif self.pixel_format == "NV16":
            return int(w * h * 2)
        elif self.pixel_format in ("BGR", "RGB"):
            return int(w * h * 3)
        else:
            return int(w * h * 2)
    
    def is_device_memory(self) -> bool:
        return True
    
    def get_gpu_pointers(self) -> Tuple[int, int]:
        """
        Get GPU device pointers for NV12 planes.
        Returns (y_ptr, uv_ptr) as integers.
        """
        if self._y_ptr is None or self._uv_ptr is None:
            self._cache_pointers()
        if self._y_ptr is None or self._uv_ptr is None:
            raise RuntimeError("GPU pointers not available")
        return (self._y_ptr, self._uv_ptr)
    
    def get_tensors(self) -> Tuple[torch.Tensor, torch.Tensor]:
        """Get the underlying PyTorch CUDA tensors."""
        return (self._y_tensor, self._uv_tensor)
    
    def release(self):
        """Release tensor references."""
        self._y_tensor = None
        self._uv_tensor = None
        self._y_ptr = None
        self._uv_ptr = None
        self.released = True


def nv12_cuda_to_bgr_cuda(
    y_tensor: torch.Tensor,
    uv_tensor: torch.Tensor,
    limited_range: bool = True,
) -> torch.Tensor:
    """
    Convert NV12 CUDA tensors to BGR CUDA tensor using PyTorch CUDA operations.
    
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
        # Limited range (16-235 for Y, 16-240 for UV)
        y = (y - 16.0) * 255.0 / 219.0
        u = (u - 128.0) * 255.0 / 224.0
        v = (v - 128.0) * 255.0 / 224.0
    else:
        # Full range (0-255)
        u = u - 128.0
        v = v - 128.0
    
    # BT.601 conversion coefficients
    r = torch.clamp(y + 1.402 * v, 0, 255)
    g = torch.clamp(y - 0.344136 * u - 0.714136 * v, 0, 255)
    b = torch.clamp(y + 1.772 * u, 0, 255)
    
    # Stack to BGR
    bgr = torch.stack([b, g, r], dim=2).byte()
    
    return bgr


def nv12_cuda_to_rgb_cuda(
    y_tensor: torch.Tensor,
    uv_tensor: torch.Tensor,
    limited_range: bool = True,
) -> torch.Tensor:
    """
    Convert NV12 CUDA tensors to RGB CUDA tensor using PyTorch CUDA operations.
    
    Args:
        y_tensor: (H, W) uint8 on CUDA
        uv_tensor: (H/2, W/2, 2) uint8 on CUDA
        limited_range: If True, use limited range (16-235/240), else full range (0-255)
        
    Returns:
        RGB tensor: (H, W, 3) uint8 on CUDA
    """
    import torch.nn.functional as F
    
    H, W = y_tensor.shape
    
    uv_upsampled = F.interpolate(
        uv_tensor.permute(2, 0, 1).unsqueeze(0).float(),
        size=(H, W),
        mode='bilinear',
        align_corners=False
    ).squeeze(0).permute(1, 2, 0)
    
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
    
    rgb = torch.stack([r, g, b], dim=2).byte()
    
    return rgb
    v = uv_upsampled[:, :, 1].float() - 128.0
    
    r = torch.clamp(y + 1.402 * v, 0, 255)
    g = torch.clamp(y - 0.344136 * u - 0.714136 * v, 0, 255)
    b = torch.clamp(y + 1.772 * u, 0, 255)
    
    rgb = torch.stack([r, g, b], dim=2).byte()
    
    return rgb


def validate_cuda_conversion():
    """Validate CUDA NV12→BGR conversion against CPU reference."""
    import cv2
    
    # Create test pattern
    H, W = 480, 640
    y_cpu = np.random.randint(0, 256, (H, W), dtype=np.uint8)
    uv_cpu = np.random.randint(0, 256, (H//2, W//2, 2), dtype=np.uint8)
    
    # CPU reference (OpenCV) - NV12 format: Y plane + interleaved UV
    # OpenCV expects NV12 as Y plane + UV plane (interleaved)
    uv_interleaved = uv_cpu.reshape(H//2, W)  # Interleave UV: (H/2, W)
    nv12_cpu = np.concatenate([y_cpu, uv_interleaved], axis=0)
    bgr_cpu = cv2.cvtColor(nv12_cpu, cv2.COLOR_YUV2BGR_NV12)
    
    # CUDA conversion
    y_cuda = torch.from_numpy(y_cpu).cuda()
    uv_cuda = torch.from_numpy(uv_cpu).cuda()
    bgr_cuda = nv12_cuda_to_bgr_cuda(y_cuda, uv_cuda)
    bgr_cuda_cpu = bgr_cuda.cpu().numpy()
    
    # Compare
    diff = np.abs(bgr_cpu.astype(np.float32) - bgr_cuda_cpu.astype(np.float32))
    max_diff = diff.max()
    mean_diff = diff.mean()
    
    print(f"CUDA NV12->BGR validation:")
    print(f"  Max absolute error: {max_diff:.2f}")
    print(f"  Mean absolute error: {mean_diff:.4f}")
    print(f"  Shapes: CPU={bgr_cpu.shape}, CUDA={bgr_cuda_cpu.shape}")
    
    return max_diff < 2.0  # Allow small interpolation differences


if __name__ == "__main__":
    validate_cuda_conversion()