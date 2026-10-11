# Control Idempotency and Recovery Evidence

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Idempotency Implementation

### 1.1 Request Submission Idempotency (Backend)

**Storage:** `_processed_idempotency_keys: Dict[str, ControlResponse]`

**Logic (lines 1429-1439):**
```python
if request.idempotency_key in _processed_idempotency_keys:
    logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
    stored = _processed_idempotency_keys[request.idempotency_key]
    return {
        "success": True,
        "request_id": request.request_id,
        "status": "DUPLICATE",
        "message": "Duplicate request, returning stored response",
        "original_response": stored.dict()
    }
```

**Key Points:**
- Checked BEFORE storing new pending request
- Returns stored response (which is a PENDING placeholder)
- Does NOT execute action again

**Test Evidence (Test 3):** Duplicate idempotency key returns DUPLICATE with original response.

---

### 1.2 Idempotency Key Storage

**When stored:** After creating pending request (line 1452)
```python
_processed_idempotency_keys[request.idempotency_key] = ControlResponse(
    success=True,
    action=request.action,
    worker_id="pipeline_engine_1",  # Hardcoded!
    status=ControlRequestStatus.PENDING,
    request_id=request.request_id,
    timestamp=time.time(),
    details={"message": "Request queued"}
)
```

**Issues:**
1. `worker_id` hardcoded to "pipeline_engine_1" instead of `request.target_id`
2. Stores PENDING response, not final response
3. If same idempotency_key used for different worker, returns wrong worker_id

---

### 1.3 Response Idempotency (Missing)

**No deduplication on response submission.** Multiple POSTs to `/response` will overwrite status each time.

**Risk Scenario:**
1. Worker submits COMPLETED
2. Network timeout, worker retries
3. Retry arrives after backend processed first
4. Status could flip COMPLETED → FAILED → COMPLETED

---

## 2. Recovery Scenarios

### 2.1 Duplicate Pending Poll

**Scenario:** Client polls, gets request, processes, but response fails. Client polls again.

**Current Behavior:**
- Request stays PENDING in backend
- Client receives same request again
- Client executes action again (no client-side dedup after first poll)

**Client Idempotency (line 190-193):**
```python
async with self._processed_keys_lock:
    if request.idempotency_key in self._processed_keys:
        logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
        return
```

**Issue:** Client only tracks idempotency keys in memory. On restart, loses all keys.

---

### 2.2 Duplicate Request Delivery

**Scenario:** Backend somehow delivers same request twice (bug, retry).

**Backend:** Idempotency key prevents duplicate storage, but if request already PENDING and client polls, it will see it.

**Client:** In-memory `_processed_keys` prevents re-execution IF same client instance.

**Gap:** No cross-instance deduplication.

---

### 2.3 Worker Restart Before Execution

**Scenario:** Worker polls, gets request, crashes before executing.

**State:**
- Backend: Request PENDING
- Client: Never executed, no idempotency key stored

**On Restart:**
- Client polls again, gets same request
- Executes action (correct behavior)
- Submits response

**Result:** Action executed once. ✅

---

### 2.4 Worker Restart During Execution

**Scenario:** Worker starts executing, crashes mid-action.

**State:**
- Backend: Request PENDING (or RUNNING if client sent ACCEPTED)
- Action: Partially executed

**On Restart:**
- Client polls, gets request again (if still PENDING)
- Executes action again

**Risk:** Action executed twice (e.g., double STOP, double RESTART)

**Mitigation Needed:** Actions should be idempotent at engine level, or backend should track execution state.

---

### 2.5 Backend Restart

**State Storage:** In-memory `_pending_control_requests` and `_processed_idempotency_keys`

**On Restart:** ALL STATE LOST
- Pending requests gone
- Idempotency keys gone
- Completed request history gone

**Impact:** 
- Clients will re-poll, get 404 on response submission
- Admin must resubmit requests
- No audit trail

**Required:** Persistent storage for production.

---

### 2.6 Network Interruption Before Response

**Scenario:** Worker executes action, network fails before response POST.

**State:** Backend has PENDING request.

**Recovery:** Worker retries response POST (no retry logic currently).

