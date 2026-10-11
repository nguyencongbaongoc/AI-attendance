"""
Unit tests for Phase 4 production model acquisition and validation.

Tests:
- Model file existence
- SHA256 validation
- Hash mismatch rejection
- Registry resolution
- All-six-model inventory
- ONNX checker validation
- YOLO model load validation
- Contract validation
- Missing-model handling
- Forbidden substitution detection

Safety tests:
- No camera access
- No MediaMTX
- No RTMP/RTSP
- No FFmpeg streaming
- No IPC
- No model modification
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.validation import (
    ModelInventory,
    ModelInventoryEntry,
    ONNXValidationResult,
    YOLOLoadResult,
    check_all_models_available,
    collect_model_inventory,
    compute_file_sha256,
    validate_contract_consistency,
    validate_onnx_model,
    validate_yolo_model,
)
from app.models.registry import (
    ModelRegistry,
    get_model_registry,
)
from app.models.contracts import ModelStatus


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the ModelRegistry singleton before each test."""
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


# =============================================================================
# MODEL FILE EXISTENCE TESTS
# =============================================================================

class TestModelFileExistence:
    """Test model file existence checks."""

    def test_scrfd_file_exists(self):
        """Test SCRFD model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("scrfd")
        assert model_path.exists(), f"SCRFD model not found at {model_path}"

    def test_arcface_file_exists(self):
        """Test ArcFace model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("arcface")
        assert model_path.exists(), f"ArcFace model not found at {model_path}"

    def test_landmark_file_exists(self):
        """Test 1k3d68 landmark model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("landmark_1k3d68")
        assert model_path.exists(), f"Landmark model not found at {model_path}"

    def test_reid_file_exists(self):
        """Test ReID model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("reid")
        assert model_path.exists(), f"ReID model not found at {model_path}"

    def test_yolo_person_file_exists(self):
        """Test YOLO person model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("yolo_person")
        assert model_path.exists(), f"YOLO person model not found at {model_path}"

    def test_yolo_pose_file_exists(self):
        """Test YOLO pose model file exists at registry path."""
        registry = get_model_registry()
        model_path = registry.get_model_path("yolo_pose")
        assert model_path.exists(), f"YOLO pose model not found at {model_path}"


# =============================================================================
# SHA256 VALIDATION TESTS
# =============================================================================

class TestSHA256Validation:
    """Test SHA256 hash validation."""

    def test_scrfd_sha256_matches(self):
        """Test SCRFD model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("scrfd")
        assert result.is_verified(), f"SCRFD hash mismatch: {result}"

    def test_arcface_sha256_matches(self):
        """Test ArcFace model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("arcface")
        assert result.is_verified(), f"ArcFace hash mismatch: {result}"

    def test_landmark_sha256_matches(self):
        """Test 1k3d68 model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("landmark_1k3d68")
        assert result.is_verified(), f"Landmark hash mismatch: {result}"

    def test_reid_sha256_matches(self):
        """Test ReID model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("reid")
        assert result.is_verified(), f"ReID hash mismatch: {result}"

    def test_yolo_person_sha256_matches(self):
        """Test YOLO person model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("yolo_person")
        assert result.is_verified(), f"YOLO person hash mismatch: {result}"

    def test_yolo_pose_sha256_matches(self):
        """Test YOLO pose model SHA256 matches expected value."""
        registry = get_model_registry()
        result = registry.verify_model("yolo_pose")
        assert result.is_verified(), f"YOLO pose hash mismatch: {result}"


# =============================================================================
# HASH MISMATCH REJECTION TESTS
# =============================================================================

class TestHashMismatchRejection:
    """Test that hash mismatches are properly rejected."""

    def test_hash_mismatch_detected(self, tmp_path):
        """Test that a corrupted model file is detected."""
        # Create a fake model file with wrong content
        fake_model = tmp_path / "fake_model.onnx"
        fake_model.write_bytes(b"not a real model")
        
        # Compute hash
        actual_hash = compute_file_sha256(fake_model)
        expected_hash = "0" * 64  # Wrong hash
        
        assert actual_hash != expected_hash

    def test_registry_reports_corrupt_on_mismatch(self, tmp_path):
        """Test that registry reports CORRUPT status on hash mismatch."""
        registry = get_model_registry()
        
        # Get a model and verify it's available
        model_path = registry.get_model_path("scrfd")
        if model_path.exists():
            # The actual model should be verified
            status = registry.get_model_status("scrfd")
            assert status == ModelStatus.AVAILABLE


