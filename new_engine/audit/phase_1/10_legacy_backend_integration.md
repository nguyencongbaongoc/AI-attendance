# Gate E — Legacy Backend Event Integration Design

**Date:** 2026-10-04  
**Phase:** 1  
**Gate:** E  
**Status:** DESIGN PHASE — Backend endpoints exist, Worker event delivery implemented  

---

## 1. Objective

Connect generated CrossingEvents to actual Phase 0.2.6 Backend APIs:
- Worker authentication (AI_WORKER_API_KEY)
- Event schema validation (CrossingEventRequest)
- Idempotent delivery with retry
- Explicit acknowledgment
- Error classification
- No bypass of Phase 22-25

---

## 2. Backend Endpoints (Existing in `app/api/ai_worker.py`)

### 2.1 Event Ingestion: `POST /api/v1/attendance/events`

**Authentication:** `verify_ai_worker_key` (AI_WORKER_API_KEY)

**Request Schema:** `CrossingEventRequest` (lines 119-148)

```python
class CrossingEventRequest(BaseModel):
    event_id: str                    # Globally unique, stable across retries
    camera_id: str                   # Camera identifier
    track_id: int                    # Local track ID
    direction: str                   # 'in' or 'out'
    event_type: str                  # default: 'line_crossing'
    crossing_point: CrossingPoint    # x, y
    timestamp: float                 # Unix timestamp
    frame_index: int                 # Frame index in stream
    previous_position: Position      # x, y
    current_position: Position       # x, y
    person_id: Optional[str]         # If confidently identified
    person_name: Optional[str]
    identity_confidence: Optional[float]
    stream_epoch: int                # Stream session epoch
    pts: int                         # Presentation timestamp
    time_base: TimeBase              # num, den
    capture_timestamp: float         # Wall-clock at capture
    processing_timestamp: float      # Wall-clock at AI complete
    model_version: str               # Model versions
    enrollment_version: str          # Enrollment DB version
    provenance: str                  # 'pipeline_engine_v1'
    schema_version: str              # '1.0'
```

**Response:** `CrossingEventResponse`
```python
{
    "success": bool,
    "event_id": str,
    "source_resolution_id": Optional[str],
    "status": "accepted",
    "message": "Event queued for resolution"
}
```

**Processing Flow (lines 429-489):**
1. Validate schema
2. Convert to `RawInOutEvent` (Phase 23)
3. Submit to `RepeatedInOutResolver` (Phase 24)
4. Return `source_resolution_id` immediately
5. Async: Resolver → `AttendanceRecord` (Phase 25)

---

### 2.2 Health Endpoint: `POST /api/v1/health/ai-worker`

**Authentication:** `verify_ai_worker_key`

**Already implemented and tested** (Gate A)

---

### 2.3 Control Endpoints

**Already implemented and tested** (Gate A)
- `POST /api/v1/ai/control/{action}` (Admin)
- `GET /api/v1/ai/control/pending` (Worker)
- `POST /api/v1/ai/control/{action}/response` (Worker)
- `GET /api/v1/ai/control/history` (Admin)

---

### 2.4 Enrollment Reload: `POST /api/v1/enrollment/reload`

**Authentication:** `verify_admin_key`

**Worker notifies backend** when enrollment database changes.

---

## 3. Worker Event Delivery (Implemented in Gate A)

### 3.1 EventDeliveryClient (`pipeline_engine/integration/event_client.py`)

**Features:**
- Async queue with bounded size (default 1000)
- Exponential backoff retry (max 3, base 1s, max 30s)
- Idempotency via delivered event_id tracking
- Stats: pending, delivered, failed, queue_depth
- Health check: `is_healthy()` (queue not near capacity)

### 3.2 Event Callback Registration

```python
def _register_event_callback(self):
    def on_attendance_event(event: CrossingEvent):
        request = self._convert_crossing_event(event)
        asyncio.create_task(self.event_client.submit_event(request))
    
    for camera_id in self.engine.camera_manager.get_camera_list():
        camera = self.engine.camera_manager._cameras[camera_id]
        camera["attendance"].register_event_callback(on_attendance_event)
```

### 3.3 CrossingEvent → CrossingEventRequest Conversion

