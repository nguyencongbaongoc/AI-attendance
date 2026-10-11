# Control Worker Execution Evidence

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. PipelineEngine Control Client Architecture

The `PipelineEngineControlServer` class (`pipeline_engine/integration/control_client.py`) is designed to:
1. Poll Legacy Backend for pending commands
2. Execute commands on the PipelineEngine
3. Submit responses back to Legacy Backend

### 1.1 Key Components

| Component | Implementation |
|---|---|
| Polling Loop | `_poll_loop()` → `_poll_commands()` every 2s |
| Action Handlers | `_action_handlers` dict mapping 6 actions |
| Idempotency | `_processed_keys` set |
| Response Submission | `_send_response()` POSTs to `/api/v1/ai/control/{action}/response` |

---

## 2. Critical Contract Mismatches

### 2.1 Action Name Mismatch (BLOCKING)

| Backend Action | Client Action | Match |
|---|---|---|
| `START_WORKER` | `START` = "start" | ❌ |
| `STOP_WORKER` | `STOP` = "stop" | ❌ |
| `RESTART_WORKER` | `RESTART` = "restart" | ❌ |
| `ENABLE_CAMERA` | `PAUSE_CAMERA` = "pause_camera" | ❌ |
| `DISABLE_CAMERA` | `RESUME_CAMERA` = "resume_camera" | ❌ |
| `GET_STATUS` | (not in client) | ❌ |
| (none) | `RECONFIG` = "reconfig" | ❌ |

**Impact:** Zero action overlap. Client cannot execute any backend command.

---

### 2.2 Polling Response Key Mismatch (BLOCKING)

**Backend Response (`ai_worker.py`):**
```python
return PendingControlRequests(worker_id=worker_id, requests=requests)
# Returns: {"worker_id": "...", "requests": [...]}
```

**Client Expectation (`control_client.py` line 158):**
```python
commands = data.get("commands", [])
# Expects: {"commands": [...]}
```

**Result:** Client always gets empty list, never executes commands.

---

### 2.3 Response Endpoint Mismatch (BLOCKING)

**Client Submission (`control_client.py` line 218):**
```python
await self._client.post(
    f"/api/v1/ai/control/{response.action}/response",  # Uses "start", "stop", etc.
```

**Backend Valid Actions:** `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS`

**Result:** Client POSTs to `/api/v1/ai/control/start/response` → 400 Invalid Action

---

## 3. Client Action Handlers Analysis

### 3.1 Handler Mapping
```python
_action_handlers = {
    Action.START: self._handle_start,           # "start"
    Action.STOP: self._handle_stop,             # "stop"
    Action.RESTART: self._handle_restart,       # "restart"
    Action.RECONFIG: self._handle_reconfig,     # "reconfig"
    Action.PAUSE_CAMERA: self._handle_pause_camera,     # "pause_camera"
    Action.RESUME_CAMERA: self._handle_resume_camera,   # "resume_camera"
}
```

### 3.2 Handler Implementation Quality

| Handler | Status | Notes |
|---|---|---|
| `_handle_start` | IMPLEMENTED | Checks engine state, calls `engine.start()` |
| `_handle_stop` | IMPLEMENTED | Graceful/forced stop with timeout |
| `_handle_restart` | IMPLEMENTED | Stop + sleep + start |
| `_handle_reconfig` | STUB | Returns ACCEPTED, notes restart required |
| `_handle_pause_camera` | STUB | Returns ACCEPTED, camera manager not checked |
| `_handle_resume_camera` | STUB | Returns ACCEPTED, camera manager not checked |

**Note:** Camera handlers are stubs — they don't actually pause/resume cameras.

---

## 4. Integration Test Results

### 4.1 Direct Backend Test (Working)
From `control_integration_test.py`:
- ✅ Admin can submit START_WORKER, GET_STATUS
- ✅ Worker can poll pending requests (with correct "requests" key)
- ✅ Worker can submit responses (with correct action name in path)
- ✅ Completed requests filtered from pending
- ✅ Idempotency, expiration, isolation all work

### 4.2 Client-to-Backend Test (BLOCKED)
From `control_client_integration_test.py`:
- ❌ Client polling returns 422 (parameter validation issue with test adapter)
- ❌ Client expects "commands" key, gets "requests"
- ❌ Client action names don't match backend
- ❌ Client response endpoint wrong

---

## 5. Worker Execution Flow (Theoretical)

If contract mismatches were fixed, the flow would be:

