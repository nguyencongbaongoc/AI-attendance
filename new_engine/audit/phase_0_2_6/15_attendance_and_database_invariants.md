# Phase 0.2.6 Attendance and Database Invariants

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate D  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Database Authority Verification

| Database | Path | Purpose | Writer | Status |
|---|---|---|---|---|
| Authoritative Attendance | `app/data/attendance.db` | AttendanceRecord only | Legacy Backend (Phase 22-25) | VERIFIED |
| Secondary (Benchmark) | `data/attendance.db` | Benchmark only | None (preserved) | PRESERVED |
| PipelineEngine Events | `data/attendance_events.db` | CrossingEvent only | PipelineEngine | SEPARATE |

---

## 2. Invariant Checks

| Invariant | Verification |
|---|---|
| Single authoritative attendance DB | `app/attendance/storage.py` uses fixed path `_get_attendance_db_path()` |
| No PipelineEngine writes to AttendanceRecord | PipelineEngine has no AttendanceRecord import, no attendance DB writes |
| Phase 22-25 sole resolver | `app/api/ai_worker.py` ingests events -> RawInOutEvent -> RepeatedInOutResolver |
| Camera tracking isolated | Per-camera `CrossingEngine` in resolver |
| Timestamps synchronizable | `stream_epoch`, `pts`, `time_base` in event schema |
| Health doesn't claim READY without evidence | Backend validates state enum, sequence |
| Control doesn't permit arbitrary execution | Fixed action allowlist, no shell/eval |
| Enrollment reload preserves on failure | `preserved_previous=true` on all failures |
| No unsafe process termination | No `taskkill`, `del *.db-wal` in codebase |
| No manual WAL/SHM deletion | Not present in codebase |
| Quarantine unchanged | Phase 0.2.4 manifest verified |

---

## 3. Health/Control Data Isolation

| Data Type | Storage | Isolation |
|---|---|---|
| Health state | `_worker_health_states` dict | Per worker_id |
| Control requests | `_pending_control_requests` dict | Per worker_id (target_id) |
| Idempotency (backend) | `_processed_idempotency_keys` | Global |
| Idempotency (client) | `_processed_keys` set | Per client instance |
| Attendance | `app/data/attendance.db` | Legacy Backend only |

---

## 4. Health/Control Do Not Contaminate Attendance

- Health state: In-memory only, separate from attendance DB
- Control state: In-memory only, separate from attendance DB
- Event ingestion: Goes through resolver pipeline, not direct DB write
- No AttendanceRecord imports in health/control modules

---

## 5. Test Evidence

| Invariant | Test | Status |
|---|---|---|
| Authoritative DB path | `app/attendance/storage.py` inspection | SOURCE-VERIFIED |
| PipelineEngine no AttendanceRecord | `pipeline_engine/` grep | SOURCE-VERIFIED |
| Phase 22-25 sole resolver | `app/api/ai_worker.py` event ingestion | SOURCE-VERIFIED |
| Enrollment failure preserves | `enrollment_regression_test.py` | RUNTIME-VERIFIED |
| No unsafe procedures | Code grep | SOURCE-VERIFIED |
| Quarantine unchanged | Phase 0.2.4 manifest | SOURCE-VERIFIED |

All 25 enrollment regression tests PASS.
All attendance pipeline tests (148) PASS.
All integration tests (37) PASS.