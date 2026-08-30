"""
Phase 30A — Enrollment & ArcFace Database Deliverables Verification.

This test verifies that all Phase 30A deliverables are present and correct.
It does NOT modify any production code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


# =============================================================================
# PHASE 19 CONTRACT INSPECTION
# =============================================================================

def get_phase19_contract():
    """Extract the expected contract from Phase 19 matching module."""
    from app.vision.matching_contract import (
        MatchingConfig,
        validate_database_for_matching,
        validate_query_embedding,
    )
    from app.vision.enrollment_contract import EnrollmentDatabaseMetadata
    
    # Phase 19 expects:
    # - embeddings: (N, 512) float32 L2-normalized
    # - metadata: EnrollmentDatabaseMetadata with schema_version=1.0, model_id=arcface, model_filename=glintr100.onnx
    # - normalization: L2
    # - dtype: float32
    # - embedding_dimension: 512
    
    return {
        "embedding_dimension": 512,
        "embedding_dtype": np.float32,
        "normalization": "L2",
        "model_id": "arcface",
        "model_filename": "glintr100.onnx",
        "schema_version": "1.0",
    }


# =============================================================================
# DELIVERABLES VERIFICATION
# =============================================================================

class TestPhase30ADeliverables:
    """Verify all Phase 30A deliverables exist and are correct."""
    
    def test_scripts_phase30a_enrollment_exists(self):
        """scripts/phase30a_enrollment.py exists."""
        path = Path("scripts/phase30a_enrollment.py")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_tests_unit_phase30a_enrollment_exists(self):
        """tests/unit/test_phase30a_enrollment.py exists."""
        path = Path("tests/unit/test_phase30a_enrollment.py")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_enrollment_database_embeddings_npy_exists(self):
        """data/enrollment_db/embeddings.npy exists."""
        path = Path("data/enrollment_db/embeddings.npy")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_enrollment_database_metadata_json_exists(self):
        """data/enrollment_db/embeddings.npy.metadata.json exists."""
        path = Path("data/enrollment_db/embeddings.npy.metadata.json")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_enrollment_report_json_exists(self):
        """reports/enrollment/enrollment_report.json exists."""
        path = Path("reports/enrollment/enrollment_report.json")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_enrollment_report_md_exists(self):
        """reports/enrollment/enrollment_report.md exists."""
        path = Path("reports/enrollment/enrollment_report.md")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_inspection_report_exists(self):
        """reports/inspection exists."""
        path = Path("reports/inspection")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_determinism_report_exists(self):
        """reports/determinism exists."""
        path = Path("reports/determinism")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_phase19_test_report_exists(self):
        """reports/phase19_test exists."""
        path = Path("reports/phase19_test")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()
    
    def test_acceptance_report_md_exists(self):
        """reports/PHASE_30A_ACCEPTANCE_REPORT.md exists."""
        path = Path("reports/PHASE_30A_ACCEPTANCE_REPORT.md")
        assert path.exists(), f"Missing: {path}"
        assert path.is_file()


# =============================================================================
# DATABASE VERIFICATION
# =============================================================================

class TestEnrollmentDatabase:
    """Verify the enrollment database content matches Phase 19 contract."""
    
    def test_embeddings_load_successfully(self):
        """embeddings.npy loads without error."""
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        assert embeddings is not None
    
    def test_embeddings_not_empty(self):
        """embeddings array is not empty."""
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        assert embeddings.size > 0, "Embeddings array is empty"
        assert embeddings.shape[0] > 0, "No embeddings in database"
    
    def test_embeddings_dimensionality_matches_phase19(self):
        """Embedding dimension matches Phase 19 contract (512)."""
        contract = get_phase19_contract()
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        
        assert embeddings.ndim == 2, f"Expected 2D array, got {embeddings.ndim}D"
        assert embeddings.shape[1] == contract["embedding_dimension"], \
            f"Expected dimension {contract['embedding_dimension']}, got {embeddings.shape[1]}"
    
    def test_embeddings_dtype_matches_phase19(self):
        """Embedding dtype matches Phase 19 contract (float32)."""
        contract = get_phase19_contract()
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        
        assert embeddings.dtype == contract["embedding_dtype"], \
            f"Expected dtype {contract['embedding_dtype']}, got {embeddings.dtype}"
    
    def test_embeddings_all_finite(self):
        """All embedding values are finite (no NaN, no Inf)."""
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        
        assert np.isfinite(embeddings).all(), "Embeddings contain non-finite values"
        assert not np.isnan(embeddings).any(), "Embeddings contain NaN"
        assert not np.isinf(embeddings).any(), "Embeddings contain Inf"
    
    def test_embeddings_l2_normalized(self):
        """Embeddings are L2-normalized (norm ≈ 1.0)."""
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        
        norms = np.linalg.norm(embeddings, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5), \
            f"Embeddings not L2-normalized. Norms range: [{norms.min():.6f}, {norms.max():.6f}]"


# =============================================================================
# METADATA VERIFICATION
# =============================================================================

class TestEnrollmentMetadata:
    """Verify the enrollment metadata content matches Phase 19 contract."""
    
    def test_metadata_loads_successfully(self):
        """Metadata JSON loads without error."""
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        assert metadata is not None
    
    def test_metadata_schema_version(self):
        """Metadata has correct schema_version."""
        contract = get_phase19_contract()
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert metadata["schema_version"] == contract["schema_version"], \
            f"Expected schema_version {contract['schema_version']}, got {metadata['schema_version']}"
    
    def test_metadata_model_id(self):
        """Metadata has correct model_id."""
        contract = get_phase19_contract()
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert metadata["model_id"] == contract["model_id"], \
            f"Expected model_id {contract['model_id']}, got {metadata['model_id']}"
    
    def test_metadata_model_filename(self):
        """Metadata has correct model_filename."""
        contract = get_phase19_contract()
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert metadata["model_filename"] == contract["model_filename"], \
            f"Expected model_filename {contract['model_filename']}, got {metadata['model_filename']}"
    
    def test_metadata_embedding_dimension(self):
        """Metadata embedding_dimension matches contract."""
        contract = get_phase19_contract()
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert metadata["embedding_dimension"] == contract["embedding_dimension"], \
            f"Expected embedding_dimension {contract['embedding_dimension']}, got {metadata['embedding_dimension']}"
    
    def test_metadata_normalization(self):
        """Metadata normalization matches contract."""
        contract = get_phase19_contract()
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert metadata["normalization"] == contract["normalization"], \
            f"Expected normalization {contract['normalization']}, got {metadata['normalization']}"
    
    def test_metadata_person_ids_present(self):
        """Metadata contains person_ids list."""
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        assert "person_ids" in metadata
        assert isinstance(metadata["person_ids"], list)
        assert len(metadata["person_ids"]) > 0
    
    def test_metadata_embedding_count_matches(self):
        """Metadata embedding_count matches actual embeddings count."""
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        assert metadata["embedding_count"] == embeddings.shape[0], \
            f"Metadata count {metadata['embedding_count']} != actual {embeddings.shape[0]}"
    
    def test_metadata_sample_provenance_count_matches(self):
        """Metadata sample_provenance count matches embedding count."""
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        assert len(metadata["sample_provenance"]) == embeddings.shape[0], \
            f"Provenance count {len(metadata['sample_provenance'])} != embedding count {embeddings.shape[0]}"
    
    def test_metadata_embedding_dimension_consistency(self):
        """Metadata embedding_dimension matches actual embeddings dimension."""
        with open("data/enrollment_db/embeddings.npy.metadata.json") as f:
            metadata = json.load(f)
        
        embeddings = np.load("data/enrollment_db/embeddings.npy")
        assert metadata["embedding_dimension"] == embeddings.shape[1], \
            f"Metadata dimension {metadata['embedding_dimension']} != actual {embeddings.shape[1]}"


# =============================================================================
# REPORTS VERIFICATION
# =============================================================================

class TestReports:
    """Verify generated reports are valid and readable."""
    
    def test_enrollment_report_json_valid(self):
        """enrollment_report.json is valid JSON with expected structure."""
        with open("reports/enrollment/enrollment_report.json") as f:
            report = json.load(f)
        
        assert "summary" in report
        assert "rejection_reasons" in report
        assert "person_embedding_counts" in report
        assert "rejections" in report
        
        summary = report["summary"]
        assert summary["total_persons"] > 0
        assert summary["total_source_images"] > 0
        assert summary["accepted_images"] >= 0
        assert summary["rejected_images"] >= 0
        assert summary["embeddings_generated"] > 0
        assert summary["embedding_dimension"] == 512
    
    def test_enrollment_report_md_nonempty(self):
        """enrollment_report.md is non-empty and readable."""
        content = Path("reports/enrollment/enrollment_report.md").read_text()
        assert len(content) > 0
        assert "Phase 30A Enrollment Report" in content
    
    def test_inspection_report_valid(self):
        """inspection report is valid Markdown with expected content."""
        content = Path("reports/inspection").read_text()
        assert len(content) > 0
        assert "Phase 30A Database Inspection" in content
        assert "Shape:" in content
        assert "Dtype:" in content
        assert "All Finite:" in content
        assert "L2 Normalized:" in content
        assert "Validation" in content
        assert "Passed" in content
        assert "True" in content
        assert "HS001" in content
        assert "HS002" in content
        assert "HS003" in content
    
    def test_determinism_report_valid(self):
        """determinism report is valid JSON with expected structure."""
        with open("reports/determinism") as f:
            report = json.load(f)
        
        assert "embeddings_identical" in report
        assert "metadata_identical" in report
        assert "embeddings_shape_match" in report
        assert "person_ids_match" in report
        assert "sample_order_match" in report
        assert report["embeddings_identical"] is True
        assert report["embeddings_shape_match"] is True
        assert report["person_ids_match"] is True
    
    def test_phase19_test_report_valid(self):
        """phase19_test report is valid JSON with expected structure."""
        with open("reports/phase19_test") as f:
            report = json.load(f)
        
        assert "database_loaded" in report
        assert "matching_tests" in report
        assert "overall_pass" in report
        assert report["database_loaded"] is True
    
    def test_acceptance_report_md_nonempty(self):
        """PHASE_30A_ACCEPTANCE_REPORT.md is non-empty and readable."""
        content = Path("reports/PHASE_30A_ACCEPTANCE_REPORT.md").read_text()
        assert len(content) > 0
        assert "PHASE 30A ACCEPTANCE REPORT" in content


# =============================================================================
# CLI VERIFICATION
# =============================================================================

class TestCLI:
    """Verify the Phase 30A CLI works correctly."""
    
    def test_cli_help_works(self):
        """CLI --help returns success and shows usage."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.phase30a_enrollment", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        assert result.returncode == 0, f"CLI help failed: {result.stderr}"
        assert "Phase 30A" in result.stdout
        assert "build" in result.stdout
        assert "validate" in result.stdout
        assert "inspect" in result.stdout
        assert "test-phase19" in result.stdout
        assert "determinism" in result.stdout
    
    def test_cli_validate_works(self):
        """CLI validate command works on generated database."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.phase30a_enrollment", "validate", "--database", "data/enrollment_db"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        assert result.returncode == 0, f"CLI validate failed: {result.stderr}"
        assert "Validation passed: True" in result.stdout
    
    def test_cli_inspect_works(self):
        """CLI inspect command works on generated database."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.phase30a_enrollment", "inspect", "--database", "data/enrollment_db"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        assert result.returncode == 0, f"CLI inspect failed: {result.stderr}"
        assert "ENROLLMENT DATABASE INSPECTION" in result.stdout
        assert "Validation: PASS" in result.stdout


