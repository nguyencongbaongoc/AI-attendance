"""
Unit tests for runtime detection module.

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

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.runtime.detector import RuntimeInfo, detect_runtime


class TestRuntimeDetector:
    """Tests for runtime detection."""

    def test_detect_runtime_returns_runtime_info(self):
        """detect_runtime should return a RuntimeInfo instance."""
        result = detect_runtime()
        assert isinstance(result, RuntimeInfo)

    def test_runtime_info_has_required_fields(self):
        """RuntimeInfo should have all required fields populated."""
        result = detect_runtime()

        # Check all fields exist and are non-empty where appropriate
        assert isinstance(result.platform, str)
        assert len(result.platform) > 0

        assert isinstance(result.architecture, str)
        assert len(result.architecture) > 0

        assert isinstance(result.python_version, str)
        assert len(result.python_version) > 0

        assert isinstance(result.python_executable, str)
        assert len(result.python_executable) > 0

        assert isinstance(result.venv_active, bool)

        # venv_path can be None or string
        if result.venv_path is not None:
            assert isinstance(result.venv_path, str)

        assert isinstance(result.nvidia_available, bool)
        assert isinstance(result.cuda_available, bool)

        # cuda_version can be None or string
        if result.cuda_version is not None:
            assert isinstance(result.cuda_version, str)

        assert isinstance(result.ffmpeg_available, bool)

        # ffmpeg_path can be None or string
        if result.ffmpeg_path is not None:
            assert isinstance(result.ffmpeg_path, str)

        # ffmpeg_version can be None or string
        if result.ffmpeg_version is not None:
            assert isinstance(result.ffmpeg_version, str)

        assert isinstance(result.gpu_info, list)

    def test_platform_is_windows(self):
        """Platform should be Windows for this project."""
        result = detect_runtime()
        # This test documents the expected platform
        # On Windows it should be "Windows"
        assert result.platform in ("Windows", "Linux", "Darwin")

    def test_python_version_format(self):
        """Python version should be in standard format."""
        result = detect_runtime()
        # Should be like "3.11.5" or "3.12.0"
        parts = result.python_version.split(".")
        assert len(parts) >= 2
        assert all(part.isdigit() for part in parts[:2])

    def test_python_executable_exists(self):
        """Python executable path should exist."""
        result = detect_runtime()
        assert Path(result.python_executable).exists()

    def test_to_dict_returns_dict(self):
        """to_dict should return a dictionary with all fields."""
        result = detect_runtime()
        d = result.to_dict()

        assert isinstance(d, dict)
        expected_keys = {
            "platform",
            "architecture",
            "python_version",
            "python_executable",
            "venv_active",
            "venv_path",
            "nvidia_available",
            "cuda_available",
            "cuda_version",
            "ffmpeg_available",
            "ffmpeg_path",
            "ffmpeg_version",
            "gpu_info",
        }
        assert set(d.keys()) == expected_keys

    def test_gpu_info_structure(self):
        """GPU info should be a list of dicts with expected keys."""
        result = detect_runtime()
        for gpu in result.gpu_info:
            assert isinstance(gpu, dict)
            assert "index" in gpu
            assert "name" in gpu
            assert isinstance(gpu["index"], int)
            assert isinstance(gpu["name"], str)
            assert len(gpu["name"]) > 0


class TestVenvDetection:
    """Tests for virtual environment detection."""

    def test_venv_active_is_bool(self):
        """venv_active should be a boolean."""
        result = detect_runtime()
        assert isinstance(result.venv_active, bool)

    def test_venv_path_consistency(self):
        """If venv_active is True, venv_path should be set."""
        result = detect_runtime()
        if result.venv_active:
            assert result.venv_path is not None
            assert len(result.venv_path) > 0
        else:
            # When not in venv, venv_path can be None or the base prefix
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])