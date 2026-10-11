# Frame contract for PyNvVideoCodec adapter (2.2.3)
# Every decoded/encoded frame must expose these fields.

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class FrameContract:
    # Identity / provenance
    frame_id: int                   # monotonically increasing adapter-level
    camera_id: str                  # e.g. "CAM1"
    source_provenance: str          # e.g. "RTSP" / "file"

    # Media timing (no fabricated values; must come from packet/decoder)
    timestamp: Optional[float]      # presentation timestamp (PTS) in seconds
    pts: Optional[int]              # decoder-provided pts when available
    dts: Optional[int]              # decoder-provided dts when available

    # Dimensions / format
    width: int
    height: int
    # Actual decoded dimensions (may differ from metadata due to decoder contract mismatch)
    # e.g., NVDEC may report 720 but actual Y plane is 480 rows
    actual_width: Optional[int] = None
    actual_height: Optional[int] = None
    pixel_format: str = "NV12"      # "NV12", "NV16", "RGB", etc.
    device_id: int = 0              # CUDA device ordinal (usually 0)

    # Memory identity
    cuda_stream: Optional[int] = None  # non-zero stream ID (explicit contract)
    cuda_memory_ref: Optional[Any] = None  # CAIMemoryView / tensor / capsule reference

    # Ownership / lifetime
    memory_owner: str = "adapter"   # adapter / decoder / AI / encoder
    released: bool = False

    def __post_init__(self):
        # If actual dimensions not explicitly set, fall back to width/height
        if self.actual_width is None:
            self.actual_width = self.width
        if self.actual_height is None:
            self.actual_height = self.height

    @property
    def nbytes(self) -> int:
        # Production payload size for NV12 (1 byte per pixel Y + 0.5 byte per pixel UV = 1.5 bytes/pixel)
        # Used by ingestion health telemetry (ingestion_worker:568) without requiring CPU array upload.
        # Use actual dimensions if available
        w = self.actual_width or self.width
        h = self.actual_height or self.height
        if self.pixel_format == "NV12":
            return int(w * h * 1.5)
        elif self.pixel_format == "NV16":
            return int(w * h * 2)
        elif self.pixel_format == "BGR" or self.pixel_format == "RGB":
            return int(w * h * 3)
        else:
            # Default estimate for GPU-resident frames
            return int(w * h * 2)

    def is_device_memory(self) -> bool:
        return self.cuda_memory_ref is not None and self.device_id >= 0

    def get_gpu_pointers(self) -> tuple[int, int]:
        """
        Get GPU device pointers for NV12 planes from the underlying DecodedFrame.
        Returns (y_ptr, uv_ptr) as integers.
        """
        if self.cuda_memory_ref is None:
            raise RuntimeError("FrameContract has no cuda_memory_ref")
        frame = self.cuda_memory_ref
        if not hasattr(frame, 'GetPtrToPlane'):
            raise RuntimeError("cuda_memory_ref does not have GetPtrToPlane method")
        y_ptr = frame.GetPtrToPlane(0)
        uv_ptr = frame.GetPtrToPlane(1)
        if y_ptr == 0 or uv_ptr == 0:
            raise RuntimeError("Invalid GPU pointers from decoded frame")
        return (y_ptr, uv_ptr)
