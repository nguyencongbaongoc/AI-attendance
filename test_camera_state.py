from app.streaming.health import StreamHealthMonitor, create_health_monitor, StreamHealthState, HealthCheckResult
import time

# Test camera state machine
monitor = create_health_monitor()
monitor.register_camera('CAM1')
monitor.register_camera('CAM2')

print('=== Initial State (no frames) ===')
for cam_id in ['CAM1', 'CAM2']:
    result = monitor.check_health(cam_id)
    print(f'{cam_id}: state={result.state.value}, message={result.message}')

print()
print('=== Simulate frame received ===')
monitor.update_frame_received('CAM1', frame_index=1, timestamp=time.time(), frame_size=1000, resolution=(3840, 2160), fps=30.0, codec='h264')
result = monitor.check_health('CAM1')
print(f'CAM1: state={result.state.value}, message={result.message}')

print()
print('=== Simulate frame timeout (11 seconds later) ===')
# Use a time function that simulates time passing
class MockTime:
    def __init__(self):
        self.t = time.time()
    def __call__(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds

mock_time = MockTime()
monitor2 = create_health_monitor(time_func=mock_time)
monitor2.register_camera('CAM1')
monitor2.update_frame_received('CAM1', frame_index=1, timestamp=mock_time(), frame_size=1000, resolution=(3840, 2160), fps=30.0, codec='h264')
print(f'After first frame: {monitor2.check_health("CAM1").state.value}')

mock_time.advance(11)  # Past frame_timeout (10s)
result = monitor2.check_health('CAM1')
print(f'After 11s: state={result.state.value}, message={result.message}')

print()
print('=== State transitions ===')
print('OFFLINE -> CONNECTING -> LIVE -> DEGRADED -> ERROR -> RECONNECTING -> LIVE')
print('States defined in StreamHealthState:')
for state in StreamHealthState:
    print(f'  {state.value}')