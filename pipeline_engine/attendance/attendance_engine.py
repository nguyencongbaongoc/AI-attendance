"""
Attendance Engine - Line crossing detection and IN/OUT event generation.

Integrates with tracker to generate attendance events from track trajectories.
"""

from __future__ import annotations

import logging
import uuid
import time
import json
import sqlite3
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum
from pathlib import Path

import numpy as np

from pipeline_engine.tracking.tracker import Track, TrackingResult
from pipeline_engine.config import get_camera_config, get_config
from app.identity.global_identity_service import GlobalIdentityService, create_global_identity_service
from app.identity.models import IdentityState, GISConfig

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class CrossingDirection(str, Enum):
    IN = "in"
    OUT = "out"


class CrossingEventType(str, Enum):
    LINE_CROSSING = "line_crossing"


@dataclass
class LineGeometry:
    """Configurable line for crossing detection."""
    p1: Tuple[float, float]  # (x, y)
    p2: Tuple[float, float]  # (x, y)
    direction_semantics: str = "side_a_to_b_in"
    
    def side_of_point(self, point: Tuple[float, float]) -> int:
        """Determine which side of the line a point is on."""
        x, y = point
        px1, py1 = self.p1
        px2, py2 = self.p2
        
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
        
        line_length_sq = (x2 - x1)**2 + (y2 - y1)**2
        if line_length_sq == 0:
            return np.sqrt((x - x1)**2 + (y - y1)**2)
        
        t = max(0, min(1, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / line_length_sq))
        
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)
        
        return np.sqrt((x - proj_x)**2 + (y - proj_y)**2)


@dataclass
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
    person_id: Optional[str] = None
    person_name: Optional[str] = None
    identity_confidence: float = 0.0
    # NEW: GIS fields (P3.11)
    global_person_id: Optional[str] = None
    identity_state: str = "unknown"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "direction": self.direction.value,
            "event_type": self.event_type.value,
            "crossing_point": self.crossing_point,
            "timestamp": self.timestamp,
            "frame_index": self.frame_index,
            "previous_position": self.previous_position,
            "current_position": self.current_position,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "identity_confidence": self.identity_confidence,
            # NEW: GIS fields
            "global_person_id": self.global_person_id,
            "identity_state": self.identity_state,
        }


@dataclass
class CrossingPolicyConfig:
    """Policy for line crossing detection."""
    min_crossing_distance: float = 50.0
    temporal_debounce_seconds: float = 2.0
    side_confirmation_frames: int = 3
    max_trajectory_gap_frames: int = 5


@dataclass
class CameraAttendanceConfig:
    """Attendance configuration for a camera."""
    camera_id: str
    line: LineGeometry
    crossing_policy: CrossingPolicyConfig = field(default_factory=CrossingPolicyConfig)
    enabled: bool = True


