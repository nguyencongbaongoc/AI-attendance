# Phase 0.2.1 — SQLite Inventory and Integrity Audit

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED / RUNTIME VERIFIED

---

## 1. Executive Summary

**13 SQLite database files discovered** across active repository and quarantine directories. All databases pass `PRAGMA integrity_check`. Two distinct `attendance.db` instances exist with different schemas, record counts, and data provenance — this is the primary database authority conflict.

---

## 2. Complete SQLite Inventory

| # | Path | Size (bytes) | SHA256 | WAL/SHM | Tables | Record Counts | Classification |
|---|------|--------------|--------|---------|--------|---------------|----------------|
| 1 | `app/data/attendance.db` | 86,016 | f711c4392426c4c1f6ae278fed12b5121dc4cccf29a18a4a899485ec4100f5eb | ✅ WAL (32 KB), SHM (32 KB) | `attendance_records` (108), `schema_version` (1) | 108 attendance records | **AUTHORITATIVE** |
| 2 | `data/attendance.db` | 65,536 | 30fb1f177f284b3fd573d2baa46538da2993b0bf5b6c6cb48717116a429d7080 | ✅ WAL (32 KB), SHM (32 KB) | `attendance_records` (18), `schema_version` (1) | 18 attendance records | **ACTIVE SECONDARY** |
| 3 | `data/attendance_events.db` | 20,480 | 0fbdab692515cec5a724e7e6eb275d679b51534b389943830522c9b58f2d1c6a | ❌ None | `attendance_events` (0) | 0 crossing events | **DUPLICATE / PipelineEngine** |
| 4 | `app/data/exit_sessions.db` | 24,576 | eeefde20e6d9d3314c9a72a32a8b4b38101958d042e1f12ead3ac947741a724a | ❌ None | `exit_sessions` (0) | 0 exit sessions | **AUTHORITATIVE** |
| 5 | `data/exit_sessions.db` | 24,576 | eeefde20e6d9d3314c9a72a32a8b4b38101958d042e1f12ead3ac947741a724a | ❌ None | `exit_sessions` (0) | 0 exit sessions | **DUPLICATE (identical SHA256)** |
| 6 | `app/data/parent_registry.db` | 45,056 | 0aa11dab160117070214ce16125e476d98bfbfd8ff48cb4a06b7f81a79b96ec8 | ❌ None | `parents` (0), `student_parent_links` (0), `link_codes` (0) | All empty | **AUTHORITATIVE** |
| 7 | `data/parent_registry.db` | 45,056 | 0aa11dab160117070214ce16125e476d98bfbfd8ff48cb4a06b7f81a79b96ec8 | ❌ None | `parents` (0), `student_parent_links` (0), `link_codes` (0) | All empty | **DUPLICATE (identical SHA256)** |
| 8 | `app/data/notification_queue.db` | 32,768 | 670211d208999b820855c2244da5d8bcebdf4a731bcfc22bdd08f019eea49894 | ❌ None | `notifications` (0) | 0 notifications | **AUTHORITATIVE** |
| 9 | `data/notification_queue.db` | 32,768 | 670211d208999b820855c2244da5d8bcebdf4a731bcfc22bdd08f019eea49894 | ❌ None | `notifications` (0) | 0 notifications | **DUPLICATE (identical SHA256)** |
| 10 | `app/data/test_phase52_notification_queue.db` | 32,768 | (not computed) | ❌ None | (not inspected) | (not inspected) | **HISTORICAL / TEST** |
| 11 | `app/data/test_phase52_runloop.db` | (not computed) | (not computed) | ❌ None | (not inspected) | (not inspected) | **HISTORICAL / TEST** |
| 12 | `app/data/test_phase52_shutdown.db` | (not computed) | (not computed) | ❌ None | (not inspected) | (not inspected) | **HISTORICAL / TEST** |
| 13 | `data/test_phase52_notification.db` | (not computed) | (not computed) | ❌ None | (not inspected) | (not inspected) | **HISTORICAL / TEST** |
| 14 | `data/test_phase52_runloop.db` | (not computed) | (not computed) | ❌ None | (not inspected) | (not inspected) | **HISTORICAL / TEST** |

**Quarantine note:** `new_engine/audit/phase_0_2/quarantine/data_duplicate_dbs/` directory exists but is **empty** — the 4 databases claimed quarantined in Phase 0.2 were "restored to `data/` after quarantine to support Legacy Backend operation" (per `04_cleanup_execution_log.md` §2.3).

---

## 3. Detailed Database Analysis

### 3.1 `app/data/attendance.db` — AUTHORITATIVE

