"""
Phase 32 — Unit Tests for MediaMTX Configuration.

Tests cover:
- Configuration exists
- CAM1 path exists
- CAM2 path exists
- RTMP routes to expected path
- RTSP routes to expected path
- No duplicate paths
"""

import pytest

from app.streaming.mediamtx_config import (
    MediaMTXConfig,
    MediaMTXPathConfig,
    create_mediamtx_config,
    validate_mediamtx_config,
    MEDIAMTX_DEFAULT_CONFIG_YAML,
)


class TestMediaMTXPathConfig:
    """Tests for MediaMTXPathConfig."""

    def test_default_values(self):
        path = MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert path.name == "cam1"
        assert path.rtmp_stream_key == "cam1"
        assert path.rtsp_path == "cam1"
        assert path.source == "publisher"
        assert path.rtsp_transport == "tcp"
        assert path.codec == "h264"

    def test_serialization_roundtrip(self):
        path = MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        data = path.to_dict()
        restored = MediaMTXPathConfig.from_dict(data)
        assert restored.name == path.name
        assert restored.rtmp_stream_key == path.rtmp_stream_key
        assert restored.rtsp_path == path.rtsp_path


class TestMediaMTXConfig:
    """Tests for MediaMTXConfig."""

    def test_create_default_config(self):
        config = create_mediamtx_config()
        assert config.rtmp_address == ":1935"
        assert config.rtsp_address == ":8554"
        assert config.api_address == ":9997"
        assert "cam1" in config.paths
        assert "cam2" in config.paths

    def test_cam1_path_exists(self):
        config = create_mediamtx_config()
        cam1 = config.get_path("cam1")
        assert cam1 is not None
        assert cam1.name == "cam1"
        assert cam1.rtmp_stream_key == "cam1"
        assert cam1.rtsp_path == "cam1"

    def test_cam2_path_exists(self):
        config = create_mediamtx_config()
        cam2 = config.get_path("cam2")
        assert cam2 is not None
        assert cam2.name == "cam2"
        assert cam2.rtmp_stream_key == "cam2"
        assert cam2.rtsp_path == "cam2"

    def test_rtmp_routes_to_expected_path(self):
        config = create_mediamtx_config()
        cam1 = config.get_path("cam1")
        assert cam1.rtmp_stream_key == "cam1"
        cam2 = config.get_path("cam2")
        assert cam2.rtmp_stream_key == "cam2"

    def test_rtsp_routes_to_expected_path(self):
        config = create_mediamtx_config()
        cam1 = config.get_path("cam1")
        assert cam1.rtsp_path == "cam1"
        cam2 = config.get_path("cam2")
        assert cam2.rtsp_path == "cam2"

    def test_no_duplicate_paths(self):
        config = create_mediamtx_config()
        path_names = list(config.paths.keys())
        assert len(path_names) == len(set(path_names))

    def test_no_duplicate_rtmp_keys(self):
        config = create_mediamtx_config()
        stream_keys = [p.rtmp_stream_key for p in config.paths.values()]
        assert len(stream_keys) == len(set(stream_keys))

    def test_no_duplicate_rtsp_paths(self):
        config = create_mediamtx_config()
        rtsp_paths = [p.rtsp_path for p in config.paths.values()]
        assert len(rtsp_paths) == len(set(rtsp_paths))

    def test_custom_keys(self):
        config = create_mediamtx_config(
            cam1_rtmp_key="custom_cam1",
            cam1_rtsp_path="custom_cam1",
            cam2_rtmp_key="custom_cam2",
            cam2_rtsp_path="custom_cam2",
        )
        assert config.get_path("cam1").rtmp_stream_key == "custom_cam1"
        assert config.get_path("cam1").rtsp_path == "custom_cam1"
        assert config.get_path("cam2").rtmp_stream_key == "custom_cam2"
        assert config.get_path("cam2").rtsp_path == "custom_cam2"

    def test_to_yaml(self):
        config = create_mediamtx_config()
        yaml_str = config.to_yaml()
        assert "rtmpAddress: :1935" in yaml_str
        assert "rtspAddress: :8554" in yaml_str
        assert "cam1:" in yaml_str
        assert "cam2:" in yaml_str

    def test_serialization_roundtrip(self):
        config = create_mediamtx_config()
        data = config.to_dict()
        restored = MediaMTXConfig.from_dict(data)
        assert restored.rtmp_address == config.rtmp_address
        assert restored.rtsp_address == config.rtsp_address
        assert set(restored.paths.keys()) == set(config.paths.keys())

    def test_validate_valid_config(self):
        config = create_mediamtx_config()
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is True
        assert errors == []

    def test_validate_missing_cam1(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="cam2",
            rtsp_path="cam2",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("cam1" in e for e in errors)

    def test_validate_missing_cam2(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("cam2" in e for e in errors)

    def test_validate_extra_camera(self):
        config = create_mediamtx_config()
        config.add_path(MediaMTXPathConfig(
            name="cam3",
            rtmp_stream_key="cam3",
            rtsp_path="cam3",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("cam1 and cam2" in e for e in errors)

    def test_validate_missing_rtmp_key(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="",
            rtsp_path="cam1",
        ))
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="cam2",
            rtsp_path="cam2",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("rtmp_stream_key is required" in e for e in errors)

    def test_validate_missing_rtsp_path(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="",
        ))
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="cam2",
            rtsp_path="cam2",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("rtsp_path is required" in e for e in errors)

    def test_validate_unsupported_codec(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
            codec="h265",
        ))
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="cam2",
            rtsp_path="cam2",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("H.264" in e for e in errors)

    def test_validate_duplicate_rtmp_keys(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="same_key",
            rtsp_path="cam1",
        ))
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="same_key",
            rtsp_path="cam2",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("Duplicate RTMP stream keys" in e for e in errors)

    def test_validate_duplicate_rtsp_paths(self):
        config = MediaMTXConfig()
        config.add_path(MediaMTXPathConfig(
            name="cam1",
            rtmp_stream_key="cam1",
            rtsp_path="same_path",
        ))
        config.add_path(MediaMTXPathConfig(
            name="cam2",
            rtmp_stream_key="cam2",
            rtsp_path="same_path",
        ))
        is_valid, errors = validate_mediamtx_config(config)
        assert is_valid is False
        assert any("Duplicate RTSP paths" in e for e in errors)


class TestDefaultConfigYAML:
    """Tests for default MediaMTX YAML configuration."""

    def test_default_yaml_contains_required_fields(self):
        assert "rtmpAddress: \":1935\"" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "rtspAddress: \":8554\"" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "apiAddress: \":9997\"" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "cam1:" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "cam2:" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "source: \"publisher\"" in MEDIAMTX_DEFAULT_CONFIG_YAML
        assert "rtspTransport: \"tcp\"" in MEDIAMTX_DEFAULT_CONFIG_YAML