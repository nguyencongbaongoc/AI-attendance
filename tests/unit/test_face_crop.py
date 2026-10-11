"""
Unit tests for Phase 7 Face Crop.

Tests cover:
- FaceCrop creation and validation
- safe_crop_face function
- Boundary clipping
- Multiple faces
- Provenance preservation
"""

from __future__ import annotations

import numpy as np
import pytest

from app.vision.crop import (
    FaceCrop,
    CropError,
    safe_crop_face,
    crop_multiple_faces,
    validate_crop_for_landmark,
)
from app.vision.detection import FaceDetection, CoordinateSpace
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat


class TestFaceCrop:
    """Tests for FaceCrop dataclass."""
    
    def test_valid_crop(self):
        """Test creating a valid face crop."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
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
        
        assert crop.shape == (100, 100, 3)
        assert crop.channels == 3
        assert crop.aspect_ratio == 1.0
        assert crop.area == 10000
    
    def test_invalid_dimensions(self):
        """Test that dimension mismatch raises ValueError."""
        crop_data = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        
        with pytest.raises(ValueError, match="dimensions mismatch"):
            FaceCrop(
                data=crop_data,
                crop_width=100,  # Wrong!
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
    
    def test_invalid_bbox(self):
        """Test that non-finite bbox raises ValueError."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceCrop(
                data=crop_data,
                crop_width=100,
                crop_height=100,
                source_type=SourceType.IMAGE,
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                original_frame_width=640,
                original_frame_height=480,
                bbox=(float('nan'), 100.0, 200.0, 200.0),
                detection_confidence=0.9,
                detection_id="det123",
            )
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
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
        
        d = crop.to_dict()
        assert d["crop_width"] == 100
        assert d["crop_height"] == 100
        assert d["source_type"] == "image"
        assert d["detection_confidence"] == 0.9
        assert d["detection_id"] == "det123"
    
    def test_copy(self):
        """Test deep copy."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
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
        
        copy = crop.copy()
        assert np.array_equal(copy.data, crop.data)
        assert copy.crop_id == crop.crop_id
        
        # Modify original, check copy is independent
        crop.data[0, 0, 0] = 255
        assert copy.data[0, 0, 0] != 255


class TestSafeCropFace:
    """Tests for safe_crop_face function."""
    
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
    
    @pytest.fixture
    def valid_detection(self):
        """Create a valid face detection."""
        return FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            detection_id="det123",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            model_id="scrfd",
            model_sha256="abc123",
            frame_index=0,
            source_id="test.jpg",
        )
    
    def test_basic_crop(self, sample_frame, valid_detection):
        """Test basic face cropping."""
        crop = safe_crop_face(sample_frame, valid_detection)
        
        assert crop.crop_width == 100
        assert crop.crop_height == 100
        assert crop.data.shape == (100, 100, 3)
        assert crop.detection_id == "det123"
        assert crop.source_id == "test.jpg"
    
    def test_crop_rgb_conversion(self, sample_frame, valid_detection):
        """Test that crop is converted to RGB."""
        crop = safe_crop_face(sample_frame, valid_detection, target_format=PixelFormat.RGB)
        
        assert crop.pixel_format == PixelFormat.RGB
        # Original frame is BGR, crop should be RGB
    
    def test_bbox_at_top_left(self, sample_frame):
        """Test crop at top-left corner (0, 0)."""
        detection = FaceDetection(
            bbox=(0.0, 0.0, 100.0, 100.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det1",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        crop = safe_crop_face(sample_frame, detection)
        
        assert crop.crop_width == 100
        assert crop.crop_height == 100
        assert crop.bbox == (0.0, 0.0, 100.0, 100.0)
    
    def test_bbox_at_bottom_right(self, sample_frame):
        """Test crop at bottom-right corner."""
        detection = FaceDetection(
            bbox=(540.0, 380.0, 640.0, 480.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det2",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        crop = safe_crop_face(sample_frame, detection)
        
        assert crop.crop_width == 100
        assert crop.crop_height == 100
    
    def test_bbox_partially_outside(self, sample_frame):
        """Test crop with bbox partially outside image."""
        detection = FaceDetection(
            bbox=(-50.0, -50.0, 150.0, 150.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det3",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        crop = safe_crop_face(sample_frame, detection)
        
        # Should be clipped to (0, 0, 150, 150)
        assert crop.crop_width == 150
        assert crop.crop_height == 150
        # Original bbox preserved in provenance
        assert crop.bbox == (-50.0, -50.0, 150.0, 150.0)
    
    def test_bbox_exactly_on_boundary(self, sample_frame):
        """Test crop with bbox exactly on image boundary."""
        detection = FaceDetection(
            bbox=(0.0, 0.0, 640.0, 480.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det4",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        crop = safe_crop_face(sample_frame, detection)
        
        assert crop.crop_width == 640
        assert crop.crop_height == 480
    
    def test_invalid_detection_coordinate_space(self, sample_frame):
        """Test that wrong coordinate space raises CropError."""
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det5",
            coordinate_space=CoordinateSpace.MODEL_INPUT,  # Wrong!
        )
        
        with pytest.raises(CropError, match="ORIGINAL_FRAME coordinates"):
            safe_crop_face(sample_frame, detection)
    
    def test_invalid_bbox_x1_ge_x2(self, sample_frame):
        """Test that x1 >= x2 raises CropError."""
        detection = FaceDetection(
            bbox=(200.0, 100.0, 100.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det6",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        with pytest.raises(CropError, match="Invalid bbox"):
            safe_crop_face(sample_frame, detection)
    
    def test_nan_bbox(self, sample_frame):
        """Test that NaN bbox raises ValueError in FaceDetection."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetection(
                bbox=(float('nan'), 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detection_id="det7",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            )
    
    def test_empty_crop_after_clipping(self, sample_frame):
        """Test that empty crop after clipping raises CropError."""
        detection = FaceDetection(
            bbox=(640.0, 100.0, 640.0, 200.0),  # Zero width
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det8",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        with pytest.raises(CropError, match="Invalid bbox"):
            safe_crop_face(sample_frame, detection)
    
    def test_crop_too_small(self, sample_frame):
        """Test that crop below minimum size raises CropError."""
        detection = FaceDetection(
            bbox=(100.0, 100.0, 105.0, 105.0),  # 5x5 crop
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det9",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        with pytest.raises(CropError, match="Crop too small"):
            safe_crop_face(sample_frame, detection, min_crop_size=16)
    
    def test_provenance_preserved(self, sample_frame, valid_detection):
        """Test that all provenance metadata is preserved."""
        crop = safe_crop_face(sample_frame, valid_detection)
        
        assert crop.source_type == SourceType.IMAGE
        assert crop.source_id == "test.jpg"
        assert crop.frame_index == 0
        assert crop.timestamp is None
        assert crop.original_frame_width == 640
        assert crop.original_frame_height == 480
        assert crop.bbox == (100.0, 100.0, 200.0, 200.0)
        assert crop.detection_confidence == 0.9
        assert crop.detection_id == "det123"
        assert crop.crop_id is not None


class TestCropMultipleFaces:
    """Tests for crop_multiple_faces function."""
    
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
    
    def test_multiple_valid_crops(self, sample_frame):
        """Test cropping multiple valid faces."""
        detections = [
            FaceDetection(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detection_id="det1",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            ),
            FaceDetection(
                bbox=(300.0, 100.0, 400.0, 200.0),
                confidence=0.8,
                landmarks5=[(0, 0)] * 5,
                detection_id="det2",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            ),
        ]
        
        crops = crop_multiple_faces(sample_frame, detections)
        
        assert len(crops) == 2
        assert crops[0].detection_id == "det1"
        assert crops[1].detection_id == "det2"
    
    def test_skip_invalid_crops(self, sample_frame):
        """Test that invalid crops are skipped with warning."""
        detections = [
            FaceDetection(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detection_id="det1",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            ),
            FaceDetection(
                bbox=(200.0, 100.0, 100.0, 200.0),  # Invalid: x1 >= x2
                confidence=0.8,
                landmarks5=[(0, 0)] * 5,
                detection_id="det2",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            ),
        ]
        
        crops = crop_multiple_faces(sample_frame, detections)
        
        # Only first crop should succeed
        assert len(crops) == 1
        assert crops[0].detection_id == "det1"


class TestValidateCropForLandmark:
    """Tests for validate_crop_for_landmark function."""
    
    def test_valid_crop(self):
        """Test validation of valid crop."""
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
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
        
        assert validate_crop_for_landmark(crop, min_dimension=32) is True
    
    def test_crop_too_small(self):
        """Test validation fails for too small crop."""
        crop_data = np.random.randint(0, 256, (20, 20, 3), dtype=np.uint8)
        crop = FaceCrop(
            data=crop_data,
            crop_width=20,
            crop_height=20,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 120.0, 120.0),
            detection_confidence=0.9,
            detection_id="det123",
        )
        
        assert validate_crop_for_landmark(crop, min_dimension=32) is False
    
    def test_empty_crop(self):
        """Test validation fails for empty crop."""
        crop_data = np.array([]).reshape(0, 0, 3)
        crop = FaceCrop(
            data=crop_data,
            crop_width=0,
            crop_height=0,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 100.0, 100.0),
            detection_confidence=0.9,
            detection_id="det123",
        )
        
        assert validate_crop_for_landmark(crop) is False
    
    def test_non_finite_values(self):
        """Test validation fails for non-finite pixel values."""
        crop_data = np.full((100, 100, 3), np.nan, dtype=np.float32)
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
        
        assert validate_crop_for_landmark(crop) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])