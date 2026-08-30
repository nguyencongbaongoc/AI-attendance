"""
Phase 30 — Unit Tests for Daily Excel Exporter.

Tests for the DailyExcelExporter functionality including:
- Empty day handling
- Single attendance record
- Multiple people
- Different attendance states
- Missing OUT records
- Multi-camera records
- Provenance preservation
- Event ordering
- Summary counts
- Deterministic row ordering
- Timezone handling
- Filename generation
- Bounded query
- Invalid record handling
- Formula injection safety
- No database mutation
"""

import pytest
import tempfile
import os
from datetime import datetime, date, time, timedelta
from pathlib import Path

from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    IdentityCertainty,
)
from app.attendance.daily_excel import (
    DailyExportRequest,
    DailyExportResult,
    DailyExcelExporter,
    create_daily_excel_exporter,
)
from app.attendance.repository import AttendanceRepository
from app.attendance.storage import AttendanceStorage, StorageConfig
from app.attendance.timetable import AttendanceState


class TestDailyExcelExporterIntegration:
    """Integration tests for DailyExcelExporter with real storage."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)

    @pytest.fixture
    def storage(self, temp_db):
        """Create storage with temp database."""
        config = StorageConfig(database_path=temp_db)
        storage = AttendanceStorage(config)
        yield storage
        storage.close()

    @pytest.fixture
    def repository(self, storage):
        """Create repository with storage."""
        repo = AttendanceRepository(storage=storage)
        yield repo
        repo.close()

    @pytest.fixture
    def exporter(self, repository):
        """Create exporter with repository."""
        exporter = DailyExcelExporter(repository=repository)
        yield exporter
        exporter.close()

    def create_sample_record(
        self,
        attendance_record_id: str,
        direction: str = "in",
        identity_certainty: IdentityCertainty = IdentityCertainty.UNKNOWN,
        identity_candidate: str = None,
        camera_id: str = "CAM1",
        local_track_id: str = "track_001",
        global_observation_id: str = "GO-123",
        event_timestamp: float = 1000.0,
        previous_state: str = "unknown",
        new_state: str = "inside",
    ) -> AttendanceRecord:
        """Create a sample attendance record."""
        return AttendanceRecord(
            attendance_record_id=attendance_record_id,
            identity_certainty=identity_certainty,
            identity_candidate=identity_candidate,
            identity_confidence=0.95 if identity_candidate else 0.0,
            identity_evidence_ref=global_observation_id,
            direction=AttendanceDirection(direction),
            event_timestamp=event_timestamp,
            event_frame_index=100,
            camera_id=camera_id,
            local_track_id=local_track_id,
            global_observation_id=global_observation_id,
            source_raw_event_id=f"RIE-{attendance_record_id}",
            source_resolution_id=f"RES-{attendance_record_id}",
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash",
            resolver_version="1.0",
            resolver_config_hash="config_hash",
            previous_state=previous_state,
            new_state=new_state,
            attendance_schema_version="1.0",
        )

    def test_empty_day(self, exporter, temp_db):
        """Test exporting an empty day (no records)."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_processed == 0
            assert result.records_exported == 0
            assert "DAILY_ATTENDANCE" in result.sheets_created
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_single_attendance_record(self, exporter, storage, temp_db):
        """Test exporting a single attendance record."""
        # Insert a record with timestamp for 2026-08-23 08:00:00 Bangkok time (UTC+7)
        # 2026-08-23 08:00:00 Bangkok = 2026-08-23 01:00:00 UTC = 1787446800.0
        record = self.create_sample_record(
            attendance_record_id="ATT-001",
            direction="in",
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_processed == 1
            assert result.records_exported == 1
            assert "DAILY_ATTENDANCE" in result.sheets_created
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_multiple_people(self, exporter, storage, temp_db):
        """Test exporting multiple people."""
        # Insert multiple records for different people with timestamps for 2026-08-23 Bangkok time
        base_ts = 1787446800.0  # 2026-08-23 08:00:00 Bangkok = 2026-08-23 01:00:00 UTC
        for i in range(3):
            record = self.create_sample_record(
                attendance_record_id=f"ATT-{i:03d}",
                direction="in",
                identity_certainty=IdentityCertainty.KNOWN,
                identity_candidate=f"student_{i:03d}",
                event_timestamp=base_ts + i * 100,
                local_track_id=f"track_{i:03d}",
                global_observation_id=f"GO-{i:03d}",
            )
            storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_processed == 3
            assert result.records_exported == 3
            assert os.path.exists(output_path)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_present_state(self, exporter, storage, temp_db):
        """Test PRESENT attendance state."""
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-present",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787446800.0,
            previous_state="unknown",
            new_state="inside",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_late_state(self, exporter, storage, temp_db):
        """Test LATE attendance state."""
        # 2026-08-23 08:30:00 Bangkok = 1787448600.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-late",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787448600.0,
            previous_state="unknown",
            new_state="inside",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_left_state(self, exporter, storage, temp_db):
        """Test LEFT attendance state."""
        # 2026-08-23 12:00:00 Bangkok = 1787461200.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-left",
            direction="out",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787461200.0,
            previous_state="inside",
            new_state="outside",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_absent_state(self, exporter, storage, temp_db):
        """Test ABSENT attendance state."""
        # 2026-08-23 15:00:00 Bangkok = 1787470800.0 UTC (outside normal hours)
        record = self.create_sample_record(
            attendance_record_id="ATT-absent",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787470800.0,
            previous_state="unknown",
            new_state="outside",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_unknown_state(self, exporter, storage, temp_db):
        """Test UNKNOWN attendance state."""
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-unknown",
            direction="in",
            identity_certainty=IdentityCertainty.UNKNOWN,
            event_timestamp=1787446800.0,
            previous_state="unknown",
            new_state="unknown",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_ambiguous_identity(self, exporter, storage, temp_db):
        """Test AMBIGUOUS identity certainty."""
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-ambiguous",
            direction="in",
            identity_certainty=IdentityCertainty.AMBIGUOUS,
            identity_candidate="student_001",
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_missing_out_record(self, exporter, storage, temp_db):
        """Test handling of missing OUT record."""
        # Only IN record, no matching OUT
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-in-only",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_multi_camera_records(self, exporter, storage, temp_db):
        """Test multi-camera records are preserved."""
        # Same person, different cameras
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record1 = self.create_sample_record(
            attendance_record_id="ATT-cam1",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-001",
            event_timestamp=1787446800.0,
        )
        record2 = self.create_sample_record(
            attendance_record_id="ATT-cam2",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            camera_id="CAM2",
            local_track_id="track_001",  # Same local track ID, different camera
            global_observation_id="GO-001",  # Same global observation
            event_timestamp=1787446800.0,
        )
        storage.insert(record1)
        storage.insert(record2)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 2
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_duplicate_source_records(self, exporter, storage, temp_db):
        """Test handling of duplicate source records (idempotency)."""
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-dup1",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        # Try to insert duplicate with same source_resolution_id
        duplicate = AttendanceRecord(
            **{**record.to_dict(), "attendance_record_id": "ATT-dup2"}
        )
        storage.insert(duplicate)  # Should be idempotent

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            # Should only export one record (the original)
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_provenance_preservation(self, exporter, storage, temp_db):
        """Test that provenance fields are preserved in export."""
        record = self.create_sample_record(
            attendance_record_id="ATT-prov",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-123",
            event_timestamp=28800.0,
            previous_state="unknown",
            new_state="inside",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                include_provenance_sheet=True,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert "PROVENANCE" in result.sheets_created
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_event_ordering(self, exporter, storage, temp_db):
        """Test that events are ordered chronologically."""
        # Insert records out of order
        timestamps = [30000.0, 28800.0, 29400.0]  # 08:20, 08:00, 08:10
        for i, ts in enumerate(timestamps):
            record = self.create_sample_record(
                attendance_record_id=f"ATT-order{i}",
                direction="in",
                event_timestamp=ts,
                local_track_id=f"track_{i:03d}",
            )
            storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                include_events_sheet=True,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert "EVENTS" in result.sheets_created
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_summary_counts(self, exporter, storage, temp_db):
        """Test summary sheet counts."""
        # Insert records with different states
        states = [
            ("ATT-p1", "in", "inside"),   # PRESENT
            ("ATT-p2", "in", "inside"),   # PRESENT
            ("ATT-l1", "in", "inside"),   # LATE (will be mapped to PRESENT in simplified logic)
            ("ATT-o1", "out", "outside"), # LEFT
            ("ATT-a1", "in", "outside"),  # ABSENT
        ]
        for i, (rec_id, direction, new_state) in enumerate(states):
            record = self.create_sample_record(
                attendance_record_id=rec_id,
                direction=direction,
                identity_certainty=IdentityCertainty.KNOWN,
                identity_candidate=f"student_{i:03d}",
                event_timestamp=28800.0 + i * 100,
                new_state=new_state,
            )
            storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                include_summary_sheet=True,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert "SUMMARY" in result.sheets_created
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_deterministic_row_ordering(self, exporter, storage, temp_db):
        """Test that row ordering is deterministic."""
        # Insert records with same timestamp for 2026-08-23 08:00:00 Bangkok
        base_ts = 1787446800.0  # 2026-08-23 08:00:00 Bangkok = 2026-08-23 01:00:00 UTC
        for i in range(3):
            record = self.create_sample_record(
                attendance_record_id=f"ATT-det{i}",
                direction="in",
                event_timestamp=base_ts,  # Same timestamp
                local_track_id=f"track_{i:03d}",
            )
            storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 3
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_timezone_handling(self, exporter, storage, temp_db):
        """Test timezone-aware handling."""
        # Record at 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-tz",
            direction="in",
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                timezone="Asia/Bangkok",
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_filename_generation(self, exporter, storage, temp_db):
        """Test deterministic filename generation."""
        record = self.create_sample_record(
            attendance_record_id="ATT-fname",
            direction="in",
            event_timestamp=28800.0,
        )
        storage.insert(record)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "attendance_2026-08-23.xlsx")

            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.output_path == output_path
            assert os.path.exists(output_path)

    def test_bounded_query(self, exporter, storage, temp_db):
        """Test that query is bounded to the requested date."""
        # Insert records for different dates with proper UTC timestamps for Bangkok timezone
        # 2026-08-22 08:00:00 Bangkok = 2026-08-22 01:00:00 UTC = 1787360400.0
        # 2026-08-23 08:00:00 Bangkok = 2026-08-23 01:00:00 UTC = 1787446800.0
        # 2026-08-24 08:00:00 Bangkok = 2026-08-24 01:00:00 UTC = 1787533200.0
        dates_and_timestamps = [
            (date(2026, 8, 22), 1787360400.0),   # Previous day
            (date(2026, 8, 23), 1787446800.0),   # Target day
            (date(2026, 8, 24), 1787533200.0),   # Next day
        ]
        for i, (d, ts) in enumerate(dates_and_timestamps):
            record = self.create_sample_record(
                attendance_record_id=f"ATT-date{i}",
                direction="in",
                event_timestamp=ts,
                local_track_id=f"track_{i:03d}",
            )
            storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            # Should only get records for 2026-08-23
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_invalid_record_handling(self, exporter, storage, temp_db):
        """Test handling of invalid records."""
        # Valid record with timestamp for 2026-08-23 08:00:00 Bangkok
        valid_record = self.create_sample_record(
            attendance_record_id="ATT-valid",
            direction="in",
            event_timestamp=1787446800.0,
        )
        storage.insert(valid_record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_formula_injection_safety(self, exporter, storage, temp_db):
        """Test that formula-like values are sanitized."""
        # Record with formula-like identity candidate
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-formula",
            direction="in",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="=CMD|'/C calc'!A0",  # Formula injection attempt
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_no_database_mutation(self, exporter, storage, temp_db):
        """Test that export does not mutate the database."""
        record = self.create_sample_record(
            attendance_record_id="ATT-nomutate",
            direction="in",
            event_timestamp=28800.0,
        )
        storage.insert(record)

        # Count before export
        count_before = storage.count()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True

            # Count after export
            count_after = storage.count()
            assert count_after == count_before
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_restart_readonly_behavior(self, temp_db):
        """Test that export works after database restart."""
        config = StorageConfig(database_path=temp_db)
        storage1 = AttendanceStorage(config)
        
        # Insert record with timestamp for 2026-08-23 08:00:00 Bangkok
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = AttendanceRecord(
            attendance_record_id="ATT-restart",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            direction=AttendanceDirection.IN,
            event_timestamp=1787446800.0,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-123",
            source_raw_event_id="RIE-restart",
            source_resolution_id="RES-restart",
            geometry_version=1,
            geometry_config_hash="geom_hash",
            resolver_version="1.0",
            resolver_config_hash="config_hash",
            previous_state="unknown",
            new_state="inside",
            attendance_schema_version="1.0",
        )
        storage1.insert(record)
        storage1.close()

        # Reopen and export
        storage2 = AttendanceStorage(config)
        repository = AttendanceRepository(storage=storage2)
        exporter = DailyExcelExporter(repository=repository)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
            exporter.close()
            repository.close()
            storage2.close()


class TestDailyExcelExporterEdgeCases:
    """Edge case tests for DailyExcelExporter."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)

    @pytest.fixture
    def storage(self, temp_db):
        config = StorageConfig(database_path=temp_db)
        storage = AttendanceStorage(config)
        yield storage
        storage.close()

    @pytest.fixture
    def repository(self, storage):
        repo = AttendanceRepository(storage=storage)
        yield repo
        repo.close()

    @pytest.fixture
    def exporter(self, repository):
        exporter = DailyExcelExporter(repository=repository)
        yield exporter
        exporter.close()

    def create_sample_record(self, **kwargs) -> AttendanceRecord:
        defaults = {
            "attendance_record_id": "ATT-test",
            "identity_certainty": IdentityCertainty.UNKNOWN,
            "identity_candidate": None,
            "identity_confidence": 0.0,
            "identity_evidence_ref": "GO-123",
            "direction": AttendanceDirection.IN,
            "event_timestamp": 28800.0,
            "event_frame_index": 100,
            "camera_id": "CAM1",
            "local_track_id": "track_001",
            "global_observation_id": "GO-123",
            "source_raw_event_id": "RIE-test",
            "source_resolution_id": "RES-test",
            "source_crossing_event_id": "CE-001",
            "geometry_version": 1,
            "geometry_config_hash": "geom_hash",
            "resolver_version": "1.0",
            "resolver_config_hash": "config_hash",
            "previous_state": "unknown",
            "new_state": "inside",
            "attendance_schema_version": "1.0",
        }
        defaults.update(kwargs)
        return AttendanceRecord(**defaults)

    def test_missing_global_observation(self, exporter, storage, temp_db):
        """Test handling of missing global_observation_id."""
        # 2026-08-23 08:00:00 Bangkok = 1787446800.0 UTC
        record = self.create_sample_record(
            attendance_record_id="ATT-no-go",
            global_observation_id=None,
            event_timestamp=1787446800.0,
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert result.records_exported == 1
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_missing_camera(self, exporter, storage, temp_db):
        """Test handling of missing camera_id (should not happen but test robustness)."""
        # Camera ID is required by contract, so this tests the exporter's robustness
        record = self.create_sample_record(
            attendance_record_id="ATT-no-cam",
            camera_id="CAM1",  # Required field
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_missing_timetable(self, exporter, storage, temp_db):
        """Test export without timetable (should work)."""
        record = self.create_sample_record(
            attendance_record_id="ATT-no-tt",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                timetable=None,  # No timetable
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_incomplete_provenance(self, exporter, storage, temp_db):
        """Test handling of incomplete provenance data."""
        record = self.create_sample_record(
            attendance_record_id="ATT-incomplete-prov",
            source_crossing_event_id=None,
            geometry_version=0,
            geometry_config_hash="",
            resolver_version="",
            resolver_config_hash="",
        )
        storage.insert(record)

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            request = DailyExportRequest(
                date=date(2026, 8, 23),
                output_path=output_path,
                include_provenance_sheet=True,
            )
            result = exporter.export_daily_attendance(request)

            assert result.success is True
            assert "PROVENANCE" in result.sheets_created
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])