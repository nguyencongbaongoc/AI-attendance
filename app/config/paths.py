"""
Path management module for Windows native AI attendance system.

Provides OS-safe path handling using pathlib.
No hardcoded platform-specific paths outside the platform layer.

Standard project paths:
- project_root
- config
- models
- logs
- data
- recordings
- benchmark_results
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class ProjectPaths:
    """
    Centralized path management for the project.

    All paths are resolved to absolute paths using pathlib.
    """

    def __init__(self, project_root: Optional[Path] = None):
        """
        Initialize project paths.

        Args:
            project_root: Optional explicit project root. If not provided,
                         attempts to find it from the current file location.
        """
        if project_root is not None:
            self._project_root = Path(project_root).resolve()
        else:
            # Try to find project root from this file's location
            self._project_root = Path(__file__).parent.parent.parent.resolve()

        # Define standard paths
        self._config_dir = self._project_root / "config"
        self._models_dir = self._project_root / "models"
        self._logs_dir = self._project_root / "logs"
        self._data_dir = self._project_root / "data"
        self._recordings_dir = self._project_root / "recordings"
        self._benchmark_results_dir = self._project_root / "benchmark_results"

        # Model subdirectories
        self._scrfd_dir = self._models_dir / "scrfd"
        self._arcface_dir = self._models_dir / "arcface"
        self._landmark_dir = self._models_dir / "landmark"
        self._reid_dir = self._models_dir / "reid"
        self._yolo_dir = self._models_dir / "yolo"

    @property
    def project_root(self) -> Path:
        """Project root directory."""
        return self._project_root

    @property
    def config_dir(self) -> Path:
        """Configuration directory."""
        return self._config_dir

    @property
    def models_dir(self) -> Path:
        """Models directory."""
        return self._models_dir

    @property
    def logs_dir(self) -> Path:
        """Logs directory."""
        return self._logs_dir

    @property
    def data_dir(self) -> Path:
        """Data directory."""
        return self._data_dir

    @property
    def recordings_dir(self) -> Path:
        """Recordings directory."""
        return self._recordings_dir

    @property
    def benchmark_results_dir(self) -> Path:
        """Benchmark results directory."""
        return self._benchmark_results_dir

    @property
    def scrfd_dir(self) -> Path:
        """SCRFD models directory."""
        return self._scrfd_dir

    @property
    def arcface_dir(self) -> Path:
        """ArcFace models directory."""
        return self._arcface_dir

    @property
    def landmark_dir(self) -> Path:
        """Landmark models directory."""
        return self._landmark_dir

    @property
    def reid_dir(self) -> Path:
        """ReID models directory."""
        return self._reid_dir

    @property
    def yolo_dir(self) -> Path:
        """YOLO models directory."""
        return self._yolo_dir

    def ensure_directories(self) -> None:
        """Create all standard directories if they don't exist."""
        directories = [
            self._config_dir,
            self._models_dir,
            self._logs_dir,
            self._data_dir,
            self._recordings_dir,
            self._benchmark_results_dir,
            self._scrfd_dir,
            self._arcface_dir,
            self._landmark_dir,
            self._reid_dir,
            self._yolo_dir,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def get_model_dir(self, model_type: str) -> Path:
        """
        Get model directory for a specific model type.

        Args:
            model_type: One of 'scrfd', 'arcface', 'landmark', 'reid', 'yolo'

        Returns:
            Path to the model directory.

        Raises:
            ValueError: If model_type is not recognized.
        """
        model_dirs = {
            "scrfd": self._scrfd_dir,
            "arcface": self._arcface_dir,
            "landmark": self._landmark_dir,
            "reid": self._reid_dir,
            "yolo": self._yolo_dir,
        }

        if model_type not in model_dirs:
            raise ValueError(f"Unknown model type: {model_type}. Valid types: {list(model_dirs.keys())}")

        return model_dirs[model_type]

    def to_dict(self) -> dict:
        """Return all paths as a dictionary."""
        return {
            "project_root": str(self._project_root),
            "config_dir": str(self._config_dir),
            "models_dir": str(self._models_dir),
            "logs_dir": str(self._logs_dir),
            "data_dir": str(self._data_dir),
            "recordings_dir": str(self._recordings_dir),
            "benchmark_results_dir": str(self._benchmark_results_dir),
            "scrfd_dir": str(self._scrfd_dir),
            "arcface_dir": str(self._arcface_dir),
            "landmark_dir": str(self._landmark_dir),
            "reid_dir": str(self._reid_dir),
            "yolo_dir": str(self._yolo_dir),
        }


# Global instance for convenience
_project_paths: Optional[ProjectPaths] = None


def get_project_paths(project_root: Optional[Path] = None) -> ProjectPaths:
    """
    Get the global ProjectPaths instance.

    Args:
        project_root: Optional explicit project root (only used on first call).

    Returns:
        ProjectPaths instance.
    """
    global _project_paths
    if _project_paths is None:
        _project_paths = ProjectPaths(project_root)
    return _project_paths


def set_project_paths(paths: ProjectPaths) -> None:
    """Set the global ProjectPaths instance (mainly for testing)."""
    global _project_paths
    _project_paths = paths