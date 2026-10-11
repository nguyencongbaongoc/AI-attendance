"""
Phase 16 — Adaptive Person/Face Crop Pipeline.

This module implements the adaptive crop pipeline that transforms a 4K ORIGINAL_FRAME
through YOLO person detection → dynamic person crop → face detection → dynamic face crop.

CRITICAL ARCHITECTURE RULE:
    ORIGINAL_FRAME is the source of truth.
    Never use the 640×640 YOLO tensor as the final image source for face recognition.

Pipeline:
    ORIGINAL_FRAME (3840×2160)
        ↓
    YOLO11n preprocessing (640×640 letterbox)
        ↓
    Person Detection (class 0 only)
        ↓
    Restore bbox to ORIGINAL_FRAME coordinates
        ↓
    Dynamic Person Crop from ORIGINAL_FRAME
        ↓
    Face Detection on person crop
        ↓
    Restore face bbox to person-crop coordinates
        ↓
    Dynamic Face Crop from ORIGINAL_FRAME
        ↓
    Phase 15 pose/alignment/ArcFace

All coordinates remain explicit relative to their source frame.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.detection import CoordinateSpace, FaceDetection

logger = logging.getLogger(__name__)


# =============================================================================
# COORDINATE SPACE
# =============================================================================

class CropCoordinateSpace(str, Enum):
    """Explicit coordinate space for crop geometry."""
    
    ORIGINAL_FRAME = "original_frame"
    PERSON_CROP = "person_crop"


# =============================================================================
# CROP PROVENANCE
# =============================================================================

@dataclass(frozen=True)
class CropProvenance:
    """
    Complete provenance chain for a crop.
    
    Tracks the full lineage from original frame through detection to crop.
    """
    
    # Source identification
    source_type: str  # "image", "video", etc.
    source_id: str  # filename or stream id
    frame_index: int
    timestamp: Optional[float]
    
    # Original frame dimensions
    original_frame_width: int
    original_frame_height: int
    
    # Detection chain
    person_detection_id: str
    person_detection_confidence: float
    face_detection_id: Optional[str] = None
    face_detection_confidence: Optional[float] = None
    
    # Model information
    person_model_id: str = "yolo_person"
    face_model_id: str = "scrfd"
    
    # Crop identification
    crop_id: str = field(default_factory=lambda: f"crop_{uuid.uuid4().hex[:8]}")
    
    # Face-specific provenance (for face crops)
    face_bbox_original: Tuple[float, float, float, float] = (0, 0, 0, 0)
    face_bbox_person_crop: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    # Person crop bbox in original frame (for face crops)
    person_bbox_original: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "original_frame_width": self.original_frame_width,
            "original_frame_height": self.original_frame_height,
            "person_detection_id": self.person_detection_id,
            "person_detection_confidence": self.person_detection_confidence,
            "face_detection_id": self.face_detection_id,
            "face_detection_confidence": self.face_detection_confidence,
            "person_model_id": self.person_model_id,
            "face_model_id": self.face_model_id,
            "crop_id": self.crop_id,
            "face_bbox_original": list(self.face_bbox_original),
            "face_bbox_person_crop": list(self.face_bbox_person_crop),
        }


# =============================================================================
# PADDING POLICY
# =============================================================================

@dataclass(frozen=True)
class PaddingPolicy:
    """
    Configurable padding behavior for crops.
    
    Padding can be specified as:
    - absolute pixels (pad_pixels)
    - ratio of bbox dimensions (pad_ratio)
    - both (pixels take precedence when specified)
    
    The padding is applied symmetrically around the bbox.
    Crops are clipped to frame boundaries.
    """
    
    # Absolute padding in pixels
    pad_pixels: Optional[int] = None
    
    # Relative padding as ratio of bbox dimension (0.0 to 1.0)
    pad_ratio: Optional[float] = None
    
    def compute_padding(self, bbox_width: float, bbox_height: float) -> Tuple[int, int]:
        """
        Compute effective padding in pixels for a given bbox.
        
        Args:
            bbox_width: Width of the bounding box.
            bbox_height: Height of the bounding box.
            
        Returns:
            Tuple of (pad_x, pad_y) in pixels.
            
        Raises:
            ValueError: If neither pad_pixels nor pad_ratio is set.
        """
        if self.pad_pixels is not None:
            return (self.pad_pixels, self.pad_pixels)
        
        if self.pad_ratio is not None:
            pad_x = int(round(bbox_width * self.pad_ratio))
            pad_y = int(round(bbox_height * self.pad_ratio))
            return (pad_x, pad_y)
        
        raise ValueError("PaddingPolicy requires either pad_pixels or pad_ratio")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pad_pixels": self.pad_pixels,
            "pad_ratio": self.pad_ratio,
        }


# Default padding: 15% of bbox dimension
DEFAULT_PERSON_PADDING = PaddingPolicy(pad_ratio=0.15)
DEFAULT_FACE_PADDING = PaddingPolicy(pad_ratio=0.20)


# =============================================================================
# CROP RESULT
# =============================================================================

@dataclass
class AdaptiveCropResult:
    """
    Result of an adaptive crop operation.
    
    Contains the cropped image data, bounding box in ORIGINAL_FRAME coordinates,
    coordinate space metadata, and complete provenance chain.
    """
    
    # Cropped image data (HWC, RGB)
    data: np.ndarray
    
    # Crop bbox in ORIGINAL_FRAME coordinates (x1, y1, x2, y2)
    bbox_in_original: Tuple[float, float, float, float]
    
    # Crop bbox in source coordinate space
    bbox_in_source: Tuple[float, float, float, float]
    
    # Coordinate space of the source
    source_space: CropCoordinateSpace
    
    # Dimensions
    crop_width: int
    crop_height: int
    
    # Source frame dimensions (the frame this crop was taken from)
    source_frame_width: int
    source_frame_height: int
    
    # Provenance
    provenance: CropProvenance
    
    # Quality metadata (for small face handling)
    is_usable: bool = True
    unusable_reason: Optional[str] = None
    
    def __post_init__(self):
        """Validate crop result."""
        if self.data is None:
            raise ValueError("Crop data cannot be None")
        
        if not isinstance(self.data, np.ndarray):
            raise TypeError(f"Crop data must be numpy array, got {type(self.data)}")
        
        if self.data.ndim != 3:
            raise ValueError(f"Crop data must be 3D (HWC), got {self.data.ndim}D")
        
        h, w = self.data.shape[:2]
        if h != self.crop_height or w != self.crop_width:
            raise ValueError(
                f"Crop dimensions mismatch: data={w}x{h}, "
                f"metadata={self.crop_width}x{self.crop_height}"
            )
        
        # Validate crop dimensions are positive
        if self.crop_width <= 0 or self.crop_height <= 0:
            raise ValueError(
                f"Crop dimensions must be positive: {self.crop_width}x{self.crop_height}"
            )
        
        # Validate bbox in original frame
        x1, y1, x2, y2 = self.bbox_in_original
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise ValueError(f"Non-finite bbox_in_original: ({x1}, {y1}, {x2}, {y2})")
        
        if x1 < 0 or y1 < 0:
            raise ValueError(f"Negative bbox_in_original: ({x1}, {y1}, {x2}, {y2})")
        
        if x2 > self.provenance.original_frame_width:
            raise ValueError(
                f"bbox x2={x2} exceeds original frame width={self.provenance.original_frame_width}"
            )
        
        if y2 > self.provenance.original_frame_height:
            raise ValueError(
                f"bbox y2={y2} exceeds original frame height={self.provenance.original_frame_height}"
            )
    
    @property
    def area(self) -> int:
        """Get crop area in pixels."""
        return self.crop_width * self.crop_height
    
    @property
    def aspect_ratio(self) -> float:
        """Get crop aspect ratio (width / height)."""
        return self.crop_width / self.crop_height if self.crop_height > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without image data)."""
        return {
            "crop_id": self.provenance.crop_id,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "area": self.area,
            "aspect_ratio": self.aspect_ratio,
            "bbox_in_original": list(self.bbox_in_original),
            "bbox_in_source": list(self.bbox_in_source),
            "source_space": self.source_space.value,
            "source_frame_width": self.source_frame_width,
            "source_frame_height": self.source_frame_height,
            "is_usable": self.is_usable,
            "unusable_reason": self.unusable_reason,
            "provenance": self.provenance.to_dict(),
        }


