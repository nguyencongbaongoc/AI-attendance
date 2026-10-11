"""
Phase 27 — Unit Tests for Replay Annotation Contracts.

Tests annotation contract serialization, deserialization, and validation.
"""

import pytest
import json
from app.replay.annotation import (
    AnnotationFrame,
    PersonAnnotation,
    FaceAnnotation,
    EventAnnotation,
    AttendanceAnnotation,
    GlobalObservationReference,
    AnnotationProvenance,
    BoundingBox,
    IdentityDisplayState,
    AttendanceDisplayState,
    EventDisplayType,
    generate_annotation_frame_id,
)


class TestBoundingBox:
    """Tests for BoundingBox contract."""
    
    def test_bbox_creation(self):
        bbox = BoundingBox(x=10.0, y=20.0, width=100.0, height=150.0)
        assert bbox.x == 10.0
        assert bbox.y == 20.0
        assert bbox.width == 100.0
        assert bbox.height == 150.0
    
    def test_bbox_serialization(self):
        bbox = BoundingBox(x=10.0, y=20.0, width=100.0, height=150.0)
        data = bbox.to_dict()
        assert data == {"x": 10.0, "y": 20.0, "width": 100.0, "height": 150.0}
        
        restored = BoundingBox.from_dict(data)
        assert restored.x == bbox.x
        assert restored.y == bbox.y
        assert restored.width == bbox.width
        assert restored.height == bbox.height
    
    def test_bbox_json_roundtrip(self):
        bbox = BoundingBox(x=10.0, y=20.0, width=100.0, height=150.0)
        json_str = json.dumps(bbox.to_dict())
        restored = BoundingBox.from_dict(json.loads(json_str))
        assert restored == bbox


class TestPersonAnnotation:
    """Tests for PersonAnnotation contract."""
    
    def test_person_annotation_minimal(self):
        bbox = BoundingBox(x=0, y=0, width=100, height=200)
        ann = PersonAnnotation(bbox=bbox, local_track_id="track_001")
        
        assert ann.bbox == bbox
        assert ann.local_track_id == "track_001"
        assert ann.identity_certainty == IdentityDisplayState.UNKNOWN
        assert ann.identity_confidence == 0.0
    
    def test_person_annotation_full(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        face_bbox = BoundingBox(x=30, y=40, width=50, height=60)
        
        ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
            similarity=0.95,
            face_bbox=face_bbox,
            face_quality_class="GOOD",
            face_quality_score=0.9,
            face_quality_reasons=("sharp", "frontal"),
            pose_state="frontal",
            pose_angles=(0.0, 0.0, 0.0),
            attendance_state=AttendanceDisplayState.PRESENT,
            attendance_decision_id="ATT-xyz789",
            detection_id="det_001",
            face_crop_id="face_001",
            track_provenance={"camera_id": "CAM1", "frame_index": 100},
        )
        
        assert ann.identity_certainty == IdentityDisplayState.KNOWN
        assert ann.identity_confidence == 0.95
        assert ann.similarity == 0.95
        assert ann.face_bbox == face_bbox
        assert ann.face_quality_class == "GOOD"
        assert ann.attendance_state == AttendanceDisplayState.PRESENT
    
    def test_person_annotation_serialization(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
        )
        
        data = ann.to_dict()
        assert data["local_track_id"] == "track_001"
        assert data["identity_candidate"] == "HS001"
        assert data["identity_certainty"] == "known"
        assert data["identity_confidence"] == 0.95
        
        restored = PersonAnnotation.from_dict(data)
        assert restored.local_track_id == ann.local_track_id
        assert restored.identity_candidate == ann.identity_candidate
        assert restored.identity_certainty == ann.identity_certainty
        assert restored.identity_confidence == ann.identity_confidence
    
    def test_person_annotation_json_roundtrip(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
        )
        
        json_str = json.dumps(ann.to_dict())
        restored = PersonAnnotation.from_dict(json.loads(json_str))
        assert restored == ann
    
    def test_person_annotation_unknown_identity(self):
        """Test that UNKNOWN identity is explicitly represented."""
        bbox = BoundingBox(x=0, y=0, width=100, height=200)
        ann = PersonAnnotation(bbox=bbox, local_track_id="track_001")
        
        assert ann.identity_certainty == IdentityDisplayState.UNKNOWN
        assert ann.identity_candidate is None
        assert ann.identity_confidence == 0.0
        
        data = ann.to_dict()
        assert data["identity_certainty"] == "unknown"
        assert data["identity_candidate"] is None


