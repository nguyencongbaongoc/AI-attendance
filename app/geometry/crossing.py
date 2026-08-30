"""
Phase 22 — Crossing Detection Engine.

Detects IN/OUT crossing events from track trajectories against configured geometry.
Operates in ORIGINAL_FRAME coordinate space with configurable hysteresis/debounce.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.geometry.contract import (
    CameraGeometryConfig,
    CrossingPolicyConfig,
    DirectionSemantics,
    GeometryConfigSnapshot,
    GeometryType,
    LineGeometry,
    Point2D,
    ZoneGeometry,
)
from app.replay.fusion import GlobalObservation, LocalObservationRef
from app.vision.track_contract import Track


class CrossingDirection(str, Enum):
    """Crossing event direction."""
    IN = "in"
    OUT = "out"


class CrossingEventType(str, Enum):
    """Type of crossing event."""
    LINE_CROSSING = "line_crossing"
    ZONE_ENTRY = "zone_entry"
    ZONE_EXIT = "zone_exit"


@dataclass(frozen=True)
class TrajectoryPoint:
    """
    Single trajectory point from a track.
    
    Represents a person's position at a specific time.
    """
    track_id: str
    frame_index: int
    timestamp: float
    position: Point2D  # Center of person bbox in ORIGINAL_FRAME
    bbox: Tuple[float, float, float, float]  # Full bbox for reference
    camera_id: str
    global_observation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "position": self.position.to_dict(),
            "bbox": list(self.bbox),
            "camera_id": self.camera_id,
            "global_observation_id": self.global_observation_id,
        }


@dataclass(frozen=True)
class CrossingEvent:
    """
    Canonical crossing event.
    
    Generated when a trajectory crosses a configured boundary.
    Preserves full provenance for forensic reproducibility.
    """
    # Event identification
    event_id: str
    
    # Camera and geometry
    camera_id: str
    geometry_config: GeometryConfigSnapshot
    
    # Track reference
    local_track_id: str
    global_observation_id: Optional[str] = None
    
    # Crossing details
    event_type: CrossingEventType = CrossingEventType.LINE_CROSSING
    direction: CrossingDirection = CrossingDirection.IN
    crossing_point: Point2D = field(default_factory=lambda: Point2D(0, 0))
    crossing_timestamp: float = 0.0
    
    # Trajectory evidence
    previous_position: Optional[Point2D] = None
    current_position: Optional[Point2D] = None
    previous_frame_index: int = -1
    current_frame_index: int = -1
    previous_timestamp: float = 0.0
    current_timestamp: float = 0.0
    
    # Crossing metrics
    crossing_distance: float = 0.0  # Distance crossed beyond boundary
    side_transition: str = ""  # e.g., "SIDE_A->SIDE_B"
    
    # Provenance
    trajectory_points: List[TrajectoryPoint] = field(default_factory=list)
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    version: str = "1.0"
    
    def __post_init__(self):
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
    
    @property
    def is_in(self) -> bool:
        return self.direction == CrossingDirection.IN
    
    @property
    def is_out(self) -> bool:
        return self.direction == CrossingDirection.OUT
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "geometry_config": self.geometry_config.to_dict(),
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "event_type": self.event_type.value,
            "direction": self.direction.value,
            "crossing_point": self.crossing_point.to_dict(),
            "crossing_timestamp": self.crossing_timestamp,
            "previous_position": self.previous_position.to_dict() if self.previous_position else None,
            "current_position": self.current_position.to_dict() if self.current_position else None,
            "previous_frame_index": self.previous_frame_index,
            "current_frame_index": self.current_frame_index,
            "previous_timestamp": self.previous_timestamp,
            "current_timestamp": self.current_timestamp,
            "crossing_distance": self.crossing_distance,
            "side_transition": self.side_transition,
            "trajectory_points": [p.to_dict() for p in self.trajectory_points],
            "config_snapshot": self.config_snapshot,
            "created_at": self.created_at,
            "version": self.version,
        }


@dataclass
class TrackCrossingState:
    """
    Per-track crossing state for hysteresis/debounce.
    
    Maintains state to prevent event spam from jitter.
    """
    track_id: str
    camera_id: str
    
    # Current side of geometry
    current_side: int = 0  # 0=on_line, 1=side_a, -1=side_b, 2=inside_zone, -2=outside_zone
    confirmed_side: int = 0  # Side confirmed after confirmation_frames
    
    # Confirmation counter
    frames_on_current_side: int = 0
    
    # Last crossing event
    last_crossing_timestamp: float = 0.0
    last_crossing_direction: Optional[CrossingDirection] = None
    last_crossing_event_id: Optional[str] = None
    
    # Trajectory history (bounded)
    recent_positions: List[TrajectoryPoint] = field(default_factory=list)
    max_history: int = 10
    
    # For zone: track if we were inside
    was_inside_zone: bool = False
    
    def add_position(self, point: TrajectoryPoint) -> None:
        """Add a new trajectory point, maintaining bounded history."""
        self.recent_positions.append(point)
        if len(self.recent_positions) > self.max_history:
            self.recent_positions.pop(0)
    
    def get_previous_position(self) -> Optional[TrajectoryPoint]:
        """Get the previous trajectory point."""
        if len(self.recent_positions) >= 2:
            return self.recent_positions[-2]
        return None
    
    def time_since_last_crossing(self, current_timestamp: float) -> float:
        """Time elapsed since last crossing event."""
        if self.last_crossing_timestamp <= 0:
            return float('inf')
        return current_timestamp - self.last_crossing_timestamp
    
    def can_cross(
        self,
        current_timestamp: float,
        debounce_seconds: float,
        min_distance: float,
    ) -> bool:
        """Check if enough time/distance has passed for a new crossing."""
        # Temporal debounce - allow first crossing (last_crossing_timestamp <= 0)
        if self.last_crossing_timestamp > 0:
            if self.time_since_last_crossing(current_timestamp) < debounce_seconds:
                return False
        
        # Distance check would need geometry context
        return True
    
    def record_crossing(
        self,
        event: CrossingEvent,
        new_side: int,
    ) -> None:
        """Record a crossing event and update state."""
        self.last_crossing_timestamp = event.crossing_timestamp
        self.last_crossing_direction = event.direction
        self.last_crossing_event_id = event.event_id
        self.confirmed_side = new_side
        self.current_side = new_side
        # Reset confirmation counter - start fresh on new side
        # Set to 1 because we just entered this side with the crossing
        self.frames_on_current_side = 1


class CrossingEngine:
    """
    Crossing detection engine for a single camera.
    
    Processes track trajectories and generates CrossingEvents when
    configured boundaries are crossed with proper hysteresis/debounce.
    """
    
    def __init__(
        self,
        geometry_config: CameraGeometryConfig,
    ):
        """
        Initialize crossing engine for a camera.
        
        Args:
            geometry_config: Camera geometry configuration
        """
        self.geometry_config = geometry_config
        self.crossing_policy = geometry_config.crossing_policy
        
        # Per-track state
        self._track_states: Dict[str, TrackCrossingState] = {}
        
        # Generated events
        self._events: List[CrossingEvent] = []
        
        # Statistics
        self._stats = {
            "total_crossings": 0,
            "in_crossings": 0,
            "out_crossings": 0,
            "rejected_debounce": 0,
            "rejected_distance": 0,
            "rejected_confirmation": 0,
        }
    
    def process_track(
        self,
        track: Track,
        frame_index: int,
        timestamp: float,
        global_observation_id: Optional[str] = None,
    ) -> List[CrossingEvent]:
        """
        Process a track update and detect crossings.
        
        Args:
            track: Current track state
            frame_index: Current frame index
            timestamp: Current timestamp
            global_observation_id: Optional GlobalObservation reference
            
        Returns:
            List of new CrossingEvents generated
        """
        # Get track center position
        center = track.center
        position = Point2D(center[0], center[1])
        bbox = track.bbox_original_frame
        
        # Create trajectory point
        traj_point = TrajectoryPoint(
            track_id=track.track_id,
            frame_index=frame_index,
            timestamp=timestamp,
            position=position,
            bbox=bbox,
            camera_id=self.geometry_config.camera_id,
            global_observation_id=global_observation_id,
        )
        
        # Get or create track state
        state = self._get_or_create_state(track.track_id)
        state.add_position(traj_point)
        
        # Detect crossing based on geometry type
        new_events = []
        
        if self.geometry_config.geometry_type == GeometryType.LINE:
            new_events = self._process_line_crossing(state, traj_point)
        elif self.geometry_config.geometry_type == GeometryType.ZONE:
            new_events = self._process_zone_crossing(state, traj_point)
        
        # Record events
        for event in new_events:
            self._events.append(event)
            self._stats["total_crossings"] += 1
            if event.direction == CrossingDirection.IN:
                self._stats["in_crossings"] += 1
            else:
                self._stats["out_crossings"] += 1
            
            # Update track state
            new_side = self._get_side_for_position(event.current_position)
            state.record_crossing(event, new_side)
        
        return new_events
    
    def _get_or_create_state(self, track_id: str) -> TrackCrossingState:
        """Get or create crossing state for a track."""
        if track_id not in self._track_states:
            self._track_states[track_id] = TrackCrossingState(
                track_id=track_id,
                camera_id=self.geometry_config.camera_id,
                max_history=self.crossing_policy.max_trajectory_gap_frames + 5,
            )
        return self._track_states[track_id]
    
    def _get_side_for_position(self, position: Optional[Point2D]) -> int:
        """Get side of geometry for a position."""
        if position is None:
            return 0
        
        if self.geometry_config.geometry_type == GeometryType.LINE:
            if self.geometry_config.line:
                return self.geometry_config.line.side_of_point(position)
            return 0
        elif self.geometry_config.geometry_type == GeometryType.ZONE:
            if self.geometry_config.zone:
                inside = self.geometry_config.zone.point_in_polygon(position)
                return 2 if inside else -2
            return 0
        return 0
    
    def _process_line_crossing(
        self,
        state: TrackCrossingState,
        current_point: TrajectoryPoint,
    ) -> List[CrossingEvent]:
        """Process line crossing detection with hysteresis."""
        line = self.geometry_config.line
        if not line:
            return []
        
        current_pos = current_point.position
        current_side = line.side_of_point(current_pos)
        
        # Get previous position
        prev_point = state.get_previous_position()
        if prev_point is None:
            # First point - initialize side
            state.current_side = current_side
            state.confirmed_side = current_side
            state.frames_on_current_side = 1
            return []
        
        prev_pos = prev_point.position
        prev_side = line.side_of_point(prev_pos)
        
        # Check for side transition using immediate previous position
        if current_side != prev_side and current_side != 0 and prev_side != 0:
            # Potential crossing detected - evaluate but don't generate event yet
            # We need confirmation frames on the NEW side
            events = self._evaluate_line_crossing(
                state, prev_point, current_point, prev_side, current_side
            )
            # If crossing is valid, we'll start counting frames on new side
            # If rejected, we do NOT update state to current side - keep previous side
            # so that subsequent frames can still detect the transition
            if not events:
                # Crossing rejected (e.g., by debounce) - keep previous side
                # to allow re-detection when debounce expires
                # But we still need to track that we're now on the new side
                # for confirmation purposes
                pass
            else:
                # Valid crossing detected - start counting frames on new side
                # The crossing frame counts as frame 1
                state.current_side = current_side
                state.frames_on_current_side = 1
                # Store pending crossing for confirmation
                state._pending_crossing = events[0]
                state._pending_prev_side = prev_side
                state._pending_current_side = current_side
                
                # If confirmation_frames == 1, generate immediately
                if self.crossing_policy.side_confirmation_frames <= 1:
                    pending_event = state._pending_crossing
                    state._pending_crossing = None
                    state._pending_prev_side = None
                    state._pending_current_side = None
                    state.confirmed_side = current_side
                    return [pending_event]
            return []
        
        # Check for transition from confirmed side to current side
        # This handles the case where trajectory history was polluted by rejected crossings
        if (state.confirmed_side != 0 and 
            current_side != state.confirmed_side and 
            current_side != 0 and 
            state.confirmed_side != 0):
            # Find the last confirmed position
            last_confirmed = self._find_last_confirmed_position(state, line)
            if last_confirmed is not None:
                # Evaluate crossing from last confirmed position to current
                events = self._evaluate_line_crossing(
                    state, last_confirmed, current_point, state.confirmed_side, current_side
                )
                if events:
                    # Valid crossing detected
                    state.current_side = current_side
                    state.frames_on_current_side = 1
                    state._pending_crossing = events[0]
                    state._pending_prev_side = state.confirmed_side
                    state._pending_current_side = current_side
                    
                    if self.crossing_policy.side_confirmation_frames <= 1:
                        pending_event = state._pending_crossing
                        state._pending_crossing = None
                        state._pending_prev_side = None
                        state._pending_current_side = None
                        state.confirmed_side = current_side
                        return [pending_event]
                    return []
        
        # Update confirmation counter
        if current_side == state.current_side:
            state.frames_on_current_side += 1
            # Confirm side after enough frames
            if state.frames_on_current_side >= self.crossing_policy.side_confirmation_frames:
                state.confirmed_side = current_side
                # If we had a pending crossing, generate it now
                if hasattr(state, '_pending_crossing') and state._pending_crossing is not None:
                    pending_event = state._pending_crossing
                    state._pending_crossing = None
                    state._pending_prev_side = None
                    state._pending_current_side = None
                    return [pending_event]
        else:
            # Side changed but not confirmed yet
            state.current_side = current_side
            state.frames_on_current_side = 1
            # Clear any pending crossing since side changed again
            if hasattr(state, '_pending_crossing'):
                state._pending_crossing = None
                state._pending_prev_side = None
                state._pending_current_side = None
        
        return []
    
    def _find_last_confirmed_position(
        self,
        state: TrackCrossingState,
        line: LineGeometry,
    ) -> Optional[TrajectoryPoint]:
        """Find the last trajectory point that was on the confirmed side."""
        if state.confirmed_side == 0:
            return None
        
        # Search backwards through history for a point on the confirmed side
        for point in reversed(state.recent_positions):
            side = line.side_of_point(point.position)
            if side == state.confirmed_side:
                return point
        
        return None
    
    def _evaluate_line_crossing(
        self,
        state: TrackCrossingState,
        prev_point: TrajectoryPoint,
        current_point: TrajectoryPoint,
        prev_side: int,
        current_side: int,
    ) -> List[CrossingEvent]:
        """Evaluate if a line crossing should generate an event."""
        line = self.geometry_config.line
        if not line:
            return []
        
        # Check minimum crossing distance
        prev_dist = line.distance_to_line(prev_point.position)
        current_dist = line.distance_to_line(current_point.position)
        crossing_distance = prev_dist + current_dist
        
        if crossing_distance < self.crossing_policy.min_crossing_distance:
            self._stats["rejected_distance"] += 1
            return []
        
        # Check temporal debounce
        if not state.can_cross(
            current_point.timestamp,
            self.crossing_policy.temporal_debounce_seconds,
            self.crossing_policy.min_crossing_distance,
        ):
            self._stats["rejected_debounce"] += 1
            return []
        
        # Check side confirmation
        if state.confirmed_side != 0 and state.confirmed_side != prev_side:
            # Previous side was confirmed, this is a valid transition
            pass
        elif state.frames_on_current_side < self.crossing_policy.side_confirmation_frames:
            # Not enough confirmation frames
            self._stats["rejected_confirmation"] += 1
            return []
        
        # Determine direction based on semantics
        direction = self._determine_line_direction(prev_side, current_side)
        
        # Calculate crossing point (intersection with line)
        crossing_point = self._calculate_line_intersection(
            prev_point.position, current_point.position, line
        )
        
        # Generate event ID
        event_id = self._generate_event_id(
            current_point.track_id, current_point.frame_index, "line"
        )
        
        # Create crossing event
        event = CrossingEvent(
            event_id=event_id,
            camera_id=self.geometry_config.camera_id,
            geometry_config=GeometryConfigSnapshot.from_config(self.geometry_config),
            local_track_id=current_point.track_id,
            global_observation_id=current_point.global_observation_id,
            event_type=CrossingEventType.LINE_CROSSING,
            direction=direction,
            crossing_point=crossing_point,
            crossing_timestamp=current_point.timestamp,
            previous_position=prev_point.position,
            current_position=current_point.position,
            previous_frame_index=prev_point.frame_index,
            current_frame_index=current_point.frame_index,
            previous_timestamp=prev_point.timestamp,
            current_timestamp=current_point.timestamp,
            crossing_distance=crossing_distance,
            side_transition=f"{self._side_name(prev_side)}->{self._side_name(current_side)}",
            trajectory_points=[prev_point, current_point],
            config_snapshot=self.geometry_config.crossing_policy.to_dict(),
        )
        
        return [event]
    
    def _determine_line_direction(
        self,
        prev_side: int,
        current_side: int,
    ) -> CrossingDirection:
        """Determine IN/OUT direction from side transition."""
        line = self.geometry_config.line
        if not line:
            return CrossingDirection.IN
        
        semantics = line.direction_semantics
        
        # SIDE_A = +1, SIDE_B = -1
        if semantics == DirectionSemantics.SIDE_A_TO_B_IN:
            # SIDE_A (+1) -> SIDE_B (-1) = IN
            if prev_side == 1 and current_side == -1:
                return CrossingDirection.IN
            # SIDE_B (-1) -> SIDE_A (+1) = OUT
            elif prev_side == -1 and current_side == 1:
                return CrossingDirection.OUT
        elif semantics == DirectionSemantics.SIDE_B_TO_A_IN:
            # SIDE_B (-1) -> SIDE_A (+1) = IN
            if prev_side == -1 and current_side == 1:
                return CrossingDirection.IN
            # SIDE_A (+1) -> SIDE_B (-1) = OUT
            elif prev_side == 1 and current_side == -1:
                return CrossingDirection.OUT
        
        # Default: treat as IN if moving from positive to negative side
        return CrossingDirection.IN if prev_side > current_side else CrossingDirection.OUT
    
    def _side_name(self, side: int) -> str:
        """Get human-readable side name."""
        if side == 1:
            return "SIDE_A"
        elif side == -1:
            return "SIDE_B"
        elif side == 0:
            return "ON_LINE"
        elif side == 2:
            return "INSIDE"
        elif side == -2:
            return "OUTSIDE"
        return f"UNKNOWN({side})"
    
    def _calculate_line_intersection(
        self,
        p1: Point2D,
        p2: Point2D,
        line: LineGeometry,
    ) -> Point2D:
        """Calculate intersection point of trajectory segment with line."""
        # Line segment: p1 -> p2
        # Infinite line: line.p1 -> line.p2
        
        x1, y1 = p1.x, p1.y
        x2, y2 = p2.x, p2.y
        x3, y3 = line.p1.x, line.p1.y
        x4, y4 = line.p2.x, line.p2.y
        
        # Line intersection formula
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-12:
            # Parallel or coincident - return midpoint
            return Point2D((x1 + x2) / 2, (y1 + y2) / 2)
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        
        # Clamp to segment
        t = max(0.0, min(1.0, t))
        
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        
        return Point2D(ix, iy)
    
    def _process_zone_crossing(
        self,
        state: TrackCrossingState,
        current_point: TrajectoryPoint,
    ) -> List[CrossingEvent]:
        """Process zone entry/exit detection."""
        zone = self.geometry_config.zone
        if not zone:
            return []
        
        current_pos = current_point.position
        currently_inside = zone.point_in_polygon(current_pos)
        
        # Get previous position
        prev_point = state.get_previous_position()
        if prev_point is None:
            # First point - initialize
            state.was_inside_zone = currently_inside
            state.current_side = 2 if currently_inside else -2
            state.confirmed_side = state.current_side
            state.frames_on_current_side = 1
            return []
        
        prev_pos = prev_point.position
        was_inside = zone.point_in_polygon(prev_pos)
        
        # Check for zone transition
        if currently_inside != was_inside:
            return self._evaluate_zone_crossing(
                state, prev_point, current_point, was_inside, currently_inside
            )
        
        # Update confirmation
        current_side = 2 if currently_inside else -2
        if current_side == state.current_side:
            state.frames_on_current_side += 1
            if state.frames_on_current_side >= self.crossing_policy.side_confirmation_frames:
                state.confirmed_side = current_side
        else:
            state.current_side = current_side
            state.frames_on_current_side = 1
        
        return []
    
    def _evaluate_zone_crossing(
        self,
        state: TrackCrossingState,
        prev_point: TrajectoryPoint,
        current_point: TrajectoryPoint,
        was_inside: bool,
        currently_inside: bool,
    ) -> List[CrossingEvent]:
        """Evaluate if a zone crossing should generate an event."""
        zone = self.geometry_config.zone
        if not zone:
            return []
        
        # Check minimum crossing distance (distance to boundary)
        prev_dist = zone.distance_to_boundary(prev_point.position)
        current_dist = zone.distance_to_boundary(current_point.position)
        crossing_distance = prev_dist + current_dist
        
        if crossing_distance < self.crossing_policy.min_crossing_distance:
            self._stats["rejected_distance"] += 1
            return []
        
        # Check temporal debounce
        if not state.can_cross(
            current_point.timestamp,
            self.crossing_policy.temporal_debounce_seconds,
            self.crossing_policy.min_crossing_distance,
        ):
            self._stats["rejected_debounce"] += 1
            return []
        
        # Check side confirmation
        if state.confirmed_side != 0:
            prev_confirmed_inside = state.confirmed_side == 2
            if prev_confirmed_inside != was_inside:
                # State doesn't match - need confirmation
                if state.frames_on_current_side < self.crossing_policy.side_confirmation_frames:
                    self._stats["rejected_confirmation"] += 1
                    return []
        
        # Determine event type and direction
        if not was_inside and currently_inside:
            # Entry
            event_type = CrossingEventType.ZONE_ENTRY
            direction = self._determine_zone_direction(True)
            side_transition = "OUTSIDE->INSIDE"
        else:
            # Exit
            event_type = CrossingEventType.ZONE_EXIT
            direction = self._determine_zone_direction(False)
            side_transition = "INSIDE->OUTSIDE"
        
        # Calculate crossing point (intersection with zone boundary)
        crossing_point = self._calculate_zone_intersection(
            prev_point.position, current_point.position, zone
        )
        
        # Generate event ID
        event_id = self._generate_event_id(
            current_point.track_id, current_point.frame_index, "zone"
        )
        
        # Create crossing event
        event = CrossingEvent(
            event_id=event_id,
            camera_id=self.geometry_config.camera_id,
            geometry_config=GeometryConfigSnapshot.from_config(self.geometry_config),
            local_track_id=current_point.track_id,
            global_observation_id=current_point.global_observation_id,
            event_type=event_type,
            direction=direction,
            crossing_point=crossing_point,
            crossing_timestamp=current_point.timestamp,
            previous_position=prev_point.position,
            current_position=current_point.position,
            previous_frame_index=prev_point.frame_index,
            current_frame_index=current_point.frame_index,
            previous_timestamp=prev_point.timestamp,
            current_timestamp=current_point.timestamp,
            crossing_distance=crossing_distance,
            side_transition=side_transition,
            trajectory_points=[prev_point, current_point],
            config_snapshot=self.geometry_config.crossing_policy.to_dict(),
        )
        
        return [event]
    
    def _determine_zone_direction(self, is_entry: bool) -> CrossingDirection:
        """Determine IN/OUT direction for zone transition."""
        semantics = self.geometry_config.zone.direction_semantics if self.geometry_config.zone else DirectionSemantics.OUTSIDE_TO_INSIDE_IN
        
        if semantics == DirectionSemantics.OUTSIDE_TO_INSIDE_IN:
            return CrossingDirection.IN if is_entry else CrossingDirection.OUT
        elif semantics == DirectionSemantics.INSIDE_TO_OUTSIDE_IN:
            return CrossingDirection.IN if not is_entry else CrossingDirection.OUT
        
        return CrossingDirection.IN if is_entry else CrossingDirection.OUT
    
    def _calculate_zone_intersection(
        self,
        p1: Point2D,
        p2: Point2D,
        zone: ZoneGeometry,
    ) -> Point2D:
        """Calculate intersection of trajectory segment with zone boundary."""
        # Find intersection with any polygon edge
        n = len(zone.vertices)
        best_intersection = None
        best_t = float('inf')
        
        for i in range(n):
            v1 = zone.vertices[i]
            v2 = zone.vertices[(i + 1) % n]
            
            # Segment intersection: p1-p2 with v1-v2
            intersection = self._segment_intersection(p1, p2, v1, v2)
            if intersection:
                # Calculate t parameter along p1-p2
                dx = p2.x - p1.x
                dy = p2.y - p1.y
                if abs(dx) > abs(dy):
                    t = (intersection.x - p1.x) / dx if dx != 0 else 0
                else:
                    t = (intersection.y - p1.y) / dy if dy != 0 else 0
                
                if 0 <= t <= 1 and t < best_t:
                    best_t = t
                    best_intersection = intersection
        
        if best_intersection:
            return best_intersection
        
        # Fallback: midpoint
        return Point2D((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)
    
    def _segment_intersection(
        self,
        p1: Point2D,
        p2: Point2D,
        q1: Point2D,
        q2: Point2D,
    ) -> Optional[Point2D]:
        """Calculate intersection of two line segments."""
        x1, y1 = p1.x, p1.y
        x2, y2 = p2.x, p2.y
        x3, y3 = q1.x, q1.y
        x4, y4 = q2.x, q2.y
        
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-12:
            return None
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        
        if 0 <= t <= 1 and 0 <= u <= 1:
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            return Point2D(ix, iy)
        
        return None
    
    def _generate_event_id(
        self,
        track_id: str,
        frame_index: int,
        prefix: str,
    ) -> str:
        """Generate deterministic event ID."""
        content = f"{self.geometry_config.camera_id}:{track_id}:{frame_index}:{prefix}:{self.geometry_config.config_hash}"
        hash_suffix = hashlib.md5(content.encode()).hexdigest()[:10]
        return f"CE-{prefix[:2].upper()}-{hash_suffix}"
    
    def get_events(self) -> List[CrossingEvent]:
        """Get all generated crossing events."""
        return list(self._events)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return dict(self._stats)
    
    def clear_track(self, track_id: str) -> None:
        """Clear state for a track (e.g., when track is closed)."""
        if track_id in self._track_states:
            del self._track_states[track_id]
    
    def clear_all(self) -> None:
        """Clear all track states and events."""
        self._track_states.clear()
        self._events.clear()
        for key in self._stats:
            self._stats[key] = 0


def create_crossing_engine(
    geometry_config: CameraGeometryConfig,
) -> CrossingEngine:
    """Factory function to create a CrossingEngine."""
    return CrossingEngine(geometry_config)

def process_tracks_for_crossings(
    tracks: List[Track],
    geometry_config: CameraGeometryConfig,
    frame_index: int,
    timestamp: float,
    global_observation_map: Optional[Dict[str, str]] = None,
) -> List[CrossingEvent]:
    """
    Convenience function to process multiple tracks for crossings.
    
    Args:
        tracks: List of tracks to process
        geometry_config: Camera geometry configuration
        frame_index: Current frame index
        timestamp: Current timestamp
        global_observation_map: Optional map of track_id -> global_observation_id
        
    Returns:
        List of crossing events
    """
    engine = create_crossing_engine(geometry_config)
    all_events = []
    
    for track in tracks:
        global_obs_id = None
        if global_observation_map:
            global_obs_id = global_observation_map.get(track.track_id)
        
        events = engine.process_track(track, frame_index, timestamp, global_obs_id)
        all_events.extend(events)
    
    return all_events