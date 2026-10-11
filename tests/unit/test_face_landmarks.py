"""
Unit tests for Phase 7 Face Landmarks.

Tests cover:
- LandmarkDetector initialization
- LandmarkResult contract validation
- Landmark output validation
- Coordinate space conversion
- CUDA/CPU inference
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.vision.landmarks import (
    LandmarkDetector,
    LandmarkResult,
    LandmarkError,
    LandmarkCoordinateSpace,
    create_landmark_detector,
)
from app.vision.crop import FaceCrop
from app.data.frame import SourceType, PixelFormat


class TestLandmarkResult:
    """Tests for LandmarkResult dataclass."""
    
    def test_valid_landmarks(self):
        """Test creating valid landmark result."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.5,
        )
        
        assert len(result.landmarks) == 68
        assert result.landmarks_xy[0] == (0.0, 0.0)
        assert result.landmarks_z[0] == 0.0
    
    def test_invalid_landmark_count(self):
        """Test that wrong number of landmarks raises ValueError."""
        landmarks = [(float(i), float(i), float(i)) for i in range(67)]  # Only 67
        
        with pytest.raises(ValueError, match="Expected 68 landmarks"):
            LandmarkResult(
                landmarks=landmarks,
                coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            )
    
    def test_non_finite_landmarks(self):
        """Test that non-finite landmarks are now allowed (validated in quality assessment)."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        landmarks[0] = (float('nan'), 0.0, 0.0)
        
        # This is now allowed - validation happens in quality assessment
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        # NaN != NaN in Python, so check with math.isnan
        import math
        assert math.isnan(result.landmarks[0][0])
        assert result.landmarks[0][1] == 0.0
        assert result.landmarks[0][2] == 0.0
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.5,
        )
        
        d = result.to_dict()
        assert d["num_landmarks"] == 68
        assert d["coordinate_space"] == "model_input_relative"
        assert d["model_id"] == "landmark_1k3d68"
        assert d["inference_time_ms"] == 10.5
    
    def test_convert_to_same_space(self):
        """Test conversion to same space returns self."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        
        converted = result.convert_to_space(LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE)
        assert converted is result
    
    def test_convert_model_to_crop_relative(self):
        """Test conversion from model input to crop-relative."""
        # Landmarks in model input space (0-192)
        landmarks = [(96.0, 96.0, 0.0)] * 68  # Center of 192x192
        
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        
        # Create a mock crop
        crop = MagicMock()
        crop.crop_width = 100
        crop.crop_height = 100
        
        converted = result.convert_to_space(
            LandmarkCoordinateSpace.CROP_RELATIVE,
            crop=crop,
        )
        
        # 96/192 = 0.5, so crop-relative should be 50, 50
        assert abs(converted.landmarks[0][0] - 50.0) < 0.1
        assert abs(converted.landmarks[0][1] - 50.0) < 0.1
        assert converted.coordinate_space == LandmarkCoordinateSpace.CROP_RELATIVE
    
    def test_convert_model_to_original_frame(self):
        """Test conversion from model input to original frame."""
        landmarks = [(96.0, 96.0, 0.0)] * 68  # Center of 192x192
        
        result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        
        converted = result.convert_to_space(
            LandmarkCoordinateSpace.ORIGINAL_FRAME_RELATIVE,
            original_frame_width=640,
            original_frame_height=480,
        )
        
        # 96/192 = 0.5, so original frame should be 320, 240
        assert abs(converted.landmarks[0][0] - 320.0) < 0.1
        assert abs(converted.landmarks[0][1] - 240.0) < 0.1
        assert converted.coordinate_space == LandmarkCoordinateSpace.ORIGINAL_FRAME_RELATIVE


