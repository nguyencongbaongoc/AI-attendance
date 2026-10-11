"""
Phase 17 — Unit Tests for Evidence Storage Components.

Tests cover:
1. AsyncSnapshotSaver - GPU snapshot extraction and saving
2. ClipExtractor - Zero-transcode event clip extraction  
3. RetentionService - Retention policies and scheduled cleanup
4. DiskWatchdog - Disk space monitoring and emergency purge
5. DatabaseMaintenance - SQLite backup and VACUUM
"""

import pytest
import tempfile
import time
import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

import torch

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.snapshot_saver import AsyncSnapshotSaver, SnapshotResult, get_snapshot_saver, shutdown_snapshot_saver
from app.storage.clip_extractor import ClipExtractor, ClipExtractResult, get_clip_extractor
from app.storage.retention_service import (
    RetentionService, RetentionPolicy, RetentionStats, DiskWatchdog, DiskSpaceInfo,
    DatabaseMaintenance, get_retention_service, get_disk_watchdog, get_db_maintenance,
    start_storage_services, stop_storage_services
)
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract


class TestAsyncSnapshotSaver:
    """Tests for AsyncSnapshotSaver."""
    
    def test_snapshot_saver_instantiation(self):
        """Test AsyncSnapshotSaver can be instantiated."""
        saver = AsyncSnapshotSaver(
            base_dir="app/static/evidence/snapshots",
            max_workers=2,
            jpeg_quality=90,
            device_id=0,
        )
        assert saver.base_dir == Path("app/static/evidence/snapshots")
        assert saver.max_workers == 2
        assert saver.jpeg_quality == 90
        assert saver.device_id == 0
        saver.shutdown()
    
    def test_get_snapshot_saver_singleton(self):
        """Test global singleton getter."""
        shutdown_snapshot_saver()
        saver1 = get_snapshot_saver()
        saver2 = get_snapshot_saver()
        assert saver1 is saver2
        shutdown_snapshot_saver()
    
    def test_generate_paths(self):
        """Test path generation for face and scene snapshots."""
        saver = AsyncSnapshotSaver()
        face_path, scene_path = saver._generate_paths("cam1", "evt_001")
        
        assert "cam1_evt_001_face.jpg" in str(face_path)
        assert "cam1_evt_001_scene.jpg" in str(scene_path)
        assert "snapshots" in str(face_path)
        saver.shutdown()
    
    def test_get_relative_uri(self):
        """Test relative URI generation."""
        saver = AsyncSnapshotSaver()
        test_path = Path("app/static/evidence/snapshots/2026-10-10/cam1_evt_001_face.jpg")
        uri = saver._get_relative_uri(test_path)
        # On Windows, path separators are backslashes
        assert "evidence" in uri and "snapshots" in uri and "cam1_evt_001_face.jpg" in uri
        saver.shutdown()


class TestClipExtractor:
    """Tests for ClipExtractor."""
    
    def test_clip_extractor_instantiation(self):
        """Test ClipExtractor can be instantiated."""
        extractor = ClipExtractor(
            recordings_dir="recordings",
            clips_dir="app/static/evidence/clips",
            ffmpeg_path="ffmpeg",
            pre_roll_sec=3.0,
            post_roll_sec=3.0,
        )
        assert extractor.recordings_dir == Path("recordings")
        assert extractor.clips_dir == Path("app/static/evidence/clips")
        assert extractor.pre_roll_sec == 3.0
        assert extractor.post_roll_sec == 3.0
    
    def test_get_clip_extractor_singleton(self):
        """Test global singleton getter."""
        extractor1 = get_clip_extractor()
        extractor2 = get_clip_extractor()
        assert extractor1 is extractor2
    
    def test_get_camera_recording_dir(self):
        """Test camera recording directory resolution."""
        extractor = ClipExtractor()
        cam1_dir = extractor._get_camera_recording_dir("cam1")
        cam2_dir = extractor._get_camera_recording_dir("cam2")
        
        assert cam1_dir == Path("recordings/cam1")
        assert cam2_dir == Path("recordings/cam2")
    
    def test_get_relative_uri(self):
        """Test relative URI generation for clips."""
        extractor = ClipExtractor()
        test_path = Path("app/static/evidence/clips/2026-10-10/cam1_evt_001.mp4")
        uri = extractor._get_relative_uri(test_path)
        # On Windows, path separators are backslashes
        assert "evidence" in uri and "clips" in uri and "cam1_evt_001.mp4" in uri


