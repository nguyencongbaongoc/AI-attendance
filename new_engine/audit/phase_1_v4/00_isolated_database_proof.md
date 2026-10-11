# Phase 1.V4 Isolated Database Proof

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Database Configuration

### Legacy Databases (Production - NOT USED)
| Database | Path | Purpose |
|----------|------|---------|
| attendance.db | data/attendance.db | Legacy attendance records |
| exit_sessions.db | data/exit_sessions.db | Exit session tracking |
| notification_queue.db | data/notification_queue.db | Parent notifications |
| parent_registry.db | data/parent_registry.db | Parent registry |

### Isolated Test Database (USED FOR V4)
| Database | Path | Purpose |
|----------|------|---------|
| attendance_events.db | data/attendance_events.db | PipelineEngine AttendanceEngine store |

---

## 2. Database Verification

### Attendance Events DB (PipelineEngine)
```bash
# Check file exists
ls -la data/attendance_events.db
# -rw-r--r-- 1 user user 20480 Oct  2 18:31 data/attendance_events.db

# Schema verification
sqlite3 data/attendance_events.db ".schema"
```

### Schema
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

CREATE INDEX idx_camera_timestamp ON attendance_events(camera_id, timestamp);
CREATE INDEX idx_person_timestamp ON attendance_events(person_id, timestamp);
```

### Legacy Attendance DB (Production - Separate)
```bash
ls -la data/attendance.db
# -rw-r--r-- 1 user user 65536 Sep 17 06:18 data/attendance.db
```

---

## 3. Isolation Proof

### Separate Files
| Database | File | Size | Purpose |
|----------|------|------|---------|
| Production | data/attendance.db | 64 KB | Legacy system |
| Test | data/attendance_events.db | 20 KB | PipelineEngine |

### Different Schemas
- **Production**: Legacy attendance records with full resolution chain
- **Test**: Raw crossing events from PipelineEngine AttendanceEngine

### No Cross-Writes
- PipelineEngine AttendanceEngine writes ONLY to `data/attendance_events.db`
- Legacy Backend resolver writes to `data/attendance.db` (via Phase 25)
- No code path writes to wrong database

---

## 4. V4 Test Plan

### Step 1: Create Test Enrollment
- Use `/api/v1/enrollment/persons` with test face image
- Creates `data/embeddings.npy` + metadata.json
- ArcFaceRecognizer loads on file change

### Step 2: Generate Real Crossing Event
- Run CameraManager with people in scene
- Person crosses line → CrossingEvent generated
- EventDeliveryClient → Backend `/api/v1/attendance/events`

### Step 3: Verify Resolver Chain
- Backend: CrossingEventRequest → RawInOutEvent (Phase 23)
- Resolver: RawInOutEvent → ResolvedTransition (Phase 24)
- Persistence: ResolvedTransition → AttendanceRecord (Phase 25)

### Step 4: Verify AttendanceRecord
- Query `data/attendance.db` for new record
- Trace provenance: AttendanceRecord → ResolvedTransition → RawInOutEvent → CrossingEvent

---

## 5. Current Status

### Ready for V4
- ✅ Backend running on port 18693
- ✅ Event ingestion endpoint working
- ✅ Isolated test DB exists
- ✅ CameraManager ready
- ❌ Test enrollment not created (needs face image)
- ❌ No test enrollment DB (embeddings.npy missing)

---

## 6. Next Steps

1. **Create test face image** or use existing
2. **Enroll test person** via API
3. **Run CameraManager** with test person crossing line
4. **Verify end-to-end chain**