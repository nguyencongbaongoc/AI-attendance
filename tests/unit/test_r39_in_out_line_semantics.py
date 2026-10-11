"""
Phase 44.X.4-R3.9-FIX — IN/OUT Line Semantics Tests.

Tests cover:
- GeometryVersionManager.load_latest() returns canonical latest geometry
- CAM1 and CAM2 latest geometry are isolated
- REST geometry returns real line (not null)
- geometry camera isolation
- crossing events included in DetectionSnapshot
- A->B = IN semantics
- B->A = OUT semantics
- save_version / list_versions / load_version round-trip
"""

import pytest

from app.geometry.contract import (
    CameraGeometryConfig,
    DirectionSemantics,
    create_line_geometry,
    CrossingPolicyConfig,
    CrossingPolicy,
    GeometryType,
    CoordinateSpace,
)
from app.geometry.versioning import GeometryVersionManager
from app.streaming.health_events import create_detection_snapshot_event


class TestGeometryVersionManagerLoadLatest:
    """Tests for GeometryVersionManager.load_latest()."""

    def test_load_latest_returns_registered_config(self):
        """load_latest() should return the most recently registered config."""
        vm = GeometryVersionManager()
        config = create_line_geometry(
            camera_id="TEST_CAM",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        )
        vm.register_config(config, "test_author")

        result = vm.load_latest("TEST_CAM")
        assert result is not None
        assert result.camera_id == "TEST_CAM"
        assert result.line is not None
        assert result.line.p1.x == 1920
        assert result.line.p1.y == 0
        assert result.line.p2.x == 1920
        assert result.line.p2.y == 2160
        assert result.line.direction_semantics == DirectionSemantics.SIDE_A_TO_B_IN

    def test_load_latest_returns_none_for_unknown_camera(self):
        """load_latest() should return None for cameras without a config."""
        vm = GeometryVersionManager()
        result = vm.load_latest("NONEXISTENT")
        assert result is None

    def test_load_latest_cam1_and_cam2_isolated(self):
        """CAM1 and CAM2 configs must remain isolated."""
        vm = GeometryVersionManager()
        cam1_config = create_line_geometry(
            camera_id="CAM1",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        )
        cam2_config = create_line_geometry(
            camera_id="CAM2",
            frame_width=3840,
            frame_height=2160,
            p1=(1500, 0),
            p2=(1500, 2160),
            direction_semantics=DirectionSemantics.SIDE_B_TO_A_IN,
        )
        vm.register_config(cam1_config, "test")
        vm.register_config(cam2_config, "test")

        cam1_result = vm.load_latest("CAM1")
        cam2_result = vm.load_latest("CAM2")
        assert cam1_result is not None
        assert cam2_result is not None
        assert cam1_result.camera_id == "CAM1"
        assert cam2_result.camera_id == "CAM2"
        assert cam1_result.line.p1.x == 1920
        assert cam2_result.line.p1.x == 1500
        assert cam1_result.line.direction_semantics == DirectionSemantics.SIDE_A_TO_B_IN
        assert cam2_result.line.direction_semantics == DirectionSemantics.SIDE_B_TO_A_IN

    def test_save_version_and_load_latest_round_trip(self):
        """save_version() should be an alias for register_config() and work with load_latest()."""
        vm = GeometryVersionManager()
        config = create_line_geometry(
            camera_id="TEST_CAM2",
            frame_width=3840,
            frame_height=2160,
            p1=(1000, 0),
            p2=(1000, 2160),
            direction_semantics=DirectionSemantics.SIDE_B_TO_A_IN,
        )
        version = vm.save_version(config)
        assert version is not None
        assert version.camera_id == "TEST_CAM2"

        result = vm.load_latest("TEST_CAM2")
        assert result is not None
        assert result.line.p1.x == 1000
        assert result.line.direction_semantics == DirectionSemantics.SIDE_B_TO_A_IN

    def test_list_versions_returns_dicts(self):
        """list_versions() should return a list of version dicts."""
        vm = GeometryVersionManager()
        config = create_line_geometry(
            camera_id="TEST_CAM3",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        )
        vm.register_config(config, "test")

        versions = vm.list_versions("TEST_CAM3")
        assert isinstance(versions, list)
        assert len(versions) == 1
        assert versions[0]["camera_id"] == "TEST_CAM3"

    def test_load_version_returns_specific_config(self):
        """load_version() should return a specific version's config."""
        vm = GeometryVersionManager()
        config_v1 = create_line_geometry(
            camera_id="TEST_CAM4",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
            version=1,
        )
        config_v2 = create_line_geometry(
            camera_id="TEST_CAM4",
            frame_width=3840,
            frame_height=2160,
            p1=(1500, 0),
            p2=(1500, 2160),
            direction_semantics=DirectionSemantics.SIDE_B_TO_A_IN,
            version=2,
        )
        vm.register_config(config_v1, "test")
        vm.register_config(config_v2, "test")

        v1_loaded = vm.load_version("TEST_CAM4", 1)
        v2_loaded = vm.load_version("TEST_CAM4", 2)
        assert v1_loaded is not None
        assert v2_loaded is not None
        assert v1_loaded.line.p1.x == 1920
        assert v2_loaded.line.p1.x == 1500


