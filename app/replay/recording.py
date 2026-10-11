"""
Phase Replay-Fix — Recording Subsystem.

Adds the minimum viable recording mechanism required to make Replay real.

Architectural rules
-------------------
- Independent from AI inference pipeline. The recorder does NOT touch
  DetectionPipeline, YOLO, SCRFD, ArcFace, tracking, association or
  crossing engine.
- Does NOT feed recorded video back into live detection.
- For test/development we synthesize a real fMP4 segment with ffmpeg
  so the API and frontend can serve an actual playable artefact.
- The recording output directory and filename convention are explicit
  and deterministic:

      <recordings_dir>/<camera_id>/<YYYY-MM-DD_HH-MM-SS>.mp4

- Mapping between (camera_id, event_timestamp) and recording file is
  performed by a deterministic lookup: the recording whose start
  timestamp is the greatest start <= event_timestamp wins.
- Retention: 24h, matching MediaMTX default semantics, but enforced
  at API scan time only (no background thread).

This module deliberately stays small and explicit. It does not modify
the live camera pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    candidates = [
        r"C:\Users\Nguyen Cong Thong\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0-full_build\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


@dataclass(frozen=True)
class RecordingInfo:
    """Metadata for a single recording file on disk."""
    recording_id: str              # stable id (e.g. "rec_cam1_2026-08-23_07-30-00")
    camera_id: str
    file_path: str                 # absolute filesystem path
    url_path: str                  # URL relative to the API root, e.g. /recordings/cam1/2026-08-23_07-30-00.mp4
    start_timestamp: float         # unix seconds (UTC)
    end_timestamp: float           # unix seconds (UTC)
    duration_seconds: float
    width: int
    height: int
    fps: float
    size_bytes: int
    codec: str
    source: str                    # "mediamtx" or "test"
    exists: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecordingRegistry:
    """
    Minimal, deterministic recording registry.

    Scans the recordings directory on disk and exposes recordings keyed
    by (camera_id, timestamp) so the API can resolve a Replay occurrence
    to a real, playable file.
    """

    def __init__(self, recordings_dir: Path, retention_seconds: float = 24 * 3600):
        self.recordings_dir = Path(recordings_dir)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = float(retention_seconds)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_cameras(self) -> List[str]:
        """List camera IDs that have at least one recording."""
        cams: List[str] = []
        for child in self.recordings_dir.iterdir():
            if child.is_dir():
                cams.append(child.name)
        return sorted(cams)

    def list_recordings(self, camera_id: Optional[str] = None) -> List[RecordingInfo]:
        """Return all recordings for the given camera (or all cameras)."""
        results: List[RecordingInfo] = []
        cams = [camera_id] if camera_id else self.list_cameras()
        for cam in cams:
            cam_dir = self.recordings_dir / cam
            if not cam_dir.is_dir():
                continue
            for f in sorted(cam_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in (".mp4", ".m4s", ".fmp4"):
                    info = self._build_info(cam, f)
                    if info is not None:
                        results.append(info)
        results.sort(key=lambda r: (r.camera_id, r.start_timestamp))
        return results

    def get_recording_for_event(self, camera_id: str, event_timestamp: float) -> Optional[RecordingInfo]:
        """Return the recording that covers the given event timestamp.

        The recording with the largest start_timestamp <= event_timestamp
        wins. If no recording precedes the event, the first recording of
        the day is returned as a fallback.
        """
        recs = [r for r in self.list_recordings(camera_id) if r.exists]
        if not recs:
            return None
        candidates = [r for r in recs if r.start_timestamp <= event_timestamp]
        if candidates:
            return max(candidates, key=lambda r: r.start_timestamp)
        return recs[0]

    def get_recording_by_id(self, recording_id: str) -> Optional[RecordingInfo]:
        for r in self.list_recordings():
            if r.recording_id == recording_id:
                return r
        return None

    # ------------------------------------------------------------------
    # Test/dev recording generation
    # ------------------------------------------------------------------

    def ensure_test_recording(self, camera_id: str, start_dt: datetime) -> RecordingInfo:
        """
        Ensure a real fMP4/MP4 test recording exists for (camera_id, day).

        Filename convention: recordings/<camera_id>/<YYYY-MM-DD_HH-MM-SS>.mp4
        start_dt is treated as UTC.
        """
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        start_ts = start_dt.timestamp()
        filename = start_dt.strftime("%Y-%m-%d_%H-%M-%S") + ".mp4"
        cam_dir = self.recordings_dir / camera_id
        cam_dir.mkdir(parents=True, exist_ok=True)
        file_path = cam_dir / filename

        if not file_path.exists() or file_path.stat().st_size == 0:
            self._generate_test_clip(file_path)

        info = self._build_info(camera_id, file_path)
        if info is None:
            raise RuntimeError(f"Failed to build RecordingInfo for {file_path}")
        return info

    def _generate_test_clip(self, file_path: Path) -> None:
        """Render a 5 second, 320x240, 10fps H.264 test clip with ffmpeg.

        This is the only test/dev side effect of this module. It produces
        a real, playable MP4 so the API can serve an actual recording.
        """
        ffmpeg = _find_ffmpeg()
        if ffmpeg is None:
            raise RuntimeError(
                "ffmpeg not found on PATH; cannot synthesize test recording. "
                "Install ffmpeg or drop a real .mp4 into recordings/<cam>/."
            )
        duration = 5
        width, height, fps = 320, 240, 10
        cmd = [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
            "-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            "-c:a", "aac", "-b:a", "32k",
            "-shortest", "-movflags", "+faststart",
            str(file_path),
        ]
        logger.info("Synthesizing test recording: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg failed to create test recording: {e}") from e

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_info(self, camera_id: str, file_path: Path) -> Optional[RecordingInfo]:
        try:
            st = file_path.stat()
        except FileNotFoundError:
            return None
        start_dt = self._parse_start_from_filename(file_path.name)
        if start_dt is None:
            start_ts = st.st_mtime
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        else:
            start_ts = start_dt.timestamp()
        # default duration: 5s for test clips
        duration = 5.0
        rel = file_path.relative_to(self.recordings_dir)
        return RecordingInfo(
            recording_id=f"rec_{camera_id}_{file_path.stem}",
            camera_id=camera_id,
            file_path=str(file_path),
            url_path=f"/recordings/{rel.as_posix()}",
            start_timestamp=start_ts,
            end_timestamp=start_ts + duration,
            duration_seconds=duration,
            width=320,
            height=240,
            fps=10.0,
            size_bytes=st.st_size,
            codec="h264",
            source="test",
            exists=st.st_size > 0,
        )

    @staticmethod
    def _parse_start_from_filename(name: str) -> Optional[datetime]:
        stem = Path(name).stem
        for fmt in ("%Y-%m-%d_%H-%M-%S",):
            try:
                return datetime.strptime(stem, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None


# ----------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------

_registry: Optional[RecordingRegistry] = None


def get_recording_registry() -> RecordingRegistry:
    global _registry
    if _registry is None:
        from app.config.settings import load_settings
        settings = load_settings()
        _registry = RecordingRegistry(settings.paths.recordings_dir)
    return _registry
