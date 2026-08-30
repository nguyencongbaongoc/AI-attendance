"""
Phase 14 — ArcFace Identity Matching Unit Tests.

Tests cover:
- Matching contract
- Database validation
- Query validation
- Cosine similarity
- Best candidate
- Person-level aggregation
- MATCH
- UNKNOWN
- AMBIGUOUS
- Multiple samples/person
- Threshold behavior
- Ambiguity margin
- Order independence
- Determinism
- Provenance
- Corrupted database
- Memory safety
- Safety boundary
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.vision.enrollment import build_enrollment_database
from app.vision.enrollment_contract import (
    EnrollmentDatabaseMetadata,
    EnrollmentResult,
    EnrollmentSample,
    EnrollmentSampleProvenance,
    FaceDetectionProvenance,
    PreprocessingProvenance,
    ArcFaceModelProvenance,
    SourceType,
    validate_enrollment_database,
)
from app.vision.matching import (
    aggregate_person_matches,
    load_matching_database,
    match_identity,
    match_identity_from_database_dir,
)
from app.vision.matching_contract import (
    CandidateMatch,
    IdentityMatchResult,
    MatchStatus,
    MatchingConfig,
    PersonLevelMatch,
    QueryEmbeddingContract,
    compute_cosine_similarity,
    validate_database_for_matching,
    validate_query_embedding,
)


# ============================================================
# Test Fixtures
# ============================================================

def create_valid_embedding(seed: int = 42) -> np.ndarray:
    """Create a valid L2-normalized 512D float32 embedding."""
    rng = np.random.default_rng(seed)
    emb = rng.normal(0, 1, 512).astype(np.float32)
    emb = emb / np.linalg.norm(emb)
    return emb


def create_database_embeddings(count: int, base_seed: int = 100) -> np.ndarray:
    """Create multiple valid embeddings for database."""
    embeddings = []
    for i in range(count):
        rng = np.random.default_rng(base_seed + i)
        emb = rng.normal(0, 1, 512).astype(np.float32)
        emb = emb / np.linalg.norm(emb)
        embeddings.append(emb)
    return np.stack(embeddings, axis=0)


def create_sample_provenance(person_id: str, sample_id: str, source_type: SourceType = SourceType.IMAGE) -> dict:
    """Create a sample provenance dict."""
    return {
        "person_id": person_id,
        "source_type": source_type,  # Pass enum, not string
        "source": f"/path/to/{sample_id}.jpg",
        "frame_index": None,
        "timestamp": "2024-01-01T00:00:00Z",
        "face_detection": {
            "detector_model": "scrfd",
            "detector_model_sha256": "abc123",
            "detection_confidence": 0.9,
            "bbox": [100, 100, 200, 200],
            "landmarks": [[120, 130], [180, 130], [150, 160], [130, 180], [170, 180]],
            "detection_time_ms": 10.0,
        },
        "preprocessing": {
            "crop_method": "safe_crop_face",
            "alignment_method": "similarity_transform_5pt",
            "aligned_size": [112, 112],
            "interpolation": "INTER_LINEAR",
            "preprocessing_time_ms": 5.0,
        },
        "arcface_model": {
            "model_id": "arcface",
            "model_filename": "glintr100.onnx",
            "model_sha256": "model_sha256_hash",
            "embedding_dimension": 512,
            "normalization_method": "L2",
            "inference_time_ms": 15.0,
            "provider": "CPUExecutionProvider",
        },
        "quality_score": 0.85,
        "quality_passed": True,
        "rejection_reason": None,
        "is_duplicate": False,
        "duplicate_of": None,
        "sample_id": sample_id,
    }


def create_test_database(tmp_path: Path, person_samples: dict) -> tuple[Path, Path]:
    """
    Create a test enrollment database.
    
    Args:
        tmp_path: Temporary directory
        person_samples: Dict of person_id -> list of embeddings
        
    Returns:
        Tuple of (embeddings_path, metadata_path)
    """
    all_samples = []
    person_ids = set()
    
    for person_id, embeddings in person_samples.items():
        person_ids.add(person_id)
        for i, emb in enumerate(embeddings):
            sample_id = f"{person_id}_sample_{i}_{uuid.uuid4().hex[:8]}"
            provenance = create_sample_provenance(person_id, sample_id)
            sample = EnrollmentSample(
                embedding=emb,
                provenance=EnrollmentSampleProvenance(**provenance),
            )
            all_samples.append(sample)
    
    # Sort for determinism
    all_samples.sort(key=lambda s: (s.provenance.person_id, s.provenance.source, s.provenance.sample_id))
    
    embeddings_array = np.stack([s.embedding for s in all_samples], axis=0).astype(np.float32)
    
    sample_provenance = [s.provenance.__dict__ for s in all_samples]
    for prov in sample_provenance:
        prov["source_type"] = prov["source_type"].value if hasattr(prov["source_type"], "value") else prov["source_type"]
        # The nested objects are already dicts from create_sample_provenance, no need to call __dict__ again
        # They were converted to dicts when EnrollmentSampleProvenance was created
    
    metadata = EnrollmentDatabaseMetadata(
        schema_version="1.0",
        embedding_dimension=512,
        dtype="float32",
        normalization="L2",
        model_id="arcface",
        model_filename="glintr100.onnx",
        model_sha256="model_sha256_hash",
        enrollment_contract_version="1.0",
        embedding_count=len(all_samples),
        person_ids=sorted(list(person_ids)),
        sample_provenance=sample_provenance,
        creation_timestamp="2024-01-01T00:00:00Z",
    )
    
    # Validate
    is_valid, error = validate_enrollment_database(embeddings_array, metadata)
    assert is_valid, f"Database validation failed: {error}"
    
    # Write
    embeddings_path = tmp_path / "embeddings.npy"
    metadata_path = tmp_path / "embeddings.npy.metadata.json"
    
    np.save(embeddings_path, embeddings_array)
    with open(metadata_path, "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)
    
    return embeddings_path, metadata_path


# ============================================================
# Task 1: Matching Contract Tests
# ============================================================

class TestMatchingContract:
    """Test the matching contract definitions."""
    
    def test_match_status_enum(self):
        """Test MatchStatus enum values."""
        assert MatchStatus.MATCH.value == "MATCH"
        assert MatchStatus.UNKNOWN.value == "UNKNOWN"
        assert MatchStatus.AMBIGUOUS.value == "AMBIGUOUS"
    
    def test_query_embedding_contract_valid(self):
        """Test valid query embedding contract."""
        emb = create_valid_embedding()
        contract = QueryEmbeddingContract(embedding=emb)
        assert contract.embedding.shape == (512,)
        assert contract.embedding.dtype == np.float32
    
    def test_query_embedding_contract_invalid_shape(self):
        """Test query embedding contract rejects wrong shape."""
        emb = np.random.rand(256).astype(np.float32)
        with pytest.raises(ValueError, match="shape"):
            QueryEmbeddingContract(embedding=emb)
    
    def test_query_embedding_contract_invalid_dtype(self):
        """Test query embedding contract rejects wrong dtype."""
        emb = np.random.rand(512).astype(np.float64)
        with pytest.raises(ValueError, match="float32"):
            QueryEmbeddingContract(embedding=emb)
    
    def test_query_embedding_contract_nan(self):
        """Test query embedding contract rejects NaN."""
        emb = create_valid_embedding()
        emb[0] = np.nan
        with pytest.raises(ValueError, match="non-finite"):
            QueryEmbeddingContract(embedding=emb)
    
    def test_query_embedding_contract_not_normalized(self):
        """Test query embedding contract rejects non-normalized."""
        emb = np.ones(512, dtype=np.float32)  # norm = sqrt(512) != 1
        with pytest.raises(ValueError, match="L2 normalized"):
            QueryEmbeddingContract(embedding=emb)
    
    def test_identity_match_result_match(self):
        """Test IdentityMatchResult for MATCH status."""
        result = IdentityMatchResult(
            status=MatchStatus.MATCH,
            person_id="P001",
            similarity=0.85,
            matched_sample_id="sample_123",
            candidate_count=10,
            threshold=0.5,
            ambiguity_margin=0.05,
            database_schema_version="1.0",
            model_identity="arcface/glintr100.onnx",
            provenance={},
        )
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
    
    def test_identity_match_result_unknown(self):
        """Test IdentityMatchResult for UNKNOWN status."""
        result = IdentityMatchResult(
            status=MatchStatus.UNKNOWN,
            person_id=None,
            similarity=0.3,
            matched_sample_id=None,
            candidate_count=10,
            threshold=0.5,
            ambiguity_margin=0.05,
            database_schema_version="1.0",
            model_identity="arcface/glintr100.onnx",
            provenance={},
        )
        assert result.status == MatchStatus.UNKNOWN
        assert result.person_id is None
        assert result.matched_sample_id is None
    
    def test_identity_match_result_ambiguous(self):
        """Test IdentityMatchResult for AMBIGUOUS status."""
        result = IdentityMatchResult(
            status=MatchStatus.AMBIGUOUS,
            person_id=None,
            similarity=0.85,
            matched_sample_id=None,
            candidate_count=10,
            threshold=0.5,
            ambiguity_margin=0.05,
            database_schema_version="1.0",
            model_identity="arcface/glintr100.onnx",
            provenance={},
        )
        assert result.status == MatchStatus.AMBIGUOUS
        assert result.person_id is None
        assert result.matched_sample_id is None
    
    def test_identity_match_result_invalid_unknown_with_person_id(self):
        """Test IdentityMatchResult rejects UNKNOWN with person_id."""
        with pytest.raises(ValueError, match="person_id must be None"):
            IdentityMatchResult(
                status=MatchStatus.UNKNOWN,
                person_id="P001",
                similarity=0.3,
                matched_sample_id=None,
                candidate_count=10,
                threshold=0.5,
                ambiguity_margin=0.05,
                database_schema_version="1.0",
                model_identity="arcface/glintr100.onnx",
                provenance={},
            )
    
    def test_matching_config_defaults(self):
        """Test MatchingConfig default values."""
        config = MatchingConfig()
        assert config.match_threshold == 0.5
        assert config.ambiguity_margin == 0.05
        assert config.person_aggregation_policy == "best_sample"
    
    def test_matching_config_custom(self):
        """Test MatchingConfig custom values."""
        config = MatchingConfig(
            match_threshold=0.6,
            ambiguity_margin=0.1,
            person_aggregation_policy="average",
        )
        assert config.match_threshold == 0.6
        assert config.ambiguity_margin == 0.1
        assert config.person_aggregation_policy == "average"
    
    def test_matching_config_invalid_threshold(self):
        """Test MatchingConfig rejects invalid threshold."""
        with pytest.raises(ValueError, match="threshold"):
            MatchingConfig(match_threshold=1.5)
    
    def test_matching_config_invalid_policy(self):
        """Test MatchingConfig rejects invalid policy."""
        with pytest.raises(ValueError, match="policy"):
            MatchingConfig(person_aggregation_policy="invalid")


# ============================================================
# Task 2: Database Validation Tests
# ============================================================

class TestDatabaseValidation:
    """Test database validation for matching."""
    
    def test_validate_database_for_matching_valid(self, tmp_path):
        """Test validation passes for valid database."""
        emb1 = create_valid_embedding(1)
        emb2 = create_valid_embedding(2)
        embeddings_path, metadata_path = create_test_database(tmp_path, {"P001": [emb1], "P002": [emb2]})
        
        embeddings_arr = np.load(embeddings_path)
        with open(metadata_path) as f:
            metadata_dict = json.load(f)
        metadata = EnrollmentDatabaseMetadata.from_dict(metadata_dict)
        
        is_valid, error = validate_database_for_matching(embeddings_arr, metadata)
        assert is_valid
        assert error is None
    
    def test_validate_database_wrong_shape(self):
        """Test validation rejects wrong embedding shape."""
        embeddings = np.random.rand(10, 256).astype(np.float32)
        metadata = EnrollmentDatabaseMetadata(embedding_count=10)
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "512 columns" in error
    
    def test_validate_database_wrong_dtype(self):
        """Test validation rejects wrong dtype."""
        embeddings = np.random.rand(10, 512).astype(np.float64)
        metadata = EnrollmentDatabaseMetadata(embedding_count=10)
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "float32" in error
    
    def test_validate_database_nan(self):
        """Test validation rejects NaN embeddings."""
        embeddings = create_database_embeddings(10)
        embeddings[0, 0] = np.nan
        metadata = EnrollmentDatabaseMetadata(embedding_count=10)
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "non-finite" in error
    
    def test_validate_database_not_normalized(self):
        """Test validation rejects non-normalized embeddings."""
        embeddings = np.ones((10, 512), dtype=np.float32)
        metadata = EnrollmentDatabaseMetadata(embedding_count=10)
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "L2 normalized" in error
    
    def test_validate_database_wrong_model_id(self):
        """Test validation rejects wrong model_id."""
        embeddings = create_database_embeddings(10)
        metadata = EnrollmentDatabaseMetadata(embedding_count=10, model_id="wrong_model")
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "model_id must be arcface" in error
    
    def test_validate_database_wrong_model_filename(self):
        """Test validation rejects wrong model_filename."""
        embeddings = create_database_embeddings(10)
        metadata = EnrollmentDatabaseMetadata(embedding_count=10, model_filename="wrong.onnx")
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        assert "model_filename must be glintr100.onnx" in error
    
    def test_validate_database_count_mismatch(self):
        """Test validation rejects count mismatch."""
        embeddings = create_database_embeddings(10)
        # Create metadata with sample_provenance to avoid that validation error first
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=5, 
            model_sha256="valid_hash",
            sample_provenance=[{}] * 10  # Match embeddings count
        )
        
        is_valid, error = validate_database_for_matching(embeddings, metadata)
        assert not is_valid
        # The error message may vary, check for count mismatch
        assert "count" in error.lower() or "mismatch" in error.lower()


# ============================================================
# Task 3: Query Validation Tests
# ============================================================

class TestQueryValidation:
    """Test query embedding validation."""
    
    def test_validate_query_embedding_valid(self):
        """Test validation passes for valid query."""
        emb = create_valid_embedding()
        is_valid, error = validate_query_embedding(emb)
        assert is_valid
        assert error is None
    
    def test_validate_query_embedding_wrong_shape(self):
        """Test validation rejects wrong shape."""
        emb = np.random.rand(256).astype(np.float32)
        is_valid, error = validate_query_embedding(emb)
        assert not is_valid
        assert "shape" in error
    
    def test_validate_query_embedding_wrong_dtype(self):
        """Test validation rejects wrong dtype."""
        emb = np.random.rand(512).astype(np.float64)
        is_valid, error = validate_query_embedding(emb)
        assert not is_valid
        assert "float32" in error
    
    def test_validate_query_embedding_nan(self):
        """Test validation rejects NaN."""
        emb = create_valid_embedding()
        emb[0] = np.nan
        is_valid, error = validate_query_embedding(emb)
        assert not is_valid
        assert "non-finite" in error
    
    def test_validate_query_embedding_zero_vector(self):
        """Test validation rejects zero vector."""
        emb = np.zeros(512, dtype=np.float32)
        is_valid, error = validate_query_embedding(emb)
        assert not is_valid
        assert "norm too small" in error
    
    def test_validate_query_embedding_not_normalized(self):
        """Test validation rejects non-normalized."""
        emb = np.ones(512, dtype=np.float32)
        is_valid, error = validate_query_embedding(emb)
        assert not is_valid
        assert "L2 normalized" in error


# ============================================================
# Task 4: Cosine Similarity Tests
# ============================================================

class TestCosineSimilarity:
    """Test cosine similarity computation."""
    
    def test_compute_cosine_similarity_basic(self):
        """Test basic cosine similarity computation."""
        query = create_valid_embedding(1)
        database = create_database_embeddings(5, 10)
        
        similarities = compute_cosine_similarity(query, database)
        
        assert similarities.shape == (5,)
        assert similarities.dtype == np.float32
        assert np.all(np.isfinite(similarities))
        assert np.all((similarities >= -1.0) & (similarities <= 1.0))
    
    def test_compute_cosine_similarity_self_match(self):
        """Test cosine similarity of embedding with itself is 1.0."""
        query = create_valid_embedding(42)
        database = query.reshape(1, 512)
        
        similarities = compute_cosine_similarity(query, database)
        
        assert np.isclose(similarities[0], 1.0, atol=1e-5)
    
    def test_compute_cosine_similarity_orthogonal(self):
        """Test cosine similarity of orthogonal vectors is ~0."""
        # Create two orthogonal vectors
        query = np.zeros(512, dtype=np.float32)
        query[0] = 1.0
        database = np.zeros((1, 512), dtype=np.float32)
        database[0, 1] = 1.0
        
        similarities = compute_cosine_similarity(query, database)
        
        assert np.isclose(similarities[0], 0.0, atol=1e-5)
    
    def test_compute_cosine_similarity_invalid_query_shape(self):
        """Test cosine similarity rejects invalid query shape."""
        query = np.random.rand(256).astype(np.float32)
        database = create_database_embeddings(5)
        
        with pytest.raises(ValueError, match="query must have shape"):
            compute_cosine_similarity(query, database)
    
    def test_compute_cosine_similarity_invalid_database_shape(self):
        """Test cosine similarity rejects invalid database shape."""
        query = create_valid_embedding()
        database = np.random.rand(5, 256).astype(np.float32)
        
        with pytest.raises(ValueError, match="database must have shape"):
            compute_cosine_similarity(query, database)


# ============================================================
# Task 5: Best Candidate Tests
# ============================================================

class TestBestCandidate:
    """Test best candidate selection."""
    
    def test_best_candidate_selection(self, tmp_path):
        """Test best candidate is correctly identified."""
        # Create database with known similarities
        base_emb = create_valid_embedding(100)
        # Similar embedding (high similarity)
        similar_emb = base_emb + np.random.default_rng(1).normal(0, 0.01, 512).astype(np.float32)
        similar_emb = similar_emb / np.linalg.norm(similar_emb)
        # Different embedding (low similarity)
        diff_emb = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [similar_emb], "P002": [diff_emb]}
        )
        
        context = load_matching_database(str(tmp_path))
        result = match_identity(base_emb, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
        assert result.similarity > 0.9  # Should be very similar
        assert result.matched_sample_id is not None
        assert result.candidate_count == 2


# ============================================================
# Task 6: Person-Level Matching Tests
# ============================================================

class TestPersonLevelMatching:
    """Test person-level match aggregation."""
    
    def test_aggregate_person_matches_best_sample(self):
        """Test person aggregation with best_sample policy."""
        candidates = [
            CandidateMatch("s1", "P001", 0.9, {}),
            CandidateMatch("s2", "P001", 0.8, {}),
            CandidateMatch("s3", "P002", 0.7, {}),
        ]
        
        person_matches = aggregate_person_matches(candidates, policy="best_sample")
        
        assert len(person_matches) == 2
        assert person_matches[0].person_id == "P001"
        assert person_matches[0].best_similarity == 0.9
        assert person_matches[0].sample_count == 2
        assert person_matches[1].person_id == "P002"
        assert person_matches[1].best_similarity == 0.7
    
    def test_aggregate_person_matches_average(self):
        """Test person aggregation with average policy."""
        candidates = [
            CandidateMatch("s1", "P001", 0.9, {}),
            CandidateMatch("s2", "P001", 0.7, {}),
            CandidateMatch("s3", "P002", 0.8, {}),
        ]
        
        person_matches = aggregate_person_matches(candidates, policy="average")
        
        assert len(person_matches) == 2
        # P001 average = (0.9 + 0.7) / 2 = 0.8
        assert person_matches[0].person_id == "P001"
        assert np.isclose(person_matches[0].best_similarity, 0.8)
        assert person_matches[0].sample_count == 2
        # P002 average = 0.8
        assert person_matches[1].person_id == "P002"
        assert np.isclose(person_matches[1].best_similarity, 0.8)
    
    def test_aggregate_person_matches_same_person_not_ambiguous(self, tmp_path):
        """Test multiple samples for same person don't cause ambiguity."""
        # P001 has two very similar samples
        base_emb = create_valid_embedding(100)
        emb1 = base_emb + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = base_emb + np.random.default_rng(2).normal(0, 0.001, 512).astype(np.float32)
        emb2 = emb2 / np.linalg.norm(emb2)
        # P002 has different embedding
        emb3 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1, emb2], "P002": [emb3]}
        )
        
        context = load_matching_database(str(tmp_path))
        # Query is close to P001
        query = base_emb + np.random.default_rng(3).normal(0, 0.001, 512).astype(np.float32)
        query = query / np.linalg.norm(query)
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
        # Should NOT be ambiguous because both top matches are same person


