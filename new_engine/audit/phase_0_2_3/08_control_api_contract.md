# Gate C — Control API Contract

**Date:** 2026-10-04  
**Phase:** 0.2.3 — Gate C  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL CONTRACT

---

## 1. Executive Summary

This document defines the formal control API contract between Legacy Backend and PipelineEngine. The contract is implemented at:

- **Endpoint:** `POST /api/v1/ai/control/{action}`
- **Authentication:** `X-API-Key: AI_CONTROL_API_KEY`
- **File:** `app/api/ai_worker.py` (lines 155-280)

---

## 2. Supported Actions

| Action | Description | Request Body | Response |
|---|---|---|---|
| `start` | Start AI worker | `{}` | `{success, action, worker_id, status, timestamp}` |
| `stop` | Graceful stop | `{}` | `{success, action, worker_id, status, timestamp}` |
| `restart` | Restart worker | `{}` | `{success, action, worker_id, status, timestamp}` |
| `reconfig` | Update runtime config | `{"camera_config": {...}, "model_config": {...}}` | `{success, action, worker_id, status, timestamp}` |
| `pause_camera` | Pause specific camera | `{"camera_id": "cam1"}` | `{success, action, worker_id, status, timestamp}` |
| `resume_camera` | Resume specific camera | `{"camera_id": "cam1"}` | `{success, action, worker_id, status, timestamp}` |

---

## 3. Request Schema

### 3.1 Base Request

```json
{
  "request_id": "uuid-v4",
  "action": "start|stop|restart|reconfig|pause_camera|resume_camera",
  "target": "worker|camera",
  "target_id": "pipeline_engine_1|cam1|cam2",
  "parameters": {},
  "idempotency_key": "uuid-v4"
}
```

### 3.2 Action-Specific Parameters

| Action | Target | Parameters |
|---|---|---|
| `start` | worker | `{}` |
| `stop` | worker | `{"graceful": true, "timeout": 30}` |
| `restart` | worker | `{"graceful": true, "timeout": 30}` |
| `reconfig` | worker | `{"camera_config": {...}, "model_config": {...}}` |
| `pause_camera` | camera | `{"camera_id": "cam1"}` |
| `resume_camera` | camera | `{"camera_id": "cam1"}` |

---

## 4. Response Schema

```json
{
  "success": true,
  "action": "start",
  "worker_id": "pipeline_engine_1",
  "status": "accepted",
  "request_id": "uuid-v4",
  "timestamp": 1728000000.125,
  "details": {}
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `success` | bool | Overall success |
| `action` | string | Echo of requested action |
| `worker_id` | string | Target worker identifier |
| `status` | enum | `accepted`, `completed`, `failed` |
| `request_id` | string | Echo of request ID |
| `timestamp` | float | Server Unix timestamp |
| `details` | object | Action-specific details |

### Status Values

| Status | Meaning |
|---|---|
| `accepted` | Request validated and queued |
| `completed` | Action fully executed |
| `failed` | Action failed (details in `details.error`) |

---

## 5. Idempotency

- **`idempotency_key`** (UUID v4) provided by caller
- Duplicate requests with same key return original response
- Key expires after 24 hours
- Legacy Backend stores key → response mapping

---

## 6. Authentication

- **Header:** `X-API-Key`
- **Required Value:** `AI_CONTROL_API_KEY` environment variable
- **Verification:** Constant-time comparison
- **Failure:** HTTP 401 with "Invalid AI Control API key"

---

## 6. Authorization Matrix

| Action | Required Role | Notes |
|---|---|---|
| `start` | admin/operator | Starts worker process |
| `stop` | admin/operator | Graceful shutdown |
| `restart` | admin | Full restart |
| `reconfig` | admin | Runtime config changes |
| `pause_camera` | operator | Pauses specific camera |
| `resume_camera` | operator | Resumes specific camera |

---

## 7. Request/Response Examples

### 7.1 Start Worker
```http
POST /api/v1/ai/control/start
X-API-Key: <AI_CONTROL_API_KEY>
Content-Type: application/json

{
  "request_id": "req-123",
  "action": "start",
  "target": "worker",
  "target_id": "pipeline_engine_1",
  "parameters": {},
  "idempotency_key": "idem-abc-123"
}
```

**Response:**
```json
{
  "success": true,
  "action": "start",
  "worker_id": "pipeline_engine_1",
  "status": "accepted",
  "request_id": "req-123",
  "timestamp": 1728000000.125,
  "details": {}
}
```

### 7.2 Pause Camera
```http
POST /api/v1/ai/control/pause_camera
X-API-Key: <AI_CONTROL_API_KEY>
Content-Type: application/json

{
  "request_id": "req-456",
  "action": "pause_camera",
  "target": "camera",
  "target_id": "cam1",
  "parameters": {},
  "idempotency_key": "idem-def-456"
}
```

**Response:**
```json
{
  "success": true,
  "action": "pause_camera",
  "worker_id": "pipeline_engine_1",
  "status": "accepted",
  "request_id": "req-456",
  "timestamp": 1728000000.125,
  "details": {
    "camera_id": "cam1",
    "previous_state": "running"
  }
}
```

---

## 7. Idempotency Behavior

| Scenario | Behavior |
|---|---|
| First request | Process, store key→response, return response |
| Duplicate with same key | Return stored response immediately |
| Different key, same action | Process as new request |
| Expired key (>24h) | Process as new request |

---

## 8. Error Responses

| HTTP Code | Error | Details |
|---|---|---|
| 400 | Invalid action | `"Invalid action 'xyz'. Valid: start, stop, restart, reconfig, pause_camera, resume_camera"` |
| 400 | Invalid target | `"Invalid target 'xyz'. Valid: worker, camera"` |
| 400 | Missing camera_id | `"camera_id required for camera actions"` |
| 401 | Invalid API key | `"Invalid AI Control API key"` |
| 404 | Worker not found | `"Worker pipeline_engine_2 not found"` |
| 404 | Camera not found | `"Camera cam3 not found"` |
| 409 | Conflict | `"Worker already running"` |
| 500 | Internal error | `{"error": "Internal server error"}` |

---

## 8. Audit Logging

Every control request logs:

| Field | Value |
|---|---|
| `timestamp` | ISO 8601 |
| `request_id` | From request |
| `action` | From request |
| `target` | From request |
| `target_id` | From request |
| `caller_ip` | Client IP |
| `api_key_hash` | SHA256 of API key (first 8 chars) |
| `result` | accepted/completed/failed |
| `duration_ms` | Processing time |

---

## 8. Current Implementation Status

| Action | Status | File |
|---|---|---|
| `start` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |
| `stop` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |
| `restart` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |
| `reconfig` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |
| `pause_camera` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |
| `resume_camera` | ⚠️ SCAFFOLDED | `app/api/ai_worker.py` |

**All actions are scaffolded** — they validate input, log the action, and return "acknowledged" but don't forward to PipelineEngine.

---

## 9. Required for FUNCTIONAL Status

1. **PipelineEngine control interface** — Expose start/stop/reconfig methods
2. **Message transport** — Backend → PipelineEngine (message queue, gRPC, or HTTP)
3. **Idempotency storage** — Persist request_id → response mapping
4. **Audit logging** — Structured logging to file/database
4. **Status tracking** — Track "accepted" → "completed" → "failed" lifecycle

---

## 9. Gate C Contract Status

**CONTRACT DEFINED** — Implementation scaffolded. Requires PipelineEngine control interface and message transport.