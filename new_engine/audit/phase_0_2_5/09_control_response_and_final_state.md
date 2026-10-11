# Control Response and Final State Evidence

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Response Submission Endpoint

**Backend:** `POST /api/v1/ai/control/{action}/response` (lines 1518-1568 in `ai_worker.py`)

### 1.1 Request Validation

| Check | Implementation |
|---|---|
| Action in valid set | ✅ `valid_actions = {"START_WORKER", "STOP_WORKER", "RESTART_WORKER", "ENABLE_CAMERA", "DISABLE_CAMERA", "GET_STATUS"}` |
| request_id required | ✅ `if not response.request_id: raise 400` |
| Pending request exists | ✅ `pending = _pending_control_requests.get(response.request_id)` |
| 404 if not found | ✅ |

### 1.2 State Updates

```python
pending.status = response.status
if response.status in (COMPLETED, FAILED, REJECTED):
    pending.completed_at = time.time()
pending.response = response
```

### 1.3 Response

```python
return {"success": True, "message": "Response recorded"}
```

---

## 2. Status Transitions

### 2.1 Valid Status Values (ControlRequestStatus)

| Status | Terminal? | Description |
|---|---|---|
| PENDING | No | Initial state, queued |
| ACCEPTED | No | Worker acknowledged |
| RUNNING | No | Worker executing |
| COMPLETED | Yes | Success |
| FAILED | Yes | Execution failed |
| REJECTED | Yes | Worker rejected |
| EXPIRED | Yes | TTL elapsed |

### 2.2 Transition Rules (Backend Enforced)

| From → To | Allowed | Notes |
|---|---|---|
| PENDING → ACCEPTED | ✅ | Worker acknowledges |
| PENDING → RUNNING | ✅ | Worker starts execution |
| PENDING → REJECTED | ✅ | Worker rejects |
| PENDING → EXPIRED | ✅ | Backend cleanup |
| ACCEPTED → RUNNING | ✅ | |
| RUNNING → COMPLETED | ✅ | Sets completed_at |
| RUNNING → FAILED | ✅ | Sets completed_at |
| RUNNING → REJECTED | ✅ | Sets completed_at |
| COMPLETED → * | ❌ | Terminal |
| FAILED → * | ❌ | Terminal |
| REJECTED → * | ❌ | Terminal |

**Note:** Backend doesn't enforce transition rules — any status can be set. This is a gap.

---

## 3. Final State Retrieval

### 3.1 Current Capabilities

| Endpoint | Returns | Limitation |
|---|---|---|
| `GET /api/v1/ai/control/pending` | Only PENDING requests | Completed/failed filtered out |
| `GET /api/v1/ai/control/status` | Counts only | No detail |

### 3.2 Missing: Completed Request Retrieval

**No endpoint exists** to retrieve final state of completed/failed requests.

**Required for audit:** `GET /api/v1/ai/control/history` or similar to query completed requests by worker_id, request_id, or time range.

---

## 4. Integration Test Evidence

### 4.1 Successful Response Flow

From `control_integration_test.py`:

```
1. Admin submits GET_STATUS request → 200 PENDING
2. Worker polls → receives request
3. Worker POSTs /api/v1/ai/control/GET_STATUS/response with status=COMPLETED
   → 200 "Response recorded"
4. Worker polls again → GET_STATUS no longer in pending
5. Control status → pending_requests=1 (only START_WORKER remains)
```

**Verified:** Response submission works, pending filtering works.

---

### 4.2 Response Validation Tests

