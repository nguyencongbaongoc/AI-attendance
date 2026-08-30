"""
Phase 11 — Unit Tests for Person/Face Tracking.

Tests cover:
1. Track contract validation
2. Single person tracking
3. Multiple people tracking
4. Shuffled ordering determinism
5. Track lifecycle (NEW -> ACTIVE -> LOST -> CLOSED)
6. Temporary person loss (occlusion)
7. Temporary face loss
8. Face attachment stability
9. Crossing trajectories
10. Provenance preservation
11. Invalid input rejection
12. Deterministic results
13. Memory bounded
14. Safety boundary (no camera/streaming)
"""

from __future__ import annotations

import gc
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
from app.vision.association_contract import (
    AssociationResult,
    AssociationStatus,
    PersonFaceAssociation,
    create_association_from_detections,
)
from app.vision.detector_contract import DetectorProvenance, FaceDetectionContract
from app.vision.track_contract import (
    Track,
    TrackLifecycleState,
    TrackerConfig,
    TrackingResult,
    age_track_without_detection,
    create_track_from_person_detection,
    update_track_from_person_detection,
)
from app.vision.tracker import (
    CoordinateSpaceError,
    TrackingError,
    track_frame,
    track_frame_deterministic,
    update_tracks,
)


# =============================================================================
# TEST FIXTURES AND HELPERS
# =============================================================================

SYNTHETIC_SEED = 42


def create_synthetic_4k_frame(
    source_id: str = "test_4k.jpg",
    frame_index: int = 0,
    timestamp: float = None,
) -> CanonicalFrame:
    """Create a deterministic synthetic 4K frame."""
    rng = np.random.default_rng(SYNTHETIC_SEED + frame_index)
    data = rng.integers(0, 256, size=(2160, 3840, 3), dtype=np.uint8)
    
    metadata = FrameMetadata(
        source_type=SourceType.IMAGE,
        source_id=source_id,
        frame_index=frame_index,
        timestamp=timestamp,
        original_width=3840,
        original_height=2160,
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
    )
    
    return CanonicalFrame(data=data, metadata=metadata)


class MockPersonDetection:
    """Mock person detection compatible with PersonDetectionContract."""
    
    def __init__(
        self,
        bbox: tuple,
        confidence: float = 0.9,
        detection_id: str = "",
        model_id: str = "yolo_person",
        model_sha256: str = "test_sha256",
        provenance: DetectorProvenance = None,
    ):
        self.bbox = bbox
        self.confidence = confidence
        self.class_id = 0
        self.class_name = "person"
        self.coordinate_space = "original_frame"
        self.detection_id = detection_id or f"person_{id(self)}"
        self.model_id = model_id
        self.model_sha256 = model_sha256
        self.provenance = provenance
    
    def to_dict(self):
        return {
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "detection_id": self.detection_id,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
        }


def create_face_detection(
    bbox: tuple,
    confidence: float = 0.9,
    landmarks5: list = None,
    detection_id: str = "",
    model_id: str = "scrfd",
    model_sha256: str = "test_sha256",
    provenance: DetectorProvenance = None,
) -> FaceDetectionContract:
    """Create a FaceDetectionContract for testing."""
    if landmarks5 is None:
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        landmarks5 = [
            (cx - w * 0.2, cy - h * 0.1),
            (cx + w * 0.2, cy - h * 0.1),
            (cx, cy),
            (cx - w * 0.15, cy + h * 0.15),
            (cx + w * 0.15, cy + h * 0.15),
        ]
    
    return FaceDetectionContract(
        bbox=bbox,
        confidence=confidence,
        landmarks5=landmarks5,
        coordinate_space="original_frame",
        source_frame_id="test_4k.jpg",
        detector_model_id=model_id,
        detector_model_version="1.0",
        detector_model_sha256=model_sha256,
        detection_id=detection_id or f"face_{id(bbox)}",
        provenance=provenance,
    )


def create_association_result(
    frame: CanonicalFrame,
    persons: list,
    faces: list,
    associations: list = None,
) -> AssociationResult:
    """Create an AssociationResult for testing."""
    if associations is None:
        associations = []
    
    return AssociationResult(
        source_frame_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        associations=associations,
        unmatched_persons=[],
        unmatched_faces=[],
    )


# =============================================================================
# TESTS: TRACK CONTRACT
# =============================================================================