**If Retry Succeeds:** Status updated to COMPLETED. ✅
**If Retry Fails:** Request stays PENDING, eventually expires.

---

### 2.7 Network Interruption After Execution, Before Acknowledgement

**Scenario:** Worker completes action, sends response, network fails. Backend receives but ACK lost.

**State:** Backend updated status to COMPLETED.

**Worker:** Thinks failed, may retry.

**Retry:** Submits COMPLETED again → overwrites with same status. ✅ (idempotent for terminal states)

---

### 2.8 Expired Request

**Scenario:** Request expires before worker polls.

**Backend:** `_cleanup_expired_requests()` removes on poll.

**Client:** Never sees request.

**Admin:** Must resubmit.

---

### 2.9 Unknown Request ID Response

**Test Evidence (Test 12):** Response to non-existent request_id → 404. ✅

---

### 2.10 Unknown Action Response

**Test Evidence (Test 8):** Submit with invalid action → 400. ✅

---

### 2.11 Worker Identity Mismatch

**Test Evidence (Test 10):** Worker A cannot see Worker B's requests. ✅

**Mechanism:** `if pending.request.target_id != worker_id: continue`

---

### 2.12 Authentication Failure

**Test Evidence (Tests 14, 15):** Missing/invalid admin key → 422/401. ✅

---

## 3. Response Timeout

**No timeout handling** for:
- How long request stays PENDING before admin should escalate
- How long worker has to respond after polling
- No "stuck in RUNNING" detection

---

## 4. Uncertain State Handling

**Requirement (from mandate):** "If the worker cannot determine whether an operation completed, require an explicit uncertain state rather than false success."

**Current:** No uncertain state. Statuses are binary (COMPLETED/FAILED).

**Gap:** Need `UNCERTAIN` status for cases where execution status unknown.

---

## 5. Integration Test Evidence

### 5.1 Tested Scenarios

| Scenario | Test | Result |
|---|---|---|
| Duplicate admin submit | Test 3 | PASS (DUPLICATE returned) |
| Worker isolation | Test 10 | PASS |
| Expired request filtering | Test 11 | PASS |
| Unknown request_id response | Test 12 | PASS (404) |
| Invalid action | Test 8 | PASS (400) |

### 5.2 NOT Tested (Require Runtime)

| Scenario | Blocked By |
|---|---|
| Worker restart before execution | Client mismatches |
| Worker restart during execution | Client mismatches |
| Backend restart | In-memory state |
| Network interruption | Client mismatches |
| Duplicate response submission | Not implemented |
| Uncertain state | Not implemented |

---

## 6. Required Fixes

### 6.1 Critical (For Gate B PASS)
1. Fix client contract mismatches (actions, polling key, response endpoint)
2. Add path/body action validation
3. Fix hardcoded worker_id in idempotency storage

### 6.2 Important (For Production)
1. Persistent storage for control state
2. Response idempotency
3. Status transition enforcement
4. Uncertain state support
5. Execution timeout tracking
6. Completed request history endpoint

---

## 7. Conclusion

**Idempotency: PARTIAL** — Request submission deduplication works. Response deduplication missing. Client in-memory dedup lost on restart.

**Recovery: BLOCKED** — Client contract mismatches prevent testing recovery scenarios. In-memory backend state lost on restart.

**Gate B Overall: BLOCKED** — Cannot verify end-to-end idempotency/recovery without working client integration.

---

## 8. Evidence Classification

| Assertion | Classification |
|---|---|
| Request idempotency (backend) | RUNTIME-VERIFIED |
| Response idempotency | NOT-VERIFIED (missing) |
| Client in-memory dedup | SOURCE-VERIFIED |
| Cross-restart dedup | NOT-VERIFIED (lost) |
| Worker isolation | RUNTIME-VERIFIED |
| Expired request handling | RUNTIME-VERIFIED |
| Unknown request rejection | RUNTIME-VERIFIED |
| Auth failure handling | RUNTIME-VERIFIED |
| Backend restart recovery | NOT-VERIFIED (state lost) |
| Network failure recovery | NOT-TESTED (blocked) |
| Uncertain state | NOT-VERIFIED (missing) |