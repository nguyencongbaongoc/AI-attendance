"""
Unit tests for Phase 7 Face Detection.

Tests cover:
- FaceDetector initialization
- FaceDetection contract validation
- Bounding box validation
- Coordinate conversion
- NMS
- CUDA/CPU inference
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.vision.detection import (
    FaceDetector,
    FaceDetection,
    DetectionError,
    CoordinateSpace,
    create_face_detector,
)
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat


class TestFaceDetection:
    """Tests for FaceDetection dataclass."""
    
    def test_valid_detection(self):
        """Test creating a valid face detection."""
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            detection_id="test123",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            model_id="scrfd",
            model_sha256="abc123",
            frame_index=0,
            source_id="test.jpg",
        )
        
        assert detection.width == 100.0
        assert detection.height == 100.0
        assert detection.area == 10000.0
        assert detection.center == (150.0, 150.0)
    
    def test_invalid_bbox_x1_ge_x2(self):
        """Test that x1 >= x2 is now allowed (clipped in safe_crop_face)."""
        # This is now allowed - validation happens in safe_crop_face
        detection = FaceDetection(
            bbox=(200.0, 100.0, 100.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="test",
        )
        assert detection.bbox == (200.0, 100.0, 100.0, 200.0)
    
    def test_invalid_bbox_y1_ge_y2(self):
        """Test that y1 >= y2 is now allowed (clipped in safe_crop_face)."""
        detection = FaceDetection(
            bbox=(100.0, 200.0, 200.0, 100.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="test",
        )
        assert detection.bbox == (100.0, 200.0, 200.0, 100.0)
    
    def test_invalid_negative_coordinates(self):
        """Test that negative coordinates are now allowed (clipped in safe_crop_face)."""
        detection = FaceDetection(
            bbox=(-10.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="test",
        )
        assert detection.bbox == (-10.0, 100.0, 200.0, 200.0)
    
    def test_invalid_confidence(self):
        """Test that confidence outside [0, 1] raises ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence"):
            FaceDetection(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=1.5,
                landmarks5=[(0, 0)] * 5,
                detection_id="test",
            )
    
    def test_invalid_landmarks_count(self):
        """Test that wrong number of landmarks raises ValueError."""
        with pytest.raises(ValueError, match="Expected 5 landmarks"):
            FaceDetection(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 4,  # Only 4 landmarks
                detection_id="test",
            )
    
    def test_non_finite_landmarks(self):
        """Test that non-finite landmarks raise ValueError."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetection(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0), (float('nan'), 0), (0, 0), (0, 0), (0, 0)],
                detection_id="test",
            )
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            detection_id="test123",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            model_id="scrfd",
            model_sha256="abc123",
            frame_index=0,
            source_id="test.jpg",
        )
        
        d = detection.to_dict()
        assert d["bbox"] == [100.0, 100.0, 200.0, 200.0]
        assert d["confidence"] == 0.9
        assert d["detection_id"] == "test123"
        assert d["coordinate_space"] == "original_frame"
        assert d["width"] == 100.0
        assert d["height"] == 100.0


class TestFaceDetector:
    """Tests for FaceDetector class."""
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock ONNX Runtime session."""
        mock = MagicMock()
        mock.get_inputs.return_value = [MagicMock(name="input")]
        mock.get_outputs.return_value = [
            MagicMock(name="scores"),
            MagicMock(name="bboxes"),
            MagicMock(name="keypoints"),
        ]
        mock.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return mock
    
    @pytest.fixture
    def sample_frame(self):
        """Create a sample canonical frame."""
        data = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        return CanonicalFrame(data=data, metadata=metadata)
    
    def test_detector_creation_wrong_model(self):
        """Test that wrong model_id raises ValueError."""
        with pytest.raises(ValueError, match="only supports 'scrfd'"):
            FaceDetector(model_id="arcface")
    
    @patch('app.vision.detection.get_ort_session')
    @patch('app.vision.detection.verify_sha256')
    @patch('app.vision.detection.get_model_registry')
    def test_detector_initialization(self, mock_registry, mock_verify, mock_get_session, mock_session):
        """Test detector initialization."""
        # Setup mocks
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        mock_model.thresholds.confidence_threshold = 0.55
        mock_model.thresholds.nms_threshold = 0.45
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/scrfd/scrfd_10g_bnkps.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Create detector
        detector = FaceDetector()
        
        assert detector.model_id == "scrfd"
        assert detector.confidence_threshold == 0.55
        assert detector.nms_threshold == 0.45
    
    @patch('app.vision.detection.get_ort_session')
    @patch('app.vision.detection.verify_sha256')
    @patch('app.vision.detection.get_model_registry')
    def test_detector_hash_mismatch(self, mock_registry, mock_verify, mock_get_session, mock_session):
        """Test that hash mismatch raises DetectionError."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/scrfd/scrfd_10g_bnkps.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: False, status=MagicMock(value="hash_mismatch"))
        
        with pytest.raises(DetectionError, match="SHA256 verification failed"):
            FaceDetector()
    
    @patch('app.vision.detection.get_ort_session')
    @patch('app.vision.detection.verify_sha256')
    @patch('app.vision.detection.get_model_registry')
    @patch('app.vision.detection.UnifiedPreprocessor')
    def test_detect_no_outputs(self, mock_preprocessor_class, mock_registry, mock_verify, mock_get_session, mock_session, sample_frame):
        """Test detection with insufficient outputs."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        mock_model.thresholds.confidence_threshold = 0.55
        mock_model.thresholds.nms_threshold = 0.45
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/scrfd/scrfd_10g_bnkps.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        mock_get_session.return_value = mock_session
        
        # Mock preprocessor
        mock_preprocessor = MagicMock()
        mock_preprocessor.preprocess.return_value = MagicMock(
            tensor=np.zeros((1, 3, 960, 960), dtype=np.float32),
            scale_factor=1.0,
            padding_applied=(0, 0, 0, 0),
            frame_index=0,
            source_id="test.jpg",
        )
        mock_preprocessor_class.return_value = mock_preprocessor
        
        # Mock session to return only 2 outputs
        mock_session.run.return_value = [np.array([[]]), np.array([[]])]
        
        detector = FaceDetector()
        
        with pytest.raises(DetectionError, match="Expected 9 outputs from SCRFD 10G"):
            detector.detect(sample_frame)
    
    def test_compute_iou(self):
        """Test IoU computation."""
        detector = FaceDetector.__new__(FaceDetector)
        
        # Perfect overlap
        iou = detector._compute_iou((0, 0, 100, 100), (0, 0, 100, 100))
        assert iou == 1.0
        
        # No overlap
        iou = detector._compute_iou((0, 0, 100, 100), (200, 200, 300, 300))
        assert iou == 0.0
        
        # Partial overlap
        iou = detector._compute_iou((0, 0, 100, 100), (50, 50, 150, 150))
        # Intersection: 50x50 = 2500
        # Union: 10000 + 10000 - 2500 = 17500
        # IoU: 2500/17500 = 1/7 ≈ 0.142857
        assert abs(iou - 1/7) < 0.001
    
    def test_apply_nms(self):
        """Test NMS suppression."""
        detector = FaceDetector.__new__(FaceDetector)
        detector.nms_threshold = 0.45
        
        # Create detections with high overlap
        det1 = FaceDetection(
            bbox=(100, 100, 200, 200),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="1",
        )
        det2 = FaceDetection(
            bbox=(110, 110, 210, 210),  # High overlap with det1
            confidence=0.8,
            landmarks5=[(0, 0)] * 5,
            detection_id="2",
        )
        det3 = FaceDetection(
            bbox=(300, 300, 400, 400),  # No overlap
            confidence=0.7,
            landmarks5=[(0, 0)] * 5,
            detection_id="3",
        )
        
        detections = [det1, det2, det3]
        result = detector._apply_nms(detections)
        
        # Should keep det1 (highest confidence) and det3 (no overlap)
        # Should suppress det2 (overlaps with det1)
        assert len(result) == 2
        assert result[0].detection_id == "1"
        assert result[1].detection_id == "3"


