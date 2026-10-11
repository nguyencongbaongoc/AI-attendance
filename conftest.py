"""
Pytest configuration and shared fixtures for Phase 10 tests.
"""
import pytest
import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)


@pytest.fixture
def camera_id():
    """Camera identifier fixture."""
    return "CAM1"


@pytest.fixture
def rtsp_url():
    """RTSP URL fixture for CAM1."""
    return "rtsp://localhost:8554/live/cam1"


@pytest.fixture
def cam1_url():
    """CAM1 RTSP URL fixture."""
    return "rtsp://localhost:8554/live/cam1"


@pytest.fixture
def cam2_url():
    """CAM2 RTSP URL fixture."""
    return "rtsp://localhost:8554/live/cam2"


@pytest.fixture
def dual_camera_urls():
    """Both camera URLs fixture."""
    return {
        "CAM1": "rtsp://localhost:8554/live/cam1",
        "CAM2": "rtsp://localhost:8554/live/cam2",
    }


@pytest.fixture
def gpu_device():
    """GPU device index fixture."""
    return 0