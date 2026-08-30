"""
Phase 13 — ArcFace Enrollment Database Contract.

Defines the contract for offline face enrollment from IMAGE and VIDEO sources.
This module does NOT perform inference.
This module does NOT access cameras.
This module does NOT implement identity matching.
This module does NOT implement 1K3D68.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import numpy as np


class SourceType(Enum):
    """Enumeration of supported enrollment source types."""
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


@dataclass(frozen=True)
class EnrollmentInputContract:
    """
    Enrollment input contract - explicit and deterministic.
    
    Input:
        person_id: Unique identifier for the person being enrolled
        source_type: Source type (IMAGE or VIDEO)
        source: Source identifier (file path, URL, etc.)
        frame_index: Frame index for video sources (None for images)
        timestamp: Timestamp when available (ISO 8601 format)
    """
    person_id: str
    source_type: SourceType
    source: str
    frame_index: Optional[int] = None
    timestamp: Optional[str] = None
    
    def __post_init__(self):
        """Validate input contract after initialization."""
        if not self.person_id or not self.person_id.strip():
            raise ValueError("person_id must be non-empty string")
        
        if not isinstance(self.source_type, SourceType):
            raise ValueError(f"source_type must be SourceType enum, got {type(self.source_type)}")
        
        if not self.source or not self.source.strip():
            raise ValueError("source must be non-empty string")
        
        if self.source_type == SourceType.VIDEO and self.frame_index is None:
            raise ValueError("frame_index is required for VIDEO source type")
        
        if self.source_type == SourceType.IMAGE and self.frame_index is not None:
            raise ValueError("frame_index must be None for IMAGE source type")
        
        if self.timestamp is not None:
            # Validate ISO 8601 format
            try:
                datetime.fromisoformat(self.timestamp.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError(f"timestamp must be ISO 8601 format, got {self.timestamp}")


@dataclass(frozen=True)
class FaceDetectionProvenance:
    """Provenance information from face detection step."""
    detector_model: str
    detector_model_sha256: str
    detection_confidence: float
    bbox: List[float]  # [x1, y1, x2, y2] in original image coordinates
    landmarks: Optional[List[List[float]]] = None  # 5-point landmarks if available
    detection_time_ms: float = 0.0


@dataclass(frozen=True)
class PreprocessingProvenance:
    """Provenance information from preprocessing/alignment step."""
    crop_method: str
    alignment_method: str
    aligned_size: tuple = (112, 112)
    interpolation: str = "INTER_LINEAR"
    preprocessing_time_ms: float = 0.0


@dataclass(frozen=True)
class ArcFaceModelProvenance:
    """Provenance information from ArcFace model."""
    model_id: str = "arcface"
    model_filename: str = "glintr100.onnx"
    model_sha256: str = ""
    embedding_dimension: int = 512
    normalization_method: str = "L2"
    inference_time_ms: float = 0.0
    provider: str = "CPUExecutionProvider"


@dataclass(frozen=True)
class EnrollmentSampleProvenance:
    """
    Complete provenance for an accepted enrollment sample.
    
    Required provenance fields per Phase 13 specification:
    - person_id
    - source_type
    - source identifier
    - frame_index for video when applicable
    - timestamp when available
    - face detection provenance
    - preprocessing contract
    - ArcFace model identity
    - model SHA256
    - embedding dimension
    - normalization method
    """
    # Source identification
    person_id: str
    source_type: SourceType
    source: str
    frame_index: Optional[int] = None
    timestamp: Optional[str] = None
    
    # Face detection provenance
    face_detection: Optional[FaceDetectionProvenance] = None
    
    # Preprocessing provenance
    preprocessing: Optional[PreprocessingProvenance] = None
    
    # ArcFace model provenance
    arcface_model: Optional[ArcFaceModelProvenance] = None
    
    # Quality and duplicate filtering
    quality_score: Optional[float] = None
    quality_passed: bool = True
    rejection_reason: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None  # sample_id of the original
    
    # Sample identification
    sample_id: str = ""
    
    def __post_init__(self):
        """Validate provenance after initialization."""
        if not self.person_id or not self.person_id.strip():
            raise ValueError("person_id must be non-empty string")
        
        if not isinstance(self.source_type, SourceType):
            raise ValueError(f"source_type must be SourceType enum, got {type(self.source_type)}")
        
        if not self.source or not self.source.strip():
            raise ValueError("source must be non-empty string")
        
        if self.source_type == SourceType.VIDEO and self.frame_index is None:
            raise ValueError("frame_index is required for VIDEO source type")
        
        if self.source_type == SourceType.IMAGE and self.frame_index is not None:
            raise ValueError("frame_index must be None for IMAGE source type")
        
        if not self.sample_id:
            raise ValueError("sample_id must be non-empty string")


@dataclass(frozen=True)
class EnrollmentSample:
    """
    An accepted enrollment sample with embedding and full provenance.
    
    Output contract:
    - embedding: 512D float32 L2-normalized vector
    - provenance: Complete provenance information
    """
    embedding: np.ndarray  # shape (512,), dtype float32, L2 normalized
    provenance: EnrollmentSampleProvenance
    
    def __post_init__(self):
        """Validate enrollment sample after initialization."""
        # Validate embedding
        if not isinstance(self.embedding, np.ndarray):
            raise ValueError("embedding must be numpy array")
        
        if self.embedding.shape != (512,):
            raise ValueError(f"embedding must have shape (512,), got {self.embedding.shape}")
        
        if self.embedding.dtype != np.float32:
            raise ValueError(f"embedding must be float32, got {self.embedding.dtype}")
        
        if not np.isfinite(self.embedding).all():
            raise ValueError("embedding contains non-finite values")
        
        # Validate L2 normalization (norm ≈ 1.0)
        norm = np.linalg.norm(self.embedding)
        if abs(norm - 1.0) > 1e-5:
            raise ValueError(f"embedding must be L2 normalized (norm ≈ 1.0), got norm={norm}")
        
        # Validate provenance
        if not isinstance(self.provenance, EnrollmentSampleProvenance):
            raise ValueError("provenance must be EnrollmentSampleProvenance")


@dataclass(frozen=True)
class EnrollmentResult:
    """
    Result of enrollment processing for a single source (image or video).
    
    Contains accepted samples and rejected samples with reasons.
    """
    person_id: str
    source_type: SourceType
    source: str
    accepted_samples: List[EnrollmentSample] = field(default_factory=list)
    rejected_samples: List[Dict[str, Any]] = field(default_factory=list)
    processing_time_ms: float = 0.0
    
    def get_accepted_count(self) -> int:
        """Get number of accepted samples."""
        return len(self.accepted_samples)
    
    def get_rejected_count(self) -> int:
        """Get number of rejected samples."""
        return len(self.rejected_samples)


@dataclass(frozen=True)
class EnrollmentDatabaseMetadata:
    """
    Metadata for the enrollment database (embeddings.npy.metadata.json).
    
    Required fields per Phase 13 specification:
    - schema_version
    - embedding_dimension = 512
    - dtype = float32
    - normalization = L2
    - model_id = arcface
    - model_filename = glintr100.onnx
    - model_sha256
    - enrollment_contract_version
    - embedding_count
    - person_ids
    - sample provenance
    - creation timestamp
    """
    schema_version: str = "1.0"
    embedding_dimension: int = 512
    dtype: str = "float32"
    normalization: str = "L2"
    model_id: str = "arcface"
    model_filename: str = "glintr100.onnx"
    model_sha256: str = ""
    enrollment_contract_version: str = "1.0"
    embedding_count: int = 0
    person_ids: List[str] = field(default_factory=list)
    sample_provenance: List[Dict[str, Any]] = field(default_factory=list)
    creation_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "embedding_dimension": self.embedding_dimension,
            "dtype": self.dtype,
            "normalization": self.normalization,
            "model_id": self.model_id,
            "model_filename": self.model_filename,
            "model_sha256": self.model_sha256,
            "enrollment_contract_version": self.enrollment_contract_version,
            "embedding_count": self.embedding_count,
            "person_ids": self.person_ids,
            "sample_provenance": self.sample_provenance,
            "creation_timestamp": self.creation_timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EnrollmentDatabaseMetadata:
        """Create from dictionary (JSON deserialization)."""
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            embedding_dimension=data.get("embedding_dimension", 512),
            dtype=data.get("dtype", "float32"),
            normalization=data.get("normalization", "L2"),
            model_id=data.get("model_id", "arcface"),
            model_filename=data.get("model_filename", "glintr100.onnx"),
            model_sha256=data.get("model_sha256", ""),
            enrollment_contract_version=data.get("enrollment_contract_version", "1.0"),
            embedding_count=data.get("embedding_count", 0),
            person_ids=data.get("person_ids", []),
            sample_provenance=data.get("sample_provenance", []),
            creation_timestamp=data.get("creation_timestamp", datetime.utcnow().isoformat() + "Z"),
        )
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """
        Validate metadata against contract.
        
        Returns:
            (is_valid, error_message)
        """
        if self.schema_version != "1.0":
            return False, f"Unsupported schema_version: {self.schema_version}"
        
        if self.embedding_dimension != 512:
            return False, f"embedding_dimension must be 512, got {self.embedding_dimension}"
        
        if self.dtype != "float32":
            return False, f"dtype must be float32, got {self.dtype}"
        
        if self.normalization != "L2":
            return False, f"normalization must be L2, got {self.normalization}"
        
        if self.model_id != "arcface":
            return False, f"model_id must be arcface, got {self.model_id}"
        
        if self.model_filename != "glintr100.onnx":
            return False, f"model_filename must be glintr100.onnx, got {self.model_filename}"
        
        if not self.model_sha256:
            return False, "model_sha256 must be non-empty"
        
        if self.embedding_count < 0:
            return False, f"embedding_count must be non-negative, got {self.embedding_count}"
        
        if not isinstance(self.person_ids, list):
            return False, "person_ids must be a list"
        
        if not isinstance(self.sample_provenance, list):
            return False, "sample_provenance must be a list"
        
        if len(self.sample_provenance) != self.embedding_count:
            return False, f"sample_provenance length ({len(self.sample_provenance)}) must match embedding_count ({self.embedding_count})"
        
        return True, None


# Global contract instances
ENROLLMENT_INPUT_CONTRACT = EnrollmentInputContract


def create_enrollment_input(
    person_id: str,
    source_type: SourceType,
    source: str,
    frame_index: Optional[int] = None,
    timestamp: Optional[str] = None,
) -> EnrollmentInputContract:
    """Factory function to create EnrollmentInputContract."""
    return EnrollmentInputContract(
        person_id=person_id,
        source_type=source_type,
        source=source,
        frame_index=frame_index,
        timestamp=timestamp,
    )


def validate_enrollment_database(
    embeddings: np.ndarray,
    metadata: EnrollmentDatabaseMetadata,
) -> tuple[bool, Optional[str]]:
    """
    Validate enrollment database (embeddings array + metadata) against contract.
    
    Returns:
        (is_valid, error_message)
    """
    # Validate embeddings array
    if not isinstance(embeddings, np.ndarray):
        return False, "embeddings must be numpy array"
    
    if embeddings.ndim != 2:
        return False, f"embeddings must be 2D array, got {embeddings.ndim}D"
    
    if embeddings.shape[1] != 512:
        return False, f"embeddings must have 512 columns, got {embeddings.shape[1]}"
    
    if embeddings.dtype != np.float32:
        return False, f"embeddings must be float32, got {embeddings.dtype}"
    
    if not np.isfinite(embeddings).all():
        return False, "embeddings contains non-finite values"
    
    # Validate L2 normalization for all embeddings
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-5):
        return False, f"embeddings must be L2 normalized, norms range: [{norms.min():.6f}, {norms.max():.6f}]"
    
    # Validate metadata
    is_valid, error = metadata.validate()
    if not is_valid:
        return False, f"Metadata validation failed: {error}"
    
    # Cross-validate embeddings count
    if embeddings.shape[0] != metadata.embedding_count:
        return False, f"embeddings count ({embeddings.shape[0]}) != metadata.embedding_count ({metadata.embedding_count})"
    
    return True, None