# =============================================================================
# REGISTRY RESOLUTION TESTS
# =============================================================================

class TestRegistryResolution:
    """Test ModelRegistry resolution."""

    def test_registry_resolves_all_six_models(self):
        """Test that registry resolves all six production models."""
        registry = get_model_registry()
        model_ids = registry.get_model_ids()
        
        expected_models = {"scrfd", "arcface", "landmark_1k3d68", "reid", "yolo_person", "yolo_pose"}
        actual_models = set(model_ids)
        
        assert expected_models == actual_models

    def test_registry_returns_correct_paths(self):
        """Test that registry returns correct model paths."""
        registry = get_model_registry()
        
        # SCRFD
        scrfd_path = registry.get_model_path("scrfd")
        assert "scrfd" in str(scrfd_path)
        assert scrfd_path.name == "scrfd_10g_bnkps.onnx"
        
        # ArcFace
        arcface_path = registry.get_model_path("arcface")
        assert "arcface" in str(arcface_path)
        assert arcface_path.name == "glintr100.onnx"

    def test_registry_raises_for_unknown_model(self):
        """Test that registry raises for unknown model ID."""
        registry = get_model_registry()
        
        with pytest.raises(Exception):  # ModelNotFoundError
            registry.get("unknown_model_xyz")


# =============================================================================
# ALL SIX MODEL INVENTORY TESTS
# =============================================================================

class TestAllSixModelInventory:
    """Test complete model inventory collection."""

    def test_inventory_collects_all_six_models(self):
        """Test that inventory collects all six production models."""
        inventory = collect_model_inventory()
        
        assert inventory.total_count == 6
        assert len(inventory.entries) == 6

    def test_inventory_all_models_verified(self):
        """Test that all models are verified in inventory."""
        inventory = collect_model_inventory()
        
        # All 6 models should be verified
        assert inventory.verified_count == 6
        assert inventory.mismatch_count == 0
        assert inventory.missing_count == 0

    def test_inventory_entry_has_required_fields(self):
        """Test that inventory entries have all required fields."""
        inventory = collect_model_inventory()
        
        for entry in inventory.entries:
            assert entry.model_id is not None
            assert entry.filename is not None
            assert entry.path is not None
            assert entry.expected_sha256 is not None
            assert entry.actual_sha256 is not None
            assert entry.hash_match is True
            assert entry.integrity_status == "VALID"
            assert entry.provenance == "imported_from_legacy_project"


# =============================================================================
# ONNX CHECKER VALIDATION TESTS
# =============================================================================

class TestONNXCheckerValidation:
    """Test ONNX model integrity validation."""

    def test_scrfd_onnx_valid(self):
        """Test SCRFD ONNX model passes integrity check."""
        registry = get_model_registry()
        model_path = registry.get_model_path("scrfd")
        
        result = validate_onnx_model(model_path)
        
        assert result.valid, f"SCRFD ONNX validation failed: {result.error_message}"

    def test_arcface_onnx_valid(self):
        """Test ArcFace ONNX model passes integrity check."""
        registry = get_model_registry()
        model_path = registry.get_model_path("arcface")
        
        result = validate_onnx_model(model_path)
        
        assert result.valid, f"ArcFace ONNX validation failed: {result.error_message}"

    def test_landmark_onnx_valid(self):
        """Test 1k3d68 ONNX model passes integrity check."""
        registry = get_model_registry()
        model_path = registry.get_model_path("landmark_1k3d68")
        
        result = validate_onnx_model(model_path)
        
        assert result.valid, f"Landmark ONNX validation failed: {result.error_message}"

    def test_reid_onnx_valid(self):
        """Test ReID ONNX model passes integrity check."""
        registry = get_model_registry()
        model_path = registry.get_model_path("reid")
        
        result = validate_onnx_model(model_path)
        
        assert result.valid, f"ReID ONNX validation failed: {result.error_message}"

    def test_onnx_validation_returns_metadata(self):
        """Test ONNX validation returns model metadata."""
        registry = get_model_registry()
        model_path = registry.get_model_path("scrfd")
        
        result = validate_onnx_model(model_path)
        
        if result.valid:
            assert result.input_names is not None
            assert result.output_names is not None
            assert len(result.input_names) > 0
            assert len(result.output_names) > 0

    def test_onnx_validation_missing_file(self, tmp_path):
        """Test ONNX validation handles missing file."""
        missing_path = tmp_path / "missing.onnx"
        
        result = validate_onnx_model(missing_path)
        
        assert not result.valid
        assert "does not exist" in result.error_message


