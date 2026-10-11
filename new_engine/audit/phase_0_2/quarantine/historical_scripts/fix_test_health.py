from pathlib import Path

content = Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/tests/unit/test_streaming_health.py').read_text(encoding='utf-8')

# Find the problematic section
idx = content.find('HealthEventType.RECONNECT_ATTEMPT,')
if idx > 0:
    start = content.rfind('reconnect_events = [e for e in events if e.event_type in (', 0, idx)
    if start > 0:
        end = content.find('assert len(reconnect_events) == 2', idx)
        if end > 0:
            end = content.find('\n', end) + 1
            # Replace the broken section
            replacement = '        reconnect_events = [e for e in events if e.event_type in (\n            HealthEventType.RECONNECT_ATTEMPT,\n            HealthEventType.RECONNECT_SUCCESS,\n        )]\n        assert len(reconnect_events) == 2\n        assert reconnect_events[0].event_type == HealthEventType.RECONNECT_ATTEMPT\n        assert reconnect_events[1].event_type == HealthEventType.RECONNECT_SUCCESS\n        assert reconnect_events[1].details["success"] is True\n\n    def test_reconnect_failed_emits_event(self):'
            fixed = content[:start] + replacement + content[end:]
            Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/tests/unit/test_streaming_health.py').write_text(fixed, encoding='utf-8')
            print('Fixed')
        else:
            print('End not found')
    else:
        print('Start not found')
else:
    print('Pattern not found')