```
1. Admin POSTs /api/v1/ai/control/START_WORKER
   ↓
2. Backend stores pending request with status=PENDING
   ↓
3. Client polls GET /api/v1/ai/control/pending?worker_id=X
   ↓
4. Backend returns {"worker_id": "X", "requests": [ControlRequest...]}
   ↓
5. Client maps action "START_WORKER" → handler _handle_start
   ↓
6. Client executes handler → engine.start()
   ↓
7. Client creates ControlResponse with status=COMPLETED
   ↓
8. Client POSTs /api/v1/ai/control/START_WORKER/response
   ↓
9. Backend updates pending.status = COMPLETED, stores response
   ↓
10. Next poll: request filtered out (status=COMPLETED)
```

---

## 6. Idempotency and Recovery (Client Side)

### 6.1 Client Idempotency
```python
async with self._processed_keys_lock:
    if request.idempotency_key in self._processed_keys:
        logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
        return
```

**Issue:** Only checked after polling, before execution. No deduplication on backend response submission.

### 6.2 Response Submission Retry
```python
async def _send_response(self, response: ControlResponse) -> None:
    try:
        await self._client.post(...)
    except Exception as e:
        logger.error(f"Failed to send control response: {e}")
```

**Issue:** No retry logic for response submission. If network fails, backend never gets completion status.

---

## 7. Action Execution Safety

### 7.1 Allowlist Enforcement
Client only executes actions in `_action_handlers` dict. Arbitrary code execution prevented.

### 7.2 State Checks
- START: Checks if already RUNNING/STARTING
- STOP: Checks if already STOPPED/STOPPING
- RESTART: Always executes stop+start

### 7.3 Missing Safety
- No confirmation that operation actually completed (engine.start() returns bool but not awaited)
- No timeout on handler execution
- Camera pause/resume are stubs

---

## 8. Required Fixes for Client Integration

### 8.1 Fix Action Names (Option A: Align Client to Backend)
```python
class Action(str):
    START_WORKER = "START_WORKER"
    STOP_WORKER = "STOP_WORKER"
    RESTART_WORKER = "RESTART_WORKER"
    ENABLE_CAMERA = "ENABLE_CAMERA"
    DISABLE_CAMERA = "DISABLE_CAMERA"
    GET_STATUS = "GET_STATUS"
```

### 8.2 Fix Polling Response Key
```python
data = response.json()
requests = data.get("requests", [])  # Not "commands"
for req in requests:
    await self._execute_command(req)
```

### 8.3 Fix Response Endpoint
```python
# Use backend action name from request, not client action enum
await self._client.post(
    f"/api/v1/ai/control/{request.action}/response",  # request.action = "START_WORKER"
```

### 8.4 Add GET_STATUS Handler
```python
Action.GET_STATUS: self._handle_get_status,
async def _handle_get_status(self, request):
    # Return engine status
    return ControlResponse(..., details={"state": self.engine.state.value, ...})
```

---

## 9. Conclusion

**Gate B Worker Execution: BLOCKED**

The PipelineEngine control client (`control_client.py`) cannot execute any backend control actions due to three fundamental contract mismatches:

1. **Action names don't match** — Zero overlap between client and backend action vocabularies
2. **Polling response key mismatch** — Client expects "commands", backend returns "requests"
3. **Response endpoint mismatch** — Client uses lowercase action names, backend requires uppercase

The client action handlers are well-structured for the actions they define, but those actions don't correspond to any backend endpoint.

**Backend is ready** — All 4 control endpoints functional and tested.
**Client needs rewrite** — Action vocabulary and response handling must align with backend contract.

---

## 10. Evidence Classification

| Assertion | Classification |
|---|---|
| Client polls backend | SOURCE-VERIFIED |
| Client action handlers exist | SOURCE-VERIFIED |
| Client executes handlers | SOURCE-VERIFIED |
| Client submits responses | SOURCE-VERIFIED |
| Client-backend action match | NOT-VERIFIED (mismatch) |
| Client polling works end-to-end | NOT-VERIFIED (key mismatch) |
| Client response submission works | NOT-VERIFIED (endpoint mismatch) |
| Worker execution of START/STOP | NOT-TESTED (blocked by mismatches) |
| Idempotency on client | SOURCE-VERIFIED |
| Response retry logic | NOT-VERIFIED (absent) |

---

**Status:** BLOCKED — Client contract mismatches prevent any worker execution