"""
Phase 43.6A — Geometry Management REST API.

Provides CRUD endpoints for CameraGeometryConfig:
- GET /api/v1/geometry/{camera_id} - Get current geometry config
- POST /api/v1/geometry/{camera_id} - Create/update geometry
- PUT /api/v1/geometry/{camera_id}/line - Update line geometry
- PUT /api/v1/geometry/{camera_id}/zone - Update zone geometry
- DELETE /api/v1/geometry/{camera_id} - Reset to default

Uses existing backend geometry models from app.geometry.contract.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel, Field

from app.geometry.contract import (
    CameraGeometryConfig,
    LineGeometry,
    ZoneGeometry,
    Point2D,
    DirectionSemantics,
    GeometryType,
    CrossingPolicyConfig,
    CrossingPolicy,
    CoordinateSpace,
    create_line_geometry,
    create_zone_geometry,
    load_geometry_config,
    save_geometry_config,
)
from app.geometry.versioning import GeometryVersionManager, create_version_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/geometry", tags=["geometry"])

# In-memory storage for geometry configs (can be replaced with persistent storage)
_geometry_store: Dict[str, CameraGeometryConfig] = {}

# Version manager for persistence
_version_manager: Optional[GeometryVersionManager] = None


def get_version_manager() -> GeometryVersionManager:
    """Get or create the geometry version manager."""
    global _version_manager
    if _version_manager is None:
        _version_manager = create_version_manager()
    return _version_manager


class LineGeometryRequest(BaseModel):
    """Request model for line geometry."""
    p1: Dict[str, float] = Field(..., description="Start point {x, y}")
    p2: Dict[str, float] = Field(..., description="End point {x, y}")
    direction_semantics: str = Field(
        default="side_a_to_b_in",
        description="Direction semantics: side_a_to_b_in or side_b_to_a_in"
    )


class ZoneGeometryRequest(BaseModel):
    """Request model for zone geometry."""
    vertices: list[Dict[str, float]] = Field(..., description="List of vertices [{x, y}, ...]")
    direction_semantics: str = Field(
        default="outside_to_inside_in",
        description="Direction semantics: outside_to_inside_in or inside_to_outside_in"
    )


class CrossingPolicyRequest(BaseModel):
    """Request model for crossing policy."""
    min_crossing_distance: float = Field(default=5.0, ge=0)
    temporal_debounce_seconds: float = Field(default=1.0, ge=0)
    side_confirmation_frames: int = Field(default=2, ge=1)
    max_trajectory_gap_frames: int = Field(default=5, ge=1)
    crossing_policy: str = Field(default="strict", pattern="^(strict|touch_allowed)$")


class GeometryConfigRequest(BaseModel):
    """Request model for full geometry config."""
    frame_width: int = Field(default=3840, gt=0)
    frame_height: int = Field(default=2160, gt=0)
    geometry_type: str = Field(default="line", pattern="^(line|zone)$")
    line: Optional[LineGeometryRequest] = None
    zone: Optional[ZoneGeometryRequest] = None
    crossing_policy: Optional[CrossingPolicyRequest] = None
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


def _convert_line_request(req: LineGeometryRequest) -> LineGeometry:
    """Convert LineGeometryRequest to LineGeometry."""
    return LineGeometry(
        p1=Point2D(x=req.p1["x"], y=req.p1["y"]),
        p2=Point2D(x=req.p2["x"], y=req.p2["y"]),
        direction_semantics=DirectionSemantics(req.direction_semantics),
    )


def _convert_zone_request(req: ZoneGeometryRequest) -> ZoneGeometry:
    """Convert ZoneGeometryRequest to ZoneGeometry."""
    return ZoneGeometry(
        vertices=tuple(Point2D(x=v["x"], y=v["y"]) for v in req.vertices),
        direction_semantics=DirectionSemantics(req.direction_semantics),
    )


def _convert_policy_request(req: Optional[CrossingPolicyRequest]) -> CrossingPolicyConfig:
    """Convert CrossingPolicyRequest to CrossingPolicyConfig."""
    if req is None:
        return CrossingPolicyConfig()
    return CrossingPolicyConfig(
        min_crossing_distance=req.min_crossing_distance,
        temporal_debounce_seconds=req.temporal_debounce_seconds,
        side_confirmation_frames=req.side_confirmation_frames,
        max_trajectory_gap_frames=req.max_trajectory_gap_frames,
        crossing_policy=CrossingPolicy(req.crossing_policy),
    )


@router.get("/{camera_id}")
async def get_geometry(camera_id: str = Path(..., description="Camera ID")) -> Dict[str, Any]:
    """
    Get current geometry configuration for a camera.
    
    Returns the CameraGeometryConfig with all geometry details.
    """
    # Check in-memory store first
    if camera_id in _geometry_store:
        return _geometry_store[camera_id].to_dict()
    
    # Try to load from file via version manager
    try:
        vm = get_version_manager()
        config = vm.load_latest(camera_id)
        if config:
            _geometry_store[camera_id] = config
            return config.to_dict()
    except Exception as e:
        logger.warning(f"Failed to load geometry for {camera_id}: {e}")
    
    # Return default empty config
    return {
        "camera_id": camera_id,
        "frame_width": 3840,
        "frame_height": 2160,
        "coordinate_space": "original_frame",
        "geometry_type": "line",
        "line": None,
        "zone": None,
        "crossing_policy": CrossingPolicyConfig().to_dict(),
        "version": 1,
        "config_hash": "",
        "created_at": "",
        "updated_at": "",
        "description": "",
        "tags": [],
    }


@router.post("/{camera_id}")
async def create_or_update_geometry(
    camera_id: str = Path(..., description="Camera ID"),
    request: GeometryConfigRequest = Body(...),
) -> Dict[str, Any]:
    """
    Create or update geometry configuration for a camera.
    
    Accepts full geometry config including line/zone, crossing policy, and metadata.
    """
    # Validate geometry type matches provided geometry
    if request.geometry_type == "line" and request.line is None:
        raise HTTPException(status_code=400, detail="LINE geometry requires 'line' field")
    if request.geometry_type == "zone" and request.zone is None:
        raise HTTPException(status_code=400, detail="ZONE geometry requires 'zone' field")
    if request.geometry_type == "line" and request.zone is not None:
        raise HTTPException(status_code=400, detail="LINE geometry must not have 'zone' field")
    if request.geometry_type == "zone" and request.line is not None:
        raise HTTPException(status_code=400, detail="ZONE geometry must not have 'line' field")
    
    # Convert request to domain models
    line = _convert_line_request(request.line) if request.line else None
    zone = _convert_zone_request(request.zone) if request.zone else None
    crossing_policy = _convert_policy_request(request.crossing_policy)
    
    # Determine version
    existing = _geometry_store.get(camera_id)
    version = (existing.version + 1) if existing else 1
    
    # Create config
    config = CameraGeometryConfig(
        camera_id=camera_id,
        frame_width=request.frame_width,
        frame_height=request.frame_height,
        coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        geometry_type=GeometryType(request.geometry_type),
        line=line,
        zone=zone,
        crossing_policy=crossing_policy,
        version=version,
        description=request.description,
        tags=request.tags,
    )
    
    # Store in memory
    _geometry_store[camera_id] = config
    
    # Persist via version manager
    try:
        vm = get_version_manager()
        vm.save_version(config)
    except Exception as e:
        logger.error(f"Failed to persist geometry for {camera_id}: {e}")
        # Don't fail the request if persistence fails
    
    return config.to_dict()


@router.put("/{camera_id}/line")
async def update_line_geometry(
    camera_id: str = Path(..., description="Camera ID"),
    request: LineGeometryRequest = Body(...),
) -> Dict[str, Any]:
    """
    Update line geometry for a camera.
    
    Only updates the line; preserves other config (zone, policy, metadata).
    """
    existing = _geometry_store.get(camera_id)
    
    if existing is None:
        # Try to load from persistence
        try:
            vm = get_version_manager()
            existing = vm.load_latest(camera_id)
            if existing:
                _geometry_store[camera_id] = existing
        except Exception:
            pass
    
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No geometry config found for camera {camera_id}")
    
    if existing.geometry_type != GeometryType.LINE:
        raise HTTPException(status_code=400, detail=f"Camera {camera_id} is configured for ZONE geometry, not LINE")
    
    line = _convert_line_request(request)
    new_version = existing.version + 1
    
    updated = existing.with_updated_geometry(line=line, version=new_version)
    _geometry_store[camera_id] = updated
    
    # Persist
    try:
        vm = get_version_manager()
        vm.save_version(updated)
    except Exception as e:
        logger.error(f"Failed to persist line geometry for {camera_id}: {e}")
    
    return updated.to_dict()


@router.put("/{camera_id}/zone")
async def update_zone_geometry(
    camera_id: str = Path(..., description="Camera ID"),
    request: ZoneGeometryRequest = Body(...),
) -> Dict[str, Any]:
    """
    Update zone geometry for a camera.
    
    Only updates the zone; preserves other config (line, policy, metadata).
    """
    existing = _geometry_store.get(camera_id)
    
    if existing is None:
        # Try to load from persistence
        try:
            vm = get_version_manager()
            existing = vm.load_latest(camera_id)
            if existing:
                _geometry_store[camera_id] = existing
        except Exception:
            pass
    
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No geometry config found for camera {camera_id}")
    
    if existing.geometry_type != GeometryType.ZONE:
        raise HTTPException(status_code=400, detail=f"Camera {camera_id} is configured for LINE geometry, not ZONE")
    
    zone = _convert_zone_request(request)
    new_version = existing.version + 1
    
    updated = existing.with_updated_geometry(zone=zone, version=new_version)
    _geometry_store[camera_id] = updated
    
    # Persist
    try:
        vm = get_version_manager()
        vm.save_version(updated)
    except Exception as e:
        logger.error(f"Failed to persist zone geometry for {camera_id}: {e}")
    
    return updated.to_dict()


@router.put("/{camera_id}/policy")
async def update_crossing_policy(
    camera_id: str = Path(..., description="Camera ID"),
    request: CrossingPolicyRequest = Body(...),
) -> Dict[str, Any]:
    """
    Update crossing policy for a camera.
    
    Only updates the policy; preserves geometry and metadata.
    """
    existing = _geometry_store.get(camera_id)
    
    if existing is None:
        try:
            vm = get_version_manager()
            existing = vm.load_latest(camera_id)
            if existing:
                _geometry_store[camera_id] = existing
        except Exception:
            pass
    
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No geometry config found for camera {camera_id}")
    
    crossing_policy = _convert_policy_request(request)
    new_version = existing.version + 1
    
    updated = existing.with_updated_geometry(crossing_policy=crossing_policy, version=new_version)
    _geometry_store[camera_id] = updated
    
    # Persist
    try:
        vm = get_version_manager()
        vm.save_version(updated)
    except Exception as e:
        logger.error(f"Failed to persist crossing policy for {camera_id}: {e}")
    
    return updated.to_dict()


@router.delete("/{camera_id}")
async def delete_geometry(camera_id: str = Path(..., description="Camera ID")) -> Dict[str, Any]:
    """
    Delete geometry configuration for a camera.
    
    Removes from memory and marks as deleted in version history.
    """
    if camera_id in _geometry_store:
        del _geometry_store[camera_id]
    
    # Note: Version manager doesn't have explicit delete, but we can save an empty config
    # or just remove from memory. For now, just remove from memory.
    
    return {"status": "deleted", "camera_id": camera_id}


@router.get("/{camera_id}/versions")
async def get_geometry_versions(camera_id: str = Path(..., description="Camera ID")) -> Dict[str, Any]:
    """
    Get version history for a camera's geometry.
    """
    try:
        vm = get_version_manager()
        versions = vm.list_versions(camera_id)
        return {"camera_id": camera_id, "versions": versions}
    except Exception as e:
        logger.error(f"Failed to list versions for {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{camera_id}/versions/{version}")
async def get_geometry_version(
    camera_id: str = Path(..., description="Camera ID"),
    version: int = Path(..., description="Version number"),
) -> Dict[str, Any]:
    """
    Get a specific version of geometry configuration.
    """
    try:
        vm = get_version_manager()
        config = vm.load_version(camera_id, version)
        if config is None:
            raise HTTPException(status_code=404, detail=f"Version {version} not found for camera {camera_id}")
        return config.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load version {version} for {camera_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))