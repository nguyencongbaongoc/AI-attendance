"""Debug jitter/hysteresis test."""
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
        min_crossing_distance=10.0,
        temporal_debounce_seconds=0.0,
        side_confirmation_frames=2,
    ),
)

engine = create_crossing_engine(config)

# Start on left
track = MockTrack("track_1", 950, 1080, (850, 980, 1050, 1180))
engine.process_track(track, frame_index=0, timestamp=0.0)

# Jitter around line - all positions on LEFT side of line (x < 1000)
positions = [995, 996, 997, 998, 999, 998]
for i, x in enumerate(positions):
    track = MockTrack("track_1", x, 1080, (x-100, 980, x+100, 1180))
    events = engine.process_track(track, frame_index=i+1, timestamp=(i+1)*0.033)
    print(f"Frame {i+1}: x={x}, events={len(events)}")
    if events:
        for e in events:
            print(f"  Event: {e.direction.value}, crossing_dist={e.crossing_distance}")

all_events = engine.get_events()
print(f"Total events after jitter: {len(all_events)}")

# Now cross properly
track = MockTrack("track_1", 1150, 1080, (1050, 980, 1250, 1180))
events = engine.process_track(track, frame_index=10, timestamp=0.33)
print(f"Frame 10 (cross): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}")

track = MockTrack("track_1", 1200, 1080, (1100, 980, 1300, 1180))
events = engine.process_track(track, frame_index=11, timestamp=0.363)
print(f"Frame 11 (confirm): events={len(events)}")
if events:
    for e in events:
        print(f"  Event: {e.direction.value}")

print(f"Total events: {len(engine.get_events())}")