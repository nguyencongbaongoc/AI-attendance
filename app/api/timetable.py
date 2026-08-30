"""
Phase 41A — Timetable API Endpoints.

REST endpoints for timetable management.
Integrates with existing Timetable and TimetableEntry models.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from app.attendance.timetable import Timetable, TimetableEntry, SessionDay, SessionType
from app.attendance.timetable_loader import TimetableLoader, load_timetable_from_excel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/timetable", tags=["timetable"])

# Global timetable instance
_timetable: Optional[Timetable] = None
_timetable_loader: Optional[TimetableLoader] = None


def get_timetable_loader() -> TimetableLoader:
    """Get or create the global timetable loader."""
    global _timetable_loader
    if _timetable_loader is None:
        _timetable_loader = TimetableLoader()
    return _timetable_loader


def get_timetable() -> Optional[Timetable]:
    """Get the current timetable."""
    global _timetable
    if _timetable is None:
        loader = get_timetable_loader()
        # Try to load from default location
        import os
        default_path = "data/timetable.xlsx"
        if os.path.exists(default_path):
            result = loader.load_from_excel(default_path)
            if result.success:
                _timetable = result.timetable
    return _timetable


# Pydantic models for API responses

class TimetableEntryResponse(BaseModel):
    """Timetable entry response model."""
    entry_id: str
    person_id: str
    session_id: str
    day: str
    entry_time: int
    exit_time: int
    entry_window_seconds: int
    exit_window_seconds: int
    late_tolerance_seconds: int
    session_type: str
    subject: str = ""
    location: str = ""
    expected_location: str = ""
    outside_allowed: bool
    created_at: str
    updated_at: str


class TimetableResponse(BaseModel):
    """Timetable response model."""
    timetable_id: str
    version: str
    entries: List[TimetableEntryResponse]
    created_at: str
    updated_at: str


class TimetableEntryCreate(BaseModel):
    """Timetable entry creation model."""
    person_id: str
    session_id: str
    day: str
    entry_time: int
    exit_time: int
    entry_window_seconds: int = 300
    exit_window_seconds: int = 300
    late_tolerance_seconds: int = 600
    session_type: str = "CLASSROOM"
    subject: str = ""
    location: str = ""
    expected_location: str = ""
    outside_allowed: bool = False


class TimetableEntryUpdate(BaseModel):
    """Timetable entry update model."""
    person_id: Optional[str] = None
    session_id: Optional[str] = None
    day: Optional[str] = None
    entry_time: Optional[int] = None
    exit_time: Optional[int] = None
    entry_window_seconds: Optional[int] = None
    exit_window_seconds: Optional[int] = None
    late_tolerance_seconds: Optional[int] = None
    session_type: Optional[str] = None
    subject: Optional[str] = None
    location: Optional[str] = None
    expected_location: Optional[str] = None
    outside_allowed: Optional[bool] = None


class ImportResult(BaseModel):
    """Import result model."""
    success: bool
    errors: List[str]


@router.get("", response_model=TimetableResponse)
async def get_timetable_endpoint():
    """Get the current timetable."""
    timetable = get_timetable()
    
    if not timetable:
        # Return empty timetable
        return TimetableResponse(
            timetable_id="empty",
            version="1.0",
            entries=[],
            created_at=datetime.utcnow().isoformat() + "Z",
            updated_at=datetime.utcnow().isoformat() + "Z",
        )
    
    entries_response = []
    for entry in timetable.entries:
        entries_response.append(TimetableEntryResponse(
            entry_id=entry.entry_id,
            person_id=entry.person_id,
            session_id=entry.session_id,
            day=entry.day.value,
            entry_time=entry.entry_time,
            exit_time=entry.exit_time,
            entry_window_seconds=entry.entry_window_end - entry.entry_window_start,
            exit_window_seconds=entry.exit_window_end - entry.exit_window_start,
            late_tolerance_seconds=entry.late_tolerance,
            session_type=entry.session_type.value,
            subject=entry.subject or "",
            location=entry.location or "",
            expected_location=entry.expected_location or "",
            outside_allowed=entry.outside_allowed,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        ))
    
    return TimetableResponse(
        timetable_id=timetable.timetable_id,
        version=timetable.timetable_version,
        entries=entries_response,
        created_at=timetable.created_at,
        updated_at=timetable.updated_at,
    )


@router.get("/entries", response_model=List[TimetableEntryResponse])
async def get_timetable_entries(person_id: Optional[str] = Query(None)):
    """Get timetable entries, optionally filtered by person."""
    timetable = get_timetable()
    
    if not timetable:
        return []
    
    entries = timetable.entries
    if person_id:
        entries = [e for e in entries if e.person_id == person_id]
    
    entries_response = []
    for entry in entries:
        entries_response.append(TimetableEntryResponse(
            entry_id=entry.entry_id,
            person_id=entry.person_id,
            session_id=entry.session_id,
            day=entry.day.value,
            entry_time=entry.entry_time,
            exit_time=entry.exit_time,
            entry_window_seconds=entry.entry_window_end - entry.entry_window_start,
            exit_window_seconds=entry.exit_window_end - entry.exit_window_start,
            late_tolerance_seconds=entry.late_tolerance,
            session_type=entry.session_type.value,
            subject=entry.subject or "",
            location=entry.location or "",
            expected_location=entry.expected_location or "",
            outside_allowed=entry.outside_allowed,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        ))
    
    return entries_response


@router.post("/entries", response_model=TimetableEntryResponse)
async def create_timetable_entry(entry: TimetableEntryCreate):
    """Create a new timetable entry."""
    timetable = get_timetable()
    
    if not timetable:
        raise HTTPException(status_code=400, detail="No timetable loaded. Please import a timetable first.")
    
    # Validate day
    try:
        day = SessionDay(entry.day)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid day: {entry.day}")
    
    # Validate session type
    try:
        session_type = SessionType(entry.session_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid session_type: {entry.session_type}")
    
    # Create new entry
    new_entry = TimetableEntry(
        entry_id=f"TT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        person_id=entry.person_id,
        session_id=entry.session_id,
        day=day,
        entry_time=entry.entry_time,
        exit_time=entry.exit_time,
        entry_window_seconds=entry.entry_window_seconds,
        exit_window_seconds=entry.exit_window_seconds,
        late_tolerance_seconds=entry.late_tolerance_seconds,
        session_type=session_type,
        subject=entry.subject,
        location=entry.location,
        expected_location=entry.expected_location,
        outside_allowed=entry.outside_allowed,
        created_at=datetime.utcnow().isoformat() + "Z",
        updated_at=datetime.utcnow().isoformat() + "Z",
    )
    
    # Add to timetable (in memory - would need persistence in production)
    timetable.entries.append(new_entry)
    timetable.timetable_version = f"v{len(timetable.entries)}"
    timetable.updated_at = datetime.utcnow().isoformat() + "Z"
    
    return TimetableEntryResponse(
        entry_id=new_entry.entry_id,
        person_id=new_entry.person_id,
        session_id=new_entry.session_id,
        day=new_entry.day.value,
        entry_time=new_entry.entry_time,
        exit_time=new_entry.exit_time,
        entry_window_seconds=new_entry.entry_window_seconds,
        exit_window_seconds=new_entry.exit_window_seconds,
        late_tolerance_seconds=new_entry.late_tolerance_seconds,
        session_type=new_entry.session_type.value,
        subject=new_entry.subject,
        location=new_entry.location,
        expected_location=new_entry.expected_location,
        outside_allowed=new_entry.outside_allowed,
        created_at=new_entry.created_at,
        updated_at=new_entry.updated_at,
    )


@router.put("/entries/{entry_id}", response_model=TimetableEntryResponse)
async def update_timetable_entry(entry_id: str, entry_update: TimetableEntryUpdate):
    """Update a timetable entry."""
    timetable = get_timetable()
    
    if not timetable:
        raise HTTPException(status_code=400, detail="No timetable loaded")
    
    # Find entry
    entry_idx = None
    for i, entry in enumerate(timetable.entries):
        if entry.entry_id == entry_id:
            entry_idx = i
            break
    
    if entry_idx is None:
        raise HTTPException(status_code=404, detail=f"Timetable entry {entry_id} not found")
    
    entry = timetable.entries[entry_idx]
    
    # Update fields
    update_data = entry_update.model_dump(exclude_unset=True)
    
    if "day" in update_data:
        try:
            entry.day = SessionDay(update_data["day"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid day: {update_data['day']}")
    
    if "session_type" in update_data:
        try:
            entry.session_type = SessionType(update_data["session_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid session_type: {update_data['session_type']}")
    
    for field, value in update_data.items():
        if field not in ["day", "session_type"]:
            setattr(entry, field, value)
    
    entry.updated_at = datetime.utcnow().isoformat() + "Z"
    timetable.updated_at = datetime.utcnow().isoformat() + "Z"
    
    return TimetableEntryResponse(
        entry_id=entry.entry_id,
        person_id=entry.person_id,
        session_id=entry.session_id,
        day=entry.day.value,
        entry_time=entry.entry_time,
        exit_time=entry.exit_time,
        entry_window_seconds=entry.entry_window_seconds,
        exit_window_seconds=entry.exit_window_seconds,
        late_tolerance_seconds=entry.late_tolerance_seconds,
        session_type=entry.session_type.value,
        subject=entry.subject,
        location=entry.location,
        expected_location=entry.expected_location,
        outside_allowed=entry.outside_allowed,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@router.delete("/entries/{entry_id}")
async def delete_timetable_entry(entry_id: str):
    """Delete a timetable entry."""
    timetable = get_timetable()
    
    if not timetable:
        raise HTTPException(status_code=400, detail="No timetable loaded")
    
    # Find and remove entry
    entry_idx = None
    for i, entry in enumerate(timetable.entries):
        if entry.entry_id == entry_id:
            entry_idx = i
            break
    
    if entry_idx is None:
        raise HTTPException(status_code=404, detail=f"Timetable entry {entry_id} not found")
    
    timetable.entries.pop(entry_idx)
    timetable.timetable_version = f"v{len(timetable.entries)}"
    timetable.updated_at = datetime.utcnow().isoformat() + "Z"
    
    return {"success": True}


@router.post("/import", response_model=ImportResult)
async def import_timetable_from_excel(file: UploadFile = File(...)):
    """Import timetable from Excel file."""
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be an Excel file (.xlsx or .xls)")
    
    # Save uploaded file temporarily
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Load timetable from Excel
        timetable = load_timetable_from_excel(tmp_path)
        
        # Update global timetable
        global _timetable
        _timetable = timetable
        
        return ImportResult(success=True, errors=[])
    except Exception as e:
        logger.error(f"Failed to import timetable: {e}")
        return ImportResult(success=False, errors=[str(e)])
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get("/session-types")
async def get_session_types():
    """Get available session types."""
    return {"session_types": [t.value for t in SessionType]}


@router.get("/days")
async def get_days():
    """Get available days."""
    return {"days": [d.value for d in SessionDay]}