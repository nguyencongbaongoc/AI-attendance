# Gate A — Health Contract Final

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Gate A  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL CONTRACT

---

## 1. Executive Summary

This document defines the final, authoritative health contract between PipelineEngine (AI Worker) and Legacy Backend. It consolidates the schema from Phase 0.2.3 (`05_health_api_contract.md`) and extends it with the required state machine, validation rules, and backend state management requirements.

**Endpoint:** `POST /api/v1/health/ai-worker`  
**Authentication:** `X-API-Key: AI_WORKER_API_KEY`  
**Implementation File:** `app/api/ai_worker.py` (Legacy Backend)  
**Client:** `pipeline_engine/integration/health_client.py` (PipelineEngine)

---

## 2. Health State Machine

### 2.1 Worker States

| State | Enum Value | Meaning | READY? |
|---|---|---|---|
| STARTING | `starting` | Worker process started, initialization incomplete | NO |
| INITIALIZING | `initializing` | Models/dependencies loading | NO |
| READY | `ready` | All required components operational | **YES** |
| DEGRADED | `degraded` | Worker alive but capabilities impaired | NO |
| FAILED | `failed` | Worker cannot perform required function | NO |
| STOPPING | `stopping` | Graceful shutdown in progress | NO |
| STOPPED | `stopped` | Worker no longer operational | NO |

**Critical Rule:** A process heartbeat alone must NEVER imply READY. READY requires explicit verification of all required capabilities.

### 2.2 Camera States

| State | Meaning |
|---|---|
| `live` | Stream connected, frames arriving, inference active |
| `connecting` | Establishing RTSP/RTMP connection |
| `disconnected` | Stream lost, reconnection attempts ongoing |
| `error` | Persistent failure (codec, auth, network) |

### 2.3 Model Readiness

Per-model boolean flags:
- `scrfd`: SCRFD face detector ready
- `arcface`: ArcFace recognition ready
- `yolo`: YOLO person detector ready

---

## 3. Health Payload Schema

### 3.1 Request: `AIWorkerHealthRequest` (PipelineEngine → Legacy Backend)

```json
{
  "worker_id": "string",
  "worker_version": "string",
  "state": "starting|initializing|ready|degraded|failed|stopping|stopped",
  "timestamp": 1728000000.123,
  "sequence_number": 1,
  "camera_states": {
    "cam1": {
      "state": "live|connecting|disconnected|error",
      "stream_epoch": 1,
      "stream_connected": true,
      "last_frame_timestamp": 1728000000.120,
      "last_inference_timestamp": 1728000000.123,
      "decode_fps": 29.5,
      "inference_fps": 28.3,
      "track_count": 3
    }
  },
  "model_readiness": {
    "scrfd": true,
    "arcface": true,
    "yolo": true
  },
  "inference_provider": "CUDAExecutionProvider",
  "queue_depth": 2,
  "processing_latency_ms": 15.3,
  "dropped_frame_count": 0,
  "event_delivery_state": "operational",
  "error_code": null,
  "error_message": null,
  "stream_epochs": {
    "cam1": 1,
    "cam2": 1
  }
}
```

### 3.2 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `worker_id` | string | YES | Unique worker identifier |
| `worker_version` | string | YES | Worker software version |
| `state` | enum | YES | Worker state enum |
| `timestamp` | float | YES | Unix epoch seconds (UTC) |
| `sequence_number` | int | YES | Monotonically increasing per worker |
| `camera_states` | dict | YES | Per-camera operational state |
| `camera_states[cam].state` | enum | YES | Camera state enum |
| `camera_states[cam].stream_epoch` | int | YES | Stream session counter |
| `camera_states[cam].stream_connected` | bool | YES | Current connection status |
| `camera_states[cam].last_frame_timestamp` | float | YES | Unix epoch of last received frame |
| `camera_states[cam].last_inference_timestamp` | float | YES | Unix epoch of last completed inference |
| `camera_states[cam].decode_fps` | float | YES | Current decode frame rate |
| `camera_states[cam].inference_fps` | float | YES | Current inference frame rate |
| `camera_states[cam].track_count` | int | YES | Active tracks for this camera |
| `model_readiness` | object | YES | Model initialization status |
| `inference_provider` | string | NO | ONNX Runtime provider (default: `CUDAExecutionProvider`) |
| `queue_depth` | int | NO | Pending events in delivery queue |
| `processing_latency_ms` | float | NO | End-to-end processing latency |
| `dropped_frame_count` | int | NO | Frames dropped due to backpressure |
| `event_delivery_state` | string | NO | `operational`, `degraded`, `unavailable` |
| `error_code` | string | NO | Standardized error code |
| `error_message` | string | NO | Human-readable error description |
| `stream_epochs` | dict | NO | Per-camera stream session counters |