# =============================================================================
# ADAPTIVE CROP CONTRACT
# =============================================================================

@dataclass(frozen=True)
class AdaptiveCropContract:
    """
    Configuration contract for the adaptive crop pipeline.
    
    Defines padding policies, minimum sizes, and coordinate handling.
    """
    
    # Padding policies
    person_padding: PaddingPolicy = field(default_factory=lambda: DEFAULT_PERSON_PADDING)
    face_padding: PaddingPolicy = field(default_factory=lambda: DEFAULT_FACE_PADDING)
    
    # Minimum dimensions
    min_person_crop_width: int = 32
    min_person_crop_height: int = 32
    min_face_crop_width: int = 16
    min_face_crop_height: int = 16
    
    # Face detection minimum on person crop
    min_person_for_face_detection: int = 48
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "person_padding": self.person_padding.to_dict(),
            "face_padding": self.face_padding.to_dict(),
            "min_person_crop_width": self.min_person_crop_width,
            "min_person_crop_height": self.min_person_crop_height,
            "min_face_crop_width": self.min_face_crop_width,
            "min_face_crop_height": self.min_face_crop_height,
            "min_person_for_face_detection": self.min_person_for_face_detection,
        }


DEFAULT_CROP_CONTRACT = AdaptiveCropContract()


