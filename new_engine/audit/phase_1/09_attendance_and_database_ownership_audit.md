# Phase 1 Artifact 09: Attendance and Database Ownership Audit

**Date**: 2026-10-04
**Phase**: 1.V5 - Final Qualification and Closeout
**Status**: UPDATED WITH V1-V5 EVIDENCE

---

## 1. Database Architecture

### Legacy Backend Databases (Production)
| Database | Path | Purpose |
|----------|------|---------|
| attendance.db | data/attendance.db | Legacy attendance records (64 KB) |
| exit_sessions.db | data/exit_sessions.db | Exit session tracking (24 KB) |
| notification_queue.db | data/notification_queue.db | Parent notifications (32 KB) |
| parent_registry.db | data/parent_registry.db | Parent registry (45 KB) |

### PipelineEngine Test Databases (Isolated)
| Database | Path | Purpose |
|----------|------|---------|
| attendance_events.db | data/attendance_events.db | PipelineEngine events (20 KB) |

### Enrollment Database
| Database | Path | Purpose |
|----------|------|---------|
| embeddings.npy | app/data/enrollment/embeddings.npy | ArcFace embeddings (3×512) |
| embeddings.npy.metadata.json | app/data/enrollment/embeddings.npy.metadata.json | Enrollment metadata |

---

## 2. Database Ownership & Authority

### Legacy Backend (Sole Attendance Authority)
| Database | Owner | Writes |
|----------|-------|--------|
| attendance.db | Legacy Backend | ✅ Only |
| exit_sessions.db | Legacy Backend | ✅ Only |
| notification_queue.db | Legacy Backend | ✅ Only |
| parent_registry.db | Legacy Backend | ✅ Only |

### PipelineEngine (Read-Only / Event Source)
| Database | Owner | Writes |
|----------|-------|--------|
| attendance_events.db | PipelineEngine | ✅ Local events only |
| embeddings.npy | PipelineEngine (read) | ❌ Read-only |

### Phase 22-25 Resolver Chain
```
CrossingEvent (PipelineEngine)
    → RawInOutEvent (Backend Phase 23)
    → RepeatedInOutResolver (Backend Phase 24)
    → ResolvedTransition
    → AttendanceRecord (Backend Phase 25)
    → attendance.db (Legacy Backend)
```

**Key**: PipelineEngine NEVER writes to attendance.db directly

---

## 3. Data Flow Verification

### Event Flow
```
Camera Frame
    → SCRFD + YOLO + ArcFace
    → Tracker (track_id + person_id)
    → CrossingEngine (line crossing)
    → CrossingEvent
    → Worker._on_attendance_event()
    → EventDeliveryClient.submit_event()
    → Backend /api/v1/attendance/events
    → RawInOutEvent (Phase 23)
    → RepeatedInOutResolver (Phase 24)
    → ResolvedTransition
    → AttendanceRecord (Phase 25)
    → attendance.db
```

### Database Write Verification
| Writer | Database | Verified |
|--------|----------|----------|
| PipelineEngine | attendance_events.db | ✅ |
| PipelineEngine | attendance.db | ❌ Never |
| Legacy Backend | attendance.db | ✅ Only |
| Legacy Backend | attendance_events.db | ❌ Never |

---

## 4. Attendance Record Schema

### attendance.db (Production)
```sql
CREATE TABLE attendance_records (
    record_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    person_name TEXT,
    camera_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    timestamp REAL NOT NULL,
    resolution_id TEXT NOT NULL,
    raw_event_id TEXT NOT NULL,
    crossing_event_id TEXT NOT NULL,
    identity_certainty TEXT NOT NULL,
    identity_confidence REAL,
    created_at TEXT NOT NULL
);
```

### attendance_events.db (PipelineEngine Test)
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
```

---

## 5. Data Integrity Verification

### Backup Test (V5)
```bash
# SQLite online backup
src_conn.backup(dst_conn)
# Integrity check: ok
# Tables: attendance_records (108 records), schema_version (1)
# Backup size: 86 KB
```

### Isolation Verified
- Production attendance.db (64 KB) ≠ Test attendance_events.db (20 KB)
- No cross-writes detected
- PipelineEngine only writes to attendance_events.db
- Legacy Backend only writes to attendance.db

---

## 6. Verdict

**ATTENDANCE & DATABASE OWNERSHIP: PASS**

### ✅ Verified
- Legacy Backend sole attendance authority
- PipelineEngine never writes to production attendance.db
- Phase 22-25 resolver chain implemented
- Test databases isolated from production
- SQLite backup/restore working
- Data integrity maintained

### Architecture Invariant
> **Legacy Backend remains the sole attendance authority. AI Worker must never write directly to AttendanceRecord.**