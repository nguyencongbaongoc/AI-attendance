"""
Phase 22 — Coordinate Transform Module.

Handles deterministic coordinate transforms between display space and ORIGINAL_FRAME space.
Used for UI rendering where source frame is displayed at different resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.geometry.contract import Point2D


@dataclass(frozen=True)
class DisplayTransform:
    """
    Deterministic transform between display space and ORIGINAL_FRAME space.
    
    Source frame (ORIGINAL_FRAME) -> Display frame (e.g., 1920x1080)
    
    The transform preserves aspect ratio by default (letterbox/pillarbox).
    """
    # Source frame dimensions (ORIGINAL_FRAME)
    source_width: int
    source_height: int
    
    # Display frame dimensions
    display_width: int
    display_height: int
    
    # Transform mode
    preserve_aspect_ratio: bool = True
    
    def __post_init__(self):
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError(f"Invalid source dimensions: {self.source_width}x{self.source_height}")
        if self.display_width <= 0 or self.display_height <= 0:
            raise ValueError(f"Invalid display dimensions: {self.display_width}x{self.display_height}")
    
    @property
    def source_aspect(self) -> float:
        return self.source_width / self.source_height
    
    @property
    def display_aspect(self) -> float:
        return self.display_width / self.display_height
    
    @property
    def scale(self) -> float:
        """Uniform scale factor when preserving aspect ratio."""
        if self.preserve_aspect_ratio:
            return min(
                self.display_width / self.source_width,
                self.display_height / self.source_height
            )
        else:
            # Non-uniform scaling (stretch to fill)
            return self.display_width / self.source_width  # x scale
    
    @property
    def scale_x(self) -> float:
        """X scale factor."""
        if self.preserve_aspect_ratio:
            return self.scale
        return self.display_width / self.source_width
    
    @property
    def scale_y(self) -> float:
        """Y scale factor."""
        if self.preserve_aspect_ratio:
            return self.scale
        return self.display_height / self.source_height
    
    @property
    def offset_x(self) -> float:
        """X offset (letterbox/pillarbox padding)."""
        if self.preserve_aspect_ratio:
            scaled_width = self.source_width * self.scale
            return (self.display_width - scaled_width) / 2
        return 0.0
    
    @property
    def offset_y(self) -> float:
        """Y offset (letterbox/pillarbox padding)."""
        if self.preserve_aspect_ratio:
            scaled_height = self.source_height * self.scale
            return (self.display_height - scaled_height) / 2
        return 0.0
    
    def source_to_display(self, point: Point2D) -> Point2D:
        """
        Transform point from ORIGINAL_FRAME (source) to display coordinates.
        
        Args:
            point: Point in ORIGINAL_FRAME coordinates
            
        Returns:
            Point in display coordinates
        """
        x = point.x * self.scale_x + self.offset_x
        y = point.y * self.scale_y + self.offset_y
        return Point2D(x, y)
    
    def display_to_source(self, point: Point2D) -> Point2D:
        """
        Transform point from display coordinates to ORIGINAL_FRAME (source).
        
        Args:
            point: Point in display coordinates
            
        Returns:
            Point in ORIGINAL_FRAME coordinates
        """
        x = (point.x - self.offset_x) / self.scale_x
        y = (point.y - self.offset_y) / self.scale_y
        return Point2D(x, y)
    
    def source_to_display_bbox(
        self, 
        bbox: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        """Transform bbox from source to display coordinates."""
        x1, y1, x2, y2 = bbox
        p1 = self.source_to_display(Point2D(x1, y1))
        p2 = self.source_to_display(Point2D(x2, y2))
        return (p1.x, p1.y, p2.x, p2.y)
    
    def display_to_source_bbox(
        self, 
        bbox: Tuple[float, float, float, float]
    ) -> Tuple[float, float, float, float]:
        """Transform bbox from display to source coordinates."""
        x1, y1, x2, y2 = bbox
        p1 = self.display_to_source(Point2D(x1, y1))
        p2 = self.display_to_source(Point2D(x2, y2))
        return (p1.x, p1.y, p2.x, p2.y)
    
    def round_trip(self, point: Point2D, tolerance: float = 1e-6) -> bool:
        """
        Test round-trip: source -> display -> source.
        
        Args:
            point: Original point in source coordinates
            tolerance: Maximum allowed difference
            
        Returns:
            True if round-trip is within tolerance
        """
        display = self.source_to_display(point)
        back = self.display_to_source(display)
        dx = abs(point.x - back.x)
        dy = abs(point.y - back.y)
        return dx <= tolerance and dy <= tolerance
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "display_width": self.display_width,
            "display_height": self.display_height,
            "preserve_aspect_ratio": self.preserve_aspect_ratio,
            "scale": self.scale,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisplayTransform":
        return cls(
            source_width=data["source_width"],
            source_height=data["source_height"],
            display_width=data["display_width"],
            display_height=data["display_height"],
            preserve_aspect_ratio=data.get("preserve_aspect_ratio", True),
        )


def create_display_transform(
    source_width: int,
    source_height: int,
    display_width: int,
    display_height: int,
    preserve_aspect_ratio: bool = True,
) -> DisplayTransform:
    """Factory function to create a DisplayTransform."""
    return DisplayTransform(
        source_width=source_width,
        source_height=source_height,
        display_width=display_width,
        display_height=display_height,
        preserve_aspect_ratio=preserve_aspect_ratio,
    )


def create_transform_for_ui(
    source_width: int,
    source_height: int,
    max_display_width: int = 1920,
    max_display_height: int = 1080,
) -> DisplayTransform:
    """
    Create a display transform suitable for UI preview.
    
    Scales source frame to fit within max display dimensions while preserving aspect ratio.
    """
    scale = min(max_display_width / source_width, max_display_height / source_height)
    display_width = int(source_width * scale)
    display_height = int(source_height * scale)
    
    return DisplayTransform(
        source_width=source_width,
        source_height=source_height,
        display_width=display_width,
        display_height=display_height,
        preserve_aspect_ratio=True,
    )


@dataclass(frozen=True)
class TransformProvenance:
    """
    Provenance record for coordinate transforms.
    
    Ensures forensic reproducibility of coordinate conversions.
    """
    transform: DisplayTransform
    source_point: Optional[Point2D] = None
    display_point: Optional[Point2D] = None
    direction: str = "source_to_display"  # or "display_to_source"
    timestamp: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transform": self.transform.to_dict(),
            "source_point": self.source_point.to_dict() if self.source_point else None,
            "display_point": self.display_point.to_dict() if self.display_point else None,
            "direction": self.direction,
            "timestamp": self.timestamp,
        }


def transform_geometry_config(
    config: Any,  # CameraGeometryConfig
    display_transform: DisplayTransform,
) -> Any:
    """
    Transform geometry configuration for display rendering.
    
    Returns a new config with geometry coordinates in display space.
    Original config remains in ORIGINAL_FRAME coordinates.
    """
    # This would create a copy with transformed coordinates for UI rendering
    # The stored config always remains in ORIGINAL_FRAME
    raise NotImplementedError("Use display_transform directly for rendering")


def validate_round_trip(
    source_width: int,
    source_height: int,
    display_width: int,
    display_height: int,
    test_points: int = 100,
    tolerance: float = 1e-6,
) -> Dict[str, Any]:
    """
    Validate coordinate round-trip for a transform.
    
    Tests random points to ensure source -> display -> source is accurate.
    """
    transform = DisplayTransform(
        source_width=source_width,
        source_height=source_height,
        display_width=display_width,
        display_height=display_height,
        preserve_aspect_ratio=True,
    )
    
    rng = np.random.default_rng(42)
    passed = 0
    failed = 0
    max_error = 0.0
    
    for _ in range(test_points):
        x = rng.uniform(0, source_width)
        y = rng.uniform(0, source_height)
        point = Point2D(x, y)
        
        if transform.round_trip(point, tolerance):
            passed += 1
        else:
            failed += 1
            display = transform.source_to_display(point)
            back = transform.display_to_source(display)
            error = max(abs(point.x - back.x), abs(point.y - back.y))
            max_error = max(max_error, error)
    
    return {
        "total_tests": test_points,
        "passed": passed,
        "failed": failed,
        "max_error": max_error,
        "tolerance": tolerance,
        "transform": transform.to_dict(),
    }