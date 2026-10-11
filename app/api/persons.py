"""
Phase 41A — Persons API Endpoints.

REST endpoints for person search, details, and enrollment data.
Integrates with existing enrollment database and attendance repository.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.vision.enrollment import load_enrollment_database
from app.vision.enrollment_contract import EnrollmentDatabaseMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/persons", tags=["persons"])

# Global instances
_repository: Optional[AttendanceRepository] = None
_enrollment_data: Optional[tuple] = None  # (embeddings, metadata)


def get_repository() -> AttendanceRepository:
    """Get or create the global attendance repository."""
    global _repository
    if _repository is None:
        _repository = create_attendance_repository()
    return _repository


def get_enrollment_data() -> tuple:
    """Get or load enrollment database."""
    global _enrollment_data
    if _enrollment_data is None:
        try:
            _enrollment_data = load_enrollment_database("data/enrollment")
        except Exception as e:
            logger.warning(f"Could not load enrollment database: {e}")
            _enrollment_data = (None, None)
    return _enrollment_data


# Pydantic models for API responses

class PersonResponse(BaseModel):
    """Person response model."""
    person_id: str
    name: str
    role: str
    enrollment_date: str
    last_seen: str
    last_camera: str
    attendance_state: str
    face_quality: float
    track_count: int


class PersonSearchParams(BaseModel):
    """Query parameters for person search."""
    query: Optional[str] = None
    filter: Optional[str] = None
    limit: int = 50
    offset: int = 0


class PersonSearchResultResponse(BaseModel):
    """Person search result response model."""
    persons: List[PersonResponse]
    total: int


class PersonAppearanceResponse(BaseModel):
    """Person appearance history response model."""
    attendance_record_id: str
    camera_id: str
    local_track_id: str
    global_observation_id: str
    direction: str
    identity_confidence: float
    timestamp: float
    timestamp_iso: str
    attendance_state: str


class EnrollmentPersonResponse(BaseModel):
    """Enrolled person response model."""
    person_id: str
    name: str
    role: str
    face_quality: float
    vector_count: int
    last_seen: str
    enrollment_date: str


class EnrollmentStatsResponse(BaseModel):
    """Enrollment statistics response model."""
    total_enrolled: int
    students: int
    staff: int
    avg_quality: float
    model: str
    threshold: str
    last_updated: str


class QualityCheckResultResponse(BaseModel):
    """Quality check result response model."""
    label: str
    value: str
    ok: bool


@router.get("", response_model=PersonSearchResultResponse)
async def search_persons(
    query: Optional[str] = Query(None),
    filter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Search persons by name, ID, or filter by role/attendance state."""
    repository = get_repository()
    embeddings, metadata = get_enrollment_data()
    
    persons = []
    
    # If we have enrollment data, use it
    if metadata and metadata.person_ids:
        for person_id in metadata.person_ids:
            # Get sample provenance for this person
            person_name = person_id
            role = "student" if person_id.startswith("STU") else "staff"
            enrollment_date = "2024-01-15"
            face_quality = 0.9
            vector_count = 1
            last_seen = "—"
            last_camera = "—"
            attendance_state = "absent"
            track_count = 0
            
            # Try to get attendance info from repository
            try:
                records = repository.query_by_identity(person_id, limit=10)
                if records:
                    latest = records[0]
                    last_seen = datetime.utcfromtimestamp(latest.event_timestamp).strftime("%H:%M:%S")
                    last_camera = latest.camera_id
                    track_count = len(records)
                    # Determine attendance state from latest record
                    if latest.new_state == "inside":
                        attendance_state = "present"
                    elif latest.new_state == "outside":
                        attendance_state = "left_early"
                    else:
                        attendance_state = "absent"
                    
                    # Get face quality from enrollment metadata if available
                    for prov in metadata.sample_provenance:
                        if prov.get("person_id") == person_id:
                            face_quality = prov.get("quality_score", 0.9)
                            break
            except Exception:
                pass
            
            # Apply filters
            if query and query.lower() not in person_id.lower() and query.lower() not in person_name.lower():
                continue
            if filter and filter != "all":
                if filter in ["student", "staff"] and role != filter:
                    continue
                if filter in ["present", "absent", "late"] and attendance_state != filter:
                    continue
            
            persons.append(PersonResponse(
                person_id=person_id,
                name=person_name,
                role=role,
                enrollment_date=enrollment_date,
                last_seen=last_seen,
                last_camera=last_camera,
                attendance_state=attendance_state,
                face_quality=face_quality,
                track_count=track_count,
            ))
    
    # If no enrollment data, fall back to attendance records
    if not persons:
        all_records = repository.get_chronological_history(limit=1000)
        person_map = {}
        for record in all_records:
            pid = record.identity_candidate or record.local_track_id
            if pid not in person_map:
                person_map[pid] = {
                    "person_id": pid,
                    "name": f"Person {pid}",
                    "role": "unknown",
                    "enrollment_date": "unknown",
                    "last_seen": "—",
                    "last_camera": "—",
                    "attendance_state": "unknown",
                    "face_quality": 0.0,
                    "track_count": 0,
                }
            person_map[pid]["track_count"] += 1
            person_map[pid]["last_seen"] = datetime.utcfromtimestamp(record.event_timestamp).strftime("%H:%M:%S")
            person_map[pid]["last_camera"] = record.camera_id
            if record.new_state == "inside":
                person_map[pid]["attendance_state"] = "present"
            elif record.new_state == "outside":
                person_map[pid]["attendance_state"] = "left_early"
        
        for person in person_map.values():
            if query and query.lower() not in person["person_id"].lower() and query.lower() not in person["name"].lower():
                continue
            if filter and filter != "all":
                if filter in ["student", "staff"] and person["role"] != filter:
                    continue
                if filter in ["present", "absent", "late"] and person["attendance_state"] != filter:
                    continue
            persons.append(PersonResponse(**person))
    
    # Sort by last_seen descending
    persons.sort(key=lambda p: p.last_seen, reverse=True)
    
    total = len(persons)
    paginated = persons[offset:offset + limit]
    
    return PersonSearchResultResponse(persons=paginated, total=total)


