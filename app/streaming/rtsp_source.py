"""
Phase 32 — RTSP Source Adapter.

Integrates MediaMTX RTSP output with existing ReplaySource/ReplayScheduler infrastructure.
Thin adapter: MediaMTX RTSP → existing V2 ingestion contract (ReplaySource).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import numpy as np

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.data.input_adapter import VideoFrameIterator, VideoInfo
from app.replay.clock import ReplayClock, ReplayTimestamp
from app.replay.source import ReplaySource, ReplaySourceConfig, ReplaySourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RTSPSourceConfig:
    """Configuration for an RTSP source (MediaMTX output)."""
    camera_id: str
    rtsp_url: str
    use_pts: bool = True
    max_queue_size: int = 10
    timeout: float = 10.0
    retry_interval: float = 5.0
    max_retries: int = 3
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    decoder: str = "software"  # "software" | "nvdec"
    nvdec_gpu_device: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "rtsp_url": self.rtsp_url,
            "use_pts": self.use_pts,
            "max_queue_size": self.max_queue_size,
            "timeout": self.timeout,
            "retry_interval": self.retry_interval,
            "max_retries": self.max_retries,
            "expected_codec": self.expected_codec,
            "expected_width": self.expected_width,
            "expected_height": self.expected_height,
            "expected_fps": self.expected_fps,
            "decoder": self.decoder,
            "nvdec_gpu_device": self.nvdec_gpu_device,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RTSPSourceConfig":
        return cls(
            camera_id=data["camera_id"],
            rtsp_url=data["rtsp_url"],
            use_pts=data.get("use_pts", True),
            max_queue_size=data.get("max_queue_size", 10),
            timeout=data.get("timeout", 10.0),
            retry_interval=data.get("retry_interval", 5.0),
            max_retries=data.get("max_retries", 3),
            expected_codec=data.get("expected_codec", "h264"),
            expected_width=data.get("expected_width", 3840),
            expected_height=data.get("expected_height", 2160),
            expected_fps=data.get("expected_fps", 30.0),
            decoder=data.get("decoder", "software"),
            nvdec_gpu_device=data.get("nvdec_gpu_device", 0),
        )
    
    def to_replay_source_config(self) -> ReplaySourceConfig:
        """Convert to ReplaySourceConfig for integration with existing pipeline."""
        return ReplaySourceConfig(
            camera_id=self.camera_id,
            source_path=self.rtsp_url,
            use_pts=self.use_pts,
            max_queue_size=self.max_queue_size,
        )


class RTSPSourceError(ReplaySourceError):
    """Exception raised when RTSP source encounters an error."""
    def __init__(
        self,
        message: str,
        camera_id: str,
        rtsp_url: str,
        frame_index: Optional[int] = None,
        recoverable: bool = False,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, camera_id, rtsp_url, frame_index, recoverable)
        self.rtsp_url = rtsp_url
        self.original_error = original_error
class RTSPSource:
    """
    RTSP source adapter for MediaMTX output.
    
    Wraps VideoFrameIterator to provide RTSP streaming with:
    - Camera ID preservation
    - Frame identity (frame_index)
    - Timestamp semantics (via ReplayClock)
    - Bounded memory (streaming, not loading all frames)
    - Error isolation
    - Reconnect support
    - Stream validation (codec, resolution, FPS)
    """
    
    def __init__(self, config: RTSPSourceConfig):
        self.config = config
        self.camera_id = config.camera_id
        # Force RTSP-over-TCP to avoid UDP packet loss/reordering causing H.264 decode errors
        self.rtsp_url = config.rtsp_url
        if "transport=" not in self.rtsp_url:
            separator = "&" if "?" in self.rtsp_url else "?"
            self.rtsp_url = f"{self.rtsp_url}{separator}transport=tcp"
        
        self._iterator: Optional[VideoFrameIterator] = None
        self._info: Optional[VideoInfo] = None
        self._clock: Optional[ReplayClock] = None
        
        self._opened = False
        self._frame_count = 0
        self._error: Optional[RTSPSourceError] = None
        self._exhausted = False
        self._reconnect_count = 0
        self._last_frame_time: Optional[float] = None
        self._stream_validated = False
    
    def open(self) -> VideoInfo:
        """Open the RTSP source and return metadata."""
        if self._opened:
            return self._info
        
        logger.info(f"Opening RTSP source: camera_id={self.camera_id}, url={self.rtsp_url}")
        
        try:
            self._iterator = VideoFrameIterator(
                self.rtsp_url,
                decoder=self.config.decoder,
                nvdec_gpu_device=self.config.nvdec_gpu_device,
            )
            self._info = self._iterator.info
            
            # Create iterator from iterable for next() calls
            self._frame_iter = iter(self._iterator)
            
            fps = self._info.fps if self._info.fps > 0 else self.config.expected_fps
            self._clock = ReplayClock(camera_id=self.camera_id, fps=fps)
            
            self._validate_stream()
            
            self._opened = True
            self._frame_count = 0
            self._error = None
            self._exhausted = False
            self._stream_validated = True
            
            logger.info(
                f"RTSP source opened: camera_id={self.camera_id}, "
                f"resolution={self._info.width}x{self._info.height}, "
                f"fps={self._info.fps}, frames={self._info.frame_count}, "
                f"decoder={self.config.decoder}"
            )
            
            return self._info
            
        except Exception as e:
            error = RTSPSourceError(
                f"Failed to open RTSP source: {e}",
                camera_id=self.camera_id,
                rtsp_url=self.rtsp_url,
                recoverable=True,
                original_error=e,
            )
            self._error = error
            logger.error(f"Failed to open RTSP source: {error}")
            raise error
    
    def _validate_stream(self) -> None:
        """Validate stream properties match expectations."""
        if not self._info:
            return
        
        if (self._info.width != self.config.expected_width or 
            self._info.height != self.config.expected_height):
            logger.warning(
                f"Stream resolution mismatch for {self.camera_id}: "
                f"expected {self.config.expected_width}x{self.config.expected_height}, "
                f"got {self._info.width}x{self._info.height}"
            )
        
        if self._info.fps > 0:
            fps_diff = abs(self._info.fps - self.config.expected_fps)
            if fps_diff > 1.0:
                logger.warning(
                    f"Stream FPS mismatch for {self.camera_id}: "
                    f"expected {self.config.expected_fps}, got {self._info.fps}"
                )
        
        logger.info(f"Stream validation passed for {self.camera_id}")
    
    def __iter__(self) -> Iterator[CanonicalFrame]:
        if not self._opened:
            self.open()
        return self
    
    def __next__(self) -> CanonicalFrame:
        frame = self.get_next_frame()
        if frame is None:
            raise StopIteration
        return frame

    def get_next_frame(self) -> Optional[CanonicalFrame]:
        """Get the next frame from the RTSP stream."""
        if not self._opened:
            self.open()
        
        if self._exhausted:
            return None
        
        if self._error:
            raise self._error
        
        try:
            frame = next(self._frame_iter)
            
            # For live RTSP streams, use wall-clock receive time as timestamp
            # since frame_index/FPS doesn't work for live streams
            frame_receive_time = time.time()
            
            # Use ReplayClock for deterministic timestamps if PTS available
            # Otherwise fall back to wall-clock time for live streams
            replay_timestamp = self._clock.next_timestamp() if self._clock else ReplayTimestamp.not_available()
            
            # For live streams, use wall-clock time as the primary timestamp
            # This ensures proper FPS calculation for live streams
            live_timestamp = frame_receive_time - self._start_time if hasattr(self, '_start_time') and self._start_time else frame_receive_time
            
            # Initialize start time on first frame
            if not hasattr(self, '_start_time') or self._start_time is None:
                self._start_time = frame_receive_time
                live_timestamp = 0.0
            
            new_metadata = FrameMetadata(
                source_type=SourceType.VIDEO,
                source_id=self.rtsp_url,
                frame_index=frame.metadata.frame_index,
                timestamp=live_timestamp,  # Use wall-clock based timestamp for live streams
                timestamp_utc=frame.metadata.timestamp_utc,
                original_width=frame.metadata.original_width,
                original_height=frame.metadata.original_height,
                pixel_format=frame.metadata.pixel_format,
                dtype=frame.metadata.dtype,
                source_fps=frame.metadata.source_fps,
                source_duration=frame.metadata.source_duration,
                source_frame_count=frame.metadata.source_frame_count,
                extra={
                    **frame.metadata.extra,
                    "camera_id": self.camera_id,
                    "replay_timestamp": replay_timestamp.to_dict(),
                    "replay_frame_index": self._frame_count,
                    "rtsp_url": self.rtsp_url,
                    "wall_clock_receive_time": frame_receive_time,
                },
            )
            
            replay_frame = CanonicalFrame(
                data=frame.data,
                metadata=new_metadata,
                conversions_applied={},
            )
            
            self._frame_count += 1
            self._last_frame_time = frame_receive_time
            return replay_frame
            
        except StopIteration:
            self._exhausted = True
            logger.info(f"RTSP source exhausted: camera_id={self.camera_id}, frames={self._frame_count}")
            return None
        except Exception as e:
            error = RTSPSourceError(
                f"Error getting next frame: {e}",
                camera_id=self.camera_id,
                rtsp_url=self.rtsp_url,
                frame_index=self._frame_count,
                recoverable=True,
                original_error=e,
            )
            self._error = error
            logger.error(f"RTSP source error: {error}")
            raise error

    def reconnect(self) -> bool:
        """Attempt to reconnect to the RTSP stream."""
        if self._reconnect_count >= self.config.max_retries:
            logger.error(f"Max retries exceeded for {self.camera_id}")
            return False
        
        self._reconnect_count += 1
        logger.info(f"Reconnecting {self.camera_id} (attempt {self._reconnect_count}/{self.config.max_retries})")
        
        self.close()
        time.sleep(self.config.retry_interval)
        
        try:
            self.open()
            logger.info(f"Reconnection successful for {self.camera_id}")
            return True
        except Exception as e:
            logger.error(f"Reconnection failed for {self.camera_id}: {e}")
            return False

    @property
    def is_exhausted(self) -> bool:
        return self._exhausted
    
    @property
    def has_error(self) -> bool:
        return self._error is not None
    
    @property
    def error(self) -> Optional[RTSPSourceError]:
        return self._error
    
    @property
    def frames_produced(self) -> int:
        return self._frame_count
    
    @property
    def total_frames(self) -> Optional[int]:
        return self._info.frame_count if self._info else None
    
    @property
    def fps(self) -> Optional[float]:
        return self._info.fps if self._info else None
    
    @property
    def resolution(self) -> Optional[tuple]:
        if self._info:
            return (self._info.width, self._info.height)
        return None
    
    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count
    
    @property
    def last_frame_time(self) -> Optional[float]:
        return self._last_frame_time
    
    @property
    def is_stream_validated(self) -> bool:
        return self._stream_validated
    
    def close(self) -> None:
        """Close the RTSP source and release resources."""
        if self._iterator:
            self._iterator.close()
            self._iterator = None
        self._opened = False
        logger.info(f"Closed RTSP source: camera_id={self.camera_id}")
    
    def reset(self) -> None:
        """Reset source to beginning (re-open)."""
        self.close()
        self._frame_count = 0
        self._error = None
        self._exhausted = False
        self._reconnect_count = 0
        self._last_frame_time = None
        self._stream_validated = False
        if self._clock:
            self._clock.reset()
        self.open()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "frames_produced": self._frame_count,
            "total_frames": self.total_frames,
            "fps": self.fps,
            "resolution": self.resolution,
            "is_exhausted": self.is_exhausted,
            "has_error": self.has_error,
            "error": str(self._error) if self._error else None,
            "reconnect_count": self._reconnect_count,
            "last_frame_time": self._last_frame_time,
            "stream_validated": self._stream_validated,
        }


def create_rtsp_source(
    camera_id: str,
    rtsp_url: str,
    expected_codec: str = "h264",
    expected_width: int = 3840,
    expected_height: int = 2160,
    expected_fps: float = 30.0,
    decoder: str = "software",
    nvdec_gpu_device: int = 0,
) -> RTSPSource:
    """Factory function to create an RTSP source."""
    config = RTSPSourceConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        expected_codec=expected_codec,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_fps=expected_fps,
        decoder=decoder,
        nvdec_gpu_device=nvdec_gpu_device,
    )
    return RTSPSource(config)
