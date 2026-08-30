"""
Unit tests for the model registry module.

Tests:
- Registry lookup
- Unknown model rejection
- All six model IDs registered
- Filename resolution
- Model path resolution
- Expected SHA256 metadata
- Missing model detection
- Hash mismatch detection
- Verified model detection
- Input shape metadata
- Output contract metadata
- Embedding dimensions
- SCRFD contract
- Model version metadata
- Dataset compatibility metadata

Tests do NOT:
- Start MediaMTX
- Start FFmpeg
- Access a camera
- Perform live inference
- Modify model weights
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.contracts import (
    ModelDefinition,
    ModelFormat,
    ModelProvider,
    ModelStatus,
    HashStatus,
    PreprocessingConfig,
    OutputContract,
    ThresholdsConfig,
    ModelVersion,
    DatasetCompatibility,
)
from app.models.exceptions import (
    ModelError,
    ModelNotFoundError,
    ModelMissingError,
    ModelHashMismatchError,
    ModelNotVerifiedError,
)
from app.models.hashing import compute_sha256, verify_sha256, HashResult
from app.models.registry import (
    ModelRegistry,
    get_model_registry,
    SCRFD_REFERENCE_SHA256,
    ARCFACE_REFERENCE_SHA256,
    LANDMARK_1K3D68_REFERENCE_SHA256,
    REID_REFERENCE_SHA256,
    YOLO11N_REFERENCE_SHA256,
    YOLO11N_POSE_REFERENCE_SHA256,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton registry before each test."""
    ModelRegistry.reset()
    yield
    ModelRegistry.reset()


@pytest.fixture
def registry():
    """Get a fresh ModelRegistry instance."""
    return ModelRegistry()


