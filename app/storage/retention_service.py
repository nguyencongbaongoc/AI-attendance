"""
Phase 17C — Storage Retention Service & Watchdog.

Implements configurable retention policies, disk space monitoring,
emergency auto-purge, and automated SQLite backup & VACUUM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class RetentionPolicy:
    """Configuration for a single retention policy."""
    name: str
    paths: List[str]  # Glob patterns or directories
    max_age_days: int
    file_extensions: List[str] = field(default_factory=lambda: ["*"])
    preserve_recent: int = 0  # Always keep at least N most recent files
    enabled: bool = True


@dataclass
class RetentionStats:
    """Statistics from a retention run."""
    policy_name: str
    files_scanned: int = 0
    files_deleted: int = 0
    bytes_freed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class DiskSpaceInfo:
    """Disk space information."""
    total_bytes: int
    free_bytes: int
    used_bytes: int
    free_percent: float
    path: str


class RetentionService:
    """
    Scheduled background retention worker.
    
    Runs once per hour by default and enforces retention policies:
    - Continuous recordings: 7 days
    - Event snapshots: 30 days  
    - Event video clips: 14 days
    - Database cleanup: NULL out expired URIs
    """
    
    DEFAULT_POLICIES = [
        RetentionPolicy(
            name="continuous_recordings",
            paths=["recordings/cam1", "recordings/cam2"],
            max_age_days=7,
            file_extensions=[".mp4", ".m4s"],
            preserve_recent=5,  # Keep at least 5 recent segments per camera
        ),
        RetentionPolicy(
            name="event_snapshots",
            paths=["app/static/evidence/snapshots"],
            max_age_days=30,
            file_extensions=[".jpg", ".jpeg"],
        ),
        RetentionPolicy(
            name="event_clips",
            paths=["app/static/evidence/clips"],
            max_age_days=14,
            file_extensions=[".mp4"],
        ),
    ]
    
    def __init__(
        self,
        policies: Optional[List[RetentionPolicy]] = None,
        interval_seconds: float = 3600.0,  # 1 hour
        attendance_db_path: str = "app/data/attendance.db",
    ):
        self.policies = policies or self.DEFAULT_POLICIES
        self.interval_seconds = interval_seconds
        self.attendance_db_path = attendance_db_path
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._stats_history: List[RetentionStats] = []
        self._max_history = 100
        self._callbacks: List[Callable[[RetentionStats], None]] = []
    
    def add_callback(self, callback: Callable[[RetentionStats], None]):
        """Add callback to be notified of retention runs."""
        self._callbacks.append(callback)
    
    async def start(self):
        """Start the retention worker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._worker_loop())
        logger.info(f"RetentionService started (interval: {self.interval_seconds}s)")
    
    async def stop(self):
        """Stop the retention worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RetentionService stopped")
    
    async def _worker_loop(self):
        """Main worker loop."""
        # Run immediately on start
        await self.run_retention()
        
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if self._running:
                    await self.run_retention()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in retention worker loop: {e}")
                await asyncio.sleep(60)  # Back off on error
    
    async def run_retention(self) -> List[RetentionStats]:
        """Run all retention policies once."""
        logger.info("Starting retention run...")
        all_stats = []
        
        for policy in self.policies:
            if not policy.enabled:
                continue
            
            stats = await self._apply_policy(policy)
            all_stats.append(stats)
            
            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(stats)
                except Exception as e:
                    logger.error(f"Retention callback error: {e}")
        
        # Database cleanup
        db_stats = await self._cleanup_database_uris()
        all_stats.append(db_stats)
        
        # Store stats
        self._stats_history.extend(all_stats)
        if len(self._stats_history) > self._max_history:
            self._stats_history = self._stats_history[-self._max_history:]
        
        total_deleted = sum(s.files_deleted for s in all_stats)
        total_freed = sum(s.bytes_freed for s in all_stats)
        logger.info(f"Retention run complete: {total_deleted} files deleted, {total_freed / (1024**2):.1f} MB freed")
        
        return all_stats
    
    async def _apply_policy(self, policy: RetentionPolicy) -> RetentionStats:
        """Apply a single retention policy."""
        start_time = time.perf_counter()
        stats = RetentionStats(policy_name=policy.name)
        
        try:
            cutoff_time = time.time() - (policy.max_age_days * 86400)
            
            for path_pattern in policy.paths:
                base_path = Path(path_pattern)
                if not base_path.exists():
                    logger.debug(f"Path not found: {base_path}")
                    continue
                
                # Find files matching extensions
                for ext in policy.file_extensions:
                    if ext == "*":
                        files = list(base_path.rglob("*"))
                    else:
                        files = list(base_path.rglob(f"*{ext}"))
                    
                    for file_path in files:
                        if not file_path.is_file():
                            continue
                        
                        stats.files_scanned += 1
                        
                        try:
                            mtime = file_path.stat().st_mtime
                            
                            # Check if file is older than cutoff
                            if mtime < cutoff_time:
                                # Check preserve_recent
                                if policy.preserve_recent > 0:
                                    # Get all files in same directory
                                    sibling_files = list(file_path.parent.glob("*"))
                                    sibling_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                                    if sibling_files.index(file_path) < policy.preserve_recent:
                                        continue  # Skip - within preserve_recent
                                
                                file_size = file_path.stat().st_size
                                file_path.unlink()
                                stats.files_deleted += 1
                                stats.bytes_freed += file_size
                                logger.debug(f"Deleted expired file: {file_path}")
                        
                        except Exception as e:
                            error_msg = f"Error processing {file_path}: {e}"
                            stats.errors.append(error_msg)
                            logger.warning(error_msg)
            
        except Exception as e:
            error_msg = f"Policy {policy.name} failed: {e}"
            stats.errors.append(error_msg)
            logger.error(error_msg)
        
        stats.duration_ms = (time.perf_counter() - start_time) * 1000
        return stats
    
    async def _cleanup_database_uris(self) -> RetentionStats:
        """Set expired evidence URIs to NULL in attendance database."""
        start_time = time.perf_counter()
        stats = RetentionStats(policy_name="database_uri_cleanup")
        
        try:
            # Find records with URIs pointing to files that no longer exist
            conn = sqlite3.connect(self.attendance_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all records with non-null URIs
            cursor.execute("""
                SELECT attendance_record_id, snapshot_face_url, snapshot_scene_url, video_clip_url
                FROM attendance_records
                WHERE snapshot_face_url IS NOT NULL 
                   OR snapshot_scene_url IS NOT NULL 
                   OR video_clip_url IS NOT NULL
            """)
            
            records = cursor.fetchall()
            stats.files_scanned = len(records)
            
            updates = []
            for record in records:
                updates_needed = []
                
                for url_field in ["snapshot_face_url", "snapshot_scene_url", "video_clip_url"]:
                    url = record[url_field]
                    if url:
                        # Convert relative URI to absolute path
                        file_path = Path("app/static") / url
                        if not file_path.exists():
                            updates_needed.append(url_field)
                
                if updates_needed:
                    updates.append((record["attendance_record_id"], updates_needed))
            
            # Perform updates
            for record_id, fields in updates:
                set_clause = ", ".join([f"{f} = NULL" for f in fields])
                cursor.execute(
                    f"UPDATE attendance_records SET {set_clause} WHERE attendance_record_id = ?",
                    (record_id,)
                )
                stats.files_deleted += len(fields)  # Count as "deleted" URIs
            
            conn.commit()
            conn.close()
            
            logger.info(f"Database URI cleanup: {stats.files_deleted} URIs nulled out")
            
        except Exception as e:
            error_msg = f"Database URI cleanup failed: {e}"
            stats.errors.append(error_msg)
            logger.error(error_msg)
        
        stats.duration_ms = (time.perf_counter() - start_time) * 1000
        return stats
    
    def get_stats_history(self) -> List[RetentionStats]:
        """Get retention run history."""
        return self._stats_history.copy()
    
    def get_last_stats(self) -> Optional[RetentionStats]:
        """Get the most recent retention run stats."""
        return self._stats_history[-1] if self._stats_history else None


class DiskWatchdog:
    """
    Real-time disk space monitor with emergency auto-purge.
    
    Monitors free disk percentage every 60 seconds:
    - Warning (< 15%): Log warning, notify admin
    - Emergency (< 10%): Aggressive purge of oldest recordings
    """
    
    def __init__(
        self,
        watch_path: str = ".",
        check_interval_seconds: float = 60.0,
        warning_threshold_pct: float = 15.0,
        emergency_threshold_pct: float = 10.0,
        retention_service: Optional[RetentionService] = None,
        purge_callback: Optional[Callable[[float], None]] = None,
    ):
        self.watch_path = Path(watch_path).resolve()
        self.check_interval_seconds = check_interval_seconds
        self.warning_threshold_pct = warning_threshold_pct
        self.emergency_threshold_pct = emergency_threshold_pct
        self.retention_service = retention_service
        self.purge_callback = purge_callback
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_warning_time = 0
        self._warning_cooldown = 300  # 5 minutes between warnings
        self._last_emergency_time = 0
        self._emergency_cooldown = 60  # 1 minute between emergency purges
    
    async def start(self):
        """Start the disk watchdog."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"DiskWatchdog started on {self.watch_path}")
    
    async def stop(self):
        """Stop the disk watchdog."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DiskWatchdog stopped")
    
    def get_disk_info(self) -> DiskSpaceInfo:
        """Get current disk space info."""
        usage = shutil.disk_usage(self.watch_path)
        free_percent = (usage.free / usage.total) * 100
        
        return DiskSpaceInfo(
            total_bytes=usage.total,
            free_bytes=usage.free,
            used_bytes=usage.used,
            free_percent=free_percent,
            path=str(self.watch_path),
        )
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_disk_space()
            except Exception as e:
                logger.error(f"Disk watchdog error: {e}")
            
            await asyncio.sleep(self.check_interval_seconds)
    
    async def _check_disk_space(self):
        """Check disk space and take action if needed."""
        info = self.get_disk_info()
        
        logger.debug(f"Disk space: {info.free_percent:.1f}% free ({info.free_bytes / (1024**3):.1f} GB)")
        
        now = time.time()
        
        if info.free_percent < self.emergency_threshold_pct:
            # Emergency threshold breached
            if now - self._last_emergency_time > self._emergency_cooldown:
                logger.critical(
                    f"EMERGENCY: Disk space critical ({info.free_percent:.1f}% free). "
                    f"Triggering aggressive purge..."
                )
                await self._emergency_purge()
                self._last_emergency_time = now
        
        elif info.free_percent < self.warning_threshold_pct:
            # Warning threshold breached
            if now - self._last_warning_time > self._warning_cooldown:
                logger.warning(
                    f"WARNING: Disk space low ({info.free_percent:.1f}% free). "
                    f"Threshold: {self.warning_threshold_pct}%"
                )
                self._last_warning_time = now
                
                # Notify admin via callback if provided
                if self.purge_callback:
                    try:
                        await self.purge_callback(info.free_percent)
                    except Exception as e:
                        logger.error(f"Warning callback failed: {e}")
    
    async def _emergency_purge(self):
        """Aggressively purge oldest continuous recordings until free space >= 15%."""
        if not self.retention_service:
            logger.error("No retention service available for emergency purge")
            return
        
        logger.info("Starting emergency disk purge...")
        
        # Target: get to 15% free
        target_free_pct = 15.0
        max_iterations = 10
        
        for iteration in range(max_iterations):
            info = self.get_disk_info()
            if info.free_percent >= target_free_pct:
                logger.info(f"Emergency purge complete: {info.free_percent:.1f}% free")
                break
            
            # Find and delete oldest recording segments (but preserve snapshots/clips)
            await self._purge_oldest_recordings()
            
            # Small delay to let filesystem catch up
            await asyncio.sleep(1)
        
        final_info = self.get_disk_info()
        logger.info(f"Emergency purge finished: {final_info.free_percent:.1f}% free")
    
    async def _purge_oldest_recordings(self):
        """Delete oldest recording segments first."""
        recordings_dirs = [
            Path("recordings/cam1"),
            Path("recordings/cam2"),
        ]
        
        # Collect all recording files with their mtime
        all_files = []
        for rec_dir in recordings_dirs:
            if rec_dir.exists():
                for ext in [".mp4", ".m4s"]:
                    for f in rec_dir.rglob(f"*{ext}"):
                        if f.is_file():
                            all_files.append((f.stat().st_mtime, f))
        
        # Sort by age (oldest first)
        all_files.sort(key=lambda x: x[0])
        
        # Delete up to 100 oldest files per iteration
        deleted = 0
        for mtime, file_path in all_files[:100]:
            try:
                file_path.unlink()
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
        
        logger.info(f"Emergency purge iteration: deleted {deleted} recording files")


class DatabaseMaintenance:
    """
    Automated SQLite backup & VACUUM maintenance.
    
    - Daily online backup via sqlite3.backup()
    - Rolling 7-day backup retention
    - Weekly PRAGMA incremental_vacuum / PRAGMA optimize
    """
    
    def __init__(
        self,
        db_path: str = "app/data/attendance.db",
        backup_dir: str = "app/data/backups",
        backup_interval_hours: float = 24.0,
        vacuum_interval_days: int = 7,
        max_backups: int = 7,
    ):
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.backup_interval_seconds = backup_interval_hours * 3600
        self.vacuum_interval_seconds = vacuum_interval_days * 86400
        self.max_backups = max_backups
        
        self._running = False
        self._backup_task: Optional[asyncio.Task] = None
        self._vacuum_task: Optional[asyncio.Task] = None
        self._last_backup = 0
        self._last_vacuum = 0
        
        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    async def start(self):
        """Start maintenance tasks."""
        if self._running:
            return
        
        self._running = True
        self._backup_task = asyncio.create_task(self._backup_loop())
        self._vacuum_task = asyncio.create_task(self._vacuum_loop())
        logger.info("DatabaseMaintenance started")
    
    async def stop(self):
        """Stop maintenance tasks."""
        self._running = False
        for task in [self._backup_task, self._vacuum_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("DatabaseMaintenance stopped")
    
    async def _backup_loop(self):
        """Daily backup loop."""
        # Run backup immediately on start
        await self._create_backup()
        
        while self._running:
            try:
                await asyncio.sleep(self.backup_interval_seconds)
                if self._running:
                    await self._create_backup()
                    await self._cleanup_old_backups()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Backup loop error: {e}")
                await asyncio.sleep(3600)  # Retry in 1 hour
    
    async def _vacuum_loop(self):
        """Weekly vacuum/optimize loop."""
        # Run vacuum immediately on start if enough time has passed
        await self._run_vacuum()
        
        while self._running:
            try:
                await asyncio.sleep(self.vacuum_interval_seconds)
                if self._running:
                    await self._run_vacuum()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Vacuum loop error: {e}")
                await asyncio.sleep(86400)  # Retry in 1 day
    
    async def _create_backup(self):
        """Create online SQLite backup."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"attendance_backup_{timestamp}.db"
        
        try:
            logger.info(f"Creating database backup: {backup_path}")
            
            # Use sqlite3 online backup API
            source_conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            dest_conn = sqlite3.connect(str(backup_path))
            
            try:
                source_conn.backup(dest_conn)
                dest_conn.close()
                source_conn.close()
                
                backup_size = backup_path.stat().st_size
                logger.info(f"Backup created: {backup_path} ({backup_size / (1024**2):.1f} MB)")
                self._last_backup = time.time()
                
            except Exception as e:
                dest_conn.close()
                source_conn.close()
                raise
                
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
    
    async def _cleanup_old_backups(self):
        """Remove backups older than max_backups."""
        try:
            backups = sorted(
                self.backup_dir.glob("attendance_backup_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            for old_backup in backups[self.max_backups:]:
                old_backup.unlink()
                logger.info(f"Removed old backup: {old_backup}")
                
        except Exception as e:
            logger.error(f"Backup cleanup failed: {e}")
    
    async def _run_vacuum(self):
        """Run incremental vacuum and optimize."""
        try:
            logger.info("Running database vacuum and optimize...")
            
            conn = sqlite3.connect(str(self.db_path))
            try:
                # Incremental vacuum (reclaim free pages)
                conn.execute("PRAGMA incremental_vacuum;")
                
                # Optimize query planner
                conn.execute("PRAGMA optimize;")
                
                # Analyze statistics
                conn.execute("ANALYZE;")
                
                conn.commit()
                logger.info("Database vacuum and optimize complete")
                self._last_vacuum = time.time()
                
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"Database vacuum failed: {e}")
    
    async def force_backup(self) -> Optional[Path]:
        """Force an immediate backup. Returns backup path or None on failure."""
        await self._create_backup()
        backups = sorted(self.backup_dir.glob("attendance_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        return backups[0] if backups else None
    
    async def force_vacuum(self):
        """Force an immediate vacuum."""
        await self._run_vacuum()


# Global instances
_retention_service: Optional[RetentionService] = None
_disk_watchdog: Optional[DiskWatchdog] = None
_db_maintenance: Optional[DatabaseMaintenance] = None


def get_retention_service(
    policies: Optional[List[RetentionPolicy]] = None,
    interval_seconds: float = 3600.0,
    attendance_db_path: str = "app/data/attendance.db",
) -> RetentionService:
    """Get or create the global retention service."""
    global _retention_service
    if _retention_service is None:
        _retention_service = RetentionService(policies, interval_seconds, attendance_db_path)
    return _retention_service


def get_disk_watchdog(
    watch_path: str = ".",
    check_interval_seconds: float = 60.0,
    warning_threshold_pct: float = 15.0,
    emergency_threshold_pct: float = 10.0,
    retention_service: Optional[RetentionService] = None,
    purge_callback: Optional[Callable[[float], None]] = None,
) -> DiskWatchdog:
    """Get or create the global disk watchdog."""
    global _disk_watchdog
    if _disk_watchdog is None:
        _disk_watchdog = DiskWatchdog(
            watch_path, check_interval_seconds, warning_threshold_pct,
            emergency_threshold_pct, retention_service, purge_callback
        )
    return _disk_watchdog


def get_db_maintenance(
    db_path: str = "app/data/attendance.db",
    backup_dir: str = "app/data/backups",
    backup_interval_hours: float = 24.0,
    vacuum_interval_days: int = 7,
    max_backups: int = 7,
) -> DatabaseMaintenance:
    """Get or create the global database maintenance."""
    global _db_maintenance
    if _db_maintenance is None:
        _db_maintenance = DatabaseMaintenance(
            db_path, backup_dir, backup_interval_hours, vacuum_interval_days, max_backups
        )
    return _db_maintenance


async def start_storage_services(
    retention_interval_seconds: float = 3600.0,
    disk_check_interval_seconds: float = 60.0,
    backup_interval_hours: float = 24.0,
    vacuum_interval_days: int = 7,
):
    """Start all storage lifecycle services."""
    retention = get_retention_service(interval_seconds=retention_interval_seconds)
    watchdog = get_disk_watchdog(
        check_interval_seconds=disk_check_interval_seconds,
        retention_service=retention,
    )
    db_maint = get_db_maintenance(
        backup_interval_hours=backup_interval_hours,
        vacuum_interval_days=vacuum_interval_days,
    )
    
    await retention.start()
    await watchdog.start()
    await db_maint.start()
    
    logger.info("All storage lifecycle services started")


async def stop_storage_services():
    """Stop all storage lifecycle services."""
    global _retention_service, _disk_watchdog, _db_maintenance
    
    if _retention_service:
        await _retention_service.stop()
        _retention_service = None
    
    if _disk_watchdog:
        await _disk_watchdog.stop()
        _disk_watchdog = None
    
    if _db_maintenance:
        await _db_maintenance.stop()
        _db_maintenance = None
    
    logger.info("All storage lifecycle services stopped")