# =============================================================================
# BBOX RESTORATION (Reuses Phase 9 formula)
# =============================================================================

def restore_bbox_to_original(
    bbox_model: np.ndarray,
    scale_factor: float,
    pad_top: int,
    pad_left: int,
    original_width: int,
    original_height: int,
) -> Tuple[float, float, float, float]:
    """
    Restore bounding box from YOLO model input space (640×640) to original frame space.
    
    This reuses the validated Phase 9 coordinate restoration formula:
        bbox_original = (bbox_model - padding) / scale_factor
    
    Args:
        bbox_model: Bbox in model input space [x1, y1, x2, y2].
        scale_factor: Preprocessing scale factor.
        pad_top: Top padding applied during preprocessing.
        pad_left: Left padding applied during preprocessing.
        original_width: Original frame width.
        original_height: Original frame height.
        
    Returns:
        Bbox in original frame space (x1, y1, x2, y2), clipped to boundaries.
    """
    x1, y1, x2, y2 = bbox_model
    
    # Remove padding and rescale
    x1 = float((x1 - pad_left) / scale_factor)
    y1 = float((y1 - pad_top) / scale_factor)
    x2 = float((x2 - pad_left) / scale_factor)
    y2 = float((y2 - pad_top) / scale_factor)
    
    # Clip to original frame boundaries
    x1 = max(0.0, min(x1, float(original_width)))
    y1 = max(0.0, min(y1, float(original_height)))
    x2 = max(0.0, min(x2, float(original_width)))
    y2 = max(0.0, min(y2, float(original_height)))
    
    return (x1, y1, x2, y2)


def restore_face_bbox_to_person_crop(
    bbox_model: np.ndarray,
    scale_factor: float,
    pad_top: int,
    pad_left: int,
    person_crop_width: int,
    person_crop_height: int,
) -> Tuple[float, float, float, float]:
    """
    Restore face detection bbox from model input space to person-crop coordinates.
    
    Uses the same formula as Phase 9 restoration but targets person-crop dimensions.
    
    Args:
        bbox_model: Face bbox in SCRFD model input space [x1, y1, x2, y2].
        scale_factor: SCRFD preprocessing scale factor.
        pad_top: Top padding from SCRFD preprocessing.
        pad_left: Left padding from SCRFD preprocessing.
        person_crop_width: Width of the person crop image.
        person_crop_height: Height of the person crop image.
        
    Returns:
        Bbox in person-crop coordinates (x1, y1, x2, y2), clipped to crop boundaries.
    """
    x1, y1, x2, y2 = bbox_model
    
    # Remove padding and rescale
    x1 = float((x1 - pad_left) / scale_factor)
    y1 = float((y1 - pad_top) / scale_factor)
    x2 = float((x2 - pad_left) / scale_factor)
    y2 = float((y2 - pad_top) / scale_factor)
    
    # Clip to person crop boundaries
    x1 = max(0.0, min(x1, float(person_crop_width)))
    y1 = max(0.0, min(y1, float(person_crop_height)))
    x2 = max(0.0, min(x2, float(person_crop_width)))
    y2 = max(0.0, min(y2, float(person_crop_height)))
    
    return (x1, y1, x2, y2)


