"""
Phase 27 — Unit Tests for Appearance Record and Video Evidence Retrieval.

Tests appearance record contract, person search, and video segment retrieval.
"""

import pytest
import json
from pathlib import Path
from app.replay.appearance import (
    AppearanceRecord,
    VideoSegmentRequest,
    VideoSegmentResult,
    PersonSearchResult,
    generate_appearance_id,
    generate_video_segment_id,
)
from app.replay.video_evidence import (
    VideoSourceInfo,
    VideoEvidenceRetriever,
    VideoExtractionError,
    create_video_source_info_from_replay_source,
)


class TestAppearanceRecord:
    """Tests for AppearanceRecord contract."""
    
    def test_appearance_record_creation(self):
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
        
        assert app.appearance_id == "APP-abc123"
        assert app.person_id == "HS001"
        assert app.identity_certainty == "known"
        assert app.camera_id == "CAM1"
        assert app.duration_seconds == 10.0
        assert app.frame_count == 11
        assert app.has_known_identity is True
    
    def test_appearance_record_unknown_identity(self):
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
    
    def test_appearance_record_serialization(self):
        app = AppearanceRecord(
            appearance_id="APP-abc123",
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
        
        data = app.to_dict()
        assert data["appearance_id"] == "APP-abc123"
        assert data["person_id"] == "HS001"
        assert data["identity_certainty"] == "known"
        assert data["duration_seconds"] == 10.0
        assert data["frame_count"] == 11
        
        restored = AppearanceRecord.from_dict(data)
        assert restored.appearance_id == app.appearance_id
        assert restored.person_id == app.person_id
        assert restored.identity_certainty == app.identity_certainty
    
    def test_appearance_record_json_roundtrip(self):
        app = AppearanceRecord(
            appearance_id="APP-abc123",
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
        
        json_str = app.to_json()
        restored = AppearanceRecord.from_json(json_str)
        assert restored == app
    
    def test_appearance_record_validation(self):
        # Test invalid timestamps
        with pytest.raises(ValueError):
            AppearanceRecord(
                appearance_id="APP-abc123",
                camera_id="CAM1",
                local_track_id="track_001",
                source_video_id="CAM1_video",
                start_timestamp=110.0,
                end_timestamp=100.0,  # end < start
                start_frame=100,
                end_frame=110,
            )
        
        # Test invalid frames
        with pytest.raises(ValueError):
            AppearanceRecord(
                appearance_id="APP-abc123",
                camera_id="CAM1",
                local_track_id="track_001",
                source_video_id="CAM1_video",
                start_timestamp=100.0,
                end_timestamp=110.0,
                start_frame=110,
                end_frame=100,  # end < start
            )


class TestVideoSegmentRequest:
    """Tests for VideoSegmentRequest contract."""
    
    def test_video_segment_request_creation(self):
        req = VideoSegmentRequest(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            start_timestamp=100.0,
            end_timestamp=110.0,
            start_frame=100,
            end_frame=110,
            pre_roll_seconds=3.0,
            post_roll_seconds=3.0,
        )
        
        assert req.source_video_id == "CAM1_video"
        assert req.camera_id == "CAM1"
        assert req.pre_roll_seconds == 3.0
        assert req.post_roll_seconds == 3.0
    
    def test_video_segment_request_validation(self):
        with pytest.raises(ValueError):
            VideoSegmentRequest(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                start_timestamp=110.0,
                end_timestamp=100.0,  # end <= start
                start_frame=100,
                end_frame=110,
            )
        
        with pytest.raises(ValueError):
            VideoSegmentRequest(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                start_timestamp=100.0,
                end_timestamp=110.0,
                start_frame=100,
                end_frame=110,
                pre_roll_seconds=-1.0,  # negative
            )


class TestVideoSegmentResult:
    """Tests for VideoSegmentResult contract."""
    
    def test_video_segment_result_creation(self):
        result = VideoSegmentResult(
            output_path="/tmp/segment.mp4",
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_start_timestamp=100.0,
            source_end_timestamp=110.0,
            source_start_frame=100,
            source_end_frame=110,
            pre_roll_seconds=3.0,
            post_roll_seconds=3.0,
            output_format="mp4",
            actual_start_timestamp=97.0,
            actual_end_timestamp=113.0,
            actual_start_frame=97,
            actual_end_frame=113,
        )
        
        assert result.output_path == "/tmp/segment.mp4"
        assert result.actual_start_timestamp == 97.0
        assert result.actual_end_timestamp == 113.0
    
    def test_video_segment_result_serialization(self):
        result = VideoSegmentResult(
            output_path="/tmp/segment.mp4",
            source_video_id="CAM1_video",
            camera_id="CAM1",
            source_start_timestamp=100.0,
            source_end_timestamp=110.0,
            source_start_frame=100,
            source_end_frame=110,
            pre_roll_seconds=3.0,
            post_roll_seconds=3.0,
            output_format="mp4",
            actual_start_timestamp=97.0,
            actual_end_timestamp=113.0,
            actual_start_frame=97,
            actual_end_frame=113,
        )
        
        data = result.to_dict()
        assert data["output_path"] == "/tmp/segment.mp4"
        assert data["actual_start_timestamp"] == 97.0
        
        restored = VideoSegmentResult.from_dict(data)
        assert restored.output_path == result.output_path
        assert restored.actual_start_timestamp == result.actual_start_timestamp


class TestPersonSearchResult:
    """Tests for PersonSearchResult contract."""
    
    def test_person_search_result(self):
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
    
    def test_person_search_result_serialization(self):
        app = AppearanceRecord(
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
        
        result = PersonSearchResult(person_id="HS001", appearances=(app,))
        data = result.to_dict()
        
        assert data["person_id"] == "HS001"
        assert len(data["appearances"]) == 1
        
        restored = PersonSearchResult.from_dict(data)
        assert restored.person_id == result.person_id
        assert len(restored.appearances) == 1


class TestGenerateIds:
    """Tests for ID generation functions."""
    
    def test_generate_appearance_id_deterministic(self):
        id1 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 100.0)
        id2 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 100.0)
        assert id1 == id2
        assert id1.startswith("APP-")
    
    def test_generate_appearance_id_different_inputs(self):
        id1 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 100.0)
        id2 = generate_appearance_id("CAM2_video", "CAM1", "track_001", 100.0)
        id3 = generate_appearance_id("CAM1_video", "CAM2", "track_001", 100.0)
        id4 = generate_appearance_id("CAM1_video", "CAM1", "track_002", 100.0)
        id5 = generate_appearance_id("CAM1_video", "CAM1", "track_001", 200.0)
        
        assert id1 != id2
        assert id1 != id3
        assert id1 != id4
        assert id1 != id5
    
    def test_generate_video_segment_id_deterministic(self):
        id1 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        id2 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        assert id1 == id2
        assert id1.startswith("VID-")


