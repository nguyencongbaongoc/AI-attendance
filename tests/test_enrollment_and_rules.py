"""
Phase 1 Offline Verification: Enrollment Hot-Reload, Cooldown Guard & LATE Rule.
"""

from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import openpyxl
import torch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.attendance import evaluate_entry_status, get_repository, router as attendance_router
from app.attendance.contract import AttendanceDirection, AttendanceRecord, IdentityCertainty
from app.attendance.repository import AttendanceRepository
from app.attendance.storage import AttendanceStorage, StorageConfig
from pipeline_engine.attendance.attendance_engine import (
    CameraAttendanceConfig,
    CrossingDirection,
    CrossingEngine,
    CrossingPolicyConfig,
    LineGeometry,
)
from pipeline_engine.inference.face_recognition import ArcFaceConfig, ArcFaceRecognizer
from pipeline_engine.tracking.tracker import Track, TrackLifecycleState


def test_enrollment_hot_reload_thread_safety():
    """Verify 512D ArcFace gallery hot-reload under concurrent identify() reads."""
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    recognizer = ArcFaceRecognizer("models/arcface/glintr100.onnx", ArcFaceConfig(), device_id=0)
    recognizer.device = device
    recognizer.mean = recognizer.mean.to(device)
    recognizer.std = recognizer.std.to(device)
    recognizer.embeddings_matrix = torch.empty((0, 512), device=device, dtype=torch.float32)

    rng = np.random.default_rng(42)
    base_emb = rng.standard_normal(512).astype(np.float32)
    base_emb /= np.linalg.norm(base_emb)

    new_emb = rng.standard_normal(512).astype(np.float32)
    new_emb /= np.linalg.norm(new_emb)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        tmp = Path(tmpdir)
        emb_dir = tmp / "embeddings"
        emb_dir.mkdir(parents=True, exist_ok=True)
        np.save(emb_dir / "HS_001.npy", base_emb)

        # Populate initial gallery via _enrollment_embeddings + _build_matrix_gallery
        with recognizer._lock:
            recognizer._enrollment_embeddings["HS_001"] = torch.from_numpy(base_emb).to(device).float()
            recognizer._enrollment_metadata["HS_001"] = {"name": "Student 1"}
            recognizer._build_matrix_gallery()

        errors = []
        stop_flag = threading.Event()

        def reader_loop():
            q = torch.from_numpy(base_emb).to(device).float()
            while not stop_flag.is_set():
                try:
                    res = recognizer.identify(q, top_k=3)
                    assert isinstance(res, list)
                except Exception as exc:
                    errors.append(repr(exc))

        threads = [threading.Thread(target=reader_loop, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()

        # Simulate concurrent hot-reload adding HS_002
        for step in range(20):
            with recognizer._lock:
                recognizer._enrollment_embeddings[f"HS_NEW_{step}"] = torch.from_numpy(new_emb).to(device).float()
                recognizer._enrollment_metadata[f"HS_NEW_{step}"] = {"name": f"New {step}"}
                recognizer._build_matrix_gallery()
            time.sleep(0.002)

        stop_flag.set()
        for t in threads:
            t.join(timeout=2.0)

        assert not errors, f"Concurrent identify() errors during hot-reload: {errors}"
        q_new = torch.from_numpy(new_emb).to(device).float()
        matches = recognizer.identify(q_new, top_k=1)
        assert matches and matches[0][0].startswith("HS_NEW_"), f"Expected hot-reloaded identity, got {matches}"
        assert matches[0][1] > 0.99


def test_crossing_cooldown_suppresses_sway_duplicates():
    """Verify CrossingEngine enforces cooldown_seconds against boundary swaying."""
    cfg = CameraAttendanceConfig(
        camera_id="cam1",
        line=LineGeometry(p1=(0.0, 1080.0), p2=(3840.0, 1080.0), direction_semantics="side_a_to_b_in"),
        crossing_policy=CrossingPolicyConfig(
            min_crossing_distance=50.0,
            temporal_debounce_seconds=1.0,
            cooldown_seconds=10.0,
            side_confirmation_frames=1,
        ),
    )
    engine = CrossingEngine(cfg)

    def make_track(tid: int, cy: float, ts: float, fidx: int, pid: str = "HS_COOLDOWN") -> Track:
        return Track(
            track_id=tid,
            source_frame_id="cam1",
            frame_index=fidx,
            timestamp=ts,
            bbox_original_frame=(1000.0, cy - 50.0, 1100.0, cy + 50.0),
            confidence=0.95,
            lifecycle_state=TrackLifecycleState.ACTIVE,
            age=fidx,
            hits=fidx,
            missed_frames=0,
            last_seen=ts,
            person_id=pid,
        )

    t0 = 1000.0
    # 1. Start on Side A (y=1200 > 1080), cross to Side B (y=900 < 1080) -> IN
    assert engine.process_track_update(make_track(1, 1200.0, t0, 1), t0, 1) == []
    ev1 = engine.process_track_update(make_track(1, 900.0, t0 + 0.5, 2), t0 + 0.5, 2)
    assert len(ev1) == 1 and ev1[0].direction == CrossingDirection.IN

    # 2. Sway back and forth within 10s cooldown (even with a new track_id=2 for same person_id)
    assert engine.process_track_update(make_track(2, 1200.0, t0 + 2.0, 3), t0 + 2.0, 3) == []
    ev_dup = engine.process_track_update(make_track(2, 900.0, t0 + 3.0, 4), t0 + 3.0, 4)
    assert ev_dup == [], f"Expected duplicate IN suppressed within cooldown, got {ev_dup}"
    assert engine.get_stats()["rejected_cooldown"] >= 1

    # 3. After cooldown_seconds (t0 + 12.0s), a valid IN is allowed
    assert engine.process_track_update(make_track(3, 1200.0, t0 + 11.5, 5), t0 + 11.5, 5) == []
    ev_after = engine.process_track_update(make_track(3, 900.0, t0 + 12.0, 6), t0 + 12.0, 6)
    assert len(ev_after) == 1 and ev_after[0].direction == CrossingDirection.IN


def test_late_rule_in_records_and_excel():
    """Verify LATE status tagging, /records?status=LATE, and Tong_Hop_Si_So sheet."""
    from fastapi import FastAPI
    import app.api.attendance as att_api

    today = datetime.now().strftime("%Y-%m-%d")
    ts_ontime = datetime.strptime(f"{today} 06:55:00", "%Y-%m-%d %H:%M:%S").timestamp()
    ts_late = datetime.strptime(f"{today} 07:15:00", "%Y-%m-%d %H:%M:%S").timestamp()

    assert evaluate_entry_status(ts_ontime, default_threshold="07:00:00", is_first_entry=True) == "PRESENT"
    assert evaluate_entry_status(ts_late, default_threshold="07:00:00", is_first_entry=True) == "LATE"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test_att.db"
        repo = AttendanceRepository(AttendanceStorage(StorageConfig(database_path=db_path)))

        repo.storage.insert(
            AttendanceRecord(
                attendance_record_id="rec_ontime",
                source_resolution_id="res_ontime",
                source_raw_event_id="raw_ontime",
                camera_id="cam1",
                local_track_id="1",
                global_observation_id="obs_1",
                direction=AttendanceDirection.IN,
                identity_certainty=IdentityCertainty.KNOWN,
                identity_candidate="HS_ONTIME",
                identity_confidence=0.95,
                event_timestamp=ts_ontime,
                previous_state="unknown",
                new_state="inside",
                created_at=datetime.now().isoformat(),
                persisted_at=datetime.now().isoformat(),
            )
        )
        repo.storage.insert(
            AttendanceRecord(
                attendance_record_id="rec_late",
                source_resolution_id="res_late",
                source_raw_event_id="raw_late",
                camera_id="cam1",
                local_track_id="2",
                global_observation_id="obs_2",
                direction=AttendanceDirection.IN,
                identity_certainty=IdentityCertainty.KNOWN,
                identity_candidate="HS_LATE",
                identity_confidence=0.93,
                event_timestamp=ts_late,
                previous_state="unknown",
                new_state=evaluate_entry_status(ts_late, default_threshold="07:00:00", is_first_entry=True),
                created_at=datetime.now().isoformat(),
                persisted_at=datetime.now().isoformat(),
            )
        )

        orig_repo = att_api._repository
        att_api._repository = repo
        try:
            test_app = FastAPI()
            test_app.include_router(attendance_router)
            client = TestClient(test_app)

            r_late = client.get(f"/api/v1/attendance/records?date={today}&status=LATE")
            assert r_late.status_code == 200
            data = r_late.json()
            assert len(data["records"]) == 1
            assert data["records"][0]["attendance_record_id"] == "rec_late"
            assert data["records"][0]["status"] == "LATE"
            assert data["records"][0]["attendance_state"] == "LATE"

            r_xlsx = client.get(f"/api/v1/attendance/export?format=xlsx&date={today}")
            assert r_xlsx.status_code == 200
            wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content))
            assert "Tong_Hop_Si_So" in wb.sheetnames
            ws2 = wb["Tong_Hop_Si_So"]
            headers = [c.value for c in ws2[1]]
            row2 = [c.value for c in ws2[2]]
            late_idx = headers.index("Đi trễ")
            present_idx = headers.index("Có mặt")
            assert row2[late_idx] == 1, f"Expected Đi trễ=1 in Tong_Hop_Si_So, got {row2}"
            assert row2[present_idx] == 1, f"Expected Có mặt=1 in Tong_Hop_Si_So, got {row2}"
        finally:
            att_api._repository = orig_repo


if __name__ == "__main__":
    test_enrollment_hot_reload_thread_safety()
    print("[PASS] Enrollment hot-reload thread safety")
    test_crossing_cooldown_suppresses_sway_duplicates()
    print("[PASS] CrossingEngine cooldown duplicate suppression")
    test_late_rule_in_records_and_excel()
    print("[PASS] LATE arrival rule in /records and Tong_Hop_Si_So")
