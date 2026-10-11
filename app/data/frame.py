"""
Phase 20 — Canonical Frame Data Structures.

Provides the core data structures for frame representation across the pipeline:
- CanonicalFrame: Unified frame container with metadata
- FrameMetadata: Rich metadata for frame provenance and processing
- PixelFormat: Enumeration of supported pixel formats
- SourceType: Enumeration of frame source types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
import numpy as np

# Import adapter FrameContract for GPU contract unification
try:
    from app.video.pynvcodec.frame_contract import FrameContract
except Exception:
    FrameContract = None  # type: ignore


class PixelFormat(Enum):
    """Supported pixel formats for frame data."""
    RGB = "rgb"
    BGR = "bgr"
    GRAY = "gray"
    YUV420P = "yuv420p"
    NV12 = "nv12"
    UNKNOWN = "unknown"


class SourceType(Enum):
    """Source type classification for frames."""
    IMAGE = "image"
    VIDEO = "video"
    RTSP = "rtsp"
    RTMP = "rtmp"
    WEBCAM = "webcam"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


@dataclass
class FrameMetadata:
    """
    Rich metadata for a frame, capturing provenance, format, and processing history.
    
    This is the single source of truth for frame identity and processing context.
    """
    # Source identification
    source_type: SourceType = SourceType.UNKNOWN
    source_id: str = ""  # Path, URL, camera ID, etc.
    frame_index: int = 0  # Zero-based frame index within source
    
    # Temporal information
    timestamp: float = 0.0  # Relative timestamp in seconds from source start
    timestamp_utc: Optional[str] = None  # ISO 8601 UTC timestamp if available
    
    # Spatial information
    original_width: int = 0
    original_height: int = 0
    pixel_format: PixelFormat = PixelFormat.UNKNOWN
    dtype: str = "uint8"
    
    # Source properties
    source_fps: float = 0.0
    source_duration: float = 0.0
    source_frame_count: int = 0
    
    # Phase R3.14-H.9: Frame age instrumentation (optional)
    # Per-stage timestamps for pipeline latency measurement.
    # Stored in extra dict; provided here for type clarity.
    capture_timestamp: Optional[float] = None  # When frame was captured by camera
    decode_timestamp: Optional[float] = None   # When NVDEC/software decoded the frame
    inference_start: Optional[float] = None    # When AI inference started
    inference_end: Optional[float] = None      # When AI inference ended
    annotation_start: Optional[float] = None   # When annotation started
    annotation_end: Optional[float] = None     # When annotation ended
    encode_start: Optional[float] = None       # When encode started
    encode_end: Optional[float] = None         # When encode ended
    
    # Extensible extra fields for pipeline-specific data
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "timestamp_utc": self.timestamp_utc,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "pixel_format": self.pixel_format.value,
            "dtype": self.dtype,
            "source_fps": self.source_fps,
            "source_duration": self.source_duration,
            "source_frame_count": self.source_frame_count,
            "capture_timestamp": self.capture_timestamp,
            "decode_timestamp": self.decode_timestamp,
            "inference_start": self.inference_start,
            "inference_end": self.inference_end,
            "annotation_start": self.annotation_start,
            "annotation_end": self.annotation_end,
            "encode_start": self.encode_start,
            "encode_end": self.encode_end,
            "extra": self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrameMetadata":
        """Create from dictionary."""
        return cls(
            source_type=SourceType(data.get("source_type", "unknown")),
            source_id=data.get("source_id", ""),
            frame_index=data.get("frame_index", 0),
            timestamp=data.get("timestamp", 0.0),
            timestamp_utc=data.get("timestamp_utc"),
            original_width=data.get("original_width", 0),
            original_height=data.get("original_height", 0),
            pixel_format=PixelFormat(data.get("pixel_format", "unknown")),
            dtype=data.get("dtype", "uint8"),
            source_fps=data.get("source_fps", 0.0),
            source_duration=data.get("source_duration", 0.0),
            source_frame_count=data.get("source_frame_count", 0),
            capture_timestamp=data.get("capture_timestamp"),
            decode_timestamp=data.get("decode_timestamp"),
            inference_start=data.get("inference_start"),
            inference_end=data.get("inference_end"),
            annotation_start=data.get("annotation_start"),
            annotation_end=data.get("annotation_end"),
            encode_start=data.get("encode_start"),
            encode_end=data.get("encode_end"),
            extra=data.get("extra", {}),
        )


@dataclass
class CanonicalFrame:
    """
    Canonical frame representation used throughout the pipeline.
    
    Combines raw frame data with rich metadata and tracks applied conversions.
    This is the primary data structure passed between pipeline stages.
    """
    # Frame data as numpy array (H, W, C) or (H, W) for grayscale.
    # H.10-C.3: May also be a dict with DLPack planes (dlpack_y, dlpack_uv,
    # width, height, format) for the PyAV CUDA zero-copy path. In that case
    # the underlying memory is GPU-resident and never copied to CPU.
    data: Any

    # Rich metadata
    metadata: FrameMetadata

    # Track which conversions have been applied (for idempotency)
    conversions_applied: Dict[str, Any] = field(default_factory=dict)

    def with_conversion(self, conversion_name: str) -> "CanonicalFrame":
        """Create a new frame with an additional conversion recorded."""
        new_frame = self.copy()
        new_frame.conversions_applied[conversion_name] = True
        return new_frame

    def __post_init__(self):
        """Validate frame data after initialization."""
        # H.10-C.3: Accept numpy ndarray, CUDA torch tensor, DLPack dict,
        # FrameContract (adapter GPU contract), or adapter contract wrapper.
        if isinstance(self.data, np.ndarray):
            if self.data.ndim not in (2, 3):
                raise ValueError(f"Frame data must be 2D (grayscale) or 3D (color), got {self.data.ndim}D")
            if self.data.ndim == 3 and self.data.shape[2] not in (1, 3, 4):
                raise ValueError(f"Frame data must have 1, 3, or 4 channels, got {self.data.shape[2]}")
            # Validate metadata dimensions match data dimensions
            if self.metadata.original_width and self.metadata.original_height:
                if self.data.shape[1] != self.metadata.original_width:
                    raise ValueError(f"Frame data width {self.data.shape[1]} does not match metadata original_width {self.metadata.original_width}")
                if self.data.shape[0] != self.metadata.original_height:
                    raise ValueError(f"Frame data height {self.data.shape[0]} does not match metadata original_height {self.metadata.original_height}")
        else:
            import torch
            # Adapter FrameContract: canonical GPU contract from R8K
            if FrameContract is not None and isinstance(self.data, FrameContract):
                # Accept adapter FrameContract; metadata preserved via adapter_contract reference in metadata.extra
                # Native GPU payload accessible via .cuda_memory_ref; do NOT convert to CPU array.
                return
            # Adapter wrapper that exposes adapter_contract
            adapter_contract_ref = getattr(self.data, "adapter_contract", None)
            if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
                return
            if isinstance(self.data, torch.Tensor) and self.data.device.type == 'cuda':
                # Phase 3A: GPU-resident CUDA tensor path (GPU-native preprocessing)
                if self.data.dim() not in (3, 4):
                    raise ValueError(f"GPU-resident frame must be 3D (HWC) or 4D (NCHW/NHWC), got {self.data.dim()}D")
            elif isinstance(self.data, dict):
                # PyNvVideoCodec GPU contract dict (watchdog frame or adapter wrapper)
                # Must NOT be confused with legacy PyAV CUDA DLPack path (dlpack_y/dlpack_uv)
                if "dlpack_y" in self.data or "dlpack_uv" in self.data:
                    raise TypeError(
                        "Legacy PyAV CUDA DLPack path (dlpack_y/dlpack_uv) is forbidden in production; "
                        "use adapter FrameContract or PyNvVideoCodec native GPU contract instead (H.10-C.3 deprecated)"
                    )
                # Accept PyNvVideoCodec native GPU contract dict (NV12, adapter reference, GPU frame info)
                return
            else:
                # Native GPU payload: any non-dict, non-ndarray GPU reference (e.g. CUDA capsule, CAIMemoryView, native payload)
                # Accept if it has __dlpack__ or __cuda_array_interface__, otherwise allow through for adapter pipeline
                has_dlpack = hasattr(self.data, "__dlpack__") or (hasattr(self.data, "__cuda_array_interface__"))
                if has_dlpack:
                    return
                # Allow any other native GPU reference (not FrameContract directly; FrameContract handled above)
                return
    
    @property
    def height(self) -> int:
        """Frame height in pixels."""
        if isinstance(self.data, dict):
            return int(self.data.get("height", self.metadata.original_height or 0))
        # Adapter FrameContract / GPU contract
        if FrameContract is not None and isinstance(self.data, FrameContract):
            # Return actual decoded height (handles NVDEC metadata mismatch)
            return int(self.data.actual_height) if self.data.actual_height is not None else int(self.data.height)
        adapter_contract_ref = getattr(self.data, "adapter_contract", None)
        if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
            return int(adapter_contract_ref.actual_height) if adapter_contract_ref.actual_height is not None else int(adapter_contract_ref.height)
        # GPU adapter wrapper (e.g., GPUFrameContractAdapter)
        if hasattr(self.data, "adapter_contract"):
            adapter_contract_ref = self.data.adapter_contract
            if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
                return int(adapter_contract_ref.actual_height) if adapter_contract_ref.actual_height is not None else int(adapter_contract_ref.height)
            # Fallback to adapter wrapper's own dimensions
            if hasattr(self.data, "height"):
                return int(self.data.height)
        # Native GPU reference (torch CUDA tensor / native CUDA payload)
        try:
            return self.data.shape[0]
        except Exception:
            pass
        return int(self.metadata.original_height or 0)

    @property
    def width(self) -> int:
        """Frame width in pixels."""
        if isinstance(self.data, dict):
            return int(self.data.get("width", self.metadata.original_width or 0))
        if FrameContract is not None and isinstance(self.data, FrameContract):
            # Return actual decoded width (handles NVDEC metadata mismatch)
            return int(self.data.actual_width) if self.data.actual_width is not None else int(self.data.width)
        adapter_contract_ref = getattr(self.data, "adapter_contract", None)
        if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
            return int(adapter_contract_ref.actual_width) if adapter_contract_ref.actual_width is not None else int(adapter_contract_ref.width)
        if hasattr(self.data, "adapter_contract"):
            adapter_contract_ref = self.data.adapter_contract
            if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
                return int(adapter_contract_ref.actual_width) if adapter_contract_ref.actual_width is not None else int(adapter_contract_ref.width)
            if hasattr(self.data, "width"):
                return int(self.data.width)
        try:
            return self.data.shape[1]
        except Exception:
            pass
        return int(self.metadata.original_width or 0)

    @property
    def channels(self) -> int:
        """Number of color channels."""
        if isinstance(self.data, dict):
            return 3  # NV12 (Y + interleaved UV) is treated as 3-channel logically
        if FrameContract is not None and isinstance(self.data, FrameContract):
            # NV12 logical = 3; other adapter pixel formats derived from metadata
            pixel_fmt = getattr(self.data, "pixel_format", None)
            if pixel_fmt == "NV12":
                return 3
            return 3  # Adapter GPU contract default logical channels
        adapter_contract_ref = getattr(self.data, "adapter_contract", None)
        if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
            pixel_fmt = getattr(adapter_contract_ref, "pixel_format", None)
            return 3 if pixel_fmt == "NV12" else 3
        # Native GPU reference
        try:
            if hasattr(self.data, "ndim") and self.data.ndim == 2:
                return 1
            return self.data.shape[2] if self.data.ndim >= 3 else 3
        except Exception:
            pass
        return 3

    @property
    def is_bgr(self) -> bool:
        """Check if frame is in BGR format."""
        if isinstance(self.data, dict):
            return self.data.get("format", "").upper() == "NV12" or self.data.get("format", "").upper() == "BGR"
        if FrameContract is not None and isinstance(self.data, FrameContract):
            return getattr(self.data, "pixel_format", "").upper() in ("NV12", "BGR")
        # For numpy arrays, assume BGR if 3 channels
        try:
            return self.channels == 3
        except Exception:
            return False
    
    @property
    def is_rgb(self) -> bool:
        """Check if frame is in RGB format."""
        if isinstance(self.data, dict):
            return self.data.get("format", "").upper() == "RGB"
        if FrameContract is not None and isinstance(self.data, FrameContract):
            return getattr(self.data, "pixel_format", "").upper() == "RGB"
        return False

    @property
    def shape(self) -> tuple:
        """Frame shape as (height, width, channels)."""
        h = self.height
        w = self.width
        c = self.channels
        return (h, w, c)
    
    def copy(self) -> "CanonicalFrame":
        """Create a deep copy of the frame."""
        # For adapter FrameContract / GPU native references, do NOT copy the GPU payload.
        # Preserve the same reference so lifetime/ownership stays with adapter/decoder.
        data_copy = self.data
        if isinstance(self.data, np.ndarray):
            data_copy = self.data.copy()
        # Metadata deep copy always
        metadata_copy = FrameMetadata(**self.metadata.to_dict())
        # Preserve adapter_contract reference in extra
        adapter_contract_ref = getattr(self.data, "adapter_contract", None)
        if adapter_contract_ref is not None:
            metadata_copy.extra.setdefault("adapter_contract_ref", adapter_contract_ref)
        if FrameContract is not None and isinstance(self.data, FrameContract):
            metadata_copy.extra.setdefault("adapter_contract_ref", self.data)
        native_ref = None
        if FrameContract is not None and isinstance(self.data, FrameContract):
            native_ref = getattr(self.data, "cuda_memory_ref", None)
        elif hasattr(self.data, "cuda_memory_ref"):
            native_ref = self.data.cuda_memory_ref
        if native_ref is not None:
            metadata_copy.extra.setdefault("canonical_representation", native_ref)
        return CanonicalFrame(
            data=data_copy,
            metadata=metadata_copy,
            conversions_applied=self.conversions_applied.copy(),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes raw frame data)."""
        # Preserve adapter_contract in metadata.extra if present on data
        extra = dict(self.metadata.extra) if self.metadata.extra else {}
        adapter_contract_ref = getattr(self.data, "adapter_contract", None)
        if adapter_contract_ref is not None and FrameContract is not None and isinstance(adapter_contract_ref, FrameContract):
            extra.setdefault("adapter_contract", adapter_contract_ref)
        if FrameContract is not None and isinstance(self.data, FrameContract):
            extra.setdefault("adapter_contract", self.data)
        # Keep native GPU reference identity for downstream
        native_ref = None
        if FrameContract is not None and isinstance(self.data, FrameContract):
            native_ref = getattr(self.data, "cuda_memory_ref", None)
        elif hasattr(self.data, "cuda_memory_ref"):
            native_ref = self.data.cuda_memory_ref
        extra.setdefault("canonical_representation", native_ref)
        # Build output preserving pixel_format, width, height, CUDA pointer info
        result = {
            "metadata": self.metadata.to_dict(),
            "conversions_applied": self.conversions_applied,
            "shape": self.shape,
            "pixel_format": getattr(self.metadata, "pixel_format", None),
            "width": self.width,
            "height": self.height,
        }
        if native_ref is not None:
            result["cuda_memory_ref_identity"] = "present"
        if FrameContract is not None and isinstance(self.data, FrameContract):
            result["frame_contract_present"] = True
            result["frame_contract_pixel_format"] = getattr(self.data, "pixel_format", None)
            result["frame_contract_device_id"] = getattr(self.data, "device_id", None)
        # Preserve adapter_contract metadata
        result["metadata_extra"] = extra
        # Dtype: prefer adapter contract metadata if FrameContract, else native reference
        dtype_str = "uint8"
        if FrameContract is not None and isinstance(self.data, FrameContract):
            dtype_str = "uint8"
        elif hasattr(self.data, "dtype"):
            dtype_str = str(self.data.dtype)
        result["dtype"] = dtype_str
        return result


def create_frame_from_array(
    array: np.ndarray,
    source_type: SourceType = SourceType.UNKNOWN,
    source_id: str = "",
    frame_index: int = 0,
    timestamp: float = 0.0,
    pixel_format: PixelFormat = PixelFormat.RGB,
    **extra
) -> CanonicalFrame:
    """
    Factory function to create a CanonicalFrame from a numpy array.
    
    Args:
        array: Frame data as numpy array (H, W, C) or (H, W)
        source_type: Type of source
        source_id: Source identifier
        frame_index: Frame index within source
        timestamp: Relative timestamp in seconds
        pixel_format: Pixel format of the data
        **extra: Additional metadata fields
        
    Returns:
        CanonicalFrame with inferred metadata
    """
    if array.ndim == 2:
        height, width = array.shape
        channels = 1
    else:
        height, width, channels = array.shape
    
    metadata = FrameMetadata(
        source_type=source_type,
        source_id=source_id,
        frame_index=frame_index,
        timestamp=timestamp,
        original_width=width,
        original_height=height,
        pixel_format=pixel_format,
        dtype=str(array.dtype),
        extra=extra,
    )
    
    return CanonicalFrame(
        data=array,
        metadata=metadata,
    )