def face_bbox_to_original_frame(
    face_bbox_person: Tuple[float, float, float, float],
    person_bbox_original: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """
    Convert face bbox from person-crop coordinates to ORIGINAL_FRAME coordinates.
    
    Args:
        face_bbox_person: Face bbox in person-crop coordinates (x1, y1, x2, y2).
        person_bbox_original: Person bbox in original frame coordinates (x1, y1, x2, y2).
        
    Returns:
        Face bbox in original frame coordinates (x1, y1, x2, y2).
    """
    fx1, fy1, fx2, fy2 = face_bbox_person
    px1, py1, px2, py2 = person_bbox_original
    
    # Translate from person crop space to original frame space
    orig_x1 = fx1 + px1
    orig_y1 = fy1 + py1
    orig_x2 = fx2 + px1
    orig_y2 = fy2 + py1
    
    return (orig_x1, orig_y1, orig_x2, orig_y2)


# =============================================================================
# DYNAMIC CROP UTILITIES
# =============================================================================

def compute_crop_bbox(
    bbox: Tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    padding_policy: PaddingPolicy,
) -> Tuple[float, float, float, int, int]:
    """
    Compute padded and clipped crop bbox.
    
    Args:
        bbox: Bounding box (x1, y1, x2, y2) in frame coordinates.
        frame_width: Width of the source frame.
        frame_height: Height of the source frame.
        padding_policy: Padding configuration.
        
    Returns:
        Tuple of (crop_x1, crop_y1, crop_x2, crop_y2, crop_width, crop_height).
    """
    x1, y1, x2, y2 = bbox
    
    bbox_width = x2 - x1
    bbox_height = y2 - y1
    
    # Compute padding
    pad_x, pad_y = padding_policy.compute_padding(bbox_width, bbox_height)
    
    # Apply padding
    crop_x1 = x1 - pad_x
    crop_y1 = y1 - pad_y
    crop_x2 = x2 + pad_x
    crop_y2 = y2 + pad_y
    
    # Clip to frame boundaries
    crop_x1 = max(0.0, crop_x1)
    crop_y1 = max(0.0, crop_y1)
    crop_x2 = min(float(frame_width), crop_x2)
    crop_y2 = min(float(frame_height), crop_y2)
    
    # Compute integer pixel bounds for slicing
    crop_x1_int = int(np.floor(crop_x1))
    crop_y1_int = int(np.floor(crop_y1))
    crop_x2_int = int(np.ceil(crop_x2))
    crop_y2_int = int(np.ceil(crop_y2))
    
    # Ensure non-negative dimensions
    crop_width = max(0, crop_x2_int - crop_x1_int)
    crop_height = max(0, crop_y2_int - crop_y1_int)
    
    return (float(crop_x1_int), float(crop_y1_int), float(crop_x2_int), float(crop_y2_int), crop_width, crop_height)


def extract_crop(
    frame: np.ndarray,
    crop_x1: int,
    crop_y1: int,
    crop_x2: int,
    crop_y2: int,
) -> np.ndarray:
    """
    Extract a crop from a frame with boundary safety.
    
    Args:
        frame: Source frame (HWC numpy array).
        crop_x1: Left boundary (inclusive).
        crop_y1: Top boundary (inclusive).
        crop_x2: Right boundary (exclusive).
        crop_y2: Bottom boundary (exclusive).
        
    Returns:
        Cropped image as numpy array (HWC).
        
    Raises:
        ValueError: If crop dimensions are invalid.
    """
    frame_h, frame_w = frame.shape[:2]
    
    # Clamp to frame boundaries
    crop_x1 = max(0, min(crop_x1, frame_w))
    crop_y1 = max(0, min(crop_y1, frame_h))
    crop_x2 = max(crop_x1, min(crop_x2, frame_w))
    crop_y2 = max(crop_y1, min(crop_y2, frame_h))
    
    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        raise ValueError(
            f"Invalid crop region: ({crop_x1}, {crop_y1}, {crop_x2}, {crop_y2})"
        )
    
    return frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()


# =============================================================================
# NEGATIVE GEOMETRY VALIDATION
# =============================================================================

class CropGeometryError(Exception):
    """Exception raised for invalid crop geometry."""
    
    def __init__(self, message: str, bbox: Optional[Tuple] = None):
        super().__init__(message)
        self.bbox = bbox


def validate_bbox(
    bbox: Tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
) -> None:
    """
    Validate a bounding box against geometry rules.
    
    Args:
        bbox: Bounding box (x1, y1, x2, y2).
        frame_width: Width of the source frame.
        frame_height: Height of the source frame.
        
    Raises:
        CropGeometryError: If bbox is invalid.
    """
    x1, y1, x2, y2 = bbox
    
    # Check for NaN
    if not all(np.isfinite([x1, y1, x2, y2])):
        raise CropGeometryError(
            f"Bbox contains non-finite values: ({x1}, {y1}, {x2}, {y2})",
            bbox=bbox,
        )
    
    # Check for zero area
    if x1 >= x2 or y1 >= y2:
        raise CropGeometryError(
            f"Bbox has zero or negative area: ({x1}, {y1}, {x2}, {y2})",
            bbox=bbox,
        )
    
    # Check for negative coordinates
    if x1 < 0 or y1 < 0:
        raise CropGeometryError(
            f"Bbox has negative coordinates: ({x1}, {y1}, {x2}, {y2})",
            bbox=bbox,
        )
    
    # Check bounds (allow bbox to extend slightly for clipping)
    if x2 > frame_width + 1 or y2 > frame_height + 1:
        raise CropGeometryError(
            f"Bbox exceeds frame boundaries: ({x1}, {y1}, {x2}, {y2}) "
            f"vs frame {frame_width}x{frame_height}",
            bbox=bbox,
        )


def validate_bbox_safe(
    bbox: Tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
) -> bool:
    """
    Validate a bounding box, returning False instead of raising.
    
    Args:
        bbox: Bounding box (x1, y1, x2, y2).
        frame_width: Width of the source frame.
        frame_height: Height of the source frame.
        
    Returns:
        True if bbox is valid, False otherwise.
    """
    try:
        validate_bbox(bbox, frame_width, frame_height)
        return True
    except CropGeometryError:
        return False


# =============================================================================
# MAIN ADAPTIVE CROP PIPELINE
# =============================================================================

def crop_person_from_frame(
    frame: np.ndarray,
    person_bbox: Tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    padding_policy: PaddingPolicy = DEFAULT_PERSON_PADDING,
    min_crop_width: int = 32,
    min_crop_height: int = 32,
) -> Tuple[np.ndarray, Tuple[float, float, float, float], Tuple[int, int]]:
    """
    Crop a person region from the original frame.
    
    Args:
        frame: Original frame (HWC numpy array, e.g., 3840×2160).
        person_bbox: Person detection bbox in original frame coordinates (x1, y1, x2, y2).
        frame_width: Width of the original frame.
        frame_height: Height of the original frame.
        padding_policy: Padding configuration.
        min_crop_width: Minimum crop width to be considered usable.
        min_crop_height: Minimum crop height to be considered usable.
        
    Returns:
        Tuple of (crop_image, crop_bbox_in_original, (crop_width, crop_height)).
        
    Raises:
        CropGeometryError: If bbox is invalid.
    """
    # Validate input bbox
    validate_bbox(person_bbox, frame_width, frame_height)
    
    # Compute padded and clipped crop bbox
    crop_x1, crop_y1, crop_x2, crop_y2, crop_w, crop_h = compute_crop_bbox(
        bbox=person_bbox,
        frame_width=frame_width,
        frame_height=frame_height,
        padding_policy=padding_policy,
    )
    
    if crop_w < 1 or crop_h < 1:
        raise CropGeometryError(
            f"Crop has zero dimensions after padding/clipping: {crop_w}x{crop_h}",
            bbox=person_bbox,
        )
    
    # Extract crop from original frame (NOT from 640×640 tensor)
    crop_image = extract_crop(
        frame=frame,
        crop_x1=int(crop_x1),
        crop_y1=int(crop_y1),
        crop_x2=int(crop_x2),
        crop_y2=int(crop_y2),
    )
    
    return crop_image, (crop_x1, crop_y1, crop_x2, crop_y2), (crop_w, crop_h)


def crop_face_from_frame(
    frame: np.ndarray,
    face_bbox_in_original: Tuple[float, float, float, float],
    frame_width: int,
    frame_height: int,
    padding_policy: PaddingPolicy = DEFAULT_FACE_PADDING,
) -> Tuple[np.ndarray, Tuple[float, float, float, float], Tuple[int, int]]:
    """
    Crop a face region from the original frame.
    
    Preferred approach: crop face directly from ORIGINAL_FRAME using face bbox
    in original frame coordinates.
    
    Args:
        frame: Original frame (HWC numpy array).
        face_bbox_in_original: Face bbox in original frame coordinates (x1, y1, x2, y2).
        frame_width: Width of the original frame.
        frame_height: Height of the original frame.
        padding_policy: Padding configuration.
        
    Returns:
        Tuple of (crop_image, crop_bbox_in_original, (crop_width, crop_height)).
        
    Raises:
        CropGeometryError: If bbox is invalid.
    """
    # Validate input bbox
    validate_bbox(face_bbox_in_original, frame_width, frame_height)
    
    # Compute padded and clipped crop bbox
    crop_x1, crop_y1, crop_x2, crop_y2, crop_w, crop_h = compute_crop_bbox(
        bbox=face_bbox_in_original,
        frame_width=frame_width,
        frame_height=frame_height,
        padding_policy=padding_policy,
    )
    
    if crop_w < 1 or crop_h < 1:
        raise CropGeometryError(
            f"Face crop has zero dimensions after padding/clipping: {crop_w}x{crop_h}",
            bbox=face_bbox_in_original,
        )
    
    # Extract crop from original frame
    crop_image = extract_crop(
        frame=frame,
        crop_x1=int(crop_x1),
        crop_y1=int(crop_y1),
        crop_x2=int(crop_x2),
        crop_y2=int(crop_y2),
    )
    
    return crop_image, (crop_x1, crop_y1, crop_x2, crop_y2), (crop_w, crop_h)


# =============================================================================
# MULTI-PEOPLE CROP
# =============================================================================

def crop_multiple_persons(
    frame: np.ndarray,
    person_bboxes: List[Tuple[float, float, float, float]],
    frame_width: int,
    frame_height: int,
    padding_policy: PaddingPolicy = DEFAULT_PERSON_PADDING,
    min_crop_width: int = 32,
    min_crop_height: int = 32,
) -> List[Tuple[np.ndarray, Tuple[float, float, float, float], Tuple[int, int], bool, Optional[str]]]:
    """
    Crop multiple person regions from the original frame.
    
    Each person receives an independent dynamic crop.
    Detection order does not alter crop correctness.
    
    Args:
        frame: Original frame (HWC numpy array).
        person_bboxes: List of person detection bboxes in original frame coordinates.
        frame_width: Width of the original frame.
        frame_height: Height of the original frame.
        padding_policy: Padding configuration.
        min_crop_width: Minimum usable crop width.
        min_crop_height: Minimum usable crop height.
        
    Returns:
        List of tuples: (crop_image, crop_bbox_in_original, (crop_w, crop_h), is_usable, unusable_reason).
    """
    results = []
    
    for bbox in person_bboxes:
        try:
            crop_image, crop_bbox, (crop_w, crop_h) = crop_person_from_frame(
                frame=frame,
                person_bbox=bbox,
                frame_width=frame_width,
                frame_height=frame_height,
                padding_policy=padding_policy,
                min_crop_width=min_crop_width,
                min_crop_height=min_crop_height,
            )
            
            is_usable = crop_w >= min_crop_width and crop_h >= min_crop_height
            unusable_reason = None
            if not is_usable:
                unusable_reason = f"Crop too small: {crop_w}x{crop_h} < {min_crop_width}x{min_crop_height}"
            
            results.append((crop_image, crop_bbox, (crop_w, crop_h), is_usable, unusable_reason))
            
        except CropGeometryError as e:
            logger.warning(f"Failed to crop person bbox {bbox}: {e}")
            results.append((
                np.zeros((1, 1, 3), dtype=np.uint8),
                bbox,
                (0, 0),
                False,
                str(e),
            ))
    
    return results


# =============================================================================
# MEMORY SAFETY
# =============================================================================

def estimate_crop_memory_bytes(
    crop_width: int,
    crop_height: int,
    channels: int = 3,
    dtype_bytes: int = 1,
) -> int:
    """
    Estimate memory usage for a crop.
    
    Args:
        crop_width: Width of crop in pixels.
        crop_height: Height of crop in pixels.
        channels: Number of channels.
        dtype_bytes: Bytes per pixel value.
        
    Returns:
        Estimated memory in bytes.
    """
    return crop_width * crop_height * channels * dtype_bytes