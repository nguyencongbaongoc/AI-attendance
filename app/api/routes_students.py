"""
FastAPI router for Student Roster management.
"""

from __future__ import annotations

import logging
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session, get_session_factory, init_database
from app.models.student import (
    Student,
    Class,
    EnrollmentStatusEnum,
    upsert_student,
    get_or_create_class,
)
from app.services.excel_roster_service import import_students_from_excel, ImportResult, ValidationError

logger = logging.getLogger(__name__)

# Try to get ArcFace recognizer for hot-reload
try:
    from app.api.enrollment import get_arcface_recognizer
except ImportError:
    get_arcface_recognizer = None

router = APIRouter(prefix="/api/v1/students", tags=["students"])


# Pydantic models
class StudentResponse(BaseModel):
    """Student response model."""
    student_id: str
    full_name: str
    class_id: str
    class_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: str
    parent_phone: Optional[str] = None
    embedding_path: Optional[str] = None
    enrollment_status: str
    is_active: bool
    created_at: str
    updated_at: str


class ClassResponse(BaseModel):
    """Class response model."""
    class_id: str
    class_name: str
    grade_level: int
    shift_start_time: Optional[str] = None
    late_threshold_time: Optional[str] = None
    student_count: int = 0


class StudentCreateRequest(BaseModel):
    """Request model for creating a student."""
    student_id: str = Field(..., min_length=1, max_length=32)
    full_name: str = Field(..., min_length=1, max_length=150)
    class_id: str = Field(..., min_length=1, max_length=20)
    date_of_birth: Optional[str] = None
    gender: str = "OTHER"
    parent_phone: Optional[str] = None


class StudentUpdateRequest(BaseModel):
    """Request model for updating a student."""
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    class_id: Optional[str] = Field(None, min_length=1, max_length=20)
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    parent_phone: Optional[str] = None
    is_active: Optional[bool] = None


class ImportResponse(BaseModel):
    """Response model for import operation."""
    imported: int
    updated: int
    errors: List[dict]


async def get_session() -> AsyncSession:
    """Dependency to get database session."""
    async with get_db_session() as session:
        yield session


@router.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    await init_database()