class TestCoordinateConversion:
    """Tests for coordinate space conversion."""
    
    def test_model_to_original_conversion(self):
        """Test conversion from model input to original frame coordinates."""
        detector = FaceDetector.__new__(FaceDetector)
        
        # Model input: 960x960, original: 640x480
        # Scale factor: min(960/640, 960/480) = 1.5
        # Padding: (960 - 480*1.5)/2 = (960-720)/2 = 120 top/bottom
        #          (960 - 640*1.5)/2 = (960-960)/2 = 0 left/right
        
        bbox_model = np.array([200.0, 300.0, 400.0, 500.0])  # In model space
        scale = 1.5
        pad_left, pad_top = 0, 120
        orig_w, orig_h = 640, 480
        
        bbox_orig = detector._convert_bbox_model_to_original(
            bbox_model, scale, pad_left, pad_top, orig_w, orig_h
        )
        
        # Expected: (200-0)/1.5 = 133.33, (300-120)/1.5 = 120
        #           (400-0)/1.5 = 266.67, (500-120)/1.5 = 253.33
        assert abs(bbox_orig[0] - 133.33) < 0.1
        assert abs(bbox_orig[1] - 120.0) < 0.1
        assert abs(bbox_orig[2] - 266.67) < 0.1
        assert abs(bbox_orig[3] - 253.33) < 0.1
    
    def test_keypoints_conversion(self):
        """Test keypoints conversion from model to original."""
        detector = FaceDetector.__new__(FaceDetector)
        
        kps_model = np.array([
            [200.0, 300.0],
            [400.0, 300.0],
            [300.0, 400.0],
            [250.0, 450.0],
            [350.0, 450.0],
        ])
        scale = 1.5
        pad_left, pad_top = 0, 120
        orig_w, orig_h = 640, 480
        
        kps_orig = detector._convert_keypoints_model_to_original(
            kps_model, scale, pad_left, pad_top, orig_w, orig_h
        )
        
        # First keypoint: (200-0)/1.5 = 133.33, (300-120)/1.5 = 120
        assert abs(kps_orig[0][0] - 133.33) < 0.1
        assert abs(kps_orig[0][1] - 120.0) < 0.1


class TestFactoryFunction:
    """Tests for factory functions."""
    
    @patch('app.vision.detection.FaceDetector')
    def test_create_face_detector(self, mock_detector_class):
        """Test factory function."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        
        detector = create_face_detector(
            model_id="scrfd",
            confidence_threshold=0.6,
            nms_threshold=0.5,
        )
        
        mock_detector_class.assert_called_once_with(
            model_id="scrfd",
            confidence_threshold=0.6,
            nms_threshold=0.5,
            providers=None,
        )
        assert detector == mock_detector


if __name__ == "__main__":
    pytest.main([__file__, "-v"])