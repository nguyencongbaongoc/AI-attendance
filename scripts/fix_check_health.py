from pathlib import Path

content = Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').read_text(encoding='utf-8')

old = '''        result.details = {
            "frames_received": snapshot.frames_received,
            "frames_dropped": snapshot.frames_dropped,
            "total_errors": snapshot.total_errors,
            "uptime_seconds": snapshot.uptime_seconds,
            "current_resolution": snapshot.current_resolution,
            "current_fps": snapshot.current_fps,
            "current_codec": snapshot.current_codec,
        }
        
        result.reconnect_count = snapshot.reconnect_count
        result.last_successful_frame = snapshot.frames_received if snapshot.frames_received > 0 else None
        result.last_successful_time = snapshot.last_frame_timestamp
        
        self._last_check_results[camera_id] = result
        return result'''

new = '''        # Create a new result with details since HealthCheckResult is frozen
        result = HealthCheckResult(
            camera_id=result.camera_id,
            state=result.state,
            timestamp=result.timestamp,
            message=result.message,
            details={
                "frames_received": snapshot.frames_received,
                "frames_dropped": snapshot.frames_dropped,
                "total_errors": snapshot.total_errors,
                "uptime_seconds": snapshot.uptime_seconds,
                "current_resolution": snapshot.current_resolution,
                "current_fps": snapshot.current_fps,
                "current_codec": snapshot.current_codec,
            },
            last_successful_frame=result.last_successful_frame,
            last_successful_time=result.last_successful_time,
            failure_reason=result.failure_reason,
            reconnect_count=snapshot.reconnect_count,
            consecutive_failures=result.consecutive_failures,
        )
        
        self._last_check_results[camera_id] = result
        return result'''

if old in content:
    content = content.replace(old, new)
    Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').write_text(content, encoding='utf-8')
    print('Replaced successfully')
else:
    print('Old text not found')
    idx = content.find('result.details = {')
    if idx >= 0:
        print(repr(content[idx:idx+500]))
    else:
        print('Pattern not found')