@pytest.fixture
def temp_models_dir():
    """Create a temporary models directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        models_dir = Path(tmpdir) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        yield models_dir


@pytest.fixture
def temp_model_file(temp_models_dir):
    """Create a temporary model file for testing hash verification."""
    def _create_model_file(model_id: str, content: bytes = b"test model content") -> Path:
        registry = ModelRegistry()
        model = registry.get(model_id)
        model_path = temp_models_dir / model.subdirectory / model.filename
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_bytes(content)
        return model_path
    return _create_model_file


# =============================================================================
# REGISTRY LOOKUP TESTS
# =============================================================================

class TestRegistryLookup:
    """Tests for registry lookup functionality."""
    
    def test_get_scrfd_model(self, registry):
        """Test getting SCRFD model by ID."""
        model = registry.get("scrfd")
        assert model is not None
        assert model.model_id == "scrfd"
        assert model.display_name == "SCRFD Face Detector"
    
    def test_get_arcface_model(self, registry):
        """Test getting ArcFace model by ID."""
        model = registry.get("arcface")
        assert model is not None
        assert model.model_id == "arcface"
        assert model.display_name == "ArcFace Face Recognition"
    
    def test_get_landmark_model(self, registry):
        """Test getting landmark model by ID."""
        model = registry.get("landmark_1k3d68")
        assert model is not None
        assert model.model_id == "landmark_1k3d68"
        assert model.display_name == "1K3D68 Face Landmark"
    
    def test_get_reid_model(self, registry):
        """Test getting ReID model by ID."""
        model = registry.get("reid")
        assert model is not None
        assert model.model_id == "reid"
        assert model.display_name == "ResNet50 ReID"
    
    def test_get_yolo_person_model(self, registry):
        """Test getting YOLO person model by ID."""
        model = registry.get("yolo_person")
        assert model is not None
        assert model.model_id == "yolo_person"
        assert model.display_name == "YOLO11n Person Detector"
    
    def test_get_yolo_pose_model(self, registry):
        """Test getting YOLO pose model by ID."""
        model = registry.get("yolo_pose")
        assert model is not None
        assert model.model_id == "yolo_pose"
        assert model.display_name == "YOLO11n-Pose"


# =============================================================================
# UNKNOWN MODEL REJECTION TESTS
# =============================================================================

class TestUnknownModelRejection:
    """Tests for rejecting unknown models."""
    
    def test_get_unknown_model_raises_error(self, registry):
        """Test that getting an unknown model raises ModelNotFoundError."""
        with pytest.raises(ModelNotFoundError) as exc_info:
            registry.get("unknown_model")
        assert "unknown_model" in str(exc_info.value)
    
    def test_is_registered_returns_false_for_unknown(self, registry):
        """Test that is_registered returns False for unknown models."""
        assert registry.is_registered("unknown_model") is False
    
    def test_verify_unknown_model_raises_error(self, registry):
        """Test that verifying an unknown model raises ModelNotFoundError."""
        with pytest.raises(ModelNotFoundError):
            registry.verify_model("unknown_model")


# =============================================================================
# ALL SIX MODELS REGISTERED TESTS
# =============================================================================

class TestAllModelsRegistered:
    """Tests for verifying all six models are registered."""
    
    def test_all_six_models_registered(self, registry):
        """Test that all six production models are registered."""
        model_ids = registry.get_model_ids()
        assert len(model_ids) == 6
        assert "scrfd" in model_ids
        assert "arcface" in model_ids
        assert "landmark_1k3d68" in model_ids
        assert "reid" in model_ids
        assert "yolo_person" in model_ids
        assert "yolo_pose" in model_ids
    
    def test_get_all_models_returns_six(self, registry):
        """Test that get_all_models returns all six models."""
        models = registry.get_all_models()
        assert len(models) == 6
    
    def test_is_registered_for_all_models(self, registry):
        """Test that is_registered returns True for all six models."""
        for model_id in ["scrfd", "arcface", "landmark_1k3d68", "reid", "yolo_person", "yolo_pose"]:
            assert registry.is_registered(model_id) is True


# =============================================================================
# FILENAME RESOLUTION TESTS
# =============================================================================

class TestFilenameResolution:
    """Tests for filename resolution."""
    
    def test_scrfd_filename(self, registry):
        """Test SCRFD filename resolution."""
        model = registry.get("scrfd")
        assert model.filename == "scrfd_10g_bnkps.onnx"
    
    def test_arcface_filename(self, registry):
        """Test ArcFace filename resolution."""
        model = registry.get("arcface")
        assert model.filename == "glintr100.onnx"
    
    def test_landmark_filename(self, registry):
        """Test landmark filename resolution."""
        model = registry.get("landmark_1k3d68")
        assert model.filename == "1k3d68.onnx"
    
    def test_reid_filename(self, registry):
        """Test ReID filename resolution."""
        model = registry.get("reid")
        assert model.filename == "resnet50_reid.onnx"
    
    def test_yolo_person_filename(self, registry):
        """Test YOLO person filename resolution."""
        model = registry.get("yolo_person")
        assert model.filename == "yolo11n.pt"
    
    def test_yolo_pose_filename(self, registry):
        """Test YOLO pose filename resolution."""
        model = registry.get("yolo_pose")
        assert model.filename == "yolo11n-pose.pt"


# =============================================================================
# MODEL PATH RESOLUTION TESTS
# =============================================================================

class TestModelPathResolution:
    """Tests for model path resolution."""
    
    def test_scrfd_path_resolution(self, registry, temp_models_dir):
        """Test SCRFD path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("scrfd")
        expected = (temp_models_dir / "scrfd" / "scrfd_10g_bnkps.onnx").resolve()
        assert path.resolve() == expected
    
    def test_arcface_path_resolution(self, registry, temp_models_dir):
        """Test ArcFace path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("arcface")
        expected = (temp_models_dir / "arcface" / "glintr100.onnx").resolve()
        assert path.resolve() == expected
    
    def test_landmark_path_resolution(self, registry, temp_models_dir):
        """Test landmark path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("landmark_1k3d68")
        expected = (temp_models_dir / "landmark" / "1k3d68.onnx").resolve()
        assert path.resolve() == expected
    
    def test_reid_path_resolution(self, registry, temp_models_dir):
        """Test ReID path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("reid")
        expected = (temp_models_dir / "reid" / "resnet50_reid.onnx").resolve()
        assert path.resolve() == expected
    
    def test_yolo_person_path_resolution(self, registry, temp_models_dir):
        """Test YOLO person path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("yolo_person")
        expected = (temp_models_dir / "yolo" / "yolo11n.pt").resolve()
        assert path.resolve() == expected
    
    def test_yolo_pose_path_resolution(self, registry, temp_models_dir):
        """Test YOLO pose path resolution."""
        registry.set_models_dir(temp_models_dir)
        path = registry.get_model_path("yolo_pose")
        expected = (temp_models_dir / "yolo" / "yolo11n-pose.pt").resolve()
        assert path.resolve() == expected


