"""
Phase 20 — Replay Manifest.

Contains all information required to reproduce a replay.
Serializable for audit and regression testing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.replay.source import ReplaySourceConfig


@dataclass(frozen=True)
class ReplaySourceManifest:
    """Manifest for a single replay source."""
    camera_id: str
    source_path: str
    source_metadata: Dict[str, Any]  # width, height, fps, frame_count, duration, codec
    timestamp_policy: str  # "pts" or "frame_index_fps"
    config: Dict[str, Any]  # ReplaySourceConfig as dict
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "source_path": self.source_path,
            "source_metadata": self.source_metadata,
            "timestamp_policy": self.timestamp_policy,
            "config": self.config,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplaySourceManifest":
        return cls(
            camera_id=data["camera_id"],
            source_path=data["source_path"],
            source_metadata=data["source_metadata"],
            timestamp_policy=data["timestamp_policy"],
            config=data["config"],
        )


@dataclass
class ReplayManifest:
    """
    Complete manifest for a replay session.
    
    Contains all information needed to reproduce the replay:
    - replay_id: Unique identifier
    - sources: List of source manifests
    - scheduler_config: Scheduler configuration
    - pipeline_config: Pipeline configuration (Phase 15-19 contracts)
    - version_info: Software/model versions
    - created_at: Creation timestamp
    """
    replay_id: str
    sources: List[ReplaySourceManifest]
    scheduler_config: Dict[str, Any]
    pipeline_config: Dict[str, Any]
    version_info: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        if not self.replay_id:
            # Generate deterministic ID from content
            content = json.dumps(self.to_dict(), sort_keys=True)
            self.replay_id = f"replay_{hashlib.md5(content.encode()).hexdigest()[:12]}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "sources": [s.to_dict() for s in self.sources],
            "scheduler_config": self.scheduler_config,
            "pipeline_config": self.pipeline_config,
            "version_info": self.version_info,
            "created_at": self.created_at,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def save(self, path: str) -> None:
        """Save manifest to file."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplayManifest":
        return cls(
            replay_id=data["replay_id"],
            sources=[ReplaySourceManifest.from_dict(s) for s in data["sources"]],
            scheduler_config=data["scheduler_config"],
            pipeline_config=data["pipeline_config"],
            version_info=data["version_info"],
            created_at=data["created_at"],
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> "ReplayManifest":
        return cls.from_dict(json.loads(json_str))
    
    @classmethod
    def load(cls, path: str) -> "ReplayManifest":
        """Load manifest from file."""
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_json(f.read())
    
    @classmethod
    def create(
        cls,
        sources: List[ReplaySourceConfig],
        scheduler_config: Dict[str, Any],
        pipeline_config: Dict[str, Any],
        version_info: Optional[Dict[str, Any]] = None,
    ) -> "ReplayManifest":
        """
        Create a manifest from source configs and pipeline config.
        
        Args:
            sources: List of ReplaySourceConfig objects.
            scheduler_config: Scheduler configuration dict.
            pipeline_config: Pipeline configuration dict (Phase 15-19).
            version_info: Optional version information.
            
        Returns:
            ReplayManifest with source metadata populated.
        """
        source_manifests = []
        
        for config in sources:
            # Open source to get metadata
            from app.replay.source import ReplaySource
            source = ReplaySource(config)
            try:
                info = source.open()
                source_metadata = {
                    "width": info.width,
                    "height": info.height,
                    "fps": info.fps,
                    "frame_count": info.frame_count,
                    "duration_seconds": info.duration_seconds,
                    "codec": info.codec,
                }
            finally:
                source.close()
            
            source_manifests.append(ReplaySourceManifest(
                camera_id=config.camera_id,
                source_path=config.source_path,
                source_metadata=source_metadata,
                timestamp_policy="pts" if config.use_pts else "frame_index_fps",
                config=config.to_dict(),
            ))
        
        if version_info is None:
            version_info = {
                "phase": "20",
                "python_version": "3.12",
            }
        
        return cls(
            replay_id="",  # Will be generated in __post_init__
            sources=source_manifests,
            scheduler_config=scheduler_config,
            pipeline_config=pipeline_config,
            version_info=version_info,
        )