"""
Global Identity Service Data Models.

Defines the core data structures for global identity management.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from fractions import Fraction
from typing import Any, Dict, List, Optional
import numpy as np


class IdentityState(str, Enum):
    """Global identity lifecycle state."""
    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    REACQUIRED = "reacquired"
    TEMPORARILY_LOST = "temporarily_lost"
    EXPIRED = "expired"


class ConflictType(str, Enum):
    """Types of identity conflicts."""
    FACE_BODY_MISMATCH = "face_body_mismatch"
    MULTI_CANDIDATE = "multi_candidate"
    CROSS_CAMERA_MISMATCH = "cross_camera_mismatch"


class ConflictResolution(str, Enum):
    """Conflict resolution options."""
    ACCEPT_FACE = "accept_face"
    ACCEPT_BODY = "accept_body"
    MANUAL_ID = "manual_id"
    PENDING = "pending"


class EvidenceType(str, Enum):
    """Type of identity evidence."""
    FACE_EMBEDDING = "face_embedding"
    BODY_EMBEDDING = "body_embedding"


@dataclass
class GlobalPersonID:
    """Canonical global person identity."""
    person_id: str  # e.g., "PERSON_001"
    created_at: float
    updated_at: float
    state: IdentityState = IdentityState.CANDIDATE
    face_embedding: Optional[np.ndarray] = None  # Aggregate face embedding
    body_embedding: Optional[np.ndarray] = None  # Aggregate body embedding
    evidence_score: float = 0.0
    camera_count: int = 0
    conflict_count: int = 0
    camera_tracks: Dict[str, List[TrackRef]] = field(default_factory=dict)  # camera_id -> [TrackRef]


@dataclass
class TrackRef:
    """Reference to a camera-local track."""
    camera_id: str
    local_track_id: str
    global_person_id: str
    identity_state: IdentityState
    face_similarity: float
    body_similarity: float
    assigned_at: float
    updated_at: float


@dataclass
class IdentityConflict:
    """Identity conflict record."""
    conflict_id: str
    person_id_1: str
    person_id_2: str
    conflict_type: ConflictType
    face_similarity: float
    body_similarity: float
    detected_at: float
    resolved_at: Optional[float] = None
    resolution: Optional[ConflictResolution] = ConflictResolution.PENDING
    resolved_by: Optional[str] = None


@dataclass
class IdentityEvidence:
    """Single piece of identity evidence (embedding)."""
    evidence_id: str
    global_person_id: str
    camera_id: str
    local_track_id: str
    evidence_type: EvidenceType
    embedding: np.ndarray
    quality_score: float
    timestamp: float
    frame_index: int
    model_id: str
    model_sha256: str
    detection_provenance: Optional[Dict[str, Any]] = None
    alignment_provenance: Optional[Dict[str, Any]] = None


@dataclass
class FaceMatchResult:
    """Result of face matching."""
    person_id: str
    similarity: float
    confidence: float


@dataclass
class BodyMatchResult:
    """Result of body matching."""
    person_id: str
    similarity: float
    confidence: float


@dataclass
class FusionResult:
    """Result of face+body fusion."""
    fused_score: float
    face_score: float
    body_score: float
    conflict_flag: bool
    conflict_type: Optional[ConflictType] = None
    resolution_hint: Optional[ConflictResolution] = None


def generate_global_person_id() -> str:
    """Generate a new global person ID."""
    import time
    content = f"PERSON_{int(time.time() * 1000)}:{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
    return f"PERSON_{hashlib.sha256(content.encode()).hexdigest()[:8].upper()}"


def generate_conflict_id() -> str:
    """Generate a conflict ID."""
    import time
    content = f"CONFLICT_{time.time()}:{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
    return f"CONF_{hashlib.sha256(content.encode()).hexdigest()[:8].upper()}"


def generate_evidence_id() -> str:
    """Generate an evidence ID."""
    import time
    content = f"EVID_{time.time()}:{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
    return f"EVID_{hashlib.sha256(content.encode()).hexdigest()[:8].upper()}"


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two L2-normalized vectors."""
    return float(np.dot(a, b))


def weighted_fusion(face_score: float, body_score: float, face_weight: float = 0.7, body_weight: float = 0.3) -> float:
    """Compute weighted fusion of face and body scores."""
    total_weight = face_weight + body_weight
    return (face_score * face_weight + body_score * body_weight) / total_weight


def detect_conflict(face_score: float, body_score: float, threshold: float = 0.3) -> Optional[ConflictType]:
    """Detect if face and body evidence disagree significantly."""
    if abs(face_score - body_score) > threshold:
        if face_score > body_score:
            return ConflictType.FACE_BODY_MISMATCH
        else:
            return ConflictType.FACE_BODY_MISMATCH
    return None


@dataclass
class GISConfig:
    """Global Identity Service configuration."""
    # Face matching thresholds
    face_match_threshold: float = 0.6
    face_match_high_confidence: float = 0.75
    
    # Body matching thresholds
    body_match_threshold: float = 0.5
    body_match_high_confidence: float = 0.65
    
    # Fusion weights
    face_weight: float = 0.7
    body_weight: float = 0.3
    
    # Conflict detection
    conflict_threshold: float = 0.3
    
    # Lifecycle thresholds
    candidate_min_evidence: int = 1
    provisional_min_evidence: int = 3
    provisional_min_duration_seconds: float = 5.0
    confirmed_min_evidence: int = 10
    confirmed_min_duration_seconds: float = 30.0
    
    # Reacquisition
    reacquisition_max_gap_seconds: float = 60.0
    reacquisition_similarity_threshold: float = 0.6
    
    # Evidence retention
    max_evidence_per_person: int = 100
    evidence_ttl_days: float = 30.0
    
    # Cross-camera
    cross_camera_enabled: bool = True
    cross_camera_time_window_seconds: float = 300.0  # 5 minutes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "face_match_threshold": self.face_match_threshold,
            "face_match_high_confidence": self.face_match_high_confidence,
            "body_match_threshold": self.body_match_threshold,
            "body_match_high_confidence": self.body_match_high_confidence,
            "face_weight": self.face_weight,
            "body_weight": self.body_weight,
            "conflict_threshold": self.conflict_threshold,
            "candidate_min_evidence": self.candidate_min_evidence,
            "provisional_min_evidence": self.provisional_min_evidence,
            "provisional_min_duration_seconds": self.provisional_min_duration_seconds,
            "confirmed_min_evidence": self.confirmed_min_evidence,
            "confirmed_min_duration_seconds": self.confirmed_min_duration_seconds,
            "reacquisition_max_gap_seconds": self.reacquisition_max_gap_seconds,
            "reacquisition_similarity_threshold": self.reacquisition_similarity_threshold,
            "max_evidence_per_person": self.max_evidence_per_person,
            "evidence_ttl_days": self.evidence_ttl_days,
            "cross_camera_enabled": self.cross_camera_enabled,
            "cross_camera_time_window_seconds": self.cross_camera_time_window_seconds,
        }


def load_gis_config() -> GISConfig:
    """Load GIS configuration from environment/settings."""
    # For now, return defaults
    # In production, load from settings file or environment
    return GISConfig()