"""
Phase 44 — Real Enrollment HTTP Endpoint.

Provides POST /api/v1/enrollment/persons accepting multipart/form-data
and delegates to existing enrollment pipeline (process_image_enrollment +
build_enrollment_database). Does not duplicate embedding logic.

Phase 0.2.2 — Added POST /api/v1/enrollment/reload for NPY reload notification.

Step 3 — Modified to use student_id as SSOT, save per-person NPY to
app/data/embeddings/{student_id}.npy, and update Student record.

Step 4/5 — Added ArcFaceRecognizer hot-reload integration.
"""

from __future__ import annotations

import logging
import tempfile
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.ai_worker import verify_admin_key
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.db.session import get_db_session, get_session_factory
from app.models.student import Student, EnrollmentStatusEnum, upsert_student
from app.vision.enrollment import (
    EnrollmentConfig,
    build_enrollment_database,
    load_enrollment_database,
    process_image_enrollment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/enrollment", tags=["enrollment"])

# Global ArcFace recognizer instance for hot-reload
_arcface_recognizer = None

def get_arcface_recognizer():
    """Get or create the global ArcFace recognizer."""
    global _arcface_recognizer
    if _arcface_recognizer is None:
        try:
            from pipeline_engine.inference.face_recognition import create_arcface_recognizer
            _arcface_recognizer = create_arcface_recognizer()
            _arcface_recognizer.initialize()
        except Exception as e:
            logger.warning(f"Could not initialize ArcFace recognizer: {e}")
    return _arcface_recognizer


def _reload_enrollment_database() -> Dict[str, Any]:
    """Reload enrollment database and return metadata."""
    global _enrollment_metadata_cache, _enrollment_embeddings_cache
    
    output_dir = _get_output_dir()
    embeddings_path = output_dir / "embeddings.npy"
    metadata_path = output_dir / "embeddings.npy.metadata.json"
    
    if not embeddings_path.exists() or not metadata_path.exists():
        return {
            "success": False,
            "error": "Enrollment database files not found",
            "previous_version": None,
            "preserved_previous": True
        }
    
    try:
        embeddings, metadata = load_enrollment_database(str(output_dir))
        
        _enrollment_embeddings_cache = embeddings
        _enrollment_metadata_cache = metadata
        
        person_counts: Dict[str, int] = {}
        for prov in metadata.sample_provenance:
            pid = prov.get("person_id")
            if pid:
                person_counts[pid] = person_counts.get(pid, 0) + 1
        
        return {
            "success": True,
            "previous_version": _enrollment_metadata_cache.creation_timestamp if _enrollment_metadata_cache else None,
            "new_version": metadata.creation_timestamp,
            "persons_loaded": len(metadata.person_ids),
            "vectors_loaded": len(embeddings),
            "embedding_dimension": metadata.embedding_dimension,
            "model_sha256": metadata.model_sha256,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
    except Exception as e:
        logger.exception("Failed to reload enrollment database")
        return {
            "success": False,
            "error": f"Enrollment reload failed: {e}",
            "previous_version": _enrollment_metadata_cache.creation_timestamp if _enrollment_metadata_cache else None,
            "preserved_previous": True
        }


class EnrollmentResponse(BaseModel):
    """Response for successful enrollment."""
    success: bool = True
    student_id: str
    name: str
    role: str
    student_class: Optional[str] = None
    vector_count: int
    embedding_dimension: int
    model_sha256: str
    output_directory: str
    npy_path: Optional[str] = None
    npy_filename: Optional[str] = None


class EnrollmentErrorResponse(BaseModel):
    """Response for enrollment failure."""
    success: bool = False
    error: str
    person_id: Optional[str] = None


def _get_output_dir() -> Path:
    """Get the enrollment output directory."""
    from app.config.settings import _get_repository_root
    repo_root = _get_repository_root()
    output_dir = repo_root / "app" / "data" / "enrollment"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@router.post("/persons", response_model=EnrollmentResponse)
async def enroll_person(
    student_id: str = Form(..., description="Student ID (must exist in student roster)"),
    name: str = Form(..., description="Full name"),
    role: str = Form(..., description="Role (student, staff, visitor)"),
    student_class: Optional[str] = Form(None, description="Class name (optional, for display)"),
    image: UploadFile = File(...),
) -> EnrollmentResponse:
    """
    Enroll a student from an uploaded image.

    Accepts multipart/form-data with:
    - student_id: Student identifier (must exist in students table, e.g., HS2026_10A1_01)
    - name: Full name
    - role: Role (student, staff, visitor)
    - student_class: Class name (optional, for display)
    - image: JPEG/PNG image file

    Delegates to existing enrollment pipeline:
    1. Validates student_id exists in Student table
    2. Saves image to temporary file
    3. Calls process_image_enrollment()
    4. Calls build_enrollment_database() (for composite compatibility)
    4. Saves per-person NPY to app/data/embeddings/{student_id}.npy
    5. Updates Student.embedding_path and Student.enrollment_status
    6. Returns result
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    allowed_extensions = {".jpg", ".jpeg", ".png"}
    filename = image.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}. Allowed: {', '.join(allowed_extensions)}")

    output_dir = _get_output_dir()
    embeddings_dir = output_dir.parent / "embeddings"
    embeddings_dir.mkdir(parents=True, exist_ok=True)

    # Validate student_id exists in database
    async with get_db_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Student).where(Student.student_id == student_id))
        student = result.scalar_one_or_none()
        
        if not student:
            raise HTTPException(
                status_code=404, 
                detail=f"Student {student_id} not found in roster. Import roster first via POST /api/v1/students/import"
            )
        
        # Verify name matches (optional check)
        if student.full_name != name:
            logger.warning(f"Name mismatch: roster has '{student.full_name}', enrollment has '{name}'")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            content = await image.read()
            tmp.write(content)
        except Exception as e:
            logger.exception("Failed to save uploaded image")
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Failed to save uploaded image: {e}")

    try:
        config = EnrollmentConfig()

        result = process_image_enrollment(
            image_path=str(tmp_path),
            person_id=student_id,  # Use student_id as person_id
            config=config,
        )

        accepted_count = len(result.accepted_samples)
        if accepted_count == 0:
            reasons = [r.get("rejection_reason", "unknown") for r in result.rejected_samples]
            error_msg = f"No face accepted for enrollment. Rejections: {', '.join(reasons) if reasons else 'no detections'}"
            raise HTTPException(status_code=400, detail=error_msg)

        model_sha256 = config.arcface_inference.model_def.expected_sha256
        embeddings_path, metadata_path = build_enrollment_database(
            results=[result],
            output_dir=str(output_dir),
            model_sha256=model_sha256,
        )

        # Export per-person NPY to app/data/embeddings/{student_id}.npy (SSOT)
        per_person_npy_path = embeddings_dir / f"{student_id}.npy"
        if result.accepted_samples:
            embedding = result.accepted_samples[0].embedding
            embedding_arr = np.asarray(embedding, dtype=np.float32)
            np.save(str(per_person_npy_path), embedding_arr)
            npy_filename = f"{student_id}.npy"
            npy_path = str(per_person_npy_path)
        else:
            npy_filename = None
            npy_path = None

        # Update Student record with embedding path and enrollment status
        async with get_db_session() as session:
            await upsert_student(
                session=session,
                student_id=student_id,
                full_name=name,
                class_id=student.class_id,
                date_of_birth=student.date_of_birth,
                gender=student.gender,
                parent_phone=student.parent_phone,
                embedding_path=npy_path,
            )

        # Trigger ArcFace hot-reload (Step 5)
        recognizer = get_arcface_recognizer()
        if recognizer:
            reload_result = recognizer.reload_gallery(get_session_factory())
            logger.info(f"ArcFace hot-reload after enrollment: {reload_result}")

        embeddings, metadata = load_enrollment_database(str(output_dir))

        return EnrollmentResponse(
            student_id=student_id,
            name=name,
            role=role,
            student_class=student_class,
            vector_count=accepted_count,
            embedding_dimension=metadata.embedding_dimension,
            model_sha256=model_sha256[:16] + "...",
            output_directory=str(output_dir),
            npy_path=npy_path,
            npy_filename=npy_filename,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Enrollment failed")
        raise HTTPException(status_code=500, detail=f"Enrollment failed: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/persons", response_model=List[Dict[str, Any]])
async def list_enrolled_persons() -> List[Dict[str, Any]]:
    """List all enrolled persons from the Student database and enrollment metadata."""
    output_dir = _get_output_dir()
    embeddings_path = output_dir / "embeddings.npy"
    metadata_path = output_dir / "embeddings.npy.metadata.json"
    
    # Get students from database
    students_list = []
    async with get_db_session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Student))
        students = result.scalars().all()
        
        for student in students:
            # Get vector count from enrollment metadata if available
            vector_count = 0
            face_quality = 0.0
            if embeddings_path.exists() and metadata_path.exists():
                try:
                    embeddings, metadata = load_enrollment_database(str(output_dir))
                    for prov in metadata.sample_provenance:
                        if prov.get("person_id") == student.student_id:
                            vector_count += 1
                            face_quality = prov.get("quality_score", 0.0)
                except Exception:
                    pass
            
            students_list.append({
                "student_id": student.student_id,
                "name": student.full_name,
                "role": "student",
                "student_class": student.class_id,
                "face_quality": face_quality,
                "vector_count": vector_count,
                "enrollment_status": student.enrollment_status.value,
                "embedding_path": student.embedding_path,
                "is_active": student.is_active,
            })
    
    return students_list


# =============================================================================
# Phase 0.2.2 — NPY Reload Endpoint
# =============================================================================

from datetime import datetime


class EnrollmentReloadRequest(BaseModel):
    """Request for enrollment reload."""
    trigger: str = Field(default="manual", description="Trigger type: manual, file_watcher, api")
    expected_version: Optional[str] = Field(default=None, description="Expected enrollment version (optional)")


class EnrollmentReloadResponse(BaseModel):
    """Response for enrollment reload."""
    success: bool
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    persons_loaded: int = 0
    vectors_loaded: int = 0
    embedding_dimension: int = 0
    model_sha256: Optional[str] = None
    error: Optional[str] = None
    preserved_previous: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@router.post("/reload", response_model=EnrollmentReloadResponse, dependencies=[Depends(verify_admin_key)])
async def reload_enrollment(request: EnrollmentReloadRequest = None, _: bool = Depends(verify_admin_key)) -> EnrollmentReloadResponse:
    """
    Reload enrollment database and trigger ArcFace recognizer hot-reload.
    
    Triggered by:
    - Manual admin action
    - File watcher detecting NPY changes
    - PipelineEngine health endpoint detecting version change
    
    Behavior:
    - Validates NPY dimensions and metadata
    - Triggers ArcFace recognizer to reload from student database
    - Returns explicit success/failure and version info
    """
    # Reload legacy composite database
    result = _reload_enrollment_database()
    
    # Trigger ArcFace hot-reload (Step 5)
    recognizer = get_arcface_recognizer()
    if recognizer:
        recognizer_result = recognizer.reload_gallery(get_session_factory())
        result["arcface_reload"] = recognizer_result
        logger.info(f"ArcFace hot-reload triggered: {recognizer_result}")
    
    # Check expected version if provided
    if request and request.expected_version:
        if result.get("new_version") != request.expected_version:
            logger.warning(f"Expected version {request.expected_version}, got {result.get('new_version')}")
    
    return EnrollmentReloadResponse(
        success=result.get("success", False),
        previous_version=result.get("previous_version"),
        new_version=result.get("new_version"),
        persons_loaded=result.get("persons_loaded", 0),
        vectors_loaded=result.get("vectors_loaded", 0),
        embedding_dimension=result.get("embedding_dimension", 0),
        model_sha256=result.get("model_sha256"),
        error=result.get("error"),
        preserved_previous=result.get("preserved_previous", False),
    )


@router.get("/reload/status", response_model=EnrollmentReloadResponse, dependencies=[Depends(verify_admin_key)])
async def get_enrollment_reload_status(_: bool = Depends(verify_admin_key)) -> EnrollmentReloadResponse:
    """Get current enrollment database status without reloading."""
    global _enrollment_metadata_cache
    
    if _enrollment_metadata_cache is None:
        # Try to load
        result = _reload_enrollment_database()
    else:
        result = {
            "success": True,
            "previous_version": None,
            "new_version": _enrollment_metadata_cache.creation_timestamp,
            "persons_loaded": len(_enrollment_metadata_cache.person_ids),
            "vectors_loaded": len(_enrollment_embeddings_cache) if _enrollment_embeddings_cache is not None else 0,
            "embedding_dimension": _enrollment_metadata_cache.embedding_dimension,
            "model_sha256": _enrollment_metadata_cache.model_sha256,
        }
    
    return EnrollmentReloadResponse(
        success=result.get("success", False),
        previous_version=None,
        new_version=result.get("new_version"),
        persons_loaded=result.get("persons_loaded", 0),
        vectors_loaded=result.get("vectors_loaded", 0),
        embedding_dimension=result.get("embedding_dimension", 0),
        model_sha256=result.get("model_sha256"),
    )