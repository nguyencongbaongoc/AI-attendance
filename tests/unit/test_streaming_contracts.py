"""
Phase 32 — Unit Tests for Streaming Contracts.

Tests cover:
- Valid camera configuration
- Invalid camera ID
- Invalid RTMP path
- Invalid RTSP path
- Unsupported codec
- Serialization round-trip
- Deterministic IDs
"""

import pytest

from app.streaming.contracts import (
    CameraStreamContract,
    RTMPPath,
    RTSPPath,
    StreamCodec,
    StreamHealthState,
    StreamMetadata,
    create_camera_stream_contract,
    validate_camera_stream_contract,
)


class TestRTMPPath:
    """Tests for RTMPPath."""

    def test_default_values(self):
        path = RTMPPath()
        assert path.app == "live"
        assert path.stream_key == ""

    def test_custom_values(self):
        path = RTMPPath(app="custom", stream_key="test_key")
        assert path.app == "custom"
        assert path.stream_key == "test_key"

    def test_to_url(self):
        path = RTMPPath(stream_key="cam1")
        url = path.to_url("localhost", 1935)
        assert url == "rtmp://localhost:1935/live/cam1"

    def test_serialization_roundtrip(self):
        path = RTMPPath(app="live", stream_key="cam1")
        data = path.to_dict()
        restored = RTMPPath.from_dict(data)
        assert restored.app == path.app
        assert restored.stream_key == path.stream_key


class TestRTSPPath:
    """Tests for RTSPPath."""

    def test_default_values(self):
        path = RTSPPath()
        assert path.path == ""

    def test_custom_values(self):
        path = RTSPPath(path="cam1")
        assert path.path == "cam1"

    def test_to_url(self):
        path = RTSPPath(path="cam1")
        url = path.to_url("localhost", 8554)
        assert url == "rtsp://localhost:8554/cam1"

    def test_serialization_roundtrip(self):
        path = RTSPPath(path="cam1")
        data = path.to_dict()
        restored = RTSPPath.from_dict(data)
        assert restored.path == path.path


class TestStreamMetadata:
    """Tests for StreamMetadata."""

    def test_default_values(self):
        meta = StreamMetadata(camera_id="CAM1")
        assert meta.camera_id == "CAM1"
        assert meta.codec == StreamCodec.H264
        assert meta.width == 3840
        assert meta.height == 2160
        assert meta.fps == 30.0

    def test_is_4k_h264_30fps(self):
        meta = StreamMetadata(camera_id="CAM1")
        assert meta.is_4k_h264_30fps() is True

    def test_is_4k_h264_30fps_false_codec(self):
        meta = StreamMetadata(camera_id="CAM1", codec=StreamCodec.H265)
        assert meta.is_4k_h264_30fps() is False

    def test_is_4k_h264_30fps_false_resolution(self):
        meta = StreamMetadata(camera_id="CAM1", width=1920, height=1080)
        assert meta.is_4k_h264_30fps() is False

    def test_is_4k_h264_30fps_false_fps(self):
        meta = StreamMetadata(camera_id="CAM1", fps=25.0)
        assert meta.is_4k_h264_30fps() is False

    def test_serialization_roundtrip(self):
        meta = StreamMetadata(camera_id="CAM1", bitrate_kbps=5000)
        data = meta.to_dict()
        restored = StreamMetadata.from_dict(data)
        assert restored.camera_id == meta.camera_id
        assert restored.codec == meta.codec
        assert restored.width == meta.width
        assert restored.height == meta.height
        assert restored.fps == meta.fps
        assert restored.bitrate_kbps == meta.bitrate_kbps

class TestCameraStreamContract:
    """Tests for CameraStreamContract."""

    def test_valid_contract(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract.camera_id == "CAM1"
        assert contract.rtmp_path.stream_key == "cam1"
        assert contract.rtsp_path.path == "cam1"
        assert contract.expected_codec == StreamCodec.H264
        assert contract.expected_resolution == (3840, 2160)
        assert contract.expected_fps == 30.0
        assert contract.enabled is True
        assert contract.reconnect_enabled is True

    def test_get_rtmp_url(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        url = contract.get_rtmp_url("localhost", 1935)
        assert url == "rtmp://localhost:1935/live/cam1"

    def test_get_rtsp_url(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        url = contract.get_rtsp_url("localhost", 8554)
        assert url == "rtsp://localhost:8554/cam1"

    def test_validate_codec(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract.validate_codec(StreamCodec.H264) is True
        assert contract.validate_codec(StreamCodec.H265) is False

    def test_validate_resolution(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract.validate_resolution(3840, 2160) is True
        assert contract.validate_resolution(1920, 1080) is False

    def test_validate_fps(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract.validate_fps(30.0) is True
        assert contract.validate_fps(30.5) is True
        assert contract.validate_fps(25.0) is False

    def test_serialization_roundtrip(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        data = contract.to_dict()
        restored = CameraStreamContract.from_dict(data)
        assert restored.camera_id == contract.camera_id
        assert restored.rtmp_path.stream_key == contract.rtmp_path.stream_key
        assert restored.rtsp_path.path == contract.rtsp_path.path
        assert restored.expected_codec == contract.expected_codec
        assert restored.expected_resolution == contract.expected_resolution
        assert restored.expected_fps == contract.expected_fps

    def test_deterministic_ids(self):
        contract1 = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        contract2 = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        assert contract1.to_dict() == contract2.to_dict()


class TestValidateCameraStreamContract:
    """Tests for validate_camera_stream_contract."""

    def test_valid_contract(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is True
        assert errors == []

    def test_invalid_camera_id(self):
        contract = create_camera_stream_contract(
            camera_id="",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert "camera_id is required" in errors

    def test_invalid_rtmp_stream_key(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="",
            rtsp_path="cam1",
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert "rtmp stream_key is required" in errors

    def test_invalid_rtsp_path(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="",
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert "rtsp path is required" in errors

    def test_unsupported_codec(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
            expected_codec=StreamCodec.H265,
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert any("H.264" in e for e in errors)

    def test_unsupported_resolution(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
            expected_resolution=(1920, 1080),
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert any("3840x2160" in e for e in errors)

    def test_unsupported_fps(self):
        contract = create_camera_stream_contract(
            camera_id="CAM1",
            rtmp_stream_key="cam1",
            rtsp_path="cam1",
            expected_fps=25.0,
        )
        is_valid, errors = validate_camera_stream_contract(contract)
        assert is_valid is False
        assert any("30 FPS" in e for e in errors)


class TestStreamHealthState:
    """Tests for StreamHealthState enum."""

    def test_all_states_exist(self):
        states = [
            StreamHealthState.OFFLINE,
            StreamHealthState.CONNECTING,
            StreamHealthState.LIVE,
            StreamHealthState.DEGRADED,
            StreamHealthState.RECONNECTING,
            StreamHealthState.ERROR,
        ]
        assert len(states) == 6

    def test_state_values(self):
        assert StreamHealthState.OFFLINE.value == "offline"
        assert StreamHealthState.LIVE.value == "live"
        assert StreamHealthState.ERROR.value == "error"


class TestStreamCodec:
    """Tests for StreamCodec enum."""

    def test_h264_supported(self):
        assert StreamCodec.H264.value == "h264"

    def test_other_codecs_exist(self):
        assert StreamCodec.H265.value == "h265"
        assert StreamCodec.VP8.value == "vp8"
        assert StreamCodec.VP9.value == "vp9"
        assert StreamCodec.UNKNOWN.value == "unknown"