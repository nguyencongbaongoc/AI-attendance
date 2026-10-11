"""
Phase 41A — Excel Export API Endpoints.

REST endpoints for daily Excel export generation and management.
Integrates with existing DailyExcelExporter.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pydantic import BaseModel, Field

from app.attendance.daily_excel import DailyExcelExporter, DailyExportRequest, DailyExportResult
from app.attendance.timetable import Timetable
from app.attendance.timetable_loader import TimetableLoader
from app.config.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/excel", tags=["excel"])

# Global exporter instance
_exporter: Optional[DailyExcelExporter] = None
_timetable: Optional[Timetable] = None


def get_exporter() -> DailyExcelExporter:
    """Get or create the global Excel exporter."""
    global _exporter
    if _exporter is None:
        _exporter = DailyExcelExporter()
    return _exporter


def get_timetable() -> Optional[Timetable]:
    """Get the current timetable for export."""
    global _timetable
    if _timetable is None:
        loader = TimetableLoader()
        _timetable = loader.load_latest()
    return _timetable


def get_exports_dir() -> Path:
    """Get the canonical exports directory (absolute)."""
    settings = load_settings()
    exports_dir = settings.paths.data_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    return exports_dir


# Pydantic models for API requests/responses


class DailyExportRequestModel(BaseModel):
    """Daily export request model."""
    date: str  # YYYY-MM-DD
    timezone: str = "Asia/Bangkok"
    export_version: str = "1.0"
    include_events_sheet: bool = True
    include_provenance_sheet: bool = True
    include_summary_sheet: bool = True


class DailyExportResultResponse(BaseModel):
    """Daily export result response model."""
    export_id: str
    file_path: str
    sheets_created: List[str]
    record_count: int
    success: bool
    error: Optional[str] = None
    created_at: str


class ExportListResponse(BaseModel):
    """Export list response model."""
    exports: List[DailyExportResultResponse]


def _read_workbook_metadata(file_path: Path) -> Dict[str, Any]:
    """
    Read metadata from an XLSX file using openpyxl read_only mode.
    Returns dict with sheets, record_count (from DAILY_ATTENDANCE sheet data rows), etc.
    """
    metadata = {
        "sheets_created": [],
        "record_count": 0,
    }
    try:
        wb = load_workbook(file_path, read_only=True, data_only=True)
        metadata["sheets_created"] = wb.sheetnames
        wb.close()
        # Try to count data rows in DAILY_ATTENDANCE sheet (header row + data rows)
        wb = load_workbook(file_path, read_only=True, data_only=True)
        if "DAILY_ATTENDANCE" in wb.sheetnames:
            ws = wb["DAILY_ATTENDANCE"]
            # max_row includes header; subtract 1 for data rows
            metadata["record_count"] = max(0, ws.max_row - 1)
        wb.close()
    except Exception as e:
        logger.warning(f"Failed to read workbook metadata from {file_path}: {e}")
    return metadata


@router.post("/export/daily", response_model=DailyExportResultResponse)
async def export_daily_attendance(request: DailyExportRequestModel):
    """Generate daily attendance Excel export."""
    exporter = get_exporter()
    timetable = get_timetable()

    # Parse date
    try:
        export_date = datetime.strptime(request.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Create export request with ABSOLUTE output path
    exports_dir = get_exports_dir()
    output_filename = f"daily_{request.date.replace('-', '')}.xlsx"
    absolute_output_path = str(exports_dir / output_filename)

    export_request = DailyExportRequest(
        date=export_date,
        output_path=absolute_output_path,
        timezone=request.timezone,
        export_version=request.export_version,
        timetable=timetable,
        include_events_sheet=request.include_events_sheet,
        include_provenance_sheet=request.include_provenance_sheet,
        include_summary_sheet=request.include_summary_sheet,
    )

    # Generate export
    result = exporter.export_daily_attendance(export_request)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Export failed")

    return DailyExportResultResponse(
        export_id=result.export_id or f"EXP-{request.date.replace('-', '')}-001",
        file_path=result.output_path or "",
        sheets_created=result.sheets_created,
        record_count=result.records_exported,
        success=result.success,
        error=result.error,
        created_at=datetime.utcnow().isoformat() + "Z",
    )


@router.get("/export/{export_id}/download")
async def download_excel_export(export_id: str):
    """Download an Excel export file - exact export_id match."""
    exports_dir = get_exports_dir()

    # Exact filename match: export_id must be in the filename without .xlsx
    # Export IDs from exporter are like "EXPORT-<hash16>", but user may also use filename-based IDs
    target_filename = None
    for filename in os.listdir(exports_dir):
        if filename.endswith('.xlsx'):
            # Match by exact export_id in filename (without .xlsx)
            if filename.replace('.xlsx', '') == export_id:
                target_filename = filename
                break

    if not target_filename:
        raise HTTPException(status_code=404, detail=f"Export {export_id} not found")

    file_path = exports_dir / target_filename
    return FileResponse(
        path=str(file_path),
        filename=target_filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/exports", response_model=ExportListResponse)
async def list_excel_exports():
    """List all generated Excel exports with real metadata."""
    exports_dir = get_exports_dir()
    exports = []

    if exports_dir.exists():
        for filename in sorted(os.listdir(exports_dir), reverse=True):
            if filename.endswith('.xlsx'):
                file_path = exports_dir / filename
                stat = file_path.stat()

                # Read actual metadata from the workbook
                metadata = _read_workbook_metadata(file_path)

                # Parse export_id from filename (without .xlsx)
                export_id = filename.replace('.xlsx', '')

                exports.append(DailyExportResultResponse(
                    export_id=export_id,
                    file_path=str(file_path),
                    sheets_created=metadata["sheets_created"],
                    record_count=metadata["record_count"],
                    success=True,
                    created_at=datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                ))

    return ExportListResponse(exports=exports)


@router.delete("/export/{export_id}")
async def delete_excel_export(export_id: str):
    """Delete an Excel export file - exact export_id match."""
    exports_dir = get_exports_dir()

    target_filename = None
    for filename in os.listdir(exports_dir):
        if filename.endswith('.xlsx'):
            if filename.replace('.xlsx', '') == export_id:
                target_filename = filename
                break

    if not target_filename:
        raise HTTPException(status_code=404, detail=f"Export {export_id} not found")

    file_path = exports_dir / target_filename
    try:
        file_path.unlink()
        return {"success": True, "message": f"Export {export_id} deleted"}
    except Exception as e:
        logger.error(f"Failed to delete {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete export: {e}")