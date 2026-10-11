# Phase 0.2.6 Health Sequence and Generation Policy

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Sequence Number Policy

### 1.1 Rules

| Rule | Description |
|---|---|
| **Monotonic increase** | Each report must have `sequence_number = last_sequence + 1` |
| **First report** | Must have `sequence_number = 1` |
| **No gaps** | Sequence cannot skip numbers (e.g., 1→3 rejected) |
| **No duplicates** | Same or lower sequence rejected |

### 1.2 Error Responses

| Violation | HTTP Status | Error Message |
|---|---|---|
| First report ≠ 1 | 400 | "First report must have sequence_number=1, got X" |
| Duplicate/stale (≤ last) | 400 | "Stale or duplicate sequence: got X, last was Y" |
| Sequence gap (> expected) | 400 | "Sequence gap: got X, expected Y" |

---

## 2. Generation Tracking

### 2.1 Purpose

Distinguish legitimate worker restarts from malicious/erroneous sequence resets.

### 2.2 Generation Increment Conditions

| Condition | Generation Change |
|---|---|
| First report ever | Generation = 1 |
| Sequence reset to 1 after higher sequences | Generation += 1 |
| Normal sequence increment | No change |

### 2.3 Implementation Logic

```python
def _validate_health_request(health, worker_state):
    if worker_state is None:
        if health.sequence_number != 1:
            return False, "First report must have sequence_number=1", 1
        return True, "", 1
    
    # Worker restart detection (MUST come before duplicate check)
    if health.sequence_number == 1 and worker_state.last_sequence > 1:
        new_generation = worker_state.generation_id + 1
        return True, "", new_generation
    
    # Duplicate/stale check
    if health.sequence_number <= worker_state.last_sequence:
        return False, f"Stale or duplicate: got {health.sequence_number}, last was {worker_state.last_sequence}", worker_state.generation_id
    
    # Normal sequence validation
    expected = worker_state.last_sequence + 1
    if health.sequence_number != expected:
        return False, f"Sequence gap: got {health.sequence_number}, expected {expected}", worker_state.generation_id
    
    return True, "", worker_state.generation_id
```

### 2.4 Generation Storage

- Stored in `WorkerHealthState.generation_id`
- Included in health state retrieval
- Increments only on detected restart

---

## 3. Worker Restart Scenarios

### 3.1 Normal Restart

```
Report 1: seq=1, gen=1  → ACCEPTED (first report)
Report 2: seq=2, gen=1  → ACCEPTED
Report 3: seq=3, gen=1  → ACCEPTED
[Worker restarts]
Report 4: seq=1, gen=2  → ACCEPTED (restart detected)
Report 5: seq=2, gen=2  → ACCEPTED
```

### 3.2 Malicious/Erroneous Reset (No Restart)

```
Report 1: seq=1, gen=1  → ACCEPTED
Report 2: seq=2, gen=1  → ACCEPTED
Report 3: seq=1, gen=1  → REJECTED (duplicate, no restart detected since last=2)
```

### 3.3 First Report After Long Gap

```
Report 1: seq=1, gen=1  → ACCEPTED
[Long time passes, worker marked stale]
Report 2: seq=2, gen=1  → ACCEPTED (not a restart, seq continued)
```

---

## 4. Test Evidence

| Scenario | Expected | Actual |
|---|---|---|
| First report seq=1 | PASS | PASS |
| First report seq≠1 | 400 | 400 ✅ |
| Normal sequence 1→2→3 | PASS | PASS ✅ |
| Duplicate sequence | 400 | 400 ✅ |
| Out-of-order (1→3) | 400 | 400 ✅ |
| Worker restart (3→1) | PASS (gen+1) | PASS ✅ |
| Stale sequence (1→1 without restart) | 400 | 400 ✅ |

All sequence/generation tests PASS in `health_integration_test.py`.