"""
Phase 7 — Safe Face Crop Component.

This module provides a dedicated safe face crop component that:
- Maps coordinates to original frame
- Clips to image boundaries
- Prevents negative array slicing
- Prevents empty crops
- Preserves provenance metadata
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.vision.detection import FaceDetection, CoordinateSpace


class CropError(Exception):
    """Exception raised when face cropping fails."""
    
    def __init__(
        self,
        message: str,
        detection_id: Optional[str] = None,
        frame_index: Optional[int] = None,
    ):
        super().__init__(message)
        self.detection_id = detection_id
        self.frame_index = frame_index


@dataclass
class FaceCrop:
    """
    Safe face crop with full provenance.
    
    The crop is extracted from the original frame using validated bounding box.
    All provenance metadata is preserved.
    """
    
    # Cropped face image data (HWC format, RGB)
    data: np.ndarray
    
    # Crop dimensions
    crop_width: int
    crop_height: int
    
    # Provenance - source frame
    source_type: SourceType
    source_id: str
    frame_index: int
    timestamp: Optional[float]
    original_frame_width: int
    original_frame_height: int
    
    # Provenance - detection
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 in original frame
    detection_confidence: float
    detection_id: str
    
    # Provenance - crop
    crop_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # Pixel format
    pixel_format: PixelFormat = PixelFormat.RGB
    
    def __post_init__(self):
        """Validate crop data."""
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
        
        # Allow zero-area crops for edge cases (will be filtered by validate_crop_for_landmark)
        # Only validate that dimensions are non-negative
        if self.crop_width < 0 or self.crop_height < 0:
            raise ValueError(f"Invalid crop dimensions: {self.crop_width}x{self.crop_height}")
        
        # Validate bbox - allow zero-area for edge cases
        x1, y1, x2, y2 = self.bbox
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise ValueError(f"Invalid bbox in crop: non-finite coordinates ({x1}, {y1}, {x2}, {y2})")
    
    @property
    def shape(self) -> Tuple[int, int, int]:
        """Get crop shape (H, W, C)."""
        return self.data.shape
    
    @property
    def channels(self) -> int:
        """Get number of channels."""
        return self.data.shape[2] if self.data.ndim == 3 else 1
    
    @property
    def aspect_ratio(self) -> float:
        """Get crop aspect ratio (width / height)."""
        return self.crop_width / self.crop_height if self.crop_height > 0 else 0.0
    
    @property
    def area(self) -> int:
        """Get crop area in pixels."""
        return self.crop_width * self.crop_height
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without image data)."""
        return {
            "crop_id": self.crop_id,
            "crop_width": self.crop_width,
            "crop_height": self.crop_height,
            "shape": list(self.shape),
            "channels": self.channels,
            "aspect_ratio": self.aspect_ratio,
            "area": self.area,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "original_frame_width": self.original_frame_width,
            "original_frame_height": self.original_frame_height,
            "bbox": list(self.bbox),
            "detection_confidence": self.detection_confidence,
            "detection_id": self.detection_id,
            "pixel_format": self.pixel_format.value,
        }
    
    def copy(self) -> "FaceCrop":
        """Create a deep copy of the crop."""
        return FaceCrop(
            data=self.data.copy(),
            crop_width=self.crop_width,
            crop_height=self.crop_height,
            source_type=self.source_type,
            source_id=self.source_id,
            frame_index=self.frame_index,
            timestamp=self.timestamp,
            original_frame_width=self.original_frame_width,
            original_frame_height=self.original_frame_height,
            bbox=self.bbox,
            detection_confidence=self.detection_confidence,
            detection_id=self.detection_id,
            crop_id=self.crop_id,
            pixel_format=self.pixel_format,
        )


