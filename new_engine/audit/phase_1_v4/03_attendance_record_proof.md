# Phase 1.V4 Attendance Record Proof

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Database Configuration

### Isolated Test Database
| Database | Path | Purpose |
|----------|------|---------|
| Test | `data/attendance_events.db` | PipelineEngine events (local) |
| Production | `data/attendance.db` | Legacy Backend resolver output |

### Schema: attendance.db (Production)
```sql
CREATE TABLE attendance_records (
    record_id TEXT PRIMARY KEY,
    person_id TEXT NOT NULL,
    person_name TEXT,
    camera_id TEXT NOT NULL,
    direction TEXT NOT NULL,  -- 'in' or 'out'
    timestamp REAL NOT NULL,
    resolution_id TEXT NOT NULL,
    raw_event_id TEXT NOT NULL,
    crossing_event_id TEXT NOT NULL,
    identity_certainty TEXT NOT NULL,  -- 'known', 'unknown', 'ambiguous', 'insufficient'
    identity_confidence REAL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_person_timestamp ON attendance_records(person_id, timestamp);
CREATE INDEX idx_camera_timestamp ON attendance_records(camera_id, timestamp);
```

---

## 2. Attendance Record Generation Flow

### Complete Chain
```
1. Person crosses line in camera view
2. SCRFD detects face → ArcFace generates embedding
3. ArcFace matches embedding to enrollment → person_id
4. Tracker associates face with track → track.person_id
5. CrossingEngine detects line crossing → CrossingEvent
6. AttendanceEngine.process_tracks() → CrossingEvent
7. Event callback → Worker._on_attendance_event()
8. Worker._convert_crossing_event() → CrossingEventRequest
9. EventDeliveryClient.submit_event() → Backend /api/v1/attendance/events
9. Backend: CrossingEventRequest → RawInOutEvent (Phase 23)
10. Backend: RawInOutEvent → RepeatedInOutResolver (Phase 24)
11. Resolver → ResolvedTransition
12. Phase 25: ResolvedTransition → AttendanceRecord
13. AttendanceRecord stored in data/attendance.db
```

---

## 2. AttendanceRecord Fields

### Core Fields
| Field | Source | Description |
|-------|--------|-------------|
| `record_id` | Backend | Unique record ID |
| `person_id` | Enrollment | TEST-001, TEST-002, TEST-003 |
| `person_name` | Enrollment | From metadata |
| `camera_id` | PipelineEngine | "cam1" or "cam2" |
| `direction` | CrossingEngine | "in" or "out" |
| `timestamp` | PipelineEngine | Unix timestamp |
| `resolution_id` | Phase 24 | Links to ResolvedTransition |
| `raw_event_id` | Phase 23 | Links to RawInOutEvent |
| `crossing_event_id` | Phase 22 | Links to CrossingEvent |
| `identity_certainty` | Phase 23 | "known"/"unknown"/"ambiguous" |
| `identity_confidence` | ArcFace | Similarity score (0.0-1.0) |
| `created_at` | Backend | ISO timestamp |

---

## 3. Verification Method

### Query Attendance Records
```bash
sqlite3 data/attendance.db "SELECT * FROM attendance_records;"
```

### Expected Result (for TEST-001 crossing IN)
| Field | Expected Value |
|-------|----------------|
| person_id | "TEST-001" |
| person_name | "Test Person 1" (from metadata) |
| camera_id | "cam1" |
| direction | "in" |
| identity_certainty | "known" |
| identity_confidence | ≥ 0.6 |
| resolution_id | RES-... (from resolver) |

---

## 4. Provenance Chain Verification

### Trace from AttendanceRecord to Camera Frame
```sql
-- 1. Get AttendanceRecord
SELECT * FROM attendance_records WHERE person_id = 'TEST-001';

-- 2. Trace to ResolvedTransition (via resolution_id)
-- resolver logs show: "Event {event_id} ingested, resolution: {RES-...}"

-- 3. Trace to RawInOutEvent (via raw_event_id)
-- RawInOutEvent.source_crossing_event_id → CrossingEvent

-- 4. Trace to CrossingEvent
-- CrossingEvent.track_id → Track
# CameraManager metrics show: tracks_active

-- 5. Trace to Frame
# CrossingEvent.frame_index → Frame
# Frame.pts, Frame.time_base, Frame.camera_id
```

---

## 5. Proof Requirements (V4 Gate)

### Minimum Viable Proof
| Requirement | Status | Evidence |
|-------------|--------|----------|
| Real crossing event generated | ⏳ Pending | Need person in scene |
| Event delivered to Backend | ✅ Ready | EventDeliveryClient ready |
| Resolver processes event | ✅ Ready | Resolver chain implemented |
| AttendanceRecord created | ⏳ Pending | Need real event |
| Record in isolated DB | ✅ Ready | data/attendance.db exists |
| Provenance chain intact | ✅ Designed | Full chain implemented |

---

## 6. Verification Checklist

### When Real Event Occurs
- [ ] CrossingEvent generated with person_id = "TEST-001"
- [ ] EventDeliveryClient submits to Backend
- [ ] Backend returns source_resolution_id
- [ ] Resolver creates ResolvedTransition
- [ ] AttendanceRecord inserted into data/attendance.db
- [ ] Query confirms record exists with correct fields
- [ ] Provenance chain traceable end-to-end

---

## 6. Current Status

### Ready for Live Test
- ✅ Backend running
- ✅ Enrollment loaded (3 test persons)
- ✅ ArcFaceRecognizer loaded 3 identities
- ✅ CameraManager running (dual-camera tested 30 min)
- ✅ EventDeliveryClient connected
- ✅ Backend resolver chain implemented

### Blocking: No Person in Scene
- Need person to walk in front of camera
- Cross the configured line (y=1080)
- Generate real CrossingEvent with person_id

---

## 7. Next Steps

1. **Have person walk in front of CAM1/CAM2**
2. **Cross the line at y=1080** (configured for both cameras)
3. **Monitor logs** for:
   - `CrossingEvent generated: CE-...`
   - `Event {event_id} ingested, resolution: RES-...`
4. **Query attendance.db** for new record
5. **Verify provenance chain** end-to-end

---

## 8. Evidence Artifacts

### Database Files
- `data/attendance.db` - Production attendance records
- `data/attendance_events.db` - PipelineEngine local events

### Verification Commands
```bash
# Check for new records
sqlite3 data/attendance.db "SELECT * FROM attendance_records ORDER BY created_at DESC LIMIT 10;"

# Check resolver logs
grep "ingested, resolution" backend.log

# Check event delivery
grep "Event delivery" backend.log
```