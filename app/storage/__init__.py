"""
Phase 17 — Storage Module.
"""

from app.storage.snapshot_saver import AsyncSnapshotSaver, SnapshotResult, get_snapshot_saver, shutdown_snapshot_saver
from app.storage.clip_extractor import ClipExtractor, ClipExtractResult, get_clip_extractor
from app.storage.retention_service import (
    RetentionService,
    RetentionPolicy,
    RetentionStats,
    DiskWatchdog,
    DiskSpaceInfo,
    DatabaseMaintenance,
    get_retention_service,
    get_disk_watchdog,
    get_db_maintenance,
    start_storage_services,
    stop_storage_services,
)

__all__ = [
    "AsyncSnapshotSaver",
    "SnapshotResult",
    "get_snapshot_saver",
    "shutdown_snapshot_saver",
    "ClipExtractor",
    "ClipExtractResult",
    "get_clip_extractor",
    "RetentionService",
    "RetentionPolicy",
    "RetentionStats",
    "DiskWatchdog",
    "DiskSpaceInfo",
    "DatabaseMaintenance",
    "get_retention_service",
    "get_disk_watchdog",
    "get_db_maintenance",
    "start_storage_services",
    "stop_storage_services",
]