"""
Phase 27 — Unit Tests for Video Segment Retrieval.

Tests video evidence retrieval functionality.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from app.replay.video_evidence import (
    VideoSourceInfo,
    VideoEvidenceRetriever,
    VideoExtractionError,
    create_video_source_info_from_replay_source,
    build_source_video_registry_from_manifest,
)
from app.replay.appearance import (
    AppearanceRecord,
    VideoSegmentRequest,
    VideoSegmentResult,
    generate_video_segment_id,
)


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
        assert info.camera_id == "CAM1"
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30.0
        assert info.duration_seconds == 60.0
        assert info.frame_count == 1800
        assert info.codec == "h264"
    
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
        assert data["camera_id"] == "CAM1"
        assert data["width"] == 1920
        assert data["height"] == 1080
        assert data["fps"] == 30.0
        assert data["duration_seconds"] == 60.0
        assert data["frame_count"] == 1800
        assert data["codec"] == "h264"


class TestVideoEvidenceRetriever:
    """Tests for VideoEvidenceRetriever."""
    
    def test_retriever_initialization(self):
        registry = {}
        retriever = VideoEvidenceRetriever(
            source_video_registry=registry,
            output_directory="/tmp/test_output",
            ffmpeg_path="ffmpeg",
            max_concurrent_extractions=2,
        )
        
        assert retriever.output_directory.exists()
        assert retriever.ffmpeg_path == "ffmpeg"
        assert retriever.max_concurrent_extractions == 2
        assert retriever.source_video_registry == registry
    
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
        assert stats["ffmpeg_path"] == "ffmpeg"
        assert stats["max_concurrent_extractions"] == 2
        assert stats["source_videos"] == {}
    
    def test_extraction_stats_with_sources(self):
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
        stats = retriever.get_extraction_stats()
        assert stats["registered_sources"] == 1
        assert "CAM1_video" in stats["source_videos"]
        assert stats["source_videos"]["CAM1_video"]["camera_id"] == "CAM1"


class TestVideoSegmentRequest:
    """Tests for VideoSegmentRequest."""
    
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
            output_format="mp4",
        )
        
        assert req.source_video_id == "CAM1_video"
        assert req.camera_id == "CAM1"
        assert req.start_timestamp == 100.0
        assert req.end_timestamp == 110.0
        assert req.pre_roll_seconds == 3.0
        assert req.post_roll_seconds == 3.0
        assert req.output_format == "mp4"
    
    def test_video_segment_request_validation(self):
        # end_timestamp <= start_timestamp
        with pytest.raises(ValueError):
            VideoSegmentRequest(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                start_timestamp=110.0,
                end_timestamp=100.0,
                start_frame=100,
                end_frame=110,
            )
        
        # negative pre_roll
        with pytest.raises(ValueError):
            VideoSegmentRequest(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                start_timestamp=100.0,
                end_timestamp=110.0,
                start_frame=100,
                end_frame=110,
                pre_roll_seconds=-1.0,
            )
        
        # negative post_roll
        with pytest.raises(ValueError):
            VideoSegmentRequest(
                source_video_id="CAM1_video",
                camera_id="CAM1",
                start_timestamp=100.0,
                end_timestamp=110.0,
                start_frame=100,
                end_frame=110,
                post_roll_seconds=-1.0,
            )
    
    def test_video_segment_request_serialization(self):
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
        
        data = req.to_dict()
        assert data["source_video_id"] == "CAM1_video"
        assert data["camera_id"] == "CAM1"
        assert data["pre_roll_seconds"] == 3.0
        assert data["post_roll_seconds"] == 3.0
        
        restored = VideoSegmentRequest.from_dict(data)
        assert restored.source_video_id == req.source_video_id
        assert restored.camera_id == req.camera_id
        assert restored.pre_roll_seconds == req.pre_roll_seconds


class TestVideoSegmentResult:
    """Tests for VideoSegmentResult."""
    
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
        assert result.pre_roll_seconds == 3.0
        assert result.post_roll_seconds == 3.0
    
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
        assert data["pre_roll_seconds"] == 3.0
        
        restored = VideoSegmentResult.from_dict(data)
        assert restored.output_path == result.output_path
        assert restored.actual_start_timestamp == result.actual_start_timestamp


class TestGenerateVideoSegmentId:
    """Tests for generate_video_segment_id function."""
    
    def test_deterministic_id(self):
        id1 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        id2 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        assert id1 == id2
        assert id1.startswith("VID-")
    
    def test_different_inputs_different_ids(self):
        id1 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 110.0)
        id2 = generate_video_segment_id("CAM2_video", "CAM1", 100.0, 110.0)
        id3 = generate_video_segment_id("CAM1_video", "CAM2", 100.0, 110.0)
        id4 = generate_video_segment_id("CAM1_video", "CAM1", 200.0, 110.0)
        id5 = generate_video_segment_id("CAM1_video", "CAM1", 100.0, 200.0)
        
        assert id1 != id2
        assert id1 != id3
        assert id1 != id4
        assert id1 != id5


class TestVideoExtractionError:
    """Tests for VideoExtractionError."""
    
    def test_video_extraction_error_creation(self):
        error = VideoExtractionError(
            message="Test error",
            source_video_id="CAM1_video",
            camera_id="CAM1",
            start_timestamp=100.0,
            end_timestamp=110.0,
            recoverable=True,
        )
        
        assert str(error) == "Test error"
        assert error.source_video_id == "CAM1_video"
        assert error.camera_id == "CAM1"
        assert error.start_timestamp == 100.0
        assert error.end_timestamp == 110.0
        assert error.recoverable is True


class TestCreateVideoSourceInfoFromReplaySource:
    """Tests for create_video_source_info_from_replay_source function."""
    
    def test_create_video_source_info(self):
        # This test verifies the function signature and basic behavior
        # The actual implementation uses VideoFrameIterator which requires a real video file
        # We test that the function exists and has the right signature
        import inspect
        sig = inspect.signature(create_video_source_info_from_replay_source)
        assert "source_video_id" in sig.parameters
        assert "camera_id" in sig.parameters
        assert "source_path" in sig.parameters


class TestBuildSourceVideoRegistryFromManifest:
    """Tests for build_source_video_registry_from_manifest function."""
    
    def test_build_registry_signature(self):
        # This test verifies the function signature
        import inspect
        sig = inspect.signature(build_source_video_registry_from_manifest)
        assert "manifest_path" in sig.parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])