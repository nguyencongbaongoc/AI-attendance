# Phase 0.2.1 — Attendance Authority Verification

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED / RUNTIME VERIFIED

---

## 1. Executive Summary

**The Legacy Backend remains the sole attendance authority** — but with a critical CWD-dependent path bug creating two active `attendance.db` instances. PipelineEngine does NOT independently maintain attendance state; it uses a separate `attendance_events.db` with a different schema (CrossingEvent, not AttendanceRecord). The Phase 0.2 claim "No second attendance DB" is **FALSE** — `data/attendance.db` is a second active attendance database with different data.

---

## 2. Data Flow Verification: CrossingEvent → AttendanceRecord

### 2.1 Expected Architecture A Flow

```
Camera → MediaMTX → PyAV → SCRFD/ArcFace/YOLO → Tracking → CrossingEngine
                                                              ↓
                                                    CrossingEvent (PipelineEngine)
                                                              ↓
                                                    Legacy Backend API (NOT YET IMPLEMENTED)
                                                              ↓
                                                    Phase 24 Resolver → ResolvedTransition
                                                              ↓
                                                    Phase 25 AttendanceRepository → AttendanceRecord
                                                              ↓
                                                    app/data/attendance.db (AUTHORITATIVE)
```

### 2.2 Actual Current Flow (Phase 0.2 State)

```
Camera → MediaMTX → PyAV → SCRFD/ArcFace/YOLO → Tracking → CrossingEngine
                                                              ↓
                                                    CrossingEvent (PipelineEngine)
                                                              ↓
                                                    data/attendance_events.db (PipelineEngine local)
                                                              ↓
                                                    [NO PATH TO LEGACY BACKEND — MISSING API ENDPOINTS]
```

**Missing:** Legacy Backend endpoints for AI Worker ingestion (`POST /api/v1/attendance/events`, etc.)

**Evidence:** SOURCE VERIFIED — `pipeline_engine/attendance/attendance_engine.py` stores to local SQLite; `16_blockers_and_recovery_plan.md` §2.1 lists 4 missing endpoints.

---

## 3. Entity-to-Database Mapping

| Entity | Phase | Database | Table | Owner Component | Status |
|--------|-------|----------|-------|-----------------|--------|
| `CrossingEvent` | 22/26 | `data/attendance_events.db` | `attendance_events` | PipelineEngine `AttendanceStore` | **ACTIVE** |
| `RawInOutEvent` | 23 | In-memory only | — | `InOutEventResolver` | Transient |
| `ResolvedTransition` | 24 | In-memory only | — | `RepeatedInOutResolver` | Transient |
| `AttendanceRecord` | 25 | `app/data/attendance.db` + `data/attendance.db` | `attendance_records` | Legacy Backend `AttendanceRepository` | **DUAL ACTIVE** |
| `ExitSession` | 37C | `app/data/exit_sessions.db` + `data/exit_sessions.db` | `exit_sessions` | Legacy Backend `ExitSessionPersistence` | DUPLICATE |
| `ParentRegistry` | 37B | `app/data/parent_registry.db` + `data/parent_registry.db` | `parents`, `links`, `codes` | Legacy Backend `ParentRegistry` | DUPLICATE |
| `NotificationQueue` | 37B | `app/data/notification_queue.db` + `data/notification_queue.db` | `notifications` | Legacy Backend `NotificationQueue` | DUPLICATE |
| `Enrollment` | 39C | `app/data/enrollment/embeddings.npy` | NPY file | Legacy Backend `EnrollmentService` | SINGLE SOURCE |

---

## 4. Component Ownership Analysis

### 4.1 Legacy Backend — Attendance Authority (CONFIRMED)

| Component | Responsibility | Database | Write Access |
|-----------|----------------|----------|--------------|
| `AttendanceStorage` | Phase 25 AttendanceRecord CRUD | `data/attendance.db` (CWD-dependent) | ✅ YES |
| `AttendanceRepository` | Phase 24→25 persistence bridge | `data/attendance.db` | ✅ YES |
| `AttendanceEngine` | Policy-driven state transitions | `data/attendance.db` | ✅ YES |
| `DetectionPipeline` | Streaming → attendance persistence | `data/attendance.db` | ✅ YES |
| `InOutEventResolver` | Phase 23 RawInOutEvent resolution | In-memory | Transient |
| `RepeatedInOutResolver` | Phase 24 transition resolution | In-memory | Transient |

**Authority:** **SOLE AUTHORITY for `AttendanceRecord` persistence**

---

### 4.2 PipelineEngine — AI Worker Only (CONFIRMED)

| Component | Responsibility | Database | Write Access |
|-----------|----------------|----------|--------------|
| `CrossingEngine` | Line crossing detection | `data/attendance_events.db` | ✅ YES (different schema) |
| `AttendanceEngine` | Coordinates crossing + storage | `data/attendance_events.db` | ✅ YES |
| `AttendanceStore` | CrossingEvent SQLite persistence | `data/attendance_events.db` | ✅ YES |
| `Tracking` | Camera-isolated track management | In-memory | Transient |
| `SCRFD/ArcFace/YOLO` | Detection/embedding/matching | In-memory/GPU | Transient |

