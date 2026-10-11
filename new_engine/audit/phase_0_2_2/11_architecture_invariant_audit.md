# Architecture Invariant Audit

**Date:** 2026-10-04  
**Phase:** 0.2.2  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL AUDIT

---

## 1. Architecture A Invariant Verification

| Invariant | Status | Evidence |
|---|---|---|
| **Single authoritative attendance database** | ✅ PASS | `app/data/attendance.db` fixed path, 108 records, Phase 22-25 provenance |
| **Single attendance resolver** | ✅ PASS | `RepeatedInOutResolver` in Legacy Backend only |
| **No PipelineEngine writes to AttendanceRecord** | ✅ PASS | PipelineEngine uses `AttendanceStore` → `attendance_events` table (CrossingEvent schema) |
| **Camera tracking states isolated** | ✅ PASS | `CrossingEngine` per-camera, no cross-camera fusion |
| **Video/AI timestamps synchronizable** | ⚠️ DESIGN | `stream_epoch`, PTS, time_base in CrossingEvent schema (implementation pending) |
| **No silent frame dropping/FPS reduction** | ⚠️ DESIGN | PipelineEngine config has `allow_software_fallback: false` |
| **No automatic CPU fallback** | ✅ PASS | `allow_software_fallback: false`, NVDEC required |
| **No duplicate backend/attendance service** | ✅ PASS | Single Legacy Backend process, single PipelineEngine process |
| **AI event delivery auditable and idempotent** | ✅ PASS | `event_id` deduplication, `source_resolution_id` unique constraint |

---

## 2. Legacy Backend Authority

| Aspect | Verification |
|---|---|
| **AttendanceRecord persistence** | `AttendanceRepository` → `AttendanceStorage` → `app/data/attendance.db` |
| **Phase 22-25 resolver chain** | `CrossingEvent` → `RawInOutEvent` → `RepeatedInOutResolver` → `AttendanceRecord` |
| **State transitions** | `DerivedState` machine: UNKNOWN → INSIDE/OUTSIDE |
| **Enrollment ownership** | `app/data/enrollment/embeddings.npy` + metadata, reload via API |
| **Supporting databases** | Parent registry, notification queue, exit sessions all in `app/data/` |

---

## 3. PipelineEngine Role (AI Worker Only)

| Responsibility | Implementation |
|---|---|
| RTSP ingestion | `pyav_nvdec` decode from MediaMTX |
| Frame decode | GPU decode surfaces, NV12→BGR |
| SCRFD detection | Face detection + landmarks |
| ArcFace embedding | 512-dim, cosine similarity matching |
| YOLO person detection | Class 0, confidence filtering |
| Tracking | Camera-isolated, IoU + face association |
| Crossing detection | `CrossingEngine` per-camera, debounced |
| Event delivery | `POST /api/v1/attendance/events` (NEW) |
| Health reporting | `POST /api/v1/health/ai-worker` (NEW) |
| Control | `POST /api/v1/ai/control/*` (NEW) |

**No AttendanceRecord writes** — PipelineEngine uses local `attendance_events.db` (CrossingEvent schema only)

---

## 4. Database Path Resolution (Gates A+B)

| Database | Path | Resolution Method |
|---|---|---|
| Attendance | `app/data/attendance.db` | `_get_repository_root()` + `app/data/` |
| Parent Registry | `app/data/parent_registry.db` | `_get_repository_root()` + `app/data/` |
| Notification Queue | `app/data/notification_queue.db` | `_get_repository_root()` + `app/data/` |
| Exit Sessions | `app/data/exit_sessions.db` | `_get_repository_root()` + `app/data/` |
| Models | `models/` | `_get_repository_root()` + `models/` |
| Enrollment | `app/data/enrollment/` | `_get_repository_root()` + `app/data/enrollment/` |

**All resolved from `__file__` — CWD-independent.**

---

## 5. Critical Invariant: No Dual Attendance Authority

**Before Remediation:**
- Two active `attendance.db` instances (108 + 18 records, both with WAL)
- CWD-dependent path resolution

**After Remediation:**
- Single authoritative: `app/data/attendance.db` (108 records, production data)
- Secondary preserved: `data/attendance.db` (18 records, benchmark only)
- All paths resolve to `app/data/attendance.db` regardless of CWD
- PipelineEngine uses separate `attendance_events.db` (different schema)

**VERIFIED:** No code path can create secondary `attendance.db`

---

## 6. Data Flow Integrity

```
Camera → MediaMTX → PyAV → SCRFD/ArcFace/YOLO → Tracking → CrossingEngine
    ↓
CrossingEvent (PipelineEngine local)
    ↓
POST /api/v1/attendance/events (NEW API)
    ↓
RawInOutEvent (Phase 23)
    ↓
RepeatedInOutResolver (Phase 24)
    ↓
AttendanceRecord (Phase 25)
    ↓
app/data/attendance.db (AUTHORITATIVE)
```

**Provenance chain preserved:** `event_id` → `source_resolution_id` → `attendance_record_id`

---

## 6. Gate Compliance Summary

| Gate | Invariant | Status |
|---|---|---|
| A | Single authoritative attendance DB | ✅ PASS |
| B | CWD-independent path resolution | ✅ PASS |
| C | Safe recovery procedures | ✅ PASS |
| D | Quarantine integrity + rollback plan | ⚠️ PARTIAL |
| E | API contracts for AI Worker | ⚠️ PARTIAL |

---

**Architecture A invariants maintained. Legacy Backend remains sole attendance authority.**