def safe_crop_face(
    frame: CanonicalFrame,
    detection: FaceDetection,
    min_crop_size: int = 16,
    target_format: PixelFormat = PixelFormat.RGB,
) -> FaceCrop:
    """
    Safely crop a face from a canonical frame.
    
    This function:
    - Validates the detection bbox
    - Maps coordinates to original frame (if needed)
    - Clips bbox to image boundaries
    - Prevents negative array slicing
    - Prevents empty crops
    - Converts to target pixel format
    - Preserves all provenance metadata
    
    Args:
        frame: Source canonical frame.
        detection: Validated face detection with bbox in ORIGINAL_FRAME coordinates.
        min_crop_size: Minimum crop dimension (width/height) in pixels.
        target_format: Target pixel format for the crop.
        
    Returns:
        FaceCrop with cropped face and full provenance.
        
    Raises:
        CropError: If cropping fails (invalid bbox, too small, etc.).
    """
    # Validate detection coordinate space
    if detection.coordinate_space != CoordinateSpace.ORIGINAL_FRAME:
        raise CropError(
            f"Detection bbox must be in ORIGINAL_FRAME coordinates, "
            f"got {detection.coordinate_space.value}",
            detection_id=detection.detection_id,
            frame_index=frame.metadata.frame_index,
        )
    
    # Get bbox coordinates
    x1, y1, x2, y2 = detection.bbox
    
    # Validate bbox
    if x1 >= x2 or y1 >= y2:
        raise CropError(
            f"Invalid bbox: x1={x1}, y1={y1}, x2={x2}, y2={y2}",
            detection_id=detection.detection_id,
            frame_index=frame.metadata.frame_index,
        )
    
    if not all(np.isfinite([x1, y1, x2, y2])):
        raise CropError(
            f"Bbox contains non-finite values: {detection.bbox}",
            detection_id=detection.detection_id,
            frame_index=frame.metadata.frame_index,
        )
    
    # Get frame dimensions
    frame_h, frame_w = frame.height, frame.width
    
    # Clip bbox to frame boundaries
    x1_clipped = max(0.0, min(x1, frame_w - 1))
    y1_clipped = max(0.0, min(y1, frame_h - 1))
    x2_clipped = max(0.0, min(x2, frame_w))
    y2_clipped = max(0.0, min(y2, frame_h))
    
    # Convert to integer pixel coordinates
    x1_int = int(np.floor(x1_clipped))
    y1_int = int(np.floor(y1_clipped))
    x2_int = int(np.ceil(x2_clipped))
    y2_int = int(np.ceil(y2_clipped))
    
    # Ensure valid crop after clipping
    if x1_int >= x2_int or y1_int >= y2_int:
        raise CropError(
            f"Bbox results in empty crop after clipping: "
            f"({x1_int}, {y1_int}, {x2_int}, {y2_int})",
            detection_id=detection.detection_id,
            frame_index=frame.metadata.frame_index,
        )
    
    crop_width = x2_int - x1_int
    crop_height = y2_int - y1_int
    
    # Check minimum crop size
    if crop_width < min_crop_size or crop_height < min_crop_size:
        raise CropError(
            f"Crop too small: {crop_width}x{crop_height} < {min_crop_size}x{min_crop_size}",
            detection_id=detection.detection_id,
            frame_index=frame.metadata.frame_index,
        )
    
    # Extract crop from frame data
    # Frame data is in original pixel format (typically BGR from OpenCV)
    crop_data = frame.data[y1_int:y2_int, x1_int:x2_int].copy()
    
    # Convert to target format if needed
    if target_format == PixelFormat.RGB and frame.metadata.pixel_format == PixelFormat.BGR:
        import cv2
        crop_data = cv2.cvtColor(crop_data, cv2.COLOR_BGR2RGB)
    elif target_format == PixelFormat.BGR and frame.metadata.pixel_format == PixelFormat.RGB:
        import cv2
        crop_data = cv2.cvtColor(crop_data, cv2.COLOR_RGB2BGR)
    elif target_format == PixelFormat.GRAY:
        import cv2
        if crop_data.ndim == 3:
            crop_data = cv2.cvtColor(crop_data, cv2.COLOR_BGR2GRAY if frame.metadata.pixel_format == PixelFormat.BGR else cv2.COLOR_RGB2GRAY)
    
    # Create FaceCrop with full provenance
    face_crop = FaceCrop(
        data=crop_data,
        crop_width=crop_width,
        crop_height=crop_height,
        source_type=frame.metadata.source_type,
        source_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        original_frame_width=frame.metadata.original_width,
        original_frame_height=frame.metadata.original_height,
        bbox=detection.bbox,  # Original unclipped bbox for provenance
        detection_confidence=detection.confidence,
        detection_id=detection.detection_id,
        pixel_format=target_format,
    )
    
    return face_crop


def crop_multiple_faces(
    frame: CanonicalFrame,
    detections: List[FaceDetection],
    min_crop_size: int = 16,
    target_format: PixelFormat = PixelFormat.RGB,
) -> List[FaceCrop]:
    """
    Crop multiple faces from a frame.
    
    Args:
        frame: Source canonical frame.
        detections: List of validated face detections.
        min_crop_size: Minimum crop dimension.
        target_format: Target pixel format.
        
    Returns:
        List of FaceCrop objects (failed crops are skipped with warning).
    """
    crops = []
    
    for detection in detections:
        try:
            crop = safe_crop_face(
                frame=frame,
                detection=detection,
                min_crop_size=min_crop_size,
                target_format=target_format,
            )
            crops.append(crop)
        except CropError as e:
            # Log and continue - don't fail entire frame
            import logging
            logging.warning(f"Failed to crop face {e.detection_id}: {e}")
            continue
    
    return crops


def validate_crop_for_landmark(
    crop: FaceCrop,
    min_dimension: int = 32,
) -> bool:
    """
    Validate that a face crop is suitable for landmark inference.
    
    Args:
        crop: Face crop to validate.
        min_dimension: Minimum dimension required.
        
    Returns:
        True if crop is valid for landmark inference.
    """
    if crop.crop_width < min_dimension or crop.crop_height < min_dimension:
        return False
    
    if crop.data.size == 0:
        return False
    
    # Check for valid pixel values
    if not np.all(np.isfinite(crop.data)):
        return False
    
    return True