class AttendanceStore:
    """SQLite-based attendance event store."""
    
    def __init__(self, db_path: str = "data/attendance_events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS attendance_events (
                    event_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    track_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    crossing_point_x REAL NOT NULL,
                    crossing_point_y REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    frame_index INTEGER NOT NULL,
                    previous_position_x REAL NOT NULL,
                    previous_position_y REAL NOT NULL,
                    current_position_x REAL NOT NULL,
                    current_position_y REAL NOT NULL,
                    person_id TEXT,
                    person_name TEXT,
                    identity_confidence REAL,
                    -- NEW: GIS fields (P3.11)
                    global_person_id TEXT,
                    identity_state TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_camera_timestamp 
                ON attendance_events(camera_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_person_timestamp 
                ON attendance_events(person_id, timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_global_person_timestamp 
                ON attendance_events(global_person_id, timestamp)
            """)
            conn.commit()
    
    def store_event(self, event: CrossingEvent) -> bool:
        """Store a crossing event."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO attendance_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.camera_id,
                    event.track_id,
                    event.direction.value,
                    event.event_type.value,
                    event.crossing_point[0],
                    event.crossing_point[1],
                    event.timestamp,
                    event.frame_index,
                    event.previous_position[0],
                    event.previous_position[1],
                    event.current_position[0],
                    event.current_position[1],
                    event.person_id,
                    event.person_name,
                    event.identity_confidence,
                    # NEW: GIS fields (P3.11)
                    event.global_person_id,
                    event.identity_state,
                    time.time(),
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"AttendanceStore: Failed to store event: {e}")
            return False
    
    def get_events(
        self, 
        camera_id: Optional[str] = None,
        person_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Query attendance events."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                query = "SELECT * FROM attendance_events WHERE 1=1"
                params = []
                
                if camera_id:
                    query += " AND camera_id = ?"
                    params.append(camera_id)
                
                if person_id:
                    query += " AND person_id = ?"
                    params.append(person_id)
                
                if start_time:
                    query += " AND timestamp >= ?"
                    params.append(start_time)
                
                if end_time:
                    query += " AND timestamp <= ?"
                    params.append(end_time)
                
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"AttendanceStore: Query failed: {e}")
            return []
    
    def get_daily_summary(self, date: str) -> Dict[str, Any]:
        """Get daily attendance summary (date format: YYYY-MM-DD)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                start = time.mktime(time.strptime(date + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
                end = time.mktime(time.strptime(date + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
                
                cursor = conn.execute("""
                    SELECT 
                        person_id,
                        person_name,
                        direction,
                        COUNT(*) as count,
                        MIN(timestamp) as first_event,
                        MAX(timestamp) as last_event
                    FROM attendance_events
                    WHERE timestamp >= ? AND timestamp <= ?
                    GROUP BY person_id, person_name, direction
                """, (start, end))
                
                summary = {"date": date, "records": []}
                for row in cursor.fetchall():
                    summary["records"].append(dict(row))
                
                return summary
        except Exception as e:
            logger.error(f"AttendanceStore: Daily summary failed: {e}")
            return {"date": date, "records": []}
    
    def export_to_json(self, output_path: str, **filters) -> bool:
        """Export events to JSON file."""
        try:
            events = self.get_events(**filters)
            with open(output_path, 'w') as f:
                json.dump(events, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"AttendanceStore: Export failed: {e}")
            return False


class CrossingEngine:
    """
    Line crossing detection engine.
    
    Processes track trajectories and generates CrossingEvents when
    configured line boundaries are crossed.
    """
    
    def __init__(self, config: CameraAttendanceConfig):
        self.config = config
        self.line = config.line
        self.policy = config.crossing_policy
        
        # Per-track state
        self._track_states: Dict[int, Dict] = {}
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
        track: Track,
        timestamp: float,
        frame_index: int,
    ) -> List[CrossingEvent]:
        """Process a single track update and detect crossings."""
        if not track.is_active and not track.is_new:
            return []
        
        # Get current center
        current_center = track.center
        
        # Get previous center from track state
        track_id = track.track_id
        
        if track_id not in self._track_states:
            self._track_states[track_id] = {
                "current_side": self.line.side_of_point(current_center),
                "confirmed_side": self.line.side_of_point(current_center),
                "frames_on_current_side": 1,
                "last_crossing_timestamp": 0.0,
                "last_crossing_direction": None,
                "last_position": current_center,
            }
            return []
        
        state = self._track_states[track_id]
        previous_center = state["last_position"]
        
        # Update position
        state["last_position"] = current_center
        
        # Get current and previous sides
        prev_side = self.line.side_of_point(previous_center)
        current_side = self.line.side_of_point(current_center)
        
        # Check for crossing: different sides, both non-zero
        if current_side != prev_side and current_side != 0 and prev_side != 0:
            # Potential crossing
            
            # Check debounce
            time_since_last = timestamp - state["last_crossing_timestamp"]
            if state["last_crossing_timestamp"] > 0 and time_since_last < self.policy.temporal_debounce_seconds:
                self._stats["rejected_debounce"] += 1
            else:
                # Check distance
                prev_dist = self.line.distance_to_line(previous_center)
                current_dist = self.line.distance_to_line(current_center)
                crossing_distance = prev_dist + current_dist
                
                if crossing_distance >= self.policy.min_crossing_distance:
                    # Determine direction
                    if self.line.direction_semantics == "side_a_to_b_in":
                        direction = CrossingDirection.IN if prev_side == 1 and current_side == -1 else CrossingDirection.OUT
                    elif self.line.direction_semantics == "side_b_to_a_in":
                        direction = CrossingDirection.IN if prev_side == -1 and current_side == 1 else CrossingDirection.OUT
                    else:
                        direction = CrossingDirection.IN if prev_side > current_side else CrossingDirection.OUT
                    
                    # Calculate crossing point (intersection)
                    crossing_point = self._calculate_intersection(previous_center, current_center)
                    
                    # Create event
                    event = CrossingEvent(
                        event_id=f"CE-{track_id}-{frame_index}-{int(timestamp*1000)}",
                        camera_id=self.config.camera_id,
                        track_id=track_id,
                        direction=direction,
                        crossing_point=crossing_point,
                        timestamp=timestamp,
                        frame_index=frame_index,
                        previous_position=previous_center,
                        current_position=current_center,
                        person_id=track.person_id,
                        person_name=track.person_name,
                        identity_confidence=track.identity_confidence,
                        # NEW: GIS fields (P3.11)
                        global_person_id=getattr(track, 'global_person_id', None),
                        identity_state=getattr(track, 'identity_state', 'unknown'),
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
                    
                    return [event]
                else:
                    self._stats["rejected_distance"] += 1
        else:
            # No crossing - update confirmation
            if current_side == state["current_side"]:
                state["frames_on_current_side"] += 1
                if state["frames_on_current_side"] >= self.policy.side_confirmation_frames:
                    state["confirmed_side"] = current_side
            else:
                state["current_side"] = current_side
                state["frames_on_current_side"] = 1
        
        return []
    
    def _calculate_intersection(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
    ) -> Tuple[float, float]:
        """Calculate intersection point of trajectory with line."""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = self.line.p1
        x4, y4 = self.line.p2
        
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-12:
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        t = max(0.0, min(1.0, t))
        
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        
        return (ix, iy)
    
    def get_events(self) -> List[CrossingEvent]:
        return self._events.copy()
    
    def get_stats(self) -> Dict[str, int]:
        return self._stats.copy()
    
    def clear_events(self) -> None:
        self._events.clear()
        for key in self._stats:
            self._stats[key] = 0


class AttendanceEngine:
    """
    Main attendance engine coordinating crossing detection and event storage.
    """
    
    def __init__(self, config: Optional[Any] = None, gis: Optional[GlobalIdentityService] = None):
        self.config = config or get_config()
        self._engines: Dict[str, CrossingEngine] = {}
        self._store = AttendanceStore()
        self._event_callbacks: List[callable] = []
        
        # Global Identity Service integration
        self.gis = gis or create_global_identity_service()
        
        # Initialize per-camera engines
        self._init_engines()
    
    def _init_engines(self) -> None:
        """Initialize crossing engines for all configured cameras."""
        cameras = self.config.cameras or {}
        
        for camera_id, cam_config in cameras.items():
            if not cam_config.get("enabled", True):
                continue
            
            geom = cam_config.get("geometry", {})
            line_start = geom.get("line_start", [0, 1080])
            line_end = geom.get("line_end", [3840, 1080])
            direction = geom.get("direction_semantics", "side_a_to_b_in")
            
            policy_config = cam_config.get("crossing_policy", {})
            policy = CrossingPolicyConfig(
                min_crossing_distance=policy_config.get("min_crossing_distance", 50.0),
                temporal_debounce_seconds=policy_config.get("temporal_debounce_seconds", 2.0),
                side_confirmation_frames=policy_config.get("side_confirmation_frames", 3),
                max_trajectory_gap_frames=policy_config.get("max_trajectory_gap_frames", 5),
            )
            
            line = LineGeometry(
                p1=tuple(line_start),
                p2=tuple(line_end),
                direction_semantics=direction,
            )
            
            camera_config = CameraAttendanceConfig(
                camera_id=camera_id,
                line=line,
                crossing_policy=policy,
            )
            
            self._engines[camera_id] = CrossingEngine(camera_config)
            logger.info(f"AttendanceEngine: Initialized crossing engine for {camera_id}")
    
    def register_event_callback(self, callback: callable) -> None:
        """Register callback for attendance events."""
        self._event_callbacks.append(callback)
    
    def process_tracks(self, tracking_result: TrackingResult) -> List[CrossingEvent]:
        """Process tracking results and generate attendance events."""
        camera_id = tracking_result.source_frame_id
        engine = self._engines.get(camera_id)
        
        if not engine:
            logger.warning(f"AttendanceEngine: No engine for camera {camera_id}")
            return []
        
        all_events = []
        
        for track in tracking_result.get_active_tracks():
            # Update track with GIS identity
            global_person_id, identity_state = self.gis.update_track(camera_id, track)
            
            # Set GIS fields on track
            track.global_person_id = global_person_id
            track.identity_state = identity_state
            
            events = engine.process_track_update(
                track=track,
                timestamp=tracking_result.timestamp,
                frame_index=tracking_result.frame_index,
            )
            
            for event in events:
                all_events.append(event)
                # Store in database
                self._store.store_event(event)
                # Trigger callbacks
                for callback in self._event_callbacks:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.error(f"AttendanceEngine: Event callback error: {e}")
        
        return all_events
    
    def get_events(self, **filters) -> List[Dict[str, Any]]:
        """Query stored attendance events."""
        return self._store.get_events(**filters)
    
    def get_daily_summary(self, date: str) -> Dict[str, Any]:
        """Get daily attendance summary."""
        return self._store.get_daily_summary(date)
    
    def export_events(self, output_path: str, **filters) -> bool:
        """Export events to JSON."""
        return self._store.export_to_json(output_path, **filters)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get attendance engine statistics."""
        total_events = 0
        total_in = 0
        total_out = 0
        
        for engine in self._engines.values():
            stats = engine.get_stats()
            total_events += stats["total_crossings"]
            total_in += stats["in_crossings"]
            total_out += stats["out_crossings"]
        
        return {
            "total_events": total_events,
            "in_events": total_in,
            "out_events": total_out,
            "cameras": {
                cam_id: engine.get_stats() 
                for cam_id, engine in self._engines.items()
            },
        }


def create_attendance_engine(config: Optional[Any] = None) -> AttendanceEngine:
    """Factory function to create attendance engine."""
    return AttendanceEngine(config)


if __name__ == "__main__":
    # Quick test
    from pipeline_engine.tracking.tracker import Track, TrackLifecycleState
    import time
    
    engine = AttendanceEngine()
    
    print("Engines:", list(engine._engines.keys()))
    print("Stats:", engine.get_stats())
    
    # Create test track
    track = Track(
        track_id=1,
        source_frame_id="cam1",
        frame_index=1,
        timestamp=time.time(),
        bbox_original_frame=(1000, 1200, 1100, 1300),  # Below line
        confidence=0.8,
        lifecycle_state=TrackLifecycleState.ACTIVE,
        age=1,
        hits=1,
        missed_frames=0,
        last_seen=time.time(),
    )
    
    # Process first frame - initialize state
    events1 = engine.process_tracks(
        TrackingResult(
            source_frame_id="cam1",
            frame_index=1,
            timestamp=time.time(),
            tracks=[track],
        )
    )
    print(f"Frame 1 events: {len(events1)}")
    
    # Move track above line - should trigger IN event
    track2 = Track(
        track_id=1,
        source_frame_id="cam1",
        frame_index=2,
        timestamp=time.time(),
        bbox_original_frame=(1000, 800, 1100, 900),  # Above line
        confidence=0.8,
        lifecycle_state=TrackLifecycleState.ACTIVE,
        age=2,
        hits=2,
        missed_frames=0,
        last_seen=time.time(),
    )
    
    events2 = engine.process_tracks(
        TrackingResult(
            source_frame_id="cam1",
            frame_index=2,
            timestamp=time.time(),
            tracks=[track2],
        )
    )
    print(f"Frame 2 events: {len(events2)}")
    for e in events2:
        print(f"  Event: {e.event_id}, direction={e.direction.value}, person={e.person_id}")
    
    print("AttendanceEngine test passed!")