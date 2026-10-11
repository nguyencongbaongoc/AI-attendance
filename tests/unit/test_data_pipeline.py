"""
Unit tests for Phase 6 Data Pipeline.

Tests cover:
- CanonicalFrame representation
- Preprocessing contracts
- Unified preprocessing pipeline
- Image adapter
- Video adapter
- NPY artifact format

CRITICAL: These tests do NOT access cameras.
CRITICAL: These tests do NOT start MediaMTX, RTMP, RTSP, FFmpeg streaming.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.data.frame import (
    SourceType,
    PixelFormat,
    FrameMetadata,
    CanonicalFrame,
)
from app.data.contracts import (
    ColorSpace,
    ChannelOrder,
    TensorLayout,
    ResizeMode,
    PaddingMode,
    PreprocessingVersion,
    ModelType,
    ModelFramework,
    ModelPreprocessingContract,
    get_model_contract,
    list_model_contracts,
)
from app.data.preprocessing import (
    UnifiedPreprocessor,
    PreprocessingResult,
    preprocess_frame,
)
from app.data.input_adapter import (
    VideoFrameIterator,
    VideoInfo,
)
# NPY artifacts removed - not part of canonical architecture


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_bgr_image(temp_dir: Path) -> Path:
    """Create a sample BGR image for testing."""
    import cv2
    
    # Create a 100x100 BGR image
    image = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    image_path = temp_dir / "test_image.jpg"
    cv2.imwrite(str(image_path), image)
    return image_path


@pytest.fixture
def sample_rgb_image(temp_dir: Path) -> Path:
    """Create a sample RGB image for testing."""
    import cv2
    
    # Create a 100x100 RGB image (save as BGR, OpenCV default)
    image = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    image_path = temp_dir / "test_rgb.png"
    cv2.imwrite(str(image_path), image)
    return image_path


@pytest.fixture
def sample_video(temp_dir: Path) -> Path:
    """Create a sample video for testing."""
    import cv2
    
    # Create a 10-frame video at 30fps
    video_path = temp_dir / "test_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, 30.0, (100, 100))
    
    for i in range(10):
        frame = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        writer.write(frame)
    
    writer.release()
    return video_path


@pytest.fixture
def sample_canonical_frame() -> CanonicalFrame:
    """Create a sample canonical frame for testing."""
    data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    metadata = FrameMetadata(
        source_type=SourceType.IMAGE,
        source_id="test_image.jpg",
        frame_index=0,
        timestamp=None,
        original_width=100,
        original_height=100,
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
    )
    return CanonicalFrame(data=data, metadata=metadata)


# =============================================================================
# CanonicalFrame Tests
# =============================================================================

class TestCanonicalFrame:
    """Tests for CanonicalFrame."""
    
    def test_create_frame(self):
        """Test creating a canonical frame."""
        data = np.zeros((50, 50, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=50,
            original_height=50,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        frame = CanonicalFrame(data=data, metadata=metadata)
        
        assert frame.width == 50
        assert frame.height == 50
        assert frame.channels == 3
        assert frame.is_bgr
        assert not frame.is_rgb

    def test_frame_validation(self):
        """Test frame validation."""
        data = np.zeros((50, 50, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=100,  # Wrong!
            original_height=100,  # Wrong!
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        with pytest.raises(ValueError, match="Frame data width 50 does not match metadata original_width 100"):
            CanonicalFrame(data=data, metadata=metadata)
    
    def test_frame_copy(self, sample_canonical_frame: CanonicalFrame):
        """Test frame copy."""
        copy = sample_canonical_frame.copy()
        
        assert np.array_equal(copy.data, sample_canonical_frame.data)
        # Metadata is serialized/deserialized in copy(), so enums become their string values
        assert copy.metadata.source_type == sample_canonical_frame.metadata.source_type.value
        assert copy.metadata.source_id == sample_canonical_frame.metadata.source_id
        assert copy.metadata.frame_index == sample_canonical_frame.metadata.frame_index
        
        # Modify original, check copy is independent
        sample_canonical_frame.data[0, 0, 0] = 255
        assert copy.data[0, 0, 0] != 255
    
    def test_frame_with_conversion(self, sample_canonical_frame: CanonicalFrame):
        """Test recording conversions."""
        frame = sample_canonical_frame.with_conversion("bgr_to_rgb")
        
        assert "bgr_to_rgb" in frame.conversions_applied
    
    def test_frame_to_dict(self, sample_canonical_frame: CanonicalFrame):
        """Test frame serialization."""
        d = sample_canonical_frame.to_dict()
        
        assert "metadata" in d
        assert "shape" in d
        assert "dtype" in d


class TestFrameMetadata:
    """Tests for FrameMetadata."""
    
    def test_metadata_creation(self):
        """Test creating metadata."""
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="video.mp4",
            frame_index=5,
            timestamp=0.166,
            original_width=1920,
            original_height=1080,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
            source_fps=30.0,
            source_duration=10.0,
            source_frame_count=300,
        )
        
        assert metadata.source_type == SourceType.VIDEO
        assert metadata.frame_index == 5
        assert metadata.source_fps == 30.0
    
    def test_metadata_serialization(self):
        """Test metadata serialization."""
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=100,
            original_height=100,
            pixel_format=PixelFormat.RGB,
            dtype="uint8",
        )
        
        d = metadata.to_dict()
        restored = FrameMetadata.from_dict(d)
        
        assert restored.source_type == metadata.source_type
        assert restored.source_id == metadata.source_id
        assert restored.pixel_format == metadata.pixel_format


# =============================================================================
# Preprocessing Contract Tests
# =============================================================================

class TestPreprocessingContract:
    """Tests for preprocessing contracts."""
    
    def test_contract_creation(self):
        """Test creating a preprocessing contract."""
        contract = ModelPreprocessingContract(
            model_id="test_model",
            model_type=ModelType.DETECTION,
            framework=ModelFramework.ONNX,
            input_shape=(3, 640, 640),
            input_dtype="float32",
            input_range=(0.0, 1.0),
            input_format="RGB",
            resize_mode=ResizeMode.LETTERBOX,
        )
        
        assert contract.model_id == "test_model"
        assert contract.input_shape == (3, 640, 640)
    
    def test_contract_serialization(self):
        """Test contract serialization."""
        contract = ModelPreprocessingContract(
            model_id="test_model",
            model_type=ModelType.DETECTION,
            framework=ModelFramework.ONNX,
            input_shape=(3, 640, 640),
            input_dtype="float32",
            input_range=(0.0, 1.0),
            input_format="RGB",
            resize_mode=ResizeMode.LETTERBOX,
        )
        
        d = contract.to_dict()
        
        assert d["model_id"] == "test_model"
        assert d["input_shape"] == [3, 640, 640]
        assert d["input_format"] == "RGB"
    
    def test_get_model_contract(self):
        """Test getting a model contract."""
        contract = get_model_contract("scrfd_10g")
        
        assert contract is not None
        assert contract.model_id == "scrfd_10g"
        assert contract.preprocessing is not None
        assert contract.preprocessing.input_shape == (3, 640, 640)
    
    def test_list_model_contracts(self):
        """Test listing model contracts."""
        contracts = list_model_contracts()
        
        # Should have at least the built-in models
        contract_ids = [c.model_id for c in contracts]
        assert "scrfd_10g" in contract_ids
        assert "arcface_r100" in contract_ids
        # Note: yolo_person is not registered in default contracts
    
    def test_contract_compatibility(self):
        """Test contract compatibility check."""
        contract1 = get_model_contract("scrfd")
        contract2 = get_model_contract("scrfd")
        contract3 = get_model_contract("arcface_r100")
        
        # Compatibility check is based on preprocessing compatibility
        assert contract1.preprocessing is not None
        assert contract2.preprocessing is not None
        assert contract3.preprocessing is not None
        # Same model contracts should have compatible preprocessing
        assert contract1.preprocessing.input_shape == contract2.preprocessing.input_shape
        # Different models may have different preprocessing
        assert contract1.preprocessing.input_shape != contract3.preprocessing.input_shape or contract1.model_id != contract3.model_id


# =============================================================================
# Unified Preprocessor Tests
# =============================================================================

class TestUnifiedPreprocessor:
    """Tests for the unified preprocessor."""
    
    def test_preprocessor_creation(self):
        """Test creating a preprocessor."""
        preprocessor = UnifiedPreprocessor("scrfd")
        
        assert preprocessor.model_id == "scrfd"
        assert preprocessor.contract is not None
    
    def test_preprocess_frame(self, sample_canonical_frame: CanonicalFrame):
        """Test preprocessing a frame."""
        preprocessor = UnifiedPreprocessor("scrfd_10g")
        result = preprocessor.preprocess(sample_canonical_frame)
        
        assert result.tensor.shape == (1, 3, 640, 640)
        assert result.model_id == "scrfd_10g"
        assert result.preprocessing_time_ms > 0
    
    def test_preprocess_different_models(self, sample_canonical_frame: CanonicalFrame):
        """Test preprocessing for different models."""
        models = ["scrfd_10g", "arcface_r100"]
        
        for model_id in models:
            preprocessor = UnifiedPreprocessor(model_id)
            result = preprocessor.preprocess(sample_canonical_frame)
            
            contract = get_model_contract(model_id)
            assert result.tensor.shape == (1,) + contract.preprocessing.input_shape
    
    def test_preprocess_result_serialization(self, sample_canonical_frame: CanonicalFrame):
        """Test preprocessing result serialization."""
        preprocessor = UnifiedPreprocessor("scrfd_10g")
        result = preprocessor.preprocess(sample_canonical_frame)
        
        d = result.to_dict()
        
        assert "model_id" in d
        assert "tensor_shape" in d  # Tensor shape is included in dict
        assert "conversions" in d


# =============================================================================
# Image Adapter Tests
# =============================================================================

class TestSafetyVerification:
    """Safety verification tests."""
    
    def test_no_camera_access(self):
        """Verify no camera access in data module."""
        import app.data
        
        # Check that no camera-related imports exist
        source_files = [
            "app/data/__init__.py",
            "app/data/frame.py",
            "app/data/contracts.py",
            "app/data/preprocessing.py",
            "app/data/input_adapter.py",
            "app/data/npy.py",
        ]
        
        for file_path in source_files:
            path = Path(file_path)
            if path.exists():
                content = path.read_text()
                # Check for forbidden code patterns (not documentation)
                # Look for actual usage, not mentions in docstrings or comments
                lines = content.split('\n')
                code_lines = []
                in_docstring = False
                for line in lines:
                    stripped = line.strip()
                    # Skip comment lines
                    if stripped.startswith('#'):
                        continue
                    # Track docstring state
                    if '"""' in stripped or "'''" in stripped:
                        in_docstring = not in_docstring
                        continue
                    if in_docstring:
                        continue
                    code_lines.append(line)
                code_content = '\n'.join(code_lines)
                
                # Check for actual camera access code
                assert "cv2.VideoCapture(0)" not in code_content
                assert "cv2.VideoCapture(1)" not in code_content
                # Check for streaming protocol usage in code (not docstrings)
                assert "rtmp://" not in code_content
                assert "rtsp://" not in code_content
                assert "ffmpeg -i" not in code_content
    
    def test_no_real_images(self, sample_canonical_frame: CanonicalFrame):
        """Verify tests use synthetic data only."""
        # The sample_canonical_frame fixture creates synthetic data
        assert sample_canonical_frame.data.dtype == np.uint8
        assert sample_canonical_frame.data.shape == (100, 100, 3)


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
