from pathlib import Path

content = Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/tests/unit/test_streaming_health.py').read_text(encoding='utf-8')

# Find the specific test and fix it
idx = content.find('def test_no_wall_clock_in_deterministic_tests(self):')
if idx >= 0:
    # Find the end of this test method
    idx2 = content.find('class TestHealthCheckResult:', idx)
    if idx2 >= 0:
        old = content[idx:idx2]
        new = '    def test_no_wall_clock_in_deterministic_tests(self):\n        monitor = create_health_monitor(\n            stale_threshold_seconds=5.0,\n            degraded_threshold_seconds=2.0,\n        )\n        monitor.register_camera("CAM1")\n        monitor.update_frame_received("CAM1", frame_index=0, timestamp=1000.0, current_time=1000.0)\n        \n        result = monitor.check_health("CAM1", current_time=1000.5)\n        assert result.state == StreamHealthState.LIVE\n        \n        result = monitor.check_health("CAM1", current_time=1003.0)\n        assert result.state == StreamHealthState.DEGRADED\n\n\nclass TestHealthCheckResult:'
        content = content[:idx] + new + content[idx2:]
        Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/tests/unit/test_streaming_health.py').write_text(content, encoding='utf-8')
        print('Fixed')
    else:
        print('End not found')
else:
    print('Test not found')