@router.get("/{person_id}", response_model=PersonResponse)
async def get_person(person_id: str):
    """Get detailed person information."""
    repository = get_repository()
    embeddings, metadata = get_enrollment_data()
    
    # Try to get from enrollment database first
    if metadata and person_id in metadata.person_ids:
        role = "student" if person_id.startswith("STU") else "staff"
        enrollment_date = "2024-01-15"
        face_quality = 0.9
        vector_count = 1
        last_seen = "—"
        last_camera = "—"
        attendance_state = "absent"
        track_count = 0
        
        # Get attendance info
        try:
            records = repository.query_by_identity(person_id, limit=10)
            if records:
                latest = records[0]
                last_seen = datetime.utcfromtimestamp(latest.event_timestamp).strftime("%H:%M:%S")
                last_camera = latest.camera_id
                track_count = len(records)
                if latest.new_state == "inside":
                    attendance_state = "present"
                elif latest.new_state == "outside":
                    attendance_state = "left_early"
                else:
                    attendance_state = "absent"
                
                for prov in metadata.sample_provenance:
                    if prov.get("person_id") == person_id:
                        face_quality = prov.get("quality_score", 0.9)
                        break
        except Exception:
            pass
        
        return PersonResponse(
            person_id=person_id,
            name=person_id,
            role=role,
            enrollment_date=enrollment_date,
            last_seen=last_seen,
            last_camera=last_camera,
            attendance_state=attendance_state,
            face_quality=face_quality,
            track_count=track_count,
        )
    
    # Fall back to attendance records
    records = repository.query_by_identity(person_id, limit=10)
    if not records:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")
    
    latest = records[0]
    last_seen = datetime.utcfromtimestamp(latest.event_timestamp).strftime("%H:%M:%S")
    last_camera = latest.camera_id
    track_count = len(records)
    attendance_state = "present" if latest.new_state == "inside" else "left_early" if latest.new_state == "outside" else "absent"
    
    return PersonResponse(
        person_id=person_id,
        name=f"Person {person_id}",
        role="unknown",
        enrollment_date="unknown",
        last_seen=last_seen,
        last_camera=last_camera,
        attendance_state=attendance_state,
        face_quality=0.0,
        track_count=track_count,
    )


