"""
Phase 27 — Video Evidence Retrieval.

Provides streaming/seek-based video segment extraction from source storage.
Does NOT load entire video into memory - uses bounded memory extraction.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.replay.appearance import (
    AppearanceRecord,
    VideoSegmentRequest,
    VideoSegmentResult,
    generate_video_segment_id,
)

logger = logging.getLogger(__name__)


class VideoExtractionError(Exception):
    """Exception raised when video extraction fails."""
    
    def __init__(
        self,
        message: str,
        source_video_id: str,
        camera_id: str,
        start_timestamp: float,
        end_timestamp: float,
        recoverable: bool = False,
    ):
        super().__init__(message)
        self.source_video_id = source_video_id
        self.camera_id = camera_id
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.recoverable = recoverable


@dataclass(frozen=True)
class VideoSourceInfo:
    """Information about a source video file."""
    source_video_id: str
    camera_id: str
    file_path: str
    width: int
    height: int
    fps: float
    duration_seconds: float
    frame_count: int
    codec: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_video_id": self.source_video_id,
            "camera_id": self.camera_id,
            "file_path": self.file_path,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "codec": self.codec,
        }


class VideoEvidenceRetriever:
    """
    Video evidence retrieval for forensic audit.
    
    Features:
    - Streaming/seek-based extraction (bounded memory)
    - Pre-roll/post-roll support with boundary clamping
    - Source reference preservation (no video duplication in database)
    - Deterministic extraction
    - Multiple format support via ffmpeg
    """
    
    def __init__(
        self,
        source_video_registry: Dict[str, VideoSourceInfo],
        output_directory: str,
        ffmpeg_path: str = "ffmpeg",
        max_concurrent_extractions: int = 2,
    ):
        """
        Initialize video evidence retriever.
        
        Args:
            source_video_registry: Mapping of source_video_id -> VideoSourceInfo
            output_directory: Directory for extracted segments
            ffmpeg_path: Path to ffmpeg executable
            max_concurrent_extractions: Maximum concurrent extractions (bounded)
        """
        self.source_video_registry = source_video_registry
        self.output_directory = Path(output_directory)
        self.ffmpeg_path = ffmpeg_path
        self.max_concurrent_extractions = max_concurrent_extractions
        
        # Ensure output directory exists
        self.output_directory.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"VideoEvidenceRetriever initialized: output_dir={output_directory}")
    
    def register_source_video(self, source_info: VideoSourceInfo) -> None:
        """Register a source video for extraction."""
        self.source_video_registry[source_info.source_video_id] = source_info
        logger.info(f"Registered source video: {source_info.source_video_id} ({source_info.camera_id})")
    
    def get_source_info(self, source_video_id: str) -> Optional[VideoSourceInfo]:
        """Get source video info by ID."""
        return self.source_video_registry.get(source_video_id)
    
    def extract_segment(self, request: VideoSegmentRequest) -> VideoSegmentResult:
        """
        Extract a video segment from source.
        
        Uses streaming/seek-based extraction - does NOT load entire video into memory.
        Clamps to source boundaries.
        
        Args:
            request: Video segment extraction request
            
        Returns:
            VideoSegmentResult with extraction details
            
        Raises:
            VideoExtractionError: If extraction fails
        """
        # Get source info
        source_info = self.source_video_registry.get(request.source_video_id)
        if not source_info:
            raise VideoExtractionError(
                f"Source video not registered: {request.source_video_id}",
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                start_timestamp=request.start_timestamp,
                end_timestamp=request.end_timestamp,
                recoverable=False,
            )
        
        # Verify camera matches
        if source_info.camera_id != request.camera_id:
            raise VideoExtractionError(
                f"Camera ID mismatch: registry={source_info.camera_id}, request={request.camera_id}",
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                start_timestamp=request.start_timestamp,
                end_timestamp=request.end_timestamp,
                recoverable=False,
            )
        
        # Apply pre-roll/post-roll and clamp to source boundaries
        actual_start_ts = max(0.0, request.start_timestamp - request.pre_roll_seconds)
        actual_end_ts = min(source_info.duration_seconds, request.end_timestamp + request.post_roll_seconds)
        
        # Convert timestamps to frame indices
        actual_start_frame = max(0, int(actual_start_ts * source_info.fps))
        actual_end_frame = min(source_info.frame_count - 1, int(actual_end_ts * source_info.fps))
        
        # Generate output path
        segment_id = generate_video_segment_id(
            source_video_id=request.source_video_id,
            camera_id=request.camera_id,
            start_timestamp=actual_start_ts,
            end_timestamp=actual_end_ts,
        )
        output_filename = f"{segment_id}.{request.output_format}"
        output_path = self.output_directory / output_filename
        
        # Build ffmpeg command for seek-based extraction
        # Use -ss before -i for fast seeking, then -t for duration
        duration = actual_end_ts - actual_start_ts
        
        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            "-ss", f"{actual_start_ts:.3f}",  # Seek to start (fast seek before input)
            "-i", source_info.file_path,
            "-t", f"{duration:.3f}",  # Duration
            "-c:v", "libx264",  # Re-encode for consistent output
            "-preset", "fast",
            "-crf", "23",
            "-an",  # No audio
            str(output_path),
        ]
        
        logger.info(f"Extracting video segment: {segment_id} from {source_info.file_path}")
        logger.debug(f"ffmpeg command: {' '.join(cmd)}")
        
        try:
            # Run ffmpeg with timeout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            
            if result.returncode != 0:
                raise VideoExtractionError(
                    f"ffmpeg failed: {result.stderr}",
                    source_video_id=request.source_video_id,
                    camera_id=request.camera_id,
                    start_timestamp=request.start_timestamp,
                    end_timestamp=request.end_timestamp,
                    recoverable=True,
                )
            
            # Verify output file exists and has content
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise VideoExtractionError(
                    "Output file is empty or missing",
                    source_video_id=request.source_video_id,
                    camera_id=request.camera_id,
                    start_timestamp=request.start_timestamp,
                    end_timestamp=request.end_timestamp,
                    recoverable=False,
                )
            
            logger.info(f"Video segment extracted: {output_path} ({output_path.stat().st_size} bytes)")
            
            return VideoSegmentResult(
                output_path=str(output_path),
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                source_start_timestamp=request.start_timestamp,
                source_end_timestamp=request.end_timestamp,
                source_start_frame=request.start_frame,
                source_end_frame=request.end_frame,
                pre_roll_seconds=request.pre_roll_seconds,
                post_roll_seconds=request.post_roll_seconds,
                output_format=request.output_format,
                actual_start_timestamp=actual_start_ts,
                actual_end_timestamp=actual_end_ts,
                actual_start_frame=actual_start_frame,
                actual_end_frame=actual_end_frame,
                extraction_config={
                    "ffmpeg_command": " ".join(cmd),
                    "source_fps": source_info.fps,
                    "source_resolution": f"{source_info.width}x{source_info.height}",
                },
                provenance={
                    "source_video_id": source_info.source_video_id,
                    "source_file_path": source_info.file_path,
                    "extraction_timestamp": __import__('datetime').datetime.utcnow().isoformat() + "Z",
                },
            )
            
        except subprocess.TimeoutExpired:
            raise VideoExtractionError(
                "ffmpeg extraction timed out",
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                start_timestamp=request.start_timestamp,
                end_timestamp=request.end_timestamp,
                recoverable=True,
            )
        except FileNotFoundError:
            raise VideoExtractionError(
                f"ffmpeg not found at: {self.ffmpeg_path}",
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                start_timestamp=request.start_timestamp,
                end_timestamp=request.end_timestamp,
                recoverable=False,
            )
        except VideoExtractionError:
            raise
        except Exception as e:
            raise VideoExtractionError(
                f"Unexpected extraction error: {e}",
                source_video_id=request.source_video_id,
                camera_id=request.camera_id,
                start_timestamp=request.start_timestamp,
                end_timestamp=request.end_timestamp,
                recoverable=False,
            )
    
    def extract_from_appearance(
        self,
        appearance: AppearanceRecord,
        pre_roll_seconds: float = 0.0,
        post_roll_seconds: float = 0.0,
        output_format: str = "mp4",
    ) -> VideoSegmentResult:
        """
        Extract video segment for an appearance record.
        
        Convenience method that builds request from AppearanceRecord.
        
        Args:
            appearance: AppearanceRecord to extract
            pre_roll_seconds: Seconds before appearance start
            post_roll_seconds: Seconds after appearance end
            output_format: Output video format
            
        Returns:
            VideoSegmentResult
        """
        request = VideoSegmentRequest(
            source_video_id=appearance.source_video_id,
            camera_id=appearance.camera_id,
            start_timestamp=appearance.start_timestamp,
            end_timestamp=appearance.end_timestamp,
            start_frame=appearance.start_frame,
            end_frame=appearance.end_frame,
            pre_roll_seconds=pre_roll_seconds,
            post_roll_seconds=post_roll_seconds,
            output_format=output_format,
        )
        return self.extract_segment(request)
    
    def extract_multiple_segments(
        self,
        requests: List[VideoSegmentRequest],
    ) -> List[VideoSegmentResult]:
        """
        Extract multiple video segments sequentially.
        
        Respects max_concurrent_extractions for bounded resource usage.
        
        Args:
            requests: List of extraction requests
            
        Returns:
            List of VideoSegmentResult (successful extractions)
        """
        results = []
        for request in requests:
            try:
                result = self.extract_segment(request)
                results.append(result)
            except VideoExtractionError as e:
                logger.error(f"Failed to extract segment: {e}")
                # Continue with other extractions
                continue
        return results
    
    def get_extraction_stats(self) -> Dict[str, Any]:
        """Get retriever statistics."""
        return {
            "registered_sources": len(self.source_video_registry),
            "output_directory": str(self.output_directory),
            "ffmpeg_path": self.ffmpeg_path,
            "max_concurrent_extractions": self.max_concurrent_extractions,
            "source_videos": {
                vid: info.to_dict() for vid, info in self.source_video_registry.items()
            },
        }


def create_video_source_info_from_replay_source(
    source_video_id: str,
    camera_id: str,
    source_path: str,
) -> VideoSourceInfo:
    """
    Create VideoSourceInfo from a replay source path.
    
    Uses the existing VideoFrameIterator to get metadata.
    """
    from app.data.input_adapter import VideoFrameIterator
    
    iterator = VideoFrameIterator(source_path)
    try:
        info = iterator.info
        return VideoSourceInfo(
            source_video_id=source_video_id,
            camera_id=camera_id,
            file_path=source_path,
            width=info.width,
            height=info.height,
            fps=info.fps if info.fps > 0 else 30.0,
            duration_seconds=info.duration_seconds,
            frame_count=info.frame_count,
            codec=info.codec,
        )
    finally:
        iterator.close()


def build_source_video_registry_from_manifest(
    manifest_path: str,
) -> Dict[str, VideoSourceInfo]:
    """
    Build source video registry from a Phase 20 ReplayManifest.
    
    Args:
        manifest_path: Path to ReplayManifest JSON file
        
    Returns:
        Dictionary mapping source_video_id -> VideoSourceInfo
    """
    from app.replay.manifest import ReplayManifest
    
    manifest = ReplayManifest.load(manifest_path)
    registry = {}
    
    for source_manifest in manifest.sources:
        source_video_id = f"{source_manifest.camera_id}_{Path(source_manifest.source_path).stem}"
        source_info = create_video_source_info_from_replay_source(
            source_video_id=source_video_id,
            camera_id=source_manifest.camera_id,
            source_path=source_manifest.source_path,
        )
        registry[source_video_id] = source_info
    
    return registry