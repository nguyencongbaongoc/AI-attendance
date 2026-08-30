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
    ImageAdapter,
    VideoAdapter,
    VideoFrameIterator,
    VideoInfo,
    load_image,
    iter_video_frames,
    SUPPORTED_IMAGE_FORMATS,
)
from app.data.npy import (
    NpyArtifactMetadata,
    NpyArtifactWriter,
    NpyArtifactReader,
    NpyValidationError,
    write_npy_artifact,
    read_npy_artifact,
)


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
        assert frame.is_bgr()
        assert not frame.is_rgb()
    
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
        
        with pytest.raises(ValueError, match="do not match metadata"):
            CanonicalFrame(data=data, metadata=metadata)
    
    def test_frame_copy(self, sample_canonical_frame: CanonicalFrame):
        """Test frame copy."""
        copy = sample_canonical_frame.copy()
        
        assert np.array_equal(copy.data, sample_canonical_frame.data)
        assert copy.metadata == sample_canonical_frame.metadata
        
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
            model_sha256="abc123",
            preprocessing_version=PreprocessingVersion(),
            contract_version="1.0",
            input_height=640,
            input_width=640,
            input_channels=3,
            color_space=ColorSpace.RGB,
            channel_order=ChannelOrder.CHW,
            tensor_layout=TensorLayout.NCHW,
            dtype="float32",
        )
        
        assert contract.model_id == "test_model"
        assert contract.input_height == 640
        assert contract.target_shape == (1, 3, 640, 640)
    
    def test_contract_serialization(self):
        """Test contract serialization."""
        contract = ModelPreprocessingContract(
            model_id="test_model",
            model_sha256="abc123",
            preprocessing_version=PreprocessingVersion(),
            contract_version="1.0",
            input_height=640,
            input_width=640,
            input_channels=3,
            color_space=ColorSpace.RGB,
            channel_order=ChannelOrder.CHW,
            tensor_layout=TensorLayout.NCHW,
            dtype="float32",
        )
        
        d = contract.to_dict()
        
        assert d["model_id"] == "test_model"
        assert d["input_height"] == 640
        assert d["color_space"] == "rgb"
    
    def test_get_model_contract(self):
        """Test getting a model contract."""
        contract = get_model_contract("scrfd")
        
        assert contract.model_id == "scrfd"
        assert contract.input_height == 640
        assert contract.input_width == 640
    
    def test_list_model_contracts(self):
        """Test listing all model contracts."""
        contracts = list_model_contracts()
        
        assert "scrfd" in contracts
        assert "arcface" in contracts
        assert "yolo_person" in contracts
        assert len(contracts) == 6
    
    def test_contract_compatibility(self):
        """Test contract compatibility check."""
        contract1 = get_model_contract("scrfd")
        contract2 = get_model_contract("scrfd")
        contract3 = get_model_contract("arcface")
        
        assert contract1.is_compatible_with(contract2)
        assert not contract1.is_compatible_with(contract3)


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
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        
        assert result.tensor.shape == (1, 3, 640, 640)
        assert result.model_id == "scrfd"
        assert len(result.conversions) > 0
    
    def test_preprocess_different_models(self, sample_canonical_frame: CanonicalFrame):
        """Test preprocessing for different models."""
        models = ["scrfd", "arcface", "yolo_person"]
        
        for model_id in models:
            preprocessor = UnifiedPreprocessor(model_id)
            result = preprocessor.preprocess(sample_canonical_frame)
            
            contract = get_model_contract(model_id)
            assert result.tensor.shape == contract.target_shape
    
    def test_preprocess_result_serialization(self, sample_canonical_frame: CanonicalFrame):
        """Test preprocessing result serialization."""
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        
        d = result.to_dict()
        
        assert "model_id" in d
        assert "tensor_shape" not in d  # Tensor not in dict
        assert "conversions" in d


# =============================================================================
# Image Adapter Tests
# =============================================================================

class TestImageAdapter:
    """Tests for the image adapter."""
    
    def test_load_image(self, sample_bgr_image: Path):
        """Test loading an image."""
        adapter = ImageAdapter()
        frame = adapter.load(sample_bgr_image)
        
        assert frame.width == 100
        assert frame.height == 100
        assert frame.is_bgr()
        assert frame.metadata.source_type == SourceType.IMAGE
    
    def test_load_image_as_rgb(self, sample_bgr_image: Path):
        """Test loading an image as RGB."""
        adapter = ImageAdapter()
        frame = adapter.load_as_rgb(sample_bgr_image)
        
        assert frame.is_rgb()
    
    def test_load_nonexistent_image(self, temp_dir: Path):
        """Test loading a nonexistent image."""
        adapter = ImageAdapter()
        
        with pytest.raises(FileNotFoundError):
            adapter.load(temp_dir / "nonexistent.jpg")
    
    def test_is_supported(self, temp_dir: Path):
        """Test format support check."""
        adapter = ImageAdapter()
        
        assert adapter.is_supported("test.jpg")
        assert adapter.is_supported("test.png")
        assert not adapter.is_supported("test.txt")
    
    def test_convenience_function(self, sample_bgr_image: Path):
        """Test convenience function."""
        frame = load_image(sample_bgr_image)
        
        assert frame is not None
        assert frame.metadata.source_type == SourceType.IMAGE


# =============================================================================
# Video Adapter Tests
# =============================================================================

