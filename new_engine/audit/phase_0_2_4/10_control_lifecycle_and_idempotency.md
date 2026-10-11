# Gate C — Control Lifecycle and Idempotency

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Gate C/D  
**Classification:** SOURCE-VERIFIED / ARCHITECTURAL DESIGN

---

## 1. Executive Summary

This document defines the complete lifecycle of a control request from submission to completion, including idempotency guarantees, replay handling, and failure recovery.

---

## 2. Control Request Lifecycle

### 2.1 Lifecycle States

```
PENDING → ACCEPTED → RUNNING → COMPLETED
                    ↓
                 FAILED
                    ↓
                 REJECTED
                    ↓
                 EXPIRED
```

### 2.2 State Definitions

| Status | Meaning | Terminal? |
|---|---|---|
| PENDING | Request queued, not yet polled | NO |
| ACCEPTED | PipelineEngine acknowledged request | NO |
| RUNNING | Operation in progress | NO |
| COMPLETED | Operation completed successfully | YES |
| FAILED | Operation failed | YES |
| REJECTED | Request invalid or not allowed | YES |
| EXPIRED | Request TTL exceeded | YES |

---

## 2.3 State Transitions

```
PENDING → ACCEPTED (PipelineEngine polls and acknowledges)
ACCEPTED → RUNNING (Execution starts)
RUNNING → COMPLETED (Success)
RUNNING → FAILED (Execution error)
PENDING → REJECTED (Invalid request)
PENDING/ACCEPTED/RUNNING → EXPIRED (TTL exceeded)
```

---

## 3. Idempotency Design

### 3.1 Idempotency Key

- Every control request MUST include `idempotency_key` (UUID v4)
- Legacy Backend stores `idempotency_key → response` mapping
- PipelineEngine tracks processed `idempotency_key` set
- Duplicate key → return original response immediately
- Key expires after 24 hours

### 3.2 Idempotency Behavior

| Scenario | Behavior |
|---|---|
| First request | Process, store key→response, return response |
| Duplicate key | Return stored response immediately |
| Different key, same action | Process as new request |
| Expired key (>24h) | Process as new request |

### 3.3 Implementation

**Legacy Backend (Legacy Backend):**
```python
# In app/api/ai_worker.py
_processed_idempotency_keys: Dict[str, ControlResponse] = {}

# In submit_control_request:
if request.idempotency_key in _processed_idempotency_keys:
    stored = _processed_idempotency_keys[request.idempotency_key]
    return {
        "success": True,
        "request_id": request.request_id,
        "status": "DUPLICATE",
        "message": "Duplicate request, returning stored response",
        "original_response": stored.dict()
    }
```

**PipelineEngine (PipelineEngine):**
```python
# In pipeline_engine/integration/control_client.py
_processed_keys: set = set()
_processed_keys_lock = asyncio.Lock()

async def _execute_command(self, cmd: Dict[str, Any]) -> None:
    request = ControlRequest(...)
    
    # Check idempotency
    async with self._processed_keys_lock:
        if request.idempotency_key in self._processed_keys:
            logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
            return
            
        # ... execute ...
        
        async with self._processed_keys_lock:
            self._processed_keys.add(request.idempotency_key)
```

---

## 4. Request Lifecycle Details

### 4.1 Submission (Legacy Backend)

```
1. Admin submits POST /ai/control/{action}
2. Legacy Backend validates request
3. Checks idempotency key
4. Creates pending request in _pending_control_requests
5. Returns PENDING status
```

### 4.2 Polling (PipelineEngine)

```
1. PipelineEngine polls GET /ai/control/pending
2. Legacy Backend returns pending requests for worker
3. PipelineEngine processes each command
4. PipelineEngine sends response to POST /ai/control/{action}/response
```

### 4.3 Response Handling (Legacy Backend)

```
1. PipelineEngine POSTs to /ai/control/{action}/response
2. Legacy Backend validates response
5. Updates pending request status
6. Returns acknowledgment
```

---

## 4. Request Expiration

- Default TTL: 5 minutes (`expires_at = created_at + 300`)
- Expired requests automatically removed from pending queue
- PipelineEngine rejects expired requests with `EXPIRED` status
- Legacy Backend cleanup task runs periodically

---

## 5. Failure Handling

### 5.1 Failure Scenarios

| Scenario | Handling |
|---|---|
| PipelineEngine crashes mid-execution | Request stays PENDING, re-executed on restart |
| Network failure during response | Legacy Backend stays in RUNNING, retries polling |
| Legacy Backend crashes | PipelineEngine queues response, retries on recovery |
| Duplicate response delivery | Idempotency key prevents double-execution |

### 5.2 Uncertain State Handling

If PipelineEngine cannot determine whether an operation completed:
- Reports `UNCERTAIN` state (future extension)
- Does NOT falsely report success
- Requires manual intervention

---

## 6. Replay Handling

### 6.1 Worker Restart

- Idempotency keys stored in memory (lost on restart)
- Duplicate requests after restart will be re-executed
- **Mitigation:** Persist idempotency keys to disk (future enhancement)

### 6.2 Backend Restart

- Pending requests in memory (lost on restart)
- **Mitigation:** Persist pending queue to disk (future enhancement)

### 6.3 Network Partition

- PipelineEngine queues responses locally
- Retries delivery on connection restore
- Idempotency keys prevent duplicate execution

---

## 6. Request Expiration Handling

| Scenario | Handling |
|---|---|
| Request expires before polling | Legacy Backend marks EXPIRED, removes from queue |
| Request expires during execution | PipelineEngine completes, Legacy Backend accepts response |
| Response delayed past expiration | Legacy Backend accepts response, marks COMPLETED |

---

## 7. Idempotency Key Management

### 6.1 Key Generation

- Generated by Legacy Backend (UUID v4)
- Included in `ControlRequest.idempotency_key`
- Must be unique per request

### 6.2 Key Storage

| Component | Storage | Persistence |
|---|---|---|
| Legacy Backend | `_processed_idempotency_keys` dict | In-memory (24h TTL) |
| PipelineEngine | `_processed_keys` set | In-memory |

### 6.3 Key Expiration

- TTL: 24 hours
- Cleanup: Periodic task removes expired keys
- Expired keys can be reused

---

## 6. Idempotency Key Collision

- UUID v4 collision probability: ~1 in 2^122
- Negligible for practical purposes
- If collision occurs: treated as duplicate, safe behavior

---

## 7. Gate C/D Verdict

**PARTIAL** — Core lifecycle and idempotency implemented. Remaining:
- Persistent idempotency key storage (disk)
- Request expiration persistence
- Replay handling after restarts

**Status:** PARTIAL — Core logic complete, persistence pending.