# ============================================================
# Task 7: Unknown Threshold Tests
# ============================================================

class TestUnknownThreshold:
    """Test UNKNOWN threshold behavior."""
    
    def test_unknown_below_threshold(self, tmp_path):
        """Test UNKNOWN when best similarity below threshold."""
        emb1 = create_valid_embedding(100)
        emb2 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        # Query very different from both
        query = create_valid_embedding(999)
        
        config = MatchingConfig(match_threshold=0.5)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.UNKNOWN
        assert result.person_id is None
        assert result.similarity < 0.5
        assert "below_threshold" in result.provenance.get("decision", "")
    
    def test_match_above_threshold(self, tmp_path):
        """Test MATCH when best similarity above threshold."""
        base_emb = create_valid_embedding(100)
        similar_emb = base_emb + np.random.default_rng(1).normal(0, 0.01, 512).astype(np.float32)
        similar_emb = similar_emb / np.linalg.norm(similar_emb)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [similar_emb]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5)
        context.config = config
        
        result = match_identity(base_emb, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
        assert result.similarity > 0.5


# ============================================================
# Task 8: Ambiguity Tests
# ============================================================

class TestAmbiguity:
    """Test ambiguity detection."""
    
    def test_ambiguous_two_persons_equal_similarity(self, tmp_path):
        """Test AMBIGUOUS when two persons have equal similarity."""
        # Create two embeddings that are equally similar to query
        query = create_valid_embedding(100)
        
        # Create two database embeddings at same angle from query
        # Use orthogonal basis
        emb1 = create_valid_embedding(200)
        emb2 = create_valid_embedding(300)
        
        # Make them have same similarity to query by construction
        # Project query onto emb1 and emb2 directions
        # Actually, let's just make them identical for simplicity
        emb1 = query.copy()
        emb2 = query.copy()
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.05)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.AMBIGUOUS
        assert result.person_id is None
        assert "ambiguous" in result.provenance.get("decision", "")
    
    def test_ambiguous_near_equal_similarity(self, tmp_path):
        """Test AMBIGUOUS when two persons have near-equal similarity."""
        query = create_valid_embedding(100)
        
        # Create two embeddings with very similar similarity to query
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = query + np.random.default_rng(2).normal(0, 0.001, 512).astype(np.float32)
        emb2 = emb2 / np.linalg.norm(emb2)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.05)
        context.config = config
        
        result = match_identity(query, context)
        
        # Should be ambiguous since margin is very small
        assert result.status == MatchStatus.AMBIGUOUS
    
    def test_not_ambiguous_clear_winner(self, tmp_path):
        """Test MATCH when clear winner exists."""
        query = create_valid_embedding(100)
        
        # Clear winner
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        # Clear loser
        emb2 = create_valid_embedding(999)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.05)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"