# =============================================================================
# PHASE 19 COMPATIBILITY VERIFICATION
# =============================================================================

class TestPhase19Compatibility:
    """Verify the generated database is compatible with Phase 19 matcher."""
    
    def test_phase19_loads_database(self):
        """Phase 19 matcher can load the database."""
        from app.vision.matching import load_matching_database
        
        context = load_matching_database("data/enrollment_db")
        assert context is not None
        assert hasattr(context, "database_embeddings")
        assert hasattr(context, "database_metadata")
        assert hasattr(context, "config")
    
    def test_phase19_database_validation_passes(self):
        """Phase 19 database validation passes."""
        from app.vision.matching import load_matching_database
        from app.vision.matching_contract import validate_database_for_matching
        
        context = load_matching_database("data/enrollment_db")
        
        is_valid, error = validate_database_for_matching(
            context.database_embeddings,
            context.database_metadata,
        )
        
        assert is_valid, f"Phase 19 validation failed: {error}"
    
    def test_phase19_matching_executable(self):
        """Phase 19 matching can execute with a query embedding."""
        from app.vision.matching import load_matching_database, match_identity
        from app.vision.matching_contract import MatchingConfig, MatchStatus
        
        context = load_matching_database("data/enrollment_db")
        context.config = MatchingConfig(match_threshold=0.5, ambiguity_margin=0.05)
        
        # Use first embedding from database as query
        query_embedding = context.database_embeddings[0]
        
        result = match_identity(query_embedding, context)
        
        assert result is not None
        assert hasattr(result, "status")
        assert hasattr(result, "person_id")
        assert hasattr(result, "similarity")
        assert result.status in (MatchStatus.MATCH, MatchStatus.UNKNOWN, MatchStatus.AMBIGUOUS)


# =============================================================================
# REGRESSION VERIFICATION
# =============================================================================

class TestRegression:
    """Verify no regressions in existing phases."""
    
    def test_phase13_unit_tests_pass(self):
        """Phase 13 unit tests still pass."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_phase13_enrollment.py", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        assert result.returncode == 0, f"Phase 13 tests failed: {result.stdout}\n{result.stderr}"
    
    def test_phase14_unit_tests_pass(self):
        """Phase 14 unit tests still pass."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_phase14_matching.py", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        assert result.returncode == 0, f"Phase 14 tests failed: {result.stdout}\n{result.stderr}"
    
    def test_phase30a_unit_tests_pass(self):
        """Phase 30A unit tests still pass."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_phase30a_enrollment.py", "-q"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        
        assert result.returncode == 0, f"Phase 30A tests failed: {result.stdout}\n{result.stderr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])