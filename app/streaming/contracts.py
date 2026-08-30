"""
Phase 32 — Streaming Contracts.

Defines the explicit contract for RTMP → MediaMTX → RTSP camera streaming.
All contracts are serializable and use deterministic IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class StreamProtocol(str, Enum):
    """Streaming protocol."""
    RTMP = "rtmp"
    RTSP = "rtsp"


class StreamCodec(str, Enum):
    """Video codec."""
    H264 = "h264"
    H265 = "h265"
    VP8 = "vp8"
    VP9 = "vp9"
    UNKNOWN = "unknown"


class StreamHealthState(str, Enum):
    """Stream health states."""
    OFFLINE = "offline"
    CONNECTING = "connecting"
    LIVE = "live"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass(frozen=True)
class RTMPPath:
    """RTMP input path configuration."""
    app: str = "live"
    stream_key: str = ""
    
    def to_url(self, host: str = "localhost", port: int = 1935) -> str:
        """Generate RTMP URL."""
        return f"rtmp://{host}:{port}/{self.app}/{self.stream_key}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {"app": self.app, "stream_key": self.stream_key}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RTMPPath":
        return cls(app=data.get("app", "live"), stream_key=data.get("stream_key", ""))


@dataclass(frozen=True)
class RTSPPath:
    """RTSP output path configuration."""
    path: str = ""
    
    def to_url(self, host: str = "localhost", port: int = 8554) -> str:
        """Generate RTSP URL."""
        return f"rtsp://{host}:{port}/{self.path}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RTSPPath":
        return cls(path=data.get("path", ""))


@dataclass(frozen=True)
class StreamMetadata:
    """Stream metadata/provenance information."""
    camera_id: str
    codec: StreamCodec = StreamCodec.H264
    width: int = 3840
    height: int = 2160
    fps: float = 30.0
    bitrate_kbps: Optional[int] = None
    source_timestamp: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "codec": self.codec.value,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "bitrate_kbps": self.bitrate_kbps,
            "source_timestamp": self.source_timestamp,
            "extra": self.extra,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreamMetadata":
        return cls(
            camera_id=data["camera_id"],
            codec=StreamCodec(data.get("codec", "h264")),
            width=data.get("width", 3840),
            height=data.get("height", 2160),
            fps=data.get("fps", 30.0),
            bitrate_kbps=data.get("bitrate_kbps"),
            source_timestamp=data.get("source_timestamp"),
            extra=data.get("extra", {}),
        )
    
    @property
    def resolution(self) -> tuple:
        return (self.width, self.height)
    
    def is_4k_h264_30fps(self) -> bool:
        """Check if stream matches 4K H.264 30 FPS contract."""
        return (
            self.codec == StreamCodec.H264
            and self.width == 3840
            and self.height == 2160
            and abs(self.fps - 30.0) < 0.1
        )
@dataclass(frozen=True)
class CameraStreamConfig:
    """Configuration for a single camera stream."""
    camera_id: str
    rtmp: RTMPPath
    rtsp: RTSPPath
    expected_metadata: StreamMetadata
    enabled: bool = True
    reconnect_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "rtmp": self.rtmp.to_dict(),
            "rtsp": self.rtsp.to_dict(),
            "expected_metadata": self.expected_metadata.to_dict(),
            "enabled": self.enabled,
            "reconnect_enabled": self.reconnect_enabled,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraStreamConfig":
        return cls(
            camera_id=data["camera_id"],
            rtmp=RTMPPath.from_dict(data["rtmp"]),
            rtsp=RTSPPath.from_dict(data["rtsp"]),
            expected_metadata=StreamMetadata.from_dict(data["expected_metadata"]),
            enabled=data.get("enabled", True),
            reconnect_enabled=data.get("reconnect_enabled", True),
        )


@dataclass(frozen=True)
class CameraStreamContract:
    """
    Complete camera stream contract.
    
    This is the single source of truth for camera stream configuration.
    It defines the RTMP input, MediaMTX routing, RTSP output, and expected stream properties.
    """
    # Camera identification
    camera_id: str
    
    # RTMP input (from camera/publisher)
    rtmp_path: RTMPPath
    
    # RTSP output (from MediaMTX to ingestion)
    rtsp_path: RTSPPath
    
    # Expected stream properties
    expected_codec: StreamCodec = StreamCodec.H264
    expected_resolution: tuple = (3840, 2160)
    expected_fps: float = 30.0
    
    # Stream lifecycle
    enabled: bool = True
    reconnect_enabled: bool = True
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    version: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "rtmp_path": self.rtmp_path.to_dict(),
            "rtsp_path": self.rtsp_path.to_dict(),
            "expected_codec": self.expected_codec.value,
            "expected_resolution": list(self.expected_resolution),
            "expected_fps": self.expected_fps,
            "enabled": self.enabled,
            "reconnect_enabled": self.reconnect_enabled,
            "created_at": self.created_at,
            "version": self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraStreamContract":
        return cls(
            camera_id=data["camera_id"],
            rtmp_path=RTMPPath.from_dict(data["rtmp_path"]),
            rtsp_path=RTSPPath.from_dict(data["rtsp_path"]),
            expected_codec=StreamCodec(data.get("expected_codec", "h264")),
            expected_resolution=tuple(data.get("expected_resolution", [3840, 2160])),
            expected_fps=data.get("expected_fps", 30.0),
            enabled=data.get("enabled", True),
            reconnect_enabled=data.get("reconnect_enabled", True),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            version=data.get("version", 1),
        )
    
    def get_rtmp_url(self, host: str = "localhost", port: int = 1935) -> str:
        """Get RTMP input URL."""
        return self.rtmp_path.to_url(host, port)
    
    def get_rtsp_url(self, host: str = "localhost", port: int = 8554) -> str:
        """Get RTSP output URL."""
        return self.rtsp_path.to_url(host, port)
    
    def validate_codec(self, actual_codec: StreamCodec) -> bool:
        """Validate actual codec matches expected."""
        return actual_codec == self.expected_codec
    
    def validate_resolution(self, width: int, height: int) -> bool:
        """Validate actual resolution matches expected."""
        return (width, height) == self.expected_resolution
    
    def validate_fps(self, actual_fps: float, tolerance: float = 1.0) -> bool:
        """Validate actual FPS matches expected within tolerance."""
        return abs(actual_fps - self.expected_fps) <= tolerance


def create_camera_stream_contract(
    camera_id: str,
    rtmp_stream_key: str,
    rtsp_path: str,
    expected_codec: StreamCodec = StreamCodec.H264,
    expected_resolution: tuple = (3840, 2160),
    expected_fps: float = 30.0,
    enabled: bool = True,
    reconnect_enabled: bool = True,
) -> CameraStreamContract:
    """Factory function to create a camera stream contract."""
    return CameraStreamContract(
        camera_id=camera_id,
        rtmp_path=RTMPPath(stream_key=rtmp_stream_key),
        rtsp_path=RTSPPath(path=rtsp_path),
        expected_codec=expected_codec,
        expected_resolution=expected_resolution,
        expected_fps=expected_fps,
        enabled=enabled,
        reconnect_enabled=reconnect_enabled,
    )


def validate_camera_stream_contract(contract: CameraStreamContract) -> tuple[bool, list[str]]:
    """
    Validate a camera stream contract.
    
    Returns:
        (is_valid, list_of_errors)
    """
    errors = []
    
    if not contract.camera_id:
        errors.append("camera_id is required")
    
    if not contract.rtmp_path.stream_key:
        errors.append("rtmp stream_key is required")
    
    if not contract.rtsp_path.path:
        errors.append("rtsp path is required")
    
    if contract.expected_codec != StreamCodec.H264:
        errors.append(f"Only H.264 codec is supported, got {contract.expected_codec.value}")
    
    if contract.expected_resolution != (3840, 2160):
        errors.append(f"Only 3840x2160 resolution is supported, got {contract.expected_resolution}")
    
    if abs(contract.expected_fps - 30.0) > 0.1:
        errors.append(f"Only 30 FPS is supported, got {contract.expected_fps}")
    
    return len(errors) == 0, errors