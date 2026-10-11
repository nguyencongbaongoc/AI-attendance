# Phase 0.2.6 Health Contract Before/After

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Health Contract Changes

### 1.1 Request Schema (AIWorkerHealthRequest)

| Field | Before | After |
|---|---|---|
| `worker_id` | Required | Required |
| `worker_version` | Required | Required |
| `state` | Required (no validation) | Required (validated against enum) |
| `timestamp` | Required | Required |
| `sequence_number` | Required (no validation) | Required (validated monotonic) |
| `camera_states` | Optional | Optional |
| `model_readiness` | Optional | Optional |
| `gpu_provider` | Optional (default) | Optional (default) |
| `queue_depth` | Optional | Optional |
| `processing_latency_ms` | Optional | Optional |
| `dropped_frames` | Optional | Optional |
| `stream_epochs` | Optional | Optional |
| `errors` | Optional | Optional |

**Key Change:** State validation added. Sequence number validation added.

### 1.2 Response Schema (AIWorkerHealthResponse)

| Field | Before | After |
|---|---|---|
| `success` | Always true | True on validation success |
| `worker_id` | Echoed | Echoed |
| `acknowledged` | Always true | True on validation success |
| `server_timestamp` | Added | Added |
| `sequence_number` | Echoed | Echoed |
| `commands` | Always empty | Populated with pending control actions |
| `stale_threshold_seconds` | 30.0 | 30.0 |

**Key Change:** `commands` now returns pending control actions for the worker.

---

## 2. Endpoint Changes

### 2.1 POST /api/v1/health/ai-worker

| Aspect | Before | After |
|---|---|---|
| Authentication | `verify_ai_worker_key` (allows bypass) | `verify_ai_worker_key` (fail-closed) |
| State validation | None | Enum validation |
| Sequence validation | None | Monotonic, duplicate detection |
| Generation tracking | None | Worker restart detection |
| Health state storage | None | In-memory with generation |
| Stale worker detection | None | 30s threshold |
| Control command return | Empty list | Pending actions for worker |

### 2.2 NEW: GET /api/v1/health/ai-worker/{worker_id}

| Aspect | Implementation |
|---|---|
| Method | GET |
| Path | `/api/v1/health/ai-worker/{worker_id}` |
| Auth | `verify_ai_worker_key` |
| Response | `AIWorkerHealthResponse` with current state |
| 404 | Worker not found |

---

## 3. Health State Model

### 3.1 WorkerHealthState (New)

```python
@dataclass
class WorkerHealthState:
    worker_id: str
    worker_version: str
    reported_state: str          # Raw state from worker
    health_status: str           # "healthy" | "degraded" | "unhealthy" | "stale" | "unknown"
    last_report_timestamp: float # Unix timestamp
    last_sequence: int           # Last accepted sequence number
    generation_id: int           # Increments on worker restart
    camera_states: Dict[str, CameraState]
    model_readiness: ModelReadiness
    gpu_provider: str
    queue_depth: int
    processing_latency_ms: float
    dropped_frames: int
    stream_epochs: Dict[str, int]
    errors: List[str]
    state_updated_at: float      # Backend update timestamp
```

---

## 4. Sequence & Generation Policy

| Scenario | Behavior |
|---|---|
| First report (no state) | Must have sequence=1, generation=1 |
| Normal sequence | Must be exactly last_sequence + 1 |
| Duplicate sequence (≤ last) | Rejected 400 |
| Sequence gap (> expected) | Rejected 400 |
| Worker restart (seq reset to 1) | New generation, accepted |
| Invalid state string | Rejected 400 |

---

## 4.1 Before/After Comparison Table

| Feature | Phase 0.2.5 (Before) | Phase 0.2.6 (After) |
|---|---|---|
| Health endpoint accepts reports | ✅ | ✅ |
| Validates state enum | ❌ | ✅ |
| Validates sequence | ❌ | ✅ |
| Tracks worker generations | ❌ | ✅ |
| Stores health state | ❌ | ✅ |
| Status retrieval endpoint | ❌ | ✅ |
| Stale worker detection | ❌ | ✅ |
| Returns pending commands | ❌ | ✅ |
| Auth fail-closed | ❌ | ✅ |
| Tests passing | 11/13 | 13/13 |

---

## 5. Client Alignment

| Field | Client Sends | Backend Expects | Status |
|---|---|---|---|
| `inference_provider` | ✅ | ❌ (expects `gpu_provider`) | **FIXED** in client |
| `gpu_provider` | ✅ (after fix) | ✅ | Aligned |
| `dropped_frame_count` | ✅ | ❌ (expects `dropped_frames`) | **FIXED** in client |
| `dropped_frames` | ✅ (after fix) | ✅ | Aligned |
| `event_delivery_state` | ✅ | ❌ (not in schema) | Removed from client |

**Client changes made:** Fixed field names in `pipeline_engine/integration/health_client.py`