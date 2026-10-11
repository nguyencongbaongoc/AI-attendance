with open('app/attendance/repository.py', 'r') as f:
    content = f.read()

old = 'def get_by_resolution_id(self, resolution_id: str) -> Optional[AttendanceRecord]:\r\n        """Get attendance record by Phase 24 resolution ID."""\r\n        return self.storage.get_by_source_resolution_id(resolution_id)\r\n    \r\n    def exists_by_resolution_id'

new = 'def get_by_resolution_id(self, resolution_id: str) -> Optional[AttendanceRecord]:\r\n        """Get attendance record by Phase 24 resolution ID."""\r\n        return self.storage.get_by_source_resolution_id(resolution_id)\r\n    \r\n    def get_by_id(self, attendance_record_id: str) -> Optional[AttendanceRecord]:\r\n        """Get attendance record by attendance record ID."""\r\n        return self.storage.get_by_id(attendance_record_id)\r\n    \r\n    def exists_by_resolution_id'

new_content = content.replace(old, new)
with open('app/attendance/repository.py', 'w') as f:
    f.write(new_content)
print('Done')