"""
Phase 20 — Replay Source / Video Decoder Adapter.

Wraps the existing VideoFrameIterator to provide a replay source
that produces frames with camera_id, frame identity, and timestamp semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import numpy as np

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.data.input_adapter import VideoFrameIterator, VideoInfo
from app.replay.clock import ReplayClock, ReplayTimestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplaySourceConfig:
    """Configuration for a replay source."""
    camera_id: str
    source_path: str
    use_pts: bool = True
    max_queue_size: int = 10  # Bounded queue for memory safety
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "source_path": self.source_path,
            "use_pts": self.use_pts,
            "max_queue_size": self.max_queue_size,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplaySourceConfig":
        return cls(
            camera_id=data["camera_id"],
            source_path=data["source_path"],
            use_pts=data.get("use_pts", True),
            max_queue_size=data.get("max_queue_size", 10),
        )


class ReplaySourceError(Exception):
    """Exception raised when replay source encounters an error."""
    
    def __init__(
        self,
        message: str,
        camera_id: str,
        source_path: str,
        frame_index: Optional[int] = None,
        recoverable: bool = False,
    ):
        super().__init__(message)
        self.camera_id = camera_id
        self.source_path = source_path
        self.frame_index = frame_index
        self.recoverable = recoverable


class ReplaySource:
    """
    Replay source for a single camera video file.
    
    Provides streaming frame iteration with:
    - camera_id preservation
    - frame identity (frame_index)
    - timestamp semantics (via ReplayClock)
    - bounded memory (streaming, not loading all frames)
    - error isolation (errors don't affect other sources)
    """
    
    def __init__(self, config: ReplaySourceConfig):
        """
        Initialize replay source.
        
        Args:
            config: ReplaySourceConfig with camera_id and source_path.
        """
        self.config = config
        self.camera_id = config.camera_id
        self.source_path = config.source_path
        
        # Video iterator (lazy initialization)
        self._iterator: Optional[VideoFrameIterator] = None
        self._info: Optional[VideoInfo] = None
        
        # Clock for deterministic timestamps
        self._clock: Optional[ReplayClock] = None
        
        # State
        self._opened = False
        self._frame_count = 0
        self._error: Optional[ReplaySourceError] = None
        self._exhausted = False
    
    def open(self) -> VideoInfo:
        """
        Open the video source and return metadata.
        
        Returns:
            VideoInfo with source metadata.
            
        Raises:
            ReplaySourceError: If source cannot be opened.
        """
        if self._opened:
            return self._info
        
        try:
            self._iterator = VideoFrameIterator(self.source_path)
            self._info = self._iterator.info
            
            # Initialize clock with source FPS
            fps = self._info.fps if self._info.fps > 0 else 30.0
            self._clock = ReplayClock(
                camera_id=self.camera_id,
                fps=fps,
                use_pts=self.config.use_pts,
            )
            
            self._opened = True
            self._frame_count = 0
            self._error = None
            self._exhausted = False
            
            logger.info(
                f"Opened replay source: camera_id={self.camera_id}, "
                f"path={self.source_path}, "
                f"resolution={self._info.width}x{self._info.height}, "
                f"fps={self._info.fps:.2f}, "
                f"frames={self._info.frame_count}"
            )
            
            return self._info
            
        except FileNotFoundError as e:
            error = ReplaySourceError(
                f"Source file not found: {self.source_path}",
                camera_id=self.camera_id,
                source_path=self.source_path,
                recoverable=False,
            )
            self._error = error
            raise error
        except ValueError as e:
            error = ReplaySourceError(
                f"Failed to open video source: {e}",
                camera_id=self.camera_id,
                source_path=self.source_path,
                recoverable=False,
            )
            self._error = error
            raise error
        except Exception as e:
            error = ReplaySourceError(
                f"Unexpected error opening source: {e}",
                camera_id=self.camera_id,
                source_path=self.source_path,
                recoverable=False,
            )
            self._error = error
            raise error
    
    def __iter__(self) -> Iterator[CanonicalFrame]:
        """
        Iterate over frames from the replay source.
        
        Yields:
            CanonicalFrame with camera_id in metadata.extra and replay timestamp.
            
        Note:
            This is a streaming iterator - one frame at a time.
            Does NOT load all frames into memory.
        """
        if not self._opened:
            self.open()
        
        if self._error:
            raise self._error
        
        if not self._iterator:
            raise ReplaySourceError(
                "Iterator not initialized",
                camera_id=self.camera_id,
                source_path=self.source_path,
            )
        
        try:
            for frame in self._iterator:
                # Get PTS from frame metadata if available
                pts = None
                if hasattr(frame.metadata, 'extra') and frame.metadata.extra:
                    pts = frame.metadata.extra.get('pts')
                
                # Get deterministic timestamp from clock
                replay_timestamp = self._clock.next_timestamp(pts)
                
                # Create new metadata with camera_id and replay timestamp
                new_metadata = FrameMetadata(
                    source_type=frame.metadata.source_type,
                    source_id=frame.metadata.source_id,
                    frame_index=frame.metadata.frame_index,
                    timestamp=replay_timestamp.value,
                    original_width=frame.metadata.original_width,
                    original_height=frame.metadata.original_height,
                    pixel_format=frame.metadata.pixel_format,
                    dtype=frame.metadata.dtype,
                    timestamp_utc=frame.metadata.timestamp_utc,
                    source_fps=frame.metadata.source_fps,
                    source_duration=frame.metadata.source_duration,
                    source_frame_count=frame.metadata.source_frame_count,
                    extra={
                        **frame.metadata.extra,
                        "camera_id": self.camera_id,
                        "replay_timestamp": replay_timestamp.to_dict(),
                        "replay_frame_index": self._frame_count,
                    },
                )
                
                # Create new frame with updated metadata
                replay_frame = CanonicalFrame(
                    data=frame.data,
                    metadata=new_metadata,
                    conversions_applied=frame.conversions_applied,
                )
                
                self._frame_count += 1
                yield replay_frame
                
        except Exception as e:
            error = ReplaySourceError(
                f"Error during frame iteration: {e}",
                camera_id=self.camera_id,
                source_path=self.source_path,
                frame_index=self._frame_count,
                recoverable=False,
            )
            self._error = error
            raise error
        finally:
            self._exhausted = True
    
    def get_next_frame(self) -> Optional[CanonicalFrame]:
        """
        Get the next frame (non-iterator interface).
        
        Returns:
            Next CanonicalFrame or None if exhausted/error.
        """
        if not self._opened:
            self.open()
        
        if self._error or self._exhausted or not self._iterator:
            return None
        
        try:
            frame = next(self._iterator)
            
            # Get PTS from frame metadata if available
            pts = None
            if hasattr(frame.metadata, 'extra') and frame.metadata.extra:
                pts = frame.metadata.extra.get('pts')
            
            # Get deterministic timestamp from clock
            replay_timestamp = self._clock.next_timestamp(pts)
            
            # Create new metadata with camera_id and replay timestamp
            new_metadata = FrameMetadata(
                source_type=frame.metadata.source_type,
                source_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                timestamp=replay_timestamp.value,
                original_width=frame.metadata.original_width,
                original_height=frame.metadata.original_height,
                pixel_format=frame.metadata.pixel_format,
                dtype=frame.metadata.dtype,
                timestamp_utc=frame.metadata.timestamp_utc,
                source_fps=frame.metadata.source_fps,
                source_duration=frame.metadata.source_duration,
                source_frame_count=frame.metadata.source_frame_count,
                extra={
                    **frame.metadata.extra,
                    "camera_id": self.camera_id,
                    "replay_timestamp": replay_timestamp.to_dict(),
                    "replay_frame_index": self._frame_count,
                },
            )
            
            replay_frame = CanonicalFrame(
                data=frame.data,
                metadata=new_metadata,
                conversions_applied=frame.conversions_applied,
            )
            
            self._frame_count += 1
            return replay_frame
            
        except StopIteration:
            self._exhausted = True
            return None
        except Exception as e:
            error = ReplaySourceError(
                f"Error getting next frame: {e}",
                camera_id=self.camera_id,
                source_path=self.source_path,
                frame_index=self._frame_count,
                recoverable=False,
            )
            self._error = error
            raise error
    
    @property
    def is_exhausted(self) -> bool:
        """Check if source has been fully consumed."""
        return self._exhausted
    
    @property
    def has_error(self) -> bool:
        """Check if source has encountered an error."""
        return self._error is not None
    
    @property
    def error(self) -> Optional[ReplaySourceError]:
        """Get the error if any."""
        return self._error
    
    @property
    def frames_produced(self) -> int:
        """Get number of frames produced so far."""
        return self._frame_count
    
    @property
    def total_frames(self) -> Optional[int]:
        """Get total frames in source (from metadata)."""
        return self._info.frame_count if self._info else None
    
    @property
    def fps(self) -> Optional[float]:
        """Get source FPS."""
        return self._info.fps if self._info else None
    
    @property
    def resolution(self) -> Optional[tuple]:
        """Get source resolution (width, height)."""
        if self._info:
            return (self._info.width, self._info.height)
        return None
    
    def close(self) -> None:
        """Close the replay source and release resources."""
        if self._iterator:
            self._iterator.close()
            self._iterator = None
        self._opened = False
        logger.info(f"Closed replay source: camera_id={self.camera_id}")
    
    def reset(self) -> None:
        """Reset source to beginning (re-open)."""
        self.close()
        self._frame_count = 0
        self._error = None
        self._exhausted = False
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
        }