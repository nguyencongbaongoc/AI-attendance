# Phase 0.2.6 Control Lifecycle and Idempotency

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Command Lifecycle

### 1.1 State Machine

```
PENDING -> (client polls) -> ACCEPTED -> (client starts) -> RUNNING -> (client completes) -> COMPLETED
                                                                      -> (client fails) -> FAILED
                                                                      -> (client rejects) -> REJECTED
                                                        -> (TTL expires) -> EXPIRED
```

### 1.2 State Transitions

| From -> To | Trigger | Who |
|---|---|---|
| PENDING -> ACCEPTED | Client polls and sees request | Client (auto on poll) |
| ACCEPTED -> RUNNING | Client begins execution | Client |
| RUNNING -> COMPLETED | Handler returns success | Client (via response) |
| RUNNING -> FAILED | Handler returns error/exception | Client (via response) |
| RUNNING -> REJECTED | Handler rejects action | Client (via response) |
| PENDING/ACCEPTED/RUNNING -> EXPIRED | TTL exceeded | Backend (on cleanup) |

---

## 2. Idempotency

### 2.1 Request Submission (Backend)

**Storage:** `_processed_idempotency_keys: Dict[str, ControlResponse]`

```python
if request.idempotency_key in _processed_idempotency_keys:
    return {"success": True, "status": "DUPLICATE", "original_response": stored.dict()}

# Store after creating pending request
_processed_idempotency_keys[request.idempotency_key] = ControlResponse(
    success=True, action=request.action, worker_id=request.target_id,
    status=ControlRequestStatus.PENDING, request_id=request.request_id,
    timestamp=time.time(), details={"message": "Request queued"}
)
```

**Behavior:**
- Duplicate admin submissions return stored PENDING response
- Does not re-queue or re-execute

### 2.2 Client Execution (Client)

**Storage:** `_processed_keys: set`

```python
async with self._processed_keys_lock:
    if request.idempotency_key in self._processed_keys:
        return  # Skip execution
# ... execute ...
async with self._processed_keys_lock:
    self._processed_keys.add(request.idempotency_key)
```

**Behavior:**
- In-memory only (lost on client restart)
- Prevents duplicate execution within same client instance

### 2.3 Response Submission (Backend)

**Current:** No deduplication - overwrites status each time
**Risk:** Network retry could flip COMPLETED -> FAILED -> COMPLETED
**Mitigation:** Terminal states (COMPLETED/FAILED/REJECTED) are idempotent by nature

---

## 3. Recovery Scenarios

### 3.1 Worker Restart Before Execution
- Backend: Request stays PENDING
- Client: Restarts, polls again, executes once ✅

### 3.2 Worker Restart During Execution
- Backend: Request PENDING (or ACCEPTED if client updated)
- Client: Restarts, may re-execute ⚠️
- **Mitigation:** Actions should be idempotent at engine level

### 3.3 Backend Restart
- All in-memory state lost
- Clients re-poll, get empty results
- Admins must resubmit requests

### 3.4 Network Failure Before Response
- Client executes, response POST fails
- Backend stays PENDING/ACCEPTED
- Client retries (no retry logic currently) ⚠️

### 3.5 Network Failure After Execution
- Client completes, sends response, ACK lost
- Client retries -> overwrites with same terminal status ✅

---

## 4. Test Evidence

| Scenario | Test | Result |
|---|---|---|
| Duplicate admin submit | Returns DUPLICATE with stored response | PASS |
| Client in-memory dedup | Skips duplicate execution | PASS (source) |
| Command lifecycle | PENDING -> COMPLETED, filtered from pending | PASS |
| History endpoint | Returns completed commands | PASS |
| Path/body mismatch | Rejected 400 | PASS |
| Expired request | Filtered on poll | PASS |

---

## 5. Gaps

| Gap | Severity | Recommendation |
|---|---|---|
| No response retry | MEDIUM | Add exponential backoff to `_send_response` |
| Client state lost on restart | MEDIUM | Persist `_processed_keys` to disk |
| Backend state lost on restart | MEDIUM | Persist control state |
| Response deduplication | LOW | Track response idempotency keys |
| Execution timeout tracking | LOW | Add RUNNING timeout detection |