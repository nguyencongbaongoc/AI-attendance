from pathlib import Path

content = Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').read_text(encoding='utf-8')

old = '''    def update_reconnect(self, camera_id: str, attempt: int) -> None:
        """Update health during reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        snapshot.reconnect_count = attempt
        snapshot.last_reconnect_time = datetime.utcnow().isoformat() + "Z"
        snapshot.state = StreamHealthState.RECONNECTING

    def update_reconnect_success(self, camera_id: str) -> None:
        """Update health after successful reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        snapshot.state = StreamHealthState.LIVE
    
    def update_reconnect_failed(self, camera_id: str, reason: str) -> None:
        """Update health after failed reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        snapshot.state = StreamHealthState.ERROR
        snapshot.last_error = f"Reconnect failed: {reason}"
        snapshot.last_error_time = datetime.utcnow().isoformat() + "Z"
    
'''

new = '''    def update_reconnect(self, camera_id: str, attempt: int) -> None:
        """Update health during reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.reconnect_count = attempt
        snapshot.last_reconnect_time = datetime.utcnow().isoformat() + "Z"
        snapshot.state = StreamHealthState.RECONNECTING
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_ATTEMPT,
            attempt=attempt,
            max_attempts=5,  # Default, could be configurable
            reason=f"Reconnect attempt {attempt}",
            source_identifier="rtsp",
        ))

    def update_reconnect_success(self, camera_id: str) -> None:
        """Update health after successful reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.state = StreamHealthState.LIVE
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_SUCCESS,
            attempt=snapshot.reconnect_count,
            max_attempts=5,
            reason="Reconnection successful",
            source_identifier="rtsp",
            success=True,
        ))

    def update_reconnect_failed(self, camera_id: str, reason: str) -> None:
        """Update health after failed reconnection."""
        self.register_camera(camera_id)
        
        snapshot = self._snapshots[camera_id]
        prev_state = snapshot.state
        snapshot.state = StreamHealthState.ERROR
        snapshot.last_error = f"Reconnect failed: {reason}"
        snapshot.last_error_time = datetime.utcnow().isoformat() + "Z"
        
        self._emit_event(create_reconnect_event(
            event_id=f"{camera_id}-{self._get_event_counter(camera_id)}",
            camera_id=camera_id,
            event_type=HealthEventType.RECONNECT_FAILED,
            attempt=snapshot.reconnect_count,
            max_attempts=5,
            reason=f"Reconnect failed: {reason}",
            source_identifier="rtsp",
        ))
    
'''

if old in content:
    content = content.replace(old, new)
    Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').write_text(content, encoding='utf-8')
    print('Replaced successfully')
else:
    print('Old text not found')
    idx = content.find('def update_reconnect(self, camera_id: str, attempt: int)')
    print(repr(content[idx:idx+600]))