"""
Verification test for purging all synthetic/seeded timeline correlations.
Validates:
1. GET /api/v1/recordings/{recording_id}/events queries strictly by camera and real timestamp range [start_ts, end_ts].
2. For empty video clips in recordings/ (which have no matching crossings in attendance.db), events list is strictly empty: {"events": []}.
3. Zero dummy offsets or fake burst photos are returned.
4. Database has zero fake 2026-10-11 timestamps or fake Nguyễn Văn An correlations.
"""

import os
import sys
import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

def test_database_is_clean():
    """Verify attendance.db contains NO synthetic 2026-10-11 records or fake students."""
    db_path = Path("app/data/attendance.db")
    assert db_path.exists(), "attendance.db must exist"
    
    with sqlite3.connect(db_path) as conn:
        # Check no fake student HS2026_10A1_01
        fake_an = conn.execute("SELECT count(*) FROM attendance_records WHERE identity_candidate = 'HS2026_10A1_01'").fetchone()[0]
        assert fake_an == 0, f"Expected 0 records for fake student HS2026_10A1_01, found {fake_an}"
        
        # Check no fake rec_rev records
        rec_rev = conn.execute("SELECT count(*) FROM attendance_records WHERE attendance_record_id LIKE 'rec_rev%'").fetchone()[0]
        assert rec_rev == 0, f"Expected 0 rec_rev records, found {rec_rev}"
        
        # Check no 2026-10-11 fake timestamps (~17917...)
        fake_ts = conn.execute("SELECT count(*) FROM attendance_records WHERE event_timestamp >= 1791650000").fetchone()[0]
        assert fake_ts == 0, f"Expected 0 records with 2026-10-11 timestamp, found {fake_ts}"
    print("PASS: test_database_is_clean")


def test_recording_events_empty_for_test_clips():
    """Verify that recordings in recordings/ return strictly empty events."""
    with TestClient(app) as client:
        # 1. Get recordings list
        res = client.get("/api/v1/recordings")
        assert res.status_code == 200
        data = res.json()
        recordings = data.get("recordings", [])
        assert len(recordings) > 0, "Expected at least one recording in recordings/"

        # 2. Check each recording's events
        for rec in recordings[:10]:
            rec_id = rec["id"]
            ev_res = client.get(f"/api/v1/recordings/{rec_id}/events")
            assert ev_res.status_code == 200, f"Failed for {rec_id}: {ev_res.status_code}"
            ev_data = ev_res.json()
            assert "events" in ev_data
            assert isinstance(ev_data["events"], list)
            # Since no person crossing occurred in these test videos, events must be completely empty!
            assert len(ev_data["events"]) == 0, f"Expected 0 events for empty recording {rec_id}, got {len(ev_data['events'])}: {ev_data['events']}"
            assert ev_data["total"] == 0
    print("PASS: test_recording_events_empty_for_test_clips")


def test_recording_events_strict_timestamp_matching():
    """Verify that only records strictly within [start_ts, end_ts] are returned."""
    db_path = Path("app/data/attendance.db")
    test_record_id = "test_audit_strict_event_01"
    
    # Insert a temporary known record at a specific timestamp
    test_cam = "cam1"
    test_ts = 1791714549.5  # inside 2026-10-11_17-29-08 (1791714548..1791714552)
    
    with sqlite3.connect(db_path) as conn:
        # Clean up any leftover
        conn.execute("DELETE FROM attendance_records WHERE attendance_record_id = ?", (test_record_id,))
        conn.execute("""
            INSERT INTO attendance_records (
                attendance_record_id, identity_certainty, identity_candidate, identity_confidence,
                direction, event_timestamp, camera_id, local_track_id, source_raw_event_id,
                source_resolution_id, previous_state, new_state, created_at, persisted_at
            ) VALUES (?, 'known', 'TEST001', 0.95, 'in', ?, ?, 'track_01', 'raw_01', 'res_01', 'unknown', 'inside', '2026-10-11', '2026-10-11')
        """, (test_record_id, test_ts, test_cam))
        conn.commit()

    try:
        with TestClient(app) as client:
            # Query for the clip that overlaps with test_ts
            # 2026-10-11_17-29-08 has start_ts ~ 1791714548
            res = client.get("/api/v1/recordings/2026-10-11_17-29-08-550155/events")
            assert res.status_code == 200
            data = res.json()
            assert data["total"] == 1
            assert len(data["events"]) == 1
            ev = data["events"][0]
            assert ev["id"] == test_record_id
            assert ev["student_id"] == "TEST001"
            assert ev["timestamp"] == test_ts
            assert abs(ev["offset_seconds"] - (test_ts - data["video_start_timestamp"])) < 0.1
            assert ev["evidence_snapshot_path"] is None  # No fake burst photo!

            # Query for a DIFFERENT clip that does NOT overlap with test_ts
            res_other = client.get("/api/v1/recordings/2026-10-11_12-02-20-895445/events")
            assert res_other.status_code == 200
            data_other = res_other.json()
            assert data_other["total"] == 0
            assert len(data_other["events"]) == 0
    finally:
        # Clean up temporary test record
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM attendance_records WHERE attendance_record_id = ?", (test_record_id,))
            conn.commit()

    print("PASS: test_recording_events_strict_timestamp_matching")


def test_frontend_has_no_synthetic_offsets_or_fallbacks():
    """Verify frontend/index.html has zero artificial offset math or fallback queries for recording occurrences."""
    frontend_path = Path("frontend/index.html")
    content = frontend_path.read_text(encoding="utf-8")

    # Ensure no dummy offset formula
    assert "idx * 2.5 + 1.0" not in content, "Found idx * 2.5 + 1.0 in frontend/index.html"
    assert "i * 2.5 + 1.0" not in content, "Found i * 2.5 + 1.0 in frontend/index.html"

    # Ensure empty message is rendered
    assert "Không có sự kiện điểm danh nào được ghi nhận trong video này" in content

    # Ensure loadOccurrencesForRecording does not fallback to /api/v1/attendance/records
    assert "api.get(`/api/v1/attendance/records?" not in content, "Found fallback query in frontend"
    print("PASS: test_frontend_has_no_synthetic_offsets_or_fallbacks")


if __name__ == "__main__":
    test_database_is_clean()
    test_recording_events_empty_for_test_clips()
    test_recording_events_strict_timestamp_matching()
    test_frontend_has_no_synthetic_offsets_or_fallbacks()
    print("=== ALL VERIFICATION TESTS PASSED ===")
