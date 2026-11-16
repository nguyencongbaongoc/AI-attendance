"""Empirical pytest reproducers for Phase 18 DB & Evidence Storage audit (#7).

All tests are strictly isolated using ``tmp_path``, ``:memory:``, and mocks.
Production databases (``app/data/*.db``, ``data/*.db``) are never opened or written.
Each passing test proves the corresponding audited defect exists in the codebase.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_attendance_record(
    record_id: str = "rec-001",
    res_id: str = "res-001",
    raw_id: str = "raw-001",
    event_ts: float = 1760800800.0,
    face_url: str | None = None,
    scene_url: str | None = None,
    clip_url: str | None = None,
):
    from app.attendance.contract import (
        AttendanceDirection,
        AttendanceRecord,
        IdentityCertainty,
    )

    return AttendanceRecord(
        attendance_record_id=record_id,
        identity_certainty=IdentityCertainty.KNOWN,
        identity_candidate="STU001",
        identity_confidence=0.95,
        snapshot_face_url=face_url,
        snapshot_scene_url=scene_url,
        video_clip_url=clip_url,
        direction=AttendanceDirection.IN,
        event_timestamp=event_ts,
        event_frame_index=10,
        camera_id="cam1",
        local_track_id="1",
        source_raw_event_id=raw_id,
        source_resolution_id=res_id,
        previous_state="outside",
        new_state="inside",
    )


# ---------------------------------------------------------------------------
# P0-01: Split-brain attendance persistence & unpersisted AI worker ingestion
# ---------------------------------------------------------------------------


def test_p0_01_ingest_attendance_event_accepts_without_persisting(tmp_path, monkeypatch):
    """POST /api/v1/attendance/events resolves event but never calls get_repository() or stores it."""
    monkeypatch.chdir(tmp_path)
    import app.api.ai_worker as ai_worker
    from app.attendance.repository import AttendanceRepository
    from app.attendance.storage import AttendanceStorage, StorageConfig

    storage = AttendanceStorage(StorageConfig(database_path=tmp_path / "att.db"))
    repo = AttendanceRepository(storage=storage)
    get_repo_spy = MagicMock(return_value=repo)
    monkeypatch.setattr(ai_worker, "get_repository", get_repo_spy)

    # Isolate the module-level resolver so test never leaks state across runs
    from app.in_out.resolver import create_repeated_in_out_resolver

    monkeypatch.setattr(ai_worker, "_resolver", create_repeated_in_out_resolver(), raising=False)

    mini_app = FastAPI()
    mini_app.include_router(ai_worker.router)
    mini_app.dependency_overrides[ai_worker.verify_ai_worker_key] = lambda: True

    client = TestClient(mini_app)
    payload = {
        "event_id": "evt-p001-1",
        "camera_id": "cam1",
        "track_id": 42,
        "direction": "in",
        "timestamp": 1760800800.0,
        "frame_index": 100,
        "stream_epoch": 1,
        "pts": 90000,
        "capture_timestamp": 1760800800.0,
        "processing_timestamp": 1760800800.05,
        "model_version": "v1",
        "enrollment_version": "e1",
    }

    resp = client.post("/api/v1/attendance/events", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    # Defect: event accepted by backend API, yet repository is never invoked and DB has 0 rows
    assert get_repo_spy.call_count == 0
    assert storage.count() == 0


def test_p0_01_pipeline_attendance_engine_targets_separate_relative_db():
    """PipelineEngine AttendanceConfig points to data/attendance_events.db instead of app/data/attendance.db."""
    from app.attendance.storage import _get_attendance_db_path
    from pipeline_engine.attendance.attendance_engine import AttendanceConfig

    pe_db = Path(AttendanceConfig().db_path)
    app_db = _get_attendance_db_path()
    assert pe_db.as_posix() == "data/attendance_events.db"
    assert pe_db.name != app_db.name


def test_p0_01_pipeline_backend_attendance_endpoints_return_empty_stubs(monkeypatch):
    """pipeline_engine.backend.app attendance endpoints return hardcoded empty stubs."""
    import pipeline_engine.backend.app as pe_backend

    monkeypatch.setattr(pe_backend, "engine", object())
    events = asyncio.run(pe_backend.get_attendance_events())
    daily = asyncio.run(pe_backend.get_daily_attendance("2026-10-18"))
    assert events == []
    assert daily == {"date": "2026-10-18", "records": []}


# ---------------------------------------------------------------------------
# P0-02: Retention & backup services never started in FastAPI lifespan
# ---------------------------------------------------------------------------


def test_p0_02_fastapi_lifespan_never_starts_storage_services():
    """app.main.lifespan contains no RetentionService, DatabaseMaintenance, or start_storage_services call."""
    import app.main as app_main

    src = inspect.getsource(app_main.lifespan)
    assert "RetentionService" not in src
    assert "DatabaseMaintenance" not in src
    assert "start_storage_services" not in src


def test_p0_02_bootstrap_start_storage_services_orphans_tasks_on_unrun_loop():
    """Bootstrap.start_storage_services schedules asyncio tasks on a loop without run_forever()."""
    src = (REPO_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "start_storage_services"
    ]
    assert len(fn_nodes) == 1
    fn_src = ast.get_source_segment(src, fn_nodes[0]) or ""
    assert "create_task" in fn_src or "ensure_future" in fn_src
    assert "run_forever" not in fn_src
    assert "run_until_complete" not in fn_src


# ---------------------------------------------------------------------------
# P0-03: MediaMTX recording disabled (`record: no`) & YAML split-brain
# ---------------------------------------------------------------------------


def test_p0_03_mediamtx_recording_disabled_and_yaml_split_brain():
    """Both mediamtx/mediamtx.yml and mediamtx.yml have record=False and diverging parameters."""
    primary = yaml.safe_load((REPO_ROOT / "mediamtx" / "mediamtx.yml").read_text(encoding="utf-8"))
    root_cfg = yaml.safe_load((REPO_ROOT / "mediamtx.yml").read_text(encoding="utf-8"))

    for cam in ("live/cam1", "live/cam2", "live/cam1_ai", "live/cam2_ai", "cam1_ai", "cam2_ai"):
        assert primary["paths"][cam]["record"] is False
        assert root_cfg["paths"][cam]["record"] is False

    # Config split-brain between mediamtx/mediamtx.yml (runtime) and root mediamtx.yml
    assert primary["writeQueueSize"] == 8192 and root_cfg["writeQueueSize"] == 512
    assert primary["hlsSegmentCount"] == 24 and root_cfg["hlsSegmentCount"] == 12
    assert primary["hlsSegmentDuration"] == "2s" and root_cfg["hlsSegmentDuration"] == "1s"


# ---------------------------------------------------------------------------
# P0-04: Evidence snapshot/clip helpers unreferenced + URI/path/CUDA bugs
# ---------------------------------------------------------------------------


def test_p0_04_evidence_helpers_have_zero_production_callers():
    """get_snapshot_saver and get_clip_extractor are defined in app/storage only and never called."""
    hits = []
    for root in (REPO_ROOT / "app", REPO_ROOT / "pipeline_engine"):
        for py_file in root.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel.startswith("app/storage/"):
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if "get_snapshot_saver" in text or "get_clip_extractor" in text:
                hits.append(rel)
    assert hits == []


def test_p0_04_snapshot_saver_relative_uri_broken_and_cuda_event_before_copy(tmp_path, monkeypatch):
    """_get_relative_uri breaks outside CWD/app/static, lacks /static/ prefix, and CUDA event precedes DtoH."""
    from app.storage.snapshot_saver import AsyncSnapshotSaver

    saver = AsyncSnapshotSaver(base_dir=str(tmp_path / "snapshots"))
    with pytest.raises(ValueError):
        saver._get_relative_uri(tmp_path / "snapshots" / "face.jpg")

    monkeypatch.chdir(tmp_path)
    p = Path("app/static/evidence/snapshots/2026-10-18/cam1/face.jpg")
    uri = saver._get_relative_uri(p)
    assert not uri.startswith("/static/")
    assert "\\" in uri  # Windows raw Path.relative_to string

    # Verify _cuda_tensor_to_cpu_async records CUDA event BEFORE tensor.to("cpu", non_blocking=True)
    call_order = []

    class FakeEvent:
        def __init__(self, *args, **kwargs):
            pass

        def record(self, stream):
            call_order.append(("event.record", stream))

        def synchronize(self):
            call_order.append(("event.synchronize", None))

    class FakeCpuTensor:
        def numpy(self):
            import numpy as np

            return np.zeros((4, 4, 3), dtype=np.uint8)

    class FakeGpuTensor:
        dtype = object()

        def to(self, *args, **kwargs):
            if args and args[0] == "cpu":
                call_order.append(("tensor.to_cpu", kwargs))
                return FakeCpuTensor()
            return self

        def contiguous(self):
            return self

        def byte(self):
            return self

    class FakeStreamCtx:
        def __enter__(self):
            call_order.append(("stream_enter", None))

        def __exit__(self, *exc):
            call_order.append(("stream_exit", None))

    saver._cuda_stream = "FAKE_STREAM"
    with (
        patch("torch.cuda.is_available", return_value=True),
        patch("torch.cuda.Event", FakeEvent),
        patch("torch.cuda.stream", lambda s: FakeStreamCtx()),
        patch("cv2.cvtColor", lambda arr, code: arr),
    ):
        saver._cuda_tensor_to_cpu_async(FakeGpuTensor())

    rec_idx = next(i for i, c in enumerate(call_order) if c[0] == "event.record")
    to_cpu_idx = next(i for i, c in enumerate(call_order) if c[0] == "tensor.to_cpu")
    assert rec_idx < to_cpu_idx


def test_p0_04_clip_extractor_wrong_camera_dir_and_relative_segment_times(tmp_path):
    """ClipExtractor ignores live/<cam> and treats ffprobe relative duration as Unix epoch range."""
    from app.storage.clip_extractor import ClipExtractor

    rec_root = tmp_path / "recordings"
    live_dir = rec_root / "live" / "cam1"
    live_dir.mkdir(parents=True)
    (live_dir / "2026-10-18_22-19-58-000000.mp4").write_bytes(b"fake")

    extractor = ClipExtractor(
        recordings_dir=str(rec_root),
        clips_dir=str(tmp_path / "app" / "static" / "evidence" / "clips"),
    )
    # Looks in recordings/cam1 instead of recordings/live/cam1
    assert extractor._get_camera_recording_dir("cam1") == rec_root / "cam1"
    assert not extractor._get_camera_recording_dir("cam1").exists()

    # Now place a fake mp4 in recordings/cam1 and simulate ffprobe returning duration=60.0
    cam1_dir = rec_root / "cam1"
    cam1_dir.mkdir(parents=True)
    seg = cam1_dir / "2026-10-18_22-19-58-000000.mp4"
    seg.write_bytes(b"fake")

    ffprobe_ok = SimpleNamespace(returncode=0, stdout="60.0\n", stderr="")
    with patch("subprocess.run", return_value=ffprobe_ok):
        result = asyncio.run(extractor.extract_clip(camera_id="cam1", event_timestamp=1760800800.0))

    assert result.success is False
    assert result.error == "Invalid time range within segment"


# ---------------------------------------------------------------------------
# P0-05: AttendanceStorage.insert_many 39 columns vs 42 bound arguments
# ---------------------------------------------------------------------------


def test_p0_05_insert_many_column_vs_binding_mismatch_raises(tmp_path):
    """AttendanceStorage.insert_many fails deterministically with sqlite3.ProgrammingError (39 vs 42)."""
    from app.attendance.storage import AttendanceStorage, StorageConfig

    storage = AttendanceStorage(StorageConfig(database_path=tmp_path / "att.db"))
    rec = _make_attendance_record(
        face_url="/static/evidence/snapshots/f.jpg",
        scene_url="/static/evidence/snapshots/s.jpg",
        clip_url="/static/evidence/clips/c.mp4",
    )

    with pytest.raises(sqlite3.ProgrammingError, match="39.*42"):
        storage.insert_many([rec])


def test_p0_05_init_db_calls_migration_before_create_table(tmp_path, monkeypatch):
    """_init_db invokes migrate_attendance_schema before executing CREATE TABLE IF NOT EXISTS."""
    import app.attendance.storage as st_mod

    call_seq = []
    orig_migrate = st_mod.migrate_attendance_schema

    def spy_migrate(db_path: str):
        call_seq.append("migrate")
        return orig_migrate(db_path)

    monkeypatch.setattr(st_mod, "migrate_attendance_schema", spy_migrate)

    class SpyConn:
        def __init__(self, real_conn):
            self._real = real_conn

        def execute(self, sql, *args, **kwargs):
            if "CREATE TABLE IF NOT EXISTS attendance_records" in sql:
                call_seq.append("create_table")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_connect = sqlite3.connect

    def spy_connect(path, *args, **kwargs):
        assert kwargs.get("check_same_thread") is False
        return SpyConn(real_connect(path, *args, **kwargs))

    monkeypatch.setattr(st_mod.sqlite3, "connect", spy_connect)
    st_mod.AttendanceStorage(st_mod.StorageConfig(database_path=tmp_path / "order.db"))

    assert call_seq.index("migrate") < call_seq.index("create_table")


# ---------------------------------------------------------------------------
# P1-01: RetentionService watches wrong paths & checks root drive disk space
# ---------------------------------------------------------------------------


def test_p1_01_retention_policies_ignore_live_and_mediamtx_recordings():
    """Default RetentionService policies watch recordings/cam1,cam2 instead of live/cam* or mediamtx/recordings."""
    from app.storage.retention_service import RetentionConfig, RetentionService

    watched = [p for pol in RetentionService.DEFAULT_POLICIES for p in pol.paths]
    assert "recordings/cam1" in watched
    assert "recordings/cam2" in watched
    assert not any("live/" in p for p in watched)
    assert not any("mediamtx/" in p for p in watched)
    assert RetentionConfig().recordings_dir == Path("recordings")


# ---------------------------------------------------------------------------
# P1-02: RetentionService._cleanup_database_uris wipes valid /static/... URLs
# ---------------------------------------------------------------------------


def test_p1_02_cleanup_database_uris_nulls_valid_evidence_urls(tmp_path, monkeypatch):
    """Path('app/static') / '/static/...' drops prefix on OS path join and NULLs existing files."""
    monkeypatch.chdir(tmp_path)
    from app.attendance.storage import AttendanceStorage, StorageConfig
    from app.storage.retention_service import RetentionConfig, RetentionService

    face_rel = "app/static/evidence/snapshots/2026-10-18/cam1/face.jpg"
    face_file = tmp_path / face_rel
    face_file.parent.mkdir(parents=True, exist_ok=True)
    face_file.write_bytes(b"valid-jpeg-bytes")

    db_path = tmp_path / "att.db"
    storage = AttendanceStorage(StorageConfig(database_path=db_path))
    rec = _make_attendance_record(face_url="/static/evidence/snapshots/2026-10-18/cam1/face.jpg")
    assert storage.insert(rec) is True

    svc = RetentionService(RetentionConfig(db_path=str(db_path), enable_cleanup_loop=False))
    stats = asyncio.run(svc._cleanup_database_uris())

    assert stats["records_updated"] == 1
    assert face_file.exists()  # Valid file WAS on disk the entire time!
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT snapshot_face_url FROM attendance_records WHERE attendance_record_id = ?", ("rec-001",)).fetchone()
    conn.close()
    assert row[0] is None


# ---------------------------------------------------------------------------
# P1-03: DatabaseMaintenance incremental_vacuum no-op + _create_backup nuance
# ---------------------------------------------------------------------------


def test_p1_03_incremental_vacuum_noop_on_standard_db_and_no_unboundlocal_nuance(tmp_path, monkeypatch):
    """PRAGMA incremental_vacuum fails to reclaim freelist pages when auto_vacuum=0; connect failure leaks source_conn (no UnboundLocalError)."""
    from app.storage.retention_service import DatabaseMaintenance, RetentionConfig

    db_path = tmp_path / "att.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [("A" * 1000,) for _ in range(100)])
    conn.execute("DELETE FROM t")
    conn.commit()
    auto_vac = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
    freelist_before = conn.execute("PRAGMA freelist_count").fetchone()[0]
    conn.close()

    assert auto_vac == 0
    assert freelist_before > 0

    maint = DatabaseMaintenance(
        RetentionConfig(db_path=str(db_path), backup_dir=str(tmp_path / "backups"))
    )
    asyncio.run(maint._run_vacuum())

    conn = sqlite3.connect(db_path)
    freelist_after = conn.execute("PRAGMA freelist_count").fetchone()[0]
    conn.close()
    assert freelist_after == freelist_before

    # Nuance check against Report #7 P1-03 claim ("risks UnboundLocalError in except"):
    # sqlite3.connect() calls occur BEFORE the inner try block (lines 582-583), so a failure
    # in the 2nd connect() is caught cleanly without UnboundLocalError, though source_conn leaks.
    real_connect = sqlite3.connect
    opened_conns = []
    calls = {"n": 0}

    def flaky_connect(target, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite3.OperationalError("simulated dest failure")
        c = real_connect(target, *args, **kwargs)
        opened_conns.append(c)
        return c

    import app.storage.retention_service as rs_mod

    monkeypatch.setattr(rs_mod.sqlite3, "connect", flaky_connect)
    # Should return None cleanly instead of raising UnboundLocalError
    res = asyncio.run(maint._create_backup())
    assert res is None
    assert len(opened_conns) == 1
    opened_conns[0].close()


# ---------------------------------------------------------------------------
# P1-04 & P1-05: Split-brain DB dirs, bare-filename crash, DELETE mode & FK OFF
# ---------------------------------------------------------------------------


def test_p1_04_split_brain_data_dirs_and_bare_filename_crash(tmp_path, monkeypatch):
    """ProjectPaths().data_dir diverges from load_settings().paths.data_dir, and bare db_path crashes os.makedirs('')."""
    from app.attendance.policy_engine.exit_session import ExitSessionStore
    from app.config.paths import ProjectPaths
    from app.config.settings import load_settings

    assert ProjectPaths().data_dir != load_settings().paths.data_dir

    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        ExitSessionStore(db_path="exit_sessions.db")


def test_p1_05_policy_and_notification_stores_force_delete_mode_and_fk_off(tmp_path):
    """All four policy/notification stores override WAL to DELETE and leave foreign_keys=0."""
    from app.attendance.policy_engine.exit_session import ExitSessionStore
    from app.attendance.policy_engine.parent_registry import ParentRegistry
    from app.attendance.policy_engine.telegram_bot import NotificationQueue, TelegramBot
    from app.notifications.dispatcher import CooldownTracker, PersistentNotificationQueue

    exit_db = tmp_path / "exit.db"
    parent_db = tmp_path / "parent.db"
    tg_queue_db = tmp_path / "tg_queue.db"
    cd_db = tmp_path / "cd.db"
    disp_q_db = tmp_path / "disp_q.db"

    ExitSessionStore(db_path=str(exit_db))
    reg = ParentRegistry(db_path=str(parent_db))
    NotificationQueue(parent_registry=reg, telegram_bot=TelegramBot(), db_path=str(tg_queue_db))
    CooldownTracker(db_path=str(cd_db))
    PersistentNotificationQueue(db_path=str(disp_q_db))

    for db_file in (exit_db, parent_db, tg_queue_db, cd_db, disp_q_db):
        conn = sqlite3.connect(db_file)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode.lower() == "delete", f"{db_file.name} expected delete, got {mode}"

    # Verify ParentRegistry allows orphan student_parent_links due to PRAGMA foreign_keys=0
    conn = sqlite3.connect(parent_db)
    fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk_status == 0
    conn.execute(
        "INSERT INTO student_parent_links (link_id, student_id, parent_id, relationship, is_primary, created_at) "
        "VALUES ('LNK-ORPHAN', 'STU-MISSING', 'PAR-MISSING', 'parent', 1, '2026-10-18T00:00:00Z')"
    )
    conn.commit()
    orphan_count = conn.execute("SELECT COUNT(*) FROM student_parent_links WHERE parent_id = 'PAR-MISSING'").fetchone()[0]
    conn.close()
    assert orphan_count == 1


# ---------------------------------------------------------------------------
# P1-06: app/db/session.py omits foreign_keys=ON & fails raw SQL check in SA 2.0
# ---------------------------------------------------------------------------


def test_p1_06_sqlalchemy_pragma_and_check_db_connection_raw_sql_error(tmp_path):
    """set_sqlite_pragma omits foreign_keys=ON and check_db_connection passes raw string to AsyncConnection.execute."""
    import app.db.session as db_session
    from sqlalchemy.exc import ArgumentError

    fake_cursor = MagicMock()
    executed_sql = []
    fake_cursor.execute.side_effect = lambda sql: executed_sql.append(sql)
    fake_raw_conn = MagicMock()
    fake_raw_conn.cursor.return_value = fake_cursor

    db_session.set_sqlite_pragma(fake_raw_conn, None)
    assert any("WAL" in s for s in executed_sql)
    assert not any("foreign_keys" in s.lower() for s in executed_sql)

    # Confirm raw string execution in check_db_connection fails under SQLAlchemy 2.0
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _probe():
        eng = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'sa.db').as_posix()}")
        try:
            async with eng.connect() as conn:
                await conn.execute("SELECT 1")
        finally:
            await eng.dispose()

    with pytest.raises(ArgumentError, match="Textual SQL expression"):
        asyncio.run(_probe())


# ---------------------------------------------------------------------------
# P1-07: ClipExtractor leaks concat temp file & writes unescaped Windows paths
# ---------------------------------------------------------------------------


def test_p1_07_clip_extractor_leaks_concat_file_and_writes_raw_paths(tmp_path):
    """Multi-segment extract_clip leaves *_concat.txt on disk without unlinking."""
    from app.storage.clip_extractor import ClipExtractor

    rec_dir = tmp_path / "recordings"
    clips_dir = tmp_path / "app" / "static" / "evidence" / "clips"
    cam_dir = rec_dir / "cam1"
    cam_dir.mkdir(parents=True)

    seg1 = cam_dir / "seg1.mp4"
    seg2 = cam_dir / "seg2.mp4"
    seg1.write_bytes(b"s1")
    seg2.write_bytes(b"s2")
    os.utime(seg1, (1000.0, 1000.0))
    os.utime(seg2, (1010.0, 1010.0))

    extractor = ClipExtractor(recordings_dir=str(rec_dir), clips_dir=str(clips_dir))

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"clipped-mp4")
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with (
        patch.object(extractor, "_find_covering_segments", AsyncMock(return_value=[(seg1, 0.0, 10.0), (seg2, 10.0, 20.0)])),
        patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess_exec),
    ):
        res = asyncio.run(extractor.extract_clip(camera_id="cam1", event_timestamp=10.0))

    assert res.success is True
    leaked_concats = list(clips_dir.rglob("*_concat.txt"))
    assert len(leaked_concats) == 1
    assert f"file '{seg1.absolute()}'" in leaked_concats[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# P1-08: UTC vs Asia/Ho_Chi_Minh date drift + microsecond filename mtime fallback
# ---------------------------------------------------------------------------


def test_p1_08_utc_date_bucketing_and_microsecond_filename_mtime_fallback(tmp_path):
    """UTC vs +07:00 drift in query.py/clip_extractor.py and st_mtime fallback in RecordingRegistry."""
    from app.attendance.query import get_daily_attendance_counts
    from app.attendance.repository import AttendanceRepository
    from app.attendance.storage import AttendanceStorage, StorageConfig
    from app.replay.recording import RecordingRegistry
    from app.storage.clip_extractor import ClipExtractor

    # 2026-10-18 20:00:00 UTC == 2026-10-19 03:00:00 in Asia/Ho_Chi_Minh (+07:00)
    ts_utc = datetime(2026, 10, 18, 20, 0, 0, tzinfo=timezone.utc).timestamp()

    storage = AttendanceStorage(StorageConfig(database_path=tmp_path / "att_tz.db"))
    repo = AttendanceRepository(storage=storage)
    assert storage.insert(_make_attendance_record(event_ts=ts_utc)) is True

    with patch("time.time", return_value=ts_utc + 60.0):
        daily = get_daily_attendance_counts(repo, days=2)
    assert "2026-10-18" in daily
    assert "2026-10-19" not in daily

    # RecordingRegistry fails to parse MediaMTX microsecond stem '%Y-%m-%d_%H-%M-%S-%f'
    rec_root = tmp_path / "rec"
    cam_dir = rec_root / "cam1"
    cam_dir.mkdir(parents=True)
    mp4 = cam_dir / "2026-10-18_22-19-58-123456.mp4"
    mp4.write_bytes(b"mp4data")
    fake_mtime = 1700000000.0
    os.utime(mp4, (fake_mtime, fake_mtime))

    reg = RecordingRegistry(recordings_dir=rec_root)
    infos = reg.list_recordings("cam1")
    assert len(infos) == 1
    assert infos[0].start_timestamp == pytest.approx(fake_mtime, abs=1.0)
    assert infos[0].duration_seconds == 5.0

    # ClipExtractor places historical event clip under datetime.now() date folder
    extractor = ClipExtractor(
        recordings_dir=str(rec_root),
        clips_dir=str(tmp_path / "app" / "static" / "evidence" / "clips"),
    )
    today_str = datetime.now().strftime("%Y-%m-%d")

    async def fake_subproc(*cmd, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"clip")
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_subproc):
        res = asyncio.run(
            extractor._extract_single_segment(mp4, 0.0, 5.0, "cam1", ts_utc)
        )
    assert res.success is True
    assert today_str in res.clip_path
    if today_str != "2026-10-19":
        assert "2026-10-19" not in res.clip_path
