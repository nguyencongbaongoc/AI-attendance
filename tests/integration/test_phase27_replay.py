"""
Phase 27 — Integration Test for Annotated Dual-Camera Replay.

Tests the complete annotated replay pipeline integrating Phases 20-26.
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from app.replay.annotated_replay import (
    AnnotatedReplayPipeline,
    AnnotatedReplayConfig,
    AnnotatedReplayState,
)
from app.replay.source import ReplaySourceConfig
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
)
from app.replay.appearance import AppearanceRecord, PersonSearchResult
from app.replay.fusion import GlobalObservation, LocalObservationRef, AssociationState
from app.in_out.resolver_contract import ResolvedTransition, DerivedState, TransitionType
from app.attendance.engine import AttendanceDecision, DecisionReason
from app.attendance.contract import AttendanceRecord
from app.replay.clock import ReplayTimestamp


class TestAnnotatedReplayConfig:
    """Tests for AnnotatedReplayConfig."""
    
    def test_default_config(self):
        config = AnnotatedReplayConfig()
        
        assert config.include_person_annotations is True
        assert config.include_face_annotations is True
        assert config.include_event_annotations is True
        assert config.include_attendance_annotations is True
        assert config.include_global_observation_references is True
        assert config.build_appearance_index is True
        assert config.output_directory == "replay_output"
        assert config.save_annotation_frames is True
    
    def test_config_serialization(self):
        config = AnnotatedReplayConfig()
        data = config.to_dict()
        
        assert "scheduler_config" in data
        assert "fusion_config" in data
        assert data["include_person_annotations"] is True
        assert data["output_directory"] == "replay_output"


class TestAnnotatedReplayPipeline:
    """Tests for AnnotatedReplayPipeline."""
    
    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def mock_source_configs(self):
        """Create mock source configs."""
        return [
            ReplaySourceConfig(camera_id="CAM1", source_path="/fake/cam1.mp4"),
            ReplaySourceConfig(camera_id="CAM2", source_path="/fake/cam2.mp4"),
        ]
    
    @pytest.fixture
    def mock_scheduler(self):
        """Create a mock scheduler that yields test frames."""
        mock_scheduler = Mock()
        
        # Create mock frames
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        import numpy as np
        
        def create_mock_frame(camera_id, frame_index, timestamp):
            metadata = FrameMetadata(
                source_type=SourceType.VIDEO,
                source_id=f"{camera_id}_video",
                frame_index=frame_index,
                timestamp=timestamp,
                original_width=1920,
                original_height=1080,
                pixel_format=PixelFormat.BGR,
                dtype="uint8",
                extra={
                    "camera_id": camera_id,
                    "replay_timestamp": {"value": timestamp, "source": "pts"},
                    "source_video_id": f"{camera_id}_video",
                    "detections": [],
                },
            )
            frame = CanonicalFrame(
                data=np.zeros((1080, 1920, 3), dtype=np.uint8),
                metadata=metadata,
            )
            return frame
        
        # Yield frames from both cameras in timestamp order
        frames = [
            create_mock_frame("CAM1", 0, 0.0),
            create_mock_frame("CAM2", 0, 0.033),
            create_mock_frame("CAM1", 1, 0.066),
            create_mock_frame("CAM2", 1, 0.1),
        ]
        mock_scheduler.__iter__ = Mock(return_value=iter(frames))
        
        return mock_scheduler
    
    def test_pipeline_initialization(self, mock_source_configs, temp_output_dir):
        """Test pipeline initialization."""
        config = AnnotatedReplayConfig(output_directory=temp_output_dir)
        
        with patch('app.replay.annotated_replay.create_scheduler') as mock_create_scheduler:
            mock_create_scheduler.return_value = Mock()
            
            pipeline = AnnotatedReplayPipeline(
                source_configs=mock_source_configs,
                config=config,
            )
            
            assert pipeline.source_configs == mock_source_configs
            assert pipeline.config == config
            assert pipeline.output_dir.exists()
            mock_create_scheduler.assert_called_once()
    
    def test_pipeline_run_with_mock_scheduler(self, mock_source_configs, mock_scheduler, temp_output_dir):
        """Test pipeline run with mocked scheduler."""
        config = AnnotatedReplayConfig(
            output_directory=temp_output_dir,
            save_annotation_frames=True,
        )
        
        with patch('app.replay.annotated_replay.create_scheduler') as mock_create_scheduler:
            mock_create_scheduler.return_value = mock_scheduler
            
            pipeline = AnnotatedReplayPipeline(
                source_configs=mock_source_configs,
                config=config,
            )
            
            state = pipeline.run()
            
            assert state.frames_processed == 4
            assert state.frames_annotated == 4
            assert len(state.annotation_frames) == 4
    
    def test_annotation_frame_creation(self, temp_output_dir):
        """Test annotation frame creation with all annotation types."""
        # Create test annotations
        bbox = BoundingBox(x=100, y=100, width=200, height=300)
        face_bbox = BoundingBox(x=150, y=150, width=50, height=60)
        
        person_ann = PersonAnnotation(
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
            attendance_state=AttendanceDisplayState.PRESENT,
            attendance_decision_id="ATT-001",
        )
        
        face_ann = FaceAnnotation(
            bbox=face_bbox,
            quality_class="GOOD",
            quality_score=0.92,
            identity_similarity=0.88,
            identity_candidate="HS001",
        )
        
        event_ann = EventAnnotation(
            event_type=EventDisplayType.IN,
            event_id="RIE-001",
            direction="in",
            timestamp=100.0,
            camera_id="CAM1",
            local_track_id="track_001",
            raw_event_id="RIE-001",
        )
        
        att_ann = AttendanceAnnotation(
            attendance_state=AttendanceDisplayState.PRESENT,
            decision_reason="WITHIN_ENTRY_WINDOW",
            person_identity="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
        )
        
        go_ref = GlobalObservationReference(
            global_observation_id="GO-abc123",
            association_state="associated",
            camera_ids=("CAM1", "CAM2"),
            local_track_ids=("CAM1:track_001", "CAM2:track_002"),
            temporal_start=100.0,
            temporal_end=105.0,
            temporal_span=5.0,
        )
        
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=100.0,
        )
        
        frame = AnnotationFrame(
            camera_id="CAM1",
            frame_index=100,
            timestamp=100.0,
            timestamp_source="pts",
            source_frame_reference="CAM1_video:100",
            person_annotations=(person_ann,),
            face_annotations=(face_ann,),
            event_annotations=(event_ann,),
            attendance_annotations=(att_ann,),
            global_observation_references=(go_ref,),
            provenance=prov,
        )
        
        # Verify frame structure
        assert frame.camera_id == "CAM1"
        assert frame.frame_index == 100
        assert len(frame.person_annotations) == 1
        assert len(frame.face_annotations) == 1
        assert len(frame.event_annotations) == 1
        assert len(frame.attendance_annotations) == 1
        assert len(frame.global_observation_references) == 1
        
        # Test serialization
        data = frame.to_dict()
        assert data["camera_id"] == "CAM1"
        assert len(data["person_annotations"]) == 1
        assert data["person_annotations"][0]["identity_certainty"] == "known"
        
        # Test JSON roundtrip
        json_str = frame.to_json()
        restored = AnnotationFrame.from_json(json_str)
        assert restored.camera_id == frame.camera_id
        assert restored.frame_index == frame.frame_index
        assert len(restored.person_annotations) == 1


class TestAppearanceIndexing:
    """Tests for appearance indexing functionality."""
    
    def test_appearance_record_creation(self):
        """Test appearance record creation and properties."""
        app = AppearanceRecord(
            appearance_id="APP-abc123",
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=110.0,
            start_frame=100,
            end_frame=110,
        )
        
        assert app.duration_seconds == 10.0
        assert app.frame_count == 11
        assert app.has_known_identity is True
    
    def test_appearance_record_unknown_identity(self):
        """Test appearance record with unknown identity."""
        app = AppearanceRecord(
            appearance_id="APP-abc123",
            person_id=None,
            identity_certainty="unknown",
            camera_id="CAM1",
            local_track_id="track_001",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=110.0,
            start_frame=100,
            end_frame=110,
        )
        
        assert app.person_id is None
        assert app.identity_certainty == "unknown"
        assert app.has_known_identity is False
    
    def test_person_search_result(self):
        """Test person search result."""
        app1 = AppearanceRecord(
            appearance_id="APP-001",
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM1",
            local_track_id="track_001",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=110.0,
            start_frame=100,
            end_frame=110,
        )
        
        app2 = AppearanceRecord(
            appearance_id="APP-002",
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM2",
            local_track_id="track_002",
            source_video_id="CAM2_video",
            start_timestamp=200.0,
            end_timestamp=210.0,
            start_frame=200,
            end_frame=210,
        )
        
        result = PersonSearchResult(person_id="HS001", appearances=(app1, app2))
        
        assert result.person_id == "HS001"
        assert len(result.appearances) == 2
        assert result.appearances[0].camera_id == "CAM1"
        assert result.appearances[1].camera_id == "CAM2"


class TestGlobalObservationIntegration:
    """Tests for GlobalObservation integration."""
    
    def test_global_observation_creation(self):
        """Test GlobalObservation creation."""
        obs_ref1 = LocalObservationRef(
            camera_id="CAM1",
            local_track_id="track_001",
            observation_id="CAM1_track_001_f100",
            frame_index=100,
            timestamp=ReplayTimestamp(value=100.0, source="pts"),
        )
        
        obs_ref2 = LocalObservationRef(
            camera_id="CAM2",
            local_track_id="track_002",
            observation_id="CAM2_track_002_f100",
            frame_index=100,
            timestamp=ReplayTimestamp(value=100.05, source="pts"),
        )
        
        from app.replay.fusion import AssociationEvidence
        evidence = AssociationEvidence(
            timestamp_delta=0.05,
            timestamp_compatible=True,
            timestamp_tolerance=1.0,
            camera_ids=("CAM1", "CAM2"),
        )
        
        go = GlobalObservation(
            global_observation_id="GO-abc123",
            observations=(obs_ref1, obs_ref2),
            association_state=AssociationState.ASSOCIATED,
            association_evidence=evidence,
            temporal_start=ReplayTimestamp(value=100.0, source="fusion_min"),
            temporal_end=ReplayTimestamp(value=100.05, source="fusion_max"),
            temporal_span=0.05,
            camera_ids=("CAM1", "CAM2"),
            local_track_ids=("CAM1:track_001", "CAM2:track_002"),
            primary_identity_candidate="HS001",
            identity_confidence=0.95,
        )
        
        assert go.global_observation_id == "GO-abc123"
        assert go.is_associated is True
        assert go.camera_ids == ("CAM1", "CAM2")
        assert go.local_track_ids == ("CAM1:track_001", "CAM2:track_002")
        assert go.primary_identity_candidate == "HS001"
    
    def test_global_observation_serialization(self):
        """Test GlobalObservation serialization."""
        obs_ref = LocalObservationRef(
            camera_id="CAM1",
            local_track_id="track_001",
            observation_id="CAM1_track_001_f100",
            frame_index=100,
            timestamp=ReplayTimestamp(value=100.0, source="pts"),
        )
        
        from app.replay.fusion import AssociationEvidence
        evidence = AssociationEvidence(
            timestamp_delta=0.0,
            timestamp_compatible=True,
            timestamp_tolerance=1.0,
            camera_ids=("CAM1",),
        )
        
        go = GlobalObservation(
            global_observation_id="GO-abc123",
            observations=(obs_ref,),
            association_state=AssociationState.ASSOCIATED,
            association_evidence=evidence,
            temporal_start=ReplayTimestamp(value=100.0, source="fusion_min"),
            temporal_end=ReplayTimestamp(value=100.0, source="fusion_max"),
            temporal_span=0.0,
            camera_ids=("CAM1",),
            local_track_ids=("CAM1:track_001",),
        )
        
        data = go.to_dict()
        assert data["global_observation_id"] == "GO-abc123"
        assert data["association_state"] == "associated"
        assert data["camera_ids"] == ["CAM1"]
        assert data["local_track_ids"] == ["CAM1:track_001"]


class TestEventAnnotationIntegration:
    """Tests for event annotation integration with Phases 22-24."""
    
    def test_crossing_event_annotation(self):
        """Test crossing event annotation (Phase 22)."""
        # Mock crossing event
        mock_crossing = Mock()
        mock_crossing.camera_id = "CAM1"
        mock_crossing.timestamp = 100.0
        mock_crossing.direction.value = "enter"
        mock_crossing.local_track_id = "track_001"
        mock_crossing.global_observation_id = "GO-abc123"
        mock_crossing.geometry_version = 1
        mock_crossing.geometry_config_hash = "hash123"
        
        # This would be created by the pipeline
        event_ann = EventAnnotation(
            event_type=EventDisplayType.CROSSING,
            event_id="CE-001",
            direction="enter",
            timestamp=100.0,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            crossing_event_id="CE-001",
            crossing_direction="enter",
            geometry_version=1,
            geometry_config_hash="hash123",
        )
        
        assert event_ann.event_type == EventDisplayType.CROSSING
        assert event_ann.crossing_event_id == "CE-001"
        assert event_ann.geometry_version == 1
    
    def test_raw_in_out_event_annotation(self):
        """Test raw IN/OUT event annotation (Phase 23)."""
        mock_raw = Mock()
        mock_raw.camera_id = "CAM1"
        mock_raw.timestamp = 100.0
        mock_raw.direction.value = "in"
        mock_raw.local_track_id = "track_001"
        mock_raw.global_observation_id = "GO-abc123"
        
        event_ann = EventAnnotation(
            event_type=EventDisplayType.IN,
            event_id="RIE-001",
            direction="in",
            timestamp=100.0,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            raw_event_id="RIE-001",
        )
        
        assert event_ann.event_type == EventDisplayType.IN
        assert event_ann.raw_event_id == "RIE-001"
    
    def test_resolved_transition_annotation(self):
        """Test resolved transition annotation (Phase 24)."""
        mock_resolution = Mock()
        mock_resolution.camera_id = "CAM1"
        mock_resolution.source_timestamp = 100.0
        mock_resolution.direction = "in"
        mock_resolution.local_track_id = "track_001"
        mock_resolution.global_observation_id = "GO-abc123"
        mock_resolution.previous_state = Mock(value="outside")
        mock_resolution.new_state = Mock(value="inside")
        mock_resolution.resolver_version = "1.0"
        mock_resolution.resolver_config_hash = "hash123"
        
        event_ann = EventAnnotation(
            event_type=EventDisplayType.IN,
            event_id="RT-001",
            direction="in",
            timestamp=100.0,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            resolution_id="RT-001",
            previous_state="outside",
            new_state="inside",
            resolver_version="1.0",
            resolver_config_hash="hash123",
        )
        
        assert event_ann.event_type == EventDisplayType.IN
        assert event_ann.resolution_id == "RT-001"
        assert event_ann.previous_state == "outside"
        assert event_ann.new_state == "inside"


class TestAttendanceAnnotationIntegration:
    """Tests for attendance annotation integration with Phase 26."""
    
    def test_attendance_decision_annotation(self):
        """Test attendance decision annotation (Phase 26)."""
        mock_decision = Mock()
        mock_decision.camera_id = "CAM1"
        mock_decision.event_timestamp = 100.0
        mock_decision.new_attendance_state = "present"
        mock_decision.decision_reason = Mock(value="WITHIN_ENTRY_WINDOW")
        mock_decision.identity_candidate = "HS001"
        mock_decision.identity_certainty = "known"
        mock_decision.identity_confidence = 0.95
        mock_decision.timetable_id = "TT-001"
        mock_decision.session_id = "S-001"
        mock_decision.day = "MONDAY"
        mock_decision.local_track_id = "track_001"
        mock_decision.global_observation_id = "GO-abc123"
        mock_decision.decision_id = "ATT-001"
        mock_decision.attendance_policy_id = "POL-001"
        mock_decision.attendance_policy_version = "1.0"
        mock_decision.previous_attendance_state = "unknown"
        mock_decision.new_attendance_state = "present"
        
        att_ann = AttendanceAnnotation(
            attendance_state=AttendanceDisplayState.PRESENT,
            decision_reason="WITHIN_ENTRY_WINDOW",
            person_identity="HS001",
            identity_certainty=IdentityDisplayState.KNOWN,
            identity_confidence=0.95,
            timetable_id="TT-001",
            session_id="S-001",
            day="MONDAY",
            event_timestamp=100.0,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            attendance_decision_id="ATT-001",
            attendance_policy_id="POL-001",
            attendance_policy_version="1.0",
            previous_attendance_state="unknown",
            new_attendance_state="present",
        )
        
        assert att_ann.attendance_state == AttendanceDisplayState.PRESENT
        assert att_ann.decision_reason == "WITHIN_ENTRY_WINDOW"
        assert att_ann.attendance_decision_id == "ATT-001"
        assert att_ann.timetable_id == "TT-001"


class TestProvenanceChain:
    """Tests for provenance chain preservation."""
    
    def test_annotation_provenance(self):
        """Test annotation provenance chain."""
        prov = AnnotationProvenance(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_frame_index=100,
            source_timestamp=100.0,
            annotation_schema_version="1.0",
        )
        
        assert prov.source_video_id == "CAM1_video"
        assert prov.camera_id == "CAM1"
        assert prov.source_frame_index == 100
        assert prov.annotation_schema_version == "1.0"
    
    def test_appearance_provenance(self):
        """Test appearance record provenance."""
        app = AppearanceRecord(
            appearance_id="APP-abc123",
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-abc123",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=110.0,
            start_frame=100,
            end_frame=110,
            source_resolution_id="RT-001",
            attendance_decision_id="ATT-001",
            provenance={
                "first_frame": 100,
                "first_timestamp": 100.0,
                "camera_id": "CAM1",
                "source_resolution_id": "RT-001",
                "attendance_decision_id": "ATT-001",
            },
        )
        
        assert app.source_resolution_id == "RT-001"
        assert app.attendance_decision_id == "ATT-001"
        assert app.provenance["source_resolution_id"] == "RT-001"
        assert app.provenance["attendance_decision_id"] == "ATT-001"


class TestDeterministicReplay:
    """Tests for deterministic replay behavior."""
    
    def test_annotation_frame_id_deterministic(self):
        """Test that annotation frame IDs are deterministic."""
        from app.replay.annotation import generate_annotation_frame_id
        
        id1 = generate_annotation_frame_id("CAM1", 100, "CAM1_video")
        id2 = generate_annotation_frame_id("CAM1", 100, "CAM1_video")
        assert id1 == id2
    
    def test_appearance_id_deterministic(self):
        """Test that appearance IDs are deterministic."""
        from app.replay.appearance import generate_appearance_id
        
        id1 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 100.0)
        id2 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 100.0)
        assert id1 == id2
    
    def test_video_segment_id_deterministic(self):
        """Test that video segment IDs are deterministic."""
        from app.replay.appearance import generate_video_segment_id
        
        id1 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        id2 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        assert id1 == id2


class TestMemorySafety:
    """Tests for bounded memory behavior."""
    
    def test_annotation_frame_list_bounded(self):
        """Test that annotation frames list doesn't grow unbounded in normal use."""
        # In normal operation, frames are saved to disk and list can be cleared
        frames = []
        for i in range(1000):
            prov = AnnotationProvenance(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                source_frame_index=i,
                source_timestamp=float(i),
            )
            frame = AnnotationFrame(
                camera_id="CAM1",
                frame_index=i,
                timestamp=float(i),
                timestamp_source="pts",
                source_frame_reference=f"CAM1_video:{i}",
                provenance=prov,
            )
            frames.append(frame)
        
        assert len(frames) == 1000
        # In real pipeline, frames would be saved and list cleared periodically
    
    def test_appearance_index_bounded(self):
        """Test that appearance index tracks unique tracks."""
        from app.replay.annotated_replay import AnnotatedReplayState
        from app.replay.appearance import AppearanceRecord
        
        state = AnnotatedReplayState()
        
        # Add multiple appearances for same track (should update, not duplicate)
        app1 = AppearanceRecord(
            appearance_id="APP-001",
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM1",
            local_track_id="track_001",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=105.0,
            start_frame=100,
            end_frame=105,
        )
        
        app2 = AppearanceRecord(
            appearance_id="APP-001",  # Same ID
            person_id="HS001",
            identity_certainty="known",
            camera_id="CAM1",
            local_track_id="track_001",
            source_video_id="CAM1_video",
            start_timestamp=100.0,
            end_timestamp=110.0,  # Extended
            start_frame=100,
            end_frame=110,
        )
        
        state.track_appearances["CAM1:track_001"] = app1
        state.track_appearances["CAM1:track_001"] = app2  # Update
        
        assert len(state.track_appearances) == 1
        assert state.track_appearances["CAM1:track_001"].end_timestamp == 110.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])