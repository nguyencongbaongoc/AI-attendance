"""
Unit tests for path management module.

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

from app.config.paths import ProjectPaths, get_project_paths, set_project_paths


class TestProjectPaths:
    """Tests for ProjectPaths class."""

    def test_init_with_explicit_root(self):
        """ProjectPaths should accept explicit project root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)
            assert paths.project_root == root.resolve()

    def test_init_without_root(self):
        """ProjectPaths should work without explicit root."""
        paths = ProjectPaths()
        assert paths.project_root is not None
        assert paths.project_root.exists()

    def test_all_standard_paths_exist(self):
        """All standard path properties should return Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            # Check all standard paths
            assert isinstance(paths.config_dir, Path)
            assert isinstance(paths.models_dir, Path)
            assert isinstance(paths.logs_dir, Path)
            assert isinstance(paths.data_dir, Path)
            assert isinstance(paths.recordings_dir, Path)
            assert isinstance(paths.benchmark_results_dir, Path)

    def test_all_model_paths_exist(self):
        """All model subdirectory paths should return Path objects."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            assert isinstance(paths.scrfd_dir, Path)
            assert isinstance(paths.arcface_dir, Path)
            assert isinstance(paths.landmark_dir, Path)
            assert isinstance(paths.reid_dir, Path)
            assert isinstance(paths.yolo_dir, Path)

    def test_paths_are_absolute(self):
        """All paths should be absolute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            for attr_name in dir(paths):
                if not attr_name.startswith("_") and attr_name.endswith("_dir"):
                    path = getattr(paths, attr_name)
                    if isinstance(path, Path):
                        assert path.is_absolute()

    def test_ensure_directories_creates_all(self):
        """ensure_directories should create all standard directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            paths.ensure_directories()

            # Check all directories were created
            assert paths.config_dir.exists()
            assert paths.models_dir.exists()
            assert paths.logs_dir.exists()
            assert paths.data_dir.exists()
            assert paths.recordings_dir.exists()
            assert paths.benchmark_results_dir.exists()
            assert paths.scrfd_dir.exists()
            assert paths.arcface_dir.exists()
            assert paths.landmark_dir.exists()
            assert paths.reid_dir.exists()
            assert paths.yolo_dir.exists()

    def test_get_model_dir_valid_types(self):
        """get_model_dir should return correct paths for valid types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            assert paths.get_model_dir("scrfd") == paths.scrfd_dir
            assert paths.get_model_dir("arcface") == paths.arcface_dir
            assert paths.get_model_dir("landmark") == paths.landmark_dir
            assert paths.get_model_dir("reid") == paths.reid_dir
            assert paths.get_model_dir("yolo") == paths.yolo_dir

    def test_get_model_dir_invalid_type_raises(self):
        """get_model_dir should raise ValueError for invalid types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            with pytest.raises(ValueError) as exc_info:
                paths.get_model_dir("invalid_type")

            assert "Unknown model type" in str(exc_info.value)
            assert "scrfd" in str(exc_info.value)

    def test_to_dict_returns_all_paths(self):
        """to_dict should return dictionary with all paths as strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ProjectPaths(root)

            d = paths.to_dict()

            assert isinstance(d, dict)
            expected_keys = {
                "project_root",
                "config_dir",
                "models_dir",
                "logs_dir",
                "data_dir",
                "recordings_dir",
                "benchmark_results_dir",
                "scrfd_dir",
                "arcface_dir",
                "landmark_dir",
                "reid_dir",
                "yolo_dir",
            }
            assert set(d.keys()) == expected_keys

            # All values should be strings
            for value in d.values():
                assert isinstance(value, str)


class TestGlobalProjectPaths:
    """Tests for global ProjectPaths functions."""

    def test_get_project_paths_returns_instance(self):
        """get_project_paths should return a ProjectPaths instance."""
        # Reset global state
        set_project_paths(None)

        paths = get_project_paths()
        assert isinstance(paths, ProjectPaths)

    def test_get_project_paths_caches_instance(self):
        """get_project_paths should return cached instance on subsequent calls."""
        set_project_paths(None)

        paths1 = get_project_paths()
        paths2 = get_project_paths()

        assert paths1 is paths2

    def test_set_project_paths_overrides_global(self):
        """set_project_paths should override the global instance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            custom_paths = ProjectPaths(root)

            set_project_paths(custom_paths)
            paths = get_project_paths()

            assert paths is custom_paths
            assert paths.project_root == root.resolve()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])