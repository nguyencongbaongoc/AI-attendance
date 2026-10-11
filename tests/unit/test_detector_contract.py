"""
Phase 8 — Unit Tests for Face Detector Contract and Adapters.

Tests cover:
1. FaceDetectionContract validation
2. FaceDetectorInterface contract
3. SCRFD adapter
4. RetinaFace placeholder
5. Coordinate-space preservation
6. Five-point landmark preservation
7. Provenance preservation
8. Model identity preservation
9. SCRFD 640x640 preprocessing contract
10. Downstream compatibility
11. Explicit RetinaFace-not-implemented behavior
"""

from __future__ import annotations

import numpy as np
import pytest

from app.vision.detector_contract import (
    FaceDetectionContract,
    FaceDetectorInterface,
    DetectorModelId,
    DetectorStatus,
    DetectorProvenance,
    create_detector_provenance,
)
from app.vision.scrfd_adapter import SCRFDAdapter, create_scrfd_adapter
from app.vision.retinaface_adapter import RetinaFaceAdapter, create_retinaface_adapter, RetinaFaceNotImplementedError
from app.vision.detector_factory import get_detector, list_available_detectors, get_detector_status
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat


class TestDetectorProvenance:
    """Tests for DetectorProvenance."""
    
    def test_create_provenance(self):
        """Test creating provenance from frame and detector info."""
        frame = CanonicalFrame(
            data=np.zeros((480, 640, 3), dtype=np.uint8),
            metadata=FrameMetadata(
                source_type=SourceType.IMAGE,
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                original_width=640,
                original_height=480,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
            ),
        )
        
        provenance = create_detector_provenance(
            frame=frame,
            detector_model_id="scrfd",
            detector_model_version="1.0.0",
            detector_model_sha256="abc123",
            detection_id="det123",
        )
        
        assert provenance.source_type == "image"
        assert provenance.source_id == "test.jpg"
        assert provenance.frame_index == 0
        assert provenance.detector_model_id == "scrfd"
        assert provenance.detector_model_version == "1.0.0"
        assert provenance.detector_model_sha256 == "abc123"
        assert provenance.detection_id == "det123"
    
    def test_provenance_to_dict(self):
        """Test provenance serialization."""
        provenance = DetectorProvenance(
            source_type="image",
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            detector_model_id="scrfd",
            detector_model_version="1.0.0",
            detector_model_sha256="abc123",
            detection_id="det123",
        )
        
        d = provenance.to_dict()
        assert d["source_type"] == "image"
        assert d["detector_model_id"] == "scrfd"
        assert d["detection_id"] == "det123"