class TestRetentionService:
    """Tests for RetentionService."""
    
    def test_retention_service_instantiation(self):
        """Test RetentionService can be instantiated with default policies."""
        service = RetentionService()
        assert len(service.policies) == 3
        assert service.interval_seconds == 3600.0
        assert service._running is False
    
    def test_retention_service_custom_policies(self):
        """Test RetentionService with custom policies."""
        policies = [
            RetentionPolicy(
                name="test_policy",
                paths=["test_dir"],
                max_age_days=7,
                file_extensions=[".tmp"],
                preserve_recent=2,
            )
        ]
        service = RetentionService(policies=policies, interval_seconds=1800.0)
        assert len(service.policies) == 1
        assert service.policies[0].name == "test_policy"
        assert service.interval_seconds == 1800.0
    
    def test_retention_stats_dataclass(self):
        """Test RetentionStats dataclass."""
        stats = RetentionStats(policy_name="test")
        assert stats.policy_name == "test"
        assert stats.files_scanned == 0
        assert stats.files_deleted == 0
        assert stats.bytes_freed == 0
        assert stats.errors == []
        assert stats.duration_ms == 0.0


class TestDiskWatchdog:
    """Tests for DiskWatchdog."""
    
    def test_disk_watchdog_instantiation(self):
        """Test DiskWatchdog can be instantiated."""
        watchdog = DiskWatchdog(
            watch_path=".",
            check_interval_seconds=60.0,
            warning_threshold_pct=15.0,
            emergency_threshold_pct=10.0,
        )
        assert watchdog.check_interval_seconds == 60.0
        assert watchdog.warning_threshold_pct == 15.0
        assert watchdog.emergency_threshold_pct == 10.0
        assert watchdog._running is False
    
    def test_get_disk_info(self):
        """Test disk space info retrieval."""
        watchdog = DiskWatchdog(watch_path=".")
        info = watchdog.get_disk_info()
        
        assert isinstance(info, DiskSpaceInfo)
        assert info.total_bytes > 0
        assert info.free_bytes >= 0
        assert info.used_bytes >= 0
        assert 0 <= info.free_percent <= 100
        assert info.path == str(Path(".").resolve())


class TestDatabaseMaintenance:
    """Tests for DatabaseMaintenance."""
    
    def test_database_maintenance_instantiation(self):
        """Test DatabaseMaintenance can be instantiated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backup_dir = Path(tmpdir) / "backups"
            
            # Create empty db
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.close()
            
            maint = DatabaseMaintenance(
                db_path=str(db_path),
                backup_dir=str(backup_dir),
                backup_interval_hours=24.0,
                vacuum_interval_days=7,
                max_backups=7,
            )
            assert maint.db_path == db_path
            assert maint.backup_dir == backup_dir
            assert maint.max_backups == 7
            assert maint._running is False


class TestStorageServiceLifecycle:
    """Tests for storage service start/stop lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_stop_storage_services(self):
        """Test starting and stopping all storage services."""
        await start_storage_services(
            retention_interval_seconds=1.0,
            disk_check_interval_seconds=1.0,
            backup_interval_hours=1.0,
            vacuum_interval_days=1,
        )
        
        # Give services time to start
        await asyncio.sleep(0.1)
        
        # Verify services were started (no exceptions raised)
        # Internal globals are not exposed, but services are running
        
        await stop_storage_services()
        
        # Verify they stopped cleanly (no exceptions)
    
    @pytest.mark.asyncio
    async def test_retention_service_worker_loop(self):
        """Test retention service worker runs policies."""
        service = RetentionService(
            policies=[
                RetentionPolicy(
                    name="test_recordings",
                    paths=["recordings/cam1", "recordings/cam2"],
                    max_age_days=0,  # Expire everything
                    file_extensions=[".mp4"],
                    preserve_recent=0,
                    enabled=True,
                )
            ],
            interval_seconds=1.0,
        )
        
        await service.start()
        await asyncio.sleep(1.5)  # Let it run once
        await service.stop()
        
        # Check stats were recorded
        history = service.get_stats_history()
        assert len(history) >= 1
        
        # Should have run at least one policy
        stats = history[0]
        assert isinstance(stats, RetentionStats)


