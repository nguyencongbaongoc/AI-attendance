"""
Phase 41A — Attendance API Endpoints.

REST endpoints for attendance records, summaries, and queries.
Integrates with existing AttendanceRepository and AttendanceEngine.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.attendance.contract import AttendanceRecord, IdentityCertainty
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.attendance.query import (
    AttendanceQueryBuilder,
    AttendanceQueryResult,
    AttendanceSummary,
    create_query_builder,
    get_attendance_summary,
    format_timestamp,
    records_to_timeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])

# Global repository instance
_repository: Optional[AttendanceRepository] = None


def get_repository() -> AttendanceRepository:
    """Get or create the global attendance repository."""
    global _repository
    if _repository is None:
        _repository = create_attendance_repository()
    return _repository


# Pydantic models for API responses

class AttendanceRecordResponse(BaseModel):
    """Attendance record response model."""
    attendance_record_id: str
    source_resolution_id: str
    person_id: str
    person_name: str
    camera_id: str
    local_track_id: str
    global_observation_id: str
    direction: str
    identity_certainty: str
    identity_candidate: Optional[str]
    identity_confidence: float
    timestamp: float
    timestamp_iso: str
    day: str
    session_id: Optional[str]
    session_type: Optional[str]
    attendance_state: str
    in_state: str
    out_state: str
    decision_reason: str
    created_at: str
    persisted_at: str
    class_id: Optional[str] = None
    crop_url: Optional[str] = None
    id: Optional[str] = None
    student_id: Optional[str] = None
    event_type: Optional[str] = None
    confidence: Optional[float] = None
    evidence_snapshot_path: Optional[str] = None
    evidence_clip_path: Optional[str] = None
    offset_seconds: Optional[float] = None


class AttendanceSummaryResponse(BaseModel):
    """Attendance summary response model."""
    present: int
    late: int
    left_early: int
    absent: int
    total: int
    total_students: int = 0


_student_cache: Dict[str, tuple[str, str]] = {}

def _lookup_student(student_id: Optional[str]) -> tuple[str, str]:
    """Look up (full_name, class_id) for student from school.db."""
    if not student_id or student_id in ("UNKNOWN", "None", ""):
        return "Chưa xác định", "N/A"
    if student_id in _student_cache:
        return _student_cache[student_id]
    try:
        import sqlite3
        from app.config.settings import load_settings
        settings = load_settings()
        db_path = settings.paths.data_dir / "school.db"
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                row = cur.execute("SELECT full_name, class_id FROM students WHERE student_id = ?", (student_id,)).fetchone()
                if row:
                    _student_cache[student_id] = (row[0], row[1])
                    return row[0], row[1]
    except Exception:
        pass
    return student_id, "N/A"


class AttendanceQueryParams(BaseModel):
    """Query parameters for attendance records."""
    camera_id: Optional[str] = None
    track_id: Optional[str] = None
    global_observation_id: Optional[str] = None
    direction: Optional[str] = None
    identity_certainty: Optional[str] = None
    identity_candidate: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    limit: Optional[int] = 100
    offset: int = 0
    order_by: str = "event_timestamp"
    desc: bool = False


class AttendanceQueryResultResponse(BaseModel):
    """Attendance query result response model."""
    records: List[AttendanceRecordResponse]
    total: int
    limit: int
    offset: int


class PersonAttendanceResponse(BaseModel):
    """Person attendance response model."""
    person_id: str
    person_name: str
    total_events: int
    in_events: int
    out_events: int
    first_seen: Optional[str]
    last_seen: Optional[str]
    cameras: List[str]
    attendance_states: Dict[str, int]


@router.get("/summary", response_model=AttendanceSummaryResponse)
async def get_attendance_summary_endpoint():
    """Get attendance summary for today."""
    repository = get_repository()
    summary = get_attendance_summary(repository)
    
    total_students = 0
    try:
        import sqlite3
        from app.config.settings import load_settings
        settings = load_settings()
        db_path = settings.paths.data_dir / "school.db"
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM students WHERE is_active = 1").fetchone()
                if row:
                    total_students = row[0]
    except Exception:
        pass
    
    absent = max(0, total_students - summary.in_count)
    
    return AttendanceSummaryResponse(
        present=summary.in_count,  # IN events = present
        late=0,
        left_early=summary.out_count,  # OUT events = left
        absent=absent,
        total=summary.total_records,
        total_students=total_students,
    )


@router.get("/records", response_model=AttendanceQueryResultResponse)
async def get_attendance_records(
    camera_id: Optional[str] = Query(None),
    track_id: Optional[str] = Query(None),
    global_observation_id: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    identity_certainty: Optional[str] = Query(None),
    identity_candidate: Optional[str] = Query(None),
    class_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    order_by: str = Query("event_timestamp"),
    desc: bool = Query(False),
):
    """Query attendance records with filters."""
    repository = get_repository()
    builder = create_query_builder(repository)
    
    if camera_id:
        builder.camera(camera_id)
    if track_id:
        builder.track(camera_id or "", track_id)
    if global_observation_id:
        builder.global_observation(global_observation_id)
    if direction:
        builder.direction(direction)
    if identity_certainty:
        builder.identity_certainty(identity_certainty)
    if identity_candidate:
        builder.identity_candidate(identity_candidate)
        
    if date:
        clean_d = date.replace("-", "").strip()
        try:
            dt = datetime.strptime(clean_d, "%Y%m%d")
            d_start = dt.replace(hour=0, minute=0, second=0).timestamp()
            d_end = dt.replace(hour=23, minute=59, second=59).timestamp()
            if start_time is None:
                start_time = d_start
            if end_time is None:
                end_time = d_end
        except Exception:
            pass

    if start_time is not None:
        builder.since(start_time)
    if end_time is not None:
        builder.until(end_time)
    
    builder.limit(limit).offset(offset).order_by(order_by, desc)
    
    result = builder.execute_with_metadata()
    
    # Convert records to response format
    records_response = []
    for idx, record in enumerate(result.records):
        candidate = record.identity_candidate or "UNKNOWN"
        name, student_class = _lookup_student(candidate)
        if class_id and student_class != class_id:
            continue
        if name == "Chưa xác định" and record.local_track_id:
            name = f"Track #{record.local_track_id}"
        
        crop_url = record.snapshot_face_url
        conf = float(record.identity_confidence or 0.0)
        event_type = "IN" if (record.direction.value if hasattr(record.direction, "value") else str(record.direction)).lower() == "in" else "OUT"
        
        records_response.append(AttendanceRecordResponse(
            attendance_record_id=record.attendance_record_id,
            source_resolution_id=record.source_resolution_id,
            person_id=candidate,
            person_name=name,
            camera_id=record.camera_id,
            local_track_id=record.local_track_id,
            global_observation_id=record.global_observation_id or "",
            direction=record.direction.value if hasattr(record.direction, "value") else str(record.direction),
            identity_certainty=record.identity_certainty.value if hasattr(record.identity_certainty, "value") else str(record.identity_certainty),
            identity_candidate=record.identity_candidate,
            identity_confidence=conf,
            timestamp=record.event_timestamp,
            timestamp_iso=format_timestamp(record.event_timestamp),
            day=datetime.utcfromtimestamp(record.event_timestamp).strftime("%Y-%m-%d"),
            session_id=None,
            session_type=None,
            attendance_state=record.new_state,
            in_state="on_time" if event_type == "IN" else "not_applicable",
            out_state="on_time" if event_type == "OUT" else "not_applicable",
            decision_reason="Auto-generated from resolution",
            created_at=record.created_at,
            persisted_at=record.persisted_at,
            class_id=student_class,
            crop_url=crop_url,
            id=record.attendance_record_id,
            student_id=candidate,
            event_type=event_type,
            confidence=conf,
            evidence_snapshot_path=crop_url,
            evidence_clip_path=record.video_clip_url,
            offset_seconds=0.0,
        ))
    
    return AttendanceQueryResultResponse(
        records=records_response,
        total=result.total_count,
        limit=result.limit or limit,
        offset=result.offset,
    )


@router.get("/records/{record_id}", response_model=AttendanceRecordResponse)
async def get_attendance_record(record_id: str):
    """Get a specific attendance record by ID."""
    repository = get_repository()
    record = repository.get_by_id(record_id)
    
    if not record:
        raise HTTPException(status_code=404, detail=f"Attendance record {record_id} not found")
    
    return AttendanceRecordResponse(
        attendance_record_id=record.attendance_record_id,
        source_resolution_id=record.source_resolution_id,
        person_id=record.identity_candidate or "UNKNOWN",
        person_name=f"Person {record.identity_candidate or record.local_track_id}",
        camera_id=record.camera_id,
        local_track_id=record.local_track_id,
        global_observation_id=record.global_observation_id or "",
        direction=record.direction.value,
        identity_certainty=record.identity_certainty.value,
        identity_candidate=record.identity_candidate,
        identity_confidence=0.0,
        timestamp=record.event_timestamp,
        timestamp_iso=format_timestamp(record.event_timestamp),
        day=datetime.utcfromtimestamp(record.event_timestamp).strftime("%Y-%m-%d"),
        session_id=None,
        session_type=None,
        attendance_state=record.new_state,
        in_state="on_time" if record.direction.value == "in" else "not_applicable",
        out_state="on_time" if record.direction.value == "out" else "not_applicable",
        decision_reason="Auto-generated from resolution",
        created_at=record.created_at,
        persisted_at=record.persisted_at,
    )


@router.get("/person/{person_id}", response_model=AttendanceQueryResultResponse)
async def get_person_attendance(
    person_id: str,
    camera_id: Optional[str] = Query(None),
    track_id: Optional[str] = Query(None),
    global_observation_id: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    identity_certainty: Optional[str] = Query(None),
    start_time: Optional[float] = Query(None),
    end_time: Optional[float] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    order_by: str = Query("event_timestamp"),
    desc: bool = Query(False),
):
    """Get attendance records for a specific person."""
    repository = get_repository()
    builder = create_query_builder(repository)
    
    builder.identity_candidate(person_id)
    
    if camera_id:
        builder.camera(camera_id)
    if track_id:
        builder.track(camera_id or "", track_id)
    if global_observation_id:
        builder.global_observation(global_observation_id)
    if direction:
        builder.direction(direction)
    if identity_certainty:
        builder.identity_certainty(identity_certainty)
    if start_time is not None:
        builder.since(start_time)
    if end_time is not None:
        builder.until(end_time)
    
    builder.limit(limit).offset(offset).order_by(order_by, desc)
    
    result = builder.execute_with_metadata()
    
    records_response = []
    for record in result.records:
        records_response.append(AttendanceRecordResponse(
            attendance_record_id=record.attendance_record_id,
            source_resolution_id=record.source_resolution_id,
            person_id=record.identity_candidate or "UNKNOWN",
            person_name=f"Person {record.identity_candidate or record.local_track_id}",
            camera_id=record.camera_id,
            local_track_id=record.local_track_id,
            global_observation_id=record.global_observation_id or "",
            direction=record.direction.value,
            identity_certainty=record.identity_certainty.value,
            identity_candidate=record.identity_candidate,
            identity_confidence=0.0,
            timestamp=record.event_timestamp,
            timestamp_iso=format_timestamp(record.event_timestamp),
            day=datetime.utcfromtimestamp(record.event_timestamp).strftime("%Y-%m-%d"),
            session_id=None,
            session_type=None,
            attendance_state=record.new_state,
            in_state="on_time" if record.direction.value == "in" else "not_applicable",
            out_state="on_time" if record.direction.value == "out" else "not_applicable",
            decision_reason="Auto-generated from resolution",
            created_at=record.created_at,
            persisted_at=record.persisted_at,
        ))
    
    return AttendanceQueryResultResponse(
        records=records_response,
        total=result.total_count,
        limit=result.limit or limit,
        offset=result.offset,
    )


@router.get("/timeline")
async def get_attendance_timeline(
    camera_id: Optional[str] = Query(None),
    local_track_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get attendance timeline for a camera/track."""
    repository = get_repository()
    
    if camera_id and local_track_id:
        records = repository.query_by_track(camera_id, local_track_id, limit=limit)
    elif camera_id:
        records = repository.query_by_camera(camera_id, limit=limit)
    else:
        records = repository.get_chronological_history(limit=limit)
    
    timeline = records_to_timeline(records)
    return {"timeline": timeline, "count": len(timeline)}


@router.get("/daily-counts")
async def get_daily_attendance_counts(
    camera_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
):
    """Get daily attendance counts for the last N days."""
    repository = get_repository()
    from app.attendance.query import get_daily_attendance_counts
    counts = get_daily_attendance_counts(repository, camera_id, days)
    return {"daily_counts": counts}


@router.get("/track-history")
async def get_track_state_history(
    camera_id: str = Query(...),
    local_track_id: str = Query(...),
):
    """Get state transition history for a specific track."""
    repository = get_repository()
    from app.attendance.query import get_track_state_history
    history = get_track_state_history(repository, camera_id, local_track_id)
    return {"history": history}


@router.get("/stats")
async def get_attendance_stats():
    """Get attendance repository statistics."""
    repository = get_repository()
    stats = repository.get_stats()
    return stats