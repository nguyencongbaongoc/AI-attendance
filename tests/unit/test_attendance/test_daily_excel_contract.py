"""
Phase 30 — Unit Tests for Daily Excel Export Contract.

Tests for DailyExportRequest, DailyExportResult, and export contract validation.
"""

import pytest
from datetime import datetime, date
from pathlib import Path

from app.attendance.daily_excel import (
    DailyExportRequest,
    DailyExportResult,
    DailyExcelExporter,
    create_daily_excel_exporter,
)


class TestDailyExportRequest:
    """Tests for DailyExportRequest contract."""

    def test_valid_request_creation(self):
        """Test creating a valid export request."""
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
            timezone="Asia/Bangkok",
            export_version="1.0",
        )
        assert request.date == date(2026, 8, 23)
        assert request.output_path == "/tmp/attendance_2026-08-23.xlsx"
        assert request.timezone == "Asia/Bangkok"
        assert request.export_version == "1.0"
        assert request.include_events_sheet is True
        assert request.include_provenance_sheet is True
        assert request.include_summary_sheet is True

    def test_request_with_optional_fields(self):
        """Test request with optional fields."""
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
            include_events_sheet=False,
            include_provenance_sheet=False,
            include_summary_sheet=False,
        )
        assert request.include_events_sheet is False
        assert request.include_provenance_sheet is False
        assert request.include_summary_sheet is False

    def test_request_defaults(self):
        """Test default values."""
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
        )
        assert request.timezone == "Asia/Bangkok"
        assert request.export_version == "1.0"
        assert request.timetable is None


class TestDailyExportResult:
    """Tests for DailyExportResult contract."""

    def test_success_result(self):
        """Test successful export result."""
        result = DailyExportResult(
            success=True,
            output_path="/tmp/attendance_2026-08-23.xlsx",
            records_processed=10,
            records_exported=8,
            sheets_created=["DAILY_ATTENDANCE", "EVENTS", "SUMMARY", "PROVENANCE"],
            export_id="EXPORT-abc123",
        )
        assert result.success is True
        assert result.output_path == "/tmp/attendance_2026-08-23.xlsx"
        assert result.records_processed == 10
        assert result.records_exported == 8
        assert len(result.sheets_created) == 4
        assert result.export_id == "EXPORT-abc123"
        assert result.error is None

    def test_failure_result(self):
        """Test failed export result."""
        result = DailyExportResult(
            success=False,
            error="Export failed: Invalid date",
            output_path="/tmp/attendance_2026-08-23.xlsx",
        )
        assert result.success is False
        assert result.error == "Export failed: Invalid date"
        assert result.output_path == "/tmp/attendance_2026-08-23.xlsx"
        assert result.records_processed == 0
        assert result.records_exported == 0
        assert result.sheets_created == []
        assert result.export_id is None


class TestDailyExcelExporter:
    """Tests for DailyExcelExporter."""

    def test_create_exporter(self):
        """Test creating exporter instance."""
        exporter = create_daily_excel_exporter()
        assert exporter is not None
        assert isinstance(exporter, DailyExcelExporter)
        exporter.close()

    def test_exporter_context_manager(self):
        """Test exporter as context manager."""
        with create_daily_excel_exporter() as exporter:
            assert exporter is not None
            assert isinstance(exporter, DailyExcelExporter)

    def test_validate_export_request_valid(self):
        """Test validation of valid request."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
        )
        error = exporter._validate_export_request(request)
        assert error is None
        exporter.close()

    def test_validate_export_request_missing_date(self):
        """Test validation fails for missing date."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=None,
            output_path="/tmp/attendance_2026-08-23.xlsx",
        )
        error = exporter._validate_export_request(request)
        assert error is not None
        assert "Date is required" in error
        exporter.close()

    def test_validate_export_request_missing_output_path(self):
        """Test validation fails for missing output path."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="",
        )
        error = exporter._validate_export_request(request)
        assert error is not None
        assert "Output path is required" in error
        exporter.close()

    def test_validate_export_request_relative_path(self):
        """Test validation fails for relative output path."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="attendance_2026-08-23.xlsx",
        )
        error = exporter._validate_export_request(request)
        assert error is not None
        assert "Output path must be absolute" in error
        exporter.close()

    def test_validate_export_request_wrong_extension(self):
        """Test validation fails for wrong file extension."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.csv",
        )
        error = exporter._validate_export_request(request)
        assert error is not None
        assert "Output path must have .xlsx extension" in error
        exporter.close()

    def test_generate_export_id_deterministic(self):
        """Test export ID generation is deterministic."""
        exporter = create_daily_excel_exporter()
        request = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
            export_version="1.0",
        )
        id1 = exporter._generate_export_id(request)
        id2 = exporter._generate_export_id(request)
        assert id1 == id2
        assert id1.startswith("EXPORT-")
        exporter.close()

    def test_generate_export_id_different_dates(self):
        """Test different dates produce different export IDs."""
        exporter = create_daily_excel_exporter()
        request1 = DailyExportRequest(
            date=date(2026, 8, 23),
            output_path="/tmp/attendance_2026-08-23.xlsx",
        )
        request2 = DailyExportRequest(
            date=date(2026, 8, 24),
            output_path="/tmp/attendance_2026-08-24.xlsx",
        )
        id1 = exporter._generate_export_id(request1)
        id2 = exporter._generate_export_id(request2)
        assert id1 != id2
        exporter.close()


class TestExcelFormatting:
    """Tests for Excel formatting constants."""

    def test_state_colors_defined(self):
        """Test that state colors are defined for all attendance states."""
        from app.attendance.daily_excel import STATE_COLORS
        from app.attendance.timetable import AttendanceState

        assert AttendanceState.PRESENT in STATE_COLORS
        assert AttendanceState.LATE in STATE_COLORS
        assert AttendanceState.LEFT in STATE_COLORS
        assert AttendanceState.ABSENT in STATE_COLORS
        assert AttendanceState.UNKNOWN in STATE_COLORS
        assert AttendanceState.EXPECTED in STATE_COLORS

    def test_state_colors_are_hex(self):
        """Test that state colors are valid hex color codes."""
        from app.attendance.daily_excel import STATE_COLORS

        for state, color in STATE_COLORS.items():
            assert color.startswith("#") or len(color) == 6
            # Should be valid hex
            int(color, 16)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])