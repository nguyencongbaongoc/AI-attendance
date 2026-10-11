# Open Findings and Blockers

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate G  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Critical Blockers (Phase 1 Entry Blocked)

### 1.1 Health Backend State Management Not Implemented
**Gate:** A  
**Severity:** CRITICAL  
**Finding:** Legacy Backend health endpoint (`POST /api/v1/health/ai-worker`) is a scaffold that:
- Accepts requests but does NOT persist health state
- Does NOT validate sequence numbers (duplicates accepted)
- Does NOT validate state enum values (accepts any string)
- Does NOT track camera states, model readiness, stream epochs, errors
- Does NOT provide status retrieval endpoint (`GET /api/v1/health/ai-worker/{worker_id}`)
- Does NOT return pending control commands

**Impact:** Cannot prove Health E2E flow. Architecture A invariant "Health doesn't claim READY without evidence" unverifiable.

**Required Fix:** Implement in-memory health state store with sequence validation, state persistence, and status retrieval endpoint.

---

### 1.2 PipelineEngine Control Client Contract Mismatches
**Gate:** B  
**Severity:** CRITICAL  
**Finding:** Three fundamental mismatches prevent any control flow:

| Mismatch | Backend | Client | Result |
|---|---|---|---|
| Action names | START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS | start, stop, restart, reconfig, pause_camera, resume_camera | Zero overlap |
| Polling response key | `"requests"` | expects `"commands"` | Always empty |
| Response endpoint | `/api/v1/ai/control/START_WORKER/response` | posts to `/api/v1/ai/control/start/response` | 400 Invalid Action |

**Impact:** PipelineEngine cannot execute ANY backend control action. End-to-end control flow BLOCKED.

**Required Fix:** Align client action vocabulary, response key handling, and response endpoint construction to match backend contract.

---

### 1.3 Missing Phase 0.2.4 Artifact 11
**Gate:** 0  
**Severity:** CRITICAL  
**Finding:** Phase 0.2.4 spec required 20 artifacts (00-19). Artifact 11 (`11_control_end_to_end_tests.md`) missing. Instead there are two artifact 10s and numbering offset by 1 from artifact 12 onwards.

**Impact:** Control end-to-end test evidence not documented. Phase 0.2.4 final verdict references OF-01/OF-02 as blockers which correspond to this missing artifact.

**Required Fix:** Create artifact 11 with actual integration test evidence or mark NOT-VERIFIED.

---

## 2. High Severity Findings

### 2.1 ai_worker.py Massive Code Duplication
**Gate:** A, B, C, F  
**Severity:** HIGH  
**Finding:** File is 1,635 lines but contains 3 complete copies of all models, dependencies, and endpoints. Actual unique content ~550 lines.

**Impact:** Maintenance burden, potential for inconsistencies, confusing debugging.

**Required Fix:** Remove duplicate sections, keep single definition of each model/endpoint.

---

### 2.2 Non-Constant-Time Auth Comparison (Worker/Control Keys)
**Gate:** C  
**Severity:** HIGH  
**Finding:** `verify_ai_worker_key` and `verify_ai_control_key` use `!=` instead of `secrets.compare_digest`. Also allow ANY key if env var not set.

**Location:** `app/api/ai_worker.py` lines 39, 274, 509, 744, 979, 1214 (worker), 48, 283, 518, 753, 988, 1223 (control)

**Required Fix:** Use `secrets.compare_digest` and fail-closed when env not set.

---

### 2.3 Backend Response Idempotency Missing
**Gate:** B  
**Severity:** HIGH  
**Finding:** Multiple responses to same request_id overwrite status each time. No deduplication on response submission.

**Risk:** Network retry could flip COMPLETED → FAILED → COMPLETED.

**Required Fix:** Track processed response idempotency keys or enforce terminal state transitions only.

---

### 2.4 No Completed Request History Endpoint
**Gate:** B  
**Severity:** HIGH  
**Finding:** No endpoint to retrieve final state of completed/failed/expired requests. Only `GET /pending` (excludes completed) and `GET /status` (counts only).

**Required Fix:** Add `GET /api/v1/ai/control/history` with filtering by worker_id, request_id, time range.

---

### 2.5 Path/Body Action Consistency Not Validated
**Gate:** B  
**Severity:** HIGH  
**Finding:** `POST /api/v1/ai/control/{action}/response` validates action in path but doesn't verify it matches `response.action` in body.

**Test Evidence:** POST to `/STOP_WORKER/response` with body `action: START_WORKER` returns 200 OK.

**Required Fix:** Add validation `if action != response.action: raise 400`.

---

## 3. Medium Severity Findings

### 3.1 Hardcoded Worker ID in Idempotency Storage
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** Line 1455 in `ai_worker.py`: `worker_id="pipeline_engine_1"` hardcoded instead of `request.target_id`.

**Impact:** Duplicate detection returns wrong worker_id if same idempotency_key used for different workers.

---

### 3.2 Control Client Response Submission No Retry
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** `_send_response()` has no retry logic. If network fails, backend never gets completion status.

**Required Fix:** Add exponential backoff retry for response submission.

---