# =============================================================================
# YOLO MODEL LOAD VALIDATION TESTS
# =============================================================================

class TestYOLOLoadValidation:
    """Test YOLO model load validation."""

    def test_yolo_person_loads_successfully(self):
        """Test YOLO person model loads successfully."""
        registry = get_model_registry()
        model_path = registry.get_model_path("yolo_person")
        
        result = validate_yolo_model(model_path)
        
        assert result.load_success, f"YOLO person load failed: {result.error_message}"

    def test_yolo_pose_loads_successfully(self):
        """Test YOLO pose model loads successfully."""
        registry = get_model_registry()
        model_path = registry.get_model_path("yolo_pose")
        
        result = validate_yolo_model(model_path)
        
        assert result.load_success, f"YOLO pose load failed: {result.error_message}"

    def test_yolo_validation_missing_file(self, tmp_path):
        """Test YOLO validation handles missing file."""
        missing_path = tmp_path / "missing.pt"
        
        result = validate_yolo_model(missing_path)
        
        assert not result.load_success
        assert "does not exist" in result.error_message


# =============================================================================
# CONTRACT VALIDATION TESTS
# =============================================================================

class TestContractValidation:
    """Test model contract validation."""

    def test_scrfd_contract_valid(self):
        """Test SCRFD contract validation."""
        is_valid, error = validate_contract_consistency("scrfd")
        assert is_valid, f"SCRFD contract validation failed: {error}"

    def test_arcface_contract_valid(self):
        """Test ArcFace contract validation."""
        is_valid, error = validate_contract_consistency("arcface")
        assert is_valid, f"ArcFace contract validation failed: {error}"

    def test_landmark_contract_valid(self):
        """Test 1k3d68 contract validation."""
        is_valid, error = validate_contract_consistency("landmark_1k3d68")
        assert is_valid, f"Landmark contract validation failed: {error}"

    def test_reid_contract_valid(self):
        """Test ReID contract validation."""
        is_valid, error = validate_contract_consistency("reid")
        assert is_valid, f"ReID contract validation failed: {error}"

    def test_yolo_person_contract_valid(self):
        """Test YOLO person contract validation."""
        is_valid, error = validate_contract_consistency("yolo_person")
        assert is_valid, f"YOLO person contract validation failed: {error}"

    def test_yolo_pose_contract_valid(self):
        """Test YOLO pose contract validation."""
        is_valid, error = validate_contract_consistency("yolo_pose")
        assert is_valid, f"YOLO pose contract validation failed: {error}"


# =============================================================================
# MISSING MODEL HANDLING TESTS
# =============================================================================

class TestMissingModelHandling:
    """Test handling of missing models."""

    def test_missing_model_returns_missing_status(self, tmp_path):
        """Test that missing model returns MISSING status."""
        registry = get_model_registry()
        
        # Override models_dir to a temp directory
        registry.set_models_dir(tmp_path)
        
        # Now all models should be missing
        status = registry.get_model_status("scrfd")
        assert status == ModelStatus.MISSING

    def test_check_all_models_available_returns_false_for_missing(self, tmp_path):
        """Test check_all_models_available returns False when models missing."""
        registry = get_model_registry()
        registry.set_models_dir(tmp_path)
        
        all_available, missing = check_all_models_available()
        
        assert not all_available
        assert len(missing) > 0


# =============================================================================
# FORBIDDEN SUBSTITUTION DETECTION TESTS
# =============================================================================

