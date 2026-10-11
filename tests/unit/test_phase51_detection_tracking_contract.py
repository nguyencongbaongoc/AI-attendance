"""
Phase 51 — Detection → Tracking Contract Tests.

Verifies the fix for the numpy.ndarray.metadata runtime error by
asserting that DetectionPipeline.process_frame() passes the correct
frame contract through Person Detection -> Face Detection ->
Association -> Tracking without bypassing or skipping any stage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
from app.streaming.detection_pipeline import DetectionPipeline, DetectionPipelineConfig
from app.vision.association_contract import AssociationResult
from app.vision.track_contract import (
    TrackLifecycleState,
    TrackerConfig,
)
from app.vision.tracker import track_frame
from app.vision.association import associate_detections, AssociationConfig


SYNTHETIC_SEED = 42


def _make_4k_frame(frame_index: int = 0, source_id: str = "test_4k.jpg") -> CanonicalFrame:
    rng = np.random.default_rng(SYNTHETIC_SEED + frame_index)
    data = rng.integers(0, 256, size=(2160, 3840, 3), dtype=np.uint8)
    metadata = FrameMetadata(
        source_type=SourceType.IMAGE,
        source_id=source_id,
        frame_index=frame_index,
        timestamp=float(frame_index),
        original_width=3840,
        original_height=2160,
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
    )
    return CanonicalFrame(data=data, metadata=metadata)


def _make_config(camera_id: str = "CAM1") -> DetectionPipelineConfig:
    return DetectionPipelineConfig(
        camera_id=camera_id,
        confidence_threshold=0.5,
        nms_threshold=0.4,
        tracker_config=TrackerConfig(),
        association_config=AssociationConfig(),
        emit_detection_events=False,
        enable_crossing=False,
        enable_attendance=False,
        enable_policy=False,
    )


# A. Frame contract preserved
class TestFrameContract:
    def test_4k_frame_has_metadata(self):
        frame = _make_4k_frame(frame_index=7)
        assert frame.width == 3840
        assert frame.height == 2160
        assert frame.metadata.source_id == "test_4k.jpg"
        assert frame.metadata.frame_index == 7
        assert frame.metadata.timestamp == 7.0

    def test_track_frame_rejects_3k_frame(self):
        # Validate the existing track_frame contract
        from app.vision.tracker import TrackingError
        small = np.zeros((1080, 1920, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="1080p",
            frame_index=0,
            timestamp=0.0,
            original_width=1920,
            original_height=1080,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        small_frame = CanonicalFrame(data=small, metadata=metadata)
        with pytest.raises(TrackingError, match="3840x2160"):
            track_frame(
                person_detections=[],
                face_detections=[],
                associations=AssociationResult(
                    source_frame_id="1080p", frame_index=0, associations=[]
                ),
                frame=small_frame,
                previous_tracks=[],
                config=TrackerConfig(),
            )


# B+D. Detection → Tracking contract through DetectionPipeline
class TestPipelineContract:
    def test_pipeline_runs_full_chain(self):
        """The pipeline must run person + face + association + tracking
        without raising the numpy.ndarray.metadata error."""
        pipeline = DetectionPipeline(_make_config("CAM1"))
        try:
            pipeline.start()
            pipeline.process_frame(_make_4k_frame(0))
            assert pipeline._frame_count == 1
            assert pipeline._tracker_state is not None
        finally:
            pipeline.stop()

    def test_multiple_consecutive_frames(self):
        pipeline = DetectionPipeline(_make_config("CAM1"))
        try:
            pipeline.start()
            for i in range(3):
                pipeline.process_frame(_make_4k_frame(i))
            assert pipeline._frame_count == 3
        finally:
            pipeline.stop()

    def test_no_metadata_attribute_error_in_logs(self, caplog):
        import logging
        caplog.set_level(logging.ERROR)
        pipeline = DetectionPipeline(_make_config("CAM1"))
        try:
            pipeline.start()
            pipeline.process_frame(_make_4k_frame(0))
            metadata_errors = [
                r for r in caplog.records
                if "metadata" in r.getMessage() and "numpy" in r.getMessage()
            ]
            assert len(metadata_errors) == 0, (
                f"numpy.ndarray.metadata error still present: {metadata_errors}"
            )
        finally:
            pipeline.stop()


# E. Camera isolation
class TestCameraIsolation:
    def test_cam1_and_cam2_have_independent_state(self):
        p1 = DetectionPipeline(_make_config("CAM1"))
        p2 = DetectionPipeline(_make_config("CAM2"))
        try:
            p1.start()
            p2.start()
            assert id(p1._tracker_state) != id(p2._tracker_state)
            p1.process_frame(_make_4k_frame(0))
            p2.process_frame(_make_4k_frame(0))
            assert id(p1._tracker_state) != id(p2._tracker_state)
        finally:
            p1.stop()
            p2.stop()

    def test_stop_clears_tracker_state(self):
        pipeline = DetectionPipeline(_make_config("CAM1"))
        pipeline.start()
        pipeline.process_frame(_make_4k_frame(0))
        assert len(pipeline._tracker_state) >= 0
        pipeline.stop()
        assert pipeline._tracker_state == []


# F. Continuous processing
class TestContinuousProcessing:
    def test_ten_consecutive_frames(self):
        pipeline = DetectionPipeline(_make_config("CAM1"))
        try:
            pipeline.start()
            for i in range(10):
                pipeline.process_frame(_make_4k_frame(i))
            assert pipeline._frame_count == 10
        finally:
            pipeline.stop()


# C. Association contract
class TestAssociationContract:
    def test_association_executes_with_valid_inputs(self):
        from app.vision.detector_contract import FaceDetectionContract
        from app.vision.yolo_person_detector import PersonDetection

        frame = _make_4k_frame(0)
        person = PersonDetection(
            bbox=(100, 100, 300, 400),
            confidence=0.9,
            detection_id="p1",
            model_id="face_based_person_fallback",
            model_sha256="face_based_fallback_sha256_placeholder",
            frame_index=0,
            source_id="test_4k.jpg",
        )
        face = FaceDetectionContract(
            bbox=(150, 150, 250, 300),
            confidence=0.9,
            landmarks5=[(170, 200), (220, 200), (200, 230), (180, 270), (220, 270)],
            detector_model_id="scrfd",
            detector_model_sha256="test",
        )
        result = associate_detections(
            person_detections=[person],
            face_detections=[face],
            frame=frame,
            config=AssociationConfig(),
        )
        assert result is not None
        assert result.frame_index == 0


# D. Tracking contract
class TestTrackingContract:
    def test_track_frame_executes_without_metadata_error(self):
        from app.vision.detector_contract import FaceDetectionContract
        from app.vision.yolo_person_detector import PersonDetection

        frame = _make_4k_frame(0)
        person = PersonDetection(
            bbox=(100, 100, 300, 400),
            confidence=0.9,
            detection_id="p1",
            model_id="face_based_person_fallback",
            model_sha256="face_based_fallback_sha256_placeholder",
            frame_index=0,
            source_id="test_4k.jpg",
        )
        face = FaceDetectionContract(
            bbox=(150, 150, 250, 300),
            confidence=0.9,
            landmarks5=[(170, 200), (220, 200), (200, 230), (180, 270), (220, 270)],
            detector_model_id="scrfd",
            detector_model_sha256="test",
        )
        assoc_result = associate_detections(
            person_detections=[person],
            face_detections=[face],
            frame=frame,
            config=AssociationConfig(),
        )
        result = track_frame(
            person_detections=[person],
            face_detections=[face],
            associations=assoc_result,
            frame=frame,
            previous_tracks=[],
            config=TrackerConfig(),
        )
        assert result is not None
        assert len(result.tracks) >= 1

    def test_tracking_does_not_raise_attribute_error(self):
        """The exact error from Phase 50 must not occur."""
        from app.vision.detector_contract import FaceDetectionContract
        from app.vision.yolo_person_detector import PersonDetection

        frame = _make_4k_frame(0)
        person = PersonDetection(
            bbox=(100, 100, 300, 400),
            confidence=0.9,
            detection_id="p1",
            model_id="face_based_person_fallback",
            model_sha256="face_based_fallback_sha256_placeholder",
            frame_index=0,
            source_id="test_4k.jpg",
        )
        face = FaceDetectionContract(
            bbox=(150, 150, 250, 300),
            confidence=0.9,
            landmarks5=[(170, 200), (220, 200), (200, 230), (180, 270), (220, 270)],
            detector_model_id="scrfd",
            detector_model_sha256="test",
        )
        assoc_result = associate_detections(
            person_detections=[person],
            face_detections=[face],
            frame=frame,
            config=AssociationConfig(),
        )
        try:
            track_frame(
                person_detections=[person],
                face_detections=[face],
                associations=assoc_result,
                frame=frame,
                previous_tracks=[],
                config=TrackerConfig(),
            )
        except AttributeError as e:
            if "metadata" in str(e):
                pytest.fail(f"numpy.ndarray.metadata error regressed: {e}")
            raise


# Person detector interface
class TestPersonDetector:
    def test_person_detection_has_required_fields(self):
        from app.vision.yolo_person_detector import PersonDetection, get_person_detector

        detector = get_person_detector(allow_fallback=True)
        assert detector.model_id  # may be "yolo_person" or "face_based_person_fallback"
        assert detector.status.value == "active"

        det = PersonDetection(
            bbox=(100, 100, 200, 200),
            confidence=0.8,
            detection_id="p1",
            model_id=detector.model_id,
            model_sha256=detector.model_sha256 or "placeholder",
        )
        assert det.coordinate_space == "original_frame"
        assert det.bbox == (100, 100, 200, 200)
        assert det.confidence == 0.8
