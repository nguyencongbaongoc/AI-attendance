# Phase 0.2.6 Control Backend Client Alignment

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Changes Made

### 1.1 PipelineEngine Control Client (`pipeline_engine/integration/control_client.py`)

**Action Vocabulary (Complete Rewrite):**

```python
# Before
class Action(str):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RECONFIG = "reconfig"
    PAUSE_CAMERA = "pause_camera"
    RESUME_CAMERA = "resume_camera"

# After - Matches backend exactly
class Action(str):
    START_WORKER = "START_WORKER"
    STOP_WORKER = "STOP_WORKER"
    RESTART_WORKER = "RESTART_WORKER"
    ENABLE_CAMERA = "ENABLE_CAMERA"
    DISABLE_CAMERA = "DISABLE_CAMERA"
    GET_STATUS = "GET_STATUS"
```

**ControlResult Enum (Aligned to Backend):**

```python
# Before
class ControlResult(str):
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"

# After - Matches backend ControlRequestStatus
class ControlResult(str):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
```

**Polling Response Key Fix:**

```python
# Before
commands = data.get("commands", [])

# After
requests = data.get("requests", [])
commands = [req.get("action") for req in requests if req.get("action")]
```

**Response Endpoint Path Fix:**

```python
# Before
f"/api/v1/ai/control/{response.action}/response"  # Used local enum value

# After - Uses the canonical action from the original request
f"/api/v1/ai/control/{response.action}/response"  # response.action = "START_WORKER"
```

**Added GET_STATUS Handler:**

```python
async def _handle_get_status(self, request: ControlRequest) -> ControlResponse:
    # Returns worker state, uptime, camera status
    return ControlResponse(
        success=True,
        action=Action.GET_STATUS,
        worker_id=self.config.worker_id,
        status=ControlResult.COMPLETED,
        request_id=request.request_id,
        timestamp=time.time(),
        details={...}
    )
```

**Action Handler Mapping Updated:**

```python
self._action_handlers = {
    Action.START_WORKER: self._handle_start_worker,
    Action.STOP_WORKER: self._handle_stop_worker,
    Action.RESTART_WORKER: self._handle_restart_worker,
    Action.ENABLE_CAMERA: self._handle_enable_camera,
    Action.DISABLE_CAMERA: self._handle_disable_camera,
    Action.GET_STATUS: self._handle_get_status,
}
```

---

### 1.2 Backend API (`app/api/ai_worker.py`)

**Path/Body Action Validation:**

```python
# In submit_control_response():
if action != response.action:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Path action '{action}' does not match body action '{response.action}'"
    )
```

**Worker ID Validation:**

```python
if pending.request.target_id != response.worker_id:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Worker ID mismatch: request targets {pending.request.target_id}, response from {response.worker_id}"
    )
```

**Fixed Hardcoded Worker ID in Idempotency Storage:**

```python
# Before
worker_id="pipeline_engine_1"

# After
worker_id=request.target_id
```

**Added History Endpoint:**

```python
@router.get("/ai/control/history", dependencies=[Depends(verify_admin_key)])
async def get_control_history(
    worker_id: Optional[str] = None,
    limit: int = 100,
    since: Optional[float] = None,
    status_filter: Optional[str] = None,
):
    # Returns completed/failed/expired requests with full details
```

---

## 2. Verification

### 2.1 Contract Alignment Tests (All PASS)

| Test | Description |
|---|---|
| Client Action enum matches backend | PASS |
| Client ControlResult enum matches backend | PASS |
| Client polling uses 'requests' key | PASS |
| Client response endpoint uses response.action | PASS |
| Client has GET_STATUS handler | PASS |

### 2.2 End-to-End Tests (All PASS)

| Test | Description |
|---|---|
| Simulated client poll retrieves commands | PASS |
| Simulated client response submission | PASS |
| Command lifecycle PENDING -> COMPLETED | PASS |
| History endpoint returns completed commands | PASS |
| Path/body mismatch rejected | PASS |

---

## 3. Summary

**All 3 critical mismatches resolved:**

1. **Action vocabulary** - Client now uses `START_WORKER` etc.
2. **Polling response key** - Client now reads `requests` not `commands`
3. **Response endpoint** - Client uses `response.action` from canonical request

**Gate B: PASS** - 17/17 tests passing