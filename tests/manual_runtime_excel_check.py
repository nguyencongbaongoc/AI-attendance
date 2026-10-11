"""
Phase 44.X.4-R3.4-FIX — Runtime verification.

Spins up an in-process FastAPI app with the Excel endpoints, drives the chain:
  POST /api/v1/excel/export/daily
  GET  /api/v1/excel/exports
  GET  /api/v1/excel/export/{id}/download
  DELETE /api/v1/excel/export/{id}
and verifies each step produces a real XLSX file on disk and the metadata is real.

Run with: python tests/manual_runtime_excel_check.py
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import excel as excel_module
from app.api.excel import router as excel_router
from app.api.health import router as health_router
from app.api.attendance import router as attendance_router

excel_module._exporter = None

with tempfile.TemporaryDirectory() as tmpdir:
    exports_dir = Path(tmpdir) / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    def patched_exports_dir():
        return exports_dir

    with patch.object(excel_module, "get_exports_dir", side_effect=patched_exports_dir), \
         patch.object(excel_module, "get_timetable", return_value=None):
        app = FastAPI()
        for r in [health_router, attendance_router, excel_router]:
            for route in r.routes:
                app.router.routes.append(route)
        client = TestClient(app)

        target_date = "2026-09-02"

        print("STEP 1: POST /api/v1/excel/export/daily")
        r = client.post(
            "/api/v1/excel/export/daily",
            json={
                "date": target_date,
                "timezone": "Asia/Bangkok",
                "export_version": "1.0",
                "include_events_sheet": True,
                "include_provenance_sheet": True,
                "include_summary_sheet": True,
            },
        )
        print(f"  status={r.status_code}")
        assert r.status_code == 200, r.text
        body = r.json()
        print(f"  export_id={body['export_id']}")
        print(f"  file_path={body['file_path']}")
        print(f"  record_count={body['record_count']}")
        print(f"  sheets_created={body['sheets_created']}")
        assert os.path.isabs(body['file_path'])
        assert Path(body['file_path']).exists()
        assert "DAILY_ATTENDANCE" in body['sheets_created']

        # Real XLSX check
        with open(body['file_path'], 'rb') as f:
            assert f.read(2) == b'PK'

        print("STEP 2: GET /api/v1/excel/exports")
        r = client.get("/api/v1/excel/exports")
        print(f"  status={r.status_code}")
        listing = r.json()
        assert r.status_code == 200
        print(f"  count={len(listing['exports'])}")
        assert len(listing['exports']) == 1
        entry = listing['exports'][0]
        print(f"  export_id={entry['export_id']}")
        print(f"  file_path={entry['file_path']}")
        print(f"  record_count={entry['record_count']}  (read from real XLSX)")
        print(f"  sheets_created={entry['sheets_created']}")
        assert entry['export_id'] == f"daily_{target_date.replace('-', '')}"

        print("STEP 3: GET /api/v1/excel/export/{id}/download")
        r = client.get(f"/api/v1/excel/export/{entry['export_id']}/download")
        print(f"  status={r.status_code}")
        print(f"  content-length={len(r.content)}")
        assert r.status_code == 200
        assert r.content[:2] == b'PK'
        # Verify the downloaded bytes match the on-disk file
        with open(entry['file_path'], 'rb') as f:
            assert r.content == f.read()

        print("STEP 4: DELETE /api/v1/excel/export/{id}")
        r = client.delete(f"/api/v1/excel/export/{entry['export_id']}")
        print(f"  status={r.status_code}")
        print(f"  body={r.json()}")
        assert r.status_code == 200
        assert not Path(entry['file_path']).exists()

        print("STEP 5: GET /api/v1/excel/exports (after delete)")
        r = client.get("/api/v1/excel/exports")
        assert r.status_code == 200
        listing = r.json()
        print(f"  count={len(listing['exports'])}")
        assert listing == {"exports": []}

        print("STEP 6: DELETE again -> 404")
        r = client.delete(f"/api/v1/excel/export/{entry['export_id']}")
        print(f"  status={r.status_code}")
        assert r.status_code == 404

        print("\nALL STEPS PASS — runtime end-to-end Excel chain is real-data-driven.")