# =============================================================================
# EXPECTED SHA256 METADATA TESTS
# =============================================================================

class TestExpectedSHA256:
    """Tests for expected SHA256 metadata."""
    
    def test_scrfd_expected_sha256(self, registry):
        """Test SCRFD has expected SHA256."""
        model = registry.get("scrfd")
        assert model.expected_sha256 == SCRFD_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64  # SHA256 is 64 hex chars
    
    def test_arcface_expected_sha256(self, registry):
        """Test ArcFace has expected SHA256."""
        model = registry.get("arcface")
        assert model.expected_sha256 == ARCFACE_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64
    
    def test_landmark_expected_sha256(self, registry):
        """Test landmark has expected SHA256."""
        model = registry.get("landmark_1k3d68")
        assert model.expected_sha256 == LANDMARK_1K3D68_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64
    
    def test_reid_expected_sha256(self, registry):
        """Test ReID has expected SHA256."""
        model = registry.get("reid")
        assert model.expected_sha256 == REID_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64
    
    def test_yolo_person_expected_sha256(self, registry):
        """Test YOLO person has expected SHA256."""
        model = registry.get("yolo_person")
        assert model.expected_sha256 == YOLO11N_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64
    
    def test_yolo_pose_expected_sha256(self, registry):
        """Test YOLO pose has expected SHA256."""
        model = registry.get("yolo_pose")
        assert model.expected_sha256 == YOLO11N_POSE_REFERENCE_SHA256
        assert len(model.expected_sha256) == 64


# =============================================================================
# MISSING MODEL DETECTION TESTS
# =============================================================================

class TestMissingModelDetection:
    """Tests for detecting missing model files."""
    
    def test_missing_model_returns_missing_status(self, registry, temp_models_dir):
        """Test that missing model returns MISSING status."""
        registry.set_models_dir(temp_models_dir)
        status = registry.get_model_status("scrfd")
        assert status == ModelStatus.MISSING
    
    def test_missing_model_verify_returns_missing(self, registry, temp_models_dir):
        """Test that verify_model returns MISSING for missing file."""
        registry.set_models_dir(temp_models_dir)
        result = registry.verify_model("scrfd")
        assert result.is_missing()
        assert result.status == HashStatus.MISSING
    
    def test_get_missing_models(self, registry, temp_models_dir):
        """Test getting list of missing models."""
        registry.set_models_dir(temp_models_dir)
        missing = registry.get_missing_models()
        # All models should be missing in empty temp directory
        assert len(missing) == 6


# =============================================================================
# HASH MISMATCH DETECTION TESTS
# =============================================================================

class TestHashMismatchDetection:
    """Tests for detecting hash mismatches."""
    
    def test_hash_mismatch_detected(self, registry, temp_models_dir, temp_model_file):
        """Test that hash mismatch is detected."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file with wrong content
        temp_model_file("scrfd", b"wrong content")
        
        result = registry.verify_model("scrfd")
        assert result.is_mismatch()
        assert result.status == HashStatus.HASH_MISMATCH
        assert result.actual_hash != result.expected_hash
    
    def test_hash_mismatch_status_corrupt(self, registry, temp_models_dir, temp_model_file):
        """Test that hash mismatch results in CORRUPT status."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file with wrong content
        temp_model_file("arcface", b"wrong content")
        
        status = registry.get_model_status("arcface")
        assert status == ModelStatus.CORRUPT


