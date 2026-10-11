# Gate G — API Endpoint Reconciliation

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Gate G  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL RECONCILIATION

---

## 1. Executive Summary

This document reconciles API contracts with actual implementations across all four API areas. It identifies gaps between contract specifications and actual implementations.

---

## 2. Reconciliation Matrix

| Endpoint | Contract Spec | Implementation | Status | Gap |
|---|---|---|---|---|
| **POST /api/v1/attendance/events** | ✅ Defined in `08_api_contracts.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | None |
| **POST /api/v1/health/ai-worker** | ✅ Defined in `05_health_api_contract.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | Backend state management added |
| **GET /api/v1/ai/control/pending** | ✅ Defined in `06_control_contract_final.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | None |
| **POST /api/v1/ai/control/{action}/response** | ✅ Defined in `06_control_contract_final.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | None |
| **POST /api/v1/ai/control/{action}** | ✅ Defined in `06_control_contract_final.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | None |
| **POST /api/v1/enrollment/reload** | ✅ Defined in `11_enrollment_authorization.md` | ✅ Implemented in `enrollment.py` | **FUNCTIONAL** | None |
| **GET /api/v1/enrollment/reload/status** | ✅ Defined in `11_enrollment_authorization.md` | ✅ Implemented in `enrollment.py` | **FUNCTIONAL** | None |
| **POST /api/v1/health/ai-worker** | ✅ Defined in `05_health_api_contract.md` | ✅ Implemented in `ai_worker.py` | **FUNCTIONAL** | Backend state management added |

---

## 3. Detailed Endpoint Reconciliation

### 3.1 POST /api/v1/attendance/events — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/attendance/events` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | AI_WORKER_API_KEY | ✅ `verify_ai_worker_key` | ✅ |
| Request Schema | `CrossingEventRequest` | ✅ Pydantic model | ✅ |
| Response Schema | `CrossingEventResponse` | ✅ Pydantic model | ✅ |
| Idempotency | `event_id` | ✅ Uses `event_id` as dedup key | ✅ |
| Integration | RawInOutEvent → Resolver | ✅ Calls `RepeatedInOutResolver` | ✅ |
| Returns | `source_resolution_id` | ✅ Returns from resolver | ✅ |

**Evidence:** `app/api/ai_worker.py` lines 197-263, `app/in_out/resolver.py`

---

### 3.2 POST /api/v1/health/ai-worker — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/health/ai-worker` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | AI_WORKER_API_KEY | ✅ `verify_ai_worker_key` | ✅ |
| Request Schema | `AIWorkerHealthRequest` | ✅ Pydantic model | ✅ |
| Response Schema | `AIWorkerHealthResponse` | ✅ Pydantic model | ✅ |
| Health Persistence | Store state, detect anomalies | ✅ Backend state management added | ✅ |
| Anomaly Detection | Stale heartbeat, model unload | ✅ Stale detection loop | ✅ |
| Command Queue | Return control commands | ✅ Returns commands array | ✅ |
| PipelineEngine Client | Send heartbeats | ✅ Client implemented | ✅ |

**Evidence:** `app/api/ai_worker.py` lines 270-297, `pipeline_engine/integration/health_client.py`, `app/api/ai_worker.py` health state management

---

### 3.3 GET /api/v1/ai/control/pending — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/ai/control/pending` | ✅ | ✅ |
| Method | GET | ✅ | ✅ |
| Auth | AI_CONTROL_API_KEY | ✅ `verify_ai_control_key` | ✅ |
| Query Params | `worker_id`, `limit`, `since` | ✅ | ✅ |
| Response Model | `PendingControlRequests` | ✅ | ✅ |
| Filtering Logic | Worker ID, TTL, expiration, limit | ✅ | ✅ |

**Evidence:** `app/api/ai_worker.py` lines 400-450, `07_control_pending_endpoint.md`

---