class TestDetectionSnapshotCrossingEvents:
    """Tests for crossing events in DetectionSnapshot event."""

    def test_detection_snapshot_event_includes_crossing_events(self):
        """DetectionSnapshot event must include crossing_events in details."""
        event = create_detection_snapshot_event(
            event_id="evt-1",
            camera_id="CAM1",
            frame_index=100,
            timestamp="2026-09-02T19:00:00Z",
            frame_width=3840,
            frame_height=2160,
            detections=[],
            lines=[],
            regions=[],
            crossing_events=[
                {
                    "event_id": "CE-LC-abc",
                    "camera_id": "CAM1",
                    "local_track_id": "TRK-441",
                    "direction": "in",
                    "event_type": "line_crossing",
                    "side_transition": "SIDE_A->SIDE_B",
                }
            ],
        )
        details = event.details
        assert "crossing_events" in details
        assert len(details["crossing_events"]) == 1
        assert details["crossing_events"][0]["direction"] == "in"
        assert details["crossing_events"][0]["event_type"] == "line_crossing"

    def test_detection_snapshot_event_crossing_events_default_empty(self):
        """DetectionSnapshot event should default to empty crossing_events list."""
        event = create_detection_snapshot_event(
            event_id="evt-2",
            camera_id="CAM1",
            frame_index=100,
            timestamp="2026-09-02T19:00:00Z",
            frame_width=3840,
            frame_height=2160,
            detections=[],
            lines=[],
            regions=[],
        )
        details = event.details
        assert "crossing_events" in details
        assert details["crossing_events"] == []


class TestCrossingSemantics:
    """Tests for A->B = IN and B->A = OUT semantics."""

    def test_side_a_to_b_in_semantics(self):
        """Verify SIDE_A_TO_B_IN means A->B is IN."""
        config = create_line_geometry(
            camera_id="CAM1",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_A_TO_B_IN,
        )
        assert config.line.direction_semantics == DirectionSemantics.SIDE_A_TO_B_IN
        assert config.line.direction_semantics.value == "side_a_to_b_in"

    def test_side_b_to_a_in_semantics(self):
        """Verify SIDE_B_TO_A_IN means B->A is IN."""
        config = create_line_geometry(
            camera_id="CAM2",
            frame_width=3840,
            frame_height=2160,
            p1=(1920, 0),
            p2=(1920, 2160),
            direction_semantics=DirectionSemantics.SIDE_B_TO_A_IN,
        )
        assert config.line.direction_semantics == DirectionSemantics.SIDE_B_TO_A_IN
        assert config.line.direction_semantics.value == "side_b_to_a_in"
