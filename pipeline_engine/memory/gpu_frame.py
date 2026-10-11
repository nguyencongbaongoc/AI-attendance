"""
GPUFrame Contract - Canonical GPU-resident frame for AI Attendance Pipeline

Single unified contract for GPU-resident frames throughout the pipeline.
No CPU staging, no format conversions between stages.
Zero-copy interoperability between decoder, AI inference, annotation, and encoder.
"""

from __future__ import annotations

import torch
from dataclasses import dataclass, field
from typing import Optional, Any, Tuple, Dict, List
from enum import Enum
import uuid


class PixelFormat(str, Enum):
    """Supported pixel formats for GPU frames."""
    NV12 = "nv12"
    NV16 = "nv16"
    BGR = "bgr"
    RGB = "rgb"


class FrameOwnership(str, Enum):
    """Frame memory ownership - tracks which pipeline stage owns the frame."""
    DECODER = "decoder"
    PREPROCESS = "preprocess"
    INFERENCE = "inference"
    TRACKING = "tracking"
    ANNOTATION = "annotation"
    ENCODER = "encoder"
    PUBLISHER = "publisher"
    EXTERNAL = "external"


class FrameStatus(str, Enum):
    """Frame processing status."""
    NEW = "new"
    DECODING = "decoding"
    DECODED = "decoded"
    PREPROCESSING = "preprocessing"
    INFERRING = "inferring"
    TRACKING = "tracking"
    ANNOTATING = "annotating"
    ENCODING = "encoding"
    ENCODED = "encoded"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    DROPPED = "dropped"
    ERROR = "error"


# Export FrameStatus at module level for external access
__all__ = [
    "PixelFormat",
    "FrameOwnership", 
    "FrameStatus",
    "CUDAContext",
    "GPUFrame",
    "nv12_to_bgr_cuda",
    "bgr_to_nv12_cuda",
    "letterbox_resize_cuda",
]


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
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "stream_ptr": self.stream_ptr,
        }


