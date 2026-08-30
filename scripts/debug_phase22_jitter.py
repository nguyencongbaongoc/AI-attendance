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
        min_crossing_distance=10.0,  # Require 10px crossing
        temporal_debounce_seconds=0.0,
        side_confirmation_frames=2,  # Need 2 frames on new side
    ),
)

engine = create_crossing_engine(config)

# Start on left
track = MockTrack("track_1", 950, 1080, (850, 980, 1050, 1180))
result = engine.process_track(track, frame_index=0, timestamp=0.0)
print(f"Frame 0: left side (950, 1080), events={len(result)}")

# Jitter around line - positions must stay within 10px total distance
# Use positions very close to line: all between 996-1004 (within 10px total range)
positions = [996, 1004, 998, 1002, 997, 1003]
for i, x in enumerate(positions):
    track = MockTrack("track_1", x, 1080, (x-100, 980, x+100, 1180))
    result = engine.process_track(track, frame_index=i+1, timestamp=(i+1)*0.033)
    print(f"Frame {i+1}: x={x}, events={len(result)}, directions={[e.direction.value for e in result]}")

all_events = engine.get_events()
print(f"Total events after jitter: {len(all_events)}")

# Now cross properly (move well beyond line)
track = MockTrack("track_1", 1150, 1080, (1050, 980, 1250, 1180))
result = engine.process_track(track, frame_index=10, timestamp=0.33)
print(f"Frame 10: x=1150, events={len(result)}, directions={[e.direction.value for e in result]}")

# Need 2 confirmation frames, so first frame after crossing won't trigger
# Second frame will
track = MockTrack("track_1", 1200, 1080, (1100, 980, 1300, 1180))
result = engine.process_track(track, frame_index=11, timestamp=0.363)
print(f"Frame 11: x=1200, events={len(result)}, directions={[e.direction.value for e in result]}")

all_events = engine.get_events()
print(f"Total events: {len(all_events)}, directions={[e.direction.value for e in all_events]}")