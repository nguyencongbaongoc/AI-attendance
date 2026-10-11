"""
SQLAlchemy models for Student Roster.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class EnrollmentStatusEnum(str, enum.Enum):
    """Student enrollment status."""
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    INACTIVE = "INACTIVE"


class Student(Base):
    """Student model - SSOT is student_id."""
    
    __tablename__ = "students"
    
    student_id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        comment="Canonical student identifier (from Excel roster)"
    )
    full_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Full name (UTF-8)"
    )
    class_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("classes.class_id"),
        nullable=False,
        index=True,
        comment="Foreign key to Class"
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Date of birth"
    )
    gender: Mapped[str] = mapped_column(
        String(10),
        default="OTHER",
        nullable=False,
        comment="Gender (MALE, FEMALE, OTHER)"
    )
    parent_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Parent/guardian phone number"
    )
    embedding_path: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Path to face embedding NPY file"
    )
    enrollment_status: Mapped[EnrollmentStatusEnum] = mapped_column(
        Enum(EnrollmentStatusEnum, values_callable=lambda x: [e.value for e in x]),
        default=EnrollmentStatusEnum.PENDING,
        nullable=False,
        index=True,
        comment="Face enrollment status"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="Whether student is currently active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Relationships
    class_: Mapped["Class"] = relationship("Class", back_populates="students")
    
    def __repr__(self) -> str:
        return f"<Student(student_id={self.student_id}, name={self.full_name}, class={self.class_id})>"


class Class(Base):
    """Class/Section model."""
    
    __tablename__ = "classes"
    
    class_id: Mapped[str] = mapped_column(
        String(20),
        primary_key=True,
        comment="Class identifier (e.g., 10A1, 10A2)"
    )
    class_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Display name"
    )
    grade_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,
        comment="Grade level (e.g., 10, 11, 12)"
    )
    shift_start_time: Mapped[Optional[str]] = mapped_column(
        String(8),  # HH:MM:SS
        nullable=True,
        comment="Morning shift start time"
    )
    late_threshold_time: Mapped[Optional[str]] = mapped_column(
        String(8),  # HH:MM:SS
        nullable=True,
        comment="Late arrival threshold"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    
    # Relationships
    students: Mapped[list["Student"]] = relationship("Student", back_populates="class_")
    
    def __repr__(self) -> str:
        return f"<Class(class_id={self.class_id}, name={self.class_name}, grade={self.grade_level})>"


async def get_or_create_class(session, class_id: str, class_name: str, grade_level: int = 10) -> Class:
    """
    Get existing class or create new one.
    
    Args:
        session: Database session
        class_id: Class identifier
        class_name: Display name
        grade_level: Grade level (default 10)
        
    Returns:
        Class instance
    """
    result = await session.execute(select(Class).where(Class.class_id == class_id))
    class_obj = result.scalar_one_or_none()
    
    if class_obj is None:
        class_obj = Class(
            class_id=class_id,
            class_name=class_name,
            grade_level=grade_level,
        )
        session.add(class_obj)
        await session.flush()
    
    return class_obj


async def upsert_student(
    session,
    student_id: str,
    full_name: str,
    class_id: str,
    date_of_birth: Optional[date] = None,
    gender: str = "OTHER",
    parent_phone: Optional[str] = None,
    embedding_path: Optional[str] = None,
) -> Student:
    """
    Upsert student record (insert or update).
    
    Args:
        session: Database session
        student_id: Canonical student ID
        full_name: Student full name
        class_id: Class ID (must exist)
        date_of_birth: Date of birth
        gender: Gender
        parent_phone: Parent phone
        embedding_path: Path to embedding NPY file
        
    Returns:
        Student instance
    """
    result = await session.execute(select(Student).where(Student.student_id == student_id))
    student = result.scalar_one_or_none()
    
    if student is None:
        # Create new student
        student = Student(
            student_id=student_id,
            full_name=full_name,
            class_id=class_id,
            date_of_birth=date_of_birth,
            gender=gender,
            parent_phone=parent_phone,
            embedding_path=embedding_path,
            enrollment_status=EnrollmentStatusEnum.PENDING,
        )
        session.add(student)
    else:
        # Update existing student (preserve embedding_path if not provided)
        student.full_name = full_name
        student.class_id = class_id
        student.date_of_birth = date_of_birth
        student.gender = gender
        student.parent_phone = parent_phone
        if embedding_path is not None:
            student.embedding_path = embedding_path
            student.enrollment_status = EnrollmentStatusEnum.ENROLLED
    
    await session.flush()
    return student