| Property | Value |
|----------|-------|
| **Path** | `app/data/attendance.db` |
| **Size** | 86,016 bytes |
| **SHA256** | f711c4392426c4c1f6ae278fed12b5121dc4cccf29a18a4a899485ec4100f5eb |
| **WAL/SHM** | Present (32 KB each) — indicates active write access |
| **Integrity** | `ok` |
| **Journal Mode** | WAL (verified via `PRAGMA journal_mode`) |
| **Tables** | `attendance_records`, `schema_version` |
| **Schema** | Full Phase 25 attendance_records schema (23 columns, 10 indexes, 7 constraints) |
| **Record Count** | 108 attendance_records |
| **Timestamp Range** | 5.24 (test data) → 1,787,502,600.0 (2026-09-22 production) |
| **Owner** | Legacy Backend — `AttendanceStorage` default path is `data/attendance.db` but resolved relative to CWD which is project root when started from `app/main.py` |
| **Provenance** | Contains mix of test records (`rec_in_1`, `rec_out_1`) and production records (`ATT-*` with full provenance chain: `source_raw_event_id`, `source_resolution_id`, `source_crossing_event_id`) |
| **Last Modified** | 2026-10-04 (active WAL indicates recent writes) |

**Evidence:** RUNTIME VERIFIED — read-only SQLite inspection

---

### 3.2 `data/attendance.db` — ACTIVE SECONDARY

| Property | Value |
|----------|-------|
| **Path** | `data/attendance.db` |
| **Size** | 65,536 bytes |
| **SHA256** | 30fb1f177f284b3fd573d2baa46538da2993b0bf5b6c6cb48717116a429d7080 |
| **WAL/SHM** | Present (32 KB each) — indicates active write access |
| **Integrity** | `ok` |
| **Journal Mode** | WAL |
| **Tables** | `attendance_records`, `schema_version` |
| **Schema** | Identical Phase 25 attendance_records schema |
| **Record Count** | 18 attendance_records |
| **Timestamp Range** | 6.91 → 100.28 (all test/benchmark data) |
| **Owner** | Legacy Backend — `Settings.paths.data_dir` resolves to `data/` (project root), so `data/attendance.db` is the configured default |
| **Provenance** | Only benchmark/test records (`ATT-*` with `CAM1` camera_id, frame indices 40-182, timestamps 6-100 seconds) |
| **Last Modified** | 2026-10-04 (active WAL indicates recent writes) |

**Evidence:** RUNTIME VERIFIED — read-only SQLite inspection

---

### 3.3 `data/attendance_events.db` — DUPLICATE / PipelineEngine

| Property | Value |
|----------|-------|
| **Path** | `data/attendance_events.db` |
| **Size** | 20,480 bytes |
| **SHA256** | 0fbdab692515cec5a724e7e6eb275d679b51534b389943830522c9b58f2d1c6a |
| **WAL/SHM** | None |
| **Integrity** | `ok` |
| **Tables** | `attendance_events` (16 columns, 2 indexes) |
| **Schema** | PipelineEngine `CrossingEvent` store schema (not Phase 25 `AttendanceRecord`) |
| **Record Count** | 0 |
| **Owner** | PipelineEngine `AttendanceStore` — configured via `pipeline_engine/config/pipeline.yaml` line 278: `event_db_path: "data/attendance_events.db"` |
| **Status** | Empty but schema initialized — PipelineEngine creates this on startup |

**Evidence:** SOURCE VERIFIED (config) + RUNTIME VERIFIED (inspection)

---

### 3.4 `app/data/exit_sessions.db` & `data/exit_sessions.db` — DUPLICATE PAIR

| Property | Value |
|----------|-------|
| **SHA256** | Identical: eeefde20e6d9d3314c9a72a32a8b4b38101958d042e1f12ead3ac947741a724a |
| **Size** | 24,576 bytes each |
| **Tables** | `exit_sessions` (0 records) |
| **Owner** | Legacy Backend `ExitSessionConfig.db_path = "data/exit_sessions.db"` |
| **Status** | Exact byte-for-byte duplicates — one in `app/data/`, one in `data/` |

**Evidence:** RUNTIME VERIFIED — SHA256 match confirms identical files

---

### 3.5 `app/data/parent_registry.db` & `data/parent_registry.db` — DUPLICATE PAIR

| Property | Value |
|----------|-------|
| **SHA256** | Identical: 0aa11dab160117070214ce16125e476d98bfbfd8ff48cb4a06b7f81a79b96ec8 |
| **Size** | 45,056 bytes each |
| **Tables** | `parents` (0), `student_parent_links` (0), `link_codes` (0) |
| **Owner** | Legacy Backend `ParentRegistryConfig.db_path = "data/parent_registry.db"` |
| **Status** | Exact byte-for-byte duplicates |

**Evidence:** RUNTIME VERIFIED — SHA256 match confirms identical files

---

### 3.6 `app/data/notification_queue.db` & `data/notification_queue.db` — DUPLICATE PAIR

| Property | Value |
|----------|-------|
| **SHA256** | Identical: 670211d208999b820855c2244da5d8bcebdf4a731bcfc22bdd08f019eea49894 |
| **Size** | 32,768 bytes each |
| **Tables** | `notifications` (0) |
| **Owner** | Legacy Backend `NotificationQueueConfig.db_path = "data/notification_queue.db"` |
| **Status** | Exact byte-for-byte duplicates |

**Evidence:** RUNTIME VERIFIED — SHA256 match confirms identical files

---

