"""
Phase 25 — Attendance Persistence & Query Layer.

Public API exports for the attendance module.
"""

from app.attendance.contract import (
    AttendanceRecord,
    AttendanceRecordCreationResult,
    AttendanceDirection,
    IdentityCertainty,
    generate_attendance_record_id,
    create_attendance_record_from_resolution,
    validate_attendance_record,
)

from app.attendance.storage import (
    AttendanceStorage,
    StorageConfig,
    create_attendance_storage,
)

from app.attendance.repository import (
    AttendanceRepository,
    PersistenceResult,
    create_attendance_repository,
)

from app.attendance.query import (
    AttendanceQueryBuilder,
    AttendanceQueryResult,
    AttendanceSummary,
    create_query_builder,
    get_attendance_summary,
    format_timestamp,
    parse_timestamp,
    records_to_timeline,
    get_daily_attendance_counts,
    get_track_state_history,
)

__all__ = [
    # Contract
    "AttendanceRecord",
    "AttendanceRecordCreationResult",
    "AttendanceDirection",
    "IdentityCertainty",
    "generate_attendance_record_id",
    "create_attendance_record_from_resolution",
    "validate_attendance_record",
    
    # Storage
    "AttendanceStorage",
    "StorageConfig",
    "create_attendance_storage",
    
    # Repository
    "AttendanceRepository",
    "PersistenceResult",
    "create_attendance_repository",
    
    # Query
    "AttendanceQueryBuilder",
    "AttendanceQueryResult",
    "AttendanceSummary",
    "create_query_builder",
    "get_attendance_summary",
    "format_timestamp",
    "parse_timestamp",
    "records_to_timeline",
    "get_daily_attendance_counts",
    "get_track_state_history",
]