### 3.4 POST /api/v1/ai/control/{action}/response — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/ai/control/{action}/response` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | AI_CONTROL_API_KEY | ✅ | ✅ |
| Path Param | `action` (6 values) | ✅ Validated | ✅ |
| Request Body | `ControlResponse` | ✅ | ✅ |
| Pending Lookup | `_pending_control_requests` | ✅ | ✅ |
| Status Update | Updates pending request | ✅ | ✅ |

**Evidence:** `app/api/ai_worker.py` lines 450-520, `08_control_response_endpoint.md`

---

### 3.5 POST /api/v1/ai/control/{action} — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/ai/control/{action}` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | ADMIN_API_KEY | ✅ `verify_admin_key` | ✅ |
| Actions | 6 supported | ✅ All 6 implemented | ✅ |
| Idempotency | `idempotency_key` | ✅ In-memory set | ✅ |
| Pending Queue | `_pending_control_requests` | ✅ | ✅ |
| Response | Immediate PENDING ack | ✅ | ✅ |

**Evidence:** `app/api/ai_worker.py` lines 300-400, `06_control_contract_final.md`

---

### 3.6 POST /api/v1/enrollment/reload — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/enrollment/reload` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | ADMIN_API_KEY | ✅ `verify_admin_key` | ✅ |
| Request Schema | `EnrollmentReloadRequest` | ✅ | ✅ |
| Response Schema | `EnrollmentReloadResponse` | ✅ | ✅ |
| Validation | Shape (512), dtype, SHA256 | ✅ | ✅ |
| Atomic Swap | Validate before replace | ✅ | ✅ |
| Failure Preservation | Preserve previous | ✅ | ✅ |
| Version Tracking | `creation_timestamp` | ✅ | ✅ |

**Evidence:** `app/api/enrollment.py` lines 270-350

---

### 3.7 GET /api/v1/enrollment/reload/status — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/enrollment/reload/status` | ✅ | ✅ |
| Method | GET | ✅ | ✅ |
| Auth | ADMIN_API_KEY | ✅ | ✅ |
| Response | `EnrollmentReloadResponse` | ✅ | ✅ |
| No Reload | Returns current status | ✅ | ✅ |

**Evidence:** `app/api/enrollment.py` lines 317-350

---

## 4. Route Registration Verification

All routes registered in `app/main.py`:

```python
for router in [health_router, websocket_router, attendance_router, persons_router, 
               timetable_router, excel_router, parent_telegram_router, geometry_router, 
               enrollment_router, ai_worker_router, replay_router, provenance_router]:
    for route in router.routes:
        app.router.routes.append(route)
```

**Verified Routes:**
- `/api/v1/attendance/events` POST
- `/api/v1/health/ai-worker` POST
- `/api/v1/ai/control/pending` GET
- `/api/v1/ai/control/{action}/response` POST
- `/api/v1/ai/control/{action}` POST
- `/api/v1/enrollment/reload` POST
- `/api/v1/enrollment/reload/status` GET

---

## 5. Classification Summary

| Endpoint | Classification | Evidence Level |
|---|---|---|
| `/api/v1/attendance/events` | **FUNCTIONAL** | INTEGRATION-TESTED |
| `/api/v1/health/ai-worker` | **FUNCTIONAL** | INTEGRATION-TESTED |
| `/api/v1/ai/control/pending` | **FUNCTIONAL** | UNIT-TESTED |
| `/api/v1/ai/control/{action}/response` | **FUNCTIONAL** | UNIT-TESTED |
| `/api/v1/ai/control/{action}` | **FUNCTIONAL** | UNIT-TESTED |
| `/api/v1/enrollment/reload` | **FUNCTIONAL** | INTEGRATION-TESTED |
| `/api/v1/enrollment/reload/status` | **FUNCTIONAL** | INTEGRATION-TESTED |

---

## 5. Gate G Verdict

**PASS** — All 7 endpoints fully functional with tests passing. Contract and implementation fully reconciled.

---

**Gate G: COMPLETE**