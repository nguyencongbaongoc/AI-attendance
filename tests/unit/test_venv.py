"""
Unit tests for virtual environment manager.

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

from app.bootstrap.venv_manager import VenvManager


class TestVenvManager:
    """Tests for VenvManager class."""

    def test_init_with_project_root(self):
        """VenvManager should accept project root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)
            assert manager.project_root == root.resolve()
            assert manager.venv_path == root.resolve() / ".venv"

    def test_venv_exists_false_when_missing(self):
        """venv_exists should be False when venv doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)
            assert manager.venv_exists is False

    def test_python_executable_fallback(self):
        """python_executable should fallback to current Python when venv missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)
            # Should return current Python executable
            assert manager.python_executable == Path(sys.executable)

    def test_pip_executable_fallback(self):
        """pip_executable should fallback to python when venv missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)
            assert manager.pip_executable == manager.python_executable

    def test_create_venv_creates_directory(self):
        """create_venv should create the virtual environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            result = manager.create_venv()
            assert result is True
            assert manager.venv_exists is True
            assert (manager.venv_path / "pyvenv.cfg").exists()
            assert (manager.venv_path / "Scripts" / "python.exe").exists()

    def test_create_venv_idempotent(self):
        """create_venv should be idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            result1 = manager.create_venv()
            result2 = manager.create_venv()

            assert result1 is True
            assert result2 is True

    def test_validate_venv_false_when_missing(self):
        """validate_venv should return False when venv doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            result = manager.validate_venv()
            assert result is False

    def test_validate_venv_true_when_exists(self):
        """validate_venv should return True when venv exists and is valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            manager.create_venv()
            result = manager.validate_venv()
            assert result is True

    def test_get_venv_info(self):
        """get_venv_info should return dictionary with venv information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            info = manager.get_venv_info()

            assert isinstance(info, dict)
            assert "venv_path" in info
            assert "venv_exists" in info
            assert "python_executable" in info
            assert "pip_executable" in info
            assert "is_active" in info

            assert info["venv_path"] == str(manager.venv_path)
            assert info["venv_exists"] is False
            assert isinstance(info["python_executable"], str)
            assert isinstance(info["is_active"], bool)

    def test_validate_dependencies_missing_file(self):
        """validate_dependencies should handle missing requirements file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            result = manager.validate_dependencies(Path("/nonexistent/requirements.txt"))

            assert result["valid"] is False
            assert "not found" in result["error"]
            assert result["packages"] == []

    def test_validate_dependencies_empty_file(self):
        """validate_dependencies should handle empty requirements file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            req_file = root / "requirements.txt"
            req_file.write_text("")

            result = manager.validate_dependencies(req_file)

            assert result["valid"] is True
            assert result["installed"] == []
            assert result["missing"] == []
            assert result["total"] == 0

    def test_validate_dependencies_with_comments(self):
        """validate_dependencies should skip comments and empty lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manager = VenvManager(root)

            req_file = root / "requirements.txt"
            req_file.write_text("""
# This is a comment
pydantic>=2.0.0

# Another comment
pyyaml
""")

            result = manager.validate_dependencies(req_file)

            assert result["total"] == 2
            assert "pydantic" in result["missing"] or "pydantic" in result["installed"]
            assert "pyyaml" in result["missing"] or "pyyaml" in result["installed"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])