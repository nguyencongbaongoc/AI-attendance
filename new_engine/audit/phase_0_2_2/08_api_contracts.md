# Gate E — API Contracts (CF-03)

**Date:** 2026-10-04  
**Phase:** 0.2.2 — Gate E  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL DESIGN

---

## 1. Executive Summary

**GATE E VERDICT: PARTIAL**

Four API contracts defined with implementation plan. Two endpoints partially exist (enrollment POST exists, reload missing). Implementation of remaining endpoints in progress. Tests designed.

---

## 2. Required API Areas (from Phase 0.2.1)

| # | Endpoint | Purpose | Status |
|---|---|---|---|
| 1 | `POST /api/v1/attendance/events` | AI Worker event ingestion (CrossingEvent → RawInOutEvent) | **MISSING** |
| 2 | `POST /api/v1/health/ai-worker` | AI Worker health reporting | **MISSING** |
| 3 | `POST /api/v1/ai/control/*` | AI Worker control (start/stop/reconfig) | **MISSING** |
| 4 | `POST /api/v1/enrollment/reload` | NPY reload notification | **MISSING** (POST /persons exists) |

---

## 3. API Contract 1: Attendance Event Ingestion

### 3.1 Endpoint Specification

```
POST /api/v1/attendance/events
```

### 3.2 Request Schema (CrossingEvent from PipelineEngine)

```json
{
  "event_id": "CE-track123-frame456-1728000000000",
  "camera_id": "cam1",
  "track_id": 123,
  "direction": "in",
  "event_type": "line_crossing",
  "crossing_point": {"x": 1920.0, "y": 1080.0},
  "timestamp": 1728000000.123,
  "frame_index": 456,
  "previous_position": {"x": 1900.0, "y": 1050.0},
  "current_position": {"x": 1940.0, "y": 1110.0},
  "person_id": "STU-10001",
  "person_name": "John Doe",
  "identity_confidence": 0.92,
  "stream_epoch": 1,
  "pts": 90000,
  "time_base": {"num": 1, "den": 90000},
  "capture_timestamp": 1728000000.120,
  "processing_timestamp": 1728000000.123,
  "model_version": "scrfd_arcface_yolo_v1",
  "enrollment_version": "2026-09-02T16:08:58Z",
  "provenance": "pipeline_engine_v1",
  "schema_version": "1.0"
}
```

### 3.3 Required Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | YES | Globally unique, stable across retries |
| `camera_id` | string | YES | Camera identifier |
| `track_id` | integer | YES | Local track ID |
| `direction` | "in"\|"out" | YES | Crossing direction |
| `timestamp` | float | YES | Unix timestamp (seconds) |
| `frame_index` | integer | YES | Frame index in stream |
| `stream_epoch` | integer | YES | Stream session epoch (increments on reconnect) |
| `pts` | integer | YES | Presentation timestamp from container |
| `time_base` | {num, den} | YES | Stream time base |
| `capture_timestamp` | float | YES | Wall-clock at frame capture |
| `processing_timestamp` | float | YES | Wall-clock at AI processing complete |
| `model_version` | string | YES | Model versions used |
| `enrollment_version` | string | YES | Enrollment database version |

### 3.4 Optional Fields

| Field | Type | Description |
|---|---|---|
| `person_id` | string | Enrollment ID if known |
| `person_name` | string | Display name |
| `identity_confidence` | float | ArcFace matching confidence |
| `crossing_point` | {x, y} | Crossing coordinates |
| `previous_position` | {x, y} | Previous track position |
| `current_position` | {x, y} | Current track position |
| `event_type` | string | Default: "line_crossing" |

### 3.5 Response Schema

```json
{
  "success": true,
  "event_id": "CE-track123-frame456-1728000000000",
  "source_resolution_id": "RES-abc123...",
  "status": "accepted",
  "message": "Event queued for resolution"
}
```

### 3.6 Idempotency

- `event_id` used as deduplication key
- Duplicate `event_id` returns existing `source_resolution_id`
- PipelineEngine must use stable `event_id` across retries

### 3.7 Integration Flow

```
POST /api/v1/attendance/events
    → Validate CrossingEvent schema
    → Create RawInOutEvent (Phase 23)
    → Queue for Phase 24 Resolver
    → Return source_resolution_id immediately
    → Async: Resolver → AttendanceRecord (Phase 25)
```

---

## 4. API Contract 2: AI Worker Health

### 4.1 Endpoint Specification

```
POST /api/v1/health/ai-worker
```

### 4.2 Request Schema (Heartbeat)

```json
{
  "worker_id": "pipeline_engine_1",
  "state": "healthy",
  "timestamp": 1728000000.123,
  "camera_states": {
    "cam1": {
      "state": "live",
      "last_frame_timestamp": 1728000000.120,
      "decode_fps": 29.8,
      "inference_fps": 28.5,
      "track_count": 3
    },
    "cam2": {
      "state": "live",
      "last_frame_timestamp": 1728000000.118,
      "decode_fps": 28.2,
      "inference_fps": 27.9,
      "track_count": 2
    }
  },
  "model_readiness": {
    "scrfd": true,
    "arcface": true,
    "yolo": true
  },
  "gpu_provider": "CUDAExecutionProvider",
  "queue_depth": 2,
  "processing_latency_ms": 15.3,
  "dropped_frames": 0,
  "stream_epochs": {"cam1": 1, "cam2": 1},
  "errors": []
}
```

