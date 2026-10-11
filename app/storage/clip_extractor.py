"""
Phase 17A WP3 — Zero-Transcode Event Clip Extractor.

Slices 5s-10s evidence MP4 clips from MediaMTX fMP4 recordings using ffmpeg stream copy.
- Zero GPU/CPU transcoding: ffmpeg -c copy (remux only)
- Non-blocking subprocess execution
- Handles open segment edge cases gracefully
- Returns relative URIs for database storage
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class ClipExtractResult:
    """Result of clip extraction operation."""
    clip_url: Optional[str] = None
    clip_path: Optional[str] = None
    error: Optional[str] = None
    duration_sec: float = 0.0
    extraction_time_ms: float = 0.0
    source_segments: List[str] = None
    
    def __post_init__(self):
        if self.source_segments is None:
            self.source_segments = []


class ClipExtractor:
    """
    Zero-transcode clip extractor using ffmpeg stream copy.
    
    Extracts short evidence clips from continuous MediaMTX fMP4 recordings
    without any re-encoding (pure container remuxing).
    """
    
    def __init__(
        self,
        recordings_dir: str = "recordings",
        clips_dir: str = "app/static/evidence/clips",
        ffmpeg_path: str = "ffmpeg",
        pre_roll_sec: float = 3.0,
        post_roll_sec: float = 3.0,
        segment_duration_sec: float = 60.0,
    ):
        self.recordings_dir = Path(recordings_dir)
        self.clips_dir = Path(clips_dir)
        self.ffmpeg_path = ffmpeg_path
        self.pre_roll_sec = pre_roll_sec
        self.post_roll_sec = post_roll_sec
        self.segment_duration_sec = segment_duration_sec
        
        # Ensure clips directory exists
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"ClipExtractor initialized: recordings={recordings_dir}, clips={clips_dir}")
    
    def _get_camera_recording_dir(self, camera_id: str) -> Path:
        """Get the recording directory for a camera."""
        return self.recordings_dir / camera_id
    
    def _find_recording_segments(
        self,
        camera_id: str,
        start_time: float,
        end_time: float,
    ) -> List[Path]:
        """
        Find recording segments covering the time range.
        
        MediaMTX creates segments with format: %Y-%m-%d_%H-%M-%S-%f.mp4
        We need to find segments that overlap with [start_time, end_time].
        """
        camera_dir = self._get_camera_recording_dir(camera_id)
        if not camera_dir.exists():
            logger.warning(f"Recording directory not found: {camera_dir}")
            return []
        
        segments = []
        start_dt = datetime.fromtimestamp(start_time)
        end_dt = datetime.fromtimestamp(end_time)
        
        # Look for segment files
        for segment_file in camera_dir.glob("*.mp4"):
            try:
                # Parse timestamp from filename
                # Format: 2026-10-10_14-30-00-123456.mp4
                stem = segment_file.stem
                # Try parsing with microseconds
                try:
                    segment_dt = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S-%f")
                except ValueError:
                    # Try without microseconds
                    try:
                        segment_dt = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
                    except ValueError:
                        logger.debug(f"Could not parse segment filename: {stem}")
                        continue
                
                segment_start = segment_dt.timestamp()
                segment_end = segment_start + self.segment_duration_sec
                
                # Check overlap
                if segment_end >= start_time and segment_start <= end_time:
                    segments.append(segment_file)
                    
            except Exception as e:
                logger.debug(f"Error parsing segment {segment_file}: {e}")
                continue
        
        # Sort by timestamp
        segments.sort(key=lambda p: p.stat().st_mtime)
        return segments
    
    def _get_segment_time_range(self, segment_path: Path) -> tuple[float, float]:
        """Get the time range of a segment using ffprobe."""
        try:
            cmd = [
                self.ffmpeg_path, "ffprobe" if "ffprobe" in self.ffmpeg_path else "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=start_time,duration",
                "-of", "csv=p=0",
                str(segment_path)
            ]
            
            # Use ffprobe if available, else ffmpeg
            if "ffprobe" not in self.ffmpeg_path:
                cmd = [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=start_time,duration",
                    "-of", "csv=p=0",
                    str(segment_path)
                ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) >= 2:
                    start = float(parts[0]) if parts[0] else 0.0
                    duration = float(parts[1]) if parts[1] else self.segment_duration_sec
                    return start, start + duration
        except Exception as e:
            logger.debug(f"ffprobe failed for {segment_path}: {e}")
        
        # Fallback: estimate from filename
        try:
            stem = segment_path.stem
            segment_dt = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S-%f")
        except ValueError:
            try:
                segment_dt = datetime.strptime(stem, "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                return 0.0, self.segment_duration_sec
        
        start = segment_dt.timestamp()
        return start, start + self.segment_duration_sec
    
    def _get_relative_uri(self, path: Path) -> str:
        """Convert absolute path to relative URI for database storage."""
        try:
            return str(path.relative_to("app/static"))
        except ValueError:
            return str(path)
    
    async def extract_clip(
        self,
        camera_id: str,
        event_timestamp: float,
        pre_roll_sec: Optional[float] = None,
        post_roll_sec: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> ClipExtractResult:
        """
        Extract a clip around the event timestamp.
        
        Args:
            camera_id: Camera identifier (e.g., "cam1", "cam2")
            event_timestamp: Unix timestamp of the event
            pre_roll_sec: Seconds before event (default: 3.0)
            post_roll_sec: Seconds after event (default: 3.0)
            event_id: Optional event ID for naming
            
        Returns:
            ClipExtractResult with clip URL/path or error
        """
        start_time = time.perf_counter()
        
        pre_roll = pre_roll_sec if pre_roll_sec is not None else self.pre_roll_sec
        post_roll = post_roll_sec if post_roll_sec is not None else self.post_roll_sec
        
        clip_start = event_timestamp - pre_roll
        clip_end = event_timestamp + post_roll
        
        # Generate output filename
        if event_id is None:
            event_id = f"evt_{int(event_timestamp * 1000)}"
        
        daily_dir = self.clips_dir / datetime.now().strftime("%Y-%m-%d")
        daily_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = daily_dir / f"{camera_id}_{event_id}.mp4"
        clip_url = self._get_relative_uri(output_path)
        
        try:
            # Find relevant recording segments
            segments = self._find_recording_segments(camera_id, clip_start, clip_end)
            
            if not segments:
                logger.warning(f"No recording segments found for {camera_id} at {event_timestamp}")
                return ClipExtractResult(
                    error="No recording segments found",
                    extraction_time_ms=(time.perf_counter() - start_time) * 1000,
                )
            
            logger.info(f"Found {len(segments)} segments for clip extraction")
            
            # Check if we need to wait for the current segment to finalize
            latest_segment = segments[-1]
            latest_mtime = latest_segment.stat().st_mtime
            time_since_modified = time.time() - latest_mtime
            
            # If segment was modified less than 3 seconds ago, it might still be writing
            if time_since_modified < 3.0:
                logger.info(f"Latest segment recently modified, waiting 3s for finalization...")
                await asyncio.sleep(3.0)
            
            # Build ffmpeg command for stream copy
            # Use concat demuxer for multiple segments
            if len(segments) == 1:
                # Single segment - direct extraction
                segment_start, segment_end = self._get_segment_time_range(segments[0])
                offset_start = clip_start - segment_start
                offset_end = clip_end - segment_start
                
                # Clamp to segment bounds
                offset_start = max(0, offset_start)
                offset_end = min(segment_end - segment_start, offset_end)
                
                if offset_end <= offset_start:
                    return ClipExtractResult(
                        error="Invalid time range within segment",
                        extraction_time_ms=(time.perf_counter() - start_time) * 1000,
                    )
                
                cmd = [
                    self.ffmpeg_path, "-y",
                    "-ss", str(offset_start),
                    "-to", str(offset_end),
                    "-i", str(segments[0]),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    "-avoid_negative_ts", "make_zero",
                    str(output_path),
                ]
            else:
                # Multiple segments - use concat demuxer
                # Create concat file
                concat_file = daily_dir / f"{camera_id}_{event_id}_concat.txt"
                try:
                    with open(concat_file, 'w') as f:
                        for seg in segments:
                            f.write(f"file '{seg.absolute()}'\n")
                    
                    # Calculate offsets relative to first segment
                    first_seg_start, _ = self._get_segment_time_range(segments[0])
                    offset_start = clip_start - first_seg_start
                    total_duration = clip_end - clip_start
                    
                    cmd = [
                        self.ffmpeg_path, "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-ss", str(max(0, offset_start)),
                        "-t", str(total_duration),
                        "-i", str(concat_file),
                        "-c", "copy",
                        "-movflags", "+faststart",
                        "-avoid_negative_ts", "make_zero",
                        str(output_path),
                    ]
                except Exception as e:
                    return ClipExtractResult(
                        error=f"Failed to create concat file: {e}",
                        extraction_time_ms=(time.perf_counter() - start_time) * 1000,
                    )
            
            # Run ffmpeg asynchronously
            logger.debug(f"Running ffmpeg: {' '.join(cmd)}")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            extraction_time = (time.perf_counter() - start_time) * 1000
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown ffmpeg error"
                logger.error(f"ffmpeg failed: {error_msg}")
                
                # Clean up partial output
                if output_path.exists():
                    output_path.unlink(missing_ok=True)
                
                return ClipExtractResult(
                    error=f"ffmpeg failed: {error_msg}",
                    extraction_time_ms=extraction_time,
                    source_segments=[str(s) for s in segments],
                )
            
            # Verify output file
            if not output_path.exists() or output_path.stat().st_size == 0:
                return ClipExtractResult(
                    error="Output file not created or empty",
                    extraction_time_ms=extraction_time,
                    source_segments=[str(s) for s in segments],
                )
            
            # Get clip duration
            duration = clip_end - clip_start
            
            logger.info(f"Clip extracted: {clip_url} ({duration:.1f}s, {extraction_time:.1f}ms)")
            
            return ClipExtractResult(
                clip_url=clip_url,
                clip_path=str(output_path),
                duration_sec=duration,
                extraction_time_ms=extraction_time,
                source_segments=[str(s) for s in segments],
            )
            
        except asyncio.TimeoutError:
            return ClipExtractResult(
                error="ffmpeg timeout",
                extraction_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Clip extraction failed: {e}")
            return ClipExtractResult(
                error=str(e),
                extraction_time_ms=(time.perf_counter() - start_time) * 1000,
            )
    
    def extract_clip_sync(
        self,
        camera_id: str,
        event_timestamp: float,
        pre_roll_sec: Optional[float] = None,
        post_roll_sec: Optional[float] = None,
        event_id: Optional[str] = None,
    ) -> ClipExtractResult:
        """Synchronous version for testing."""
        return asyncio.run(self.extract_clip(camera_id, event_timestamp, pre_roll_sec, post_roll_sec, event_id))
    
    async def verify_clip(self, clip_path: Path) -> bool:
        """Verify clip is playable and has valid duration."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration",
                "-of", "csv=p=0",
                str(clip_path)
            ]
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0 and stdout:
                duration = float(stdout.decode().strip())
                return duration > 0
            return False
        except Exception:
            return False


# Global instance
_clip_extractor: Optional[ClipExtractor] = None


def get_clip_extractor(
    recordings_dir: str = "recordings",
    clips_dir: str = "app/static/evidence/clips",
    ffmpeg_path: str = "ffmpeg",
    pre_roll_sec: float = 3.0,
    post_roll_sec: float = 3.0,
) -> ClipExtractor:
    """Get or create the global clip extractor instance."""
    global _clip_extractor
    if _clip_extractor is None:
        _clip_extractor = ClipExtractor(
            recordings_dir=recordings_dir,
            clips_dir=clips_dir,
            ffmpeg_path=ffmpeg_path,
            pre_roll_sec=pre_roll_sec,
            post_roll_sec=post_roll_sec,
        )
    return _clip_extractor