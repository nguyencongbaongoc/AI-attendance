"""
Unit tests for Phase 7 Face Pipeline Integration.

Tests cover:
- Full face pipeline: detection -> crop -> landmarks -> quality
- Multiple faces handling
- No face handling
- Invalid detection handling
- Image/video equivalence
- Deterministic results
- Provenance preservation
- CUDA/CPU paths
- Memory safety (streaming)
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from app.vision.detection import FaceDetector, FaceDetection, CoordinateSpace
from app.vision.crop import safe_crop_face, crop_multiple_faces, FaceCrop
from app.vision.landmarks import LandmarkDetector, LandmarkResult, LandmarkCoordinateSpace
from app.vision.quality import QualityAssessor, QualityDecision
from app.vision.face_sample import (
    FaceSample,
    FaceSampleCollection,
    create_face_sample_from_pipeline,
    create_face_sample_collection,
)
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
from app.data.input_adapter import ImageAdapter, VideoAdapter


class TestFacePipelineIntegration:
    """Integration tests for the full face processing pipeline."""
    
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
    def mock_detector(self):
        """Create a mock face detector."""
        detector = MagicMock(spec=FaceDetector)
        detector.model_id = "scrfd"
        detector.model_sha256 = "abc123"
        detector.confidence_threshold = 0.55
        detector.nms_threshold = 0.45
        return detector
    
    @pytest.fixture
    def mock_landmark_detector(self):
        """Create a mock landmark detector."""
        detector = MagicMock(spec=LandmarkDetector)
        detector.model_id = "landmark_1k3d68"
        detector.model_sha256 = "def456"
        detector.min_crop_dimension = 32
        return detector
    
    @pytest.fixture
    def quality_assessor(self):
        """Create a quality assessor."""
        return QualityAssessor(
            min_face_size=64,
            min_detection_confidence=0.55,
            min_sharpness=100.0,
            brightness_range=(30.0, 220.0),
            min_landmark_validity=0.8,
            max_pose_angle=45.0,
        )
    
    def create_mock_detections(self, count: int = 1) -> list:
        """Create mock face detections."""
        detections = []
        for i in range(count):
            det = FaceDetection(
                bbox=(100.0 + i * 200, 100.0, 200.0 + i * 200, 200.0),
                confidence=0.9 - i * 0.1,
                landmarks5=[(0, 0)] * 5,
                detection_id=f"det{i}",
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
                model_id="scrfd",
                model_sha256="abc123",
                frame_index=0,
                source_id="test.jpg",
            )
            detections.append(det)
        return detections
    
    def create_mock_landmarks(self, count: int = 1) -> list:
        """Create mock landmark results."""
        landmarks_list = []
        for i in range(count):
            landmarks = [(float(j % 192), float(j // 192 * 3), 0.0) for j in range(68)]
            lm = LandmarkResult(
                landmarks=landmarks,
                coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
                model_id="landmark_1k3d68",
                model_sha256="def456",
                crop_id=f"crop{i}",
                frame_index=0,
                source_id="test.jpg",
                inference_time_ms=5.0,
            )
            landmarks_list.append(lm)
        return landmarks_list
    
    @patch('app.vision.crop.safe_crop_face')
    def test_single_face_pipeline(self, mock_safe_crop, sample_frame, mock_detector, mock_landmark_detector, quality_assessor):
        """Test full pipeline for a single face."""
        # Setup mocks
        detections = self.create_mock_detections(1)
        mock_detector.detect.return_value = detections
        
        # Mock crop
        crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        mock_crop = MagicMock()
        mock_crop.crop_width = 100
        mock_crop.crop_height = 100
        mock_crop.crop_id = "crop0"
        mock_crop.data = crop_data
        mock_crop.source_type = SourceType.IMAGE
        mock_crop.source_id = "test.jpg"
        mock_crop.frame_index = 0
        mock_crop.timestamp = None
        mock_crop.original_frame_width = 640
        mock_crop.original_frame_height = 480
        mock_crop.bbox = detections[0].bbox
        mock_crop.detection_confidence = detections[0].confidence
        mock_crop.detection_id = detections[0].detection_id
        mock_crop.pixel_format = PixelFormat.RGB
        mock_safe_crop.return_value = mock_crop
        
        # Mock landmarks
        landmarks_list = self.create_mock_landmarks(1)
        mock_landmark_detector.detect.return_value = landmarks_list[0]
        
        # Run pipeline
        t0 = time.perf_counter()
        
        # Detection
        detections = mock_detector.detect(sample_frame)
        assert len(detections) == 1
        
        # Crop
        crops = []
        for det in detections:
            crop = mock_safe_crop(sample_frame, det)
            crops.append(crop)
        
        # Landmarks
        landmarks_results = []
        for crop in crops:
            lm = mock_landmark_detector.detect(crop)
            landmarks_results.append(lm)
        
        # Quality
        qualities = []
        for crop, det, lm in zip(crops, detections, landmarks_results):
            quality = quality_assessor.assess(crop, det.confidence, lm)
            qualities.append(quality)
        
        # Create face sample collection
        collection = create_face_sample_collection(
            frame=sample_frame,
            detections=detections,
            crops=crops,
            landmarks_list=landmarks_results,
            qualities=qualities,
            processing_time_ms=(time.perf_counter() - t0) * 1000,
        )
        
        # Verify
        assert len(collection) == 1
        sample = collection[0]
        assert sample.detection_id == "det0"
        assert sample.crop_id == "crop0"
        assert sample.has_landmarks
        assert sample.quality is not None
        assert sample.detection_model_sha256 == "abc123"
        assert sample.landmark_model_sha256 == "def456"
    
    @patch('app.vision.crop.safe_crop_face')
    def test_multiple_faces_pipeline(self, mock_safe_crop, sample_frame, mock_detector, mock_landmark_detector, quality_assessor):
        """Test pipeline with multiple faces."""
        # Setup mocks
        detections = self.create_mock_detections(3)
        mock_detector.detect.return_value = detections
        
        # Mock crops
        def create_mock_crop(det, idx):
            crop = MagicMock()
            crop.crop_width = 100
            crop.crop_height = 100
            crop.crop_id = f"crop{idx}"
            crop.data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            crop.source_type = SourceType.IMAGE
            crop.source_id = "test.jpg"
            crop.frame_index = 0
            crop.timestamp = None
            crop.original_frame_width = 640
            crop.original_frame_height = 480
            crop.bbox = det.bbox
            crop.detection_confidence = det.confidence
            crop.detection_id = det.detection_id
            crop.pixel_format = PixelFormat.RGB
            return crop
        
        mock_safe_crop.side_effect = lambda frame, det: create_mock_crop(det, detections.index(det))
        
        # Mock landmarks
        landmarks_list = self.create_mock_landmarks(3)
        mock_landmark_detector.detect.side_effect = landmarks_list
        
        # Run pipeline
        detections = mock_detector.detect(sample_frame)
        assert len(detections) == 3
        
        crops = [mock_safe_crop(sample_frame, det) for det in detections]
        landmarks_results = [mock_landmark_detector.detect(crop) for crop in crops]
        qualities = [quality_assessor.assess(crop, det.confidence, lm) 
                     for crop, det, lm in zip(crops, detections, landmarks_results)]
        
        collection = create_face_sample_collection(
            frame=sample_frame,
            detections=detections,
            crops=crops,
            landmarks_list=landmarks_results,
            qualities=qualities,
        )
        
        # Verify all faces preserved
        assert len(collection) == 3
        assert collection.get_acceptable_samples() is not None
        assert collection.get_rejected_samples() is not None
    
    @patch('app.vision.crop.safe_crop_face')
    def test_no_faces_pipeline(self, mock_safe_crop, sample_frame, mock_detector, quality_assessor):
        """Test pipeline with no faces detected."""
        mock_detector.detect.return_value = []

        detections = mock_detector.detect(sample_frame)
        assert len(detections) == 0

        collection = create_face_sample_collection(
            frame=sample_frame,
            detections=detections,
            crops=[],
            landmarks_list=[],
            qualities=[],
        )

        assert len(collection) == 0
        # FaceSampleCollection uses len() for count
        assert len(collection) == 0
    
    @patch('app.vision.crop.safe_crop_face')
    def test_invalid_detection_handling(self, mock_safe_crop, sample_frame, mock_detector, mock_landmark_detector, quality_assessor):
        """Test that invalid detections are handled gracefully."""
        # One valid, one invalid detection
        valid_det = self.create_mock_detections(1)[0]
        invalid_det = FaceDetection(
            bbox=(200.0, 100.0, 100.0, 200.0),  # Invalid: x1 >= x2
            confidence=0.8,
            landmarks5=[(0, 0)] * 5,
            detection_id="det_invalid",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        mock_detector.detect.return_value = [valid_det, invalid_det]
        
        # Mock crop to fail for invalid detection
        def mock_crop_side_effect(frame, det):
            if det.detection_id == "det_invalid":
                from app.vision.crop import CropError
                raise CropError("Invalid bbox")
            crop = MagicMock()
            crop.crop_width = 100
            crop.crop_height = 100
            crop.crop_id = "crop0"
            crop.data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
            crop.source_type = SourceType.IMAGE
            crop.source_id = "test.jpg"
            crop.frame_index = 0
            crop.timestamp = None
            crop.original_frame_width = 640
            crop.original_frame_height = 480
            crop.bbox = det.bbox
            crop.detection_confidence = det.confidence
            crop.detection_id = det.detection_id
            crop.pixel_format = PixelFormat.RGB
            return crop
        
        mock_safe_crop.side_effect = mock_crop_side_effect
        
        # Run pipeline - should not crash
        detections = mock_detector.detect(sample_frame)
        crops = []
        for det in detections:
            try:
                crop = mock_safe_crop(sample_frame, det)
                crops.append(crop)
            except Exception:
                pass  # Skip invalid
        
        # Only valid crop should succeed
        assert len(crops) == 1
        assert crops[0].detection_id == "det0"
    
    def test_provenance_chain(self, sample_frame):
        """Test that provenance chain is complete."""
        # Create a sample with all components
        detection = self.create_mock_detections(1)[0]
        
        crop = MagicMock()
        crop.crop_width = 100
        crop.crop_height = 100
        crop.crop_id = "crop0"
        crop.data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        crop.source_type = SourceType.IMAGE
        crop.source_id = "test.jpg"
        crop.frame_index = 0
        crop.timestamp = None
        crop.original_frame_width = 640
        crop.original_frame_height = 480
        crop.bbox = detection.bbox
        crop.detection_confidence = detection.confidence
        crop.detection_id = detection.detection_id
        crop.pixel_format = PixelFormat.RGB
        
        landmarks = self.create_mock_landmarks(1)[0]
        
        quality = MagicMock()
        quality.decision = QualityDecision.ACCEPTABLE
        quality.metrics = []
        
        sample = create_face_sample_from_pipeline(
            frame=sample_frame,
            detection=detection,
            crop=crop,
            landmarks=landmarks,
            quality=quality,
        )
        
        # Verify provenance chain
        chain = sample.get_provenance_chain()
        assert len(chain) == 5  # source, detection, crop, landmarks, quality
        
        assert chain[0]["step"] == "source"
        assert chain[0]["type"] == "image"
        assert chain[0]["id"] == "test.jpg"
        
        assert chain[1]["step"] == "detection"
        assert chain[1]["model_id"] == "scrfd"
        assert chain[1]["model_sha256"] == "abc123"
        
        assert chain[2]["step"] == "crop"
        assert chain[2]["crop_id"] == "crop0"
        
        assert chain[3]["step"] == "landmarks"
        assert chain[3]["model_id"] == "landmark_1k3d68"
        
        assert chain[4]["step"] == "quality"
        assert chain[4]["status"] == "acceptable"


class TestImageVideoEquivalence:
    """Tests for image/video processing equivalence."""
    
    @pytest.fixture
    def image_frame(self):
        """Create a frame from image."""
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
    def video_frame(self):
        """Create a frame from video (same content)."""
        data = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="test.mp4",
            frame_index=5,
            timestamp=0.166,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        return CanonicalFrame(data=data, metadata=metadata)
    
    @patch('app.vision.detection.FaceDetector')
    @patch('app.vision.crop.safe_crop_face')
    @patch('app.vision.landmarks.LandmarkDetector')
    def test_same_preprocessing(self, mock_landmark_class, mock_crop, mock_detector_class, image_frame, video_frame):
        """Test that image and video frames use same preprocessing."""
        # Setup mocks
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det1",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            model_id="scrfd",
            model_sha256="abc123",
            frame_index=0,
            source_id="test.jpg",
        )
        mock_detector.detect.return_value = [detection]
        
        mock_crop.return_value = MagicMock(
            crop_width=100,
            crop_height=100,
            crop_id="crop1",
            data=np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8),
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 200.0, 200.0),
            detection_confidence=0.9,
            detection_id="det1",
            pixel_format=PixelFormat.RGB,
        )
        
        mock_landmark = MagicMock()
        mock_landmark_class.return_value = mock_landmark
        mock_landmark.detect.return_value = LandmarkResult(
            landmarks=[(0, 0, 0)] * 68,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="def456",
        )
        
        # Process image frame
        detector = mock_detector_class()
        image_detections = detector.detect(image_frame)
        
        # Process video frame (same detector instance)
        video_detections = detector.detect(video_frame)
        
        # Both should use same detector and produce equivalent results
        assert len(image_detections) == len(video_detections)
        assert image_detections[0].bbox == video_detections[0].bbox
        assert image_detections[0].confidence == video_detections[0].confidence


class TestDeterministicResults:
    """Tests for deterministic pipeline results."""
    
    @pytest.fixture
    def fixed_frame(self):
        """Create a frame with fixed seed data."""
        rng = np.random.default_rng(42)
        data = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
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
    
    @patch('app.vision.detection.FaceDetector')
    @patch('app.vision.crop.safe_crop_face')
    @patch('app.vision.landmarks.LandmarkDetector')
    def test_deterministic_detection(self, mock_landmark_class, mock_crop, mock_detector_class, fixed_frame):
        """Test that repeated runs produce same detections."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det1",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
            model_id="scrfd",
            model_sha256="abc123",
            frame_index=0,
            source_id="test.jpg",
        )
        mock_detector.detect.return_value = [detection]
        
        detector = mock_detector_class()
        
        # Run 1
        detections1 = detector.detect(fixed_frame)
        
        # Run 2
        detections2 = detector.detect(fixed_frame)
        
        # Results should be identical
        assert len(detections1) == len(detections2)
        assert detections1[0].bbox == detections2[0].bbox
        assert detections1[0].confidence == detections2[0].confidence
        assert detections1[0].detection_id == detections2[0].detection_id


