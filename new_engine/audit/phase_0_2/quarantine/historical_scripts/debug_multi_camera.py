"""Debug multi-camera geometry isolation test."""
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
    CrossingDirection,
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

# CAM1: Vertical line at x=1000
config1 = create_line_geometry(
    camera_id="CAM1",
    frame_width=3840,
    frame_height=2160,
    p1=(1000, 0),
    p2=(1000, 2160),
    direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
    crossing_policy=CrossingPolicyConfig(
        min_crossing_distance=5.0,
        temporal_debounce_seconds=0.0,
        side_confirmation_frames=1,
    ),
)

# CAM2: Horizontal line at y=1080
config2 = create_line_geometry(
    camera_id="CAM2",
    frame_width=3840,
    frame_height=2160,
    p1=(0, 1080),
    p2=(3840, 1080),
    direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
    crossing_policy=CrossingPolicyConfig(
        min_crossing_distance=5.0,
        temporal_debounce_seconds=0.0,
        side_confirmation_frames=1,
    ),
)

engine1 = create_crossing_engine(config1)
engine2 = create_crossing_engine(config2)

# Process same track on both cameras
# CAM1: Cross vertical line
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
engine1.process_track(track, frame_index=0, timestamp=0.0)
track = MockTrack("track_1", 1500, 1080, (1400, 980, 1600, 1180))
events1 = engine1.process_track(track, frame_index=1, timestamp=0.033)
print(f"CAM1 events: {len(events1)}")
if events1:
    print(f"  Event: {events1[0].direction.value}, camera_id={events1[0].camera_id}")

# CAM2: Cross horizontal line (same track moves vertically)
track = MockTrack("track_1", 1500, 500, (1400, 400, 1600, 600))
engine2.process_track(track, frame_index=0, timestamp=0.0)
track = MockTrack("track_1", 1500, 1500, (1400, 1400, 1600, 1600))
events2 = engine2.process_track(track, frame_index=1, timestamp=0.033)
print(f"CAM2 events: {len(events2)}")
if events2:
    print(f"  Event: {events2[0].direction.value}, camera_id={events2[0].camera_id}")

# Verify isolation: CAM1 events don't affect CAM2
print(f"CAM1 total events: {len(engine1.get_events())}")
print(f"CAM2 total events: {len(engine2.get_events())}")
if engine1.get_events():
    print(f"CAM1 event camera_id: {engine1.get_events()[0].camera_id}")
if engine2.get_events():
    print(f"CAM2 event camera_id: {engine2.get_events()[0].camera_id}")