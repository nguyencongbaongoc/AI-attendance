# Phase 1.V4 Worker Authorization Tests

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Authorization Model

### Three-Tier API Keys
| Key | Environment Variable | Purpose | Endpoints |
|-----|---------------------|---------|-----------|
| AI_WORKER_API_KEY | AI_WORKER_API_KEY | Event ingestion + Health reporting | POST /api/v1/attendance/events, POST /api/v1/health/ai-worker |
| AI_CONTROL_API_KEY | AI_CONTROL_API_KEY | Control command polling | GET /api/v1/ai/control/pending, POST /api/v1/ai/control/{action}/response |
| ADMIN_API_KEY | ADMIN_API_KEY | Admin operations | POST /api/v1/ai/control/{action}, POST /api/v1/enrollment/*, GET /api/v1/ai/control/history |

---

## 2. Authorization Test Scenarios

### Test 1: Worker Can Ingest Events
| Role | Endpoint | Expected |
|------|----------|----------|
| AI_WORKER | POST /api/v1/attendance/events | 200 OK |

### Test 2: Worker Can Report Health
| Role | Endpoint | Expected |
|------|----------|----------|
| AI_WORKER | POST /api/v1/health/ai-worker | 200 OK |

### Test 3: Worker CANNOT Access Admin Endpoints
| Role | Endpoint | Expected |
|------|----------|----------|
| AI_WORKER | POST /api/v1/ai/control/START_WORKER | 401 Unauthorized |
| AI_WORKER | POST /api/v1/enrollment/persons | 401 Unauthorized |
| AI_WORKER | POST /api/v1/enrollment/reload | 401 Unauthorized |

### Test 4: Control Can Poll Commands
| Role | Endpoint | Expected |
|------|----------|----------|
| AI_CONTROL | GET /api/v1/ai/control/pending | 200 OK |

### Test 5: Control CANNOT Ingest Events
| Role | Endpoint | Expected |
|------|----------|----------|
| AI_CONTROL | POST /api/v1/attendance/events | 401 Unauthorized |

### Test 6: Admin Can Submit Control Commands
| Role | Endpoint | Expected |
|------|----------|----------|
| ADMIN | POST /api/v1/ai/control/START_WORKER | 200 OK |

### Test 7: Admin Can Reload Enrollment
| Role | Endpoint | Expected |
|------|----------|----------|
| ADMIN | POST /api/v1/enrollment/reload | 200 OK |

### Test 8: Invalid Key Rejected
| Key | Endpoint | Expected |
|-----|----------|----------|
| Invalid | POST /api/v1/attendance/events | 401 Unauthorized |
| Missing | POST /api/v1/attendance/events | 401 Unauthorized |

---

## 3. Authorization Test Commands

### Test Worker Access (Valid Key)
```bash
curl -X POST http://localhost:18693/api/v1/attendance/events \
  -H "X-API-Key: worker-test-key-1234567890123456" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"test","camera_id":"cam1","track_id":1,"direction":"in","timestamp":1234567890,"frame_index":1,"stream_epoch":0,"pts":0,"time_base":{"num":1,"den":90000},"capture_timestamp":1234567890,"processing_timestamp":1234567890,"model_version":"test","enrollment_version":"0","provenance":"test","schema_version":"1.0"}'
# Expected: 200 OK
```

### Test Worker Access (Invalid Key)
```bash
curl -X POST http://localhost:18693/api/v1/attendance/events \
  -H "X-API-Key: invalid-key" \
  -H "Content-Type: application/json" \
  -d '...'
# Expected: 401 Unauthorized
```

### Test Worker Cannot Access Admin
```bash
curl -X POST http://localhost:18693/api/v1/ai/control/START_WORKER \
  -H "X-API-Key: worker-test-key-1234567890123456" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"test","action":"START_WORKER","target":"worker","target_id":"test","idempotency_key":"test","expires_at":9999999999}'
# Expected: 401 Unauthorized
```

### Test Admin Can Control
```bash
curl -X POST http://localhost:18693/api/v1/ai/control/START_WORKER \
  -H "X-API-Key: admin-test-key-1234567890123456" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"test","action":"START_WORKER","target":"worker","target_id":"pipeline_engine_1","idempotency_key":"test","expires_at":9999999999}'
# Expected: 200 OK
```

---

## 3. Worker Authorization Test Results

### Status: READY FOR EXECUTION
- All test cases defined
- Authorization middleware implemented in `app/api/ai_worker.py`
- Three-tier key separation implemented

### Pending: Live Execution
- Need to run tests against live backend
- Verify 401 responses for unauthorized access
- Verify 200 for authorized access

---

## 4. Code Locations

### Authorization Middleware
- `app/api/ai_worker.py:36-47` - `verify_ai_worker_key()`
- `app/api/ai_worker.py:50-61` - `verify_ai_control_key()`
- `app/api/ai_worker.py:64-78` - `verify_admin_key()`

### Endpoint Dependencies
- `POST /api/v1/attendance/events` - `Depends(verify_ai_worker_key)`
- `POST /api/v1/health/ai-worker` - `Depends(verify_ai_worker_key)`
- `GET /api/v1/ai/control/pending` - `Depends(verify_ai_control_key)`
- `POST /api/v1/ai/control/{action}` - `Depends(verify_admin_key)`
- `POST /api/v1/enrollment/reload` - `Depends(verify_admin_key)`

---

## 4. Next Steps

1. Execute authorization tests against live backend
2. Verify 401/200 responses as expected
3. Document results in V4 verdict