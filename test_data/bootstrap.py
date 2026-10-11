"""
Bootstrap script for Windows native AI attendance system.

This script handles:
1. Detecting Python
2. Creating .venv if missing
3. Using .venv Python
4. Validating dependencies

Usage:
    python bootstrap.py

This script does NOT recursively invoke itself.
This script does NOT silently install packages without reporting.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap.venv_manager import VenvManager


def main() -> int:
    """Run the bootstrap process."""
    print("=" * 60)
    print("AI Attendance System - Bootstrap")
    print("=" * 60)
    print()

    # Step 1: Detect Python
    print("[1/4] Detecting Python...")
    print(f"  Python version: {sys.version}")
    print(f"  Python executable: {sys.executable}")
    print()

    # Check Python version requirement (3.11+)
    if sys.version_info < (3, 11):
        print("  WARNING: Python 3.11+ is recommended for this project.")
        print(f"  Current version: {sys.version_info.major}.{sys.version_info.minor}")
    else:
        print(f"  OK: Python {sys.version_info.major}.{sys.version_info.minor} detected.")
    print()

    # Step 2: Create .venv if missing
    print("[2/4] Checking virtual environment...")
    venv_manager = VenvManager(PROJECT_ROOT)

    if not venv_manager.venv_exists:
        print("  Virtual environment not found. Creating...")
        if not venv_manager.create_venv():
            print("  ERROR: Failed to create virtual environment.")
            return 1
    else:
        print(f"  OK: Virtual environment exists at: {venv_manager.venv_path}")
    print()

    # Step 3: Use .venv Python
    print("[3/4] Validating virtual environment...")
    venv_info = venv_manager.get_venv_info()
    print(f"  Venv path: {venv_info['venv_path']}")
    print(f"  Venv exists: {venv_info['venv_exists']}")
    print(f"  Python executable: {venv_info['python_executable']}")
    print(f"  Venv active: {venv_info['is_active']}")

    if not venv_info["is_active"]:
        print()
        print("  WARNING: Not running inside the project virtual environment.")
        print("  To activate, run:")
        print(f"    {venv_manager.venv_path / 'Scripts' / 'activate.bat'}")
        print("  Or use the venv Python directly:")
        print(f"    {venv_manager.python_executable}")
    print()

    # Step 4: Validate dependencies
    print("[4/4] Validating dependencies...")
    base_requirements = PROJECT_ROOT / "requirements" / "base.txt"
    windows_requirements = PROJECT_ROOT / "requirements" / "windows.txt"

    all_valid = True

    for req_file in [base_requirements, windows_requirements]:
        if not req_file.exists():
            print(f"  SKIP: {req_file} not found.")
            continue

        print(f"  Checking: {req_file.name}")
        result = venv_manager.validate_dependencies(req_file)

        if result["valid"]:
            print(f"    OK: All {result['total']} packages installed.")
        else:
            print(f"    MISSING: {len(result['missing'])} package(s) not installed:")
            for pkg in result["missing"]:
                print(f"      - {pkg}")
            print(f"    To install, run:")
            print(f"      {venv_manager.python_executable} -m pip install -r {req_file}")
            all_valid = False
    print()

    # Summary
    print("=" * 60)
    if all_valid:
        print("Bootstrap completed successfully.")
    else:
        print("Bootstrap completed with warnings (missing dependencies).")
        print("Install missing packages before proceeding.")
    print("=" * 60)

    return 0 if all_valid else 0  # Return 0 even with missing deps - just report


if __name__ == "__main__":
    sys.exit(main())