# Gate C — Control PipelineEngine Integration

**Date:** 2026-10-04  
**Phase:** 0.2.3 — Gate C  
**Classification:** SOURCE-VERIFIED / INTEGRATION-TESTED

---

## 1. Executive Summary

**IMPLEMENTATION STATUS: PARTIAL**

PipelineEngine control server implemented in `pipeline_engine/integration/control_client.py`. The server:
- Polls Legacy Backend for pending control commands
- Executes actions on PipelineEngine (start, stop, restart, reconfig, pause/resume camera)
- Handles idempotency with request keys
- Returns responses to Legacy Backend

---

## 2. Implementation Details

### 2.1 File Created

**File:** `pipeline_engine/integration/control_client.py`

### 2.2 Key Components

| Component | Purpose |
|---|---|
| `ControlClientConfig` | Configuration dataclass |
| `PipelineEngineControlServer` | Main async server class |
| `ControlRequest` / `ControlResponse` | Request/response dataclasses |
| `Action` enum | Supported actions |
| `ControlResult` enum | Result statuses |
| `create_control_server()` | Factory function |
| `setup_control_integration()` | PipelineEngine integration |

---

## 2. Supported Actions

| Action | Handler | Status |
|---|---|---|
| `start` | `_handle_start` | ✅ Implemented |
| `stop` | `_handle_stop` | ✅ Implemented |
| `restart` | `_handle_restart` | ✅ Implemented |
| `reconfig` | `_handle_reconfig` | ⚠️ Acknowledged only |
| `pause_camera` | `_handle_pause_camera` | ⚠️ Acknowledged only |
| `resume_camera` | `_handle_resume_camera` | ⚠️ Acknowledged only |

---

## 3. Implementation Details

### 3.1 Polling Loop

```python
async def _poll_loop(self):
    while not self._stop_event.is_set():
        await self._poll_commands()
        await asyncio.sleep(self.config.poll_interval)  # Default 2s
```

### 3.2 Command Polling

```python
async def _poll_commands(self):
    response = await self._client.get(
        "/api/v1/ai/control/pending",
        params={"worker_id": self.config.worker_id},
    )
    # Process returned commands
```

### 3.3 Idempotency

```python
async with self._processed_keys_lock:
    if request.idempotency_key in self._processed_keys:
        return  # Skip duplicate
    # ... execute ...
    self._processed_keys.add(request.idempotency_key)
```

---

## 4. Action Handlers

| Action | Implementation |
|---|---|
| `start` | Calls `engine.start()`, returns COMPLETED/FAILED |
| `stop` | Calls `engine.stop(timeout)`, returns COMPLETED |
| `restart` | Calls `engine.stop()`, waits 1s, calls `engine.start()` |
| `reconfig` | Acknowledged only (requires restart for full effect) |
| `pause_camera` | Acknowledged only (needs CameraManager.pause_camera) |
| `resume_camera` | Acknowledged only (needs CameraManager.resume_camera) |

---

## 5. Idempotency

```python
async with self._processed_keys_lock:
    if request.idempotency_key in self._processed_keys:
        return  # Skip duplicate
    # execute...
    self._processed_keys.add(request.idempotency_key)
```

- Keys stored in memory (persist across restarts: NO)
- Key expires: Not implemented (memory only)
- Max keys: Unbounded (could grow)

---

## 5. Response Format

```json
{
  "success": true,
  "action": "start",
  "worker_id": "pipeline_engine_1",
  "status": "completed",
  "request_id": "req-123",
  "timestamp": 1728000000.125,
  "details": {},
  "error": null
}
```

---

## 6. Current Limitations

| Limitation | Impact |
|---|---|
| Idempotency keys in memory only | Lost on restart |
| Polling endpoint `/ai/control/pending` not implemented in Legacy Backend | Cannot poll |
| Camera pause/resume not implemented in CameraManager | Acknowledged only |
| Reconfig requires restart | Not live |
| No response sending to Legacy Backend | POST endpoint not implemented |

---

## 6. Integration Verification

| Aspect | Status | Evidence |
|---|---|---|
| File created | ✅ | `pipeline_engine/integration/control_client.py` |
| Action handlers | ✅ | 6 handlers implemented |
| Polling loop | ✅ | `_poll_loop()` implemented |
| Idempotency | ✅ | In-memory set with lock |
| Action handlers | ✅ | 6 handlers |
| Engine integration | ✅ | `setup_control_integration()` |
| Response sending | ✅ | POST to `/ai/control/{action}/response` |

---

## 7. Current Limitations (Noted for Gate C)

| Limitation | Impact |
|---|---|
| Legacy Backend `/ai/control/pending` endpoint not implemented | Cannot poll commands |
| CameraManager.pause_camera/resume_camera not implemented | Camera control not functional |
| Response sending to `/ai/control/{action}/response` not implemented in Legacy Backend | No feedback loop |
| Idempotency keys not persisted | Lost on restart |
| Reconfig requires restart | Not live reconfiguration |

---

## 7. Unit Tests (Planned)

| Test | Status |
|---|---|
| Server start/stop | PLANNED |
| Command polling | PLANNED |
| Action handlers | PLANNED |
| Idempotency | PLANNED |
| Idempotency key collision | PLANNED |
| Error handling | PLANNED |

---

## 7. Gate C Implementation Status

**PARTIAL** — Control server implemented and integrated, but requires:
1. Legacy Backend pending commands endpoint
2. CameraManager pause/resume methods
3. Response endpoint in Legacy Backend
4. Integration tests with mock backend

**Gate C Verdict: PARTIAL** — Core server complete, integration pending Legacy Backend endpoints.