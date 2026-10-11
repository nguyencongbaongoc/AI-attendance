# Gate C — Control Contract Final

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Gate C  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL CONTRACT

---

## 1. Executive Summary

This document defines the final, authoritative control contract between Legacy Backend (admin/UI) and PipelineEngine (AI Worker). It consolidates the schema from Phase 0.2.3 (`08_control_api_contract.md`) and adds the required pending/response endpoints, idempotency, and lifecycle management.

**Endpoints:**
- `GET /api/v1/ai/control/pending` — Poll pending control requests
- `POST /api/v1/ai/control/{action}/response` — Submit control response
- `POST /api/v1/ai/control/{action}` — Submit control request (Legacy Backend → PipelineEngine)

**Authentication:** `X-API-Key: AI_CONTROL_API_KEY` (PipelineEngine), `X-API-Key: ADMIN_API_KEY` (Legacy Backend admin)

**Implementation Files:**
- `app/api/ai_worker.py` — Legacy Backend control endpoints
- `pipeline_engine/integration/control_client.py` — PipelineEngine control server

---

## 2. Control Request/Response Lifecycle

```
Admin/UI → Legacy Backend (POST /ai/control/{action}) 
    → Pending Queue (Legacy Backend)
    → PipelineEngine polls GET /ai/control/pending
    → PipelineEngine executes action
    → PipelineEngine responds POST /ai/control/{action}/response
    → Legacy Backend updates request status
    → Admin/UI sees completion
```

---

## 2. Supported Actions

| Action | Target | Description | Idempotent |
|---|---|---|---|
| `GET_STATUS` | worker | Get worker status | YES |
| `START_WORKER` | worker | Start PipelineEngine | NO |
| `STOP_WORKER` | worker | Graceful shutdown | NO |
| `ENABLE_CAMERA` | camera | Enable camera stream | YES |
| `DISABLE_CAMERA` | camera | Disable camera stream | YES |

**Note:** `RESTART_WORKER` = `STOP_WORKER` + `START_WORKER` (two separate actions). `RECONFIG` requires worker restart and is not included in Phase 0.2.4.

---

## 3. Request/Response Schemas

### 3.1 Control Request (Legacy Backend → PipelineEngine)

