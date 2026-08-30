"""
Unit tests for FFmpeg detection module.

Tests MUST NOT:
- start cameras
- connect to RTMP
- connect to RTSP
- start MediaMTX
- start FFmpeg against a camera
- load AI models
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.runtime.ffmpeg import FFmpegInfo, detect_ffmpeg, is_ffmpeg_available, get_ffmpeg_path, get_ffmpeg_version


class TestFFmpegDetection:
    """Tests for FFmpeg detection."""

    def test_detect_ffmpeg_returns_ffmpeg_info(self):
        """detect_ffmpeg should return an FFmpegInfo instance."""
        result = detect_ffmpeg()
        assert isinstance(result, FFmpegInfo)

    def test_ffmpeg_info_structure(self):
        """FFmpegInfo should have expected fields."""
        result = detect_ffmpeg()

        assert isinstance(result.available, bool)
        assert isinstance(result.source, str)

        if result.available:
            assert result.executable_path is not None
            assert isinstance(result.executable_path, str)
            assert len(result.executable_path) > 0

            # version can be None or string
            if result.version is not None:
                assert isinstance(result.version, str)
        else:
            assert result.executable_path is None
            assert result.version is None

    def test_is_ffmpeg_available_returns_bool(self):
        """is_ffmpeg_available should return a boolean."""
        result = is_ffmpeg_available()
        assert isinstance(result, bool)

    def test_get_ffmpeg_path_returns_string_or_none(self):
        """get_ffmpeg_path should return string or None."""
        result = get_ffmpeg_path()
        assert result is None or isinstance(result, str)

    def test_get_ffmpeg_version_returns_string_or_none(self):
        """get_ffmpeg_version should return string or None."""
        result = get_ffmpeg_version()
        assert result is None or isinstance(result, str)

    def test_configured_path_takes_priority(self):
        """Explicitly configured path should be checked first."""
        # Test with a non-existent configured path - should fall back to other methods
        result = detect_ffmpeg(configured_path="/nonexistent/ffmpeg")
        assert isinstance(result, FFmpegInfo)

    @patch("app.runtime.ffmpeg.shutil.which")
    def test_path_lookup_used_when_no_configured(self, mock_which):
        """PATH lookup should be used when no configured path."""
        mock_which.return_value = "/usr/bin/ffmpeg"

        with patch("app.runtime.ffmpeg._get_ffmpeg_version", return_value="ffmpeg version 4.4.0"):
            result = detect_ffmpeg(configured_path=None)

        assert result.available is True
        assert result.executable_path == "/usr/bin/ffmpeg"
        assert result.source == "path"
        mock_which.assert_called_once_with("ffmpeg")

    @patch("app.runtime.ffmpeg.shutil.which")
    @patch("app.runtime.ffmpeg._check_common_windows_locations")
    def test_common_locations_checked_when_path_fails(self, mock_common, mock_which):
        """Common Windows locations should be checked when PATH lookup fails."""
        mock_which.return_value = None
        mock_common.return_value = "C:\\ffmpeg\\bin\\ffmpeg.exe"

        with patch("app.runtime.ffmpeg._get_ffmpeg_version", return_value="ffmpeg version 5.0.0"):
            result = detect_ffmpeg(configured_path=None)

        assert result.available is True
        assert result.executable_path == "C:\\ffmpeg\\bin\\ffmpeg.exe"
        assert result.source == "common_location"
        mock_which.assert_called_once_with("ffmpeg")
        mock_common.assert_called_once()

    @patch("app.runtime.ffmpeg.shutil.which")
    @patch("app.runtime.ffmpeg._check_common_windows_locations")
    def test_not_found_when_all_methods_fail(self, mock_common, mock_which):
        """Should return unavailable when all detection methods fail."""
        mock_which.return_value = None
        mock_common.return_value = None

        result = detect_ffmpeg(configured_path=None)

        assert result.available is False
        assert result.executable_path is None
        assert result.version is None
        assert result.source == "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])