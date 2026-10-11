# Phase 1.V4 Idempotency Tests

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Idempotency Requirements

### CrossingEvent Idempotency
- **Deterministic Event ID**: Generated from `camera_id:track_id:frame_index:geometry_version:geometry_config_hash`
- **Same crossing** → **Same event_id** → Deduplicated

### RawInOutEvent Idempotency (Phase 23)
```python
# In RawEventEngine
def process_crossing_event(self, crossing_event):
    # Generate deterministic event ID
    event_id = generate_deterministic_event_id(...)
    
    # Check for duplicate
    if event_id in self._processed_event_ids:
        return existing_event  # Return existing, no new event
```

### Resolver Idempotency (Phase 24)
```python
# In RepeatedInOutResolver
def resolve_single(self, raw_event):
    # Check for duplicate
    if raw_event.event_id in self._processed_raw_event_ids:
        return existing_transition  # Return existing, no new transition
```

### Backend API Idempotency
```python
# In ai_worker.py - ingest_attendance_event
# Check idempotency key
if request.idempotency_key in _processed_idempotency_keys:
    return stored_response  # Return stored response
```

---

## 2. Idempotency Test Scenarios

### Scenario 1: Duplicate Event Submission
| Step | Action | Expected |
|------|--------|----------|
| 1 | Submit event E1 | Accepted, resolution_id = R1 |
| 2 | Submit event E1 again | Accepted, resolution_id = R1 (same) |
| 3 | Check attendance.db | 1 record |

### Scenario 2: Retry After Failure
| Step | Action | Expected |
|------|--------|----------|
| 1 | Submit event E2 | Network error |
| 2 | Client retries E2 | Accepted, resolution_id = R2 |
| 3 | Check attendance.db | 1 record |

### Scenario 3: Concurrent Duplicate Events
| Step | Action | Expected |
|------|--------|----------|
| 1 | Submit E3 from thread A | Accepted |
| 2 | Submit E3 from thread B | Accepted (deduplicated) |
| 3 | Check attendance.db | 1 record |

### Scenario 4: Out-of-Order Retry
| Step | Action | Expected |
|------|--------|----------|
| 1 | Submit E4 (timestamp T1) | Accepted |
| 2 | Submit E5 (timestamp T0, earlier) | Processed per out-of-order policy |
| 3 | Check order | Resolver handles per policy |

---

## 3. Test Implementation

### Automated Test
```python
async def test_event_idempotency():
    # 1. Create test event
    event = create_test_event(event_id="idem-test-001")
    
    # 2. Submit first time
    resp1 = await event_client.submit_event(event)
    assert resp1.success
    resolution_id_1 = resp1.source_resolution_id
    
    # 3. Submit duplicate
    resp2 = await event_client.submit_event(event)
    assert resp2.success
    resolution_id_2 = resp2.source_resolution_id
    
    # 4. Verify same resolution
    assert resolution_id_1 == resolution_id_2
    
    # 5. Verify single attendance record
    records = query_attendance_records(event_id="idem-test-001")
    assert len(records) == 1
```

### Retry Test
```python
async def test_event_retry():
    # 1. Stop backend
    stop_backend()
    
    # 2. Queue event locally
    event = create_test_event(event_id="retry-test-001")
    await event_client.submit_event(event)  # Queued locally
    
    # 3. Start backend
    start_backend()
    
    # 5. Wait for delivery
    await wait_for_delivery("retry-test-001")
    
    # 6. Verify delivered
    stats = event_client.get_stats()
    assert stats["delivered"] >= 1
```

---

## 4. Idempotency Test Results

### Status: READY FOR EXECUTION
- Test cases defined
- EventDeliveryClient implements idempotency
- Backend implements idempotency
- Resolver implements deduplication

### Pending: Live Execution
- Need to run tests with real events
- Verify no duplicate attendance records
- Verify retry behavior

---

## 5. Evidence

### Code Locations
- `pipeline_engine/integration/event_client.py:112-117` - Client deduplication
- `app/api/ai_worker.py:112-117` - API key verification + deduplication
- `app/in_out/raw_event.py:205-216` - RawEventEngine deduplication
- `app/in_out/resolver.py:109-116` - Resolver deduplication

---

## 6. Next Steps

1. Execute automated idempotency tests
2. Verify zero duplicate attendance records
2. Test retry scenarios
3. Document results in V4 verdict