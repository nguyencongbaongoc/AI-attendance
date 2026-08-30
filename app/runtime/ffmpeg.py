"""
FFmpeg detection contract for Windows native AI attendance system.

Provides executable discovery utility supporting:
- PATH lookup
- Explicit configured path

This module does NOT start FFmpeg.
This module does NOT connect FFmpeg to any camera.

Reports:
- executable path
- version if safely obtainable
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FFmpegInfo:
    """FFmpeg detection result."""

    available: bool
    executable_path: Optional[str] = None
    version: Optional[str] = None
    source: str = "unknown"  # "path", "configured", "common_location"


def _get_ffmpeg_version(executable: str) -> Optional[str]:
    """
    Safely get FFmpeg version.

    Args:
        executable: Path to FFmpeg executable.

    Returns:
        Version string or None if unable to determine.
    """
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if result.returncode == 0 and result.stdout:
            # Extract first line which contains version info
            first_line = result.stdout.split("\n")[0]
            return first_line.strip()
    except Exception:
        pass
    return None


def _check_common_windows_locations() -> Optional[str]:
    """Check common Windows FFmpeg installation locations."""
    common_paths = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(os.environ.get("USERPROFILE", "")) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/tools/ffmpeg/bin/ffmpeg.exe"),
    ]

    for path in common_paths:
        try:
            if path.exists() and path.is_file():
                return str(path)
        except (OSError, ValueError):
            continue

    return None


def detect_ffmpeg(configured_path: Optional[str] = None) -> FFmpegInfo:
    """
    Detect FFmpeg executable.

    Search order:
    1. Explicitly configured path (if provided)
    2. PATH lookup (shutil.which)
    3. Common Windows installation locations

    Args:
        configured_path: Optional explicit path to FFmpeg executable.

    Returns:
        FFmpegInfo with detection results.
    """
    # 1. Check configured path first
    if configured_path:
        path = Path(configured_path)
        if path.exists() and path.is_file():
            version = _get_ffmpeg_version(str(path))
            return FFmpegInfo(
                available=True,
                executable_path=str(path),
                version=version,
                source="configured",
            )
        else:
            # Configured path doesn't exist, fall through to other methods
            pass

    # 2. Check PATH
    path_executable = shutil.which("ffmpeg")
    if path_executable:
        version = _get_ffmpeg_version(path_executable)
        return FFmpegInfo(
            available=True,
            executable_path=path_executable,
            version=version,
            source="path",
        )

    # 3. Check common Windows locations
    common_path = _check_common_windows_locations()
    if common_path:
        version = _get_ffmpeg_version(common_path)
        return FFmpegInfo(
            available=True,
            executable_path=common_path,
            version=version,
            source="common_location",
        )

    # Not found
    return FFmpegInfo(available=False)


def is_ffmpeg_available(configured_path: Optional[str] = None) -> bool:
    """Quick check if FFmpeg is available."""
    return detect_ffmpeg(configured_path).available


def get_ffmpeg_path(configured_path: Optional[str] = None) -> Optional[str]:
    """Get FFmpeg executable path if available."""
    return detect_ffmpeg(configured_path).executable_path


def get_ffmpeg_version(configured_path: Optional[str] = None) -> Optional[str]:
    """Get FFmpeg version if available."""
    return detect_ffmpeg(configured_path).version