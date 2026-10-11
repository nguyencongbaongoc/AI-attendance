# Phase 1.V4 Retry and Failure Tests

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Failure Scenarios

### Scenario 1: Backend Temporary Unavailable
| Phase | Behavior |
|-------|----------|
| Queue | Events queued in EventDeliveryClient (max 1000) |
| Retry | Exponential backoff: 1s, 2s, 4s... max 30s |
| Max Retries | 3 |
| Recovery | Auto-deliver when backend returns |

### Scenario 2: Backend Returns 5xx
| Phase | Behavior |
|-------|----------|
| Retry | Yes (up to 3 times) |
| Backoff | Exponential |
| Permanent Failure | Moved to failed count after 3 retries |

### Scenario 3: Backend Returns 400 (Validation Error)
| Phase | Behavior |
|-------|----------|
| Retry | No (validation errors not retried) |
| Result | Failed count incremented |

### Scenario 4: Backend Returns 401 (Auth Failure)
| Phase | Behavior |
|-------|----------|
| Retry | No |
| Result | Failed, alert logged |

### Scenario 5: Backend Returns 409 (Duplicate)
| Phase | Behavior |
|-------|----------|
| Retry | No |
| Result | Treated as success (idempotent) |

---

## 2. EventDeliveryClient Failure Handling

### Queue Management
```python
# Max queue size: 1000
# On full: drop oldest, insert newest (latest-wins)
# Metrics: pending, delivered, failed, queue_depth
```

### Retry Logic
```python
for attempt in range(max_retries + 1):
    try:
        response = await client.post(...)
        if response.status_code == 200:
            return True
        elif response.status_code in (400, 401, 409):
            return False  # Don't retry
    except (httpx.TimeoutException, httpx.ConnectError):
        pass  # Retry
    
    if attempt < max_retries:
        delay = min(base_retry_delay * (retry_backoff ** attempt), max_retry_delay)
        await asyncio.sleep(delay)
```

---

## 2. Failure Test Plan

### Test 1: Backend Down During Operation
| Step | Action | Verify |
|------|--------|--------|
| 1 | Start CameraManager + EventDeliveryClient | Both running |
| 2 | Generate crossing event | Event queued |
| 3 | Stop backend | Event queued locally |
| 4 | Wait 10s | Event pending |
| 5 | Restart backend | Event delivered |
| 6 | Verify attendance.db | Record exists |

### Test 2: Backend Returns 500
| Step | Action | Verify |
|------|--------|--------|
| 1 | Configure backend to return 500 | - |
| 2 | Submit event | Event queued |
| 3 | Wait for retries | 3 retries with backoff |
| 4 | Fix backend | Event delivered |
| 5 | Verify single record | No duplicates |

### Test 3: Network Partition
| Step | Action | Verify |
|------|--------|--------|
| 1 | Block network to backend | Events queued |
| 2 | Wait 30s | Queue grows |
| 3 | Restore network | Events delivered |
| 4 | Verify no duplicates | attendance.db count |

### Test 4: Invalid Event Data
| Step | Action | Verify |
|------|--------|--------|
| 1 | Submit invalid event (missing fields) | 400 response |
| 2 | Verify not retried | Failed count = 1 |
| 3 | Submit valid event | Success |

---

## 3. EventDeliveryClient Metrics

### Failure Metrics
```python
stats = event_client.get_stats()
# {
#   "pending": 0,
#   "delivered": 10,
#   "failed": 2,
#   "queue_depth": 0,
#   "queue_max": 1000,
#   "queue_utilization_pct": 0.0
# }
```

### Health Check
```python
event_client.is_healthy()
# True if: client running, queue < 90% capacity
```

---

## 4. Test Status

### Status: READY FOR EXECUTION
- Test cases defined
- EventDeliveryClient implements retry/backoff
- Backend error handling implemented

### Pending: Live Execution
- Need to run tests with real backend failures
- Verify queue behavior under pressure
- Verify no duplicate records on recovery

---

## 4. Evidence

### Code Locations
- `pipeline_engine/integration/event_client.py:178-233` - Retry logic
- `pipeline_engine/integration/event_client.py:141-176` - Queue processing
- `app/api/ai_worker.py:206-212` - 409 handling
- `app/in_out/resolver.py:109-116` - Resolver deduplication

---

## 5. Next Steps

1. Execute failure tests with live backend
2. Verify queue behavior under pressure
3. Verify no duplicate records on recovery
4. Document results in V4 verdict