| Test | Result |
|---|---|
| Valid response to valid request | PASS (200) |
| Response to non-existent request_id | PASS (404) |
| Response with mismatched action in path | PASS (200 - but shouldn't) |
| Response with invalid action in path | PASS (400) |

---

### 4.3 Mismatched Action Path vs Body (Gap)

```
POST /api/v1/ai/control/STOP_WORKER/response
Body: {"action": "START_WORKER", ...}

Result: 200 OK (accepted!)
```

**Issue:** Backend validates `action` in path against `valid_actions` but doesn't verify it matches `response.action` in body.

**Fix needed:**
```python
if action != response.action:
    raise HTTPException(400, f"Path action '{action}' != body action '{response.action}'")
```

---

## 5. Idempotency and Duplicate Handling

### 5.1 Request Submission Idempotency

```python
if request.idempotency_key in _processed_idempotency_keys:
    return {"success": True, "status": "DUPLICATE", "original_response": ...}
```

**Works:** Duplicate admin submissions return stored response.

### 5.2 Response Idempotency

**Not implemented** — Multiple responses to same request_id will overwrite pending status each time.

**Risk:** Network retry could change COMPLETED → FAILED → COMPLETED

**Fix needed:** Track processed response idempotency keys or reject non-terminal → terminal transitions only.

---

## 6. Expiration Handling

### 6.1 Request Expiration

- `expires_at` required on submission
- Cleanup on poll: `_cleanup_expired_requests()` removes where `expires_at < now`
- Poll filter: `if pending.request.created_at < (now - 300): continue`

### 6.2 Expired Request State

- Status not automatically set to EXPIRED
- Just removed from storage
- No audit trail of expiration

---

## 7. Control Status Endpoint

**Endpoint:** `GET /api/v1/ai/control/status`

**Response:**
```json
{
  "pending_requests": 1,
  "processed_requests": 2,
  "idempotency_keys": 2
}
```

**Limitation:** No detail on which requests, their actions, or final states.

---

## 8. Evidence Summary

| Requirement | Status | Evidence |
|---|---|---|
| Response endpoint exists | ✅ RUNTIME-VERIFIED | Test 5 |
| Validates action | ✅ RUNTIME-VERIFIED | Test 8 |
| Validates request_id | ✅ RUNTIME-VERIFIED | Test 12 |
| Updates pending status | ✅ RUNTIME-VERIFIED | Test 6 |
| Filters completed from pending | ✅ RUNTIME-VERIFIED | Test 6 |
| Validates path=body action | ❌ NOT IMPLEMENTED | Test 13 |
| Response idempotency | ❌ NOT IMPLEMENTED | Gap |
| Final state retrieval | ❌ NOT IMPLEMENTED | Gap |
| Expiration audit trail | ❌ NOT IMPLEMENTED | Gap |

---

## 9. Required for Gate B PASS

### 9.1 Must Fix (Blocking)
1. Client contract mismatches (action names, polling key, response endpoint)
2. Path/body action validation

### 9.2 Should Fix (Non-blocking for Phase 1)
1. Completed request history endpoint
2. Response idempotency
3. Status transition enforcement
4. Expiration audit trail

---

## 10. Conclusion

**Backend Response Handling: FUNCTIONAL BUT INCOMPLETE**

The response submission endpoint works correctly for the happy path:
- ✅ Accepts valid responses
- ✅ Updates pending request status
- ✅ Filters completed from pending polls
- ✅ Rejects unknown request_ids
- ✅ Validates action names

**Gaps:**
- ❌ No path/body action consistency check
- ❌ No response idempotency
- ❌ No completed request retrieval
- ❌ No status transition validation

**Blocker remains:** PipelineEngine client cannot submit responses due to contract mismatches (wrong action names, wrong endpoint paths).

---

## 11. Evidence Classification

| Assertion | Classification |
|---|---|
| Response endpoint accepts valid responses | RUNTIME-VERIFIED |
| Response updates pending status | RUNTIME-VERIFIED |
| Completed filtered from pending | RUNTIME-VERIFIED |
| Unknown request_id rejected | RUNTIME-VERIFIED |
| Path/body action validation | NOT-VERIFIED (missing) |
| Response idempotency | NOT-VERIFIED (missing) |
| Completed request retrieval | NOT-VERIFIED (missing) |
| End-to-end response flow | BLOCKED (client mismatch) |