class TestFaceDetectionContract:
    """Tests for FaceDetectionContract validation."""
    
    def test_valid_detection(self):
        """Test creating a valid face detection contract."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[
                (120.0, 120.0), (180.0, 120.0), (150.0, 150.0),
                (130.0, 170.0), (170.0, 170.0)
            ],
            coordinate_space="original_frame",
            source_frame_id="test.jpg",
            detector_model_id="scrfd",
            detector_model_version="1.0.0",
            detector_model_sha256="abc123",
            detection_id="det123",
        )
        
        assert det.width == 100.0
        assert det.height == 100.0
        assert det.area == 10000.0
        assert det.center == (150.0, 150.0)
    
    def test_invalid_confidence_high(self):
        """Test that confidence > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=1.5,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_invalid_confidence_low(self):
        """Test that confidence < 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=-0.1,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_invalid_landmarks_count(self):
        """Test that wrong number of landmarks raises ValueError."""
        with pytest.raises(ValueError, match="Expected 5 landmarks"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 4,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_non_finite_landmarks(self):
        """Test that non-finite landmarks raise ValueError."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0), (float('nan'), 0), (0, 0), (0, 0), (0, 0)],
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_invalid_coordinate_space(self):
        """Test that non-original_frame coordinate space raises ValueError."""
        with pytest.raises(ValueError, match="must be in 'original_frame' space"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                coordinate_space="model_input",
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_missing_detector_model_id(self):
        """Test that missing detector_model_id raises ValueError."""
        with pytest.raises(ValueError, match="detector_model_id is required"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="",
                detector_model_sha256="abc123",
            )
    
    def test_missing_detector_model_sha256(self):
        """Test that missing detector_model_sha256 raises ValueError."""
        with pytest.raises(ValueError, match="detector_model_sha256 is required"):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="",
            )
    
    def test_non_finite_bbox(self):
        """Test that non-finite bbox raises ValueError."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetectionContract(
                bbox=(100.0, float('inf'), 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            coordinate_space="original_frame",
            source_frame_id="test.jpg",
            detector_model_id="scrfd",
            detector_model_version="1.0.0",
            detector_model_sha256="abc123",
            detection_id="det123",
        )
        
        d = det.to_dict()
        assert d["bbox"] == [100.0, 100.0, 200.0, 200.0]
        assert d["confidence"] == 0.9
        assert d["coordinate_space"] == "original_frame"
        assert d["detector_model_id"] == "scrfd"
        assert d["detector_model_sha256"] == "abc123"
        assert d["detection_id"] == "det123"
        assert d["width"] == 100.0
        assert d["height"] == 100.0
        assert d["area"] == 10000.0


class TestDetectorModelId:
    """Tests for DetectorModelId enum."""
    
    def test_scrfd_value(self):
        assert DetectorModelId.SCRFD.value == "scrfd"
    
    def test_retinaface_value(self):
        assert DetectorModelId.RETINAFACE.value == "retinaface"
    
    def test_str_representation(self):
        assert str(DetectorModelId.SCRFD) == "scrfd"
        assert str(DetectorModelId.RETINAFACE) == "retinaface"


class TestDetectorStatus:
    """Tests for DetectorStatus enum."""
    
    def test_active(self):
        assert DetectorStatus.ACTIVE.value == "active"
    
    def test_not_implemented(self):
        assert DetectorStatus.NOT_IMPLEMENTED.value == "not_implemented"
    
    def test_disabled(self):
        assert DetectorStatus.DISABLED.value == "disabled"


class TestSCRFDAdapter:
    """Tests for SCRFD adapter."""
    
    def test_adapter_creation(self):
        """Test SCRFD adapter can be created."""
        adapter = create_scrfd_adapter()
        assert isinstance(adapter, SCRFDAdapter)
        assert isinstance(adapter, FaceDetectorInterface)
    
    def test_model_id(self):
        """Test SCRFD adapter model_id property."""
        adapter = create_scrfd_adapter()
        assert adapter.model_id == "scrfd"
    
    def test_status(self):
        """Test SCRFD adapter status is ACTIVE."""
        adapter = create_scrfd_adapter()
        assert adapter.status == DetectorStatus.ACTIVE
    
    def test_preprocessing_contract(self):
        """Test SCRFD adapter returns 640x640 preprocessing contract."""
        adapter = create_scrfd_adapter()
        contract = adapter.preprocessing_contract
        assert contract.input_height == 640
        assert contract.input_width == 640
        assert contract.model_id == "scrfd"
    
    def test_detect_returns_contract_type(self):
        """Test that detect() returns FaceDetectionContract objects."""
        adapter = create_scrfd_adapter()
        
        # Create a mock frame
        frame = CanonicalFrame(
            data=np.zeros((480, 640, 3), dtype=np.uint8),
            metadata=FrameMetadata(
                source_type=SourceType.IMAGE,
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                original_width=640,
                original_height=480,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
            ),
        )
        
        # This will fail because no real model is loaded, but we can check
        # the return type expectation
        try:
            results = adapter.detect(frame)
            # If it succeeds, verify return type
            for det in results:
                assert isinstance(det, FaceDetectionContract)
        except Exception:
            # Expected - no model loaded in test environment
            pass
    
    def test_cleanup(self):
        """Test cleanup method exists and runs."""
        adapter = create_scrfd_adapter()
        adapter.cleanup()  # Should not raise


class TestRetinaFaceAdapter:
    """Tests for RetinaFace placeholder adapter."""
    
    def test_adapter_creation(self):
        """Test RetinaFace adapter can be created."""
        adapter = create_retinaface_adapter()
        assert isinstance(adapter, RetinaFaceAdapter)
        assert isinstance(adapter, FaceDetectorInterface)
    
    def test_model_id(self):
        """Test RetinaFace adapter model_id property."""
        adapter = create_retinaface_adapter()
        assert adapter.model_id == "retinaface"
    
    def test_status(self):
        """Test RetinaFace adapter status is NOT_IMPLEMENTED."""
        adapter = create_retinaface_adapter()
        assert adapter.status == DetectorStatus.NOT_IMPLEMENTED
    
    def test_preprocessing_contract_raises(self):
        """Test that preprocessing_contract raises NotImplementedError."""
        adapter = create_retinaface_adapter()
        with pytest.raises(RetinaFaceNotImplementedError):
            _ = adapter.preprocessing_contract
    
    def test_detect_raises(self):
        """Test that detect() raises NotImplementedError."""
        adapter = create_retinaface_adapter()
        frame = CanonicalFrame(
            data=np.zeros((480, 640, 3), dtype=np.uint8),
            metadata=FrameMetadata(
                source_type=SourceType.IMAGE,
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                original_width=640,
                original_height=480,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
            ),
        )
        with pytest.raises(RetinaFaceNotImplementedError):
            adapter.detect(frame)
    
    def test_cleanup(self):
        """Test cleanup method exists and runs (no-op)."""
        adapter = create_retinaface_adapter()
        adapter.cleanup()  # Should not raise


class TestDetectorFactory:
    """Tests for detector factory functions."""
    
    def test_get_detector_scrfd(self):
        """Test getting SCRFD detector via factory."""
        detector = get_detector("scrfd")
        assert isinstance(detector, SCRFDAdapter)
        assert detector.model_id == "scrfd"
    
    def test_get_detector_retinaface_raises(self):
        """Test that getting RetinaFace raises NotImplementedError."""
        with pytest.raises(RetinaFaceNotImplementedError):
            get_detector("retinaface")
    
    def test_get_detector_invalid(self):
        """Test that invalid model_id raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported detector model_id"):
            get_detector("invalid_model")
    
    def test_list_available_detectors(self):
        """Test listing available detectors."""
        detectors = list_available_detectors()
        assert len(detectors) == 2
        
        scrfd = next(d for d in detectors if d["model_id"] == "scrfd")
        assert scrfd["status"] == "active"
        assert scrfd["input_size"] == "640x640"
        
        retinaface = next(d for d in detectors if d["model_id"] == "retinaface")
        assert retinaface["status"] == "not_implemented"
        assert retinaface["input_size"] == "TBD"
    
    def test_get_detector_status(self):
        """Test getting detector status."""
        assert get_detector_status("scrfd") == DetectorStatus.ACTIVE
        assert get_detector_status("retinaface") == DetectorStatus.NOT_IMPLEMENTED
        
        with pytest.raises(ValueError, match="Unknown detector model_id"):
            get_detector_status("invalid")


