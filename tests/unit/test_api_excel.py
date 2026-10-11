"""
Phase 44.X.4-R3.4-FIX — Backend tests for Excel API integration.

Verifies the Excel endpoints expose real XLSX file metadata, exact-match
download/delete, and the POST endpoint produces a real workbook on disk.

Run with:
  python -m pytest tests/unit/test_api_excel.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.attendance.daily_excel import DailyExcelExporter
from app.attendance.repository import AttendanceRepository
from app.attendance.storage import AttendanceStorage, StorageConfig


@pytest.fixture
def tmp_exports_dir(tmp_path):
    """Patch the canonical exports directory to a tmp path."""
    return tmp_path / "exports"


@pytest.fixture
def client(tmp_exports_dir):
    """Create a TestClient with the excel endpoints mounted and tmp exports dir."""
    from app.api import excel as excel_module

    # Reset the global exporter so the patched exports_dir is used cleanly
    excel_module._exporter = None

    def patched_exports_dir():
        tmp_exports_dir.mkdir(parents=True, exist_ok=True)
        return tmp_exports_dir

    # Patch get_exports_dir at module level
    with patch.object(excel_module, "get_exports_dir", side_effect=patched_exports_dir), \
         patch.object(excel_module, "get_timetable", return_value=None):
        # Import the routers lazily after patching
        from app.api.excel import router
        from app.api.health import router as health_router
        from app.api.attendance import router as attendance_router

        from fastapi import FastAPI

        app = FastAPI()
        for r in [health_router, attendance_router, router]:
            for route in r.routes:
                app.router.routes.append(route)

        yield TestClient(app)


@pytest.fixture
def real_export_file(tmp_exports_dir):
    """Create a real XLSX file in the canonical exports dir using DailyExcelExporter."""
    tmp_exports_dir.mkdir(parents=True, exist_ok=True)

    # Build a real exporter with a temp DB (empty -> zero records but real file)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        config = StorageConfig(database_path=db_path)
        storage = AttendanceStorage(config)
        repository = AttendanceRepository(storage=storage)
        exporter = DailyExcelExporter(repository=repository)

        target_date = "2026-09-02"
        output_path = tmp_exports_dir / f"daily_{target_date.replace('-', '')}.xlsx"
        from datetime import datetime
        from app.attendance.daily_excel import DailyExportRequest

        result = exporter.export_daily_attendance(
            DailyExportRequest(
                date=datetime.strptime(target_date, "%Y-%m-%d").date(),
                output_path=str(output_path),
                timezone="Asia/Bangkok",
                export_version="1.0",
                include_events_sheet=True,
                include_provenance_sheet=True,
                include_summary_sheet=True,
            )
        )

        assert result.success is True
        assert output_path.exists()

        repository.close()
        storage.close()
        yield {
            "export_id": "daily_20260902",  # filename without .xlsx
            "file_path": output_path,
            "expected_sheets": result.sheets_created,
        }
    finally:
        # Cleanup DB
        for suffix in ["", "-wal", "-shm"]:
            p = db_path + suffix
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


# ============================================================
# Tests
# ============================================================


class TestExcelListEndpoint:
    def test_list_returns_real_metadata(self, client, real_export_file):
        response = client.get("/api/v1/excel/exports")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "exports" in data
        assert len(data["exports"]) == 1

        entry = data["exports"][0]
        assert entry["export_id"] == real_export_file["export_id"]
        assert entry["file_path"] == str(real_export_file["file_path"])
        assert entry["record_count"] == 0  # empty DB
        # sheets must be from real workbook, not the hardcoded four
        assert entry["sheets_created"] == real_export_file["expected_sheets"]
        assert "DAILY_ATTENDANCE" in entry["sheets_created"]
        # created_at derived from filesystem mtime, not random
        assert entry["created_at"].endswith("Z")

    def test_list_empty_when_no_exports(self, client):
        response = client.get("/api/v1/excel/exports")
        assert response.status_code == 200
        assert response.json() == {"exports": []}


class TestExcelDownloadEndpoint:
    def test_download_returns_real_xlsx(self, client, real_export_file):
        eid = real_export_file["export_id"]
        response = client.get(f"/api/v1/excel/export/{eid}/download")
        assert response.status_code == 200
        # Real XLSX content (zip magic 'PK')
        body = response.content
        assert body[:2] == b"PK"

    def test_download_nonexistent_returns_404(self, client):
        response = client.get("/api/v1/excel/export/does-not-exist/download")
        assert response.status_code == 404


class TestExcelDeleteEndpoint:
    def test_delete_removes_exact_export(self, client, real_export_file):
        eid = real_export_file["export_id"]
        file_path = real_export_file["file_path"]
        assert file_path.exists()

        response = client.delete(f"/api/v1/excel/export/{eid}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("success") is True

        assert not file_path.exists()

        # list endpoint must no longer contain it
        listing = client.get("/api/v1/excel/exports").json()
        assert all(item["export_id"] != eid for item in listing["exports"])

    def test_delete_nonexistent_returns_404(self, client):
        response = client.delete("/api/v1/excel/export/ghost-id")
        assert response.status_code == 404

    def test_similar_export_ids_do_not_collide(self, client, tmp_exports_dir):
        """Two files with overlapping substrings must not match each other's IDs."""
        tmp_exports_dir.mkdir(parents=True, exist_ok=True)
        # Create two files whose names share a substring
        a = tmp_exports_dir / "daily_20260902.xlsx"
        b = tmp_exports_dir / "daily_202609020_extra.xlsx"
        a.write_bytes(b"PK")
        b.write_bytes(b"PK")

        # Deleting 'daily_20260902' must NOT delete 'daily_202609020_extra'
        response = client.delete("/api/v1/excel/export/daily_20260902")
        assert response.status_code == 200
        assert not a.exists()
        assert b.exists()


class TestExcelPostEndpoint:
    def test_post_writes_real_xlsx(self, client, tmp_exports_dir):
        target_date = "2026-09-01"
        response = client.post(
            "/api/v1/excel/export/daily",
            json={
                "date": target_date,
                "timezone": "Asia/Bangkok",
                "export_version": "1.0",
                "include_events_sheet": True,
                "include_provenance_sheet": True,
                "include_summary_sheet": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # export_id is the deterministic exporter ID
        assert body["export_id"].startswith("EXPORT-")
        # file_path is absolute
        assert os.path.isabs(body["file_path"])
        # sheets_created is from real workbook
        assert "DAILY_ATTENDANCE" in body["sheets_created"]
        # success=True
        assert body["success"] is True
        # The XLSX file must exist on disk
        assert Path(body["file_path"]).exists()
        # After creation, list endpoint must include it
        listing = client.get("/api/v1/excel/exports").json()
        # New file is daily_20260901.xlsx, export_id is the filename stem
        assert any(item["export_id"] == "daily_20260901" for item in listing["exports"])