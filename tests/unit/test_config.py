"""
Unit tests for configuration module.

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
import tempfile
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings, load_settings


class TestSettings:
    """Tests for Settings class."""

    def test_settings_creation(self):
        """Settings should be creatable with defaults."""
        settings = Settings()
        assert isinstance(settings, Settings)

    def test_all_sections_exist(self):
        """All configuration sections should exist."""
        settings = Settings()

        assert hasattr(settings, "runtime")
        assert hasattr(settings, "paths")
        assert hasattr(settings, "models")
        assert hasattr(settings, "cameras")
        assert hasattr(settings, "media")
        assert hasattr(settings, "inference")
        assert hasattr(settings, "tracking")
        assert hasattr(settings, "attendance")
        assert hasattr(settings, "stranger")
        assert hasattr(settings, "geometry")
        assert hasattr(settings, "storage")
        assert hasattr(settings, "monitoring")

    def test_runtime_config_defaults(self):
        """Runtime config should have expected defaults."""
        settings = Settings()

        assert settings.runtime.log_level == "INFO"
        assert settings.runtime.debug is False

    def test_paths_config_defaults(self):
        """Paths config should have expected defaults."""
        settings = Settings()

        assert isinstance(settings.paths.project_root, Path)
        assert isinstance(settings.paths.config_dir, Path)
        assert isinstance(settings.paths.models_dir, Path)
        assert isinstance(settings.paths.logs_dir, Path)
        assert isinstance(settings.paths.data_dir, Path)
        assert isinstance(settings.paths.recordings_dir, Path)
        assert isinstance(settings.paths.benchmark_results_dir, Path)

    def test_models_config_defaults(self):
        """Models config should have expected defaults."""
        settings = Settings()

        assert isinstance(settings.models.scrfd_dir, Path)
        assert isinstance(settings.models.arcface_dir, Path)
        assert isinstance(settings.models.landmark_dir, Path)
        assert isinstance(settings.models.reid_dir, Path)
        assert isinstance(settings.models.yolo_dir, Path)

    def test_media_config_defaults(self):
        """Media config should have expected defaults."""
        settings = Settings()

        assert settings.media.ffmpeg_path is None

    def test_inference_config_defaults(self):
        """Inference config should have expected defaults."""
        settings = Settings()

        assert settings.inference.device == "auto"
        assert settings.inference.batch_size == 1

    def test_ensure_directories_creates_all(self):
        """ensure_directories should create all configured directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = Settings()
            settings.paths.project_root = root
            settings.paths.config_dir = root / "config"
            settings.paths.models_dir = root / "models"
            settings.paths.logs_dir = root / "logs"
            settings.paths.data_dir = root / "data"
            settings.paths.recordings_dir = root / "recordings"
            settings.paths.benchmark_results_dir = root / "benchmark_results"

            settings.models.scrfd_dir = root / "models" / "scrfd"
            settings.models.arcface_dir = root / "models" / "arcface"
            settings.models.landmark_dir = root / "models" / "landmark"
            settings.models.reid_dir = root / "models" / "reid"
            settings.models.yolo_dir = root / "models" / "yolo"

            settings.ensure_directories()

            # Check all directories were created
            assert settings.paths.config_dir.exists()
            assert settings.paths.models_dir.exists()
            assert settings.paths.logs_dir.exists()
            assert settings.paths.data_dir.exists()
            assert settings.paths.recordings_dir.exists()
            assert settings.paths.benchmark_results_dir.exists()
            assert settings.models.scrfd_dir.exists()
            assert settings.models.arcface_dir.exists()
            assert settings.models.landmark_dir.exists()
            assert settings.models.reid_dir.exists()
            assert settings.models.yolo_dir.exists()


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_load_settings_without_file(self):
        """load_settings should work without config file."""
        settings = load_settings()
        assert isinstance(settings, Settings)

    def test_load_settings_with_yaml_file(self):
        """load_settings should load from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.yaml"
            config_file.write_text("""
runtime:
  log_level: DEBUG
  debug: true
media:
  ffmpeg_path: "/custom/ffmpeg"
""")

            settings = load_settings(config_file)

            assert settings.runtime.log_level == "DEBUG"
            assert settings.runtime.debug is True
            assert settings.media.ffmpeg_path == "/custom/ffmpeg"

    def test_load_settings_merges_with_defaults(self):
        """load_settings should merge file config with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "test_config.yaml"
            config_file.write_text("""
runtime:
  log_level: DEBUG
""")

            settings = load_settings(config_file)

            # File value should override
            assert settings.runtime.log_level == "DEBUG"
            # Default should remain
            assert settings.runtime.debug is False

    def test_load_settings_nonexistent_file(self):
        """load_settings should handle nonexistent file gracefully."""
        settings = load_settings(Path("/nonexistent/config.yaml"))
        assert isinstance(settings, Settings)
        # Should use defaults
        assert settings.runtime.log_level == "INFO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])