"""Debug debounce test."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.geometry import (
    CameraGeometryConfig,
    CrossingPolicyConfig,
    DirectionSemantics,
    GeometryType,
    LineGeometry,
    Point2D,
    create_line_geometry,
    create_crossing_engine,
)

class MockTrack:
    def __init__(self, track_id, center_x, center_y, bbox):
        self.track_id = track_id
        self._center = (center_x, center_y)
        self._bbox = bbox
    
    @property
    def center(self):
        return self._center
    
    @property
    def bbox_original_frame(self):
        return self._bbox

config = create_line_geometry(
    camera_id="CAM1",
    frame_width=3840,
    frame_height=2160,
    p1=(1000, 0),
    p2=(1000, 2160),
    direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
    crossing_policy=CrossingPolicyConfig(
        min_crossing_distance=5.0,
        temporal_debounce_seconds=1.0,  # 1 second debounce
        side_confirmation_frames=1,
    ),
)

engine = create_crossing_engine(config)

# Cross IN
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
events = engine.process_track(track, frame_index=0, timestamp=0.0)
print(f"Frame 0 (left): events={len(events)}")

# Check state after frame 0
state = engine._track_states["track_1"]
print(f"After frame 0: current_side={state.current_side}, confirmed_side={state.confirmed_side}, frames_on_current_side={state.frames_on_current_side}")

track = MockTrack("track_1", 1500, 1080, (1400, 980, 1600, 1180))
events = engine.process_track(track, frame_index=1, timestamp=0.033)
print(f"Frame 1 (right): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}, timestamp={e.crossing_timestamp}")

# Check state after frame 1
state = engine._track_states["track_1"]
print(f"After frame 1: current_side={state.current_side}, confirmed_side={state.confirmed_side}, frames_on_current_side={state.frames_on_current_side}")
print(f"Pending: {getattr(state, '_pending_crossing', None)}")
print(f"Stats: {engine.get_stats()}")

# Immediately cross back OUT (within debounce period)
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
events = engine.process_track(track, frame_index=2, timestamp=0.066)
print(f"Frame 2 (OUT at 0.066s): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}")

# Cross back OUT after debounce period
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
events = engine.process_track(track, frame_index=30, timestamp=1.0)
print(f"Frame 30 (OUT at 1.0s): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}")

track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
events = engine.process_track(track, frame_index=60, timestamp=2.0)
print(f"Frame 60 (OUT at 2.0s): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}")

all_events = engine.get_events()
print(f"Total events: {len(all_events)}")
for e in all_events:
    print(f"  {e.direction.value} at {e.crossing_timestamp}s")