class TestFaceAnnotation:
    """Tests for FaceAnnotation contract."""
    
    def test_face_annotation_creation(self):
        bbox = BoundingBox(x=30, y=40, width=50, height=60)
        ann = FaceAnnotation(bbox=bbox)
        
        assert ann.bbox == bbox
        assert ann.quality_class is None
        assert ann.identity_similarity is None
    
    def test_face_annotation_full(self):
        bbox = BoundingBox(x=30, y=40, width=50, height=60)
        ann = FaceAnnotation(
            bbox=bbox,
            quality_class="GOOD",
            quality_score=0.92,
            quality_reasons=("sharp", "frontal", "well_lit"),
            pose_state="frontal",
            pose_angles=(0.1, -0.05, 0.0),
            identity_similarity=0.88,
            identity_candidate="HS001",
            detection_id="det_001",
            face_crop_id="face_001",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
        )
        
        assert ann.quality_class == "GOOD"
        assert ann.quality_score == 0.92
        assert ann.identity_similarity == 0.88
        assert ann.identity_candidate == "HS001"
    
    def test_face_annotation_serialization(self):
        bbox = BoundingBox(x=30, y=40, width=50, height=60)
        ann = FaceAnnotation(
            bbox=bbox,
            quality_class="GOOD",
            quality_score=0.92,
            identity_similarity=0.88,
        )
        
        data = ann.to_dict()
        assert data["quality_class"] == "GOOD"
        assert data["quality_score"] == 0.92
        assert data["identity_similarity"] == 0.88
        
        restored = FaceAnnotation.from_dict(data)
        assert restored.quality_class == ann.quality_class
        assert restored.quality_score == ann.quality_score
        assert restored.identity_similarity == ann.identity_similarity


class TestEventAnnotation:
    """Tests for EventAnnotation contract."""
    
    def test_crossing_event_annotation(self):
        ann = EventAnnotation(
            event_type=EventDisplayType.CROSSING,
            event_id="CE-001",
            direction="enter",
            timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            crossing_event_id="CE-001",
            crossing_direction="enter",
            geometry_version=1,
            geometry_config_hash="abc123",
        )
        
        assert ann.event_type == EventDisplayType.CROSSING
        assert ann.direction == "enter"
        assert ann.crossing_event_id == "CE-001"
        assert ann.geometry_version == 1
    
    def test_raw_in_out_event_annotation(self):
        ann = EventAnnotation(
            event_type=EventDisplayType.IN,
            event_id="RIE-001",
            direction="in",
            timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
            raw_event_id="RIE-001",
        )
        
        assert ann.event_type == EventDisplayType.IN
        assert ann.raw_event_id == "RIE-001"
    
    def test_resolved_transition_event_annotation(self):
        ann = EventAnnotation(
            event_type=EventDisplayType.OUT,
            event_id="RT-001",
            direction="out",
            timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
            resolution_id="RT-001",
            previous_state="inside",
            new_state="outside",
            resolver_version="1.0",
            resolver_config_hash="hash123",
        )
        
        assert ann.event_type == EventDisplayType.OUT
        assert ann.resolution_id == "RT-001"
        assert ann.previous_state == "inside"
        assert ann.new_state == "outside"
    
    def test_event_annotation_serialization(self):
        ann = EventAnnotation(
            event_type=EventDisplayType.CROSSING,
            event_id="CE-001",
            direction="enter",
            timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
        )
        
        data = ann.to_dict()
        assert data["event_type"] == "crossing"
        assert data["event_id"] == "CE-001"
        assert data["direction"] == "enter"
        
        restored = EventAnnotation.from_dict(data)
        assert restored.event_type == ann.event_type
        assert restored.event_id == ann.event_id