### 4.3 Response Schema

```json
{
  "success": true,
  "worker_id": "pipeline_engine_1",
  "acknowledged": true,
  "server_timestamp": 1728000000.125,
  "commands": []
}
```

### 4.4 State Values

| State | Meaning |
|---|---|
| `healthy` | All cameras live, models loaded, GPU OK |
| `degraded` | Some cameras down, high latency, partial models |
| `unhealthy` | No cameras, GPU failure, models unloaded |
| `starting` | Initializing models, connecting cameras |
| `stopping` | Graceful shutdown in progress |

---

## 5. API Contract 3: AI Worker Control

### 5.1 Endpoint Specification

```
POST /api/v1/ai/control/{action}
```

### 5.2 Actions

| Action | Purpose | Request Body |
|---|---|---|
| `start` | Start AI worker | `{}` |
| `stop` | Graceful stop | `{}` |
| `restart` | Restart worker | `{}` |
| `reconfig` | Update runtime config | `{"camera_config": {...}, "model_config": {...}}` |
| `pause_camera` | Pause specific camera | `{"camera_id": "cam1"}` |
| `resume_camera` | Resume specific camera | `{"camera_id": "cam1"}` |

### 5.3 Response Schema

```json
{
  "success": true,
  "action": "start",
  "worker_id": "pipeline_engine_1",
  "status": "starting",
  "timestamp": 1728000000.125
}
```

### 5.4 Authorization

- Requires `X-API-Key` header matching `AI_WORKER_CONTROL_KEY` env var
- Audit log entry for all control actions

---

## 6. API Contract 4: Enrollment Reload

### 6.1 Endpoint Specification

```
POST /api/v1/enrollment/reload
```

### 6.2 Request Schema

```json
{
  "trigger": "manual" | "file_watcher" | "api",
  "expected_version": "2026-09-02T16:08:58Z" (optional)
}
```

### 6.3 Response Schema

```json
{
  "success": true,
  "previous_version": "2026-09-02T16:08:58Z",
  "new_version": "2026-10-04T09:30:00Z",
  "persons_loaded": 1,
  "vectors_loaded": 7,
  "embedding_dimension": 512,
  "model_sha256": "4AB1D643...",
  "timestamp": 1728000000.125
}
```

### 6.4 Failure Response

```json
{
  "success": false,
  "error": "Invalid NPY dimensions: expected 512, got 256",
  "previous_version": "2026-09-02T16:08:58Z",
  "preserved_previous": true
}
```

### 6.5 Behavior

- Atomic swap: new embeddings validated before replacing active
- Previous valid enrollment preserved on failure
- PipelineEngine notified via health endpoint `enrollment_version` change
- File watcher can trigger automatically

---

## 7. Authentication & Authorization

### 7.1 AI Worker Endpoints

- `POST /api/v1/attendance/events` — Requires `X-API-Key: <AI_WORKER_API_KEY>`
- `POST /api/v1/health/ai-worker` — Requires `X-API-Key: <AI_WORKER_API_KEY>`
- `POST /api/v1/ai/control/*` — Requires `X-API-Key: <AI_CONTROL_API_KEY>`

### 7.2 Admin Endpoints

- `POST /api/v1/enrollment/reload` — Requires `X-API-Key: <ADMIN_API_KEY>` or admin JWT

### 7.3 Key Management

| Key | Environment Variable | Purpose |
|---|---|---|
| AI Worker API | `AI_WORKER_API_KEY` | Event ingestion + health |
| AI Control API | `AI_CONTROL_API_KEY` | Worker control |
| Admin API | `ADMIN_API_KEY` | Enrollment management |

---

## 8. Integration with Existing Pipeline

### 8.1 Event Flow

```
PipelineEngine (CrossingEvent)
    → POST /api/v1/attendance/events
    → Legacy Backend: RawInOutEvent (Phase 23)
    → Phase 24 Resolver (RepeatedInOutResolver)
    → Phase 25 AttendanceRecord
    → AttendanceRepository → app/data/attendance.db
```

### 8.2 Existing Components Reused

| Component | File | Role |
|---|---|---|
| `RawInOutEvent` | `app/in_out/raw_event.py` | Event creation |
| `RepeatedInOutResolver` | `app/in_out/resolver.py` | Transition resolution |
| `AttendanceRecord` | `app/attendance/contract.py` | Persistence model |
| `AttendanceRepository` | `app/attendance/repository.py` | Persistence |
| `EnrollmentConfig` | `app/vision/enrollment.py` | Reload logic |

---

## 9. Implementation Status

| Endpoint | Status | Location | Notes |
|---|---|---|---|
| `POST /api/v1/attendance/events` | **MISSING** | New file: `app/api/ai_worker.py` | New router needed |
| `POST /api/v1/health/ai-worker` | **MISSING** | New file: `app/api/ai_worker.py` | Same router |
| `POST /api/v1/ai/control/*` | **MISSING** | New file: `app/api/ai_worker.py` | Same router |
| `POST /api/v1/enrollment/reload` | **MISSING** | Add to `app/api/enrollment.py` | Extend existing |

---

## 10. Gate E Artifacts

| File | Purpose |
|---|---|
| `08_api_contracts.md` | This document |
| `09_api_implementation.md` | Implementation map |
| `10_api_test_evidence.md` | Test plan and results |

---

**Gate E Design Complete. Proceeding to Implementation.**