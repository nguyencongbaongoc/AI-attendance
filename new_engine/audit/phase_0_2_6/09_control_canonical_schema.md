# Phase 0.2.6 Control Canonical Schema

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Canonical Action Vocabulary

```python
class Action(str):
    START_WORKER = "START_WORKER"
    STOP_WORKER = "STOP_WORKER"
    RESTART_WORKER = "RESTART_WORKER"
    ENABLE_CAMERA = "ENABLE_CAMERA"
    DISABLE_CAMERA = "DISABLE_CAMERA"
    GET_STATUS = "GET_STATUS"
```

---

## 2. Request Schema

### 2.1 ControlRequest (Backend → Client)

```json
{
  "request_id": "uuid",
  "action": "START_WORKER|STOP_WORKER|RESTART_WORKER|ENABLE_CAMERA|DISABLE_CAMERA|GET_STATUS",
  "target": "worker|camera",
  "target_id": "worker_id or camera_id",
  "parameters": {},
  "idempotency_key": "uuid",
  "created_at": 1791086968.123,
  "expires_at": 1791087268.123
}
```

### 2.2 ControlResponse (Client → Backend)

```json
{
  "success": true,
  "action": "START_WORKER",
  "worker_id": "pipeline_engine_1",
  "status": "COMPLETED",
  "request_id": "uuid",
  "timestamp": 1791086968.123,
  "details": {},
  "error": null
}
```

---

## 3. Status Enum

```python
class ControlRequestStatus(str):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
```

---

## 4. API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/ai/control/{action}` | ADMIN | Submit control request |
| GET | `/api/v1/ai/control/pending` | CONTROL | Poll pending requests |
| POST | `/api/v1/ai/control/{action}/response` | CONTROL | Submit response |
| GET | `/api/v1/ai/control/status` | CONTROL | System status |
| GET | `/api/v1/ai/control/history` | ADMIN | Command history |

---

## 5. Lifecycle States

```
PENDING → ACCEPTED → RUNNING → COMPLETED/FAILED/REJECTED
                ↓
            EXPIRED (if TTL exceeded)
```

---

## 6. Idempotency

- **Request submission:** Checked via `idempotency_key` in `_processed_idempotency_keys`
- **Response submission:** Not deduplicated (backend overwrites)
- **Client execution:** Tracked in `_processed_keys` set