class TestAttendanceAnnotation:
    """Tests for AttendanceAnnotation contract."""
    
    def test_attendance_annotation_present(self):
        ann = AttendanceAnnotation(
            attendance_state=AttendanceDisplayState.PRESENT,
            decision_reason="WITHIN_ENTRY_WINDOW",
            person_identity="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
            timetable_id="TT-001",
            session_id="S-001",
            day="MONDAY",
            event_timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
            attendance_decision_id="ATT-001",
            attendance_policy_id="POL-001",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown",
            new_attendance_state="present",
        )
        
        assert ann.attendance_state == AttendanceDisplayState.PRESENT
        assert ann.decision_reason == "WITHIN_ENTRY_WINDOW"
        assert ann.person_identity == "HS001"
    
    def test_attendance_annotation_late(self):
        ann = AttendanceAnnotation(
            attendance_state=AttendanceDisplayState.LATE,
            decision_reason="LATE_WITHIN_TOLERANCE",
            person_identity="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
            timetable_id="TT-001",
            session_id="S-001",
            day="MONDAY",
            event_timestamp=123.45,
            camera_id="CAM1",
            local_track_id="track_001",
            attendance_decision_id="ATT-002",
            attendance_policy_id="POL-001",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown",
            new_attendance_state="late",
        )
        
        assert ann.attendance_state == AttendanceDisplayState.LATE
        assert ann.decision_reason == "LATE_WITHIN_TOLERANCE"
    
    def test_attendance_annotation_serialization(self):
        ann = AttendanceAnnotation(
            attendance_state=AttendanceDisplayState.PRESENT,
            decision_reason="WITHIN_ENTRY_WINDOW",
            person_identity="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
        )
        
        data = ann.to_dict()
        assert data["attendance_state"] == "present"
        assert data["decision_reason"] == "WITHIN_ENTRY_WINDOW"
        assert data["person_identity"] == "HS001"
        assert data["identity_certainty"] == "known"
        
        restored = AttendanceAnnotation.from_dict(data)
        assert restored.attendance_state == ann.attendance_state
        assert restored.decision_reason == ann.decision_reason


class TestGlobalObservationReference:
    """Tests for GlobalObservationReference contract."""
    
    def test_global_observation_reference_creation(self):
        ref = GlobalObservationReference(
            global_observation_id="GO-abc123",
            association_state="associated",
            camera_ids=("CAM1", "CAM2"),
            local_track_ids=("CAM1:track_001", "CAM2:track_002"),
            temporal_start=100.0,
            temporal_end=105.0,
            temporal_span=5.0,
            primary_identity_candidate="HS001",
            identity_confidence=0.95,
            identity_state="confident",
        )
        
        assert ref.global_observation_id == "GO-abc123"
        assert ref.association_state == "associated"
        assert ref.camera_ids == ("CAM1", "CAM2")
        assert ref.local_track_ids == ("CAM1:track_001", "CAM2:track_002")
    
    def test_global_observation_reference_serialization(self):
        ref = GlobalObservationReference(
            global_observation_id="GO-abc123",
            association_state="associated",
            camera_ids=("CAM1", "CAM2"),
            local_track_ids=("CAM1:track_001", "CAM2:track_002"),
            temporal_start=100.0,
            temporal_end=105.0,
            temporal_span=5.0,
        )
        
        data = ref.to_dict()
        assert data["global_observation_id"] == "GO-abc123"
        assert data["association_state"] == "associated"
        assert data["camera_ids"] == ["CAM1", "CAM2"]
        assert data["local_track_ids"] == ["CAM1:track_001", "CAM2:track_002"]
        
        restored = GlobalObservationReference.from_dict(data)
        assert restored.global_observation_id == ref.global_observation_id
        assert restored.association_state == ref.association_state


