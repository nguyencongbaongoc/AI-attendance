# Phase 0.2.6 Health Test Evidence

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Test Execution Summary

**Test Script:** `new_engine/audit/phase_0_2_6/health_integration_test.py`  
**Backend:** FastAPI TestClient (in-process, isolated)  
**Environment:** `AI_WORKER_API_KEY=test-worker-key-123`  
**Result:** **13/13 PASS** (0 FAIL, 0 ERROR)

---

## 2. Test Results Detail

| # | Test | Expected | Actual | Status |
|---|---|---|---|---|
| 1 | Valid health report accepted | 200 | 200 | PASS |
| 2 | Invalid state rejected | 400 | 400 | PASS |
| 3 | Duplicate sequence rejected | 400 | 400 | PASS |
| 4 | Out-of-order sequence rejected | 400 | 400 | PASS |
| 5 | Worker restart (seq reset) accepted | 200 | 200 | PASS |
| 6 | Invalid API key rejected | 401 | 401 | PASS |
| 7 | Missing API key rejected | 422 | 422 | PASS |
| 8 | Status retrieval for existing worker | 200 | 200 | PASS |
| 9 | Unknown worker returns 404 | 404 | 404 | PASS |
| 10 | Status returns correct sequence | 200, seq=5 | 200, seq=5 | PASS |
| 11 | Stale worker detection active | 200 | 200 | PASS |
| 12 | Health response includes pending commands | 200, commands=["GET_STATUS"] | 200, commands=["GET_STATUS"] | PASS |
| 13 | Full health report accepted | 200 | 200 | PASS |

---

## 3. Detailed Evidence

### Test 1: Valid Health Report
```
POST /api/v1/health/ai-worker
Headers: X-API-Key: test-worker-key-123
Body: {"worker_id": "test_worker_1", "worker_version": "1.0.0", "state": "ready", "timestamp": 1791086968.11, "sequence_number": 1}
Response: 200 OK
{"success": true, "worker_id": "test_worker_1", "acknowledged": true, "server_timestamp": 1791086968.12, "sequence_number": 1, "commands": [], "stale_threshold_seconds": 30.0}
```

### Test 2: Invalid State
```
POST /api/v1/health/ai-worker
Body: {"state": "invalid_state", ...}
Response: 400 Bad Request
{"detail": "Invalid state 'invalid_state'. Valid: ['degraded', 'failed', 'initializing', 'ready', 'starting', 'stopped', 'stopping']"}
```

### Test 3: Duplicate Sequence
```
POST seq=1 → 200 OK
POST seq=1 (duplicate) → 400 Bad Request
{"detail": "Stale or duplicate sequence: got 1, last was 1"}
```

### Test 4: Out-of-Order
```
POST seq=1 → 200 OK
POST seq=3 (skip 2) → 400 Bad Request
{"detail": "Sequence gap: got 3, expected 2"}
```

### Test 5: Worker Restart
```
POST seq=1 → 200 OK (gen=1)
POST seq=2 → 200 OK (gen=1)
POST seq=1 (restart) → 200 OK (gen=2)
Log: "Worker test_worker_1_restart restarted (sequence reset), new generation: 2"
```

### Test 8-10: Status Retrieval
```
GET /api/v1/health/ai-worker/{worker_id}
Response: 200 OK
{"success": true, "worker_id": "test_worker_1_status", "acknowledged": true, "server_timestamp": ..., "sequence_number": 1, "commands": [], "stale_threshold_seconds": 30.0}
```

### Test 12: Control Commands
```
1. POST /api/v1/ai/control/GET_STATUS (admin)
2. POST /api/v1/health/ai-worker (worker)
Response: 200 OK, "commands": ["GET_STATUS"]
```

---

## 4. Log Evidence

Key log entries from test execution:
```
INFO - Worker test_worker_1_restart restarted (sequence reset), new generation: 2
WARNING - Health validation failed for test_worker_1: Invalid state 'invalid_state'...
WARNING - Health validation failed for test_worker_1_dup: Stale or duplicate sequence: got 1, last was 1
WARNING - Health validation failed for test_worker_1_ooo: Sequence gap: got 3, expected 2
INFO - Control request queued: GET_STATUS for worker/test_worker_1_cmd
```

---

## 5. Classification

| Assertion | Classification |
|---|---|
| Valid report accepted | RUNTIME-VERIFIED |
| State enum validated | RUNTIME-VERIFIED |
| Sequence validation works | RUNTIME-VERIFIED |
| Worker restart detection works | RUNTIME-VERIFIED |
| Auth fail-closed | RUNTIME-VERIFIED |
| Status retrieval works | RUNTIME-VERIFIED |
| Control commands returned | RUNTIME-VERIFIED |
| Stale detection active | RUNTIME-VERIFIED (mechanism verified) |