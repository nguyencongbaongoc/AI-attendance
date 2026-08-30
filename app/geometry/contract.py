"""
Phase 22 — IN/OUT Geometry Configuration Contract.

Defines camera-specific spatial configuration for determining whether a tracked
person crosses an IN/OUT boundary.

All geometry operates in ORIGINAL_FRAME coordinate space.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class CoordinateSpace(str, Enum):
    """Canonical coordinate spaces."""
    ORIGINAL_FRAME = "original_frame"
    MODEL_INPUT = "model_input"
    NORMALIZED = "normalized"


class GeometryType(str, Enum):
    """Supported geometry types."""
    LINE = "line"
    ZONE = "zone"


class DirectionSemantics(str, Enum):
    """Explicit direction semantics for line/zone."""
    # For LINE: SIDE_A -> SIDE_B = IN, SIDE_B -> SIDE_A = OUT
    SIDE_A_TO_B_IN = "side_a_to_b_in"
    SIDE_B_TO_A_IN = "side_b_to_a_in"
    # For ZONE: OUTSIDE -> INSIDE = IN, INSIDE -> OUTSIDE = OUT
    OUTSIDE_TO_INSIDE_IN = "outside_to_inside_in"
    INSIDE_TO_OUTSIDE_IN = "inside_to_outside_in"


class CrossingPolicy(str, Enum):
    """Crossing detection policy."""
    STRICT = "strict"           # Require clear side transition
    TOUCH_ALLOWED = "touch_allowed"  # Touching line counts as crossing


@dataclass(frozen=True)
class Point2D:
    """2D point in ORIGINAL_FRAME coordinates."""
    x: float
    y: float
    
    def __post_init__(self):
        if not (np.isfinite(self.x) and np.isfinite(self.y)):
            raise ValueError(f"Point coordinates must be finite: ({self.x}, {self.y})")
    
    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)
    
    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y}
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Point2D":
        return cls(x=data["x"], y=data["y"])
    
    def __sub__(self, other: "Point2D") -> "Point2D":
        return Point2D(self.x - other.x, self.y - other.y)
    
    def __add__(self, other: "Point2D") -> "Point2D":
        return Point2D(self.x + other.x, self.y + other.y)
    
    def cross(self, other: "Point2D") -> float:
        """2D cross product (scalar)."""
        return self.x * other.y - self.y * other.x
    
    def dot(self, other: "Point2D") -> float:
        """2D dot product."""
        return self.x * other.x + self.y * other.y


@dataclass(frozen=True)
class LineGeometry:
    """
    Line geometry in ORIGINAL_FRAME coordinates.
    
    A line consists of two points P1 and P2.
    Direction semantics define which side is IN vs OUT.
    """
    p1: Point2D
    p2: Point2D
    direction_semantics: DirectionSemantics = DirectionSemantics.SIDE_A_TO_B_IN
    
    def __post_init__(self):
        # Validate non-zero length
        if self.p1.x == self.p2.x and self.p1.y == self.p2.y:
            raise ValueError("Line must have non-zero length (p1 != p2)")
    
    @property
    def vector(self) -> Point2D:
        """Direction vector from p1 to p2."""
        return self.p2 - self.p1
    
    @property
    def length(self) -> float:
        """Line length."""
        v = self.vector
        return np.sqrt(v.x * v.x + v.y * v.y)
    
    def side_of_point(self, point: Point2D) -> int:
        """
        Determine which side of the line a point lies on.
        
        Returns:
            +1: point is on SIDE_A (left of p1->p2)
            -1: point is on SIDE_B (right of p1->p2)
            0: point is on the line (within numerical tolerance)
        """
        # Cross product of (p2-p1) x (point-p1)
        line_vec = self.vector
        point_vec = point - self.p1
        cross = line_vec.cross(point_vec)
        
        # Numerical tolerance
        eps = 1e-9
        if abs(cross) < eps:
            return 0
        return 1 if cross > 0 else -1
    
    def distance_to_line(self, point: Point2D) -> float:
        """Perpendicular distance from point to line."""
        line_vec = self.vector
        point_vec = point - self.p1
        line_len = self.length
        if line_len == 0:
            return np.sqrt(point_vec.x * point_vec.x + point_vec.y * point_vec.y)
        return abs(line_vec.cross(point_vec)) / line_len
    
    def project_point(self, point: Point2D) -> Point2D:
        """Project point onto the line."""
        line_vec = self.vector
        point_vec = point - self.p1
        line_len_sq = line_vec.x * line_vec.x + line_vec.y * line_vec.y
        if line_len_sq == 0:
            return self.p1
        t = point_vec.dot(line_vec) / line_len_sq
        return Point2D(
            self.p1.x + t * line_vec.x,
            self.p1.y + t * line_vec.y
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "line",
            "p1": self.p1.to_dict(),
            "p2": self.p2.to_dict(),
            "direction_semantics": self.direction_semantics.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LineGeometry":
        return cls(
            p1=Point2D.from_dict(data["p1"]),
            p2=Point2D.from_dict(data["p2"]),
            direction_semantics=DirectionSemantics(data.get("direction_semantics", "side_a_to_b_in")),
        )


@dataclass(frozen=True)
class ZoneGeometry:
    """
    Zone (polygon) geometry in ORIGINAL_FRAME coordinates.
    
    A zone is a polygon with 3+ vertices.
    Direction semantics define whether entering or exiting is IN.
    """
    vertices: Tuple[Point2D, ...]
    direction_semantics: DirectionSemantics = DirectionSemantics.OUTSIDE_TO_INSIDE_IN
    
    def __post_init__(self):
        if len(self.vertices) < 3:
            raise ValueError(f"Zone must have at least 3 vertices, got {len(self.vertices)}")
        # Validate no duplicate consecutive vertices
        for i in range(len(self.vertices)):
            v1 = self.vertices[i]
            v2 = self.vertices[(i + 1) % len(self.vertices)]
            if v1.x == v2.x and v1.y == v2.y:
                raise ValueError(f"Zone has duplicate consecutive vertices at index {i}")
    
    def point_in_polygon(self, point: Point2D) -> bool:
        """
        Ray casting algorithm to test if point is inside polygon.
        
        Returns:
            True if point is inside, False if outside.
            Points on boundary are considered inside.
        """
        x, y = point.x, point.y
        inside = False
        n = len(self.vertices)
        
        for i in range(n):
            v1 = self.vertices[i]
            v2 = self.vertices[(i + 1) % n]
            
            # Check if point is on edge
            if self._point_on_segment(point, v1, v2):
                return True
            
            # Ray casting
            if ((v1.y > y) != (v2.y > y)) and \
               (x < (v2.x - v1.x) * (y - v1.y) / (v2.y - v1.y) + v1.x):
                inside = not inside
        
        return inside
    
    def _point_on_segment(self, p: Point2D, a: Point2D, b: Point2D) -> bool:
        """Check if point p lies on segment ab."""
        # Cross product should be zero (collinear)
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        if abs(cross) > 1e-9:
            return False
        # Check if within bounds
        dot = (p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)
        if dot < 0:
            return False
        len_sq = (b.x - a.x) ** 2 + (b.y - a.y) ** 2
        if dot > len_sq:
            return False
        return True
    
    def distance_to_boundary(self, point: Point2D) -> float:
        """Minimum distance from point to polygon boundary."""
        min_dist = float('inf')
        n = len(self.vertices)
        
        for i in range(n):
            v1 = self.vertices[i]
            v2 = self.vertices[(i + 1) % n]
            dist = self._distance_to_segment(point, v1, v2)
            min_dist = min(min_dist, dist)
        
        return min_dist
    
    def _distance_to_segment(self, p: Point2D, a: Point2D, b: Point2D) -> float:
        """Distance from point to line segment."""
        ap = Point2D(p.x - a.x, p.y - a.y)
        ab = Point2D(b.x - a.x, b.y - a.y)
        ab_len_sq = ab.x * ab.x + ab.y * ab.y
        
        if ab_len_sq == 0:
            return np.sqrt(ap.x * ap.x + ap.y * ap.y)
        
        t = max(0, min(1, (ap.x * ab.x + ap.y * ab.y) / ab_len_sq))
        proj = Point2D(a.x + t * ab.x, a.y + t * ab.y)
        dx = p.x - proj.x
        dy = p.y - proj.y
        return np.sqrt(dx * dx + dy * dy)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "zone",
            "vertices": [v.to_dict() for v in self.vertices],
            "direction_semantics": self.direction_semantics.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ZoneGeometry":
        return cls(
            vertices=tuple(Point2D.from_dict(v) for v in data["vertices"]),
            direction_semantics=DirectionSemantics(data.get("direction_semantics", "outside_to_inside_in")),
        )


@dataclass(frozen=True)
class CrossingPolicyConfig:
    """
    Configurable crossing detection policy.
    
    Prevents event spam through hysteresis and debouncing.
    """
    # Minimum distance a trajectory must cross the boundary
    min_crossing_distance: float = 5.0  # pixels in ORIGINAL_FRAME
    
    # Temporal debounce: minimum time between crossing events for same track
    temporal_debounce_seconds: float = 1.0
    
    # Side transition confirmation: require N consecutive frames on new side
    side_confirmation_frames: int = 2
    
    # Maximum gap in trajectory samples (frames) before resetting crossing state
    max_trajectory_gap_frames: int = 5
    
    # Crossing policy
    crossing_policy: CrossingPolicy = CrossingPolicy.STRICT
    
    def __post_init__(self):
        if self.min_crossing_distance < 0:
            raise ValueError("min_crossing_distance must be >= 0")
        if self.temporal_debounce_seconds < 0:
            raise ValueError("temporal_debounce_seconds must be >= 0")
        if self.side_confirmation_frames < 1:
            raise ValueError("side_confirmation_frames must be >= 1")
        if self.max_trajectory_gap_frames < 1:
            raise ValueError("max_trajectory_gap_frames must be >= 1")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_crossing_distance": self.min_crossing_distance,
            "temporal_debounce_seconds": self.temporal_debounce_seconds,
            "side_confirmation_frames": self.side_confirmation_frames,
            "max_trajectory_gap_frames": self.max_trajectory_gap_frames,
            "crossing_policy": self.crossing_policy.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossingPolicyConfig":
        return cls(
            min_crossing_distance=data.get("min_crossing_distance", 5.0),
            temporal_debounce_seconds=data.get("temporal_debounce_seconds", 1.0),
            side_confirmation_frames=data.get("side_confirmation_frames", 2),
            max_trajectory_gap_frames=data.get("max_trajectory_gap_frames", 5),
            crossing_policy=CrossingPolicy(data.get("crossing_policy", "strict")),
        )


@dataclass(frozen=True)
class CameraGeometryConfig:
    """
    Versioned camera geometry configuration.
    
    Contains all geometry definitions for a single camera.
    All coordinates in ORIGINAL_FRAME space.
    """
    # Camera identification
    camera_id: str
    
    # Frame dimensions (source frame)
    frame_width: int
    frame_height: int
    
    # Coordinate space (always ORIGINAL_FRAME)
    coordinate_space: CoordinateSpace = CoordinateSpace.ORIGINAL_FRAME
    
    # Geometry definition
    geometry_type: GeometryType = GeometryType.LINE
    line: Optional[LineGeometry] = None
    zone: Optional[ZoneGeometry] = None
    
    # Crossing policy
    crossing_policy: CrossingPolicyConfig = field(default_factory=CrossingPolicyConfig)
    
    # Versioning
    version: int = 1
    config_hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError(f"Invalid frame dimensions: {self.frame_width}x{self.frame_height}")
        if self.coordinate_space != CoordinateSpace.ORIGINAL_FRAME:
            raise ValueError(f"coordinate_space must be ORIGINAL_FRAME, got {self.coordinate_space}")
        
        # Validate geometry matches type
        if self.geometry_type == GeometryType.LINE:
            if self.line is None:
                raise ValueError("LINE geometry requires line field")
            if self.zone is not None:
                raise ValueError("LINE geometry must not have zone field")
        elif self.geometry_type == GeometryType.ZONE:
            if self.zone is None:
                raise ValueError("ZONE geometry requires zone field")
            if self.line is not None:
                raise ValueError("ZONE geometry must not have line field")
        
        # Validate geometry within frame bounds
        self._validate_geometry_bounds()
        
        # Compute config hash if not provided
        if not self.config_hash:
            object.__setattr__(self, 'config_hash', self._compute_hash())
    
    def _validate_geometry_bounds(self) -> None:
        """Validate all geometry coordinates are within frame bounds."""
        def check_point(p: Point2D, name: str):
            if p.x < 0 or p.x > self.frame_width or p.y < 0 or p.y > self.frame_height:
                raise ValueError(
                    f"{name} point ({p.x}, {p.y}) outside frame bounds "
                    f"({self.frame_width}x{self.frame_height})"
                )
        
        if self.line:
            check_point(self.line.p1, "line.p1")
            check_point(self.line.p2, "line.p2")
        
        if self.zone:
            for i, v in enumerate(self.zone.vertices):
                check_point(v, f"zone.vertices[{i}]")
    
    def _compute_hash(self) -> str:
        """Compute deterministic hash of configuration content."""
        content = {
            "camera_id": self.camera_id,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "geometry_type": self.geometry_type.value,
            "line": self.line.to_dict() if self.line else None,
            "zone": self.zone.to_dict() if self.zone else None,
            "crossing_policy": self.crossing_policy.to_dict(),
            "direction_semantics": (
                self.line.direction_semantics.value if self.line 
                else self.zone.direction_semantics.value if self.zone else None
            ),
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "coordinate_space": self.coordinate_space.value,
            "geometry_type": self.geometry_type.value,
            "line": self.line.to_dict() if self.line else None,
            "zone": self.zone.to_dict() if self.zone else None,
            "crossing_policy": self.crossing_policy.to_dict(),
            "version": self.version,
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "description": self.description,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraGeometryConfig":
        line = LineGeometry.from_dict(data["line"]) if data.get("line") else None
        zone = ZoneGeometry.from_dict(data["zone"]) if data.get("zone") else None
        crossing_policy = CrossingPolicyConfig.from_dict(data.get("crossing_policy", {}))
        
        return cls(
            camera_id=data["camera_id"],
            frame_width=data["frame_width"],
            frame_height=data["frame_height"],
            coordinate_space=CoordinateSpace(data.get("coordinate_space", "original_frame")),
            geometry_type=GeometryType(data.get("geometry_type", "line")),
            line=line,
            zone=zone,
            crossing_policy=crossing_policy,
            version=data.get("version", 1),
            config_hash=data.get("config_hash", ""),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
        )
    
    def with_updated_geometry(
        self,
        line: Optional[LineGeometry] = None,
        zone: Optional[ZoneGeometry] = None,
        crossing_policy: Optional[CrossingPolicyConfig] = None,
        version: Optional[int] = None,
    ) -> "CameraGeometryConfig":
        """Create a new version with updated geometry."""
        new_version = version if version is not None else self.version + 1
        return CameraGeometryConfig(
            camera_id=self.camera_id,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
            coordinate_space=self.coordinate_space,
            geometry_type=self.geometry_type,
            line=line if line is not None else self.line,
            zone=zone if zone is not None else self.zone,
            crossing_policy=crossing_policy if crossing_policy is not None else self.crossing_policy,
            version=new_version,
            created_at=self.created_at,
            updated_at=datetime.utcnow().isoformat() + "Z",
            description=self.description,
            tags=self.tags,
        )


@dataclass(frozen=True)
class GeometryConfigSnapshot:
    """
    Immutable snapshot of geometry configuration for provenance.
    
    Stored with CrossingEvent to ensure forensic reproducibility.
    """
    camera_id: str
    config_hash: str
    version: int
    geometry_type: GeometryType
    line: Optional[Dict[str, Any]] = None
    zone: Optional[Dict[str, Any]] = None
    crossing_policy: Optional[Dict[str, Any]] = None
    frame_width: int = 0
    frame_height: int = 0
    coordinate_space: str = "original_frame"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "config_hash": self.config_hash,
            "version": self.version,
            "geometry_type": self.geometry_type.value,
            "line": self.line,
            "zone": self.zone,
            "crossing_policy": self.crossing_policy,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "coordinate_space": self.coordinate_space,
        }
    
    @classmethod
    def from_config(cls, config: CameraGeometryConfig) -> "GeometryConfigSnapshot":
        return cls(
            camera_id=config.camera_id,
            config_hash=config.config_hash,
            version=config.version,
            geometry_type=config.geometry_type,
            line=config.line.to_dict() if config.line else None,
            zone=config.zone.to_dict() if config.zone else None,
            crossing_policy=config.crossing_policy.to_dict(),
            frame_width=config.frame_width,
            frame_height=config.frame_height,
            coordinate_space=config.coordinate_space.value,
        )


def create_line_geometry(
    camera_id: str,
    frame_width: int,
    frame_height: int,
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    direction_semantics: DirectionSemantics = DirectionSemantics.SIDE_A_TO_B_IN,
    crossing_policy: Optional[CrossingPolicyConfig] = None,
    version: int = 1,
    description: str = "",
    tags: List[str] = None,
) -> CameraGeometryConfig:
    """Factory function to create a LINE geometry configuration."""
    line = LineGeometry(
        p1=Point2D(p1[0], p1[1]),
        p2=Point2D(p2[0], p2[1]),
        direction_semantics=direction_semantics,
    )
    return CameraGeometryConfig(
        camera_id=camera_id,
        frame_width=frame_width,
        frame_height=frame_height,
        geometry_type=GeometryType.LINE,
        line=line,
        crossing_policy=crossing_policy or CrossingPolicyConfig(),
        version=version,
        description=description,
        tags=tags or [],
    )


def create_zone_geometry(
    camera_id: str,
    frame_width: int,
    frame_height: int,
    vertices: List[Tuple[float, float]],
    direction_semantics: DirectionSemantics = DirectionSemantics.OUTSIDE_TO_INSIDE_IN,
    crossing_policy: Optional[CrossingPolicyConfig] = None,
    version: int = 1,
    description: str = "",
    tags: List[str] = None,
) -> CameraGeometryConfig:
    """Factory function to create a ZONE geometry configuration."""
    zone = ZoneGeometry(
        vertices=tuple(Point2D(v[0], v[1]) for v in vertices),
        direction_semantics=direction_semantics,
    )
    return CameraGeometryConfig(
        camera_id=camera_id,
        frame_width=frame_width,
        frame_height=frame_height,
        geometry_type=GeometryType.ZONE,
        zone=zone,
        crossing_policy=crossing_policy or CrossingPolicyConfig(),
        version=version,
        description=description,
        tags=tags or [],
    )


def load_geometry_config(path: str) -> CameraGeometryConfig:
    """Load geometry configuration from JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return CameraGeometryConfig.from_dict(data)


def save_geometry_config(config: CameraGeometryConfig, path: str) -> None:
    """Save geometry configuration to JSON file."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