class TestAnnotationProvenance:
    """Tests for AnnotationProvenance contract."""
    
    def test_provenance_creation(self):
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        assert prov.source_video_id == "CAM1_video"
        assert prov.camera_id == "CAM1"
        assert prov.source_frame_index == 100
        assert prov.source_timestamp == 123.45
    
    def test_provenance_serialization(self):
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        data = prov.to_dict()
        assert data["source_video_id"] == "CAM1_video"
        assert data["camera_id"] == "CAM1"
        assert data["source_frame_index"] == 100
        
        restored = AnnotationProvenance.from_dict(data)
        assert restored.source_video_id == prov.source_video_id
        assert restored.camera_id == prov.camera_id


class TestAnnotationFrame:
    """Tests for AnnotationFrame contract."""
    
    def test_annotation_frame_minimal(self):
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        frame = AnnotationFrame(
            camera_id="CAM1",
            frame_index=100,
            timestamp=123.45,
            timestamp_source="pts",
            source_frame_reference="CAM1_video:100",
            provenance=prov,
        )
        
        assert frame.camera_id == "CAM1"
        assert frame.frame_index == 100
        assert frame.timestamp == 123.45
        assert frame.timestamp_source == "pts"
        assert len(frame.person_annotations) == 0
        assert len(frame.face_annotations) == 0
    
    def test_annotation_frame_with_annotations(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        person_ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
        )
        
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        frame = AnnotationFrame(
            camera_id="CAM1",
            frame_index=100,
            timestamp=123.45,
            timestamp_source="pts",
            source_frame_reference="CAM1_video:100",
            person_annotations=(person_ann,),
            provenance=prov,
        )
        
        assert len(frame.person_annotations) == 1
        assert frame.person_annotations[0].local_track_id == "track_001"
    
    def test_annotation_frame_serialization(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        person_ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
        )
        
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        frame = AnnotationFrame(
            camera_id="CAM1",
            frame_index=100,
            timestamp=123.45,
            timestamp_source="pts",
            source_frame_reference="CAM1_video:100",
            person_annotations=(person_ann,),
            provenance=prov,
        )
        
        data = frame.to_dict()
        assert data["camera_id"] == "CAM1"
        assert data["frame_index"] == 100
        assert len(data["person_annotations"]) == 1
        assert data["person_annotations"][0]["local_track_id"] == "track_001"
        
        restored = AnnotationFrame.from_dict(data)
        assert restored.camera_id == frame.camera_id
        assert restored.frame_index == frame.frame_index
        assert len(restored.person_annotations) == 1
    
    def test_annotation_frame_json_roundtrip(self):
        bbox = BoundingBox(x=10, y=20, width=100, height=200)
        person_ann = PersonAnnotation(
            bbox=bbox,
            local_track_id="track_001",
            identity_candidate="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
        )
        
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=123.45,
        )
        
        frame = AnnotationFrame(
            camera_id="CAM1",
            frame_index=100,
            timestamp=123.45,
            timestamp_source="pts",
            source_frame_reference="CAM1_video:100",
            person_annotations=(person_ann,),
            provenance=prov,
        )
        
        json_str = frame.to_json()
        restored = AnnotationFrame.from_json(json_str)
        assert restored.camera_id == frame.camera_id
        assert restored.frame_index == frame.frame_index
        assert len(restored.person_annotations) == 1


class TestGenerateAnnotationFrameId:
    """Tests for generate_annotation_frame_id function."""
    
    def test_deterministic_id(self):
        id1 = generate_annotation_frame_id("CAM1", 100, "CAM1_video")
        id2 = generate_annotation_frame_id("CAM1", 100, "CAM1_video")
        assert id1 == id2
        assert id1.startswith("ANN-")
    
    def test_different_inputs_different_ids(self):
        id1 = generate_annotation_frame_id("CAM1", 100, "CAM1_video")
        id2 = generate_annotation_frame_id("CAM2", 100, "CAM1_video")
        id3 = generate_annotation_frame_id("CAM1", 101, "CAM1_video")
        id4 = generate_annotation_frame_id("CAM1", 100, "CAM2_video")
        
        assert id1 != id2
        assert id1 != id3
        assert id1 != id4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])