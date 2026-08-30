"""
Phase 20 — Replay Scheduler.

Generic scheduler over multiple replay sources.
Orders frames by replay timestamp.
Camera state remains isolated.
N-camera capable architecture.
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.data.frame import CanonicalFrame
from app.replay.clock import ReplayTimestamp
from app.replay.source import ReplaySource, ReplaySourceConfig, ReplaySourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplaySchedulerConfig:
    """Configuration for the replay scheduler."""
    # Maximum number of frames to buffer per source (bounded memory)
    max_buffer_per_source: int = 10
    # Maximum total frames in scheduler buffer
    max_total_buffer: int = 100
    # Timestamp ordering policy
    # "strict" = require timestamps, "lenient" = allow not_available
    timestamp_policy: str = "strict"
    # Out-of-order handling
    # "sort" = sort by timestamp, "reject" = reject out-of-order
    out_of_order_policy: str = "sort"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_buffer_per_source": self.max_buffer_per_source,
            "max_total_buffer": self.max_total_buffer,
            "timestamp_policy": self.timestamp_policy,
            "out_of_order_policy": self.out_of_order_policy,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplaySchedulerConfig":
        return cls(
            max_buffer_per_source=data.get("max_buffer_per_source", 10),
            max_total_buffer=data.get("max_total_buffer", 100),
            timestamp_policy=data.get("timestamp_policy", "strict"),
            out_of_order_policy=data.get("out_of_order_policy", "sort"),
        )


@dataclass
class ScheduledFrame:
    """A frame scheduled for processing with its timestamp and source info."""
    frame: CanonicalFrame
    timestamp: ReplayTimestamp
    camera_id: str
    source_frame_index: int
    
    def __lt__(self, other: "ScheduledFrame") -> bool:
        # For heap ordering: earlier timestamps first
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        # Tie-breaker: camera_id for determinism
        return self.camera_id < other.camera_id


class ReplayScheduler:
    """
    Generic scheduler for multiple replay sources.
    
    Features:
    - N-camera capable (not hardcoded to 2)
    - Frames ordered by replay timestamp
    - Camera state isolation
    - Bounded memory buffers
    - Early termination handling
    - Error isolation
    """
    
    def __init__(
        self,
        sources: List[ReplaySource],
        config: Optional[ReplaySchedulerConfig] = None,
    ):
        """
        Initialize scheduler with replay sources.
        
        Args:
            sources: List of ReplaySource objects (already configured).
            config: Scheduler configuration.
        """
        self.sources = sources
        self.config = config or ReplaySchedulerConfig()
        
        # Per-source state
        self._source_iterators: Dict[str, Iterator[CanonicalFrame]] = {}
        self._source_buffers: Dict[str, List[ScheduledFrame]] = {}
        self._source_exhausted: Dict[str, bool] = {}
        self._source_errors: Dict[str, Optional[ReplaySourceError]] = {}
        
        # Global state
        self._global_buffer: List[ScheduledFrame] = []  # min-heap by timestamp
        self._total_frames_scheduled = 0
        self._total_frames_yielded = 0
        self._active_sources = set()
        
        # Initialize per-source state
        for source in self.sources:
            camera_id = source.camera_id
            self._source_buffers[camera_id] = []
            self._source_exhausted[camera_id] = False
            self._source_errors[camera_id] = None
            self._active_sources.add(camera_id)
    
    def _fill_buffer(self, camera_id: str) -> None:
        """Fill buffer for a specific source up to max_buffer_per_source."""
        if camera_id not in self._source_iterators:
            # Find source and create iterator
            source = next((s for s in self.sources if s.camera_id == camera_id), None)
            if not source:
                return
            try:
                self._source_iterators[camera_id] = iter(source)
            except ReplaySourceError as e:
                self._source_errors[camera_id] = e
                self._source_exhausted[camera_id] = True
                logger.error(f"Source {camera_id} failed to initialize: {e}")
                return
        
        buffer = self._source_buffers[camera_id]
        iterator = self._source_iterators.get(camera_id)
        
        if not iterator or self._source_exhausted[camera_id]:
            return
        
        # Fill buffer
        while len(buffer) < self.config.max_buffer_per_source:
            try:
                frame = next(iterator)
                
                # Extract timestamp from frame metadata
                timestamp = self._extract_timestamp(frame)
                
                # Validate timestamp
                if self.config.timestamp_policy == "strict":
                    if timestamp.source == "not_available":
                        logger.warning(f"Frame from {camera_id} has no timestamp, skipping")
                        continue
                
                scheduled = ScheduledFrame(
                    frame=frame,
                    timestamp=timestamp,
                    camera_id=camera_id,
                    source_frame_index=frame.metadata.frame_index,
                )
                buffer.append(scheduled)
                
            except StopIteration:
                self._source_exhausted[camera_id] = True
                logger.info(f"Source {camera_id} exhausted")
                break
            except ReplaySourceError as e:
                self._source_errors[camera_id] = e
                self._source_exhausted[camera_id] = True
                logger.error(f"Source {camera_id} error: {e}")
                break
            except Exception as e:
                error = ReplaySourceError(
                    f"Unexpected error reading frame: {e}",
                    camera_id=camera_id,
                    source_path="",
                    recoverable=False,
                )
                self._source_errors[camera_id] = error
                self._source_exhausted[camera_id] = True
                logger.error(f"Source {camera_id} unexpected error: {e}")
                break
    
    def _extract_timestamp(self, frame: CanonicalFrame) -> ReplayTimestamp:
        """Extract replay timestamp from frame metadata."""
        extra = frame.metadata.extra or {}
        
        # Check for replay_timestamp in extra
        if "replay_timestamp" in extra:
            rt = extra["replay_timestamp"]
            return ReplayTimestamp(value=rt["value"], source=rt["source"])
        
        # Fallback to frame metadata timestamp
        if frame.metadata.timestamp is not None:
            return ReplayTimestamp(value=frame.metadata.timestamp, source="frame_metadata")
        
        return ReplayTimestamp.not_available()
    
    def _push_to_global_buffer(self, scheduled: ScheduledFrame) -> bool:
        """
        Push a scheduled frame to the global buffer.
        
        Returns:
            True if pushed, False if buffer full.
        """
        if len(self._global_buffer) >= self.config.max_total_buffer:
            return False
        
        heapq.heappush(self._global_buffer, scheduled)
        self._total_frames_scheduled += 1
        return True
    
    def _refill_global_buffer(self) -> None:
        """Refill global buffer from source buffers."""
        # Try to push frames from each source buffer
        for camera_id in list(self._active_sources):
            buffer = self._source_buffers[camera_id]
            
            # Fill source buffer if needed
            if not buffer and not self._source_exhausted[camera_id]:
                self._fill_buffer(camera_id)
                buffer = self._source_buffers[camera_id]
            
            # Push frames from source buffer to global buffer
            while buffer and len(self._global_buffer) < self.config.max_total_buffer:
                scheduled = buffer.pop(0)
                self._push_to_global_buffer(scheduled)
    
    def __iter__(self) -> Iterator[CanonicalFrame]:
        """
        Iterate over frames in timestamp order.
        
        Yields:
            CanonicalFrame objects in deterministic timestamp order.
        """
        # Initial fill
        self._refill_global_buffer()
        
        while self._global_buffer or self._active_sources:
            # Refill if global buffer is getting low
            if len(self._global_buffer) < self.config.max_total_buffer // 2:
                self._refill_global_buffer()
            
            if not self._global_buffer:
                # Check if all sources are exhausted
                if all(self._source_exhausted.get(cid, True) for cid in self._active_sources):
                    break
                # Wait for more frames (shouldn't happen in offline replay)
                continue
            
            # Pop earliest frame
            scheduled = heapq.heappop(self._global_buffer)
            
            # Handle out-of-order if needed
            if (self.config.out_of_order_policy == "reject" and 
                self._total_frames_yielded > 0):
                # This would require tracking last yielded timestamp per camera
                # For now, we use "sort" policy which handles ordering via heap
                pass
            
            self._total_frames_yielded += 1
            yield scheduled.frame
            
            # Try to refill from the same source
            camera_id = scheduled.camera_id
            if not self._source_exhausted[camera_id]:
                self._fill_buffer(camera_id)
                # Push any new frames to global buffer
                buffer = self._source_buffers[camera_id]
                while buffer and len(self._global_buffer) < self.config.max_total_buffer:
                    s = buffer.pop(0)
                    self._push_to_global_buffer(s)
        
        logger.info(
            f"Scheduler finished: {self._total_frames_yielded} frames yielded "
            f"from {len(self.sources)} sources"
        )
    
    def get_next_frame(self) -> Optional[CanonicalFrame]:
        """
        Get next frame in timestamp order (non-iterator interface).
        
        Returns:
            Next CanonicalFrame or None if all sources exhausted.
        """
        # Ensure global buffer has frames
        self._refill_global_buffer()
        
        if not self._global_buffer:
            # Check if all sources exhausted
            if all(self._source_exhausted.get(cid, True) for cid in self._active_sources):
                return None
            return None
        
        scheduled = heapq.heappop(self._global_buffer)
        self._total_frames_yielded += 1
        
        # Refill from same source
        camera_id = scheduled.camera_id
        if not self._source_exhausted[camera_id]:
            self._fill_buffer(camera_id)
            buffer = self._source_buffers[camera_id]
            while buffer and len(self._global_buffer) < self.config.max_total_buffer:
                s = buffer.pop(0)
                self._push_to_global_buffer(s)
        
        return scheduled.frame
    
    @property
    def active_sources(self) -> List[str]:
        """Get list of active (non-exhausted, non-error) camera IDs."""
        return [
            cid for cid in self._active_sources
            if not self._source_exhausted.get(cid, True) and not self._source_errors.get(cid)
        ]
    
    @property
    def exhausted_sources(self) -> List[str]:
        """Get list of exhausted camera IDs."""
        return [
            cid for cid in self._active_sources
            if self._source_exhausted.get(cid, False)
        ]
    
    @property
    def error_sources(self) -> Dict[str, ReplaySourceError]:
        """Get dict of camera_id -> error for sources with errors."""
        return {
            cid: err for cid, err in self._source_errors.items()
            if err is not None
        }
    
    @property
    def total_frames_yielded(self) -> int:
        """Total frames yielded so far."""
        return self._total_frames_yielded
    
    @property
    def total_frames_scheduled(self) -> int:
        """Total frames scheduled (including buffered)."""
        return self._total_frames_scheduled
    
    def get_source_stats(self, camera_id: str) -> Dict[str, Any]:
        """Get statistics for a specific source."""
        source = next((s for s in self.sources if s.camera_id == camera_id), None)
        if not source:
            return {"error": "Source not found"}
        
        return {
            "camera_id": camera_id,
            "frames_produced": source.frames_produced,
            "total_frames": source.total_frames,
            "is_exhausted": self._source_exhausted.get(camera_id, False),
            "has_error": self._source_errors.get(camera_id) is not None,
            "error": str(self._source_errors[camera_id]) if self._source_errors.get(camera_id) else None,
            "buffer_size": len(self._source_buffers.get(camera_id, [])),
        }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all sources."""
        return {
            "total_frames_yielded": self._total_frames_yielded,
            "total_frames_scheduled": self._total_frames_scheduled,
            "global_buffer_size": len(self._global_buffer),
            "active_sources": self.active_sources,
            "exhausted_sources": self.exhausted_sources,
            "error_sources": {cid: str(err) for cid, err in self.error_sources.items()},
            "per_source": {
                cid: self.get_source_stats(cid) for cid in self._active_sources
            },
        }
    
    def close_all(self) -> None:
        """Close all sources."""
        for source in self.sources:
            source.close()
    
    def reset_all(self) -> None:
        """Reset all sources and scheduler state."""
        for source in self.sources:
            source.reset()
        
        self._source_iterators.clear()
        for cid in self._source_buffers:
            self._source_buffers[cid].clear()
        self._source_exhausted = {cid: False for cid in self._active_sources}
        self._source_errors = {cid: None for cid in self._active_sources}
        self._global_buffer.clear()
        self._total_frames_scheduled = 0
        self._total_frames_yielded = 0


def create_scheduler(
    source_configs: List[ReplaySourceConfig],
    config: Optional[ReplaySchedulerConfig] = None,
) -> ReplayScheduler:
    """
    Factory function to create a scheduler from source configs.
    
    Args:
        source_configs: List of ReplaySourceConfig objects.
        config: Optional scheduler configuration.
        
    Returns:
        ReplayScheduler with initialized sources.
    """
    sources = [ReplaySource(cfg) for cfg in source_configs]
    return ReplayScheduler(sources, config)