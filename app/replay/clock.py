"""
Phase 20 — Replay Clock.

Provides deterministic source timing for offline replay.
Uses source PTS as primary, frame_index/FPS as fallback.
Never uses wall-clock or processing time for temporal ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ReplayTimestamp:
    """
    Deterministic replay timestamp with explicit source.
    
    Preferred: source PTS (presentation timestamp from container)
    Fallback: frame_index / FPS
    """
    value: float  # seconds from stream start
    source: str   # "pts", "frame_index_fps", "not_available"
    
    def __lt__(self, other: "ReplayTimestamp") -> bool:
        return self.value < other.value
    
    def __le__(self, other: "ReplayTimestamp") -> bool:
        return self.value <= other.value
    
    def __gt__(self, other: "ReplayTimestamp") -> bool:
        return self.value > other.value
    
    def __ge__(self, other: "ReplayTimestamp") -> bool:
        return self.value >= other.value
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ReplayTimestamp):
            return NotImplemented
        return self.value == other.value
    
    def __hash__(self) -> int:
        return hash((self.value, self.source))
    
    def to_dict(self) -> dict:
        return {"value": self.value, "source": self.source}
    
    @classmethod
    def from_pts(cls, pts: float) -> "ReplayTimestamp":
        """Create from presentation timestamp (seconds)."""
        return cls(value=pts, source="pts")
    
    @classmethod
    def from_frame_index(cls, frame_index: int, fps: float) -> "ReplayTimestamp":
        """Create from frame index and FPS."""
        if fps <= 0:
            return cls(value=0.0, source="not_available")
        return cls(value=frame_index / fps, source="frame_index_fps")
    
    @classmethod
    def not_available(cls) -> "ReplayTimestamp":
        return cls(value=0.0, source="not_available")


class ReplayClock:
    """
    Deterministic clock for a single replay source.
    
    Provides frame timestamps based on source PTS or frame_index/FPS.
    Does NOT use wall-clock or processing completion time.
    """
    
    def __init__(
        self,
        camera_id: str,
        fps: float,
        use_pts: bool = True,
    ):
        """
        Initialize replay clock.
        
        Args:
            camera_id: Camera identifier.
            fps: Source frames per second.
            use_pts: Whether to prefer PTS over frame_index/FPS.
        """
        self.camera_id = camera_id
        self.fps = fps
        self.use_pts = use_pts
        self._frame_index = 0
        self._last_pts: Optional[float] = None
    
    def next_timestamp(self, pts: Optional[float] = None) -> ReplayTimestamp:
        """
        Get timestamp for next frame.
        
        Args:
            pts: Optional presentation timestamp from decoder (seconds).
            
        Returns:
            ReplayTimestamp for the frame.
        """
        if self.use_pts and pts is not None and pts >= 0:
            self._last_pts = pts
            self._frame_index += 1
            return ReplayTimestamp.from_pts(pts)
        
        # Fallback to frame_index / FPS
        timestamp = ReplayTimestamp.from_frame_index(self._frame_index, self.fps)
        self._frame_index += 1
        return timestamp
    
    def peek_timestamp(self, pts: Optional[float] = None) -> ReplayTimestamp:
        """Peek at next timestamp without advancing frame index."""
        if self.use_pts and pts is not None and pts >= 0:
            return ReplayTimestamp.from_pts(pts)
        return ReplayTimestamp.from_frame_index(self._frame_index, self.fps)
    
    @property
    def frame_index(self) -> int:
        """Current frame index (0-based, next frame to be produced)."""
        return self._frame_index
    
    def reset(self) -> None:
        """Reset clock to initial state."""
        self._frame_index = 0
        self._last_pts = None
    
    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "fps": self.fps,
            "use_pts": self.use_pts,
            "frame_index": self._frame_index,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ReplayClock":
        clock = cls(
            camera_id=data["camera_id"],
            fps=data["fps"],
            use_pts=data.get("use_pts", True),
        )
        clock._frame_index = data.get("frame_index", 0)
        return clock