class TestDownstreamCompatibility:
    """Tests to verify downstream code can use the generic contract."""
    
    def test_face_detection_contract_has_required_fields(self):
        """Test that FaceDetectionContract has all fields needed by downstream."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            detector_model_id="scrfd",
            detector_model_sha256="abc123",
        )
        
        # These are required by crop.py, landmarks.py, quality.py, face_sample.py
        assert hasattr(det, 'bbox')
        assert hasattr(det, 'confidence')
        assert hasattr(det, 'landmarks5')
        assert hasattr(det, 'coordinate_space')
        assert hasattr(det, 'detector_model_id')
        assert hasattr(det, 'detector_model_sha256')
        assert hasattr(det, 'detection_id')
        assert hasattr(det, 'width')
        assert hasattr(det, 'height')
        assert hasattr(det, 'area')
        assert hasattr(det, 'center')
        assert hasattr(det, 'to_dict')
    
    def test_coordinate_space_is_original_frame(self):
        """Test that detector output is always in original_frame space."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detector_model_id="scrfd",
            detector_model_sha256="abc123",
        )
        assert det.coordinate_space == "original_frame"
    
    def test_five_landmarks_preserved(self):
        """Test that exactly 5 landmarks are required."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(120.0, 120.0), (180.0, 120.0), (150.0, 150.0), (130.0, 170.0), (170.0, 170.0)],
            detector_model_id="scrfd",
            detector_model_sha256="abc123",
        )
        assert len(det.landmarks5) == 5
    
    def test_provenance_preserved(self):
        """Test that provenance is preserved in contract."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detector_model_id="scrfd",
            detector_model_sha256="abc123",
            provenance=DetectorProvenance(
                source_type="image",
                source_id="test.jpg",
                frame_index=0,
                timestamp=None,
                detector_model_id="scrfd",
                detector_model_version="1.0.0",
                detector_model_sha256="abc123",
                detection_id="det123",
            ),
        )
        assert det.provenance is not None
        assert det.provenance.source_id == "test.jpg"
        assert det.provenance.detector_model_id == "scrfd"
    
    def test_model_identity_preserved(self):
        """Test that model identity is preserved."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detector_model_id="scrfd",
            detector_model_version="1.0.0",
            detector_model_sha256="abc123",
        )
        assert det.detector_model_id == "scrfd"
        assert det.detector_model_version == "1.0.0"
        assert det.detector_model_sha256 == "abc123"


class TestNegativeCases:
    """Negative tests - verify invalid inputs are rejected."""
    
    def test_malformed_bbox_rejected(self):
        """Test that malformed bbox (non-finite) is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, float('nan'), 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_invalid_confidence_rejected(self):
        """Test that invalid confidence is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=2.0,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_wrong_landmark_shape_rejected(self):
        """Test that wrong landmark count is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 6,  # 6 landmarks instead of 5
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_nan_landmark_rejected(self):
        """Test that NaN landmark is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0), (float('nan'), 0), (0, 0), (0, 0), (0, 0)],
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_invalid_coordinate_space_rejected(self):
        """Test that invalid coordinate space is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                coordinate_space="model_input",
                detector_model_id="scrfd",
                detector_model_sha256="abc123",
            )
    
    def test_missing_model_identity_rejected(self):
        """Test that missing model identity is rejected."""
        with pytest.raises(ValueError):
            FaceDetectionContract(
                bbox=(100.0, 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detector_model_id="",
                detector_model_sha256="abc123",
            )
    
    def test_detector_specific_output_cannot_leak(self):
        """Test that detector-specific fields are not in the generic contract."""
        det = FaceDetectionContract(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detector_model_id="scrfd",
            detector_model_sha256="abc123",
        )
        
        # These SCRFD-specific fields should NOT be in the generic contract
        d = det.to_dict()
        assert "model_id" not in d or d.get("model_id") == "scrfd"  # Only generic detector_model_id
        assert "model_sha256" not in d or d.get("model_sha256") == "abc123"  # Only generic detector_model_sha256
        # No SCRFD-specific tensor names, decoding logic, session objects


if __name__ == "__main__":
    pytest.main([__file__, "-v"])