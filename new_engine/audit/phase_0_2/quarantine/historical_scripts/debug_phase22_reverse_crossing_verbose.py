import sys
sys.path.insert(0, '.')

from scripts.phase22_in_out_geometry import (
    create_line_geometry,
    create_crossing_engine,
    CrossingPolicyConfig,
    DirectionSemantics,
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

config = create_line_geometry(
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

engine = create_crossing_engine(config)

# Start on left (SIDE_A)
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
result = engine.process_track(track, frame_index=0, timestamp=0.0)
print(f"Frame 0: left side (500, 1080), events={len(result)}")

# Cross to right (SIDE_B) - IN
track = MockTrack("track_1", 1500, 1080, (1400, 980, 1600, 1180))
result = engine.process_track(track, frame_index=1, timestamp=0.033)
print(f"Frame 1: right side (1500, 1080), events={len(result)}, directions={[e.direction.value for e in result]}")

# Cross back to left (SIDE_A) - OUT
track = MockTrack("track_1", 500, 1080, (400, 980, 600, 1180))
result = engine.process_track(track, frame_index=2, timestamp=0.066)
print(f"Frame 2: left side (500, 1080), events={len(result)}, directions={[e.direction.value for e in result]}")

# Check all events
all_events = engine.get_events()
print(f"Total events: {len(all_events)}, directions={[e.direction.value for e in all_events]}")