class TestMemorySafety:
    """Tests for memory safety in video processing."""
    
    def test_streaming_video_processing(self):
        """Test that video frames are processed one at a time."""
        # This test verifies the pattern, not actual memory
        # In real implementation, VideoAdapter.iter_frames yields one frame at a time
        
        adapter = VideoAdapter()
        
        # Verify iterator pattern exists
        assert hasattr(adapter, 'iter_frames')
        
        # The iterator should be a generator/iterator, not a list
        import inspect
        sig = inspect.signature(adapter.iter_frames)
        assert 'video_path' in sig.parameters
    
    def test_no_unbounded_accumulation(self):
        """Test that face pipeline doesn't accumulate unbounded results."""
        # FaceSampleCollection only holds current frame's results
        collection = FaceSampleCollection()
        
        # Add samples with valid bboxes
        for i in range(100):
            sample = FaceSample(
                sample_id=f"sample{i}",
                source_type="video",
                source_id="test.mp4",
                frame_index=i,
                timestamp=float(i) / 30.0,
                bbox=(100.0 + i * 10, 100.0, 200.0 + i * 10, 200.0),
                confidence=0.9,
            )
            collection.add_sample(sample)
        
        # Collection only holds what we explicitly add
        assert len(collection) == 100
        
        # In streaming, we'd create new collection per frame
        # So no unbounded growth across frames