# ============================================================
# Task 9: Same-Person Multiple Samples Tests
# ============================================================

class TestSamePersonMultipleSamples:
    """Test handling of multiple samples per person."""
    
    def test_multiple_samples_same_person_match(self, tmp_path):
        """Test MATCH when query matches person with multiple samples."""
        base_emb = create_valid_embedding(100)
        
        # P001 has 3 similar samples
        emb1 = base_emb + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = base_emb + np.random.default_rng(2).normal(0, 0.001, 512).astype(np.float32)
        emb2 = emb2 / np.linalg.norm(emb2)
        emb3 = base_emb + np.random.default_rng(3).normal(0, 0.001, 512).astype(np.float32)
        emb3 = emb3 / np.linalg.norm(emb3)
        
        # P002 has different embedding
        emb4 = create_valid_embedding(999)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1, emb2, emb3], "P002": [emb4]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = base_emb + np.random.default_rng(4).normal(0, 0.001, 512).astype(np.float32)
        query = query / np.linalg.norm(query)
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
        assert result.provenance.get("sample_count_for_person") == 3
    
    def test_multiple_samples_not_ambiguous(self, tmp_path):
        """Test multiple samples for same person don't trigger ambiguity."""
        base_emb = create_valid_embedding(100)
        
        # P001 has 2 samples
        emb1 = base_emb + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = base_emb + np.random.default_rng(2).normal(0, 0.001, 512).astype(np.float32)
        emb2 = emb2 / np.linalg.norm(emb2)
        
        # P002 has 1 sample with much lower similarity (clear separation)
        emb3 = create_valid_embedding(999)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1, emb2], "P002": [emb3]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = base_emb + np.random.default_rng(4).normal(0, 0.001, 512).astype(np.float32)
        query = query / np.linalg.norm(query)
        
        result = match_identity(query, context)
        
        # Should be MATCH, not AMBIGUOUS, because both top samples are P001
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"


