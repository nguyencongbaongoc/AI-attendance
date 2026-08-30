"""
Virtual environment manager for Windows native setup.

Handles:
- Detecting Python
- Creating .venv if missing
- Using .venv Python
- Validating dependencies

This module does NOT recursively invoke itself.
This module does NOT silently install packages without reporting.
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv as _venv
from pathlib import Path
from typing import Optional


class VenvManager:
    """Manages virtual environment creation and validation."""

    def __init__(self, project_root: Path, venv_name: str = ".venv"):
        self.project_root = Path(project_root).resolve()
        self.venv_path = self.project_root / venv_name
        self._python_executable: Optional[Path] = None

    @property
    def venv_exists(self) -> bool:
        """Check if the virtual environment directory exists."""
        return self.venv_path.exists() and (self.venv_path / "pyvenv.cfg").exists()

    @property
    def python_executable(self) -> Path:
        """Get the Python executable path for the venv."""
        if self._python_executable is not None:
            return self._python_executable

        if self.venv_exists:
            # Windows venv Python path
            python_exe = self.venv_path / "Scripts" / "python.exe"
            if python_exe.exists():
                self._python_executable = python_exe
                return self._python_executable

        # Fallback to current Python
        self._python_executable = Path(sys.executable)
        return self._python_executable

    @property
    def pip_executable(self) -> Path:
        """Get the pip executable path for the venv."""
        if self.venv_exists:
            pip_exe = self.venv_path / "Scripts" / "pip.exe"
            if pip_exe.exists():
                return pip_exe

        return self.python_executable

    def create_venv(self) -> bool:
        """
        Create the virtual environment if it does not exist.

        Returns:
            True if venv was created or already exists, False on failure.
        """
        if self.venv_exists:
            print(f"[VenvManager] Virtual environment already exists at: {self.venv_path}")
            return True

        print(f"[VenvManager] Creating virtual environment at: {self.venv_path}")

        try:
            _venv.create(
                str(self.venv_path),
                clear=False,
                with_pip=True,
                symlinks=False,  # Windows uses copies, not symlinks
            )
            print(f"[VenvManager] Virtual environment created successfully.")
            return True
        except Exception as e:
            print(f"[VenvManager] Failed to create virtual environment: {e}")
            return False

    def validate_venv(self) -> bool:
        """
        Validate that the virtual environment is properly configured.

        Returns:
            True if venv is valid and active, False otherwise.
        """
        if not self.venv_exists:
            print(f"[VenvManager] Virtual environment does not exist at: {self.venv_path}")
            return False

        # Check if we're running inside the venv
        current_prefix = Path(sys.prefix).resolve()
        venv_scripts = (self.venv_path / "Scripts").resolve()

        try:
            is_active = current_prefix == self.venv_path.resolve()
        except OSError:
            is_active = False

        if not is_active:
            print(
                f"[VenvManager] Warning: Not running inside the project venv. "
                f"Current Python: {sys.executable}"
            )
            print(
                f"[VenvManager] To activate, run: "
                f"{self.venv_path / 'Scripts' / 'activate.bat'}"
            )

        # Verify Python executable exists in venv
        python_exe = self.venv_path / "Scripts" / "python.exe"
        if not python_exe.exists():
            print(f"[VenvManager] Python executable not found in venv: {python_exe}")
            return False

        return True

    def install_requirements(self, requirements_file: Path) -> bool:
        """
        Install requirements from a file using the venv's pip.

        This method reports what is being installed and does NOT silently
        install packages.

        Args:
            requirements_file: Path to the requirements file.

        Returns:
            True if installation succeeded, False otherwise.
        """
        if not self.venv_exists:
            print(f"[VenvManager] Cannot install requirements: venv does not exist.")
            return False

        requirements_file = Path(requirements_file).resolve()
        if not requirements_file.exists():
            print(f"[VenvManager] Requirements file not found: {requirements_file}")
            return False

        print(f"[VenvManager] Installing requirements from: {requirements_file}")
        print(f"[VenvManager] Using pip: {self.pip_executable}")

        try:
            result = subprocess.run(
                [
                    str(self.python_executable),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                print(f"[VenvManager] pip install failed with exit code {result.returncode}")
                if result.stderr:
                    print(f"[VenvManager] stderr: {result.stderr}")
                return False

            print(f"[VenvManager] Requirements installed successfully.")
            return True
        except subprocess.TimeoutExpired:
            print(f"[VenvManager] pip install timed out.")
            return False
        except Exception as e:
            print(f"[VenvManager] Error during pip install: {e}")
            return False

    def validate_dependencies(self, requirements_file: Path) -> dict:
        """
        Validate that all packages in a requirements file are installed.

        This does NOT install missing packages - it only reports status.

        Args:
            requirements_file: Path to the requirements file.

        Returns:
            Dictionary with validation results.
        """
        requirements_file = Path(requirements_file).resolve()
        if not requirements_file.exists():
            return {
                "valid": False,
                "error": f"Requirements file not found: {requirements_file}",
                "packages": [],
            }

        # Parse requirements file
        packages = []
        for line in requirements_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Extract package name (before any version specifier)
            for sep in [">=", "<=", "==", ">", "<", "!=", "~="]:
                if sep in line:
                    line = line.split(sep)[0]
                    break
            packages.append(line.strip())

        # Check which packages are installed
        missing = []
        installed = []
        for pkg in packages:
            try:
                result = subprocess.run(
                    [
                        str(self.python_executable),
                        "-c",
                        f"import importlib.metadata; importlib.metadata.version('{pkg}')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    installed.append(pkg)
                else:
                    missing.append(pkg)
            except Exception:
                missing.append(pkg)

        return {
            "valid": len(missing) == 0,
            "installed": installed,
            "missing": missing,
            "total": len(packages),
        }

    def get_venv_info(self) -> dict:
        """Get information about the virtual environment."""
        return {
            "venv_path": str(self.venv_path),
            "venv_exists": self.venv_exists,
            "python_executable": str(self.python_executable),
            "pip_executable": str(self.pip_executable),
            "is_active": self._is_venv_active(),
        }

    def _is_venv_active(self) -> bool:
        """Check if the current process is running inside this venv."""
        try:
            return Path(sys.prefix).resolve() == self.venv_path.resolve()
        except (OSError, ValueError):
            return False