class TestLandmarkDetector:
    """Tests for LandmarkDetector class."""
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock ONNX Runtime session."""
        mock = MagicMock()
        mock.get_inputs.return_value = [MagicMock(name="input")]
        mock.get_outputs.return_value = [MagicMock(name="output")]
        mock.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return mock
    
    @pytest.fixture
    def valid_crop(self):
        """Create a valid face crop."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        return FaceCrop(
            data=crop_data,
            crop_width=100,
            crop_height=100,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 200.0, 200.0),
            detection_confidence=0.9,
            detection_id="det123",
        )
    
    def test_detector_creation_wrong_model(self):
        """Test that wrong model_id raises ValueError."""
        with pytest.raises(ValueError, match="only supports 'landmark_1k3d68'"):
            LandmarkDetector(model_id="scrfd")
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    def test_detector_initialization(self, mock_registry, mock_verify, mock_get_session, mock_session):
        """Test detector initialization."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        detector = LandmarkDetector()
        
        assert detector.model_id == "landmark_1k3d68"
        assert detector.min_crop_dimension == 32
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    def test_detector_hash_mismatch(self, mock_registry, mock_verify, mock_get_session, mock_session):
        """Test that hash mismatch raises LandmarkError."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: False, status=MagicMock(value="hash_mismatch"))
        
        with pytest.raises(LandmarkError, match="SHA256 verification failed"):
            LandmarkDetector()
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    @patch('app.vision.landmarks.UnifiedPreprocessor')
    def test_detect_invalid_crop(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, valid_crop):
        """Test detection with invalid crop (too small)."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        detector = LandmarkDetector(min_crop_dimension=64)
        
        # Crop is 100x100, but min is 64 - should pass
        # Let's make it smaller
        small_crop = FaceCrop(
            data=np.random.randint(0, 256, (30, 30, 3), dtype=np.uint8),
            crop_width=30,
            crop_height=30,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 130.0, 130.0),
            detection_confidence=0.9,
            detection_id="det123",
        )
        
        with pytest.raises(LandmarkError, match="Crop invalid for landmark inference"):
            detector.detect(small_crop)
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    @patch('app.vision.landmarks.UnifiedPreprocessor')
    def test_detect_success_3309_output(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, valid_crop):
        """Test successful detection with 3309 output values."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor.preprocess.return_value = MagicMock(
            tensor=np.zeros((1, 3, 192, 192), dtype=np.float32),
        )
        mock_preprocessor_class.return_value = mock_preprocessor
        
        # Mock session output: 3309 values (Phase 5 format)
        output_3309 = np.random.rand(3309).astype(np.float32)
        mock_session.run.return_value = [output_3309.reshape(1, 3309)]
        
        detector = LandmarkDetector()
        result = detector.detect(valid_crop)
        
        assert isinstance(result, LandmarkResult)
        assert len(result.landmarks) == 68
        assert result.coordinate_space == LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE
        assert result.model_sha256 == "abc123"
        assert result.inference_time_ms > 0
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    @patch('app.vision.landmarks.UnifiedPreprocessor')
    def test_detect_success_204_output(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, valid_crop):
        """Test successful detection with 204 output values (68*3)."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor.preprocess.return_value = MagicMock(
            tensor=np.zeros((1, 3, 192, 192), dtype=np.float32),
        )
        mock_preprocessor_class.return_value = mock_preprocessor
        
        # Mock session output: 204 values (68*3)
        output_204 = np.random.rand(204).astype(np.float32)
        mock_session.run.return_value = [output_204.reshape(1, 204)]
        
        detector = LandmarkDetector()
        result = detector.detect(valid_crop)
        
        assert isinstance(result, LandmarkResult)
        assert len(result.landmarks) == 68
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    @patch('app.vision.landmarks.UnifiedPreprocessor')
    def test_detect_insufficient_output(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, valid_crop):
        """Test detection with insufficient output values."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor.preprocess.return_value = MagicMock(
            tensor=np.zeros((1, 3, 192, 192), dtype=np.float32),
        )
        mock_preprocessor_class.return_value = mock_preprocessor
        
        # Mock session output: only 100 values (insufficient)
        output_100 = np.random.rand(100).astype(np.float32)
        mock_session.run.return_value = [output_100.reshape(1, 100)]
        
        detector = LandmarkDetector()
        
        with pytest.raises(LandmarkError, match="Unexpected landmark output size"):
            detector.detect(valid_crop)
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    @patch('app.vision.landmarks.UnifiedPreprocessor')
    def test_detect_non_finite_landmarks(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, valid_crop):
        """Test detection with non-finite landmark output."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor.preprocess.return_value = MagicMock(
            tensor=np.zeros((1, 3, 192, 192), dtype=np.float32),
        )
        mock_preprocessor_class.return_value = mock_preprocessor
        
        # Mock session output with NaN
        output_204 = np.random.rand(204).astype(np.float32)
        output_204[0] = float('nan')
        mock_session.run.return_value = [output_204.reshape(1, 204)]
        
        detector = LandmarkDetector()
        
        with pytest.raises(LandmarkError, match="non-finite coordinates"):
            detector.detect(valid_crop)


class TestFactoryFunction:
    """Tests for factory functions."""
    
    @patch('app.vision.landmarks.LandmarkDetector')
    def test_create_landmark_detector(self, mock_detector_class):
        """Test factory function."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        
        detector = create_landmark_detector(
            model_id="landmark_1k3d68",
            min_crop_dimension=64,
        )
        
        mock_detector_class.assert_called_once_with(
            model_id="landmark_1k3d68",
            providers=None,
            min_crop_dimension=64,
        )
        assert detector == mock_detector


if __name__ == "__main__":
    pytest.main([__file__, "-v"])