@router.post("/import", response_model=ImportResponse)
async def import_students(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV file with student roster"),
    session: AsyncSession = Depends(get_session),
):
    """
    Import students from Excel/CSV file.
    
    Required columns (case-insensitive, supports Vietnamese):
    - student_id / Mã học sinh
    - full_name / Họ và tên
    - class_name / Lớp
    
    Optional columns:
    - date_of_birth / Ngày sinh
    - gender / Giới tính
    - parent_phone / Số điện thoại phụ huynh
    
    Returns:
        Import summary with counts and any validation errors.
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided"
        )
    
    allowed_extensions = {".xlsx", ".xls", ".csv"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)
    
    try:
        # Import students
        result = await import_students_from_excel(session, tmp_path)
        
        # Format errors for response
        errors = [
            {
                "row": e.row_number,
                "column": e.column,
                "value": e.value,
                "message": e.message,
            }
            for e in result.errors
        ]
        
        # Trigger ArcFace hot-reload if any students have embeddings (auto-linked during import)
        if get_arcface_recognizer:
            recognizer = get_arcface_recognizer()
            if recognizer:
                reload_result = recognizer.reload_gallery(get_session_factory())
                logger.info(f"ArcFace hot-reload after roster import: {reload_result}")
        
        return ImportResponse(
            imported=result.imported,
            updated=result.updated,
            errors=errors,
        )
    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink()
        except:
            pass


@router.get("", response_model=List[StudentResponse])
async def list_students(
    class_id: Optional[str] = None,
    enrollment_status: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """
    List students with optional filters.
    """
    query = select(Student, Class.class_name).join(Class, Student.class_id == Class.class_id)
    
    if class_id:
        query = query.where(Student.class_id == class_id)
    if enrollment_status:
        query = query.where(Student.enrollment_status == enrollment_status)
    if is_active is not None:
        query = query.where(Student.is_active == is_active)
    
    query = query.order_by(Student.class_id, Student.student_id).limit(limit).offset(offset)
    
    result = await session.execute(query)
    rows = result.all()
    
    return [
        StudentResponse(
            student_id=student.student_id,
            full_name=student.full_name,
            class_id=student.class_id,
            class_name=class_name,
            date_of_birth=student.date_of_birth.isoformat() if student.date_of_birth else None,
            gender=student.gender,
            parent_phone=student.parent_phone,
            embedding_path=student.embedding_path,
            enrollment_status=student.enrollment_status.value,
            is_active=student.is_active,
            created_at=student.created_at.isoformat(),
            updated_at=student.updated_at.isoformat(),
        )
        for student, class_name in rows
    ]


@router.get("/classes", response_model=List[ClassResponse])
async def list_classes(
    session: AsyncSession = Depends(get_session),
):
    """List all classes with student counts."""
    query = select(Class).order_by(Class.class_id)
    result = await session.execute(query)
    classes = result.scalars().all()
    
    # Get student counts per class
    count_query = select(Student.class_id, func.count(Student.student_id)).group_by(Student.class_id)
    count_result = await session.execute(count_query)
    counts = {class_id: count for class_id, count in count_result.all()}
    
    return [
        ClassResponse(
            class_id=c.class_id,
            class_name=c.class_name,
            grade_level=c.grade_level,
            shift_start_time=c.shift_start_time,
            late_threshold_time=c.late_threshold_time,
            student_count=counts.get(c.class_id, 0),
        )
        for c in classes
    ]


@router.post("/classes", response_model=ClassResponse, status_code=status.HTTP_201_CREATED)
async def create_class(
    class_id: str,
    class_name: str,
    grade_level: int = 10,
    session: AsyncSession = Depends(get_session),
):
    """Create a new class."""
    class_obj = await get_or_create_class(session, class_id, class_name, grade_level)
    await session.flush()
    
    return ClassResponse(
        class_id=class_obj.class_id,
        class_name=class_obj.class_name,
        grade_level=class_obj.grade_level,
        shift_start_time=class_obj.shift_start_time,
        late_threshold_time=class_obj.late_threshold_time,
        student_count=0,
    )
@router.get("/count")
async def get_students_count(
    class_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """Get total count of active students."""
    query = select(func.count(Student.student_id)).where(Student.is_active == True)
    if class_id:
        query = query.where(Student.class_id == class_id)
    result = await session.execute(query)
    count = result.scalar() or 0
    return {"count": count, "total": count}


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a single student by ID."""
    query = select(Student, Class.class_name).join(Class, Student.class_id == Class.class_id).where(Student.student_id == student_id)
    result = await session.execute(query)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail=f"Student {student_id} not found")
    
    student, class_name = row
    return StudentResponse(
        student_id=student.student_id,
        full_name=student.full_name,
        class_id=student.class_id,
        class_name=class_name,
        date_of_birth=student.date_of_birth.isoformat() if student.date_of_birth else None,
        gender=student.gender,
        parent_phone=student.parent_phone,
        embedding_path=student.embedding_path,
        enrollment_status=student.enrollment_status.value,
        is_active=student.is_active,
        created_at=student.created_at.isoformat(),
        updated_at=student.updated_at.isoformat(),
    )