```python
def _convert_crossing_event(self, event: CrossingEvent) -> CrossingEventRequest:
    # Maps all fields from PipelineEngine CrossingEvent to API schema
    # Adds: stream_epoch, pts, time_base, capture/processing timestamps
    # Adds: model_version, enrollment_version, provenance, schema_version
```

---

## 4. End-to-End Flow

```
Camera RTSP
    ↓
RTSPSource → NVDECDecoder → GPUFrame
    ↓
SCRFD → Face Alignment → ArcFace → Embedding
    ↓
YOLO Person Detection
    ↓
Tracker (geometry + face association + identity)
    ↓
AttendanceEngine → CrossingEngine → CrossingEvent
    ↓
Worker Callback (on_attendance_event)
    ↓
Convert to CrossingEventRequest
    ↓
EventDeliveryClient.submit_event()
    ↓
Queue → Delivery Loop → POST /api/v1/attendance/events
    ↓
Backend: validate → RawInOutEvent → Resolver → AttendanceRecord
    ↓
Response: {success, source_resolution_id}
    ↓
EventDeliveryClient marks delivered (idempotency)
```

---

## 5. Idempotency Strategy

### 5.1 Worker Side
- Track delivered `event_id` in memory (`_delivered_event_ids`)
- Skip submission if already delivered
- Queue-level dedup before submission

### 5.2 Backend Side
- `source_resolution_id` has UNIQUE constraint in `attendance_records`
- Deterministic `attendance_record_id` generated from `source_resolution_id`
- Duplicate submissions return existing record (idempotent insert)

### 5.3 PipelineEngine Side
- `CrossingEvent.event_id` generated deterministically:
  `CE-{track_id}-{frame_index}-{timestamp_ms}`
- Same track crossing same line same frame = same event_id

---

## 6. Error Handling & Classification

### 6.1 Worker Delivery Errors

| Error Type | Classification | Retry |
|------------|----------------|-------|
| 400 Bad Request | Validation error | NO (log, drop) |
| 401 Unauthorized | Auth failure | NO (alert) |
| 409 Conflict | Duplicate (idempotent) | YES (treat as success) |
| 5xx Server Error | Backend error | YES (retry) |
| Timeout | Network | YES (retry) |
| Connection Error | Network | YES (retry) |

### 6.2 Backend Processing Errors

- Validation errors → 400 with detail
- Resolver errors → 500 with detail
- Database errors → 500

---

## 7. Gate E Tests

| Test | Description | Implementation |
|------|-------------|----------------|
| T1 | Isolated test frame → valid detection | Requires camera stream |
| T2 | Detection → track association | Tracker implemented |
| T3 | Controlled crossing → event | CrossingEngine implemented |
| T4 | Worker submits event | EventDeliveryClient implemented |
| T5 | Backend accepts event | Endpoint implemented |
| T6 | Phase 22-25 processes event | Resolver + Storage implemented |
| T7 | AttendanceRecord retrieved | Storage.query() implemented |
| T8 | Provenance traceable | event_id → source_resolution_id → attendance_record_id |

---

## 8. Integration Test Scenario

### Prerequisites
1. MediaMTX running with camera streams
2. Legacy Backend API running (`python -m app.main`)
3. API keys configured in environment
4. Enrollment database populated

### Test Steps
1. Start Worker (`python scripts/run_worker.py`)
2. Verify Worker reaches RUNNING state
3. Verify health heartbeats in Backend (`GET /api/v1/health/ai-worker/{worker_id}`)
4. Person crosses line in camera view
5. Verify CrossingEvent generated (Worker logs)
6. Verify event delivered (EventDeliveryClient stats)
7. Verify Backend accepted (Backend logs)
8. Query AttendanceRecord:
   ```bash
   curl -H "X-API-Key: $ADMIN_API_KEY" \
     "http://localhost:19146/api/v1/attendance/records?camera_id=cam1"
   ```
9. Verify provenance chain: event_id → source_resolution_id → attendance_record_id

---

## 9. Gate E Verdict

**BACKEND ENDPOINTS COMPLETE** — All required endpoints implemented and tested in Phase 0.2.6.

**WORKER DELIVERY IMPLEMENTED** — EventDeliveryClient with queue, retry, idempotency.

**INTEGRATION READY** — Callback registration connects AttendanceEngine to Worker delivery.

**BLOCKED BY:** Camera streams and running Backend for end-to-end validation.

**Ready for Gate F** — Video & AI Metadata Synchronization