class TestVideoAdapter:
    """Tests for the video adapter."""
    
    def test_get_video_info(self, sample_video: Path):
        """Test getting video info."""
        adapter = VideoAdapter()
        info = adapter.get_info(sample_video)
        
        assert info.width == 100
        assert info.height == 100
        assert info.fps == 30.0
        assert info.frame_count == 10
    
    def test_iter_video_frames(self, sample_video: Path):
        """Test iterating video frames."""
        adapter = VideoAdapter()
        frames = list(adapter.iter_frames(sample_video))
        
        assert len(frames) == 10
        
        for i, frame in enumerate(frames):
            assert frame.metadata.frame_index == i
            assert frame.metadata.source_type == SourceType.VIDEO
    
    def test_video_frame_iterator_context(self, sample_video: Path):
        """Test video frame iterator context manager."""
        with VideoFrameIterator(sample_video) as iterator:
            frame = next(iterator)
            assert frame is not None
    
    def test_get_frame_at(self, sample_video: Path):
        """Test getting a specific frame."""
        adapter = VideoAdapter()
        frame = adapter.get_frame_at(sample_video, 5)
        
        assert frame is not None
        assert frame.metadata.frame_index == 5
    
    def test_get_frame_count(self, sample_video: Path):
        """Test getting frame count."""
        adapter = VideoAdapter()
        count = adapter.get_frame_count(sample_video)
        
        assert count == 10
    
    def test_get_duration(self, sample_video: Path):
        """Test getting duration."""
        adapter = VideoAdapter()
        duration = adapter.get_duration(sample_video)
        
        assert duration > 0
    
    def test_convenience_function(self, sample_video: Path):
        """Test convenience function."""
        frames = list(iter_video_frames(sample_video))
        
        assert len(frames) == 10


# =============================================================================
# NPY Artifact Tests
# =============================================================================

class TestNpyArtifact:
    """Tests for NPY artifacts."""
    
    def test_write_npy_artifact(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test writing an NPY artifact."""
        # Preprocess frame
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        
        # Write artifact
        npy_path, metadata_path = write_npy_artifact(result, temp_dir)
        
        assert npy_path.exists()
        assert metadata_path.exists()
    
    def test_read_npy_artifact(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test reading an NPY artifact."""
        # Write artifact
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        npy_path, metadata_path = write_npy_artifact(result, temp_dir)
        
        # Read artifact
        tensor, metadata = read_npy_artifact(npy_path)
        
        assert tensor.shape == result.target_shape
        assert metadata.model_id == "scrfd"
    
    def test_read_and_validate(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test reading and validating an NPY artifact."""
        # Write artifact
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        npy_path, metadata_path = write_npy_artifact(result, temp_dir)
        
        # Read and validate
        reader = NpyArtifactReader()
        tensor, metadata = reader.read_and_validate(npy_path, "scrfd")
        
        assert tensor is not None
    
    def test_validation_failure(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test validation failure for wrong model."""
        # Write artifact for scrfd
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        npy_path, metadata_path = write_npy_artifact(result, temp_dir)
        
        # Try to validate with arcface
        reader = NpyArtifactReader()
        
        with pytest.raises(NpyValidationError):
            reader.read_and_validate(npy_path, "arcface")
    
    def test_metadata_serialization(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test metadata serialization."""
        # Write artifact
        preprocessor = UnifiedPreprocessor("scrfd")
        result = preprocessor.preprocess(sample_canonical_frame)
        npy_path, metadata_path = write_npy_artifact(result, temp_dir)
        
        # Read metadata JSON
        with open(metadata_path, "r") as f:
            data = json.load(f)
        
        assert data["model_id"] == "scrfd"
        assert "tensor_shape" in data
        assert "conversions" in data
    
    def test_batch_write(self, temp_dir: Path, sample_canonical_frame: CanonicalFrame):
        """Test batch writing NPY artifacts."""
        preprocessor = UnifiedPreprocessor("scrfd")
        
        # Create multiple results
        results = []
        for i in range(5):
            result = preprocessor.preprocess(sample_canonical_frame)
            results.append(result)
        
        # Write batch
        writer = NpyArtifactWriter(temp_dir)
        paths = writer.write_batch(results, "batch_test")
        
        assert len(paths) == 5
        for npy_path, metadata_path in paths:
            assert npy_path.exists()
            assert metadata_path.exists()


# =============================================================================
# Integration Tests
# =============================================================================

class TestDataPipelineIntegration:
    """Integration tests for the data pipeline."""
    
    def test_full_image_pipeline(self, sample_bgr_image: Path, temp_dir: Path):
        """Test full image pipeline: load → preprocess → save."""
        # Load image
        adapter = ImageAdapter()
        frame = adapter.load(sample_bgr_image)
        
        # Preprocess for multiple models
        for model_id in ["scrfd", "arcface", "yolo_person"]:
            preprocessor = UnifiedPreprocessor(model_id)
            result = preprocessor.preprocess(frame)
            
            # Save as NPY
            npy_path, metadata_path = write_npy_artifact(result, temp_dir / model_id)
            
            # Read back and validate
            reader = NpyArtifactReader()
            tensor, metadata = reader.read_and_validate(npy_path, model_id)
            
            assert tensor.shape == result.target_shape
    
    def test_full_video_pipeline(self, sample_video: Path, temp_dir: Path):
        """Test full video pipeline: iterate → preprocess → save."""
        adapter = VideoAdapter()
        preprocessor = UnifiedPreprocessor("scrfd")
        writer = NpyArtifactWriter(temp_dir / "video_frames")
        
        # Process video frames
        frame_count = 0
        for frame in adapter.iter_frames(sample_video):
            result = preprocessor.preprocess(frame)
            writer.write(result)
            frame_count += 1
        
        assert frame_count == 10
        
        # Verify all artifacts exist
        npy_files = list((temp_dir / "video_frames").glob("*.npy"))
        assert len(npy_files) == 10


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
