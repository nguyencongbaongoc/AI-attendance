# Health Lifecycle and Failure Tests

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Lifecycle State Transition Tests

Since the backend does not persist health state, lifecycle transitions cannot be verified end-to-end. However, we can test the client's state mapping logic.

### 1.1 Client State Mapping (Source Verified)

From `pipeline_engine/integration/health_client.py` lines 213-233:

```python
def _get_worker_state(self) -> str:
    if not self.engine:
        return "starting"
        
    state = self.engine.state
    if state == EngineState.STOPPED:
        return "stopped"
    elif state == EngineState.STOPPING:
        return "stopping"
    elif state == EngineState.ERROR:
        return "failed"
    elif state == EngineState.DEGRADED:
        return "degraded"
    elif state == EngineState.RUNNING:
        return "ready"
    elif state == EngineState.STARTING:
        return "starting"
    elif state == EngineState.INITIALIZING:
        return "initializing"
    return "starting"
```

| EngineState | Mapped Health State | Valid Backend State |
|---|---|---|
| STOPPED | stopped | ✅ |
| STOPPING | stopping | ✅ |
| ERROR | failed | ✅ |
| DEGRADED | degraded | ✅ |
| RUNNING | ready | ✅ |
| STARTING | starting | ✅ |
| INITIALIZING | initializing | ✅ |
| (unknown) | starting | ✅ |

**Coverage:** All 7 valid backend states are mappable from EngineState.

---

## 2. Failure Mode Analysis

### 2.1 Backend Unavailable

**Client Behavior (lines 175-211):**
- Exponential backoff retry (max 3 retries)
- Base delay: 1.0s, max delay: 30.0s, backoff: 2.0x
- On 401: Returns False immediately (no retry)
- On timeout/connection error: Retries
- After max retries: Logs error, returns False

**Test Status:** NOT-TESTED (requires real network failure simulation)

---

### 2.2 Retry Exhaustion

**Expected Behavior:**
- Client retries 3 times with increasing delays
- After 4th attempt (0-indexed), gives up
- Logs error with last exception

**Test Status:** NOT-TESTED

---

### 2.3 Recovery After Backend Returns

**Client Behavior:**
- Loop continues every `report_interval` (default 5s)
- Next heartbeat attempt will succeed if backend is back
- Sequence number continues incrementing

**Test Status:** NOT-TESTED

---

### 2.4 Stale Heartbeat Detection

**Backend Requirement:** Track last heartbeat timestamp per worker, compare to `stale_threshold_seconds` (30s default from response).

**Current Backend:** NO TRACKING — Cannot detect stale workers.

**Test Status:** NOT-VERIFIED (backend missing)

---

### 2.5 Duplicate Sequence Numbers

**Test Evidence (from integration test):**
- Sent sequence 1, then 2, then duplicate 2
- All accepted with 200 OK
- Backend does not track sequence numbers

**Result:** FAIL — Duplicate sequences not rejected.

---

### 2.6 Out-of-Order Sequences

**Test:** Not executed (would require backend tracking)

**Expected:** Backend should reject sequence N+2 before N+1.

**Result:** NOT-VERIFIED (backend missing)

---

### 2.7 Worker Restart

**Client Behavior:**
- Sequence number resets to 0 on new client instance
- Worker_id remains same
- Backend would see sequence restart

**Backend Requirement:** Detect sequence reset (worker restart) vs duplicate.

**Result:** NOT-VERIFIED (backend missing)

---

### 2.8 Stream Epoch Change

**Client Behavior (line 315-318):**
```python
def update_stream_epoch(self, camera_id: str, epoch: int) -> None:
    self._stream_epochs[camera_id] = epoch
    logger.info(f"Stream epoch updated for {camera_id}: {epoch}")
```

**Backend Requirement:** Track stream_epochs per camera to distinguish stream restarts.

**Result:** NOT-VERIFIED (backend missing)

---

## 3. Required Backend Implementation for Lifecycle

### 3.1 In-Memory Health State Store

```python
@dataclass
class WorkerHealthState:
    worker_id: str
    worker_version: str
    state: str
    last_timestamp: float
    last_sequence: int
    camera_states: Dict[str, CameraState]
    model_readiness: ModelReadiness
    gpu_provider: str
    queue_depth: int
    processing_latency_ms: float
    dropped_frames: int
    stream_epochs: Dict[str, int]
    errors: List[str]
    last_update: float

_worker_health_states: Dict[str, WorkerHealthState] = {}
```

### 3.2 Sequence Validation Logic

```python
def validate_sequence(worker_id: str, sequence: int) -> Tuple[bool, str]:
    state = _worker_health_states.get(worker_id)
    if state is None:
        if sequence != 1:
            return False, "First sequence must be 1"
        return True, "OK"
    
    if sequence <= state.last_sequence:
        return False, f"Duplicate or stale sequence: {sequence} <= {state.last_sequence}"
    
    if sequence > state.last_sequence + 1:
        return False, f"Sequence gap: expected {state.last_sequence + 1}, got {sequence}"
    
    return True, "OK"
```

### 3.3 Stale Worker Detection

```python
def check_stale_workers(threshold_seconds: float = 30.0) -> List[str]:
    now = time.time()
    stale = []
    for worker_id, state in _worker_health_states.items():
        if now - state.last_update > threshold_seconds:
            stale.append(worker_id)
    return stale
```

### 3.4 Status Retrieval Endpoint

```python
@router.get("/health/ai-worker/{worker_id}", response_model=AIWorkerHealthResponse)
async def get_worker_health(worker_id: str) -> AIWorkerHealthResponse:
    state = _worker_health_states.get(worker_id)
    if not state:
        raise HTTPException(404, "Worker not found")
    return AIWorkerHealthResponse(...)
```

---

## 4. Test Plan for Full Lifecycle Verification

Once backend is implemented, these tests must pass:

| Test ID | Scenario | Expected |
|---|---|---|
| HL-01 | First heartbeat (seq=1) | Accepted, state=READY |
| HL-02 | Sequential heartbeats (seq=2,3,4) | All accepted |
| HL-03 | Duplicate sequence | Rejected 400 |
| HL-04 | Out-of-order (1,3,2) | 3 rejected, 2 accepted |
| HL-05 | State transition READY→DEGRADED | State updated |
| HL-06 | State transition READY→FAILED | State updated |
| HL-07 | Stale worker (no heartbeat 30s) | Detected as stale |
| HL-08 | Worker restart (seq reset to 1) | Detected as restart |
| HL-09 | Stream epoch increment | Tracked per camera |
| HL-10 | Backend down → up | Client recovers automatically |
| HL-11 | Invalid state string | Rejected 400 |
| HL-12 | Status retrieval after heartbeats | Returns latest state |

---

## 5. Current Verdict

**Gate A: BLOCKED**

No lifecycle or failure tests can pass because the backend health state management is not implemented. The client implementation is complete and correct, but has no functional backend to integrate with.

**Classification:** SOURCE-VERIFIED (client logic), NOT-VERIFIED (backend behavior), NOT-TESTED (failure modes)