### 3.3 Response: `AIWorkerHealthResponse`

```json
{
  "success": true,
  "worker_id": "pipeline_engine_1",
  "acknowledged": true,
  "server_timestamp": 1728000000.125,
  "sequence_number": 1,
  "commands": [],
  "stale_threshold_seconds": 30.0
}
```

| Field | Type | Description |
|---|---|---|
| `success` | bool | Always true for valid requests |
| `worker_id` | string | Echo of request worker_id |
| `acknowledged` | bool | Server received and processed |
| `server_timestamp` | float | Server Unix timestamp (UTC) |
| `sequence_number` | int | Echo of request sequence |
| `commands` | array | Optional control commands for worker |
| `stale_threshold_seconds` | float | Heartbeat timeout threshold |

---

## 4. Validation Rules

### 4.1 Payload Validation

| Check | Rule |
|---|---|
| Worker identity | Must match authenticated worker |
| State enum | Must be one of 7 valid states |
| Timestamp format | Unix epoch float (UTC) |
| Sequence number | Positive integer, monotonic per worker |
| Camera identifier | Must match configured cameras |
| Stream epoch | Non-negative integer |
| Numeric ranges | Non-negative for counts/FPS/latency |
| Payload size | Max 64 KB |
| Required vs optional | Enforce required fields |

### 4.2 State Transition Validation

| From → To | Allowed? | Condition |
|---|---|---|
| STARTING → INITIALIZING | YES | Models loading |
| INITIALIZING → READY | YES | All components ready |
| READY → DEGRADED | YES | Capability impaired |
| DEGRADED → READY | YES | Capability restored |
| * → FAILED | YES | Critical failure |
| * → STOPPING | YES | Shutdown initiated |
| STOPPING → STOPPED | YES | Shutdown complete |
| READY → STARTING | NO | Invalid regression |
| FAILED → READY | NO | Requires restart |
| STOPPED → * | NO | Terminal state |

---

## 4. Health Validation Endpoint

**Endpoint:** `POST /api/v1/health/ai-worker/validate` (optional helper)

Validates a health payload without updating state. Returns validation errors or success.

---

## 5. Backend State Management (Gate A Continuation)

See `03_health_backend_state_management.md` for backend state machine, stale detection, and persistence requirements.

---

## 6. Contract Verification

| Aspect | Status | Evidence |
|---|---|---|
| Request schema | ✅ DEFINED | `AIWorkerHealthRequest` in `app/api/ai_worker.py` |
| Response schema | ✅ DEFINED | `AIWorkerHealthResponse` in `app/api/ai_worker.py` |
| Route registration | ✅ REGISTERED | `/api/v1/health/ai-worker` POST |
| Authentication | ✅ IMPLEMENTED | `verify_ai_worker_key` dependency |
| State machine | ✅ DOCUMENTED | This document |
| Validation rules | ✅ DOCUMENTED | This document |

---

## 7. Contract Version

**Version:** 1.0  
**Date:** 2026-10-04  
**Phase:** 0.2.4 Gate A  

**Changes from Phase 0.2.3:**
- Added explicit state machine with 7 states
- Added `sequence_number` for duplicate/out-of-order detection
- Added `stream_epoch` to camera states
- Added `event_delivery_state` field
- Added `error_code` / `error_message` fields
- Defined explicit state transition rules
- Added `sequence_number` echo in response
- Added `stale_threshold_seconds` in response

---

**Gate A Contract: COMPLETE** — Proceeding to Gate A Backend State Management.