```json
{
  "request_id": "uuid-v4",
  "action": "START_WORKER|STOP_WORKER|ENABLE_CAMERA|DISABLE_CAMERA|GET_STATUS",
  "target": "worker|camera",
  "target_id": "pipeline_engine_1|cam1|cam2",
  "parameters": {},
  "idempotency_key": "uuid-v4",
  "created_at": 1728000000.123,
  "expires_at": 1728000300.123
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `request_id` | string (UUID) | YES | Unique request identifier |
| `action` | enum | YES | One of supported actions |
| `target` | enum | YES | `worker` or `camera` |
| `target_id` | string | YES | Worker ID or camera ID |
| `parameters` | object | NO | Action-specific parameters |
| `idempotency_key` | string (UUID) | YES | Deduplication key |
| `created_at` | float | YES | Unix timestamp (UTC) |
| `expires_at` | float | YES | Request expiration (default +5 min) |

---

### 3.2 Control Response (PipelineEngine → Legacy Backend)

```json
{
  "request_id": "uuid-v4",
  "action": "START_WORKER",
  "worker_id": "pipeline_engine_1",
  "status": "ACCEPTED|RUNNING|COMPLETED|FAILED|REJECTED|EXPIRED",
  "timestamp": 1728000000.125,
  "details": {
    "previous_state": "STOPPED",
    "new_state": "RUNNING"
  },
  "error": null
}
```

| Field | Type | Description |
|---|---|---|
| `request_id` | string | Echo of request ID |
| `action` | string | Echo of action |
| `worker_id` | string | Target worker ID |
| `status` | enum | `ACCEPTED`, `RUNNING`, `COMPLETED`, `FAILED`, `REJECTED`, `EXPIRED` |
| `timestamp` | float | Server Unix timestamp |
| `details` | object | Action-specific details |
| `error` | string | Error message if failed |

---

### 3.3 Pending Requests Response (GET /ai/control/pending)

```json
{
  "worker_id": "pipeline_engine_1",
  "requests": [
    {
      "request_id": "uuid-v4",
      "action": "START_WORKER",
      "target": "worker",
      "target_id": "pipeline_engine_1",
      "parameters": {},
      "idempotency_key": "uuid-v4",
      "created_at": 1728000000.123,
      "expires_at": 1728000300.123
    }
  ]
}
```

---

## 3. Action Specifications

### 3.1 GET_STATUS

| Aspect | Detail |
|---|---|
| **Target** | worker |
| **Parameters** | `{}` |
| **Response Details** | `{ "state": "RUNNING", "uptime_seconds": 123.4, "cameras": {...} }` |
| **Idempotent** | YES |
| **Timeout** | 5s |

### 3.2 START_WORKER

| Aspect | Detail |
|---|---|
| **Target** | worker |
| **Parameters** | `{ "graceful": true, "timeout": 30 }` |
| **Response Details** | `{ "previous_state": "STOPPED", "new_state": "RUNNING" }` |
| **Idempotent** | NO (but duplicate with same key returns ACCEPTED) |
| **Timeout** | 30s |

### 3.3 STOP_WORKER

| Aspect | Detail |
|---|---|
| **Target** | worker |
| **Parameters** | `{ "graceful": true, "timeout": 30 }` |
| **Response Details** | `{ "previous_state": "RUNNING", "graceful": true }` |
| **Idempotent** | YES (already stopped = COMPLETED) |
| **Timeout** | 30s |

### 3.4 ENABLE_CAMERA / DISABLE_CAMERA

| Aspect | Detail |
|---|---|
| **Target** | camera |
| **Parameters** | `{ "camera_id": "cam1" }` (or `target_id`) |
| **Response Details** | `{ "camera_id": "cam1", "previous_state": "RUNNING", "new_state": "STOPPED" }` |
| **Idempotent** | YES |
| **Timeout** | 10s |

---

## 4. Pending Endpoint

### 4.1 Endpoint Specification

**GET /api/v1/ai/control/pending**

| Aspect | Detail |
|---|---|
| **Method** | GET |
| **Path** | `/api/v1/ai/control/pending` |
| **Query Params** | `worker_id` (required), `limit` (optional, default 50) |
| **Auth** | `X-API-Key: AI_CONTROL_API_KEY` |
| **Response** | `{ "worker_id": "...", "requests": [...] }` |

### 4.2 Query Parameters

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `worker_id` | string | YES | — | Worker identifier |
| `limit` | int | NO | 50 | Max requests to return |
| `since` | float | NO | — | Only requests after timestamp |

### 4.3 Response

```json
{
  "worker_id": "pipeline_engine_1",
  "requests": [
    {
      "request_id": "uuid",
      "action": "START_WORKER",
      "target": "worker",
      "target_id": "pipeline_engine_1",
      "parameters": {},
      "idempotency_key": "uuid",
      "created_at": 1728000000.123,
      "expires_at": 1728000300.123
    }
  ]
}
```

---

## 5. Response Endpoint

### 5.1 Endpoint Specification

**POST /api/v1/ai/control/{action}/response**

| Aspect | Detail |
|---|---|
| **Method** | POST |
| **Path** | `/api/v1/ai/control/{action}/response` |
| **Path Param** | `action` (one of: START_WORKER, STOP_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS) |
| **Auth** | `X-API-Key: AI_CONTROL_API_KEY` |
| **Body** | ControlResponse schema |

### 5.2 Request Body

```json
{
  "request_id": "uuid",
  "action": "START_WORKER",
  "worker_id": "pipeline_engine_1",
  "status": "COMPLETED",
  "timestamp": 1728000000.125,
  "details": { "previous_state": "STOPPED", "new_state": "RUNNING" },
  "error": null
}
```

### 5.3 Response

```json
{
  "success": true,
  "message": "Response recorded"
}
```

---

## 5. Control Request Submission (Legacy Backend → PipelineEngine)

### 5.1 Endpoint

**POST /api/v1/ai/control/{action}**

| Aspect | Detail |
|---|---|
| **Method** | POST |
| **Path** | `/api/v1/ai/control/{action}` |
| **Auth** | `X-API-Key: ADMIN_API_KEY` |
| **Body** | ControlRequest schema |

### 5.2 Request Body

```json
{
  "request_id": "uuid-v4",
  "action": "START_WORKER",
  "target": "worker",
  "target_id": "pipeline_engine_1",
  "parameters": { "graceful": true, "timeout": 30 },
  "idempotency_key": "uuid-v4",
  "created_at": 1728000000.123,
  "expires_at": 1728000300.123
}
```

### 5.3 Response

```json
{
  "success": true,
  "request_id": "uuid-v4",
  "status": "PENDING",
  "message": "Control request queued"
}
```

---

## 6. Idempotency

### 6.1 Idempotency Key

- Every control request MUST include `idempotency_key` (UUID v4)
- Legacy Backend stores `idempotency_key → response` mapping
- PipelineEngine tracks processed `idempotency_key` set
- Duplicate key → return original response immediately
- Key expires after 24 hours

### 6.2 Idempotency Behavior

| Scenario | Behavior |
|---|---|
| First request | Process, store key→response, return response |
| Duplicate key | Return stored response immediately |
| Different key, same action | Process as new request |
| Expired key (>24h) | Process as new request |

---

## 6. Request Expiration

- Default TTL: 5 minutes (`expires_at = created_at + 300`)
- Expired requests are automatically removed from pending queue
- PipelineEngine rejects expired requests with `EXPIRED` status

---

## 7. Request/Response Status Codes

| Status | Meaning | When |
|---|---|---|
| `PENDING` | Request queued, not yet polled | After Legacy Backend accepts request |
| `ACCEPTED` | PipelineEngine accepted request | After validation, before execution |
| `RUNNING` | Operation in progress | Long-running operations |
| `COMPLETED` | Operation completed successfully | After successful execution |
| `FAILED` | Operation failed | Execution error |
| `REJECTED` | Request invalid or not allowed | Invalid params, unauthorized |
| `EXPIRED` | Request expired before execution | TTL exceeded |

---

## 8. Error Responses

| HTTP Code | Error | Details |
|---|---|---|
| 400 | Invalid action | `"Invalid action 'xyz'. Valid: ..."` |
| 400 | Invalid target | `"Invalid target 'xyz'. Valid: worker, camera"` |
| 400 | Missing camera_id | `"camera_id required for camera actions"` |
| 401 | Invalid API key | `"Invalid AI Control API key"` |
| 404 | Worker not found | `"Worker pipeline_engine_2 not found"` |
| 404 | Camera not found | `"Camera cam3 not found"` |
| 409 | Conflict | `"Worker already running"` |
| 409 | Expired request | `"Request expired"` |
| 409 | Duplicate idempotency key | Handled silently (returns stored response) |
| 500 | Internal error | `{"error": "Internal server error"}` |

---

## 9. Audit Logging

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

## 10. Contract Version

**Version:** 1.0  
**Date:** 2026-10-04  
**Phase:** 0.2.4 Gate C  

**Changes from Phase 0.2.3:**
- Added `GET /ai/control/pending` endpoint spec
- Added `POST /ai/control/{action}/response` endpoint spec
- Defined explicit action allowlist (5 actions)
- Added idempotency key requirement
- Defined request/response status lifecycle
- Defined audit logging requirements
- Defined explicit action specifications with timeouts

---

**Gate C Contract: COMPLETE** — Ready for implementation.