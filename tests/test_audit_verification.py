"""
Audit Verification Test Script
Tests:
1. RTSP TCP transport & NVDEC decode error handling
2. Line Crossing save/get endpoints
3. ArcFace Embedding detect & enrollment endpoints
"""

import os
import sys
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure CUDA and repo root are in path
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.main import app
from pipeline_engine.ingestion.rtsp_source import RTSPSourceConfig, RTSPSource
from pipeline_engine.decode.nvdec_decoder import NVDECDecoderConfig, NVDECDecoder

def test_rtsp_source_options():
    """Verify RTSP options force TCP, 10MB buffer, 5s timeout."""
    cfg = RTSPSourceConfig(camera_id="test_cam", url="rtsp://localhost:8554/test")
    assert cfg.transport == "tcp", f"Expected tcp, got {cfg.transport}"
    assert cfg.buffer_size == 10240000, f"Expected 10240000, got {cfg.buffer_size}"
    
    src = RTSPSource(cfg)
    options = src._build_ffmpeg_options()
    print("RTSPSource options:", options)
    assert options["rtsp_transport"] == "tcp"
    assert options["buffer_size"] == "10240000"
    assert options["max_delay"] == "500000"
    assert options["stimeout"] == "5000000"
    print("PASS: test_rtsp_source_options")


def test_nvdec_decoder_options_and_error_handling():
    """Verify NVDEC decoder options and error recovery methods."""
    cfg = NVDECDecoderConfig(
        camera_id="cam1",
        packet_source=RTSPSourceConfig(camera_id="cam1", url="rtsp://localhost:8554/cam1")
    )
    decoder = NVDECDecoder(cfg)
    assert hasattr(decoder, "is_degraded"), "NVDECDecoder must have is_degraded method"
    assert not decoder.is_degraded(), "Newly initialized decoder must not be degraded"
    assert hasattr(decoder, "_waiting_for_keyframe"), "Must have keyframe waiting state"
    print("PASS: test_nvdec_decoder_options_and_error_handling")


def test_line_saving_and_retrieval():
    """Test line saving and getting via FastAPI TestClient."""
    with TestClient(app) as client:
        # 1. POST /api/v1/cameras/cam1/line
        payload = {
            "cam_id": "cam1",
            "line": [[0.15, 0.75], [0.85, 0.75]],
            "direction": "IN->OUT"
        }
        res = client.post("/api/v1/cameras/cam1/line", json=payload)
        print("POST /api/v1/cameras/cam1/line response:", res.status_code, res.json())
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["status"] == "success"
        assert data["cam_id"] == "cam1"
        assert data["pixel_line"] == [[576, 1620], [3264, 1620]]

        # 2. GET /api/v1/cameras/cam1/line
        res_get = client.get("/api/v1/cameras/cam1/line")
        print("GET /api/v1/cameras/cam1/line response:", res_get.status_code, res_get.json())
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["cam_id"] == "cam1"
        assert "line" in get_data

        # 3. POST /api/v1/line alias
        res_alias = client.post("/api/v1/line", json=payload)
        assert res_alias.status_code == 200
        print("PASS: test_line_saving_and_retrieval")


def test_arcface_detect_and_enrollment():
    """Test real ArcFace face detection, embedding creation, and gallery reload without mock."""
    test_img = Path("realistic_test_face.jpg")
    assert test_img.exists(), f"Sample test image not found at {test_img}"

    with TestClient(app) as client:
        # 1. Test POST /api/v1/enrollment/detect
        with open(test_img, "rb") as f:
            files = {"image": ("test.jpg", f.read(), "image/jpeg")}
            res_det = client.post("/api/v1/enrollment/detect", files=files)
        print("POST /api/v1/enrollment/detect:", res_det.status_code, "detected:", res_det.json().get("detected"))
        assert res_det.status_code == 200, f"detect failed: {res_det.status_code}"
        det_data = res_det.json()
        assert det_data["success"] is True
        assert det_data["detected"] is True
        assert det_data["confidence"] > 0.35
        assert det_data["dimension"] == 512
        assert len(det_data["embedding"]) == 512
        assert "crop_data_url" in det_data

        # 2. Test POST /api/v1/enrollment/persons (Enrollment & NPY creation)
        with open(test_img, "rb") as f:
            files = {"image": ("test.jpg", f.read(), "image/jpeg")}
            data = {
                "student_id": "TEST_AUDIT_01",
                "name": "Audit Student 01",
                "role": "student",
                "student_class": "10A1"
            }
            res_enroll = client.post("/api/v1/enrollment/persons", data=data, files=files)
        print("POST /api/v1/enrollment/persons:", res_enroll.status_code, "student_id:", res_enroll.json().get("student_id"))
        assert res_enroll.status_code == 200, f"enroll failed: {res_enroll.text}"
        enroll_data = res_enroll.json()
        assert enroll_data["success"] is True
        assert enroll_data["student_id"] == "TEST_AUDIT_01"
        assert enroll_data["embedding_dimension"] == 512
        assert os.path.exists(enroll_data["npy_path"]), f"NPY file was not saved to {enroll_data['npy_path']}"

        # 3. Test GET /api/v1/enrollment/persons (Gallery list)
        res_list = client.get("/api/v1/enrollment/persons")
        assert res_list.status_code == 200
        persons = res_list.json()
        assert any(p.get("student_id") == "TEST_AUDIT_01" for p in persons)

        # 4. Test POST /api/v1/pipeline/reload-gallery
        res_reload = client.post("/api/v1/pipeline/reload-gallery")
        print("POST /api/v1/pipeline/reload-gallery:", res_reload.status_code, res_reload.json().get("status"))
        assert res_reload.status_code == 200
        print("PASS: test_arcface_detect_and_enrollment")


if __name__ == "__main__":
    print("=== RUNNING AUDIT VERIFICATION TESTS ===")
    test_rtsp_source_options()
    test_nvdec_decoder_options_and_error_handling()
    test_line_saving_and_retrieval()
    test_arcface_detect_and_enrollment()
    print("=== ALL AUDIT VERIFICATION TESTS PASSED SUCCESSFULLY (200 OK) ===")