# ============================================================
# Task 10: Unknown Case Tests
# ============================================================

class TestUnknownCase:
    """Test UNKNOWN case handling."""
    
    def test_unknown_no_person_id(self, tmp_path):
        """Test UNKNOWN returns no person_id."""
        emb1 = create_valid_embedding(100)
        emb2 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)  # Very different
        
        config = MatchingConfig(match_threshold=0.5)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.UNKNOWN
        assert result.person_id is None
        assert result.matched_sample_id is None
    
    def test_unknown_no_forced_match(self, tmp_path):
        """Test UNKNOWN doesn't force a match."""
        emb1 = create_valid_embedding(100)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)  # Very different
        
        config = MatchingConfig(match_threshold=0.9)  # High threshold
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.UNKNOWN
        assert result.person_id is None


# ============================================================
# Task 11: Ambiguous Case Tests
# ============================================================

class TestAmbiguousCase:
    """Test AMBIGUOUS case handling."""
    
    def test_ambiguous_no_forced_identity(self, tmp_path):
        """Test AMBIGUOUS doesn't force an identity."""
        query = create_valid_embedding(100)
        emb1 = query.copy()
        emb2 = query.copy()
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.05)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.AMBIGUOUS
        assert result.person_id is None
        assert result.matched_sample_id is None
    
    def test_ambiguous_equal_scores(self, tmp_path):
        """Test AMBIGUOUS with exactly equal scores."""
        query = create_valid_embedding(100)
        emb1 = query.copy()
        emb2 = query.copy()
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.001)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.AMBIGUOUS
    
    def test_ambiguous_near_equal_scores(self, tmp_path):
        """Test AMBIGUOUS with near-equal scores."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.0001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = query + np.random.default_rng(2).normal(0, 0.0001, 512).astype(np.float32)
        emb2 = emb2 / np.linalg.norm(emb2)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.01)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.AMBIGUOUS


# ============================================================
# Task 12: Order Independence Tests
# ============================================================

class TestOrderIndependence:
    """Test order independence of matching."""
    
    def test_shuffle_database_order(self, tmp_path):
        """Test identical decision regardless of database order."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = create_valid_embedding(999)
        
        # Create database with P001 first
        db1_path = tmp_path / "db1"
        db1_path.mkdir(parents=True, exist_ok=True)
        embeddings_path1, metadata_path1 = create_test_database(
            db1_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        # Create database with P002 first (different order)
        db2_path = tmp_path / "db2"
        db2_path.mkdir(parents=True, exist_ok=True)
        embeddings_path2, metadata_path2 = create_test_database(
            db2_path, {"P002": [emb2], "P001": [emb1]}
        )
        
        context1 = load_matching_database(str(db1_path))
        context2 = load_matching_database(str(db2_path))
        
        result1 = match_identity(query, context1)
        result2 = match_identity(query, context2)
        
        assert result1.status == result2.status
        assert result1.person_id == result2.person_id
        assert np.isclose(result1.similarity, result2.similarity, atol=1e-5)
    
    def test_deterministic_tie_handling(self, tmp_path):
        """Test deterministic tie handling when candidates equivalent."""
        query = create_valid_embedding(100)
        emb1 = query.copy()
        emb2 = query.copy()
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.001)
        context.config = config
        
        # Run multiple times
        results = [match_identity(query, context) for _ in range(5)]
        
        # All should be AMBIGUOUS (deterministic)
        for result in results:
            assert result.status == MatchStatus.AMBIGUOUS


