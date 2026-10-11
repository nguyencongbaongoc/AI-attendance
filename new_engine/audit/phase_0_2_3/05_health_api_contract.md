# Gate B — Health API Contract

**Date:** 2026-10-04  
**Phase:** 0.2.3 — Gate B  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL CONTRACT

---

## 1. Executive Summary

This document defines the formal health API contract between PipelineEngine (AI Worker) and Legacy Backend. The contract is implemented at:

- **Endpoint:** `POST /api/v1/health/ai-worker`
- **Authentication:** `X-API-Key: AI_WORKER_API_KEY`
- **File:** `app/api/ai_worker.py` (lines 131-200)

---

## 2. Request Schema: `AIWorkerHealthRequest`

```json
{
  "worker_id": "string",
  "state": "healthy|degraded|unhealthy|starting|stopping",
  "timestamp": 1728000000.123,
  "camera_states": {
    "cam1": {
      "state": "live|connecting|disconnected|error",
      "last_frame_timestamp": 1728000000.120,
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
  "gpu_provider": "CUDAExecutionProvider",
  "queue_depth": 2,
  "processing_latency_ms": 15.3,
  "dropped_frames": 0,
  "stream_epochs": {
    "cam1": 1,
    "cam2": 1
  },
  "errors": []
}
```

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `worker_id` | string | YES | Unique worker identifier (e.g., `pipeline_engine_1`) |
| `state` | enum | YES | `healthy`, `degraded`, `unhealthy`, `starting`, `stopping` |
| `timestamp` | float | YES | Unix epoch seconds |
| `camera_states` | dict | YES | Per-camera operational state |
| `camera_states[cam].state` | enum | YES | `live`, `connecting`, `disconnected`, `error` |
| `camera_states[cam].last_frame_timestamp` | float | YES | Unix epoch of last received frame |
| `camera_states[cam].decode_fps` | float | YES | Current decode frame rate |
| `camera_states[cam].inference_fps` | float | YES | Current inference frame rate |
| `camera_states[cam].track_count` | int | YES | Active tracks for this camera |
| `model_readiness` | object | YES | Model initialization status |
| `model_readiness.scrfd` | bool | YES | SCRFD face detector ready |
| `model_readiness.arcface` | bool | YES | ArcFace recognition ready |
| `model_readiness.yolo` | bool | YES | YOLO person detector ready |
| `gpu_provider` | string | NO | ONNX Runtime provider (default: `CUDAExecutionProvider`) |
| `queue_depth` | int | NO | Pending events in delivery queue |
| `processing_latency_ms` | float | NO | End-to-end processing latency |
| `dropped_frames` | int | NO | Frames dropped due to backpressure |
| `stream_epochs` | dict | NO | Per-camera stream session counters |
| `errors` | array | NO | Active error messages |

---

## 2. Response Schema: `AIWorkerHealthResponse`

```json
{
  "success": true,
  "worker_id": "pipeline_engine_1",
  "acknowledged": true,
  "server_timestamp": 1728000000.125,
  "commands": []
}
```

### Field Definitions

| Field | Type | Description |
|---|---|---|
| `success` | bool | Always true for valid requests |
| `worker_id` | string | Echo of request worker_id |
| `acknowledged` | bool | Server received and processed |
| `server_timestamp` | float | Server Unix timestamp |
| `commands` | array | Optional control commands for worker |

---

## 3. State Machine Definitions

### Worker States

| State | Meaning | Required Conditions |
|---|---|---|
| `starting` | Worker process launched, initializing | Models loading, connections establishing |
| `healthy` | Fully operational | All models loaded, cameras live, inference running |
| `degraded` | Partial functionality | Some cameras down, high latency, partial models |
| `unhealthy` | Non-operational | No cameras, GPU failure, models unloaded |
| `stopping` | Graceful shutdown in progress | Draining queues, closing connections |

### Camera States

| State | Meaning |
|---|---|
| `live` | Stream connected, frames arriving, inference active |
| `connecting` | Establishing RTSP/RTMP connection |
| `disconnected` | Stream lost, reconnection attempts ongoing |
| `error` | Persistent failure (codec, auth, network) |

---

## 4. Required Health Discrimination

The contract must distinguish between:

| Level | Meaning | READY? |
|---|---|---|
| Process alive | OS process exists | **NO** |
| Worker initialized | Python process started, imports loaded | **NO** |
| Models loaded | SCRFD, ArcFace, YOLO sessions created | **PARTIAL** |
| Camera stream connected | RTSP/RTMP connection established | **PARTIAL** |
| Frame decoding operational | Decoder producing frames at expected FPS | **PARTIAL** |
| Inference operational | Models producing embeddings/detections | **PARTIAL** |
| Event delivery operational | Can reach Legacy Backend, queue healthy | **PARTIAL** |
| **All above true** | **Fully operational** | **YES** |

**A process heartbeat alone must never mean the AI pipeline is READY.**

---

## 5. Authentication

- **Header:** `X-API-Key`
- **Required Value:** `AI_WORKER_API_KEY` environment variable
- **Verification:** Constant-time comparison
- **Failure:** HTTP 401 with "Invalid AI Worker API key"

---

## 6. Retry and Timeout Behavior (Client-Side)

| Parameter | Value |
|---|---|
| Initial timeout | 5 seconds |
| Max retries | 3 |
| Backoff multiplier | 2.0 |
| Max retry delay | 30 seconds |
| Jitter | ±10% |

**Behavior on Backend Unavailable:**
- Log warning
- Queue health report locally (bounded queue, max 100 entries)
- Retry with exponential backoff
- Do not block video reader or inference loop
- Drop oldest queued reports if queue full

---

## 7. Contract Verification

### Current Implementation Status: SCAFFOLDED

| Aspect | Status | Evidence |
|---|---|---|
| Request schema | ✅ IMPLEMENTED | `AIWorkerHealthRequest` (lines 131-143) |
| Response schema | ✅ IMPLEMENTED | `AIWorkerHealthResponse` (lines 146-152) |
| Route registration | ✅ REGISTERED | `/api/v1/health/ai-worker` POST |
| Authentication | ✅ IMPLEMENTED | `verify_ai_worker_key` dependency |
| Health persistence | ❌ NOT IMPLEMENTED | No storage, no anomaly detection |
| Command queue | ❌ NOT IMPLEMENTED | Returns empty `commands` array |
| PipelineEngine client | ❌ NOT IMPLEMENTED | No client in PipelineEngine |

### Required for FUNCTIONAL Status

1. PipelineEngine health client implementation
2. Health state persistence in Legacy Backend
3. Anomaly detection (stale heartbeat, model unload, camera drop)
4. Command queue for control actions
4. Integration tests with mock PipelineEngine

---

## 8. Gate B Contract Status

**CONTRACT DEFINED** — Implementation partially complete. PipelineEngine client integration required for full functionality.