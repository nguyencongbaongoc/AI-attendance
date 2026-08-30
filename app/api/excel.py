"""
Phase 41A — Excel Export API Endpoints.

REST endpoints for daily Excel export generation and management.
Integrates with existing DailyExcelExporter.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.attendance.daily_excel import DailyExcelExporter, DailyExportRequest, DailyExportResult
from app.attendance.timetable import Timetable
from app.attendance.timetable_loader import TimetableLoader

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
    
    # Create export request
    export_request = DailyExportRequest(
        date=export_date,
        output_path=f"exports/daily_{request.date.replace('-', '')}.xlsx",
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
    """Download an Excel export file."""
    # Find the export file
    exports_dir = "exports"
    if not os.path.exists(exports_dir):
        raise HTTPException(status_code=404, detail="Exports directory not found")
    
    # Look for file matching export_id
    for filename in os.listdir(exports_dir):
        if export_id in filename and filename.endswith('.xlsx'):
            file_path = os.path.join(exports_dir, filename)
            return FileResponse(
                path=file_path,
                filename=filename,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    raise HTTPException(status_code=404, detail=f"Export {export_id} not found")


@router.get("/exports", response_model=ExportListResponse)
async def list_excel_exports():
    """List all generated Excel exports."""
    exports_dir = "exports"
    exports = []
    
    if os.path.exists(exports_dir):
        for filename in sorted(os.listdir(exports_dir), reverse=True):
            if filename.endswith('.xlsx'):
                file_path = os.path.join(exports_dir, filename)
                stat = os.stat(file_path)
                
                # Parse export info from filename
                export_id = filename.replace('.xlsx', '')
                date_str = filename.replace('daily_', '').replace('.xlsx', '')
                
                exports.append(DailyExportResultResponse(
                    export_id=export_id,
                    file_path=file_path,
                    sheets_created=["Daily Attendance", "Events", "Provenance", "Summary"],
                    record_count=0,  # Would need to read file to get actual count
                    success=True,
                    created_at=datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                ))
    
    return ExportListResponse(exports=exports)