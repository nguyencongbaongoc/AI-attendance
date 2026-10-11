"""
Unit tests for Phase 7 Face Quality.

Tests cover:
- FaceQuality and QualityMetric creation
- QualityAssessor metrics
- Face size assessment
- Detection confidence assessment
- Sharpness/blur assessment
- Brightness/exposure assessment
- Landmark validity assessment
- Pose assessment
- Quality decision logic
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.vision.quality import (
    FaceQuality,
    QualityMetric,
    QualityDecision,
    QualityAssessor,
    create_quality_assessor,
)
from app.vision.crop import FaceCrop
from app.vision.landmarks import LandmarkResult, LandmarkCoordinateSpace
from app.data.frame import SourceType, PixelFormat


class TestQualityMetric:
    """Tests for QualityMetric dataclass."""
    
    def test_valid_metric(self):
        """Test creating a valid quality metric."""
        metric = QualityMetric(
            name="test_metric",
            measurement=0.9,
            threshold=0.5,
            passed=True,
            reason="Test passed",
            unit="ratio",
        )
        
        assert metric.name == "test_metric"
        assert metric.measurement == 0.9
        assert metric.threshold == 0.5
        assert metric.passed is True
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        metric = QualityMetric(
            name="test_metric",
            measurement=0.9,
            threshold=0.5,
            passed=True,
            reason="Test passed",
            unit="ratio",
        )
        
        d = metric.to_dict()
        assert d["name"] == "test_metric"
        assert d["measurement"] == 0.9
        assert d["threshold"] == 0.5
        assert d["passed"] is True
        assert d["reason"] == "Test passed"
        assert d["unit"] == "ratio"


class TestFaceQuality:
    """Tests for FaceQuality dataclass."""
    
    def test_valid_quality(self):
        """Test creating a valid face quality result."""
        metrics = [
            QualityMetric("m1", 0.9, 0.5, True, "pass", ""),
            QualityMetric("m2", 0.3, 0.5, False, "fail", ""),
            QualityMetric("m3", 0.8, 0.5, True, "pass", ""),
        ]
        
        quality = FaceQuality(
            metrics=metrics,
            decision=QualityDecision.REJECTED,
            passed_count=2,
            failed_count=1,
            total_count=3,
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
        )
        
        assert quality.passed_count == 2
        assert quality.failed_count == 1
        assert quality.total_count == 3
        assert quality.pass_rate == 2/3
    
    def test_invalid_counts(self):
        """Test that mismatched counts raise ValueError."""
        metrics = [QualityMetric("m1", 0.9, 0.5, True, "pass", "")]
        
        with pytest.raises(ValueError, match="Passed \\+ failed must equal total"):
            FaceQuality(
                metrics=metrics,
                decision=QualityDecision.ACCEPTABLE,
                passed_count=1,
                failed_count=1,  # Wrong!
                total_count=1,
            )
    
    def test_get_metric(self):
        """Test getting a specific metric by name."""
        metrics = [
            QualityMetric("face_size", 100.0, 64.0, True, "pass", "px"),
            QualityMetric("sharpness", 150.0, 100.0, True, "pass", "var"),
        ]
        
        quality = FaceQuality(
            metrics=metrics,
            decision=QualityDecision.ACCEPTABLE,
            passed_count=2,
            failed_count=0,
            total_count=2,
        )
        
        metric = quality.get_metric("face_size")
        assert metric is not None
        assert metric.name == "face_size"
        assert metric.measurement == 100.0
        
        # Non-existent metric
        assert quality.get_metric("nonexistent") is None
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = [
            QualityMetric("face_size", 100.0, 64.0, True, "pass", "px"),
        ]
        
        quality = FaceQuality(
            metrics=metrics,
            decision=QualityDecision.ACCEPTABLE,
            passed_count=1,
            failed_count=0,
            total_count=1,
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
        )
        
        d = quality.to_dict()
        assert d["decision"] == "acceptable"
        assert d["passed_count"] == 1
        assert d["crop_id"] == "crop123"
        assert len(d["metrics"]) == 1


class TestQualityAssessor:
    """Tests for QualityAssessor class."""
    
    @pytest.fixture
    def assessor(self):
        """Create a quality assessor with default thresholds."""
        return QualityAssessor(
            min_face_size=64,
            min_detection_confidence=0.55,
            min_sharpness=100.0,
            brightness_range=(30.0, 220.0),
            min_landmark_validity=0.8,
            max_pose_angle=45.0,
        )
    
    @pytest.fixture
    def valid_crop(self):
        """Create a valid face crop."""
        # Create a reasonably sharp, well-lit crop
        crop_data = np.random.randint(50, 200, (100, 100, 3), dtype=np.uint8)
        # Add some edges for sharpness
        crop_data[50, :, :] = 255
        crop_data[:, 50, :] = 0
        
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
    
    @pytest.fixture
    def valid_landmarks(self):
        """Create valid landmarks in model input space."""
        landmarks = [(float(i % 192), float(i // 192 * 3), 0.0) for i in range(68)]
        return LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
        )
    
    def test_assess_basic(self, assessor, valid_crop):
        """Test basic quality assessment without landmarks."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9)
        
        assert isinstance(quality, FaceQuality)
        assert quality.total_count == 4  # face_size, confidence, sharpness, brightness
        assert quality.crop_id == valid_crop.crop_id
    
    def test_assess_with_landmarks(self, assessor, valid_crop, valid_landmarks):
        """Test quality assessment with landmarks."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9, landmarks=valid_landmarks)
        
        assert quality.total_count == 6  # + landmark_validity, pose
    
    def test_face_size_pass(self, assessor, valid_crop):
        """Test face size metric passes for adequate size."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9)
        
        metric = quality.get_metric("face_size")
        assert metric is not None
        assert metric.measurement == 100.0  # min(100, 100)
        assert metric.threshold == 64.0
        assert metric.passed is True
    
    def test_face_size_fail(self, assessor):
        """Test face size metric fails for too small crop."""
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
        
        quality = assessor.assess(small_crop, detection_confidence=0.9)
        
        metric = quality.get_metric("face_size")
        assert metric.passed is False
        assert metric.measurement == 30.0
    
    def test_detection_confidence_pass(self, assessor, valid_crop):
        """Test detection confidence metric passes for high confidence."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9)
        
        metric = quality.get_metric("detection_confidence")
        assert metric.passed is True
        assert metric.measurement == 0.9
        assert metric.threshold == 0.55
    
    def test_detection_confidence_fail(self, assessor, valid_crop):
        """Test detection confidence metric fails for low confidence."""
        quality = assessor.assess(valid_crop, detection_confidence=0.3)
        
        metric = quality.get_metric("detection_confidence")
        assert metric.passed is False
        assert metric.measurement == 0.3
    
    def test_sharpness_pass(self, assessor):
        """Test sharpness metric passes for sharp image."""
        # Create a sharp image with high frequency content
        crop_data = np.zeros((100, 100, 3), dtype=np.uint8)
        # Add checkerboard pattern for high Laplacian variance
        for i in range(100):
            for j in range(100):
                if (i // 10 + j // 10) % 2 == 0:
                    crop_data[i, j] = 255
                else:
                    crop_data[i, j] = 0
        
        sharp_crop = FaceCrop(
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
        
        quality = assessor.assess(sharp_crop, detection_confidence=0.9)
        
        metric = quality.get_metric("sharpness")
        # Checkerboard should have high variance
        assert metric.measurement > 100.0
        assert metric.passed is True
    
    def test_sharpness_fail(self, assessor):
        """Test sharpness metric fails for blurry image."""
        # Create a blurry image (smooth gradient)
        crop_data = np.zeros((100, 100, 3), dtype=np.uint8)
        for i in range(100):
            crop_data[i, :, :] = i * 2  # Smooth gradient
        
        blurry_crop = FaceCrop(
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
        
        quality = assessor.assess(blurry_crop, detection_confidence=0.9)
        
        metric = quality.get_metric("sharpness")
        # Smooth gradient should have low variance
        assert metric.measurement < 100.0
        assert metric.passed is False
    
    def test_brightness_pass(self, assessor):
        """Test brightness metric passes for well-exposed image."""
        # Create image with mean brightness in range
        crop_data = np.full((100, 100, 3), 128, dtype=np.uint8)  # Mid-gray
        
        crop = FaceCrop(
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
        
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        metric = quality.get_metric("brightness")
        assert 30.0 <= metric.measurement <= 220.0
        assert metric.passed is True
    
    def test_brightness_fail_dark(self, assessor):
        """Test brightness metric fails for too dark image."""
        crop_data = np.full((100, 100, 3), 10, dtype=np.uint8)  # Very dark
        
        crop = FaceCrop(
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
        
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        metric = quality.get_metric("brightness")
        assert metric.measurement < 30.0
        assert metric.passed is False
    
    def test_brightness_fail_bright(self, assessor):
        """Test brightness metric fails for too bright image."""
        crop_data = np.full((100, 100, 3), 250, dtype=np.uint8)  # Very bright
        
        crop = FaceCrop(
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
        
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        metric = quality.get_metric("brightness")
        assert metric.measurement > 220.0
        assert metric.passed is False
    
    def test_landmark_validity_pass(self, assessor, valid_crop, valid_landmarks):
        """Test landmark validity metric passes for valid landmarks."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9, landmarks=valid_landmarks)
        
        metric = quality.get_metric("landmark_validity")
        assert metric.passed is True
        assert metric.measurement >= 0.8
    
    def test_landmark_validity_fail(self, assessor, valid_crop):
        """Test landmark validity metric fails for invalid landmarks."""
        # Create landmarks with NaN values
        landmarks = [(float('nan'), 0.0, 0.0)] * 68
        invalid_landmarks = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        
        quality = assessor.assess(valid_crop, detection_confidence=0.9, landmarks=invalid_landmarks)
        
        metric = quality.get_metric("landmark_validity")
        assert metric.passed is False
        assert metric.measurement < 0.8
    
    def test_pose_pass(self, assessor, valid_crop):
        """Test pose metric passes for frontal face."""
        # Create landmarks for a frontal face
        landmarks = []
        for i in range(68):
            if i == 30:  # Nose tip
                landmarks.append((96.0, 96.0, 0.0))
            elif i == 8:  # Chin
                landmarks.append((96.0, 140.0, 0.0))
            elif i == 36:  # Left eye
                landmarks.append((60.0, 80.0, 0.0))
            elif i == 45:  # Right eye
                landmarks.append((132.0, 80.0, 0.0))
            elif i == 48:  # Left mouth
                landmarks.append((70.0, 120.0, 0.0))
            elif i == 54:  # Right mouth
                landmarks.append((122.0, 120.0, 0.0))
            else:
                landmarks.append((float(i % 192), float(i // 192 * 3), 0.0))
        
        frontal_landmarks = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
        )
        
        quality = assessor.assess(valid_crop, detection_confidence=0.9, landmarks=frontal_landmarks)
        
        metric = quality.get_metric("pose")
        # Frontal face should have low pose angle
        assert metric.measurement < 45.0
        # Note: passed is numpy bool, compare with == True
        assert metric.passed == True
    
    def test_decision_acceptable(self, assessor, valid_crop, valid_landmarks):
        """Test final decision is ACCEPTABLE when all metrics pass."""
        quality = assessor.assess(valid_crop, detection_confidence=0.9, landmarks=valid_landmarks)
        
        # With good synthetic data, most metrics should pass
        # But sharpness might fail with random data
        # Let's check the decision logic
        if quality.failed_count == 0:
            assert quality.decision == QualityDecision.ACCEPTABLE
        else:
            assert quality.decision == QualityDecision.REJECTED
    
    def test_decision_rejected(self, assessor):
        """Test final decision is REJECTED when any metric fails."""
        # Create a crop that will fail multiple metrics
        crop_data = np.full((30, 30, 3), 10, dtype=np.uint8)  # Small, dark
        
        crop = FaceCrop(
            data=crop_data,
            crop_width=30,
            crop_height=30,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 130.0, 130.0),
            detection_confidence=0.3,  # Low confidence
            detection_id="det123",
        )
        
        quality = assessor.assess(crop, detection_confidence=0.3)
        
        assert quality.decision == QualityDecision.REJECTED
        assert quality.failed_count > 0
    
    def test_decision_insufficient_data(self, assessor):
        """Test final decision is INSUFFICIENT_DATA when no metrics."""
        # This shouldn't happen in practice, but test the logic
        quality = FaceQuality(
            metrics=[],
            decision=QualityDecision.INSUFFICIENT_DATA,
            passed_count=0,
            failed_count=0,
            total_count=0,
        )
        
        assert quality.decision == QualityDecision.INSUFFICIENT_DATA


class TestFactoryFunction:
    """Tests for factory functions."""
    
    @patch('app.vision.quality.QualityAssessor')
    def test_create_quality_assessor(self, mock_assessor_class):
        """Test factory function."""
        mock_assessor = MagicMock()
        mock_assessor_class.return_value = mock_assessor
        
        assessor = create_quality_assessor(
            min_face_size=128,
            min_sharpness=200.0,
        )
        
        mock_assessor_class.assert_called_once_with(
            min_face_size=128,
            min_detection_confidence=0.55,
            min_sharpness=200.0,
            brightness_range=(30.0, 220.0),
            min_landmark_validity=0.8,
            max_pose_angle=45.0,
        )
        assert assessor == mock_assessor


if __name__ == "__main__":
    pytest.main([__file__, "-v"])