### 3.3 Client In-Memory Idempotency Lost on Restart
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** Client `_processed_keys` set is in-memory only. On worker restart, all deduplication state lost.

**Impact:** Could re-execute actions after restart.

---

### 3.4 Backend Control State In-Memory Only
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** `_pending_control_requests` and `_processed_idempotency_keys` lost on backend restart.

**Required Fix:** Persistent storage for production.

---

### 3.5 Health Client Field Name Mismatches
**Gate:** A  
**Severity:** MEDIUM  
**Finding:** Client sends `inference_provider` but backend expects `gpu_provider`. Client sends extra `event_delivery_state` not in backend model.

**Required Fix:** Align field names.

---

### 3.6 Camera Handlers Are Stubs
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** `_handle_pause_camera` and `_handle_resume_camera` return ACCEPTED but don't actually pause/resume cameras.

**Impact:** ENABLE_CAMERA/DISABLE_CAMERA actions not functional.

---

### 3.7 No GET_STATUS Handler in Client
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** Backend supports GET_STATUS but client has no handler for it.

---

### 3.8 No Uncertain State for Recovery
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** Mandate requires "explicit uncertain state rather than false success" when execution status unknown. Only COMPLETED/FAILED/REJECTED exist.

---

### 3.9 No Rate Limiting on Auth Endpoints
**Gate:** C  
**Severity:** MEDIUM  
**Finding:** Brute force possible on all auth endpoints.

---

### 3.10 No Execution Timeout Tracking
**Gate:** B  
**Severity:** MEDIUM  
**Finding:** No detection of "stuck in RUNNING" requests. No timeout on handler execution.

---

## 4. Low Severity Findings

### 4.1 Deprecated datetime.utcnow() Usage
**Codebase-wide**  
**Severity:** LOW  
**Finding:** 345+ deprecation warnings in test runs. Should use `datetime.now(timezone.utc)`.

---

### 4.2 Duplicate ai_worker_health Endpoint Definition
**Gate:** A  
**Severity:** LOW  
**Finding:** Lines 1346-1375 and 1574-1603 both define identical `ai_worker_health` endpoint. FastAPI warns about duplicate operation ID.

---

### 4.3 Test Infrastructure Pre-existing Issues
**Unrelated to Phase 0.2.5**  
**Severity:** LOW  
**Finding:** `tests/unit/test_data_pipeline.py` has IndentationError preventing full test suite run.

---

## 5. Blocker Dependency Graph

```
Phase 1 Entry
    │
    ├── Gate A: Health E2E ──────────┐
    │   └── Health Backend State ────┼── BLOCKER 1.1
    │   └── Health Status Retrieval ─┘
    │
    ├── Gate B: Control E2E ─────────┤
    │   ├── Backend Endpoints ───────┤  (Functional)
    │   └── Client Integration ──────┼── BLOCKER 1.2
    │       ├── Action Names ────────┤
    │       ├── Polling Key ─────────┤
    │       └── Response Endpoint ───┤
    │
    └── Gate 0: Artifact Reconciliation
        └── Missing Artifact 11 ────── BLOCKER 1.3
```

---

## 6. Required Fixes Before Phase 1

### Must Fix (Blockers)
1. Implement health backend state persistence + status retrieval
2. Fix all 3 control client contract mismatches
3. Create Phase 0.2.4 artifact 11

### Should Fix (High Severity)
4. Remove ai_worker.py code duplication
5. Fix auth timing attacks + bypass
6. Add response idempotency
7. Add completed request history endpoint
8. Add path/body action validation

### Nice to Fix (Medium/Low)
9-20. See medium/low findings above

---

## 7. Current Phase 1 Eligibility

**NOT ELIGIBLE** — 3 Critical Blockers unresolved.

Per Phase 0.2.4 final verdict: "If either #1 or #2 remains unresolved: Phase 1 BLOCKED."

Both #1 (PipelineEngine health/control integration) and #2 (Legacy Backend control endpoints) remain unresolved because:
- Health backend incomplete (#1)
- Control client mismatches prevent integration (#2)

---

## 8. Evidence Classification

| Finding | Classification |
|---|---|
| Health backend scaffold | RUNTIME-VERIFIED |
| Control client mismatches | SOURCE-VERIFIED |
| Missing artifact 11 | SOURCE-VERIFIED |
| Code duplication | SOURCE-VERIFIED |
| Auth timing attack | SOURCE-VERIFIED |
| Auth bypass | RUNTIME-VERIFIED |
| Response idempotency | SOURCE-VERIFIED |
| No history endpoint | SOURCE-VERIFIED |
| Path/body validation | RUNTIME-VERIFIED |
| Hardcoded worker_id | SOURCE-VERIFIED |
| Client retry missing | SOURCE-VERIFIED |
| In-memory state loss | SOURCE-VERIFIED |
| Field name mismatches | SOURCE-VERIFIED |
| Camera stubs | SOURCE-VERIFIED |
| Missing GET_STATUS | SOURCE-VERIFIED |
| No uncertain state | SOURCE-VERIFIED |
| No rate limiting | SOURCE-VERIFIED |
| No timeout tracking | SOURCE-VERIFIED |