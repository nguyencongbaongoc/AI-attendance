"""
Phase 10 — Geometry Primitives for Person-Face Association.

This module provides deterministic geometry helpers for the association layer.
All functions operate in ORIGINAL_FRAME coordinates (3840x2160).

Functions are independently unit tested with explicit floating-point tolerances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


# Floating-point tolerance for geometry comparisons
EPS = 1e-6
AMBIGUITY_MARGIN = 0.05  # Minimum score difference to avoid AMBIGUOUS


@dataclass(frozen=True)
class BBox:
    """Bounding box in (x1, y1, x2, y2) format."""
    x1: float
    y1: float
    x2: float
    y2: float
    
    def __post_init__(self):
        if not all(np.isfinite([self.x1, self.y1, self.x2, self.y2])):
            raise ValueError(f"BBox has non-finite coordinates: {self}")
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(f"BBox has invalid dimensions: {self}")
    
    @property
    def width(self) -> float:
        return self.x2 - self.x1
    
    @property
    def height(self) -> float:
        return self.y2 - self.y1
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)
    
    def to_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)
    
    @classmethod
    def from_tuple(cls, bbox: Tuple[float, float, float, float]) -> "BBox":
        return cls(bbox[0], bbox[1], bbox[2], bbox[3])


def bbox_area(bbox: Tuple[float, float, float, float]) -> float:
    """
    Calculate bounding box area.
    
    Args:
        bbox: (x1, y1, x2, y2)
        
    Returns:
        Area in pixels^2
    """
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_intersection(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """
    Calculate intersection of two bounding boxes.
    
    Args:
        bbox1: (x1, y1, x2, y2)
        bbox2: (x1, y1, x2, y2)
        
    Returns:
        Intersection bbox (x1, y1, x2, y2) or zero-area bbox if no overlap
    """
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    
    if x2 <= x1 or y2 <= y1:
        return (0.0, 0.0, 0.0, 0.0)
    
    return (x1, y1, x2, y2)


def intersection_area(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
) -> float:
    """
    Calculate intersection area of two bounding boxes.
    
    Args:
        bbox1: (x1, y1, x2, y2)
        bbox2: (x1, y1, x2, y2)
        
    Returns:
        Intersection area in pixels^2
    """
    inter = bbox_intersection(bbox1, bbox2)
    return bbox_area(inter)


def iou(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
) -> float:
    """
    Calculate Intersection over Union (IoU) of two bounding boxes.
    
    Args:
        bbox1: (x1, y1, x2, y2)
        bbox2: (x1, y1, x2, y2)
        
    Returns:
        IoU in [0, 1]
    """
    inter = intersection_area(bbox1, bbox2)
    area1 = bbox_area(bbox1)
    area2 = bbox_area(bbox2)
    
    if area1 <= EPS or area2 <= EPS:
        return 0.0
    
    union = area1 + area2 - inter
    if union <= EPS:
        return 0.0
    
    return inter / union


def intersection_over_face(
    face_bbox: Tuple[float, float, float, float],
    person_bbox: Tuple[float, float, float, float],
) -> float:
    """
    Calculate intersection area / face area ratio.
    
    This measures how much of the face is inside the person bbox.
    
    Args:
        face_bbox: Face bounding box (x1, y1, x2, y2)
        person_bbox: Person bounding box (x1, y1, x2, y2)
        
    Returns:
        Ratio in [0, 1]
    """
    inter = intersection_area(face_bbox, person_bbox)
    face_area = bbox_area(face_bbox)
    
    if face_area <= EPS:
        return 0.0
    
    return min(1.0, inter / face_area)


def face_center_in_person(
    face_bbox: Tuple[float, float, float, float],
    person_bbox: Tuple[float, float, float, float],
    tolerance: float = EPS,
) -> bool:
    """
    Test if face center is inside person bounding box.
    
    Args:
        face_bbox: Face bounding box (x1, y1, x2, y2)
        person_bbox: Person bounding box (x1, y1, x2, y2)
        tolerance: Floating-point tolerance for boundary
        
    Returns:
        True if face center is inside person bbox
    """
    fx, fy = ((face_bbox[0] + face_bbox[2]) / 2, (face_bbox[1] + face_bbox[3]) / 2)
    
    return (
        person_bbox[0] - tolerance <= fx <= person_bbox[2] + tolerance and
        person_bbox[1] - tolerance <= fy <= person_bbox[3] + tolerance
    )


def face_center_distance_to_person(
    face_bbox: Tuple[float, float, float, float],
    person_bbox: Tuple[float, float, float, float],
) -> float:
    """
    Calculate distance from face center to person bbox.
    
    If face center is inside person bbox, distance is 0.
    Otherwise, distance to nearest point on person bbox.
    
    Args:
        face_bbox: Face bounding box (x1, y1, x2, y2)
        person_bbox: Person bounding box (x1, y1, x2, y2)
        
    Returns:
        Distance in pixels
    """
    fx, fy = ((face_bbox[0] + face_bbox[2]) / 2, (face_bbox[1] + face_bbox[3]) / 2)
    px1, py1, px2, py2 = person_bbox
    
    # If inside, distance is 0
    if px1 <= fx <= px2 and py1 <= fy <= py2:
        return 0.0
    
    # Distance to nearest point on rectangle
    dx = max(px1 - fx, 0, fx - px2)
    dy = max(py1 - fy, 0, fy - py2)
    
    return np.sqrt(dx * dx + dy * dy)


def bbox_containment(
    inner: Tuple[float, float, float, float],
    outer: Tuple[float, float, float, float],
    tolerance: float = EPS,
) -> bool:
    """
    Test if inner bbox is fully contained within outer bbox.
    
    Args:
        inner: Inner bounding box (x1, y1, x2, y2)
        outer: Outer bounding box (x1, y1, x2, y2)
        tolerance: Floating-point tolerance
        
    Returns:
        True if inner is fully contained in outer
    """
    return (
        inner[0] >= outer[0] - tolerance and
        inner[1] >= outer[1] - tolerance and
        inner[2] <= outer[2] + tolerance and
        inner[3] <= outer[3] + tolerance
    )


def clip_bbox_to_frame(
    bbox: Tuple[float, float, float, float],
    frame_width: int = 3840,
    frame_height: int = 2160,
) -> Tuple[float, float, float, float]:
    """
    Clip bounding box to frame boundaries.
    
    Args:
        bbox: (x1, y1, x2, y2)
        frame_width: Frame width
        frame_height: Frame height
        
    Returns:
        Clipped bbox
    """
    x1 = max(0.0, min(bbox[0], frame_width))
    y1 = max(0.0, min(bbox[1], frame_height))
    x2 = max(0.0, min(bbox[2], frame_width))
    y2 = max(0.0, min(bbox[3], frame_height))
    
    # Ensure valid bbox
    if x2 < x1:
        x2 = x1
    if y2 < y1:
        y2 = y1
    
    return (x1, y1, x2, y2)


def validate_bbox_4k(bbox: Tuple[float, float, float, float]) -> bool:
    """
    Validate bbox is within 4K boundaries and has valid dimensions.
    
    Args:
        bbox: (x1, y1, x2, y2)
        
    Returns:
        True if valid
    """
    x1, y1, x2, y2 = bbox
    
    # Check finite
    if not all(np.isfinite([x1, y1, x2, y2])):
        return False
    
    # Check dimensions
    if x2 < x1 or y2 < y1:
        return False
    
    # Check 4K boundaries
    if x1 < 0 or y1 < 0 or x2 > 3840 or y2 > 2160:
        return False
    
    return True


def validate_coordinate_space(
    bbox: Tuple[float, float, float, float],
    expected_space: str = "original_frame",
    frame_width: int = 3840,
    frame_height: int = 2160,
) -> bool:
    """
    Validate bbox coordinates match expected coordinate space.
    
    For ORIGINAL_FRAME: coordinates should be in [0, 3840] x [0, 2160]
    For MODEL_INPUT: coordinates should be in [0, 640] x [0, 640] (typical)
    
    Args:
        bbox: (x1, y1, x2, y2)
        expected_space: Expected coordinate space
        frame_width: Expected frame width
        frame_height: Expected frame height
        
    Returns:
        True if coordinates appear valid for the space
    """
    x1, y1, x2, y2 = bbox
    
    if not all(np.isfinite([x1, y1, x2, y2])):
        return False
    
    if expected_space == "original_frame":
        return 0 <= x1 <= frame_width and 0 <= y1 <= frame_height and \
               0 <= x2 <= frame_width and 0 <= y2 <= frame_height
    elif expected_space == "model_input":
        # Typical model input is 640x640
        return 0 <= x1 <= 640 and 0 <= y1 <= 640 and \
               0 <= x2 <= 640 and 0 <= y2 <= 640
    elif expected_space == "normalized":
        # Normalized coordinates [0, 1]
        return 0 <= x1 <= 1 and 0 <= y1 <= 1 and \
               0 <= x2 <= 1 and 0 <= y2 <= 1
    
    return True


@dataclass(frozen=True)
class AssociationScore:
    """
    Decomposed association score with geometry terms.
    
    Allows transparent inspection of scoring decisions.
    """
    containment_score: float      # Face center in person bbox [0, 1]
    intersection_ratio: float     # Intersection over face area [0, 1]
    iou_score: float              # IoU [0, 1]
    distance_score: float         # Inverse distance [0, 1]
    area_ratio_score: float       # Face area / person area [0, 1]
    total_score: float            # Weighted sum
    
    def to_dict(self) -> dict:
        return {
            "containment": self.containment_score,
            "intersection_ratio": self.intersection_ratio,
            "iou": self.iou_score,
            "distance": self.distance_score,
            "area_ratio": self.area_ratio_score,
            "total": self.total_score,
        }


def compute_association_score(
    face_bbox: Tuple[float, float, float, float],
    person_bbox: Tuple[float, float, float, float],
    weights: Tuple[float, float, float, float, float] = (0.3, 0.25, 0.2, 0.15, 0.1),
) -> AssociationScore:
    """
    Compute decomposed association score between face and person.
    
    Score components (weights sum to 1.0):
    1. containment_score (0.3): Face center inside person bbox
    2. intersection_ratio (0.25): Intersection over face area
    3. iou_score (0.2): IoU between face and person
    4. distance_score (0.15): Inverse distance from face center to person
    5. area_ratio_score (0.1): Face area / person area (penalize oversized faces)
    
    Args:
        face_bbox: Face bounding box (x1, y1, x2, y2)
        person_bbox: Person bounding box (x1, y1, x2, y2)
        weights: Tuple of 5 weights (must sum to ~1.0)
        
    Returns:
        AssociationScore with decomposed components
    """
    w1, w2, w3, w4, w5 = weights
    
    # 1. Containment: face center in person bbox
    containment = 1.0 if face_center_in_person(face_bbox, person_bbox) else 0.0
    
    # 2. Intersection over face area
    intersection_ratio = intersection_over_face(face_bbox, person_bbox)
    
    # 3. IoU
    iou_score = iou(face_bbox, person_bbox)
    
    # 4. Distance score (inverse, normalized)
    distance = face_center_distance_to_person(face_bbox, person_bbox)
    # Normalize: at 0 distance -> 1.0, at 1000px -> ~0.37, at 2000px -> ~0.14
    distance_score = np.exp(-distance / 500.0)
    
    # 5. Area ratio (face / person) - penalize faces larger than person
    face_area = bbox_area(face_bbox)
    person_area = bbox_area(person_bbox)
    if person_area > EPS:
        area_ratio = min(1.0, face_area / person_area)
        # Penalize if face is larger than person (likely wrong association)
        area_ratio_score = 1.0 - max(0.0, area_ratio - 0.5) * 2
    else:
        area_ratio_score = 0.0
    
    # Weighted total
    total = (
        w1 * containment +
        w2 * intersection_ratio +
        w3 * iou_score +
        w4 * distance_score +
        w5 * area_ratio_score
    )
    
    return AssociationScore(
        containment_score=containment,
        intersection_ratio=intersection_ratio,
        iou_score=iou_score,
        distance_score=distance_score,
        area_ratio_score=area_ratio_score,
        total_score=float(total),
    )


def is_ambiguous(
    best_score: float,
    second_best_score: float,
    margin: float = AMBIGUITY_MARGIN,
) -> bool:
    """
    Determine if association is ambiguous based on score margin.
    
    Args:
        best_score: Highest association score
        second_best_score: Second highest association score
        margin: Minimum difference to avoid ambiguity
        
    Returns:
        True if ambiguous (difference < margin)
    """
    return (best_score - second_best_score) < margin