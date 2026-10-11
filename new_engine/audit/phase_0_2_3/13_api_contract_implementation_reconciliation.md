# Gate E — API Contract / Implementation Reconciliation

**Date:** 2026-10-04  
**Phase:** 0.2.3 — Gate E  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL RECONCILIATION

---

## 1. Executive Summary

This document reconciles API contracts with actual implementations across all four API areas. It identifies gaps between contract specifications and actual implementations.

---

## 2. Reconciliation Matrix

| Endpoint | Contract Spec | Implementation | Status | Gap |
|---|---|---|---|---|
| **POST /api/v1/attendance/events** | ✅ Defined in 08_api_contracts.md | ✅ Implemented in ai_worker.py | **FUNCTIONAL** | None |
| **POST /api/v1/health/ai-worker** | ✅ Defined in 05_health_api_contract.md | ⚠️ Scaffolded in ai_worker.py | **SCAFFOLDED** | PipelineEngine client integration incomplete |
| **POST /api/v1/ai/control/{action}** | ✅ Defined in 08_control_api_contract.md | ⚠️ Scaffolded in ai_worker.py | **SCAFFOLDED** | PipelineEngine control server needs Backend endpoint |
| **POST /api/v1/enrollment/reload** | ✅ Defined in 11_enrollment_authorization.md | ✅ Implemented in enrollment.py | **FUNCTIONAL** | None |
| **GET /api/v1/enrollment/reload/status** | ✅ Defined in 11_enrollment_authorization.md | ✅ Implemented in enrollment.py | **FUNCTIONAL** | None |

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

**Evidence:** `app/api/ai_worker.py` lines 130-180, `app/in_out/resolver.py`

---

### 3.2 POST /api/v1/health/ai-worker — SCAFFOLDED

| Aspect | Contract | Implementation | Match | Gap |
|---|---|---|---|---|
| Path | `/api/v1/health/ai-worker` | ✅ | ✅ | — |
| Method | POST | ✅ | ✅ | — |
| Auth | AI_WORKER_API_KEY | ✅ `verify_ai_worker_key` | ✅ | — |
| Request Schema | `AIWorkerHealthRequest` | ✅ Pydantic model | ✅ | — |
| Response Schema | `AIWorkerHealthResponse` | ✅ Pydantic model | ✅ | — |
| Health Persistence | Store state, detect anomalies | ❌ Not implemented | ❌ | Missing persistence |
| Anomaly Detection | Stale heartbeat, model unload | ❌ Not implemented | ❌ | Missing detection |
| Command Queue | Return control commands | ❌ Returns empty `[]` | ❌ | Missing queue |
| PipelineEngine Client | Send heartbeats | ⚠️ Client exists, not integrated | ❌ | Needs integration |

**Evidence:** `app/api/ai_worker.py` lines 131-200, `pipeline_engine/integration/health_client.py`

---

### 3.3 POST /api/v1/ai/control/{action} — SCAFFOLDED

| Aspect | Contract | Implementation | Match | Gap |
|---|---|---|---|---|
| Path | `/api/v1/ai/control/{action}` | ✅ | ✅ | — |
| Method | POST | ✅ | ✅ | — |
| Auth | AI_CONTROL_API_KEY | ✅ `verify_ai_control_key` | ✅ | — |
| Actions | 6 defined | ⚠️ 6 scaffolded | ⚠️ | Not connected to PipelineEngine |
| Idempotency | `idempotency_key` | ✅ In-memory set | ✅ | In-memory only |
| Response Format | `AIControlResponse` | ✅ | ✅ | — |
| PipelineEngine Transport | Message queue / HTTP | ❌ Not implemented | ❌ | No transport |
| Legacy Backend Pending Endpoint | `/ai/control/pending` | ❌ Not implemented | ❌ | Backend endpoint missing |
| Legacy Backend Response Endpoint | `/ai/control/{action}/response` | ❌ Not implemented | ❌ | Backend endpoint missing |

**Evidence:** `app/api/ai_worker.py` lines 155-280, `pipeline_engine/integration/control_client.py`

---

### 3.4 POST /api/v1/enrollment/reload — FUNCTIONAL

| Aspect | Contract | Implementation | Match |
|---|---|---|---|
| Path | `/api/v1/enrollment/reload` | ✅ | ✅ |
| Method | POST | ✅ | ✅ |
| Auth | ADMIN_API_KEY | ✅ `verify_admin_key` | ✅ |
| Request Schema | `EnrollmentReloadRequest` | ✅ | ✅ |
| Response Schema | `EnrollmentReloadResponse` | ✅ | ✅ |
| Validation | Shape, dtype, SHA256 | ✅ | ✅ |
| Atomic Swap | Validate before replace | ✅ | ✅ |
| Failure Preservation | Preserve previous | ✅ | ✅ |
| Version Tracking | `creation_timestamp` | ✅ | ✅ |

**Evidence:** `app/api/enrollment.py` lines 270-350

---

### 3.5 GET /api/v1/enrollment/reload/status — FUNCTIONAL

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
- `/api/v1/ai/control/{action}` POST
- `/api/v1/enrollment/reload` POST
- `/api/v1/enrollment/reload/status` GET

---

## 5. Classification Summary

| Endpoint | Classification | Evidence Level |
|---|---|---|
| `/api/v1/attendance/events` | **FUNCTIONAL** | INTEGRATION-TESTED |
| `/api/v1/health/ai-worker` | **SCAFFOLDED** | SOURCE-VERIFIED |
| `/api/v1/ai/control/{action}` | **SCAFFOLDED** | SOURCE-VERIFIED |
| `/api/v1/enrollment/reload` | **FUNCTIONAL** | INTEGRATION-TESTED |
| `/api/v1/enrollment/reload/status` | **FUNCTIONAL** | INTEGRATION-TESTED |

---

## 5. Gate E Verdict

**PARTIAL** — Two endpoints fully functional with tests passing. Two endpoints scaffolded awaiting PipelineEngine integration.

**To reach COMPLETE:**
1. Implement PipelineEngine health client integration (camera states, model readiness)
2. Implement Legacy Backend health persistence and anomaly detection
3. Implement Legacy Backend `/ai/control/pending` endpoint
4. Implement Legacy Backend `/ai/control/{action}/response` endpoint
5. Connect PipelineEngine control server to Legacy Backend polling
6. Implement CameraManager pause/resume methods
6. Add integration tests with mock backend