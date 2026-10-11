"""
Phase 8 — Offline Face Detection, Crop, Landmark & Quality Pipeline.
Phase 10 — Person ↔ Face Association.

This module provides the offline face processing pipeline:
- Face Detection (model-independent via FaceDetectorInterface)
- SCRFD Face Detector Adapter (640x640)
- RetinaFace Placeholder (not yet implemented)
- Safe Face Crop
- 1K3D68 Landmark Detection
- Face Quality Assessment
- Canonical Face Sample
- Person-Face Association (Phase 10)

All components are OFFLINE ONLY - no camera access, no streaming.
"""

from __future__ import annotations

# Phase 8: Model-independent detector contract and interface
from app.vision.detector_contract import (
    FaceDetectionContract,
    FaceDetectorInterface,
    DetectorModelId,
    DetectorStatus,
    DetectorProvenance,
    create_detector_provenance,
)

# Phase 8: Detector adapters
from app.vision.scrfd_adapter import SCRFDAdapter, create_scrfd_adapter
from app.vision.retinaface_adapter import RetinaFaceAdapter, create_retinaface_adapter, RetinaFaceNotImplementedError
from app.vision.detector_factory import get_detector, list_available_detectors, get_detector_status

# Phase 7: SCRFD-specific (kept for backward compatibility during transition)
from app.vision.detection import FaceDetector, FaceDetection, DetectionError, CoordinateSpace

# Phase 7: Crop, Landmarks, Quality, Face Sample
from app.vision.crop import FaceCrop, CropError, safe_crop_face
from app.vision.landmarks import LandmarkDetector, LandmarkResult, LandmarkError
from app.vision.quality import FaceQuality, QualityAssessor, QualityDecision
from app.vision.face_sample import FaceSample, FaceSampleCollection

# Phase 10: Person-Face Association
from app.vision.association_contract import (
    AssociationStatus,
    PersonFaceAssociation,
    AssociationResult,
    create_association_from_detections,
)
from app.vision.association_geometry import (
    bbox_area,
    bbox_intersection,
    intersection_area,
    iou,
    intersection_over_face,
    face_center_in_person,
    face_center_distance_to_person,
    bbox_containment,
    clip_bbox_to_frame,
    validate_bbox_4k,
    validate_coordinate_space,
    AssociationScore,
    compute_association_score,
    is_ambiguous,
    AMBIGUITY_MARGIN,
)
from app.vision.association import (
    AssociationConfig,
    CoordinateSpaceError,
    AssociationError,
    associate_detections,
    associate_detections_deterministic,
)

__all__ = [
    # Phase 8: Detector contract
    "FaceDetectionContract",
    "FaceDetectorInterface",
    "DetectorModelId",
    "DetectorStatus",
    "DetectorProvenance",
    "create_detector_provenance",
    
    # Phase 8: Detector adapters
    "SCRFDAdapter",
    "create_scrfd_adapter",
    "RetinaFaceAdapter",
    "create_retinaface_adapter",
    "RetinaFaceNotImplementedError",
    "get_detector",
    "list_available_detectors",
    "get_detector_status",
    
    # Phase 7: SCRFD-specific (backward compatibility)
    "FaceDetector",
    "FaceDetection",
    "DetectionError",
    "CoordinateSpace",
    
    # Phase 7: Crop, Landmarks, Quality, Face Sample
    "FaceCrop",
    "CropError",
    "safe_crop_face",
    "LandmarkDetector",
    "LandmarkResult",
    "LandmarkError",
    "FaceQuality",
    "QualityAssessor",
    "QualityDecision",
    "FaceSample",
    "FaceSampleCollection",
    
    # Phase 10: Person-Face Association Contract
    "AssociationStatus",
    "PersonFaceAssociation",
    "AssociationResult",
    "create_association_from_detections",
    
    # Phase 10: Person-Face Association Geometry
    "bbox_area",
    "bbox_intersection",
    "intersection_area",
    "iou",
    "intersection_over_face",
    "face_center_in_person",
    "face_center_distance_to_person",
    "bbox_containment",
    "clip_bbox_to_frame",
    "validate_bbox_4k",
    "validate_coordinate_space",
    "AssociationScore",
    "compute_association_score",
    "is_ambiguous",
    "AMBIGUITY_MARGIN",
    
    # Phase 10: Person-Face Association Engine
    "AssociationConfig",
    "CoordinateSpaceError",
    "AssociationError",
    "associate_detections",
    "associate_detections_deterministic",
]