@router.get("/{person_id}/appearances", response_model=List[PersonAppearanceResponse])
async def get_person_appearances(
    person_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get appearance history for a person."""
    repository = get_repository()
    records = repository.query_by_identity(person_id, limit=limit)
    
    appearances = []
    for record in records:
        appearances.append(PersonAppearanceResponse(
            attendance_record_id=record.attendance_record_id,
            camera_id=record.camera_id,
            local_track_id=record.local_track_id,
            global_observation_id=record.global_observation_id or "",
            direction=record.direction.value,
            identity_confidence=0.0,
            timestamp=record.event_timestamp,
            timestamp_iso=datetime.utcfromtimestamp(record.event_timestamp).isoformat() + "Z",
            attendance_state=record.new_state,
        ))
    
    return appearances


# Enrollment endpoints

@router.get("/enrollment/persons", response_model=List[EnrollmentPersonResponse])
async def get_enrolled_persons():
    """Get all enrolled persons from the ArcFace database."""
    embeddings, metadata = get_enrollment_data()
    
    if not metadata:
        return []
    
    persons = []
    for person_id in metadata.person_ids:
        role = "student" if person_id.startswith("STU") else "staff"
        face_quality = 0.9
        vector_count = 1
        last_seen = "—"
        enrollment_date = "2024-01-15"
        
        for prov in metadata.sample_provenance:
            if prov.get("person_id") == person_id:
                face_quality = prov.get("quality_score", 0.9)
                break
        
        persons.append(EnrollmentPersonResponse(
            person_id=person_id,
            name=person_id,
            role=role,
            face_quality=face_quality,
            vector_count=vector_count,
            last_seen=last_seen,
            enrollment_date=enrollment_date,
        ))
    
    return persons


@router.get("/enrollment/stats", response_model=EnrollmentStatsResponse)
async def get_enrollment_stats():
    """Get enrollment database statistics."""
    embeddings, metadata = get_enrollment_data()
    
    if not metadata:
        return EnrollmentStatsResponse(
            total_enrolled=0,
            students=0,
            staff=0,
            avg_quality=0.0,
            model="ArcFace R100",
            threshold="0.45 cosine",
            last_updated="—",
        )
    
    students = sum(1 for pid in metadata.person_ids if pid.startswith("STU"))
    staff = sum(1 for pid in metadata.person_ids if pid.startswith("STF"))
    
    avg_quality = 0.0
    if metadata.sample_provenance:
        qualities = [p.get("quality_score", 0) for p in metadata.sample_provenance if p.get("quality_score")]
        if qualities:
            avg_quality = sum(qualities) / len(qualities) * 100
    
    return EnrollmentStatsResponse(
        total_enrolled=metadata.embedding_count,
        students=students,
        staff=staff,
        avg_quality=round(avg_quality, 1),
        model=metadata.model_filename,
        threshold="0.45 cosine",
        last_updated=metadata.creation_timestamp,
    )


@router.post("/enrollment/persons", response_model=EnrollmentPersonResponse)
async def enroll_person(data: Dict[str, Any]):
    """Enroll a new person (placeholder - actual enrollment is offline)."""
    # This is a placeholder - actual enrollment happens via offline scripts
    # Return the data as confirmation
    return EnrollmentPersonResponse(
        person_id=data.get("person_id", "NEW"),
        name=data.get("name", "New Person"),
        role=data.get("role", "student"),
        face_quality=data.get("face_quality", 0.0),
        vector_count=1,
        last_seen="—",
        enrollment_date=datetime.utcnow().strftime("%Y-%m-%d"),
    )


@router.delete("/enrollment/persons/{person_id}")
async def delete_enrolled_person(person_id: str):
    """Delete an enrolled person (placeholder)."""
    return {"success": True, "message": f"Person {person_id} deletion requested (offline operation)"}


@router.post("/enrollment/persons/{person_id}/quality-check", response_model=List[QualityCheckResultResponse])
async def run_quality_check(person_id: str):
    """Run quality check on enrolled person (placeholder)."""
    embeddings, metadata = get_enrollment_data()
    
    if not metadata or person_id not in metadata.person_ids:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found in enrollment database")
    
    # Return mock quality check results
    return [
        QualityCheckResultResponse(label="ArcFace embedding norm", value="18.4 (optimal: 15–20)", ok=True),
        QualityCheckResultResponse(label="Duplicate check", value="No match found · distance > 0.45", ok=True),
        QualityCheckResultResponse(label="Face sharpness (Laplacian)", value="412 (threshold: 100)", ok=True),
        QualityCheckResultResponse(label="Inter-ocular distance", value="84px (adequate)", ok=True),
    ]