@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    data: StudentCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new student."""
    # Validate class exists
    class_result = await session.execute(select(Class).where(Class.class_id == data.class_id))
    class_obj = class_result.scalar_one_or_none()
    
    if not class_obj:
        # Auto-create class
        class_obj = await get_or_create_class(session, data.class_id, data.class_id)
    
    # Check for duplicate
    existing = await session.execute(select(Student).where(Student.student_id == data.student_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Student {data.student_id} already exists")
    
    # Parse date_of_birth if provided
    dob = None
    if data.date_of_birth:
        try:
            from datetime import datetime
            dob = datetime.strptime(data.date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_of_birth format. Use YYYY-MM-DD")
    
    student = await upsert_student(
        session=session,
        student_id=data.student_id,
        full_name=data.full_name,
        class_id=data.class_id,
        date_of_birth=dob,
        gender=data.gender,
        parent_phone=data.parent_phone,
    )
    
    await session.refresh(student)
    
    return StudentResponse(
        student_id=student.student_id,
        full_name=student.full_name,
        class_id=student.class_id,
        class_name=class_obj.class_name,
        date_of_birth=student.date_of_birth.isoformat() if student.date_of_birth else None,
        gender=student.gender,
        parent_phone=student.parent_phone,
        embedding_path=student.embedding_path,
        enrollment_status=student.enrollment_status.value,
        is_active=student.is_active,
        created_at=student.created_at.isoformat(),
        updated_at=student.updated_at.isoformat(),
    )


@router.patch("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    data: StudentUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a student."""
    result = await session.execute(select(Student).where(Student.student_id == student_id))
    student = result.scalar_one_or_none()
    
    if not student:
        raise HTTPException(status_code=404, detail=f"Student {student_id} not found")
    
    if data.full_name is not None:
        student.full_name = data.full_name
    if data.class_id is not None:
        # Validate class exists
        class_result = await session.execute(select(Class).where(Class.class_id == data.class_id))
        if not class_result.scalar_one_or_none():
            class_obj = await get_or_create_class(session, data.class_id, data.class_id)
        student.class_id = data.class_id
    if data.date_of_birth is not None:
        try:
            from datetime import datetime
            student.date_of_birth = datetime.strptime(data.date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_of_birth format. Use YYYY-MM-DD")
    if data.gender is not None:
        student.gender = data.gender
    if data.parent_phone is not None:
        student.parent_phone = data.parent_phone
    if data.is_active is not None:
        student.is_active = data.is_active
    
    await session.flush()
    await session.refresh(student)
    
    return StudentResponse(
        student_id=student.student_id,
        full_name=student.full_name,
        class_id=student.class_id,
        class_name=None,
        date_of_birth=student.date_of_birth.isoformat() if student.date_of_birth else None,
        gender=student.gender,
        parent_phone=student.parent_phone,
        embedding_path=student.embedding_path,
        enrollment_status=student.enrollment_status.value,
        is_active=student.is_active,
        created_at=student.created_at.isoformat(),
        updated_at=student.updated_at.isoformat(),
    )


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a student (soft delete - marks inactive)."""
    result = await session.execute(select(Student).where(Student.student_id == student_id))
    student = result.scalar_one_or_none()
    
    if not student:
        raise HTTPException(status_code=404, detail=f"Student {student_id} not found")
    
    student.is_active = False
    await session.flush()




@router.post("/enroll", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def enroll_student(
    payload: StudentCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    Enroll a new student with optional face embedding.
    
    Creates the student record in the database.
    If a face photo is provided (base64 or uploaded), it would be processed by ArcFace
    to generate and store the embedding vector.
    """
    # Validate class exists
    class_obj = await get_or_create_class(session, payload.class_id, payload.class_id, 10)
    
    # Check if student already exists
    existing = await session.execute(
        select(Student).where(Student.student_id == payload.student_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Student {payload.student_id} already exists"
        )
    
    # Create student record
    student = Student(
        student_id=payload.student_id,
        full_name=payload.full_name,
        class_id=payload.class_id,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
        parent_phone=payload.parent_phone,
        enrollment_status=EnrollmentStatusEnum.ENROLLED,
        is_active=True,
    )
    
    session.add(student)
    await session.flush()
    
    # Trigger ArcFace hot-reload if available
    if get_arcface_recognizer:
        recognizer = get_arcface_recognizer()
        if recognizer:
            reload_result = recognizer.reload_gallery(get_session_factory())
            logger.info(f"ArcFace hot-reload after student enroll: {reload_result}")
    
    # Return student response with class name
    return StudentResponse(
        student_id=student.student_id,
        full_name=student.full_name,
        class_id=student.class_id,
        class_name=class_obj.class_name,
        date_of_birth=student.date_of_birth.isoformat() if student.date_of_birth else None,
        gender=student.gender,
        parent_phone=student.parent_phone,
        embedding_path=student.embedding_path,
        enrollment_status=student.enrollment_status.value,
        is_active=student.is_active,
        created_at=student.created_at.isoformat(),
        updated_at=student.updated_at.isoformat(),
    )