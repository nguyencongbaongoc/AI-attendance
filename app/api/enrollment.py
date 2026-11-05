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
import base64
import cv2
from datetime import datetime
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.ai_worker import verify_admin_key
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.db.session import get_db_session, get_session_factory
from app.models.student import Student, Class, EnrollmentStatusEnum, upsert_student, get_or_create_class
from app.vision.enrollment import (
    EnrollmentConfig,
    build_enrollment_database,
    load_enrollment_database,
    process_image_enrollment,
    align_face_with_landmarks,
)
from app.vision.crop import safe_crop_face
from app.vision.detection import FaceDetection, create_face_detector
from app.vision.arcface_inference import create_arcface_inference
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType

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
    person_id: Optional[str] = None
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


REFERENCE_LANDMARKS = np.array([
    [38.2946, 51.6963],  # left eye
    [73.5318, 51.5014],  # right eye
    [56.0252, 71.7366],  # nose
    [41.5493, 92.3655],  # left mouth
    [70.7299, 92.2041]   # right mouth
], dtype=np.float32)


def process_face_pipeline(
    image_bgr: np.ndarray,
) -> Tuple[Optional[FaceDetection], Optional[np.ndarray], Optional[np.ndarray], float]:
    """
    Scale with aspect ratio preservation (max dim <= 1280px),
    detect 5 landmarks via SCRFD (threshold 0.5 then retry with 0.35, largest face by area),
    and perform 112x112 similarity transform affine warp.
    Returns:
        (best_detection_in_orig_coords, aligned_112_bgr, embedding_512, scale)
    """
    orig_h, orig_w = image_bgr.shape[:2]
    max_dim = max(orig_h, orig_w)
    if max_dim > 1280:
        scale = 1280.0 / max_dim
        new_w = int(round(orig_w * scale))
        new_h = int(round(orig_h * scale))
        proc_bgr = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        scale = 1.0
        proc_bgr = image_bgr

    proc_h, proc_w = proc_bgr.shape[:2]
    frame_meta = FrameMetadata(
        source_type=SourceType.IMAGE,
        source_id="enrollment",
        frame_index=0,
        timestamp=datetime.utcnow(),
        original_width=proc_w,
        original_height=proc_h,
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
    )
    frame = CanonicalFrame(data=proc_bgr, metadata=frame_meta)

    # 1. Try detector at confidence 0.5
    detector_50 = create_face_detector(confidence_threshold=0.5)
    detections = detector_50.detect(frame)

    # 2. If no face detected at 0.5, retry with threshold 0.35
    if not detections:
        detector_35 = create_face_detector(confidence_threshold=0.35)
        detections = detector_35.detect(frame)

    if not detections:
        return None, None, None, scale

    # 3. If multiple faces detected, pick the largest face by area
    best_det = max(detections, key=lambda d: d.area)

    # Map detection coordinates back to original image
    best_det_orig = FaceDetection(
        bbox=(
            float(best_det.bbox[0] / scale),
            float(best_det.bbox[1] / scale),
            float(best_det.bbox[2] / scale),
            float(best_det.bbox[3] / scale),
        ),
        confidence=float(best_det.confidence),
        landmarks5=[(float(lx / scale), float(ly / scale)) for lx, ly in best_det.landmarks5],
        detection_id=best_det.detection_id,
        coordinate_space=best_det.coordinate_space,
        model_id=best_det.model_id,
        model_sha256=best_det.model_sha256,
        frame_index=best_det.frame_index,
        source_id=best_det.source_id,
    )

    # 4. Standard 5-landmark affine similarity transform to (112, 112)
    # Using landmarks on proc_bgr directly
    src_pts = np.array(best_det.landmarks5, dtype=np.float32)
    M, _ = cv2.estimateAffinePartial2D(src_pts, REFERENCE_LANDMARKS, method=cv2.LMEDS)
    if M is None:
        M, _ = cv2.estimateAffine2D(src_pts, REFERENCE_LANDMARKS)
    if M is None:
        aligned_112 = cv2.resize(proc_bgr, (112, 112))
    else:
        aligned_112 = cv2.warpAffine(proc_bgr, M, (112, 112), borderValue=0.0)

    # 5. Extract ArcFace embedding (512-D L2-normalized) using ArcFace TensorRT engine with fallback
    norm_emb = None
    recognizer = get_arcface_recognizer()
    if recognizer is not None and getattr(recognizer, "_initialized", False):
        try:
            import torch
            face_tensor = torch.from_numpy(aligned_112).to(recognizer.device)
            prep_tensor = recognizer.preprocess(face_tensor)
            raw_emb, _ = recognizer.infer_raw(prep_tensor)
            emb_np = raw_emb.detach().cpu().numpy().flatten().astype(np.float32)
            norm = float(np.linalg.norm(emb_np))
            if norm > 0:
                norm_emb = emb_np / norm
            else:
                norm_emb = emb_np
        except Exception as e:
            logger.warning(f"TensorRT ArcFace inference failed, falling back: {e}")

    if norm_emb is None:
        arcface_inference = create_arcface_inference(providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        arcface_result = arcface_inference.infer(aligned_112)
        norm_emb = arcface_result.normalized_embedding.flatten().astype(np.float32)
        norm = float(np.linalg.norm(norm_emb))
        if norm > 0:
            norm_emb = norm_emb / norm

    return best_det_orig, aligned_112, norm_emb, scale


@router.post("/detect")
async def detect_face_in_image(
    image: UploadFile = File(...),
):
    """
    Detect face in image, crop and align with 5-landmark affine transform (112x112),
    and compute preview ArcFace embedding.
    Returns detection bbox, cropped face data URL, and 512-D embedding preview.
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    allowed_extensions = {".jpg", ".jpeg", ".png"}
    filename = image.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}")

    content = await image.read()
    image_bgr = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise HTTPException(status_code=400, detail="Failed to decode image")

    img_h, img_w = image_bgr.shape[:2]
    best_det, aligned_112, norm_emb, scale = process_face_pipeline(image_bgr)

    if best_det is None or aligned_112 is None or norm_emb is None:
        return {
            "success": False,
            "detected": False,
            "message": "Không tìm thấy khuôn mặt trong ảnh"
        }

    x1, y1, x2, y2 = [int(round(c)) for c in best_det.bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img_w, x2), min(img_h, y2)

    success, buf = cv2.imencode('.jpg', aligned_112)
    crop_b64 = base64.b64encode(buf).decode('ascii') if success else ""

    l2_norm = float(np.linalg.norm(norm_emb))
    emb_list = [float(v) for v in norm_emb]

    return {
        "success": True,
        "detected": True,
        "confidence": round(float(best_det.confidence), 4),
        "bbox": [x1, y1, x2, y2],
        "norm_bbox": {
            "left": round((x1 / img_w) * 100, 2),
            "top": round((y1 / img_h) * 100, 2),
            "width": round(((x2 - x1) / img_w) * 100, 2),
            "height": round(((y2 - y1) / img_h) * 100, 2),
        },
        "crop_data_url": f"data:image/jpeg;base64,{crop_b64}",
        "embedding": emb_list,
        "embedding_preview": [round(float(v), 3) for v in emb_list[:8]],
        "dimension": len(emb_list),
        "l2_norm": round(l2_norm, 3),
    }


@router.post("/persons", response_model=EnrollmentResponse)
async def enroll_person(
    student_id: Optional[str] = Form(None, description="Student ID (e.g. HS2026_10A1_01)"),
    person_id: Optional[str] = Form(None, description="Person ID alias"),
    name: str = Form(..., description="Full name"),
    role: str = Form("student", description="Role (student, staff, visitor)"),
    student_class: Optional[str] = Form(None, description="Class name (optional, for display)"),
    image: UploadFile = File(...),
) -> EnrollmentResponse:
    """
    Enroll a student/person from an uploaded image.
    Performs aspect-ratio preserved scaling, SCRFD detection, standard 5-landmark
    affine similarity alignment to 112x112, generates 512-D L2-normalized ArcFace embedding,
    saves per-person .npy to app/data/embeddings/{student_id}.npy, updates Student in DB,
    and hot-reloads ArcFace gallery.
    """
    target_id = (student_id or person_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="student_id or person_id is required")

    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    allowed_extensions = {".jpg", ".jpeg", ".png"}
    filename = image.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}. Allowed: {', '.join(allowed_extensions)}")

    content = await image.read()
    image_bgr = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise HTTPException(status_code=400, detail="Failed to decode image")

    # Run professional pre-processing, SCRFD detection, 112x112 affine alignment, and ArcFace embedding
    best_det, aligned_112, norm_emb, scale = process_face_pipeline(image_bgr)
    if best_det is None or aligned_112 is None or norm_emb is None:
        raise HTTPException(status_code=400, detail="Không tìm thấy khuôn mặt trong ảnh để enrollment")

    output_dir = _get_output_dir()
    embeddings_dir = output_dir.parent / "embeddings"
    embeddings_dir.mkdir(parents=True, exist_ok=True)

    # Save per-person NPY: app/data/embeddings/{target_id}.npy (SSOT)
    per_person_npy_path = embeddings_dir / f"{target_id}.npy"
    embedding_arr = np.asarray(norm_emb, dtype=np.float32)
    np.save(str(per_person_npy_path), embedding_arr)
    npy_path = str(per_person_npy_path)
    npy_filename = f"{target_id}.npy"

    target_class = (student_class or "10A1").strip()
    async with get_db_session() as session:
        from sqlalchemy import select, update
        result = await session.execute(select(Student).where(Student.student_id == target_id))
        student = result.scalar_one_or_none()
        
        await get_or_create_class(session, target_class, target_class)
        student = await upsert_student(
            session=session,
            student_id=target_id,
            full_name=name,
            class_id=target_class,
            embedding_path=npy_path,
        )
        await session.execute(
            update(Student)
            .where(Student.student_id == target_id)
            .values(enrollment_status=EnrollmentStatusEnum.ENROLLED, embedding_path=npy_path, class_id=target_class)
        )

    # Hot-reload ArcFaceRecognizer gallery
    recognizer = get_arcface_recognizer()
    if recognizer:
        try:
            reload_result = recognizer.reload_gallery(get_session_factory())
            logger.info(f"ArcFace hot-reload after enrollment: {reload_result}")
        except Exception as e:
            logger.warning(f"ArcFace hot-reload failed: {e}")

    # Hot-reload CameraManager across active cameras if running
    try:
        from pipeline_engine.ingestion.camera_manager import get_camera_manager
        cm = get_camera_manager()
        if cm:
            cm.reload_gallery()
    except Exception:
        pass

    return EnrollmentResponse(
        student_id=target_id,
        person_id=target_id,
        name=name,
        role=role,
        student_class=target_class,
        vector_count=1,
        embedding_dimension=len(norm_emb),
        model_sha256="glintr100",
        output_directory=str(output_dir),
        npy_path=npy_path,
        npy_filename=npy_filename,
    )


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
                "person_id": student.student_id,
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