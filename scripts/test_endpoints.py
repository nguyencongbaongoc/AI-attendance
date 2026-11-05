import sys
import os
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def run_tests():
    print("Testing API endpoints...")
    
    # 1. Test Line Update on cam1
    payload = {
        "cam_id": "cam1",
        "line": [[0.15, 0.75], [0.85, 0.75]],
        "direction": "IN->OUT"
    }
    r = client.post("/api/v1/cameras/cam1/line", json=payload)
    print(f"POST /api/v1/cameras/cam1/line: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["cam_id"] == "cam1"
    assert "line" in data
    assert data["line"][0] == [576, 1620]  # 0.15 * 3840 = 576, 0.75 * 2160 = 1620
    
    # 2. Test Line Get on cam1
    r = client.get("/api/v1/cameras/cam1/line")
    print(f"GET /api/v1/cameras/cam1/line: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200
    
    # 3. Test Line Update alias (/api/v1/line)
    r = client.post("/api/v1/line", json=payload)
    print(f"POST /api/v1/line: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200
    
    # 4. Test Recordings list
    r = client.get("/api/v1/recordings")
    print(f"GET /api/v1/recordings: status={r.status_code}, total={r.json().get('total')}")
    assert r.status_code == 200
    
    # 5. Test Pipeline Reload Gallery
    r = client.post("/api/v1/pipeline/reload-gallery")
    print(f"POST /api/v1/pipeline/reload-gallery: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200
    
    # 6. Test Pipeline Status
    r = client.get("/api/v1/pipeline/status")
    print(f"GET /api/v1/pipeline/status: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200
    
    # 7. Test Pipeline Camera Restart
    r = client.post("/api/v1/pipeline/camera/cam1/restart")
    print(f"POST /api/v1/pipeline/camera/cam1/restart: status={r.status_code}, data={r.json()}")
    assert r.status_code == 200

    print("ALL API ENDPOINT TESTS PASSED!")

if __name__ == "__main__":
    run_tests()