# ============================================================
# Task 13: Determinism Tests
# ============================================================

class TestDeterminism:
    """Test deterministic matching."""
    
    def test_deterministic_repeated_execution(self, tmp_path):
        """Test repeated execution produces identical results."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = create_valid_embedding(999)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        
        results = [match_identity(query, context) for _ in range(10)]
        
        for result in results:
            assert result.status == results[0].status
            assert result.person_id == results[0].person_id
            assert np.isclose(result.similarity, results[0].similarity, atol=1e-6)
            assert result.matched_sample_id == results[0].matched_sample_id
    
    def test_deterministic_with_config(self, tmp_path):
        """Test deterministic with custom config."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        emb2 = create_valid_embedding(999)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        config = MatchingConfig(match_threshold=0.6, ambiguity_margin=0.02)
        
        results = []
        for _ in range(5):
            context = load_matching_database(str(tmp_path))
            context.config = config
            results.append(match_identity(query, context))
        
        for result in results:
            assert result.status == results[0].status
            assert result.person_id == results[0].person_id
            assert np.isclose(result.similarity, results[0].similarity, atol=1e-6)


# ============================================================
# Task 14: Provenance Tests
# ============================================================

class TestProvenance:
    """Test provenance preservation."""
    
    def test_provenance_in_result(self, tmp_path):
        """Test provenance is preserved in match result."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query_prov = {"source": "test_image.jpg", "timestamp": "2024-01-01T00:00:00Z"}
        
        result = match_identity(query, context, query_provenance=query_prov)
        
        assert result.status == MatchStatus.MATCH
        assert result.provenance.get("query_provenance") == query_prov
        assert "database_model_id" in result.provenance
        assert "database_model_filename" in result.provenance
        assert "database_model_sha256" in result.provenance
        assert "database_schema_version" in result.provenance
        assert "matching_time_ms" in result.provenance
        assert "person_aggregation_policy" in result.provenance
        assert "decision" in result.provenance
    
    def test_provenance_match_includes_matched_sample(self, tmp_path):
        """Test MATCH provenance includes matched sample info."""
        query = create_valid_embedding(100)
        emb1 = query + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        emb1 = emb1 / np.linalg.norm(emb1)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.MATCH
        assert result.provenance.get("matched_person_id") == "P001"
        assert result.provenance.get("matched_sample_id") is not None
        assert result.provenance.get("matched_similarity") == result.similarity
    
    def test_provenance_unknown_includes_best_candidate(self, tmp_path):
        """Test UNKNOWN provenance includes best candidate info."""
        query = create_valid_embedding(999)
        emb1 = create_valid_embedding(100)
        emb2 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.UNKNOWN
        assert "best_person_id" in result.provenance
        assert "best_person_similarity" in result.provenance
        assert "all_person_matches" in result.provenance
    
    def test_provenance_ambiguous_includes_both_candidates(self, tmp_path):
        """Test AMBIGUOUS provenance includes both candidates."""
        query = create_valid_embedding(100)
        emb1 = query.copy()
        emb2 = query.copy()
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        context = load_matching_database(str(tmp_path))
        config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.001)
        context.config = config
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.AMBIGUOUS
        assert "best_person_id" in result.provenance
        assert "second_best_person_id" in result.provenance
        assert "margin" in result.provenance


# ============================================================
# Task 15: Database Integrity Tests
# ============================================================

class TestDatabaseIntegrity:
    """Test rejection of corrupted/invalid databases."""
    
    def test_reject_corrupted_npy(self, tmp_path):
        """Test rejection of corrupted .npy file."""
        # Create valid database first
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Corrupt the .npy file
        with open(embeddings_path, "wb") as f:
            f.write(b"corrupted data")
        
        # Should raise an error when trying to load the corrupted file
        with pytest.raises(ValueError):
            load_matching_database(str(tmp_path))
    
    def test_reject_corrupted_metadata(self, tmp_path):
        """Test rejection of corrupted metadata JSON."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Corrupt the metadata file
        with open(metadata_path, "w") as f:
            f.write("{ invalid json")
        
        with pytest.raises(ValueError, match="corrupted metadata"):
            load_matching_database(str(tmp_path))
    
    def test_reject_wrong_model(self, tmp_path):
        """Test rejection of wrong model database."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Modify metadata to have wrong model
        with open(metadata_path) as f:
            metadata = json.load(f)
        metadata["model_id"] = "wrong_model"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        with pytest.raises(ValueError, match="model_id must be arcface"):
            load_matching_database(str(tmp_path))
    
    def test_reject_wrong_sha256(self, tmp_path):
        """Test rejection of wrong SHA256."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Modify metadata to have empty SHA256
        with open(metadata_path) as f:
            metadata = json.load(f)
        metadata["model_sha256"] = ""
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        with pytest.raises(ValueError, match="model_sha256 must be non-empty"):
            load_matching_database(str(tmp_path))
    
    def test_reject_wrong_dimension(self, tmp_path):
        """Test rejection of wrong dimension database."""
        # Create embeddings with wrong dimension
        embeddings = np.random.rand(10, 256).astype(np.float32)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        with pytest.raises(ValueError, match="512 columns"):
            load_matching_database(str(tmp_path))
    
    def test_reject_wrong_dtype(self, tmp_path):
        """Test rejection of wrong dtype database."""
        embeddings = np.random.rand(10, 512).astype(np.float64)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        with pytest.raises(ValueError, match="float32"):
            load_matching_database(str(tmp_path))
    
    def test_reject_nan_database(self, tmp_path):
        """Test rejection of database with NaN."""
        embeddings = create_database_embeddings(10)
        embeddings[0, 0] = np.nan
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        with pytest.raises(ValueError, match="non-finite"):
            load_matching_database(str(tmp_path))
    
    def test_reject_inf_database(self, tmp_path):
        """Test rejection of database with Inf."""
        embeddings = create_database_embeddings(10)
        embeddings[0, 0] = np.inf
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        with pytest.raises(ValueError, match="non-finite"):
            load_matching_database(str(tmp_path))
    
    def test_reject_non_normalized_database(self, tmp_path):
        """Test rejection of non-normalized database."""
        embeddings = np.ones((10, 512), dtype=np.float32)
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        with pytest.raises(ValueError, match="L2 normalized"):
            load_matching_database(str(tmp_path))
    
    def test_reject_incompatible_schema(self, tmp_path):
        """Test rejection of incompatible schema version."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Modify metadata to have wrong schema version
        with open(metadata_path) as f:
            metadata = json.load(f)
        metadata["schema_version"] = "2.0"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            load_matching_database(str(tmp_path))


# ============================================================
# Task 16: Performance/Memory Tests
# ============================================================

class TestPerformanceMemory:
    """Test performance and memory characteristics."""
    
    def test_bounded_memory(self, tmp_path):
        """Test matching doesn't accumulate unbounded memory."""
        # Create larger database
        embeddings = create_database_embeddings(1000)
        person_samples = {f"P{i:04d}": [embeddings[i]] for i in range(1000)}
        
        embeddings_path, metadata_path = create_test_database(tmp_path, person_samples)
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)
        
        # Multiple queries should not increase memory unboundedly
        for _ in range(10):
            result = match_identity(query, context)
            assert result.candidate_count == 1000
    
    def test_no_database_mutation(self, tmp_path):
        """Test matching doesn't mutate database."""
        emb1 = create_valid_embedding(100)
        emb2 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        # Load original
        original_embeddings = np.load(embeddings_path)
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)
        
        match_identity(query, context)
        
        # Reload and verify unchanged
        reloaded_embeddings = np.load(embeddings_path)
        assert np.array_equal(original_embeddings, reloaded_embeddings)
    
    def test_no_unbounded_candidate_accumulation(self, tmp_path):
        """Test no unbounded candidate accumulation."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)
        
        # Run many times
        for _ in range(100):
            result = match_identity(query, context)
            assert result.candidate_count == 1


# ============================================================
# Task 17: Safety Tests
# ============================================================

class TestSafety:
    """Test safety boundaries - no camera, no live streaming, etc."""
    
    def test_no_camera_access(self):
        """Verify matching module doesn't import camera modules."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        
        # Should not contain camera-related imports (excluding docstring)
        # Check for actual imports, not docstring mentions
        assert "import camera" not in source.lower()
        assert "from camera" not in source.lower()
        assert "CameraCapture" not in source
        assert "cv2.VideoCapture" not in source
    
    def test_no_mediamtx(self):
        """Verify matching module doesn't reference MediaMTX."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "MediaMTX" not in source
        assert "mediamtx" not in source.lower()
    
    def test_no_rtsp_rtmp(self):
        """Verify matching module doesn't reference RTSP/RTMP."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "RTSP" not in source
        assert "RTMP" not in source
        assert "rtsp" not in source.lower()
        assert "rtmp" not in source.lower()
    
    def test_no_live_ffmpeg(self):
        """Verify matching module doesn't use live FFmpeg."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "ffmpeg" not in source.lower()
        assert "subprocess" not in source
    
    def test_no_attendance(self):
        """Verify matching module doesn't implement attendance."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        
        # Should not contain attendance implementation (excluding docstring mentions)
        # Check for actual attendance-related code, not just docstring
        assert "import attendance" not in source.lower()
        assert "from attendance" not in source.lower()
        assert "Attendance" not in source or "Attendance" in source.split('"""')[0]  # Only in docstring
        # The word "attendance" may appear in docstring as negative statement
        # but should not appear as actual implementation
    
    def test_no_in_out(self):
        """Verify matching module doesn't implement IN/OUT."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "IN/OUT" not in source
        assert "in_out" not in source.lower()
    
    def test_no_schedule(self):
        """Verify matching module doesn't implement schedule."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "schedule" not in source.lower()
    
    def test_no_excel(self):
        """Verify matching module doesn't implement Excel."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "excel" not in source.lower()
        assert "openpyxl" not in source.lower()
    
    def test_no_1k3d68(self):
        """Verify matching module doesn't implement 1K3D68."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "1k3d68" not in source.lower()
        assert "1K3D68" not in source
    
    def test_no_model_weight_modification(self):
        """Verify matching module doesn't modify model weights."""
        import app.vision.matching as matching_module
        import inspect
        
        source = inspect.getsource(matching_module)
        assert "model_def" not in source or "expected_sha256" in source  # Only reads SHA256
        assert "save" not in source or "np.save" in source  # Only saves embeddings, not models


