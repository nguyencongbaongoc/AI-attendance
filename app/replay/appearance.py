"""
Phase 27 — Person Appearance / Video Evidence Retrieval.

Provides appearance indexing and video segment retrieval for forensic audit.
Built on provenance from Phases 20-26.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class AppearanceRecord:
    """
    Appearance/evidence reference for a person's presence in video.
    
    Does NOT create a new identity database - uses existing identity references.
    UNKNOWN observations remain searchable by observation/track reference.
    """
    # Unique appearance identifier
    appearance_id: str
    
    # Person identity (when known)
    person_id: Optional[str] = None
    identity_certainty: str = "unknown"  # "known", "unknown", "ambiguous", "insufficient"
    
    # Camera and track provenance
    camera_id: str = ""
    local_track_id: str = ""
    global_observation_id: Optional[str] = None
    
    # Source video reference
    source_video_id: str = ""
    
    # Temporal bounds
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0
    start_frame: int = 0
    end_frame: int = 0
    
    # Source references (provenance chain)
    source_resolution_id: Optional[str] = None
    attendance_decision_id: Optional[str] = None
    
    # Provenance
    provenance: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    
    def __post_init__(self):
        if not self.appearance_id:
            raise ValueError("appearance_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if not self.local_track_id:
            raise ValueError("local_track_id is required")
        if not self.source_video_id:
            raise ValueError("source_video_id is required")
        if self.start_timestamp < 0 or self.end_timestamp < 0:
            raise ValueError("timestamps must be >= 0")
        if self.end_timestamp < self.start_timestamp:
            raise ValueError("end_timestamp must be >= start_timestamp")
        if self.start_frame < 0 or self.end_frame < 0:
            raise ValueError("frame indices must be >= 0")
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
    
    @property
    def duration_seconds(self) -> float:
        """Duration of appearance in seconds."""
        return self.end_timestamp - self.start_timestamp
    
    @property
    def frame_count(self) -> int:
        """Number of frames in appearance."""
        return self.end_frame - self.start_frame + 1
    
    @property
    def has_known_identity(self) -> bool:
        """Whether this appearance has a known person identity."""
        return self.person_id is not None and self.identity_certainty == "known"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "appearance_id": self.appearance_id,
            "person_id": self.person_id,
            "identity_certainty": self.identity_certainty,
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "global_observation_id": self.global_observation_id,
            "source_video_id": self.source_video_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "source_resolution_id": self.source_resolution_id,
            "attendance_decision_id": self.attendance_decision_id,
            "provenance": self.provenance,
            "schema_version": self.schema_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppearanceRecord":
        return cls(
            appearance_id=data["appearance_id"],
            person_id=data.get("person_id"),
            identity_certainty=data.get("identity_certainty", "unknown"),
            camera_id=data["camera_id"],
            local_track_id=data["local_track_id"],
            global_observation_id=data.get("global_observation_id"),
            source_video_id=data["source_video_id"],
            start_timestamp=data["start_timestamp"],
            end_timestamp=data["end_timestamp"],
            start_frame=data["start_frame"],
            end_frame=data["end_frame"],
            source_resolution_id=data.get("source_resolution_id"),
            attendance_decision_id=data.get("attendance_decision_id"),
            provenance=data.get("provenance", {}),
            schema_version=data.get("schema_version", "1.0"),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "AppearanceRecord":
        return cls.from_dict(json.loads(json_str))


@dataclass(frozen=True)
class VideoSegmentRequest:
    """
    Request for video segment extraction.
    
    Uses source references - does NOT store video in database.
    """
    source_video_id: str
    camera_id: str
    start_timestamp: float
    end_timestamp: float
    start_frame: int
    end_frame: int
    pre_roll_seconds: float = 0.0
    post_roll_seconds: float = 0.0
    output_format: str = "mp4"
    
    def __post_init__(self):
        if not self.source_video_id:
            raise ValueError("source_video_id is required")
        if not self.camera_id:
            raise ValueError("camera_id is required")
        if self.start_timestamp < 0 or self.end_timestamp < 0:
            raise ValueError("timestamps must be >= 0")
        if self.end_timestamp <= self.start_timestamp:
            raise ValueError("end_timestamp must be > start_timestamp")
        if self.start_frame < 0 or self.end_frame < 0:
            raise ValueError("frame indices must be >= 0")
        if self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame")
        if self.pre_roll_seconds < 0 or self.post_roll_seconds < 0:
            raise ValueError("pre_roll_seconds and post_roll_seconds must be >= 0")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_video_id": self.source_video_id,
            "camera_id": self.camera_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "pre_roll_seconds": self.pre_roll_seconds,
            "post_roll_seconds": self.post_roll_seconds,
            "output_format": self.output_format,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoSegmentRequest":
        return cls(
            source_video_id=data["source_video_id"],
            camera_id=data["camera_id"],
            start_timestamp=data["start_timestamp"],
            end_timestamp=data["end_timestamp"],
            start_frame=data["start_frame"],
            end_frame=data["end_frame"],
            pre_roll_seconds=data.get("pre_roll_seconds", 0.0),
            post_roll_seconds=data.get("post_roll_seconds", 0.0),
            output_format=data.get("output_format", "mp4"),
        )


@dataclass(frozen=True)
class VideoSegmentResult:
    """
    Result of video segment extraction.
    
    Preserves reference to source - clip is evidence derived from source.
    """
    # Output file path
    output_path: str
    
    # Source reference
    source_video_id: str
    camera_id: str
    source_start_timestamp: float
    source_end_timestamp: float
    source_start_frame: int
    source_end_frame: int
    
    # Extraction configuration
    pre_roll_seconds: float
    post_roll_seconds: float
    output_format: str
    
    # Actual extracted bounds (may differ from request due to clamping)
    actual_start_timestamp: float
    actual_end_timestamp: float
    actual_start_frame: int
    actual_end_frame: int
    
    # Provenance
    extraction_config: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_path": self.output_path,
            "source_video_id": self.source_video_id,
            "camera_id": self.camera_id,
            "source_start_timestamp": self.source_start_timestamp,
            "source_end_timestamp": self.source_end_timestamp,
            "source_start_frame": self.source_start_frame,
            "source_end_frame": self.source_end_frame,
            "pre_roll_seconds": self.pre_roll_seconds,
            "post_roll_seconds": self.post_roll_seconds,
            "output_format": self.output_format,
            "actual_start_timestamp": self.actual_start_timestamp,
            "actual_end_timestamp": self.actual_end_timestamp,
            "actual_start_frame": self.actual_start_frame,
            "actual_end_frame": self.actual_end_frame,
            "extraction_config": self.extraction_config,
            "provenance": self.provenance,
            "schema_version": self.schema_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoSegmentResult":
        return cls(
            output_path=data["output_path"],
            source_video_id=data["source_video_id"],
            camera_id=data["camera_id"],
            source_start_timestamp=data["source_start_timestamp"],
            source_end_timestamp=data["source_end_timestamp"],
            source_start_frame=data["source_start_frame"],
            source_end_frame=data["source_end_frame"],
            pre_roll_seconds=data["pre_roll_seconds"],
            post_roll_seconds=data["post_roll_seconds"],
            output_format=data["output_format"],
            actual_start_timestamp=data["actual_start_timestamp"],
            actual_end_timestamp=data["actual_end_timestamp"],
            actual_start_frame=data["actual_start_frame"],
            actual_end_frame=data["actual_end_frame"],
            extraction_config=data.get("extraction_config", {}),
            provenance=data.get("provenance", {}),
            schema_version=data.get("schema_version", "1.0"),
        )


@dataclass(frozen=True)
class PersonSearchResult:
    """
    Result of person appearance search.
    
    Returns all matching appearances with camera/time/track references.
    """
    person_id: str
    appearances: Tuple[AppearanceRecord, ...] = ()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "person_id": self.person_id,
            "appearances": [a.to_dict() for a in self.appearances],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonSearchResult":
        return cls(
            person_id=data["person_id"],
            appearances=tuple(AppearanceRecord.from_dict(a) for a in data.get("appearances", [])),
        )


def generate_appearance_id(
    source_video_id: str,
    camera_id: str,
    local_track_id: str,
    start_timestamp: float,
    schema_version: str = "1.0",
) -> str:
    """Generate deterministic appearance ID."""
    content = f"APP:{source_video_id}:{camera_id}:{local_track_id}:{start_timestamp}:v{schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"APP-{hash_suffix}"


def generate_video_segment_id(
    source_video_id: str,
    camera_id: str,
    start_timestamp: float,
    end_timestamp: float,
    schema_version: str = "1.0",
) -> str:
    """Generate deterministic video segment ID."""
    content = f"VID:{source_video_id}:{camera_id}:{start_timestamp}:{end_timestamp}:v{schema_version}"
    hash_suffix = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"VID-{hash_suffix}"