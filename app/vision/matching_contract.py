"""
Phase 14 — ArcFace Identity Matching Contract.

Defines the contract for offline identity matching against a Phase 13 enrollment database.
This module does NOT perform detection, tracking, attendance, or hard-pose correction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import numpy as np


class MatchStatus(Enum):
    """Identity match status."""
    MATCH = "MATCH"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class QueryEmbeddingContract:
    """
    Query embedding contract - explicit and deterministic.
    
    Input:
        embedding: 512D float32 L2-normalized query embedding
        provenance: Optional provenance information for the query
    """
    embedding: np.ndarray  # shape (512,), dtype float32, L2 normalized
    provenance: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        """Validate query embedding contract after initialization."""
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
        if abs(norm - 1.0) > 1e-4:
            raise ValueError(f"embedding must be L2 normalized (norm ≈ 1.0), got norm={norm}")


@dataclass(frozen=True)
class CandidateMatch:
    """
    A single candidate match from the database.
    
    Represents one enrollment sample's similarity to the query.
    """
    sample_id: str
    person_id: str
    similarity: float
    sample_provenance: Dict[str, Any]


@dataclass(frozen=True)
class PersonLevelMatch:
    """
    Person-level match aggregation.
    
    Aggregates multiple sample-level matches for the same person.
    """
    person_id: str
    best_sample_id: str
    best_similarity: float
    sample_count: int
    all_similarities: List[float]


@dataclass(frozen=True)
class IdentityMatchResult:
    """
    Result of identity matching.
    
    Required fields per Phase 14 specification:
    - status: MATCH, UNKNOWN, or AMBIGUOUS
    - person_id: Matched person ID (null for UNKNOWN)
    - similarity: Best similarity score
    - matched_sample_id: Sample ID of the best match (null for UNKNOWN)
    - candidate_count: Number of candidates evaluated
    - threshold: Match threshold used
    - ambiguity_margin: Ambiguity margin used
    - database_schema_version: Schema version of the database
    - model_identity: Model identity (arcface/glintr100.onnx)
    - provenance: Complete provenance information
    """
    status: MatchStatus
    person_id: Optional[str]
    similarity: float
    matched_sample_id: Optional[str]
    candidate_count: int
    threshold: float
    ambiguity_margin: float
    database_schema_version: str
    model_identity: str
    provenance: Dict[str, Any]
    
    def __post_init__(self):
        """Validate match result after initialization."""
        if not isinstance(self.status, MatchStatus):
            raise ValueError(f"status must be MatchStatus enum, got {type(self.status)}")
        
        if self.status == MatchStatus.UNKNOWN:
            if self.person_id is not None:
                raise ValueError("person_id must be None for UNKNOWN status")
            if self.matched_sample_id is not None:
                raise ValueError("matched_sample_id must be None for UNKNOWN status")
        
        if self.status == MatchStatus.MATCH:
            if self.person_id is None:
                raise ValueError("person_id must be non-None for MATCH status")
            if self.matched_sample_id is None:
                raise ValueError("matched_sample_id must be non-None for MATCH status")
        
        if self.status == MatchStatus.AMBIGUOUS:
            if self.person_id is not None:
                raise ValueError("person_id must be None for AMBIGUOUS status")
            if self.matched_sample_id is not None:
                raise ValueError("matched_sample_id must be None for AMBIGUOUS status")
        
        if not (0.0 <= self.similarity <= 1.0):
            raise ValueError(f"similarity must be in [0, 1], got {self.similarity}")
        
        if self.candidate_count < 0:
            raise ValueError(f"candidate_count must be non-negative, got {self.candidate_count}")
        
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError(f"threshold must be in [0, 1], got {self.threshold}")
        
        if not (0.0 <= self.ambiguity_margin <= 1.0):
            raise ValueError(f"ambiguity_margin must be in [0, 1], got {self.ambiguity_margin}")


@dataclass(frozen=True)
class MatchingConfig:
    """
    Configuration for identity matching.
    
    Required fields per Phase 14 specification:
    - match_threshold: Minimum similarity for MATCH (default 0.5)
    - ambiguity_margin: Maximum difference between best and second-best for MATCH (default 0.05)
    - person_aggregation_policy: How to aggregate multiple samples per person (default "best_sample")
    """
    match_threshold: float = 0.5
    ambiguity_margin: float = 0.05
    person_aggregation_policy: str = "best_sample"  # "best_sample" or "average"
    
    def __post_init__(self):
        """Validate matching config after initialization."""
        if not (0.0 <= self.match_threshold <= 1.0):
            raise ValueError(f"match_threshold must be in [0, 1], got {self.match_threshold}")
        
        if not (0.0 <= self.ambiguity_margin <= 1.0):
            raise ValueError(f"ambiguity_margin must be in [0, 1], got {self.ambiguity_margin}")
        
        if self.person_aggregation_policy not in ("best_sample", "average"):
            raise ValueError(f"person_aggregation_policy must be 'best_sample' or 'average', got {self.person_aggregation_policy}")


def validate_query_embedding(embedding: np.ndarray) -> tuple[bool, Optional[str]]:
    """
    Validate query embedding against contract.
    
    Returns:
        (is_valid, error_message)
    """
    if not isinstance(embedding, np.ndarray):
        return False, "embedding must be numpy array"
    
    if embedding.shape != (512,):
        return False, f"embedding must have shape (512,), got {embedding.shape}"
    
    if embedding.dtype != np.float32:
        return False, f"embedding must be float32, got {embedding.dtype}"
    
    if not np.isfinite(embedding).all():
        return False, "embedding contains non-finite values"
    
    # Check non-zero norm
    norm = np.linalg.norm(embedding)
    if norm < 1e-6:
        return False, f"embedding norm too small: {norm}"
    
    # Check L2 normalization (within tolerance)
    if abs(norm - 1.0) > 1e-4:
        return False, f"embedding must be L2 normalized (norm ≈ 1.0), got norm={norm}"
    
    return True, None


def validate_database_for_matching(
    embeddings: np.ndarray,
    metadata: Any,  # EnrollmentDatabaseMetadata
) -> tuple[bool, Optional[str]]:
    """
    Validate enrollment database for matching.
    
    Reuses Phase 13 database validation logic.
    
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
    if hasattr(metadata, 'validate'):
        is_valid, error = metadata.validate()
        if not is_valid:
            return False, f"Metadata validation failed: {error}"
    
    # Cross-validate embeddings count
    if hasattr(metadata, 'embedding_count'):
        if embeddings.shape[0] != metadata.embedding_count:
            return False, f"embeddings count ({embeddings.shape[0]}) != metadata.embedding_count ({metadata.embedding_count})"
    
    # Check model identity
    if hasattr(metadata, 'model_id'):
        if metadata.model_id != "arcface":
            return False, f"model_id must be arcface, got {metadata.model_id}"
    
    if hasattr(metadata, 'model_filename'):
        if metadata.model_filename != "glintr100.onnx":
            return False, f"model_filename must be glintr100.onnx, got {metadata.model_filename}"
    
    return True, None


def compute_cosine_similarity(query: np.ndarray, database: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between query and database embeddings.
    
    Since both are L2-normalized: cosine_similarity = dot(query, database_embedding)
    
    Args:
        query: Query embedding, shape (512,)
        database: Database embeddings, shape (N, 512)
        
    Returns:
        Similarities array, shape (N,)
    """
    # Validate inputs
    if query.shape != (512,):
        raise ValueError(f"query must have shape (512,), got {query.shape}")
    
    if database.ndim != 2 or database.shape[1] != 512:
        raise ValueError(f"database must have shape (N, 512), got {database.shape}")
    
    # Cosine similarity = dot product (both L2 normalized)
    similarities = database @ query
    
    # Validate output
    if not np.isfinite(similarities).all():
        raise ValueError("similarities contain non-finite values")
    
    # Allow small numerical tolerance for floating point precision
    if not np.all((similarities >= -1.0 - 1e-6) & (similarities <= 1.0 + 1e-6)):
        raise ValueError("similarities outside expected range [-1, 1]")
    
    return similarities


# Global contract instances
QUERY_EMBEDDING_CONTRACT = QueryEmbeddingContract
MATCHING_CONFIG = MatchingConfig
IDENTITY_MATCH_RESULT = IdentityMatchResult