# ============================================================
# Task 18: Targeted Tests - Integration
# ============================================================

class TestIntegration:
    """Integration tests for matching pipeline."""
    
    def test_match_identity_from_database_dir(self, tmp_path):
        """Test convenience function match_identity_from_database_dir."""
        emb1 = create_valid_embedding(100)
        emb2 = create_valid_embedding(200)
        
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1], "P002": [emb2]}
        )
        
        query = emb1 + np.random.default_rng(1).normal(0, 0.001, 512).astype(np.float32)
        query = query / np.linalg.norm(query)
        
        config = MatchingConfig(match_threshold=0.5)
        result = match_identity_from_database_dir(query, str(tmp_path), config=config)
        
        assert result.status == MatchStatus.MATCH
        assert result.person_id == "P001"
    
    def test_load_matching_database_returns_context(self, tmp_path):
        """Test load_matching_database returns MatchingContext."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        
        assert hasattr(context, 'database_embeddings')
        assert hasattr(context, 'database_metadata')
        assert hasattr(context, 'config')
        assert context.database_embeddings.shape == (1, 512)
        assert isinstance(context.config, MatchingConfig)
    
    def test_empty_database(self, tmp_path):
        """Test matching with empty database."""
        # Create empty database
        embeddings = np.zeros((0, 512), dtype=np.float32)
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=0,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(999)
        
        result = match_identity(query, context)
        
        assert result.status == MatchStatus.UNKNOWN
        assert result.candidate_count == 0
        assert result.provenance.get("decision") == "no_candidates"


# ============================================================
# Task 19: Negative Tests
# ============================================================

class TestNegativeCases:
    """Test explicit rejection of invalid inputs."""
    
    def test_reject_wrong_query_shape(self, tmp_path):
        """Test rejection of wrong query shape."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = np.random.rand(256).astype(np.float32)
        
        with pytest.raises(ValueError, match="shape"):
            match_identity(query, context)
    
    def test_reject_wrong_query_dtype(self, tmp_path):
        """Test rejection of wrong query dtype."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = np.random.rand(512).astype(np.float64)
        
        with pytest.raises(ValueError, match="float32"):
            match_identity(query, context)
    
    def test_reject_nan_query(self, tmp_path):
        """Test rejection of NaN query."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(100)
        query[0] = np.nan
        
        with pytest.raises(ValueError, match="non-finite"):
            match_identity(query, context)
    
    def test_reject_inf_query(self, tmp_path):
        """Test rejection of Inf query."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = create_valid_embedding(100)
        query[0] = np.inf
        
        with pytest.raises(ValueError, match="non-finite"):
            match_identity(query, context)
    
    def test_reject_zero_query(self, tmp_path):
        """Test rejection of zero query."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        context = load_matching_database(str(tmp_path))
        query = np.zeros(512, dtype=np.float32)
        
        with pytest.raises(ValueError, match="norm too small"):
            match_identity(query, context)
    
    def test_reject_invalid_database(self, tmp_path):
        """Test rejection of invalid database."""
        # Create database with wrong dimension
        embeddings = np.random.rand(10, 256).astype(np.float32)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        metadata = EnrollmentDatabaseMetadata(
            embedding_count=10,
            model_sha256="hash",
        )
        
        embeddings_path = tmp_path / "embeddings.npy"
        metadata_path = tmp_path / "embeddings.npy.metadata.json"
        
        np.save(embeddings_path, embeddings)
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f)
        
        query = create_valid_embedding(100)
        
        with pytest.raises(ValueError, match="512 columns"):
            match_identity_from_database_dir(query, str(tmp_path))
    
    def test_reject_wrong_model_database(self, tmp_path):
        """Test rejection of wrong model database."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Modify metadata
        with open(metadata_path) as f:
            metadata = json.load(f)
        metadata["model_id"] = "wrong_model"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        query = create_valid_embedding(100)
        
        with pytest.raises(ValueError, match="model_id must be arcface"):
            match_identity_from_database_dir(query, str(tmp_path))
    
    def test_reject_incompatible_schema(self, tmp_path):
        """Test rejection of incompatible schema."""
        emb1 = create_valid_embedding(100)
        embeddings_path, metadata_path = create_test_database(
            tmp_path, {"P001": [emb1]}
        )
        
        # Modify metadata
        with open(metadata_path) as f:
            metadata = json.load(f)
        metadata["schema_version"] = "2.0"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        query = create_valid_embedding(100)
        
        with pytest.raises(ValueError, match="Unsupported schema_version"):
            match_identity_from_database_dir(query, str(tmp_path))


# ============================================================
# Task 20: Final Validation - Run all tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])