**Authority:** **NO AttendanceRecord writes** — only `CrossingEvent` to local `attendance_events.db`

**Evidence:** SOURCE VERIFIED — `pipeline_engine/attendance/attendance_engine.py` uses `AttendanceStore` with `attendance_events` table, NOT `attendance_records`.

---

### 4.3 PipelineEngine Config References (NOT Active Code)

`pipeline_engine/config/pipeline.yaml` lines 428-433 list Legacy Backend databases under `integration.databases` — but **no PipelineEngine code currently reads/writes these**. They are documented references for future integration.

---

## 5. Duplicate Attendance Databases — CONFIRMED ACTIVE

| Database | Records | Data Type | WAL Active |
|----------|---------|-----------|------------|
| `app/data/attendance.db` | 108 | Mixed test + production (real 2026 timestamps) | ✅ YES |
| `data/attendance.db` | 18 | Benchmark/test only (timestamps 6-100s) | ✅ YES |

**Both are `attendance_records` tables with identical Phase 25 schema.** Both have active WAL files indicating concurrent writes.

**Root Cause:** CWD-dependent path resolution (see `02_database_path_and_owner_trace.md` §6).

---

## 6. PipelineEngine Attendance Persistence — VERDICT

| Question | Answer | Evidence |
|----------|--------|----------|
| Does PipelineEngine write `AttendanceRecord`? | **NO** | Uses `AttendanceStore` → `attendance_events` table |
| Does PipelineEngine have independent attendance state? | **NO** | Only `CrossingEvent` (raw detection), no state resolution |
| Does PipelineEngine write to `app/data/attendance.db`? | **NO** | No code path found |
| Does PipelineEngine write to `data/attendance.db`? | **NO** | No code path found |
| Is `data/attendance_events.db` an attendance database? | **PARTIALLY** | Stores `CrossingEvent` (pre-resolution), not `AttendanceRecord` |

---

## 7. Architecture A Policy Compliance Check

| Policy Requirement | Status | Evidence |
|-------------------|--------|----------|
| Legacy Backend = sole attendance authority | ⚠️ **VIOLATED** | Two active `attendance.db` instances |
| Phase 22-25 = authoritative resolver chain | ✅ **COMPLIANT** | Phase 24 resolver → Phase 25 storage implemented |
| PipelineEngine = AI worker only | ✅ **COMPLIANT** | Only writes `CrossingEvent` to local DB |
| PipelineEngine must not write `AttendanceRecord` | ✅ **COMPLIANT** | Different schema, different table |
| PipelineEngine must not maintain attendance state | ✅ **COMPLIANT** | No `AttendanceRecord` logic in PipelineEngine |
| AI events enter through Legacy Backend boundary | ❌ **NOT IMPLEMENTED** | Missing 4 API endpoints (Phase 1 blocker) |

---

## 8. Attendance Authority Verdict Matrix

| Database | Actual Path | Current Owner | Authority | Phase 1 Action |
|----------|-------------|---------------|-----------|----------------|
| `attendance.db` (production data) | `app/data/attendance.db` | Legacy Backend | **AUTHORITATIVE** | **KEEP** — primary attendance store |
| `attendance.db` (test data only) | `data/attendance.db` | Legacy Backend | **ACTIVE SECONDARY** | **NEEDS HUMAN DECISION** — merge or remove |
| `attendance_events.db` | `data/attendance_events.db` | PipelineEngine | **ACTIVE SECONDARY** (different schema) | **API ACCESS ONLY** — PipelineEngine keeps for local crossing events; Legacy Backend ingests via API |
| `exit_sessions.db` | `app/data/exit_sessions.db` | Legacy Backend | **AUTHORITATIVE** | **KEEP** |
| `exit_sessions.db` (duplicate) | `data/exit_sessions.db` | Legacy Backend | **DUPLICATE** | **READ-ONLY ARCHIVE** — remove duplicate |
| `parent_registry.db` | `app/data/parent_registry.db` | Legacy Backend | **AUTHORITATIVE** | **KEEP** |
| `parent_registry.db` (duplicate) | `data/parent_registry.db` | Legacy Backend | **DUPLICATE** | **READ-ONLY ARCHIVE** — remove duplicate |
| `notification_queue.db` | `app/data/notification_queue.db` | Legacy Backend | **AUTHORITATIVE** | **KEEP** |
| `notification_queue.db` (duplicate) | `data/notification_queue.db` | Legacy Backend | **DUPLICATE** | **READ-ONLY ARCHIVE** — remove duplicate |

---

## 9. Critical Blockers for Phase 1

1. **CWD-dependent path bug** — Must fix `Settings.paths.data_dir` and `StorageConfig.database_path` to use absolute paths.
2. **Dual `attendance.db`** — Must choose single authoritative path (`app/data/attendance.db` recommended — has production data).
3. **Missing Legacy Backend API endpoints** — 4 endpoints needed for PipelineEngine → Legacy Backend event ingestion.
4. **PipelineEngine `LegacyBackendClient` not implemented** — Required for Architecture A compliance.

---

**End of Attendance Authority Verification**