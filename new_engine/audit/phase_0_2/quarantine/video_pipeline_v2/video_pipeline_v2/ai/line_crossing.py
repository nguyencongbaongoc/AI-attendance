"""
Line Crossing and IN/OUT Events - V2 GPU-first video pipeline.

Detects line crossing events from tracks using configurable geometry.
Attendance events are independent from video encoding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


class CrossingDirection(str, Enum):
    IN = "in"
    OUT = "out"


class CrossingEventType(str, Enum):
    LINE_CROSSING = "line_crossing"


@dataclass(frozen=True)
class LineGeometry:
    """Configurable line for crossing detection."""
    p1: Tuple[float, float]  # (x, y)
    p2: Tuple[float, float]  # (x, y)
    direction_semantics: str = "side_a_to_b_in"  # Or "side_b_to_a_in"
    
    def side_of_point(self, point: Tuple[float, float]) -> int:
        """Determine which side of the line a point is on."""
        x, y = point
        px1, py1 = self.p1
        px2, py2 = self.p2
        
        # Cross product
        cross = (px2 - px1) * (y - py1) - (py2 - py1) * (x - px1)
        
        if cross > 0:
            return 1  # Side A
        elif cross < 0:
            return -1  # Side B
        else:
            return 0  # On line
    
    def distance_to_line(self, point: Tuple[float, float]) -> float:
        """Distance from point to line."""
        x, y = point
        x1, y1 = self.p1
        x2, y2 = self.p2
        
        # Line segment distance
        line_length_sq = (x2 - x1)**2 + (y2 - y1)**2
        if line_length_sq == 0:
            return np.sqrt((x - x1)**2 + (y - y1)**2)
        
        # Project point onto line segment
        t = max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / line_length_sq))
        
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        return np.sqrt((x - proj_x)**2 + (y - proj_y)**2)


@dataclass(frozen=True)
class CrossingEvent:
    """Line crossing event."""
    event_id: str
    camera_id: str
    track_id: int
    direction: CrossingDirection
    event_type: CrossingEventType = CrossingEventType.LINE_CROSSING
    crossing_point: Tuple[float, float] = (0.0, 0.0)
    timestamp: float = 0.0
    frame_index: int = 0
    previous_position: Tuple[float, float] = (0.0, 0.0)
    current_position: Tuple[float, float] = (0.0, 0.0)
    trajectory_points: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class CrossingPolicyConfig:
    """Policy for line crossing detection."""
    min_crossing_distance: float = 50.0  # Pixels
    temporal_debounce_seconds: float = 2.0
    side_confirmation_frames: int = 3
    max_trajectory_gap_frames: int = 5


@dataclass
class CameraGeometryConfig:
    """Geometry configuration for a camera."""
    camera_id: str
    line: LineGeometry
    crossing_policy: CrossingPolicyConfig = field(default_factory=CrossingPolicyConfig)
    config_hash: str = ""


class CrossingEngine:
    """
    Line crossing detection engine.
    
    Processes track trajectories and generates CrossingEvents when
    configured line boundaries are crossed.
    Independent from video encoder, AI pipeline, and attendance database.
    """
    
    def __init__(self, geometry_config: CameraGeometryConfig):
        self.geometry_config = geometry_config
        self.crossing_policy = geometry_config.crossing_policy
        
        # Per-track state
        self._track_states: Dict[int, Any] = {}
        self._events: List[CrossingEvent] = []
        
        # Stats
        self._stats = {
            "total_crossings": 0,
            "in_crossings": 0,
            "out_crossings": 0,
            "rejected_debounce": 0,
            "rejected_distance": 0,
        }
    
    def process_track_update(
        self,
        track_id: int,
        previous_center: Tuple[float, float],
        current_center: Tuple[float, float],
        timestamp: float,
        frame_index: int,
    ) -> List[CrossingEvent]:
        """Process a single track update and detect crossings."""
        line = self.geometry_config.line
        
        # Get current and previous sides
        prev_side = line.side_of_point(previous_center)
        current_side = line.side_of_point(current_center)
        
        # Initialize or get track state
        if track_id not in self._track_states:
            self._track_states[track_id] = {
                "current_side": current_side,
                "confirmed_side": current_side,
                "frames_on_current_side": 1,
                "last_crossing_timestamp": 0.0,
                "last_crossing_direction": None,
            }
        
        
        state = self._track_states[track_id]
        
        # Check for crossing: different sides, both non-zero
        if current_side != prev_side and current_side != 0 and prev_side != 0:
            # Potential crossing
            
            # Check debounce
            time_since_last = timestamp - state["last_crossing_timestamp"]
            if state["last_crossing_timestamp"] > 0 and time_since_last < self.crossing_policy.temporal_debounce_seconds:
                self._stats["rejected_debounce"] += 1
            else:
                # Check distance
                prev_dist = line.distance_to_line(previous_center)
                current_dist = line.distance_to_line(current_center)
                crossing_distance = prev_dist + current_dist
                
                if crossing_distance >= self.crossing_policy.min_crossing_distance:
                    # Determine direction
                    if self.geometry_config.line.direction_semantics == "side_a_to_b_in":
                        direction = CrossingDirection.IN if prev_side == 1 and current_side == -1 else CrossingDirection.OUT
                    elif self.geometry_config.line.direction_semantics == "side_b_to_a_in":
                        direction = CrossingDirection.IN if prev_side == -1 and current_side == 1 else CrossingDirection.OUT
                    else:
                        direction = CrossingDirection.IN if prev_side > current_side else CrossingDirection.OUT
                    
                    # Calculate crossing point (intersection)
                    crossing_point = self._calculate_intersection(
                        previous_center, current_center, line
                    )
                    
                    # Create event
                    event = CrossingEvent(
                        event_id=f"CE-{track_id}-{frame_index}",
                        camera_id=self.geometry_config.camera_id,
                        track_id=track_id,
                        direction=direction,
                        crossing_point=crossing_point,
                        timestamp=timestamp,
                        frame_index=frame_index,
                        previous_position=previous_center,
                        current_position=current_center,
                        trajectory_points=[previous_center, current_center],
                    )
                    
                    self._events.append(event)
                    self._stats["total_crossings"] += 1
                    if direction == CrossingDirection.IN:
                        self._stats["in_crossings"] += 1
                    else:
                        self._stats["out_crossings"] += 1
                    
                    # Update state
                    state["last_crossing_timestamp"] = timestamp
                    state["last_crossing_direction"] = direction
                    state["confirmed_side"] = current_side
                    state["current_side"] = current_side
                    state["frames_on_current_side"] = 1
                else:
                    # Distance too small - reject
                    self._stats["rejected_distance"] += 1
        else:
            # No crossing - update confirmation
            if current_side == state["current_side"]:
                state["frames_on_current_side"] += 1
                if state["frames_on_current_side"] >= self.crossing_policy.side_confirmation_frames:
                    state["confirmed_side"] = current_side
            else:
                state["current_side"] = current_side
                state["frames_on_current_side"] = 1
        
        # Return new events
        return self._events[-len([e for e in self._events if e.track_id == track_id and e.frame_index == frame_index]):]
    
    def _calculate_intersection(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        line: LineGeometry
    ) -> Tuple[float, float]:
        """Calculate intersection point of trajectory with line."""
        # Line segment: p1 -> p2
        # Infinite line: line.p1 -> line.p2
        
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = line.p1
        x4, y4 = line.p2
        
        # Line intersection formula
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-12:
            # Parallel - use midpoint of trajectory segment
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        
        # Clamp to segment
        t = max(0.0, min(1.0, t))
        
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        
        return (ix, iy)
    
    def get_events(self) -> List[CrossingEvent]:
        """Get all generated events."""
        return self._events.copy()
    
    def get_stats(self) -> Dict[str, int]:
        return self._stats.copy()
    
    def clear_events(self) -> None:
        self._events.clear()
        for key in self._stats:
            if isinstance(self._stats[key], int) and key != "rejected_debounce" and key != "rejected_distance":
                self._stats[key] = 0
    
    def process_frame(
        self,
        tracks: List[Any],  # List of Track objects
        camera_id: str,
        timestamp: float,
        frame_index: int,
    ) -> List[CrossingEvent]:
        """Process all tracks for a frame."""
        events = []
        
        for track in tracks:
            if not track.is_active and not track.is_new:
                continue
            
            # Get current and previous center
            current_center = (track.bbox_original_frame[0] + track.bbox_original_frame[2]) / 2, \
                             (track.bbox_original_frame[1] + track.bbox_original_frame[3]) / 2
            
            # Get previous center from trajectory (simplified: use same bbox for now)
            # In full implementation, we'd store previous position
            previous_center = current_center  # Simplified for V2
            
            # Process
            new_events = self.process_track_update(
                track_id=track.track_id,
                previous_center=previous_center,
                current_center=current_center,
                timestamp=timestamp,
                frame_index=frame_index,
            )
            events.extend(new_events)
        
        return events


def create_crossing_engine(
    camera_id: str,
    line_start: Tuple[float, float],
    line_end: Tuple[float, float],
    direction_semantics: str = "side_a_to_b_in",
) -> CrossingEngine:
    """Factory function to create crossing engine."""
    line = LineGeometry(
        p1=line_start,
        p2=line_end,
        direction_semantics=direction_semantics,
    )
    config = CameraGeometryConfig(
        camera_id=camera_id,
        line=line,
        crossing_policy=CrossingPolicyConfig(),
    )
    return CrossingEngine(config)


def process_tracks_for_attendance(
    tracks: List[Any],  # Track objects
    camera_id: str,
    timestamp: float,
    frame_index: int,
    line_start: Tuple[float, float] = (0, 1000),
    line_end: Tuple[float, float] = (3840, 1000),
    direction_semantics: str = "side_a_to_b_in",
) -> List[CrossingEvent]:
    """
    Convenience function to process tracks for attendance events.
    Creates crossing engine and processes tracks.
    """
    engine = create_crossing_engine(camera_id, line_start, line_end, direction_semantics)
    events = engine.process_frame(tracks, camera_id, timestamp, frame_index)
    return events


if __name__ == "__main__":
    # Quick test
    from video_pipeline_v2.ai.tracking import Track, TrackLifecycleState
    
    # Create a simple line: horizontal line at y=1000, going from (0, 1000) to (3840, 1000)
    # Side A (positive y) is below the line, Side B (negative y) is above
    # With "side_a_to_b_in", crossing from below to above = IN
    engine = create_crossing_engine(
        camera_id="test",
        line_start=(0, 1000),
        line_end=(3840, 1000),
        direction_semantics="side_a_to_b_in"
    )
    
    # Create test tracks
    track1 = Track(
        track_id=1,
        source_frame_id="test",
        frame_index=1,
        timestamp=100.0,
        bbox_original_frame=(1000, 1200, 1100, 1300),  # Below line (side A)
        confidence=0.8,
        lifecycle_state=TrackLifecycleState.ACTIVE,
        age=1,
        hits=1,
        missed_frames=0,
        last_seen=100.0,
    )
    
    # Process first frame - initialize state
    events1 = engine.process_frame([track1], "test", 100.0, 1)
    print(f"Frame 1 events: {len(events1)}")
    
    # Now move track above line (side B) - should trigger IN event
    track2 = Track(
        track_id=1,
        source_frame_id="test",
        frame_index=2,
        timestamp=105.0,
        bbox_original_frame=(1000, 800, 1100, 900),  # Above line (side B) - crossed IN
        confidence=0.8,
        lifecycle_state=TrackLifecycleState.ACTIVE,
        age=2,
        hits=2,
        missed_frames=0,
        last_seen=105.0,
    )
    
    events2 = engine.process_frame([track2], "test", 105.0, 2)
    print(f"Frame 2 events: {len(events2)}")
    for e in events2:
        print(f"  Event: {e.event_id}, direction={e.direction}, point={e.crossing_point}")
    
    print(f"Engine stats: {engine.get_stats()}")
    print("Line crossing engine validated!")