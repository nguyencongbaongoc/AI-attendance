# Gate A — Database Authority Proof (CF-01)

**Date:** 2026-10-04  
**Phase:** 0.2.2 — Gate A (Authority Proof)  
**Classification:** SOURCE-VERIFIED / RUNTIME-VERIFIED

---

## 1. Executive Summary

**DATABASE AUTHORITY ESTABLISHED: `app/data/attendance.db` is the sole authoritative attendance database.**

This document provides the conclusive evidence that `app/data/attendance.db` (108 records, production data, active WAL/SHM) is the authoritative attendance database, while `data/attendance.db` (18 records, benchmark data only) is a preserved secondary artifact.

---

## 2. Authority Evidence Matrix

| Evidence Category | `app/data/attendance.db` (AUTHORITATIVE) | `data/attendance.db` (SECONDARY) |
|---|---|---|
| **Record Count** | 108 | 18 |
| **Data Provenance** | Production + test (Phase 22-25 full chain) | Benchmark only |
| **Timestamp Range** | 5.24 (test) → 1,787,502,600 (2026-09-22) | 6.91 → 100.28 (seconds, benchmark) |
| **Phase 22-25 Provenance** | ✅ Full chain (`source_raw_event_id`, `source_resolution_id`, `source_crossing_event_id`) | ❌ None |
| **WAL/SHM** | Active (SHM 32KB, WAL checkpointed) | Active (SHM 32KB, WAL checkpointed) |
| **SHA256** | f711c4392426c4c1f6ae278fed12b5121dc4cccf29a18a4a899485ec4100f5eb | 30fb1f177f284b3fd573d2baa46538da2993b0bf5b6c6cb48717116a429d7080 |
| **Size** | 86,016 bytes | 65,536 bytes |
| **Schema** | Phase 25 complete (23 cols, 10 indexes, 7 constraints) | Phase 25 complete (identical) |

---

## 3. Ownership Proof

### 3.1 Source Code Ownership Chain

```
AttendanceStorage (storage.py)
    → creates/manages AttendanceRecord persistence
    → uses StorageConfig.database_path (now fixed to app/data/attendance.db)

AttendanceRepository (repository.py)
    → wraps AttendanceStorage
    → provides high-level persistence/query API

AttendanceEngine (engine.py)
    → uses AttendanceRepository
    → applies Phase 22-25 business logic

DetectionPipeline (detection_pipeline.py)
    → uses AttendanceRepository
    → stores resolved attendance events

API Endpoints (attendance.py, persons.py, replay.py, provenance.py)
    → read from AttendanceRepository
    → never write directly to database
```

### 3.2 Runtime Ownership Verification

**No processes currently running** — both databases are checkpointed (WAL = 0 bytes, SHM = 32KB active for shared memory).

**Last access timestamps (SHM files):**
- `app/data/attendance.db-shm`: 2026-10-04 09:41:49
- `data/attendance.db-shm`: 2026-10-04 09:41:49

Both were accessed during the same session (Phase 0.2 runtime verification), confirming the dual-database bug from CWD-dependent startup.

---

## 4. Secondary Database Preservation

### 4.1 `data/attendance.db` Status

- **Location:** Preserved at original path `data/attendance.db`
- **Records:** 18 benchmark/test records intact
- **SHA256:** 30fb1f177f284b3fd573d2baa46538da2993b0bf5b6c6cb48717116a429d7080 (unchanged)
- **WAL/SHM:** Checkpointed, valid
- **Availability:** Ready for human review

### 4.2 No Data Loss

| Check | Result |
|---|---|
| Records merged? | ❌ NO |
| Records overwritten? | ❌ NO |
| Records deleted? | ❌ NO |
| Schema modified? | ❌ NO |
| WAL corrupted? | ❌ NO (both checkpointed) |
| Secondary accessible? | ✅ YES |

---

## 5. Writer/Reader Analysis

### 5.1 Confirmed Writers to Authoritative DB

| Component | File | Operation | Path Resolution |
|---|---|---|---|
| `AttendanceStorage` | `storage.py` | R/W | Fixed to `app/data/attendance.db` |
| `AttendanceRepository` | `repository.py` | R/W | Delegates to Storage |
| `AttendanceEngine` | `engine.py` | R/W | Delegates to Repository |
| `DetectionPipeline` | `detection_pipeline.py` | R/W | Delegates to Repository |

### 5.2 Confirmed Readers from Authoritative DB

| Component | File | Operation |
|---|---|---|
| `API/attendance.py` | `attendance.py` | R |
| `API/persons.py` | `persons.py` | R |
| `API/replay.py` | `replay.py` | R |
| `API/provenance.py` | `provenance.py` | R |
| `DailyExcelExporter` | `daily_excel.py` | R |

### 5.3 PipelineEngine — Different Database

| Component | File | Database | Schema |
|---|---|---|---|
| `AttendanceStore` | `pipeline_engine/attendance/attendance_engine.py` | `data/attendance_events.db` | CrossingEvent (NOT AttendanceRecord) |

**PipelineEngine does NOT write to `attendance_records` table** — confirmed by source inspection.

---

## 6. No Silent Secondary Recreation

### 5.1 Path Resolution Fixed (Gate B)

All Legacy Backend database paths now resolve to `app/data/attendance.db` regardless of CWD:

- `Settings.paths.data_dir` → `<repo_root>/app/data`
- `StorageConfig.database_path` → `<repo_root>/app/data/attendance.db`
- Supporting DB configs → `<repo_root>/app/data/*.db`

### 5.2 Verification

| Test | Result |
|---|---|
| `load_settings()` from any CWD | ✅ Resolves to `app/data/...` |
| `AttendanceStorage()` from any CWD | ✅ Uses `app/data/attendance.db` |
| `create_attendance_repository()` | ✅ Uses authoritative DB |

---

## 6. Authority Conclusion

**`app/data/attendance.db` is the authoritative attendance database because:**

1. **Contains production data** — Real 2026 timestamps, Phase 22-25 provenance chain
2. **Complete dataset** — 108 records vs 18 (6x more data)
3. **Business logic owner** — Phase 22-25 resolver chain writes here
4. **API consumers read here** — All attendance queries route to this DB
5. **Path fixed** — Gate B ensures all startups use this path
6. **Secondary preserved** — `data/attendance.db` untouched for review

**No second attendance authority exists or can be created.**

---

**Authority Proof Complete. Gate A Fully Satisfied.**