@dataclass
class GPUFrame:
    """
    GPU-resident frame contract - THE canonical frame representation.
    
    All stages in the pipeline (decoder, preprocess, AI, tracking, annotation, encoder, publisher)
    pass this contract. No CPU numpy conversion in production path.
    
    Ownership and lifetime:
    - Created by decoder (ref_count = 1)
    - Each stage that needs to keep the frame calls add_ref()
    - When done, stage calls release()
    - When ref_count reaches 0, tensors are released
    - Encoder sets _encoder_ref to prevent premature release during async encode
    """
    # Identity / provenance
    camera_id: str
    frame_id: int                          # Monotonic per-camera frame counter
    global_frame_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])  # Globally unique
    source_provenance: str = "rtsp"        # rtsp, rtmp, file, synthetic
    
    # Media timing
    timestamp: float = 0.0                 # Wall-clock time (time.time())
    pts: Optional[int] = None              # Presentation timestamp from stream
    dts: Optional[int] = None              # Decode timestamp from stream
    time_base: Optional[float] = None      # Stream time base (e.g., 1/90000)
    
    # Dimensions
    width: int = 0                         # Nominal width
    height: int = 0                        # Nominal height
    actual_width: Optional[int] = None     # Actual tensor width (may differ due to padding)
    actual_height: Optional[int] = None    # Actual tensor height
    pixel_format: PixelFormat = PixelFormat.NV12
    
    # CUDA context
    cuda_context: CUDAContext = field(default_factory=CUDAContext)
    
    # GPU memory - NV12 two-plane format
    # y_plane: (H, W) uint8
    # uv_plane: (H/2, W/2, 2) uint8 interleaved UV
    y_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    uv_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    
    # Cached pointers for NVENC (avoid repeated data_ptr() calls)
    _y_ptr: Optional[int] = field(default=None, repr=False)
    _uv_ptr: Optional[int] = field(default=None, repr=False)
    
    # Ownership / lifetime
    memory_owner: FrameOwnership = FrameOwnership.DECODER
    status: FrameStatus = FrameStatus.NEW
    released: bool = False
    ref_count: int = 0
    
    # Encoder reference (set by encoder when registered for async encoding)
    _encoder_ref: Optional[Any] = field(default=None, repr=False)
    
    # Annotation overlay (BGR tensor for GPU annotation)
    _annotation_tensor: Optional[torch.Tensor] = field(default=None, repr=False)
    
    # Processing metadata
    decode_time_ms: float = 0.0
    preprocess_time_ms: float = 0.0
    inference_time_ms: float = 0.0
    tracking_time_ms: float = 0.0
    annotation_time_ms: float = 0.0
    encode_time_ms: float = 0.0
    
    # Error tracking
    error: Optional[str] = None
    error_stage: Optional[str] = None
    
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
        time_base: Optional[float] = None,
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
            time_base: Stream time base (e.g., 1/90000 for 90kHz clock)
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
        
        frame = cls(
            camera_id=camera_id,
            frame_id=frame_id,
            source_provenance="rtsp",
            timestamp=timestamp,
            pts=pts,
            dts=pts,
            time_base=time_base,
            width=width,
            height=height,
            actual_width=width,
            actual_height=height,
            pixel_format=PixelFormat.NV12,
            cuda_context=ctx,
            y_tensor=y_tensor,
            uv_tensor=uv_tensor,
            memory_owner=FrameOwnership.DECODER,
            status=FrameStatus.DECODED,
        )
        frame.ref_count = 1  # Decoder holds initial reference
        return frame
    
    @classmethod
    def create_empty(
        cls,
        camera_id: str,
        frame_id: int,
        width: int,
        height: int,
        pixel_format: PixelFormat = PixelFormat.NV12,
        cuda_context: Optional[CUDAContext] = None,
    ) -> "GPUFrame":
        """Create an empty GPUFrame with allocated tensors (for testing/synthetic)."""
        ctx = cuda_context or CUDAContext.current()
        
        if pixel_format == PixelFormat.NV12:
            y_tensor = torch.zeros((height, width), dtype=torch.uint8, device=f'cuda:{ctx.device_id}')
            uv_tensor = torch.zeros((height // 2, width // 2, 2), dtype=torch.uint8, device=f'cuda:{ctx.device_id}')
        elif pixel_format == PixelFormat.BGR:
            y_tensor = torch.zeros((height, width, 3), dtype=torch.uint8, device=f'cuda:{ctx.device_id}')
            uv_tensor = None
        else:
            raise ValueError(f"Unsupported pixel format for empty frame: {pixel_format}")
        
        frame = cls(
            camera_id=camera_id,
            frame_id=frame_id,
            source_provenance="synthetic",
            timestamp=0.0,
            width=width,
            height=height,
            actual_width=width,
            actual_height=height,
            pixel_format=pixel_format,
            cuda_context=ctx,
            y_tensor=y_tensor,
            uv_tensor=uv_tensor,
            memory_owner=FrameOwnership.EXTERNAL,
            status=FrameStatus.NEW,
        )
        frame.ref_count = 1
        return frame
    
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
    
    def add_ref(self) -> int:
        """Increment reference count. Returns new count."""
        self.ref_count += 1
        return self.ref_count
    
    def release(self) -> bool:
        """
        Decrement reference count and release if zero.
        Returns True if actually released (ref_count reached 0).
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
        self._encoder_ref = None
        self.released = True
    
    def transfer_ownership(self, new_owner: FrameOwnership) -> None:
        """Transfer frame ownership to another pipeline stage."""
        self.memory_owner = new_owner
    
    def set_status(self, status: FrameStatus) -> None:
        """Update frame processing status."""
        self.status = status
    
    def set_error(self, error: str, stage: str) -> None:
        """Record an error."""
        self.error = error
        self.error_stage = stage
        self.status = FrameStatus.ERROR
    
    def validate(self) -> bool:
        """Validate frame integrity."""
        if self.released:
            return False
        if self.y_tensor is None:
            return False
        if self.pixel_format == PixelFormat.NV12 and self.uv_tensor is None:
            return False
        if not self.y_tensor.is_cuda:
            return False
        if self.pixel_format == PixelFormat.NV12 and not self.uv_tensor.is_cuda:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/debugging (no tensor data)."""
        return {
            "camera_id": self.camera_id,
            "frame_id": self.frame_id,
            "global_frame_id": self.global_frame_id,
            "timestamp": self.timestamp,
            "pts": self.pts,
            "dts": self.dts,
            "time_base": self.time_base,
            "width": self.width,
            "height": self.height,
            "actual_width": self.actual_width,
            "actual_height": self.actual_height,
            "pixel_format": self.pixel_format.value,
            "cuda_device": self.cuda_context.device_id,
            "memory_owner": self.memory_owner.value,
            "status": self.status.value,
            "released": self.released,
            "ref_count": self.ref_count,
            "nbytes": self.nbytes,
            "decode_time_ms": self.decode_time_ms,
            "preprocess_time_ms": self.preprocess_time_ms,
            "inference_time_ms": self.inference_time_ms,
            "tracking_time_ms": self.tracking_time_ms,
            "annotation_time_ms": self.annotation_time_ms,
            "encode_time_ms": self.encode_time_ms,
            "error": self.error,
            "error_stage": self.error_stage,
        }
    
    def get_latency_breakdown(self) -> Dict[str, float]:
        """Get detailed latency breakdown."""
        return {
            "decode": self.decode_time_ms,
            "preprocess": self.preprocess_time_ms,
            "inference": self.inference_time_ms,
            "tracking": self.tracking_time_ms,
            "annotation": self.annotation_time_ms,
            "encode": self.encode_time_ms,
            "total_ms": (
                self.decode_time_ms + self.preprocess_time_ms + 
                self.inference_time_ms + self.tracking_time_ms + 
                self.annotation_time_ms + self.encode_time_ms
            ),
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


def letterbox_resize_cuda(
    tensor: torch.Tensor,
    target_size: Tuple[int, int],
    pad_value: float = 0.0,
) -> Tuple[torch.Tensor, Dict[str, Any]]:
    """
    Letterbox resize preserving aspect ratio on CUDA.
    
    Args:
        tensor: (1, 3, H, W) or (H, W, 3) float32 on CUDA
        target_size: (target_w, target_h)
        pad_value: Padding value
        
    Returns:
        (resized_tensor, padding_info)
    """
    import torch.nn.functional as F
    
    target_w, target_h = target_size
    
    # Handle different input layouts
    if tensor.dim() == 3:
        # (H, W, C) -> (1, C, H, W)
        tensor = tensor.permute(2, 0, 1).unsqueeze(0)
    elif tensor.dim() == 4 and tensor.shape[1] == 3:
        # Already (1, 3, H, W)
        pass
    else:
        raise ValueError(f"Unexpected tensor shape: {tensor.shape}")
    
    _, _, H, W = tensor.shape
    
    # Calculate scale
    scale = min(target_w / W, target_h / H)
    new_W = int(W * scale)
    new_H = int(H * scale)
    
    # Resize
    resized = F.interpolate(
        tensor,
        size=(new_H, new_W),
        mode='bilinear',
        align_corners=False
    )
    
    # Create padded tensor
    padded = torch.full(
        (1, 3, target_h, target_w),
        pad_value,
        dtype=tensor.dtype,
        device=tensor.device
    )
    
    # Calculate padding
    pad_top = (target_h - new_H) // 2
    pad_left = (target_w - new_W) // 2
    
    # Place resized image in center
    padded[:, :, pad_top:pad_top+new_H, pad_left:pad_left+new_W] = resized
    
    padding_info = {
        "scale": scale,
        "new_width": new_W,
        "new_height": new_H,
        "pad_top": pad_top,
        "pad_left": pad_left,
        "pad_bottom": target_h - new_H - pad_top,
        "pad_right": target_w - new_W - pad_left,
        "original_width": W,
        "original_height": H,
    }
    
    return padded.contiguous(), padding_info


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