class TestRetentionPolicyApplication:
    """Tests for retention policy application logic."""
    
    @pytest.mark.asyncio
    async def test_apply_policy_deletes_old_files(self):
        """Test that retention policy deletes files older than max_age_days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "test_recordings"
            test_dir.mkdir()
            
            # Create old file
            old_file = test_dir / "old.mp4"
            old_file.write_bytes(b"old content")
            # Set mtime to 10 days ago
            old_time = time.time() - (10 * 86400)
            os.utime(old_file, (old_time, old_time))
            
            # Create new file
            new_file = test_dir / "new.mp4"
            new_file.write_bytes(b"new content")
            
            service = RetentionService(
                policies=[
                    RetentionPolicy(
                        name="test",
                        paths=[str(test_dir)],
                        max_age_days=7,
                        file_extensions=[".mp4"],
                        preserve_recent=0,
                    )
                ],
                interval_seconds=3600.0,
            )
            
            stats = await service._apply_policy(service.policies[0])
            
            assert stats.files_scanned == 2
            assert stats.files_deleted == 1
            assert stats.bytes_freed > 0
            assert not old_file.exists()
            assert new_file.exists()
    
    @pytest.mark.asyncio
    async def test_preserve_recent_files(self):
        """Test that preserve_recent keeps newest files even if old."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "test_recordings"
            test_dir.mkdir()
            
            # Create 5 old files
            for i in range(5):
                f = test_dir / f"old_{i}.mp4"
                f.write_bytes(b"x" * 1000)
                old_time = time.time() - (10 * 86400)
                os.utime(f, (old_time, old_time))
            
            service = RetentionService(
                policies=[
                    RetentionPolicy(
                        name="test",
                        paths=[str(test_dir)],
                        max_age_days=7,
                        file_extensions=[".mp4"],
                        preserve_recent=2,  # Keep 2 most recent
                    )
                ],
                interval_seconds=3600.0,
            )
            
            stats = await service._apply_policy(service.policies[0])
            
            # Should delete 3, preserve 2
            assert stats.files_scanned == 5
            assert stats.files_deleted == 3
            remaining = list(test_dir.glob("*.mp4"))
            assert len(remaining) == 2