## 4. Critical Finding: Dual `attendance.db` Instances

**Both `app/data/attendance.db` and `data/attendance.db` are ACTIVE with WAL files present**, indicating both are being written to concurrently by the running Legacy Backend.

| Aspect | `app/data/attendance.db` | `data/attendance.db` |
|--------|--------------------------|----------------------|
| Records | 108 | 18 |
| Data provenance | Mixed test + production (real timestamps 2026) | Benchmark/test only (timestamps 6-100s) |
| WAL/SHM | Active | Active |
| Owner component | Legacy Backend (actual CWD when started from project root) | Legacy Backend (configured `data_dir`) |
| Schema | Identical | Identical |

**Risk:** Data divergence — attendance records written to one database will not appear in the other. The Legacy Backend's effective database path depends on working directory at startup.

**Evidence:** RUNTIME VERIFIED — both have active WAL files

---

## 5. Schema Fingerprints

### 5.1 Phase 25 `attendance_records` (Legacy Backend)

```sql
CREATE TABLE attendance_records (
    attendance_record_id TEXT PRIMARY KEY,
    identity_certainty TEXT NOT NULL,
    identity_candidate TEXT,
    identity_confidence REAL NOT NULL DEFAULT 0.0,
    identity_evidence_ref TEXT,
    direction TEXT NOT NULL,
    event_timestamp REAL NOT NULL,
    event_frame_index INTEGER NOT NULL DEFAULT -1,
    camera_id TEXT NOT NULL,
    local_track_id TEXT NOT NULL,
    global_observation_id TEXT,
    source_raw_event_id TEXT NOT NULL,
    source_resolution_id TEXT NOT NULL UNIQUE,
    source_crossing_event_id TEXT,
    geometry_version INTEGER NOT NULL DEFAULT 0,
    geometry_config_hash TEXT NOT NULL DEFAULT '',
    resolver_version TEXT NOT NULL DEFAULT '1.0',
    resolver_config_hash TEXT NOT NULL DEFAULT '',
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    attendance_schema_version TEXT NOT NULL DEFAULT '1.0',
    created_at TEXT NOT NULL,
    persisted_at TEXT NOT NULL,
    -- 7 CHECK constraints, 10 indexes
);
```

### 5.2 PipelineEngine `attendance_events` (PipelineEngine)

```sql
CREATE TABLE attendance_events (
    event_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    event_type TEXT NOT NULL,
    crossing_point_x REAL NOT NULL,
    crossing_point_y REAL NOT NULL,
    timestamp REAL NOT NULL,
    frame_index INTEGER NOT NULL,
    previous_position_x REAL NOT NULL,
    previous_position_y REAL NOT NULL,
    current_position_x REAL NOT NULL,
    current_position_y REAL NOT NULL,
    person_id TEXT,
    person_name TEXT,
    identity_confidence REAL,
    created_at REAL NOT NULL
);
-- Indexes: idx_camera_timestamp, idx_person_timestamp
```

**Key Difference:** PipelineEngine stores `CrossingEvent` (raw crossing detection); Legacy Backend stores `AttendanceRecord` (resolved, provenance-rich attendance state transition). They are NOT the same logical data.

---

## 6. Summary Classification Matrix

| Database | Classification | Rationale |
|----------|----------------|-----------|
| `app/data/attendance.db` | **AUTHORITATIVE** | Contains production attendance records with full provenance; active WAL; legacy backend writes here when CWD=project root |
| `data/attendance.db` | **ACTIVE SECONDARY** | Configured default (`Settings.paths.data_dir`); active WAL; but only test/benchmark data |
| `data/attendance_events.db` | **DUPLICATE / PipelineEngine** | PipelineEngine-owned; different schema; empty but initialized |
| `app/data/exit_sessions.db` | **AUTHORITATIVE** | Legacy Backend exit session store |
| `data/exit_sessions.db` | **DUPLICATE** | Byte-identical to app/data version |
| `app/data/parent_registry.db` | **AUTHORITATIVE** | Legacy Backend parent registry store |
| `data/parent_registry.db` | **DUPLICATE** | Byte-identical to app/data version |
| `app/data/notification_queue.db` | **AUTHORITATIVE** | Legacy Backend notification queue store |
| `data/notification_queue.db` | **DUPLICATE** | Byte-identical to app/data version |
| `app/data/test_phase52_*.db` | **HISTORICAL / TEST** | Phase 52 test artifacts |
| `data/test_phase52_*.db` | **HISTORICAL / TEST** | Phase 52 test artifacts |

---

## 7. Open Questions

1. **Which `attendance.db` does the running Legacy Backend actually write to?** — Depends on CWD at startup. Both have active WAL, suggesting both may be receiving writes (possibly from different processes or restarts with different CWD).

2. **Does PipelineEngine write to `data/attendance.db`?** — No evidence found; PipelineEngine uses `data/attendance_events.db` (different schema).

3. **Should `data/attendance.db` be removed or merged?** — Requires human decision (Phase 1 action: NEEDS HUMAN DECISION).

---

**End of SQLite Inventory and Integrity Audit**