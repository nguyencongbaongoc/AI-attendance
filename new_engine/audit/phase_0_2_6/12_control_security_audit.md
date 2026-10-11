# Phase 0.2.6 Control Security Audit

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Authentication Dependencies

### 1.1 Admin Key (Control Submission)
```python
async def verify_admin_key(x_api_key: str = Header(...)):
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API key not configured")
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid Admin API key")
    return True
```
- Constant-time comparison
- Fail-closed if not configured
- Required on: `POST /ai/control/{action}`, `GET /ai/control/history`

### 1.2 Control Key (Poll/Response)
```python
async def verify_ai_control_key(x_api_key: str = Header(...)):
    expected = os.environ.get("AI_CONTROL_API_KEY")
    if not expected:
        raise HTTPException(503, "AI Control API key not configured")
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid AI Control API key")
    return True
```
- Constant-time comparison
- Fail-closed if not configured
- Required on: `GET /ai/control/pending`, `POST /ai/control/{action}/response`, `GET /ai/control/status`

### 1.3 Worker Key (Health)
```python
async def verify_ai_worker_key(x_api_key: str = Header(...)):
    expected = os.environ.get("AI_WORKER_API_KEY")
    if not expected:
        raise HTTPException(503, "AI Worker API key not configured")
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid AI Worker API key")
    return True
```
- Constant-time comparison
- Fail-closed if not configured
- Required on: `POST /health/ai-worker`, `GET /health/ai-worker/{id}`

---

## 2. Role Separation Matrix

| Endpoint | Admin | Control | Worker |
|---|---|---|---|
| `POST /ai/control/{action}` | PASS | 401 | 401 |
| `GET /ai/control/pending` | 401 | PASS | 401 |
| `POST /ai/control/{action}/response` | 401 | PASS | 401 |
| `GET /ai/control/status` | 401 | PASS | 401 |
| `GET /ai/control/history` | PASS | 401 | 401 |
| `POST /health/ai-worker` | 401 | 401 | PASS |
| `GET /health/ai-worker/{id}` | 401 | 401 | PASS |

---

## 3. Input Validation

| Validation | Implementation |
|---|---|
| Action enum | Backend: `valid_actions` set check |
| Target | `worker` or `camera` |
| Camera target_id required | For camera actions |
| Request ID required | On response submission |
| Path/Body action match | `path_action == body_action` |
| Worker ID match | `request.target_id == response.worker_id` |
| Idempotency key | Tracked on submit |
| Expiration | `expires_at` checked on poll |

---

## 4. Security Gaps Addressed in 0.2.6

| Gap | Before | After |
|---|---|---|
| Worker/Control auth bypass | `if expected and key != expected` | Fail-closed + constant-time |
| Timing attack | `!=` comparison | `secrets.compare_digest` |
| Path/Body action mismatch | Not validated | Validated 400 |
| Worker ID mismatch | Not validated | Validated 400 |
| Hardcoded worker_id in idempotency | `"pipeline_engine_1"` | `request.target_id` |

---

## 5. Test Evidence

All 17 control integration tests PASS including:
- Worker key rejected on admin endpoint (401)
- Control key rejected on admin endpoint (401)
- Admin key rejected on worker poll endpoint (401)
- Invalid action rejected (400)
- Missing target_id for camera actions (400)
- Path/Body action mismatch rejected (400)
- Unknown request_id response (404)
- Role separation enforced

---

## 6. Remaining Considerations

| Item | Status |
|---|---|
| Rate limiting | Not implemented |
| Audit logging | Basic logging only |
| Encryption at rest | N/A (in-memory) |
| Key rotation | Manual env var change |
| Response replay protection | Terminal states idempotent |