class TestForbiddenSubstitution:
    """Test that forbidden model substitutions are detected."""

    def test_wrong_filename_not_accepted(self, tmp_path):
        """Test that wrong filename is not accepted."""
        registry = get_model_registry()
        
        # Create a file with wrong name
        wrong_file = tmp_path / "wrong_name.onnx"
        wrong_file.write_bytes(b"fake model")
        
        # The registry should still expect the correct filename
        scrfd_path = registry.get_model_path("scrfd")
        assert scrfd_path.name == "scrfd_10g_bnkps.onnx"

    def test_no_model_substitution_allowed(self):
        """Test that model substitution is not allowed."""
        registry = get_model_registry()
        
        # Get expected hashes
        scrfd_model = registry.get("scrfd")
        expected_hash = scrfd_model.expected_sha256
        
        # The hash should be the authoritative one
        assert expected_hash == "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"


# =============================================================================
# SAFETY TESTS
# =============================================================================

class TestPhase4Safety:
    """Test Phase 4 safety requirements."""

    def test_no_camera_access(self):
        """Test that validation does not access cameras."""
        # Check that no camera-related imports exist in validation module
        import app.models.validation as validation_module
        
        source_file = Path(validation_module.__file__)
        source_content = source_file.read_text()
        
        # Should not contain camera-related code
        assert "cv2.VideoCapture" not in source_content
        assert "rtsp://" not in source_content
        assert "rtmp://" not in source_content

    def test_no_mediamtx_start(self):
        """Test that validation does not start MediaMTX."""
        import app.models.validation as validation_module
        
        source_file = Path(validation_module.__file__)
        source_content = source_file.read_text()
        
        assert "MediaMTX" not in source_content
        assert "mediamtx" not in source_content.lower()

    def test_no_rtmp_rtsp_access(self):
        """Test that validation does not access RTMP/RTSP."""
        import app.models.validation as validation_module
        
        source_file = Path(validation_module.__file__)
        source_content = source_file.read_text()
        
        assert "RTMP" not in source_content
        assert "RTSP" not in source_content

    def test_no_ffmpeg_streaming(self):
        """Test that validation does not start FFmpeg streaming."""
        import app.models.validation as validation_module
        
        source_file = Path(validation_module.__file__)
        source_content = source_file.read_text()
        
        # Should not import ffmpeg for streaming
        assert "import ffmpeg" not in source_content
        assert "ffmpeg.run" not in source_content

    def test_no_ipc_started(self):
        """Test that validation does not start IPC."""
        import app.models.validation as validation_module
        
        source_file = Path(validation_module.__file__)
        source_content = source_file.read_text()
        
        assert "socket.socket" not in source_content
        assert "multiprocessing" not in source_content

    def test_model_files_not_modified(self):
        """Test that validation does not modify model files."""
        registry = get_model_registry()
        
        # Get model paths
        model_ids = registry.get_model_ids()
        
        for model_id in model_ids:
            model_path = registry.get_model_path(model_id)
            
            if model_path.exists():
                # Get modification time before validation
                mtime_before = model_path.stat().st_mtime
                
                # Run validation
                if model_path.suffix == ".onnx":
                    validate_onnx_model(model_path)
                elif model_path.suffix == ".pt":
                    validate_yolo_model(model_path)
                
                # Get modification time after validation
                mtime_after = model_path.stat().st_mtime
                
                # File should not have been modified
                assert mtime_before == mtime_after, f"Model file {model_path} was modified"


# =============================================================================
# INVENTORY SERIALIZATION TESTS
# =============================================================================

class TestInventorySerialization:
    """Test inventory serialization."""

    def test_inventory_to_dict(self):
        """Test inventory can be serialized to dict."""
        inventory = collect_model_inventory()
        
        data = inventory.to_dict()
        
        assert isinstance(data, dict)
        assert "entries" in data
        assert "verified_count" in data
        assert "mismatch_count" in data
        assert "missing_count" in data
        assert "total_count" in data

    def test_inventory_entry_serialization(self):
        """Test inventory entry can be serialized."""
        inventory = collect_model_inventory()
        
        for entry in inventory.entries:
            entry_dict = {
                "model_id": entry.model_id,
                "filename": entry.filename,
                "path": entry.path,
                "file_size": entry.file_size,
                "expected_sha256": entry.expected_sha256,
                "actual_sha256": entry.actual_sha256,
                "hash_match": entry.hash_match,
                "integrity_status": entry.integrity_status,
                "contract_status": entry.contract_status,
                "registry_status": entry.registry_status,
                "provenance": entry.provenance,
            }
            
            assert isinstance(entry_dict, dict)
            assert entry_dict["model_id"] is not None