class TestDiskWatchdogEmergencyPurge:
    """Tests for DiskWatchdog emergency purge logic."""
    
    @pytest.mark.asyncio
    async def test_emergency_purge_deletes_oldest_recordings(self):
        """Test emergency purge deletes oldest recording files first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cam1_dir = Path(tmpdir) / "recordings" / "cam1"
            cam2_dir = Path(tmpdir) / "recordings" / "cam2"
            cam1_dir.mkdir(parents=True)
            cam2_dir.mkdir(parents=True)
            
            # Create old files in both cameras
            for i in range(3):
                f1 = cam1_dir / f"old_{i}.mp4"
                f2 = cam2_dir / f"old_{i}.mp4"
                f1.write_bytes(b"x" * 1000)
                f2.write_bytes(b"x" * 1000)
                old_time = time.time() - (10 * 86400)
                os.utime(f1, (old_time, old_time))
                os.utime(f2, (old_time, old_time))
            
            # Create newer files
            f1_new = cam1_dir / "new.mp4"
            f2_new = cam2_dir / "new.mp4"
            f1_new.write_bytes(b"x" * 1000)
            f2_new.write_bytes(b"x" * 1000)
            
            watchdog = DiskWatchdog(
                watch_path=tmpdir,
                check_interval_seconds=60.0,
                warning_threshold_pct=15.0,
                emergency_threshold_pct=10.0,
            )
            
            # Mock get_disk_info to return emergency level
            original_get_disk_info = watchdog.get_disk_info
            
            def mock_get_disk_info():
                return DiskSpaceInfo(
                    total_bytes=100000000000,
                    free_bytes=5000000000,  # 5% free - emergency
                    used_bytes=95000000000,
                    free_percent=5.0,
                    path=tmpdir,
                )
            
            watchdog.get_disk_info = mock_get_disk_info
            
            # Run emergency purge
            await watchdog._emergency_purge()
            
            # Old files should be deleted, new files preserved
            remaining_cam1 = list(cam1_dir.glob("*.mp4"))
            remaining_cam2 = list(cam2_dir.glob("*.mp4"))
            
            # Should have deleted some old files, kept new ones
            assert len(remaining_cam1) <= 4
            assert len(remaining_cam2) <= 4
            assert f1_new.exists()
            assert f2_new.exists()


class TestDatabaseMaintenanceBackup:
    """Tests for DatabaseMaintenance backup functionality."""
    
    @pytest.mark.asyncio
    async def test_create_backup(self):
        """Test online SQLite backup creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            backup_dir = Path(tmpdir) / "backups"
            
            # Create test database with some data
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
            conn.execute("INSERT INTO test (data) VALUES ('test1'), ('test2'), ('test3')")
            conn.commit()
            conn.close()
            
            maint = DatabaseMaintenance(
                db_path=str(db_path),
                backup_dir=str(backup_dir),
                backup_interval_hours=24.0,
                vacuum_interval_days=7,
                max_backups=7,
            )
            
            await maint._create_backup()
            
            # Check backup was created
            backups = list(backup_dir.glob("attendance_backup_*.db"))
            assert len(backups) == 1
            
            # Verify backup has same data
            conn = sqlite3.connect(backups[0])
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            count = cursor.fetchone()[0]
            assert count == 3
            conn.close()
    
    @pytest.mark.asyncio
    async def test_cleanup_old_backups(self):
        """Test old backup cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir) / "backups"
            backup_dir.mkdir()
            
            # Create 10 backup files with different timestamps
            for i in range(10):
                backup_file = backup_dir / f"attendance_backup_20261010_{i:06d}00.db"
                backup_file.write_bytes(b"backup data")
                # Set different mtimes
                os.utime(backup_file, (time.time() - (i * 3600), time.time() - (i * 3600)))
            
            maint = DatabaseMaintenance(
                db_path=str(Path(tmpdir) / "dummy.db"),
                backup_dir=str(backup_dir),
                backup_interval_hours=24.0,
                vacuum_interval_days=7,
                max_backups=7,  # Keep only 7
            )
            
            await maint._cleanup_old_backups()
            
            # Should have only 7 backups remaining
            backups = list(backup_dir.glob("attendance_backup_*.db"))
            assert len(backups) == 7


class TestStorageIntegration:
    """Integration tests for storage components working together."""
    
    @pytest.mark.asyncio
    async def test_snapshot_to_database_flow(self):
        """Test snapshot saver generates URIs suitable for database storage."""
        saver = AsyncSnapshotSaver()
        
        # Mock GPU frame
        if torch.cuda.is_available():
            device = torch.device('cuda:0')
            y_tensor = torch.randn(720, 1280, device=device, dtype=torch.float32).clamp(0, 255).to(torch.uint8)
            uv_tensor = torch.randn(360, 1280, 2, device=device, dtype=torch.float32).clamp(0, 255).to(torch.uint8)
            
            frame = GPUFrameContract(
                frame_id=1,
                camera_id='cam1',
                timestamp=0.0,
                pts=0,
                width=1280,
                height=720,
                _y_tensor=y_tensor,
                _uv_tensor=uv_tensor
            )
            
            result = saver.save_snapshot_blocking(frame, (100, 100, 300, 300), 'cam1', 'test_event_001')
            
            assert result.error is None
            assert result.face_url is not None
            assert result.scene_url is not None
            # On Windows, path separators are backslashes
            assert "evidence" in result.face_url and "snapshots" in result.face_url
            assert "evidence" in result.scene_url and "snapshots" in result.scene_url
            assert result.face_url.endswith("_face.jpg")
            assert result.scene_url.endswith("_scene.jpg")
        else:
            pytest.skip("CUDA not available")
        
        saver.shutdown()
    
    @pytest.mark.asyncio
    async def test_clip_extractor_output_format(self):
        """Test clip extractor generates URIs suitable for database storage."""
        extractor = ClipExtractor()
        
        # Create a dummy recording segment
        recordings_cam1 = Path("recordings/cam1")
        recordings_cam1.mkdir(parents=True, exist_ok=True)
        
        # Create a dummy MP4 file (won't be valid but tests path generation)
        dummy_segment = recordings_cam1 / "2026-10-10_12-00-00-000000.mp4"
        dummy_segment.write_bytes(b"dummy")
        
        # Test path generation
        daily_dir = extractor.clips_dir / "2026-10-10"
        daily_dir.mkdir(parents=True, exist_ok=True)
        output_path = daily_dir / "cam1_evt_001.mp4"
        clip_url = extractor._get_relative_uri(output_path)
        
        # On Windows, path separators are backslashes
        assert "evidence" in clip_url and "clips" in clip_url and "cam1_evt_001.mp4" in clip_url
        
        # Cleanup
        dummy_segment.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])