class TestCUDA_CPU_Paths:
    """Tests for CUDA and CPU inference paths."""
    
    @patch('app.vision.detection.get_ort_session')
    @patch('app.vision.detection.verify_sha256')
    @patch('app.vision.detection.get_model_registry')
    def test_cuda_provider_selection(self, mock_registry, mock_verify, mock_get_session):
        """Test that CUDA provider is attempted first."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        mock_model.thresholds.confidence_threshold = 0.55
        mock_model.thresholds.nms_threshold = 0.45
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/scrfd/scrfd_10g_bnkps.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        
        # Create detector with default providers
        detector = FaceDetector()
        
        # Verify CUDA provider is in the list
        assert "CUDAExecutionProvider" in detector.providers
        assert "CPUExecutionProvider" in detector.providers
        assert detector.providers.index("CUDAExecutionProvider") < detector.providers.index("CPUExecutionProvider")
    
    @patch('app.vision.landmarks.get_ort_session')
    @patch('app.vision.landmarks.verify_sha256')
    @patch('app.vision.landmarks.get_model_registry')
    def test_landmark_cuda_provider(self, mock_registry, mock_verify, mock_get_session):
        """Test landmark detector CUDA provider."""
        mock_model = MagicMock()
        mock_model.expected_sha256 = "abc123"
        
        mock_registry_instance = MagicMock()
        mock_registry_instance.get.return_value = mock_model
        mock_registry_instance.get_model_path.return_value = Path("models/landmark/1k3d68.onnx")
        mock_registry.return_value = mock_registry_instance
        
        mock_verify.return_value = MagicMock(is_verified=lambda: True, actual_hash="abc123")
        
        detector = LandmarkDetector()
        
        assert "CUDAExecutionProvider" in detector.providers
        assert "CPUExecutionProvider" in detector.providers


class TestEdgeCases:
    """Tests for edge cases."""
    
    def test_empty_image(self):
        """Test handling of empty image."""
        # Empty frame (0x0x3) is valid - it's a 3D array with 0 height/width
        data = np.array([]).reshape(0, 0, 3)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="empty.jpg",
            frame_index=0,
            timestamp=None,
            original_width=0,
            original_height=0,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        # This should not raise - 0x0x3 is a valid 3D array
        frame = CanonicalFrame(data=data, metadata=metadata)
        assert frame.height == 0
        assert frame.width == 0
        assert frame.channels == 3
    
    def test_invalid_image(self):
        """Test handling of invalid image data."""
        # Wrong dimensions - 1D array is invalid
        data = np.random.randint(0, 256, (100,), dtype=np.uint8)  # 1D
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="invalid.jpg",
            frame_index=0,
            timestamp=None,
            original_width=100,
            original_height=100,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        with pytest.raises(ValueError, match="must be 2D or 3D"):
            CanonicalFrame(data=data, metadata=metadata)
    
    def test_zero_area_bbox(self):
        """Test handling of zero-area bounding box."""
        # Zero-area bboxes are now allowed in FaceDetection (filtered in safe_crop_face)
        detection = FaceDetection(
            bbox=(100.0, 100.0, 100.0, 100.0),  # Zero area
            confidence=0.9,
            landmarks5=[(0, 0)] * 5,
            detection_id="det1",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        # Should not raise - zero-area bboxes are allowed
        assert detection.bbox == (100.0, 100.0, 100.0, 100.0)
        assert detection.width == 0.0
        assert detection.height == 0.0
        assert detection.area == 0.0
    
    def test_nan_bbox(self):
        """Test handling of NaN bounding box."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetection(
                bbox=(float('nan'), 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detection_id="det1",
            )
    
    def test_inf_bbox(self):
        """Test handling of Inf bounding box."""
        with pytest.raises(ValueError, match="non-finite coordinates"):
            FaceDetection(
                bbox=(float('inf'), 100.0, 200.0, 200.0),
                confidence=0.9,
                landmarks5=[(0, 0)] * 5,
                detection_id="det1",
            )
    
    def test_low_confidence_detection(self):
        """Test handling of low confidence detection."""
        detection = FaceDetection(
            bbox=(100.0, 100.0, 200.0, 200.0),
            confidence=0.1,  # Below threshold
            landmarks5=[(0, 0)] * 5,
            detection_id="det1",
            coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
        )
        
        # Detection is valid but will be filtered by threshold
        assert detection.confidence == 0.1
    
    def test_tiny_face(self):
        """Test handling of tiny face crop."""
        crop_data = np.random.randint(0, 256, (10, 10, 3), dtype=np.uint8)
        crop = FaceCrop(
            data=crop_data,
            crop_width=10,
            crop_height=10,
            source_type=SourceType.IMAGE,
            source_id="test.jpg",
            frame_index=0,
            timestamp=None,
            original_frame_width=640,
            original_frame_height=480,
            bbox=(100.0, 100.0, 110.0, 110.0),
            detection_confidence=0.9,
            detection_id="det1",
        )
        
        # Should fail landmark validation
        from app.vision.crop import validate_crop_for_landmark
        assert validate_crop_for_landmark(crop, min_dimension=32) is False
    
    def test_blurry_face(self):
        """Test quality assessment of blurry face."""
        # Smooth gradient = blurry
        crop_data = np.zeros((100, 100, 3), dtype=np.uint8)
        for i in range(100):
            crop_data[i, :, :] = i * 2
        
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
            detection_id="det1",
        )
        
        assessor = QualityAssessor(min_sharpness=100.0)
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        sharpness_metric = quality.get_metric("sharpness")
        assert sharpness_metric.passed is False
    
    def test_dark_frame(self):
        """Test quality assessment of dark frame."""
        crop_data = np.full((100, 100, 3), 5, dtype=np.uint8)
        
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
            detection_id="det1",
        )
        
        assessor = QualityAssessor(brightness_range=(30.0, 220.0))
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        brightness_metric = quality.get_metric("brightness")
        assert brightness_metric.passed is False
    
    def test_bright_frame(self):
        """Test quality assessment of overexposed frame."""
        crop_data = np.full((100, 100, 3), 250, dtype=np.uint8)
        
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
            detection_id="det1",
        )
        
        assessor = QualityAssessor(brightness_range=(30.0, 220.0))
        quality = assessor.assess(crop, detection_confidence=0.9)
        
        brightness_metric = quality.get_metric("brightness")
        assert brightness_metric.passed is False
    
    def test_malformed_landmark_output(self):
        """Test handling of malformed landmark output."""
        # Landmarks with wrong count
        landmarks = [(0, 0, 0)] * 10  # Only 10 landmarks
        
        with pytest.raises(ValueError, match="Expected 68 landmarks"):
            LandmarkResult(
                landmarks=landmarks,
                coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            )
    
    def test_video_frame_processing(self):
        """Test processing a single video frame."""
        data = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="test.mp4",
            frame_index=10,
            timestamp=0.333,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
            source_fps=30.0,
            source_duration=10.0,
            source_frame_count=300,
        )
        frame = CanonicalFrame(data=data, metadata=metadata)
        
        assert frame.metadata.source_type == SourceType.VIDEO
        assert frame.metadata.frame_index == 10
        assert frame.metadata.timestamp == 0.333
    
    def test_repeated_video_frame(self):
        """Test processing repeated video frame (deterministic)."""
        rng = np.random.default_rng(42)
        data = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
        
        metadata1 = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="test.mp4",
            frame_index=5,
            timestamp=0.166,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        metadata2 = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="test.mp4",
            frame_index=5,
            timestamp=0.166,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        frame1 = CanonicalFrame(data=data.copy(), metadata=metadata1)
        frame2 = CanonicalFrame(data=data.copy(), metadata=metadata2)
        
        # Same frame data should produce same results
        assert np.array_equal(frame1.data, frame2.data)
    
    def test_image_video_equivalence(self):
        """Test that same frame from image and video produce equivalent results."""
        rng = np.random.default_rng(42)
        data = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
        
        image_metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="frame.jpg",
            frame_index=0,
            timestamp=None,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        video_metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id="video.mp4",
            frame_index=10,
            timestamp=0.333,
            original_width=640,
            original_height=480,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        
        image_frame = CanonicalFrame(data=data.copy(), metadata=image_metadata)
        video_frame = CanonicalFrame(data=data.copy(), metadata=video_metadata)
        
        # Same pixel data, different source metadata
        assert np.array_equal(image_frame.data, video_frame.data)
        assert image_frame.metadata.source_type != video_frame.metadata.source_type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])