"""
Phase Replay-Fix — Replay API Endpoints.

Real, minimal replay API that backs the existing frontend AnnotatedReplay
UI. Does NOT replace the existing attendance pipeline; it reads from the
existing attendance_records table and the new recordings/ directory.

Endpoints
---------
GET  /api/v1/replay/cameras
    -> {"cameras": ["cam1", "cam2"]}

GET  /api/v1/replay/recordings?camera_id=cam1
    -> {"recordings": [RecordingInfo]}

GET  /api/v1/replay/recordings/{recording_id}
    -> RecordingInfo

GET  /api/v1/replay/occurrences?camera_id=cam1&person_id=...&track_id=...&limit=50
    -> ReplayOccurrence list (one per attendance event with recording reference)

GET  /api/v1/replay/occurrences/{attendance_record_id}
    -> ReplayOccurrence (single event with recording reference)

GET  /api/v1/replay/persons/{person_id}/appearances?limit=100
    -> ReplayOccurrence list (events of one person with recording refs)

GET  /api/v1/replay/persons/{person_id}/video-events?direction=in|out
    -> ReplayEvent list (lightweight IN/OUT events for a person)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.attendance.contract import AttendanceRecord
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.replay.recording import (
    RecordingInfo,
    RecordingRegistry,
    get_recording_registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/replay", tags=["replay"])


# ----------------------------------------------------------------------
# Pydantic response models
# ----------------------------------------------------------------------

class RecordingResponse(BaseModel):
    recording_id: str
    camera_id: str
    file_path: str
    url_path: str
    start_timestamp: float
    end_timestamp: float
    duration_seconds: float
    width: int
    height: int
    fps: float
    size_bytes: int
    codec: str
    source: str
    exists: bool

    @classmethod
    def from_info(cls, info: RecordingInfo) -> "RecordingResponse":
        return cls(**info.to_dict())


class RecordingListResponse(BaseModel):
    recordings: List[RecordingResponse]


class CameraListResponse(BaseModel):
    cameras: List[str]


class ReplayEventResponse(BaseModel):
    """A lightweight IN/OUT event used for the Event Log panel."""
    attendance_record_id: str
    person_id: Optional[str]
    person_name: Optional[str] = None
    camera_id: str
    local_track_id: str
    direction: str
    timestamp: float
    timestamp_iso: str
    identity_certainty: str
    identity_confidence: float
    event_frame_index: int


class ReplayOccurrenceResponse(BaseModel):
    """
    A single replayable occurrence = (attendance event) + (recording reference).

    This is the contract that ties a real event to a real recording so the
    frontend can render a true <video> + a true event log.
    """
    attendance_record_id: str
    person_id: Optional[str]
    person_name: Optional[str] = None
    camera_id: str
    local_track_id: str
    direction: str
    timestamp: float
    timestamp_iso: str
    identity_certainty: str
    identity_confidence: float
    event_frame_index: int
    has_recording: bool
    recording: Optional[RecordingResponse] = None
    # If bbox/trajectory cannot be truthfully reconstructed, this is null
    # and the UI must NOT invent a box.
    bbox: Optional[List[float]] = None
    trajectory: Optional[List[List[float]]] = None
    bbox_available: bool = False
    trajectory_available: bool = False


class OccurrenceListResponse(BaseModel):
    occurrences: List[ReplayOccurrenceResponse]
    total: int


class ReplayEventListResponse(BaseModel):
    events: List[ReplayEventResponse]
    total: int


# ----------------------------------------------------------------------
# Repository accessors
# ----------------------------------------------------------------------

_repository: Optional[AttendanceRepository] = None


def get_repository() -> AttendanceRepository:
    global _repository
    if _repository is None:
        _repository = create_attendance_repository()
    return _repository


def _registry() -> RecordingRegistry:
    return get_recording_registry()


def _ts_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _record_to_event(record: AttendanceRecord) -> ReplayEventResponse:
    return ReplayEventResponse(
        attendance_record_id=record.attendance_record_id,
        person_id=record.identity_candidate,
        person_name=None,
        camera_id=record.camera_id,
        local_track_id=record.local_track_id,
        direction=str(record.direction.value if hasattr(record.direction, "value") else record.direction),
        timestamp=float(record.event_timestamp),
        timestamp_iso=_ts_to_iso(float(record.event_timestamp)),
        identity_certainty=str(
            record.identity_certainty.value
            if hasattr(record.identity_certainty, "value")
            else record.identity_certainty
        ),
        identity_confidence=float(record.identity_confidence or 0.0),
        event_frame_index=int(record.event_frame_index if record.event_frame_index is not None else -1),
    )


def _build_occurrence(record: AttendanceRecord) -> ReplayOccurrenceResponse:
    rec = _registry().get_recording_for_event(
        camera_id=record.camera_id,
        event_timestamp=float(record.event_timestamp),
    )
    return ReplayOccurrenceResponse(
        attendance_record_id=record.attendance_record_id,
        person_id=record.identity_candidate,
        person_name=None,
        camera_id=record.camera_id,
        local_track_id=record.local_track_id,
        direction=str(record.direction.value if hasattr(record.direction, "value") else record.direction),
        timestamp=float(record.event_timestamp),
        timestamp_iso=_ts_to_iso(float(record.event_timestamp)),
        identity_certainty=str(
            record.identity_certainty.value
            if hasattr(record.identity_certainty, "value")
            else record.identity_certainty
        ),
        identity_confidence=float(record.identity_confidence or 0.0),
        event_frame_index=int(record.event_frame_index if record.event_frame_index is not None else -1),
        has_recording=rec is not None and rec.exists,
        recording=RecordingResponse.from_info(rec) if rec is not None else None,
        bbox=None,
        trajectory=None,
        bbox_available=False,
        trajectory_available=False,
    )


def _query_records(
    camera_id: Optional[str] = None,
    person_id: Optional[str] = None,
    track_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    order_desc: bool = True,
) -> List[AttendanceRecord]:
    repo = get_repository()
    if person_id is not None:
        records = repo.query_by_identity(identity_candidate=person_id, limit=1000)
        if camera_id is not None:
            records = [r for r in records if r.camera_id == camera_id]
        if track_id is not None:
            records = [r for r in records if r.local_track_id == track_id]
        records.sort(key=lambda r: r.event_timestamp, reverse=order_desc)
    else:
        records = repo.storage.query(  # type: ignore[attr-defined]
            camera_id=camera_id,
            local_track_id=track_id,
            limit=1000,
            offset=0,
            order_by="event_timestamp",
            order_desc=order_desc,
        )
        if camera_id is not None:
            records = [r for r in records if r.camera_id == camera_id]
        if track_id is not None:
            records = [r for r in records if r.local_track_id == track_id]
    return records[offset : offset + limit]


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@router.get("/cameras", response_model=CameraListResponse)
async def list_cameras() -> CameraListResponse:
    """List cameras that have at least one recording."""
    cams = _registry().list_cameras()
    return CameraListResponse(cameras=cams)


@router.get("/recordings", response_model=RecordingListResponse)
async def list_recordings(
    camera_id: Optional[str] = Query(default=None),
) -> RecordingListResponse:
    """List recordings, optionally filtered by camera_id."""
    recs = _registry().list_recordings(camera_id=camera_id)
    return RecordingListResponse(recordings=[RecordingResponse.from_info(r) for r in recs])


@router.get("/recordings/{recording_id}", response_model=RecordingResponse)
async def get_recording(recording_id: str) -> RecordingResponse:
    info = _registry().get_recording_by_id(recording_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Recording not found: {recording_id}")
    return RecordingResponse.from_info(info)


@router.get("/occurrences", response_model=OccurrenceListResponse)
async def list_occurrences(
    camera_id: Optional[str] = Query(default=None),
    person_id: Optional[str] = Query(default=None),
    track_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> OccurrenceListResponse:
    """List replay occurrences (events with recording references)."""
    # Total count requires a separate call because pagination is applied
    # after filtering/sorting.
    all_records = _query_records(
        camera_id=camera_id,
        person_id=person_id,
        track_id=track_id,
        limit=1000,
        offset=0,
        order_desc=True,
    )
    total = len(all_records)
    page = all_records[offset : offset + limit]
    return OccurrenceListResponse(
        occurrences=[_build_occurrence(r) for r in page],
        total=total,
    )


@router.get("/occurrences/{attendance_record_id}", response_model=ReplayOccurrenceResponse)
async def get_occurrence(attendance_record_id: str) -> ReplayOccurrenceResponse:
    record = get_repository().get_by_id(attendance_record_id)  # type: ignore[attr-defined]
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Occurrence not found: {attendance_record_id}",
        )
    return _build_occurrence(record)


@router.get("/persons/{person_id}/appearances", response_model=OccurrenceListResponse)
async def person_appearances(
    person_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> OccurrenceListResponse:
    """All replay occurrences for one person, ordered by timestamp DESC."""
    all_records = _query_records(
        person_id=person_id,
        limit=1000,
        offset=0,
        order_desc=True,
    )
    total = len(all_records)
    page = all_records[offset : offset + limit]
    return OccurrenceListResponse(
        occurrences=[_build_occurrence(r) for r in page],
        total=total,
    )


@router.get("/persons/{person_id}/video-events", response_model=ReplayEventListResponse)
async def person_video_events(
    person_id: str,
    direction: Optional[str] = Query(default=None, pattern="^(in|out)$"),
) -> ReplayEventListResponse:
    """Lightweight IN/OUT events for a person, used by the Replay Event Log panel."""
    records = _query_records(
        person_id=person_id,
        limit=500,
        offset=0,
        order_desc=True,
    )
    if direction is not None:
        records = [
            r for r in records
            if str(r.direction.value if hasattr(r.direction, "value") else r.direction) == direction
        ]
    return ReplayEventListResponse(
        events=[_record_to_event(r) for r in records],
        total=len(records),
    )