# =============================================================================
# VERIFIED MODEL DETECTION TESTS
# =============================================================================

class TestVerifiedModelDetection:
    """Tests for detecting verified models."""
    
    def test_verified_model_with_correct_hash(self, registry, temp_models_dir, temp_model_file):
        """Test that model with correct hash is verified."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file with known content
        content = b"test model content for verification"
        expected_hash = hashlib.sha256(content).hexdigest()
        
        # Patch the expected hash
        model = registry.get("scrfd")
        model.expected_sha256 = expected_hash
        
        # Create the file
        temp_model_file("scrfd", content)
        
        result = registry.verify_model("scrfd")
        assert result.is_verified()
        assert result.status == HashStatus.VERIFIED
    
    def test_verified_model_status_available(self, registry, temp_models_dir, temp_model_file):
        """Test that verified model has AVAILABLE status."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file with known content
        content = b"test model content for verification"
        expected_hash = hashlib.sha256(content).hexdigest()
        
        # Patch the expected hash
        model = registry.get("arcface")
        model.expected_sha256 = expected_hash
        
        # Create the file
        temp_model_file("arcface", content)
        
        status = registry.get_model_status("arcface")
        assert status == ModelStatus.AVAILABLE
    
    def test_get_available_models(self, registry, temp_models_dir, temp_model_file):
        """Test getting list of available models."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a verified file for one model
        content = b"test model content"
        expected_hash = hashlib.sha256(content).hexdigest()
        
        model = registry.get("scrfd")
        model.expected_sha256 = expected_hash
        temp_model_file("scrfd", content)
        
        available = registry.get_available_models()
        assert "scrfd" in available
        assert len(available) == 1


# =============================================================================
# INPUT SHAPE METADATA TESTS
# =============================================================================

class TestInputShapeMetadata:
    """Tests for input shape metadata."""
    
    def test_scrfd_input_shape(self, registry):
        """Test SCRFD input shape."""
        model = registry.get("scrfd")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 960, 960)
    
    def test_arcface_input_shape(self, registry):
        """Test ArcFace input shape."""
        model = registry.get("arcface")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 112, 112)
    
    def test_landmark_input_shape(self, registry):
        """Test landmark input shape."""
        model = registry.get("landmark_1k3d68")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 192, 192)
    
    def test_reid_input_shape(self, registry):
        """Test ReID input shape."""
        model = registry.get("reid")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 256, 128)
    
    def test_yolo_person_input_shape(self, registry):
        """Test YOLO person input shape."""
        model = registry.get("yolo_person")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 640, 640)
    
    def test_yolo_pose_input_shape(self, registry):
        """Test YOLO pose input shape."""
        model = registry.get("yolo_pose")
        shape = model.preprocessing.get_input_shape()
        assert shape == (1, 3, 640, 640)


# =============================================================================
# OUTPUT CONTRACT METADATA TESTS
# =============================================================================

class TestOutputContractMetadata:
    """Tests for output contract metadata."""
    
    def test_scrfd_output_type(self, registry):
        """Test SCRFD output type."""
        model = registry.get("scrfd")
        assert model.output_contract.output_type == "detection"
        assert model.output_contract.num_keypoints == 5
    
    def test_arcface_output_type(self, registry):
        """Test ArcFace output type."""
        model = registry.get("arcface")
        assert model.output_contract.output_type == "embedding"
    
    def test_landmark_output_type(self, registry):
        """Test landmark output type."""
        model = registry.get("landmark_1k3d68")
        assert model.output_contract.output_type == "landmarks"
        assert model.output_contract.num_landmarks == 68
    
    def test_reid_output_type(self, registry):
        """Test ReID output type."""
        model = registry.get("reid")
        assert model.output_contract.output_type == "embedding"
    
    def test_yolo_person_output_type(self, registry):
        """Test YOLO person output type."""
        model = registry.get("yolo_person")
        assert model.output_contract.output_type == "detection"
    
    def test_yolo_pose_output_type(self, registry):
        """Test YOLO pose output type."""
        model = registry.get("yolo_pose")
        assert model.output_contract.output_type == "pose"
        assert model.output_contract.pose_keypoints == 17


# =============================================================================
# EMBEDDING DIMENSION TESTS
# =============================================================================

class TestEmbeddingDimensions:
    """Tests for embedding dimension metadata."""
    
    def test_arcface_embedding_dimension(self, registry):
        """Test ArcFace embedding dimension."""
        model = registry.get("arcface")
        assert model.output_contract.embedding_dimension == 512
    
    def test_reid_embedding_dimension(self, registry):
        """Test ReID embedding dimension."""
        model = registry.get("reid")
        assert model.output_contract.embedding_dimension == 2048
    
    def test_scrfd_no_embedding_dimension(self, registry):
        """Test SCRFD has no embedding dimension (detection model)."""
        model = registry.get("scrfd")
        assert model.output_contract.embedding_dimension is None
    
    def test_get_embedding_models(self, registry):
        """Test getting list of embedding models."""
        embedding_models = registry.get_embedding_models()
        assert "arcface" in embedding_models
        assert "reid" in embedding_models
        assert len(embedding_models) == 2
    
    def test_get_detection_models(self, registry):
        """Test getting list of detection models."""
        detection_models = registry.get_detection_models()
        assert "scrfd" in detection_models
        assert "yolo_person" in detection_models
        assert len(detection_models) == 2


# =============================================================================
# SCRFD CONTRACT TESTS
# =============================================================================

class TestSCRFDContract:
    """Tests for SCRFD model contract."""
    
    def test_scrfd_thresholds(self, registry):
        """Test SCRFD thresholds."""
        model = registry.get("scrfd")
        assert model.thresholds is not None
        assert model.thresholds.confidence_threshold == 0.55
        assert model.thresholds.nms_threshold == 0.45
    
    def test_scrfd_format(self, registry):
        """Test SCRFD format."""
        model = registry.get("scrfd")
        assert model.format == ModelFormat.ONNX
    
    def test_scrfd_provider(self, registry):
        """Test SCRFD provider."""
        model = registry.get("scrfd")
        assert model.provider == ModelProvider.ONNXRUNTIME
    
    def test_scrfd_preprocessing(self, registry):
        """Test SCRFD preprocessing config."""
        model = registry.get("scrfd")
        assert model.preprocessing.input_height == 960
        assert model.preprocessing.input_width == 960
        assert model.preprocessing.input_channels == 3
        assert model.preprocessing.channel_order == "RGB"
        assert model.preprocessing.dtype == "float32"
    
    def test_scrfd_is_required(self, registry):
        """Test SCRFD is marked as required."""
        model = registry.get("scrfd")
        assert model.required is True


# =============================================================================
# MODEL VERSION METADATA TESTS
# =============================================================================

class TestModelVersionMetadata:
    """Tests for model version metadata."""
    
    def test_scrfd_version(self, registry):
        """Test SCRFD version info."""
        model = registry.get("scrfd")
        assert model.version.version == "1.0.0"
        assert model.version.architecture == "scrfd_10g"
        assert model.version.source == "insightface"
        assert model.version.contract_version == "1.0"
        assert model.version.preprocessing_version == "1.0"
    
    def test_arcface_version(self, registry):
        """Test ArcFace version info."""
        model = registry.get("arcface")
        assert model.version.version == "1.0.0"
        assert model.version.architecture == "glintr100"
        assert model.version.source == "insightface"
    
    def test_all_models_have_version(self, registry):
        """Test all models have version info."""
        for model_id in registry.get_model_ids():
            model = registry.get(model_id)
            assert model.version is not None
            assert model.version.version is not None
            assert model.version.contract_version is not None
            assert model.version.preprocessing_version is not None


# =============================================================================
# DATASET COMPATIBILITY METADATA TESTS
# =============================================================================

class TestDatasetCompatibilityMetadata:
    """Tests for dataset compatibility metadata."""
    
    def test_get_dataset_compatibility(self, registry):
        """Test getting dataset compatibility metadata."""
        compatibility = registry.get_dataset_compatibility("scrfd")
        assert compatibility is not None
        assert compatibility.model_id == "scrfd"
        assert compatibility.model_version == "1.0.0"
        assert compatibility.preprocessing_version == "1.0"
        assert compatibility.contract_version == "1.0"
    
    def test_dataset_compatibility_embedding_dimension(self, registry):
        """Test dataset compatibility includes embedding dimension."""
        compatibility = registry.get_dataset_compatibility("arcface")
        assert compatibility.embedding_dimension == 512
        
        compatibility = registry.get_dataset_compatibility("reid")
        assert compatibility.embedding_dimension == 2048
    
    def test_dataset_compatibility_to_dict(self, registry):
        """Test dataset compatibility serialization."""
        compatibility = registry.get_dataset_compatibility("scrfd")
        data = compatibility.to_dict()
        assert "model_id" in data
        assert "model_version" in data
        assert "preprocessing_version" in data
        assert "contract_version" in data
    
    def test_dataset_compatibility_is_compatible(self, registry):
        """Test dataset compatibility comparison."""
        compat1 = registry.get_dataset_compatibility("arcface")
        compat2 = registry.get_dataset_compatibility("arcface")
        assert compat1.is_compatible_with(compat2)
        
        compat3 = registry.get_dataset_compatibility("reid")
        assert not compat1.is_compatible_with(compat3)


# =============================================================================
# MODEL FORMAT AND PROVIDER TESTS
# =============================================================================

class TestModelFormatAndProvider:
    """Tests for model format and provider."""
    
    def test_onnx_models(self, registry):
        """Test ONNX models have correct format."""
        onnx_models = ["scrfd", "arcface", "landmark_1k3d68", "reid"]
        for model_id in onnx_models:
            model = registry.get(model_id)
            assert model.format == ModelFormat.ONNX
            assert model.provider == ModelProvider.ONNXRUNTIME
    
    def test_pytorch_models(self, registry):
        """Test PyTorch models have correct format."""
        pytorch_models = ["yolo_person", "yolo_pose"]
        for model_id in pytorch_models:
            model = registry.get(model_id)
            assert model.format == ModelFormat.PYTORCH
            assert model.provider == ModelProvider.ULTRALYTICS


# =============================================================================
# REQUIRED MODELS TESTS
# =============================================================================

class TestRequiredModels:
    """Tests for required models."""
    
    def test_get_required_models(self, registry):
        """Test getting list of required models."""
        required = registry.get_required_models()
        assert "scrfd" in required
        assert "arcface" in required
    
    def test_scrfd_is_required(self, registry):
        """Test SCRFD is required."""
        model = registry.get("scrfd")
        assert model.required is True
    
    def test_arcface_is_required(self, registry):
        """Test ArcFace is required."""
        model = registry.get("arcface")
        assert model.required is True
    
    def test_landmark_not_required(self, registry):
        """Test landmark is not required."""
        model = registry.get("landmark_1k3d68")
        assert model.required is False


# =============================================================================
# HASH COMPUTATION TESTS
# =============================================================================

class TestHashComputation:
    """Tests for hash computation."""
    
    def test_compute_sha256(self, temp_models_dir):
        """Test SHA256 computation."""
        # Create a test file
        test_file = temp_models_dir / "test.txt"
        test_file.write_bytes(b"test content")
        
        # Compute hash
        hash_result = compute_sha256(test_file)
        
        # Verify hash
        assert hash_result is not None
        assert len(hash_result) == 64
    
    def test_compute_sha256_file_not_found(self, temp_models_dir):
        """Test SHA256 computation for missing file."""
        with pytest.raises(FileNotFoundError):
            compute_sha256(temp_models_dir / "nonexistent.txt")
    
    def test_verify_sha256_missing_file(self, temp_models_dir):
        """Test SHA256 verification for missing file."""
        result = verify_sha256(temp_models_dir / "nonexistent.txt", "expected_hash")
        assert result.is_missing()
    
    def test_verify_sha256_no_expected_hash(self, temp_models_dir):
        """Test SHA256 verification without expected hash."""
        test_file = temp_models_dir / "test.txt"
        test_file.write_bytes(b"test content")
        
        result = verify_sha256(test_file)
        assert result.status == HashStatus.NO_EXPECTED_HASH
        assert result.actual_hash is not None


# =============================================================================
# REGISTRY SERIALIZATION TESTS
# =============================================================================

class TestRegistrySerialization:
    """Tests for registry serialization."""
    
    def test_to_dict(self, registry, temp_models_dir):
        """Test registry serialization to dictionary."""
        registry.set_models_dir(temp_models_dir)
        data = registry.to_dict()
        
        assert "models_dir" in data
        assert "models" in data
        assert len(data["models"]) == 6
    
    def test_model_definition_serialization(self, registry):
        """Test model definition serialization."""
        model = registry.get("scrfd")
        data = model.model_dump()
        
        assert data["model_id"] == "scrfd"
        assert data["filename"] == "scrfd_10g_bnkps.onnx"
        assert "preprocessing" in data
        assert "output_contract" in data
        assert "version" in data


# =============================================================================
# SINGLETON TESTS
# =============================================================================

class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_singleton_returns_same_instance(self):
        """Test that singleton returns the same instance."""
        ModelRegistry.reset()
        registry1 = ModelRegistry()
        registry2 = ModelRegistry()
        assert registry1 is registry2
        ModelRegistry.reset()
    
    def test_get_model_registry_function(self):
        """Test get_model_registry function."""
        ModelRegistry.reset()
        registry = get_model_registry()
        assert isinstance(registry, ModelRegistry)
        ModelRegistry.reset()


# =============================================================================
# CHECK ALL MODELS TESTS
# =============================================================================

class TestCheckAllModels:
    """Tests for checking all models."""
    
    def test_check_all_models(self, registry, temp_models_dir):
        """Test checking all models."""
        registry.set_models_dir(temp_models_dir)
        results = registry.check_all_models()
        
        assert len(results) == 6
        for model_id in registry.get_model_ids():
            assert model_id in results
            assert results[model_id].is_missing()
    
    def test_compute_actual_hash(self, registry, temp_models_dir, temp_model_file):
        """Test computing actual hash."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file
        content = b"test content for hash"
        temp_model_file("scrfd", content)
        
        # Compute hash
        actual_hash = registry.compute_actual_hash("scrfd")
        expected_hash = hashlib.sha256(content).hexdigest()
        
        assert actual_hash == expected_hash
    
    def test_compute_actual_hash_missing_file(self, registry, temp_models_dir):
        """Test computing actual hash for missing file."""
        registry.set_models_dir(temp_models_dir)
        
        with pytest.raises(ModelMissingError):
            registry.compute_actual_hash("scrfd")
    
    def test_update_actual_hash(self, registry, temp_models_dir, temp_model_file):
        """Test updating actual hash."""
        registry.set_models_dir(temp_models_dir)
        
        # Create a file
        content = b"test content for update"
        temp_model_file("arcface", content)
        
        # Update hash
        actual_hash = registry.update_actual_hash("arcface")
        expected_hash = hashlib.sha256(content).hexdigest()
        
        assert actual_hash == expected_hash
        
        # Verify model has actual hash
        model = registry.get("arcface")
        assert model.actual_sha256 == expected_hash
    
    def test_update_actual_hash_missing_file(self, registry, temp_models_dir):
        """Test updating actual hash for missing file."""
        registry.set_models_dir(temp_models_dir)
        
        result = registry.update_actual_hash("arcface")
        assert result is None
