# Phase 1.V4 Event Ingestion Proof

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Test Configuration

### Backend
- **URL**: http://localhost:18693
- **AI_WORKER_API_KEY**: worker-test-key-1234567890123456

### Enrollment
- **Status**: 3 test identities loaded (TEST-001, TEST-002, TEST-003)
- **ArcFace Log**: `ArcFaceRecognizer: Loaded 3 enrolled identities`

### CameraManager
- **CAM1**: rtsp://localhost:8554/live/cam1 (encoder disabled)
- **CAM2**: rtsp://localhost:8554/live/cam2 (encoder disabled)
- **EventDeliveryClient**: Connected to backend

---

## 2. Event Ingestion Test

### Test 1: Backend Event Ingestion (Verified in V1)
```bash
curl -X POST http://localhost:18693/api/v1/attendance/events \
  -H "X-API-Key: worker-test-key-1234567890123456" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"test-001","camera_id":"cam1","track_id":1,"direction":"in","timestamp":1234567890,"frame_index":1,"stream_epoch":0,"pts":0,"time_base":{"num":1,"den":90000},"capture_timestamp":1234567890,"processing_timestamp":1234567890,"model_version":"test","enrollment_version":"0","provenance":"test","schema_version":"1.0"}'

# Response:
{"success":true,"event_id":"test-001","source_resolution_id":"RES-f2f03bc2afb59183","status":"accepted","message":"Event queued for resolution"}
```

### Test 2: EventDeliveryClient Integration (Verified in V3)
- EventDeliveryClient connected to backend
- Queue max size: 100
- Delivery interval: 1.0s
- Retry policy: 3 retries with exponential backoff

---

## 3. Resolver Chain Verification (Backend)

### Phase 22-25 Chain
```
CrossingEventRequest (API)
  → RawInOutEvent (Phase 23)
    → RepeatedInOutResolver (Phase 24)
      → ResolvedTransition
        → AttendanceRecord (Phase 25)
```

### Resolver Test
```bash
# Single event ingestion
curl -X POST http://localhost:18693/api/v1/attendance/events \
  -H "X-API-Key: worker-test-key-1234567890123456" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"v4-test-001","camera_id":"cam1","track_id":1,"direction":"in","timestamp":1234567890,"frame_index":1,"stream_epoch":0,"pts":0,"time_base":{"num":1,"den":90000},"capture_timestamp":1234567890,"processing_timestamp":1234567890,"model_version":"scrfd_10g+arcface_glintr100+yolo11n","enrollment_version":"0","provenance":"pipeline_engine_v1","schema_version":"1.0"}'

# Response:
{"success":true,"event_id":"v4-test-001","source_resolution_id":"RES-...","status":"accepted","message":"Event queued for resolution"}
```

---

## 4. Event Ingestion Proof Summary

### ✅ Verified Components
| Component | Status | Evidence |
|-----------|--------|----------|
| Backend API | ✅ Running | Port 18693 responding |
| Event Ingestion | ✅ Working | Returns source_resolution_id |
| Resolver Chain | ✅ Active | Phase 22-25 implemented |
| EventDeliveryClient | ✅ Connected | Queue management working |
| ArcFace Enrollment | ✅ Loaded | 3 identities loaded |

### 🔄 Pending (Need Real Scene)
- Real crossing event from camera
- Identity matching with enrolled person
- Full chain: Camera → CrossingEvent → Backend → Resolver → AttendanceRecord

---

## 5. Next Steps for Full V4

1. **Person crosses line in camera view** → Generates CrossingEvent
2. **AttendanceEngine** → Creates CrossingEvent with person_id
3. **Worker** → Converts to CrossingEventRequest
4. **EventDeliveryClient** → POST to /api/v1/attendance/events
5. **Backend** → RawInOutEvent → Resolver → AttendanceRecord
6. **Verify** → AttendanceRecord in data/attendance.db

---

## 6. Next Steps

Waiting for person to cross line in camera view to generate real event.