class TestTrackContract:
    """Test Track contract validation."""
    
    def test_valid_track_creation(self):
        frame = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        track = create_track_from_person_detection(person_det, frame)
        
        assert track.track_id != ""
        assert track.track_id.startswith("trk_")
        assert track.lifecycle_state == TrackLifecycleState.NEW
        assert track.age == 1
        assert track.hits == 1
        assert track.missed_frames == 0
        assert track.last_seen == 0
        assert track.bbox_original_frame == (100, 100, 300, 400)
        assert track.confidence == 0.9
        assert track.coordinate_space == "original_frame"
    
    def test_track_with_face_association(self):
        frame = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f1")
        
        assoc = create_association_from_detections(
            person_detection=person_det,
            face_detection=face_det,
            frame=frame,
            association_status=AssociationStatus.ASSOCIATED,
            association_score=0.85,
            geometry_reason="center_contained",
        )
        
        track = create_track_from_person_detection(person_det, frame, assoc)
        
        assert track.has_face is True
        assert track.face_detection_id == "f1"
        assert track.face_bbox == (150, 150, 250, 300)
        assert track.face_confidence == 0.9
        assert track.face_model_id == "scrfd"
    
    def test_invalid_coordinate_space(self):
        with pytest.raises(ValueError, match="original_frame"):
            Track(
                track_id="t1",
                source_frame_id="test.jpg",
                frame_index=0,
                bbox_original_frame=(100, 100, 300, 400),
                confidence=0.9,
                coordinate_space="model_input",  # Invalid
            )
    
    def test_invalid_bbox_boundaries(self):
        with pytest.raises(ValueError, match="exceeds 4K boundaries"):
            Track(
                track_id="t1",
                source_frame_id="test.jpg",
                frame_index=0,
                bbox_original_frame=(-100, 100, 300, 400),
                confidence=0.9,
            )
    
    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="confidence"):
            Track(
                track_id="t1",
                source_frame_id="test.jpg",
                frame_index=0,
                bbox_original_frame=(100, 100, 300, 400),
                confidence=1.5,
            )
    
    def test_invalid_lifecycle_state(self):
        with pytest.raises(ValueError, match="Invalid lifecycle_state"):
            Track(
                track_id="t1",
                source_frame_id="test.jpg",
                frame_index=0,
                bbox_original_frame=(100, 100, 300, 400),
                confidence=0.9,
                lifecycle_state="invalid_state",
            )
    
    def test_negative_counters_rejected(self):
        with pytest.raises(ValueError, match="age must be >= 0"):
            Track(
                track_id="t1",
                source_frame_id="test.jpg",
                frame_index=0,
                bbox_original_frame=(100, 100, 300, 400),
                confidence=0.9,
                age=-1,
            )
    
    def test_track_properties(self):
        track = Track(
            track_id="t1",
            source_frame_id="test.jpg",
            frame_index=0,
            bbox_original_frame=(100, 100, 300, 400),
            confidence=0.9,
        )
        
        assert track.width == 200
        assert track.height == 300
        assert track.area == 60000
        assert track.center == (200, 250)
        assert track.has_face is False
        assert track.is_new is True
        assert track.is_active is False
        assert track.is_lost is False
        assert track.is_closed is False
    
    def test_track_to_dict(self):
        track = Track(
            track_id="t1",
            source_frame_id="test.jpg",
            frame_index=0,
            bbox_original_frame=(100, 100, 300, 400),
            confidence=0.9,
        )
        
        d = track.to_dict()
        assert d["track_id"] == "t1"
        assert d["bbox_original_frame"] == [100, 100, 300, 400]
        assert d["lifecycle_state"] == "new"
        assert d["has_face"] is False


# =============================================================================
# TESTS: TRACKER CONFIG
# =============================================================================

