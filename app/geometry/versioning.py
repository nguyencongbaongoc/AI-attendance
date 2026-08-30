"""
Phase 22 — Geometry Versioning Module.

Handles versioning, serialization, and migration of camera geometry configurations.
Ensures forensic reproducibility of crossing events.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.geometry.contract import (
    CameraGeometryConfig,
    CrossingPolicyConfig,
    DirectionSemantics,
    GeometryConfigSnapshot,
    GeometryType,
    LineGeometry,
    Point2D,
    ZoneGeometry,
    create_line_geometry,
    create_zone_geometry,
    load_geometry_config,
    save_geometry_config,
)


@dataclass(frozen=True)
class GeometryVersion:
    """
    Represents a version of a camera geometry configuration.
    
    Immutable record for audit trail.
    """
    camera_id: str
    version: int
    config_hash: str
    geometry_type: GeometryType
    created_at: str
    description: str = ""
    author: str = ""
    
    # Full config snapshot for reproducibility
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "version": self.version,
            "config_hash": self.config_hash,
            "geometry_type": self.geometry_type.value,
            "created_at": self.created_at,
            "description": self.description,
            "author": self.author,
            "config_snapshot": self.config_snapshot,
        }
    
    @classmethod
    def from_config(cls, config: CameraGeometryConfig, author: str = "") -> "GeometryVersion":
        return cls(
            camera_id=config.camera_id,
            version=config.version,
            config_hash=config.config_hash,
            geometry_type=config.geometry_type,
            created_at=config.created_at,
            description=config.description,
            author=author,
            config_snapshot=config.to_dict(),
        )


class GeometryVersionManager:
    """
    Manages versioned geometry configurations for cameras.
    
    Provides:
    - Version history per camera
    - Configuration migration
    - Compatibility checking
    - Audit trail
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize version manager.
        
        Args:
            storage_dir: Directory to store version history (optional)
        """
        self.storage_dir = Path(storage_dir) if storage_dir else None
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory version history: camera_id -> List[GeometryVersion]
        self._versions: Dict[str, List[GeometryVersion]] = {}
        
        # Current configs: camera_id -> CameraGeometryConfig
        self._current_configs: Dict[str, CameraGeometryConfig] = {}
    
    def register_config(
        self,
        config: CameraGeometryConfig,
        author: str = "",
    ) -> GeometryVersion:
        """
        Register a new geometry configuration version.
        
        Args:
            config: Camera geometry configuration
            author: Optional author identifier
            
        Returns:
            GeometryVersion record
        """
        camera_id = config.camera_id
        
        # Create version record
        version = GeometryVersion.from_config(config, author)
        
        # Store in history
        if camera_id not in self._versions:
            self._versions[camera_id] = []
        self._versions[camera_id].append(version)
        
        # Update current config
        self._current_configs[camera_id] = config
        
        # Persist if storage configured
        if self.storage_dir:
            self._persist_version(camera_id, version)
        
        return version
    
    def get_current_config(self, camera_id: str) -> Optional[CameraGeometryConfig]:
        """Get the current configuration for a camera."""
        return self._current_configs.get(camera_id)
    
    def get_version_history(self, camera_id: str) -> List[GeometryVersion]:
        """Get full version history for a camera."""
        return list(self._versions.get(camera_id, []))
    
    def get_version(self, camera_id: str, version: int) -> Optional[GeometryVersion]:
        """Get a specific version for a camera."""
        for v in self._versions.get(camera_id, []):
            if v.version == version:
                return v
        return None
    
    def get_latest_version(self, camera_id: str) -> Optional[GeometryVersion]:
        """Get the latest version for a camera."""
        versions = self._versions.get(camera_id, [])
        return versions[-1] if versions else None
    
    def update_config(
        self,
        camera_id: str,
        line: Optional[LineGeometry] = None,
        zone: Optional[ZoneGeometry] = None,
        crossing_policy: Optional[CrossingPolicyConfig] = None,
        description: str = "",
        author: str = "",
    ) -> CameraGeometryConfig:
        """
        Create a new version with updated geometry.
        
        Args:
            camera_id: Camera identifier
            line: New line geometry (for LINE type)
            zone: New zone geometry (for ZONE type)
            crossing_policy: New crossing policy
            description: Change description
            author: Author identifier
            
        Returns:
            New CameraGeometryConfig with incremented version
        """
        current = self.get_current_config(camera_id)
        if not current:
            raise ValueError(f"No configuration found for camera {camera_id}")
        
        new_config = current.with_updated_geometry(
            line=line,
            zone=zone,
            crossing_policy=crossing_policy,
        )
        
        # Update description if provided
        if description:
            # Create new config with updated description
            new_config = CameraGeometryConfig(
                camera_id=new_config.camera_id,
                frame_width=new_config.frame_width,
                frame_height=new_config.frame_height,
                coordinate_space=new_config.coordinate_space,
                geometry_type=new_config.geometry_type,
                line=new_config.line,
                zone=new_config.zone,
                crossing_policy=new_config.crossing_policy,
                version=new_config.version,
                config_hash=new_config.config_hash,
                created_at=new_config.created_at,
                updated_at=datetime.utcnow().isoformat() + "Z",
                description=description,
                tags=new_config.tags,
            )
        
        self.register_config(new_config, author)
        return new_config
    
    def _persist_version(self, camera_id: str, version: GeometryVersion) -> None:
        """Persist version to storage."""
        if not self.storage_dir:
            return
        
        camera_dir = self.storage_dir / camera_id
        camera_dir.mkdir(exist_ok=True)
        
        version_file = camera_dir / f"v{version.version:04d}.json"
        with open(version_file, 'w', encoding='utf-8') as f:
            json.dump(version.to_dict(), f, indent=2, ensure_ascii=False)
        
        # Update current symlink/reference
        current_file = camera_dir / "current.json"
        with open(current_file, 'w', encoding='utf-8') as f:
            json.dump(version.to_dict(), f, indent=2, ensure_ascii=False)
    
    def load_from_storage(self, camera_id: str) -> List[GeometryVersion]:
        """Load version history from storage."""
        if not self.storage_dir:
            return []
        
        camera_dir = self.storage_dir / camera_id
        if not camera_dir.exists():
            return []
        
        versions = []
        for version_file in sorted(camera_dir.glob("v*.json")):
            with open(version_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            version = GeometryVersion(
                camera_id=data["camera_id"],
                version=data["version"],
                config_hash=data["config_hash"],
                geometry_type=GeometryType(data["geometry_type"]),
                created_at=data["created_at"],
                description=data.get("description", ""),
                author=data.get("author", ""),
                config_snapshot=data.get("config_snapshot", {}),
            )
            versions.append(version)
        
        self._versions[camera_id] = versions
        
        # Load current config
        current_file = camera_dir / "current.json"
        if current_file.exists():
            with open(current_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            config = CameraGeometryConfig.from_dict(data["config_snapshot"])
            self._current_configs[camera_id] = config
        
        return versions
    
    def check_compatibility(
        self,
        config1: CameraGeometryConfig,
        config2: CameraGeometryConfig,
    ) -> Dict[str, Any]:
        """
        Check compatibility between two geometry configurations.
        
        Returns:
            Dict with compatibility analysis
        """
        result = {
            "compatible": True,
            "warnings": [],
            "errors": [],
            "changes": [],
        }
        
        # Check camera ID
        if config1.camera_id != config2.camera_id:
            result["errors"].append("Camera ID mismatch")
            result["compatible"] = False
        
        # Check frame dimensions
        if config1.frame_width != config2.frame_width or config1.frame_height != config2.frame_height:
            result["warnings"].append(
                f"Frame dimensions changed: {config1.frame_width}x{config1.frame_height} -> "
                f"{config2.frame_width}x{config2.frame_height}"
            )
            result["changes"].append("frame_dimensions")
        
        # Check geometry type
        if config1.geometry_type != config2.geometry_type:
            result["warnings"].append(
                f"Geometry type changed: {config1.geometry_type.value} -> {config2.geometry_type.value}"
            )
            result["changes"].append("geometry_type")
        
        # Check line geometry
        if config1.line and config2.line:
            if (config1.line.p1.x != config2.line.p1.x or config1.line.p1.y != config2.line.p1.y or
                config1.line.p2.x != config2.line.p2.x or config1.line.p2.y != config2.line.p2.y):
                result["changes"].append("line_coordinates")
            if config1.line.direction_semantics != config2.line.direction_semantics:
                result["warnings"].append(
                    f"Line direction semantics changed: {config1.line.direction_semantics.value} -> "
                    f"{config2.line.direction_semantics.value}"
                )
                result["changes"].append("direction_semantics")
        elif config1.line != config2.line:
            result["changes"].append("line_geometry")
        
        # Check zone geometry
        if config1.zone and config2.zone:
            if len(config1.zone.vertices) != len(config2.zone.vertices):
                result["changes"].append("zone_vertex_count")
            else:
                for i, (v1, v2) in enumerate(zip(config1.zone.vertices, config2.zone.vertices)):
                    if v1.x != v2.x or v1.y != v2.y:
                        result["changes"].append(f"zone_vertex_{i}")
                        break
            if config1.zone.direction_semantics != config2.zone.direction_semantics:
                result["warnings"].append(
                    f"Zone direction semantics changed: {config1.zone.direction_semantics.value} -> "
                    f"{config2.zone.direction_semantics.value}"
                )
                result["changes"].append("direction_semantics")
        elif config1.zone != config2.zone:
            result["changes"].append("zone_geometry")
        
        # Check crossing policy
        if config1.crossing_policy != config2.crossing_policy:
            result["changes"].append("crossing_policy")
        
        return result
    
    def migrate_config(
        self,
        config: CameraGeometryConfig,
        target_frame_width: int,
        target_frame_height: int,
    ) -> CameraGeometryConfig:
        """
        Migrate configuration to new frame dimensions.
        
        WARNING: This changes the coordinate space semantics.
        Only use when source frame resolution actually changes.
        
        Args:
            config: Current configuration
            target_frame_width: New frame width
            target_frame_height: New frame height
            
        Returns:
            New configuration with scaled coordinates
        """
        if config.frame_width == target_frame_width and config.frame_height == target_frame_height:
            return config
        
        scale_x = target_frame_width / config.frame_width
        scale_y = target_frame_height / config.frame_height
        
        # Scale line geometry
        new_line = None
        if config.line:
            new_line = LineGeometry(
                p1=Point2D(config.line.p1.x * scale_x, config.line.p1.y * scale_y),
                p2=Point2D(config.line.p2.x * scale_x, config.line.p2.y * scale_y),
                direction_semantics=config.line.direction_semantics,
            )
        
        # Scale zone geometry
        new_zone = None
        if config.zone:
            new_zone = ZoneGeometry(
                vertices=tuple(
                    Point2D(v.x * scale_x, v.y * scale_y) for v in config.zone.vertices
                ),
                direction_semantics=config.zone.direction_semantics,
            )
        
        return CameraGeometryConfig(
            camera_id=config.camera_id,
            frame_width=target_frame_width,
            frame_height=target_frame_height,
            coordinate_space=config.coordinate_space,
            geometry_type=config.geometry_type,
            line=new_line,
            zone=new_zone,
            crossing_policy=config.crossing_policy,
            version=config.version + 1,
            description=f"Migrated from {config.frame_width}x{config.frame_height} to {target_frame_width}x{target_frame_height}",
            tags=config.tags + ["migrated"],
        )


def create_version_manager(storage_dir: Optional[str] = None) -> GeometryVersionManager:
    """Factory function to create a GeometryVersionManager."""
    return GeometryVersionManager(storage_dir)


def load_geometry_from_file(path: str) -> CameraGeometryConfig:
    """Load geometry configuration from JSON file."""
    return load_geometry_config(path)


def save_geometry_to_file(config: CameraGeometryConfig, path: str) -> None:
    """Save geometry configuration to JSON file."""
    save_geometry_config(config, path)


def validate_geometry_config(config: CameraGeometryConfig) -> Dict[str, Any]:
    """
    Validate a geometry configuration.
    
    Returns:
        Dict with validation results
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
    }
    
    # Check required fields
    if not config.camera_id:
        result["errors"].append("camera_id is required")
        result["valid"] = False
    
    if config.frame_width <= 0 or config.frame_height <= 0:
        result["errors"].append("Invalid frame dimensions")
        result["valid"] = False
    
    # Check geometry
    if config.geometry_type == GeometryType.LINE:
        if not config.line:
            result["errors"].append("LINE geometry requires line field")
            result["valid"] = False
        else:
            # Validate line coordinates
            if config.line.p1.x == config.line.p2.x and config.line.p1.y == config.line.p2.y:
                result["errors"].append("Line has zero length")
                result["valid"] = False
    elif config.geometry_type == GeometryType.ZONE:
        if not config.zone:
            result["errors"].append("ZONE geometry requires zone field")
            result["valid"] = False
        else:
            if len(config.zone.vertices) < 3:
                result["errors"].append("Zone must have at least 3 vertices")
                result["valid"] = False
    
    # Check bounds
    def check_point(p: Point2D, name: str):
        if p.x < 0 or p.x > config.frame_width or p.y < 0 or p.y > config.frame_height:
            result["warnings"].append(f"{name} point ({p.x}, {p.y}) outside frame bounds")
    
    if config.line:
        check_point(config.line.p1, "line.p1")
        check_point(config.line.p2, "line.p2")
    
    if config.zone:
        for i, v in enumerate(config.zone.vertices):
            check_point(v, f"zone.vertices[{i}]")
    
    return result
