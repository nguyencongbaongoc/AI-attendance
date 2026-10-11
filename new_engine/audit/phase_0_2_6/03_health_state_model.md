# Phase 0.2.6 Health State Model

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. WorkerHealthState Data Model

```python
@dataclass
class WorkerHealthState:
    worker_id: str
    worker_version: str
    reported_state: str          # Raw state from worker: starting, initializing, ready, degraded, failed, stopping, stopped
    health_status: str           # Backend-derived: healthy, degraded, unhealthy, stale, unknown
    last_report_timestamp: float # Unix timestamp of last accepted report
    last_sequence: int           # Last accepted sequence number
    generation_id: int           # Increments on worker restart (sequence reset to 1)
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

## 2. State Definitions

### 2.1 Reported State (from worker)
| State | Description |
|---|---|
| `starting` | Process starting, not yet initialized |
| `initializing` | Loading models, connecting cameras |
| `ready` | Fully operational, processing frames |
| `degraded` | Operational but with issues (e.g., one camera down) |
| `failed` | Unrecoverable error, not processing |
| `stopping` | Graceful shutdown in progress |
| `stopped` | Cleanly stopped |

### 2.2 Health Status (backend-derived)
| Status | Derivation |
|---|---|
| `healthy` | reported_state in {ready, initializing, starting} AND not stale |
| `degraded` | reported_state == degraded AND not stale |
| `unhealthy` | reported_state in {failed, stopping, stopped} |
| `stale` | No report received within stale_threshold_seconds (30s) |
| `unknown` | Worker never reported or state indeterminate |

---

## 3. State Transitions

```
[Unknown] --first report (seq=1)--> [Healthy/Degraded/Unhealthy based on state]
    |
    +-- seq increment --> [Healthy/Degraded/Unhealthy]
    |
    +-- seq reset to 1 (restart) --> New generation, [Healthy/Degraded/Unhealthy]
    |
    +-- no report for 30s --> [Stale] (regardless of previous state)
    |
    +-- new valid report after stale --> [Healthy/Degraded/Unhealthy] (generation preserved)
```

---

## 4. Storage

- **In-memory dictionary**: `_worker_health_states: Dict[str, WorkerHealthState]`
- **Key**: `worker_id`
- **Persistence**: None (in-memory only)
- **Restart behavior**: All state lost on backend restart

**Rationale**: Health state is ephemeral and rebuildable from worker heartbeats. No persistence needed for Phase 0.2.6.

---

## 5. API Integration

### 5.1 POST /api/v1/health/ai-worker
- Updates or creates `WorkerHealthState`
- Returns `AIWorkerHealthResponse` with `commands` (pending control actions)
- Validates sequence/generation

### 5.2 GET /api/v1/health/ai-worker/{worker_id}
- Returns `AIWorkerHealthResponse` with current state
- Does not return commands (status-only endpoint)
- 404 if worker not found

---

## 6. Stale Detection

- Runs on every health request via `_check_stale_workers(30.0)`
- Iterates all workers, marks as `stale` if `now - last_report_timestamp > 30.0`
- Logs warning when worker becomes stale
- Does not remove state (preserves history for retrieval)

---

## 6. Test Evidence

All 13 health integration tests PASS:
- Valid health report accepted
- Invalid state rejected
- Duplicate sequence rejected
- Out-of-order sequence rejected
- Worker restart (sequence reset) accepted
- Invalid API key rejected
- Missing API key rejected
- Status retrieval for existing worker
- Status retrieval for unknown worker returns 404
- Status returns correct sequence number
- Stale worker detection mechanism active
- Health response includes pending commands
- Full health report with camera states accepted