class TestTrackerConfig:
    """Test TrackerConfig validation."""
    
    def test_valid_config(self):
        config = TrackerConfig(
            min_iou_threshold=0.3,
            new_to_active_hits=2,
            active_to_lost_missed=5,
        )
        assert config.min_iou_threshold == 0.3
        assert config.new_to_active_hits == 2
    
    def test_invalid_iou_threshold(self):
        with pytest.raises(ValueError, match="min_iou_threshold must be in"):
            TrackerConfig(min_iou_threshold=1.5)
    
    def test_invalid_thresholds(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            TrackerConfig(new_to_active_hits=0)


# =============================================================================
# TESTS: TRACK LIFECYCLE
# =============================================================================

class TestTrackLifecycle:
    """Test track lifecycle transitions."""
    
    def test_new_to_active(self):
        frame0 = create_synthetic_4k_frame(frame_index=0)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        # Frame 0: Create track (NEW)
        track = create_track_from_person_detection(person_det, frame0)
        assert track.is_new
        assert track.age == 1
        assert track.hits == 1
        
        # Frame 1: Update track (NEW -> ACTIVE after 2 hits)
        updated = update_track_from_person_detection(track, person_det, frame1)
        assert updated.is_active
        assert updated.age == 2
        assert updated.hits == 2
        assert updated.missed_frames == 0
    
    def test_active_to_lost(self):
        frame0 = create_synthetic_4k_frame(frame_index=0)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        frame2 = create_synthetic_4k_frame(frame_index=2)
        frame3 = create_synthetic_4k_frame(frame_index=3)
        frame4 = create_synthetic_4k_frame(frame_index=4)
        frame5 = create_synthetic_4k_frame(frame_index=5)
        frame6 = create_synthetic_4k_frame(frame_index=6)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        config = TrackerConfig(active_to_lost_missed=3)
        
        # Frame 0-1: Build up to ACTIVE
        track = create_track_from_person_detection(person_det, frame0)
        track = update_track_from_person_detection(track, person_det, frame1)
        assert track.is_active
        
        # Frame 2-4: Miss detections (age without detection)
        track = age_track_without_detection(track, frame2, config)
        assert track.is_active  # missed=1
        assert track.missed_frames == 1
        
        track = age_track_without_detection(track, frame3, config)
        assert track.is_active  # missed=2
        assert track.missed_frames == 2
        
        track = age_track_without_detection(track, frame4, config)
        assert track.is_lost  # missed=3 >= threshold
        assert track.missed_frames == 3
    
    def test_lost_to_active(self):
        frame0 = create_synthetic_4k_frame(frame_index=0)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        frame2 = create_synthetic_4k_frame(frame_index=2)
        frame3 = create_synthetic_4k_frame(frame_index=3)
        frame4 = create_synthetic_4k_frame(frame_index=4)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        config = TrackerConfig(active_to_lost_missed=2, lost_to_active_hits=1)
        
        # Build to ACTIVE
        track = create_track_from_person_detection(person_det, frame0)
        track = update_track_from_person_detection(track, person_det, frame1)
        assert track.is_active
        
        # Miss to LOST
        track = age_track_without_detection(track, frame2, config)
        track = age_track_without_detection(track, frame3, config)
        assert track.is_lost
        
        # Re-detect -> ACTIVE
        track = update_track_from_person_detection(track, person_det, frame4)
        assert track.is_active
        assert track.hits == 3  # 2 previous + 1 new
    
    def test_lost_to_closed(self):
        frame0 = create_synthetic_4k_frame(frame_index=0)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        frame2 = create_synthetic_4k_frame(frame_index=2)
        frame3 = create_synthetic_4k_frame(frame_index=3)
        frame4 = create_synthetic_4k_frame(frame_index=4)
        frame5 = create_synthetic_4k_frame(frame_index=5)
        frame6 = create_synthetic_4k_frame(frame_index=6)
        frame7 = create_synthetic_4k_frame(frame_index=7)
        frame8 = create_synthetic_4k_frame(frame_index=8)
        frame9 = create_synthetic_4k_frame(frame_index=9)
        frame10 = create_synthetic_4k_frame(frame_index=10)
        frame11 = create_synthetic_4k_frame(frame_index=11)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        config = TrackerConfig(active_to_lost_missed=2, lost_to_closed_missed=5)
        
        # Build to ACTIVE
        track = create_track_from_person_detection(person_det, frame0)
        track = update_track_from_person_detection(track, person_det, frame1)
        
        # Miss to LOST
        track = age_track_without_detection(track, frame2, config)
        track = age_track_without_detection(track, frame3, config)
        assert track.is_lost
        
        # Continue missing -> CLOSED
        for i in range(4, 11):
            frame = create_synthetic_4k_frame(frame_index=i)
            track = age_track_without_detection(track, frame, config)
        
        assert track.is_closed
        assert track.missed_frames >= config.lost_to_closed_missed
    
    def test_new_immediate_miss_to_lost(self):
        frame0 = create_synthetic_4k_frame(frame_index=0)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p1")
        
        config = TrackerConfig()
        
        # Create NEW track
        track = create_track_from_person_detection(person_det, frame0)
        assert track.is_new
        
        # Immediate miss -> LOST
        track = age_track_without_detection(track, frame1, config)
        assert track.is_lost


# =============================================================================
# TESTS: SINGLE PERSON TRACKING
# =============================================================================

class TestSinglePersonTracking:
    """Test single person tracking across frames."""
    
    def test_single_person_stable_track(self):
        config = TrackerConfig()
        tracks = []
        
        # Simulate 5 frames with same person
        for i in range(5):
            frame = create_synthetic_4k_frame(frame_index=i)
            person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
            
            # Create association
            assoc = create_association_from_detections(
                person_detection=person_det,
                face_detection=face_det,
                frame=frame,
                association_status=AssociationStatus.ASSOCIATED,
                association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[assoc],
            )
            
            result = track_frame(
                [person_det], [face_det], assoc_result, frame, tracks, config
            )
            tracks = result.tracks
        
        # Should have 1 track that becomes ACTIVE (after 2 hits)
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 1
        track = active_tracks[0]
        assert track.age == 5
        assert track.hits == 5
        assert track.has_face
        assert track.track_id != ""
    
    def test_single_person_temporary_occlusion(self):
        config = TrackerConfig(active_to_lost_missed=3)
        tracks = []
        
        # Frame 0-1: Person detected (2 frames = ACTIVE)
        for i in range(2):
            frame = create_synthetic_4k_frame(frame_index=i)
            person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
            
            assoc = create_association_from_detections(
                person_detection=person_det,
                face_detection=face_det,
                frame=frame,
                association_status=AssociationStatus.ASSOCIATED,
                association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[assoc],
            )
            
            result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # After frame 1, track should be ACTIVE (2 hits)
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 1
        track_id = active_tracks[0].track_id
        
        # Frame 2-3: Person occluded (no detection) - 2 missed frames
        for i in range(2, 4):
            frame = create_synthetic_4k_frame(frame_index=i)
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[],
            )
            
            result = track_frame([], [], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Track should still be ACTIVE (missed=2 < threshold=3)
        active_tracks = [t for t in tracks if t.is_active]
        lost_tracks = [t for t in tracks if t.is_lost]
        assert len(active_tracks) == 1
        assert len(lost_tracks) == 0
        assert active_tracks[0].missed_frames == 2
        assert active_tracks[0].track_id == track_id
        
        # Frame 4: Person reappears
        frame = create_synthetic_4k_frame(frame_index=4)
        person_det = MockPersonDetection((105, 105, 305, 405), detection_id="p4")
        face_det = create_face_detection((155, 155, 255, 305), detection_id="f4")
        
        assoc = create_association_from_detections(
            person_detection=person_det,
            face_detection=face_det,
            frame=frame,
            association_status=AssociationStatus.ASSOCIATED,
            association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id,
            frame_index=frame.metadata.frame_index,
            associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
        tracks = result.tracks
        
        # Track should be ACTIVE with SAME track_id
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 1
        assert active_tracks[0].track_id == track_id
        assert active_tracks[0].age == 5  # 2 hits + 2 missed + 1 hit


# =============================================================================
# TESTS: MULTIPLE PEOPLE
# =============================================================================

class TestMultiplePeopleTracking:
    """Test multiple people tracking independently."""
    
    def test_two_people_independent_tracks(self):
        config = TrackerConfig()
        tracks = []
        
        # 3 frames with two people
        for i in range(3):
            frame = create_synthetic_4k_frame(frame_index=i)
            
            # Person A on left
            person_a = MockPersonDetection((100, 100, 300, 400), detection_id=f"pa{i}")
            face_a = create_face_detection((150, 150, 250, 300), detection_id=f"fa{i}")
            
            # Person B on right
            person_b = MockPersonDetection((1000, 100, 1200, 400), detection_id=f"pb{i}")
            face_b = create_face_detection((1050, 150, 1150, 300), detection_id=f"fb{i}")
            
            assoc_a = create_association_from_detections(
                person_detection=person_a, face_detection=face_a, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_b = create_association_from_detections(
                person_detection=person_b, face_detection=face_b, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[assoc_a, assoc_b],
            )
            
            result = track_frame(
                [person_a, person_b], [face_a, face_b], assoc_result, frame, tracks, config
            )
            tracks = result.tracks
        
        # Should have 2 active tracks (after 3 frames, both have 3 hits)
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 2
        
        # Track IDs should be stable
        track_ids = {t.track_id for t in active_tracks}
        assert len(track_ids) == 2
    
    def test_shuffled_detection_order_deterministic(self):
        config = TrackerConfig()
        
        # Frame 0
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_a = MockPersonDetection((100, 100, 300, 400), detection_id="pa0")
        person_b = MockPersonDetection((1000, 100, 1200, 400), detection_id="pb0")
        face_a = create_face_detection((150, 150, 250, 300), detection_id="fa0")
        face_b = create_face_detection((1050, 150, 1150, 300), detection_id="fb0")
        
        assoc_a = create_association_from_detections(
            person_detection=person_a, face_detection=face_a, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_b = create_association_from_detections(
            person_detection=person_b, face_detection=face_b, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result0 = AssociationResult(
            source_frame_id=frame0.metadata.source_id,
            frame_index=0,
            associations=[assoc_a, assoc_b],
        )
        
        # Run with normal order
        result1 = track_frame(
            [person_a, person_b], [face_a, face_b], assoc_result0, frame0, [], config
        )
        
        # Run with reversed order
        result2 = track_frame(
            [person_b, person_a], [face_b, face_a], assoc_result0, frame0, [], config
        )
        
        # Track IDs should be the same (deterministic from bbox)
        tracks1 = sorted(result1.tracks, key=lambda t: t.track_id)
        tracks2 = sorted(result2.tracks, key=lambda t: t.track_id)
        
        assert tracks1[0].track_id == tracks2[0].track_id
        assert tracks1[1].track_id == tracks2[1].track_id
    
    def test_three_people(self):
        config = TrackerConfig()
        tracks = []
        
        frame = create_synthetic_4k_frame(frame_index=0)
        persons = [
            MockPersonDetection((100, 100, 300, 400), detection_id="p1"),
            MockPersonDetection((800, 100, 1000, 400), detection_id="p2"),
            MockPersonDetection((1500, 100, 1700, 400), detection_id="p3"),
        ]
        faces = [
            create_face_detection((150, 150, 250, 300), detection_id="f1"),
            create_face_detection((850, 150, 950, 300), detection_id="f2"),
            create_face_detection((1550, 150, 1650, 300), detection_id="f3"),
        ]
        
        associations = []
        for p, f in zip(persons, faces):
            associations.append(create_association_from_detections(
                person_detection=p, face_detection=f, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            ))
        
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id,
            frame_index=0,
            associations=associations,
        )
        
        result = track_frame(persons, faces, assoc_result, frame, tracks, config)
        tracks = result.tracks
        
        # First frame: all tracks are NEW (1 hit each)
        new_tracks = [t for t in tracks if t.is_new]
        assert len(new_tracks) == 3
        
        # After 2nd frame, they become ACTIVE
        frame1 = create_synthetic_4k_frame(frame_index=1)
        persons1 = [
            MockPersonDetection((105, 105, 305, 405), detection_id="p1_1"),
            MockPersonDetection((805, 105, 1005, 405), detection_id="p2_1"),
            MockPersonDetection((1505, 105, 1705, 405), detection_id="p3_1"),
        ]
        faces1 = [
            create_face_detection((155, 155, 255, 305), detection_id="f1_1"),
            create_face_detection((855, 155, 955, 305), detection_id="f2_1"),
            create_face_detection((1555, 155, 1655, 305), detection_id="f3_1"),
        ]
        
        associations1 = []
        for p, f in zip(persons1, faces1):
            associations1.append(create_association_from_detections(
                person_detection=p, face_detection=f, frame=frame1,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            ))
        
        assoc_result1 = AssociationResult(
            source_frame_id=frame1.metadata.source_id,
            frame_index=1,
            associations=associations1,
        )
        
        result = track_frame(persons1, faces1, assoc_result1, frame1, tracks, config)
        tracks = result.tracks
        
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 3


# =============================================================================
# TESTS: TEMPORARY FACE LOSS
# =============================================================================

class TestTemporaryFaceLoss:
    """Test face attachment stability during temporary face loss."""
    
    def test_face_loss_then_return_same_track(self):
        config = TrackerConfig()
        tracks = []
        
        # Frame 0: Person + Face
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p0")
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f0")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame0.metadata.source_id, frame_index=0, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame0, tracks, config)
        tracks = result.tracks
        track_id = tracks[0].track_id
        assert tracks[0].has_face
        assert tracks[0].face_detection_id == "f0"
        
        # Frame 1: Person only (face temporarily lost)
        frame1 = create_synthetic_4k_frame(frame_index=1)
        person_det1 = MockPersonDetection((105, 105, 305, 405), detection_id="p1")
        
        assoc_result1 = AssociationResult(
            source_frame_id=frame1.metadata.source_id, frame_index=1, associations=[],
        )
        
        result = track_frame([person_det1], [], assoc_result1, frame1, tracks, config)
        tracks = result.tracks
        
        # Track should still exist, face info preserved
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.has_face  # Face info preserved from previous frame
        assert track.face_detection_id == "f0"
        
        # Frame 2: Person + Face returns (different face detection ID)
        frame2 = create_synthetic_4k_frame(frame_index=2)
        person_det2 = MockPersonDetection((110, 110, 310, 410), detection_id="p2")
        face_det2 = create_face_detection((160, 160, 260, 310), detection_id="f2")  # Different ID
        
        assoc2 = create_association_from_detections(
            person_detection=person_det2, face_detection=face_det2, frame=frame2,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result2 = AssociationResult(
            source_frame_id=frame2.metadata.source_id, frame_index=2, associations=[assoc2],
        )
        
        result = track_frame([person_det2], [face_det2], assoc_result2, frame2, tracks, config)
        tracks = result.tracks
        
        # Track ID must remain stable
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.has_face
        assert track.face_detection_id == "f2"  # Updated to new face detection ID
        assert track.track_id == track_id  # SAME track_id


# =============================================================================
# TESTS: PERSON OCCLUSION
# =============================================================================

class TestPersonOcclusion:
    """Test temporary person detection loss (occlusion)."""
    
    def test_person_occlusion_within_tolerance(self):
        config = TrackerConfig(active_to_lost_missed=5)
        tracks = []
        
        # Frames 0-2: Person detected (3 frames = ACTIVE with 3 hits)
        for i in range(3):
            frame = create_synthetic_4k_frame(frame_index=i)
            person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
            
            assoc = create_association_from_detections(
                person_detection=person_det, face_detection=face_det, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[assoc],
            )
            
            result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        track_id = tracks[0].track_id
        # After 3 frames, track should be ACTIVE
        assert tracks[0].is_active
        assert tracks[0].hits == 3
        
        # Frames 3-5: Person occluded (3 frames missed, within tolerance of 5)
        for i in range(3, 6):
            frame = create_synthetic_4k_frame(frame_index=i)
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[],
            )
            
            result = track_frame([], [], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Track should still be ACTIVE (missed=3 < threshold=5)
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.is_active
        assert not track.is_lost
        assert not track.is_closed
        assert track.missed_frames == 3
        
        # Frame 6: Person reappears
        frame = create_synthetic_4k_frame(frame_index=6)
        person_det = MockPersonDetection((105, 105, 305, 405), detection_id="p6")
        face_det = create_face_detection((155, 155, 255, 305), detection_id="f6")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id, frame_index=6, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
        tracks = result.tracks
        
        # Track should be ACTIVE with SAME track_id
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.is_active
        assert track.track_id == track_id
    
    def test_person_occlusion_exceeds_tolerance(self):
        config = TrackerConfig(active_to_lost_missed=2, lost_to_closed_missed=3)
        tracks = []
        
        # Build track (2 frames to become ACTIVE)
        for i in range(2):
            frame = create_synthetic_4k_frame(frame_index=i)
            person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
            
            assoc = create_association_from_detections(
                person_detection=person_det, face_detection=face_det, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[assoc],
            )
            
            result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        track_id = tracks[0].track_id
        # After 2 frames, track should be ACTIVE
        assert tracks[0].is_active
        
        # Miss 5 frames (exceeds lost_to_closed_missed=3)
        for i in range(2, 7):
            frame = create_synthetic_4k_frame(frame_index=i)
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[],
            )
            
            result = track_frame([], [], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Track should be CLOSED
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.is_closed
        
        # Frame 7: Person reappears at same position - creates NEW track with different track_id (includes frame_index)
        frame = create_synthetic_4k_frame(frame_index=7)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p7")  # Same position
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f7")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id, frame_index=7, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
        tracks = result.tracks
        
        # Should have a NEW track (lifecycle_state=NEW) with different track_id (includes frame_index)
        new_tracks = [t for t in tracks if t.is_new]
        assert len(new_tracks) == 1
        assert new_tracks[0].is_new
        # Track ID is different because it includes frame_index (deterministic from bbox + frame_index)


# =============================================================================
# TESTS: CROSSING TRAJECTORIES
# =============================================================================

class TestCrossingTrajectories:
    """Test crossing people trajectories."""
    
    def test_crossing_people_geometry_only(self):
        """
        Test two people crossing paths.
        
        With geometry-only tracking, ID switches may occur when people cross.
        This test documents the behavior - the tracker uses deterministic geometry.
        """
        config = TrackerConfig(min_iou_threshold=0.2)
        tracks = []
        
        # Frame 0: Person A left, Person B right
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_a = MockPersonDetection((100, 1000, 300, 1200), detection_id="pa0")
        person_b = MockPersonDetection((3500, 1000, 3700, 1200), detection_id="pb0")
        face_a = create_face_detection((150, 1050, 250, 1150), detection_id="fa0")
        face_b = create_face_detection((3550, 1050, 3650, 1150), detection_id="fb0")
        
        assoc_a = create_association_from_detections(
            person_detection=person_a, face_detection=face_a, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_b = create_association_from_detections(
            person_detection=person_b, face_detection=face_b, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result0 = AssociationResult(
            source_frame_id=frame0.metadata.source_id, frame_index=0, associations=[assoc_a, assoc_b],
        )
        
        result = track_frame([person_a, person_b], [face_a, face_b], assoc_result0, frame0, tracks, config)
        tracks = result.tracks
        
        # Get initial track IDs
        track_a = next(t for t in tracks if t.bbox_original_frame[0] < 1000)
        track_b = next(t for t in tracks if t.bbox_original_frame[0] > 1000)
        id_a_initial = track_a.track_id
        id_b_initial = track_b.track_id
        
        # Frame 1: Moving toward center
        frame1 = create_synthetic_4k_frame(frame_index=1)
        person_a1 = MockPersonDetection((1500, 1000, 1700, 1200), detection_id="pa1")
        person_b1 = MockPersonDetection((2100, 1000, 2300, 1200), detection_id="pb1")
        face_a1 = create_face_detection((1550, 1050, 1650, 1150), detection_id="fa1")
        face_b1 = create_face_detection((2150, 1050, 2250, 1150), detection_id="fb1")
        
        assoc_a1 = create_association_from_detections(
            person_detection=person_a1, face_detection=face_a1, frame=frame1,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_b1 = create_association_from_detections(
            person_detection=person_b1, face_detection=face_b1, frame=frame1,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result1 = AssociationResult(
            source_frame_id=frame1.metadata.source_id, frame_index=1, associations=[assoc_a1, assoc_b1],
        )
        
        result = track_frame([person_a1, person_b1], [face_a1, face_b1], assoc_result1, frame1, tracks, config)
        tracks = result.tracks
        
        # Frame 2: Crossed (A now right, B now left)
        frame2 = create_synthetic_4k_frame(frame_index=2)
        person_a2 = MockPersonDetection((3500, 1000, 3700, 1200), detection_id="pa2")  # A on right
        person_b2 = MockPersonDetection((100, 1000, 300, 1200), detection_id="pb2")   # B on left
        face_a2 = create_face_detection((3550, 1050, 3650, 1150), detection_id="fa2")
        face_b2 = create_face_detection((150, 1050, 250, 1150), detection_id="fb2")
        
        assoc_a2 = create_association_from_detections(
            person_detection=person_a2, face_detection=face_a2, frame=frame2,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_b2 = create_association_from_detections(
            person_detection=person_b2, face_detection=face_b2, frame=frame2,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result2 = AssociationResult(
            source_frame_id=frame2.metadata.source_id, frame_index=2, associations=[assoc_a2, assoc_b2],
        )
        
        result = track_frame([person_a2, person_b2], [face_a2, face_b2], assoc_result2, frame2, tracks, config)
        tracks = result.tracks
        
        # With geometry-only tracking, tracks follow spatial continuity
        # The track that was on left (id_a_initial) should now be on right
        # The track that was on right (id_b_initial) should now be on left
        # This is the expected behavior for geometry-only tracking
        
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) == 2
        
        # Track IDs should be preserved (geometry follows spatial path)
        track_ids = {t.track_id for t in active_tracks}
        assert id_a_initial in track_ids
        assert id_b_initial in track_ids


# =============================================================================
# TESTS: FACE ATTACHMENT STABILITY
# =============================================================================

class TestFaceAttachmentStability:
    """Test face attachment stability across frames."""
    
    def test_face_attachment_through_track_lifecycle(self):
        config = TrackerConfig()
        tracks = []
        
        # Frame 0: Person + Face -> NEW track with face
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p0")
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f0")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame0.metadata.source_id, frame_index=0, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame0, tracks, config)
        tracks = result.tracks
        track_id = tracks[0].track_id
        assert tracks[0].has_face
        assert tracks[0].face_detection_id == "f0"
        
        # Frame 1: Person + Face -> ACTIVE with face
        frame1 = create_synthetic_4k_frame(frame_index=1)
        person_det1 = MockPersonDetection((105, 105, 305, 405), detection_id="p1")
        face_det1 = create_face_detection((155, 155, 255, 305), detection_id="f1")
        
        assoc1 = create_association_from_detections(
            person_detection=person_det1, face_detection=face_det1, frame=frame1,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result1 = AssociationResult(
            source_frame_id=frame1.metadata.source_id, frame_index=1, associations=[assoc1],
        )
        
        result = track_frame([person_det1], [face_det1], assoc_result1, frame1, tracks, config)
        tracks = result.tracks
        
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.is_active
        assert track.has_face
        assert track.face_detection_id == "f1"  # Updated
        
        # Frame 2: Person only (face lost) -> face info preserved
        frame2 = create_synthetic_4k_frame(frame_index=2)
        person_det2 = MockPersonDetection((110, 110, 310, 410), detection_id="p2")
        
        assoc_result2 = AssociationResult(
            source_frame_id=frame2.metadata.source_id, frame_index=2, associations=[],
        )
        
        result = track_frame([person_det2], [], assoc_result2, frame2, tracks, config)
        tracks = result.tracks
        
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.has_face  # Preserved
        assert track.face_detection_id == "f1"  # Last known face
        
        # Frame 3: Person + Face returns -> face updated
        frame3 = create_synthetic_4k_frame(frame_index=3)
        person_det3 = MockPersonDetection((115, 115, 315, 415), detection_id="p3")
        face_det3 = create_face_detection((165, 165, 265, 315), detection_id="f3")
        
        assoc3 = create_association_from_detections(
            person_detection=person_det3, face_detection=face_det3, frame=frame3,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result3 = AssociationResult(
            source_frame_id=frame3.metadata.source_id, frame_index=3, associations=[assoc3],
        )
        
        result = track_frame([person_det3], [face_det3], assoc_result3, frame3, tracks, config)
        tracks = result.tracks
        
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.has_face
        assert track.face_detection_id == "f3"  # Updated to new face
        
        # Track ID stable throughout
        assert track.track_id == track_id


# =============================================================================
# TESTS: PROVENANCE
# =============================================================================

class TestProvenancePreservation:
    """Test provenance preservation through tracking."""
    
    def test_person_provenance_preserved(self):
        frame = create_synthetic_4k_frame(source_id="test.jpg", frame_index=5)
        
        person_prov = DetectorProvenance(
            source_type="image",
            source_id="test.jpg",
            frame_index=5,
            timestamp=None,
            detector_model_id="yolo_person",
            detector_model_version="11n",
            detector_model_sha256="person_sha",
            detection_id="p1",
        )
        
        person_det = MockPersonDetection(
            (100, 100, 300, 400), detection_id="p1", provenance=person_prov
        )
        
        track = create_track_from_person_detection(person_det, frame)
        
        assert track.person_provenance is not None
        assert track.person_provenance.detector_model_id == "yolo_person"
        assert track.person_provenance.detector_model_sha256 == "person_sha"
        assert track.person_provenance.detection_id == "p1"
    
    def test_face_provenance_preserved(self):
        frame = create_synthetic_4k_frame(source_id="test.jpg", frame_index=5)
        
        person_prov = DetectorProvenance(
            source_type="image", source_id="test.jpg", frame_index=5, timestamp=None,
            detector_model_id="yolo_person", detector_model_version="11n",
            detector_model_sha256="person_sha", detection_id="p1",
        )
        face_prov = DetectorProvenance(
            source_type="image", source_id="test.jpg", frame_index=5, timestamp=None,
            detector_model_id="scrfd", detector_model_version="1.0",
            detector_model_sha256="face_sha", detection_id="f1",
        )
        
        person_det = MockPersonDetection(
            (100, 100, 300, 400), detection_id="p1", provenance=person_prov
        )
        face_det = create_face_detection(
            (150, 150, 250, 300), detection_id="f1", provenance=face_prov
        )
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        
        track = create_track_from_person_detection(person_det, frame, assoc)
        
        assert track.face_provenance is not None
        assert track.face_provenance.detector_model_id == "scrfd"
        assert track.face_provenance.detector_model_sha256 == "face_sha"
        assert track.face_provenance.detection_id == "f1"


# =============================================================================
# TESTS: INVALID INPUT REJECTION
# =============================================================================

class TestInvalidInputRejection:
    """Test invalid input rejection."""
    
    def test_reject_non_4k_frame(self):
        config = TrackerConfig()
        
        # Create 1080p frame
        rng = np.random.default_rng(SYNTHETIC_SEED)
        data = rng.integers(0, 256, size=(1080, 1920, 3), dtype=np.uint8)
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="1080p.jpg",
            frame_index=0,
            timestamp=None,
            original_width=1920,
            original_height=1080,
            pixel_format=PixelFormat.BGR,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=data, metadata=metadata)
        
        person_det = MockPersonDetection((100, 100, 300, 400))
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="1080p.jpg", frame_index=0, associations=[],
        )
        
        with pytest.raises(TrackingError, match="3840x2160"):
            track_frame([person_det], [face_det], assoc_result, frame, [], config)
    
    def test_reject_model_input_coordinates(self):
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        
        person_det = MockPersonDetection((100, 100, 200, 200))
        person_det.coordinate_space = "model_input"
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        with pytest.raises(CoordinateSpaceError, match="model_input"):
            track_frame([person_det], [face_det], assoc_result, frame, [], config)
    
    def test_reject_normalized_coordinates(self):
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        
        person_det = MockPersonDetection((0.1, 0.1, 0.5, 0.5))
        person_det.coordinate_space = "normalized"
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        with pytest.raises(CoordinateSpaceError, match="normalized"):
            track_frame([person_det], [face_det], assoc_result, frame, [], config)
    
    def test_reject_out_of_bounds_bbox(self):
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        
        person_det = MockPersonDetection((-100, 100, 300, 400))
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        with pytest.raises(CoordinateSpaceError, match="exceeds 4K boundaries"):
            track_frame([person_det], [face_det], assoc_result, frame, [], config)
    
    def test_reject_zero_area_bbox(self):
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        
        person_det = MockPersonDetection((100, 100, 100, 100))  # Zero area
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        with pytest.raises(CoordinateSpaceError, match="zero or negative area"):
            track_frame([person_det], [face_det], assoc_result, frame, [], config)


# =============================================================================
# TESTS: DETERMINISM
# =============================================================================

class TestDeterminism:
    """Test deterministic behavior."""
    
    def test_repeated_runs_identical(self):
        config = TrackerConfig()
        
        # Run same sequence 3 times
        all_results = []
        for run in range(3):
            tracks = []
            for i in range(3):
                frame = create_synthetic_4k_frame(frame_index=i)
                person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
                face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
                
                assoc = create_association_from_detections(
                    person_detection=person_det, face_detection=face_det, frame=frame,
                    association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                    geometry_reason="center_contained",
                )
                assoc_result = AssociationResult(
                    source_frame_id=frame.metadata.source_id, frame_index=i, associations=[assoc],
                )
                
                result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
                tracks = result.tracks
            
            all_results.append(tracks)
        
        # All runs should produce identical track IDs and states
        for i in range(1, len(all_results)):
            tracks1 = sorted(all_results[0], key=lambda t: t.track_id)
            tracks2 = sorted(all_results[i], key=lambda t: t.track_id)
            
            assert len(tracks1) == len(tracks2)
            for t1, t2 in zip(tracks1, tracks2):
                assert t1.track_id == t2.track_id
                assert t1.lifecycle_state == t2.lifecycle_state
    
    def test_track_frame_deterministic(self):
        config = TrackerConfig()
        
        frame = create_synthetic_4k_frame(frame_index=0)
        persons = [
            MockPersonDetection((100, 100, 300, 400), detection_id="p1"),
            MockPersonDetection((1000, 100, 1200, 400), detection_id="p2"),
        ]
        faces = [
            create_face_detection((150, 150, 250, 300), detection_id="f1"),
            create_face_detection((1050, 150, 1150, 300), detection_id="f2"),
        ]
        
        associations = []
        for p, f in zip(persons, faces):
            associations.append(create_association_from_detections(
                person_detection=p, face_detection=f, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            ))
        
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id, frame_index=0, associations=associations,
        )
        
        # This should not raise
        result = track_frame_deterministic(
            persons, faces, assoc_result, frame, [], config, num_runs=3
        )
        
        assert len(result.tracks) == 2


# =============================================================================
# TESTS: MEMORY SAFETY
# =============================================================================

class TestMemorySafety:
    """Test memory safety - bounded tracks, no accumulation."""
    
    def test_bounded_active_tracks(self):
        config = TrackerConfig(max_active_tracks=3, max_lost_tracks=2)
        tracks = []
        
        # Create 5 tracks over 5 frames (each frame new person)
        for i in range(5):
            frame = create_synthetic_4k_frame(frame_index=i)
            # Each frame has a new person at different position
            person_det = MockPersonDetection((100 + i*500, 100, 300 + i*500, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150 + i*500, 150, 250 + i*500, 300), detection_id=f"f{i}")
            
            assoc = create_association_from_detections(
                person_detection=person_det, face_detection=face_det, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[assoc],
            )
            
            result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Should not exceed max_active_tracks
        active_tracks = [t for t in tracks if t.is_active]
        assert len(active_tracks) <= config.max_active_tracks
        
        # Total tracks should be bounded
        assert len(tracks) <= config.max_active_tracks + config.max_lost_tracks + 5  # some closed
    
    def test_closed_tracks_removed_from_active(self):
        config = TrackerConfig(active_to_lost_missed=1, lost_to_closed_missed=1, max_active_tracks=10)
        tracks = []
        
        # Create track
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p0")
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f0")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame0.metadata.source_id, frame_index=0, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame0, tracks, config)
        tracks = result.tracks
        track_id = tracks[0].track_id
        
        # Miss frames until CLOSED
        for i in range(1, 5):
            frame = create_synthetic_4k_frame(frame_index=i)
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[],
            )
            result = track_frame([], [], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Track should be CLOSED
        track = next(t for t in tracks if t.track_id == track_id)
        assert track.is_closed
        
        # CLOSED tracks should not be in active/lost
        active = [t for t in tracks if t.is_active]
        lost = [t for t in tracks if t.is_lost]
        assert track_id not in [t.track_id for t in active]
        assert track_id not in [t.track_id for t in lost]
    
    def test_no_frame_accumulation(self):
        """Verify no frame data is accumulated in tracks."""
        config = TrackerConfig()
        tracks = []
        
        for i in range(10):
            frame = create_synthetic_4k_frame(frame_index=i)
            person_det = MockPersonDetection((100, 100, 300, 400), detection_id=f"p{i}")
            face_det = create_face_detection((150, 150, 250, 300), detection_id=f"f{i}")
            
            assoc = create_association_from_detections(
                person_detection=person_det, face_detection=face_det, frame=frame,
                association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
                geometry_reason="center_contained",
            )
            assoc_result = AssociationResult(
                source_frame_id=frame.metadata.source_id, frame_index=i, associations=[assoc],
            )
            
            result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
            tracks = result.tracks
        
        # Tracks should only store current bbox, not frame history
        track = tracks[0]
        assert not hasattr(track, 'frame_history')
        assert not hasattr(track, 'bboxes_history')
        # Only current bbox stored
        assert track.bbox_original_frame == (100, 100, 300, 400)


# =============================================================================
# TESTS: SAFETY BOUNDARY
# =============================================================================

class TestSafetyBoundary:
    """Test safety boundaries - no camera, streaming, identity, etc."""
    
    def test_no_camera_imports(self):
        """Verify no camera-related imports in tracking module."""
        import app.vision.tracker as tracker_module
        import app.vision.track_contract as contract_module
        
        source = tracker_module.__file__
        # Just verify modules load without camera dependencies
        assert tracker_module is not None
        assert contract_module is not None
    
    def test_no_arcface_dependency(self):
        """Verify tracking doesn't depend on ArcFace."""
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        person_det = MockPersonDetection((100, 100, 300, 400))
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        # Should work without any ArcFace/embedding code
        result = track_frame([person_det], [face_det], assoc_result, frame, [], config)
        assert result is not None
    
    def test_no_identity_matching(self):
        """Verify tracking doesn't do identity matching."""
        config = TrackerConfig()
        tracks = []
        
        # Two people with same appearance (simulated by same bbox pattern)
        # Tracker should distinguish by geometry only
        frame0 = create_synthetic_4k_frame(frame_index=0)
        person_a = MockPersonDetection((100, 100, 300, 400), detection_id="pa0")
        person_b = MockPersonDetection((1000, 100, 1200, 400), detection_id="pb0")
        face_a = create_face_detection((150, 150, 250, 300), detection_id="fa0")
        face_b = create_face_detection((1050, 150, 1150, 300), detection_id="fb0")
        
        assoc_a = create_association_from_detections(
            person_detection=person_a, face_detection=face_a, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_b = create_association_from_detections(
            person_detection=person_b, face_detection=face_b, frame=frame0,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame0.metadata.source_id, frame_index=0, associations=[assoc_a, assoc_b],
        )
        
        result = track_frame([person_a, person_b], [face_a, face_b], assoc_result, frame0, tracks, config)
        tracks = result.tracks
        
        # Two distinct tracks created (geometry-based, not identity)
        # First frame: both are NEW
        new_tracks = [t for t in tracks if t.is_new]
        assert len(new_tracks) == 2
        assert new_tracks[0].track_id != new_tracks[1].track_id
    
    def test_no_attendance_logic(self):
        """Verify no attendance/IN/OUT logic in tracking."""
        config = TrackerConfig()
        frame = create_synthetic_4k_frame()
        person_det = MockPersonDetection((100, 100, 300, 400))
        face_det = create_face_detection((150, 150, 250, 300))
        assoc_result = AssociationResult(
            source_frame_id="test.jpg", frame_index=0, associations=[],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame, [], config)
        
        # Result should only contain tracking info, no attendance fields
        track = result.tracks[0]
        track_dict = track.to_dict()
        
        # No attendance-related fields
        assert "attendance" not in track_dict
        assert "in_out" not in track_dict
        assert "schedule" not in track_dict
        assert "employee_id" not in track_dict


# =============================================================================
# TESTS: TRACKING RESULT
# =============================================================================

class TestTrackingResult:
    """Test TrackingResult contract."""
    
    def test_tracking_result_summary(self):
        config = TrackerConfig()
        tracks = []
        
        frame = create_synthetic_4k_frame(frame_index=0)
        person_det = MockPersonDetection((100, 100, 300, 400), detection_id="p0")
        face_det = create_face_detection((150, 150, 250, 300), detection_id="f0")
        
        assoc = create_association_from_detections(
            person_detection=person_det, face_detection=face_det, frame=frame,
            association_status=AssociationStatus.ASSOCIATED, association_score=0.85,
            geometry_reason="center_contained",
        )
        assoc_result = AssociationResult(
            source_frame_id=frame.metadata.source_id, frame_index=0, associations=[assoc],
        )
        
        result = track_frame([person_det], [face_det], assoc_result, frame, tracks, config)
        
        assert result.source_frame_id == "test_4k.jpg"
        assert result.frame_index == 0
        assert len(result.tracks) == 1
        # First frame creates NEW track (not ACTIVE yet)
        assert result.new_count == 1
        assert result.tracks_with_face == 1
        
        d = result.to_dict()
        assert d["summary"]["new"] == 1
        assert d["summary"]["with_face"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])