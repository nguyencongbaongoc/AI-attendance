# Phase 0.2.6 Control Test Evidence

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Test Execution Summary

**Test Script:** `new_engine/audit/phase_0_2_6/control_integration_test.py`  
**Backend:** FastAPI TestClient (in-process, isolated)  
**Environment:** Three distinct API keys configured  
**Result:** **17/17 PASS** (0 FAIL, 0 ERROR)

---

## 2. Test Results Detail

| # | Test Category | Test | Expected | Actual | Status |
|---|---|---|---|---|---|
| 1 | Backend | Submit START_WORKER | 200 | 200 | PASS |
| 2 | Backend | Submit GET_STATUS | 200 | 200 | PASS |
| 3 | Backend | Poll pending requests | 200, `requests` key | 200, `requests` key | PASS |
| 4 | Backend | Submit control response | 200 | 200 | PASS |
| 5 | Backend | Path/body mismatch rejected | 400 | 400 | PASS |
| 6 | Client Contract | Action enum matches backend | All 6 match | All 6 match | PASS |
| 7 | Client Contract | ControlResult enum matches | All 7 match | All 7 match | PASS |
| 8 | Client Contract | Polling uses `requests` key | Source contains `data.get("requests"` | Found | PASS |
| 9 | Client Contract | Response uses `response.action` | Source contains `response.action` | Found | PASS |
| 10 | Client Contract | Has GET_STATUS handler | Handler exists | Found | PASS |
| 11 | E2E Simulation | Client poll retrieves commands | Request in `requests` | Found | PASS |
| 12 | E2E Simulation | Client response submission | 200 | 200 | PASS |
| 13 | Lifecycle | PENDING -> COMPLETED filtered | Completed not in pending | Confirmed | PASS |
| 14 | Lifecycle | History endpoint returns completed | 200, records > 0 | 200, records > 0 | PASS |
| 15 | Auth | Worker key rejected on admin | 401 | 401 | PASS |
| 16 | Auth | Control key rejected on admin | 401 | 401 | PASS |
| 17 | Auth | Admin key rejected on poll | 401 | 401 | PASS |

---

## 3. Key Evidence

### Backend Endpoint Verification
```
POST /api/v1/ai/control/START_WORKER -> 200 OK
{"success": true, "request_id": "...", "status": "PENDING", "message": "Control request queued for PipelineEngine"}

GET /api/v1/ai/control/pending?worker_id=pipeline_engine_1 -> 200 OK
{"worker_id": "pipeline_engine_1", "requests": [{"request_id": "...", "action": "GET_STATUS", "target": "worker", "target_id": "pipeline_engine_1", ...}]}

POST /api/v1/ai/control/GET_STATUS/response -> 200 OK
{"success": true, "message": "Response recorded"}

POST /api/v1/ai/control/STOP_WORKER/response with body action=GET_STATUS -> 400 Bad Request
{"detail": "Path action 'STOP_WORKER' does not match body action 'GET_STATUS'"}
```

### Client Contract Verification
```
Action enum: START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS PASS
ControlResult enum: PENDING, ACCEPTED, RUNNING, COMPLETED, FAILED, REJECTED, EXPIRED PASS
_poll_commands source contains: data.get("requests" PASS
_send_response source contains: response.action PASS
_hasattr(_handle_get_status) PASS
```

### E2E Simulation
```
1. Admin submits GET_STATUS command
2. Client polls GET /ai/control/pending -> receives request in "requests" array
3. Client posts to /api/v1/ai/control/GET_STATUS/response (uses response.action in path)
4. Backend accepts response, marks COMPLETED
5. Subsequent poll shows request filtered out (completed)
6. History endpoint returns completed command record
```

---

## 4. Log Evidence

```
INFO - Control request queued: GET_STATUS for worker/pipeline_engine_1
INFO - Control response received: GET_STATUS for <request_id> - COMPLETED
INFO - Control request queued: START_WORKER for worker/pipeline_engine_1
```

---

## 5. Classification

| Assertion | Classification |
|---|---|
| Backend endpoints functional | RUNTIME-VERIFIED |
| Action vocabulary aligned | SOURCE-VERIFIED |
| Polling key fixed | SOURCE-VERIFIED |
| Response endpoint fixed | SOURCE-VERIFIED |
| GET_STATUS handler added | SOURCE-VERIFIED |
| E2E simulation works | RUNTIME-VERIFIED |
| Path/body validation works | RUNTIME-VERIFIED |
| History endpoint works | RUNTIME-VERIFIED |
| Role separation enforced | RUNTIME-VERIFIED |