class TestVideoSourceInfo:
    """Tests for VideoSourceInfo."""
    
    def test_video_source_info_creation(self):
        info = VideoSourceInfo(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            file_path="/path/to/video.mp4",
            width=1920,
            height=1080,
            fps=30.0,
            duration_seconds=60.0,
            frame_count=1800,
            codec="h264",
        )
        
        assert info.source_video_id == "CAM1_video"
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30.0
    
    def test_video_source_info_serialization(self):
        info = VideoSourceInfo(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            file_path="/path/to/video.mp4",
            width=1920,
            height=1080,
            fps=30.0,
            duration_seconds=60.0,
            frame_count=1800,
            codec="h264",
        )
        
        data = info.to_dict()
        assert data["source_video_id"] == "CAM1_video"
        assert data["width"] == 1920
        assert data["height"] == 1080


class TestVideoEvidenceRetriever:
    """Tests for VideoEvidenceRetriever (mocked)."""
    
    def test_retriever_initialization(self):
        registry = {}
        retriever = VideoEvidenceRetriever(
            source_video_registry=registry,
            output_directory="/tmp/test_output",
        )
        
        assert retriever.output_directory.exists()
        assert retriever.max_concurrent_extractions == 2
    
    def test_register_source_video(self):
        registry = {}
        retriever = VideoEvidenceRetriever(
            source_video_registry=registry,
            output_directory="/tmp/test_output",
        )
        
        info = VideoSourceInfo(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            file_path="/path/to/video.mp4",
            width=1920,
            height=1080,
            fps=30.0,
            duration_seconds=60.0,
            frame_count=1800,
            codec="h264",
        )
        
        retriever.register_source_video(info)
        assert "CAM1_video" in retriever.source_video_registry
        assert retriever.source_video_registry["CAM1_video"] == info
    
    def test_get_source_info(self):
        registry = {}
        retriever = VideoEvidenceRetriever(
            source_video_registry=registry,
            output_directory="/tmp/test_output",
        )
        
        info = VideoSourceInfo(
            source_video_id="CAM1_video",
            camera_id="CAM1",
            file_path="/path/to/video.mp4",
            width=1920,
            height=1080,
            fps=30.0,
            duration_seconds=60.0,
            frame_count=1800,
            codec="h264",
        )
        
        retriever.register_source_video(info)
        retrieved = retriever.get_source_info("CAM1_video")
        assert retrieved == info
        
        # Non-existent
        assert retriever.get_source_info("NONEXISTENT") is None
    
    def test_extraction_stats(self):
        registry = {}
        retriever = VideoEvidenceRetriever(
            source_video_registry=registry,
            output_directory="/tmp/test_output",
        )
        
        stats = retriever.get_extraction_stats()
        assert stats["registered_sources"] == 0
        assert Path(stats["output_directory"]) == Path("/tmp/test_output")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])