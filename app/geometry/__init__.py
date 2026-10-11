"""
Phase 22 — IN/OUT Geometry Configuration & Crossing Semantics.

This module provides:
- CameraGeometryConfig: Versioned camera-specific geometry configuration
- LineGeometry / ZoneGeometry: Geometry primitives in ORIGINAL_FRAME coordinates
- DisplayTransform: Deterministic coordinate transforms for UI rendering
- CrossingEngine: Crossing detection with hysteresis/debounce
- CrossingEvent: Canonical crossing event with full provenance
- GeometryVersionManager: Versioning and audit trail
"""

from app.geometry.contract import (
    # Enums
    CoordinateSpace,
    GeometryType,
    DirectionSemantics,
    CrossingPolicy,
    CrossingPolicyConfig,
    
    # Core types
    Point2D,
    LineGeometry,
    ZoneGeometry,
    CameraGeometryConfig,
    GeometryConfigSnapshot,
    
    # Factory functions
    create_line_geometry,
    create_zone_geometry,
    load_geometry_config,
    save_geometry_config,
)

from app.geometry.versioning import (
    validate_geometry_config,
)

from app.geometry.transform import (
    DisplayTransform,
    TransformProvenance,
    create_display_transform,
    create_transform_for_ui,
    validate_round_trip,
)

from app.geometry.crossing import (
    CrossingDirection,
    CrossingEventType,
    TrajectoryPoint,
    CrossingEvent,
    TrackCrossingState,
    CrossingEngine,
    create_crossing_engine,
    process_tracks_for_crossings,
)

from app.geometry.versioning import (
    GeometryVersion,
    GeometryVersionManager,
    create_version_manager,
    load_geometry_from_file,
    save_geometry_to_file,
)

__all__ = [
    # Contract
    "CoordinateSpace",
    "GeometryType",
    "DirectionSemantics",
    "CrossingPolicy",
    "Point2D",
    "LineGeometry",
    "ZoneGeometry",
    "CrossingPolicyConfig",
    "CameraGeometryConfig",
    "GeometryConfigSnapshot",
    "create_line_geometry",
    "create_zone_geometry",
    "load_geometry_config",
    "save_geometry_config",
    "validate_geometry_config",
    
    # Transform
    "DisplayTransform",
    "TransformProvenance",
    "create_display_transform",
    "create_transform_for_ui",
    "validate_round_trip",
    
    # Crossing
    "CrossingDirection",
    "CrossingEventType",
    "TrajectoryPoint",
    "CrossingEvent",
    "TrackCrossingState",
    "CrossingEngine",
    "create_crossing_engine",
    "process_tracks_for_crossings",
    
    # Versioning
    "GeometryVersion",
    "GeometryVersionManager",
    "create_version_manager",
    "load_geometry_from_file",
    "save_geometry_to_file",
]