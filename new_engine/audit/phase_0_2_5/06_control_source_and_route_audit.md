# Control Source and Route Audit

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Backend Control Endpoints: `app/api/ai_worker.py`

### 1.1 Endpoint Registry

| # | Method | Path | Auth | Handler | Status |
|---|---|---|---|---|---|
| 1 | POST | `/api/v1/ai/control/{action}` | ADMIN_KEY | `submit_control_request` | IMPLEMENTED |
| 2 | GET | `/api/v1/ai/control/pending` | AI_CONTROL_KEY | `get_pending_control_requests` | IMPLEMENTED |
| 3 | POST | `/api/v1/ai/control/{action}/response` | AI_CONTROL_KEY | `submit_control_response` | IMPLEMENTED |
| 4 | GET | `/api/v1/ai/control/status` | AI_CONTROL_KEY | `get_control_status` | IMPLEMENTED |

---

### 1.2 Endpoint 1: Submit Control Request

**Path:** `POST /api/v1/ai/control/{action}`

**Valid Actions:** `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS`

**Request Model:** `ControlRequest`
```python
class ControlRequest(BaseModel):
    request_id: str
    action: str
    target: str  # "worker" or "camera"
    target_id: str
    parameters: Dict[str, Any] = {}
    idempotency_key: str
    created_at: float = time.time()
    expires_at: float  # Required
```

**Validation:**
- Action must be in valid_actions set
- Target must be "worker" or "camera"
- Camera actions require target_id (camera_id)
- Idempotency key checked against `_processed_idempotency_keys`

**Response:**
```python
{
    "success": True,
    "request_id": "...",
    "status": "PENDING",
    "message": "Control request queued for PipelineEngine"
}
```

**Duplicate Handling:** Returns stored response with `"status": "DUPLICATE"`

---

### 1.3 Endpoint 2: Get Pending Requests

**Path:** `GET /api/v1/ai/control/pending`

**Query Params:**
- `worker_id` (required)
- `limit` (default 50, max 100)
- `since` (optional timestamp filter)

**Filters Applied:**
- `pending.request.target_id == worker_id`
- `pending.status != EXPIRED`
- `pending.request.created_at > now - 300` (5 min TTL)

**Response:** `PendingControlRequests`
```python
class PendingControlRequests(BaseModel):
    worker_id: str
    requests: List[ControlRequest]
```

---

### 1.4 Endpoint 3: Submit Control Response

**Path:** `POST /api/v1/ai/control/{action}/response`

**Valid Actions:** Same as submit

**Request Model:** `ControlResponse`
```python
class ControlResponse(BaseModel):
    success: bool
    action: str
    worker_id: str
    status: str  # ACCEPTED, RUNNING, COMPLETED, FAILED, REJECTED, EXPIRED
    request_id: str
    timestamp: float
    details: Dict[str, Any] = {}
    error: Optional[str] = None
```

**Validation:**
- Action in valid set
- request_id required
- Pending request must exist in `_pending_control_requests`

**Updates Pending:**
- `pending.status = response.status`
- `pending.completed_at = time.time()` (for terminal statuses)
- `pending.response = response`

---

### 1.5 Endpoint 4: Control Status

**Path:** `GET /api/v1/ai/control/status`

**Response:**
```python
{
    "pending_requests": count,
    "processed_requests": count,
    "idempotency_keys": count
}
```

---

## 2. Control State Management (In-Memory)

### 2.1 Storage

```python
_pending_control_requests: Dict[str, PendingControlRequest] = {}
_processed_idempotency_keys: Dict[str, ControlResponse] = {}
```

### 2.2 PendingControlRequest Dataclass

```python
@dataclass
class PendingControlRequest:
    request: ControlRequest
    status: str = ControlRequestStatus.PENDING
    created_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    completed_at: Optional[float] = None
    response: Optional[ControlResponse] = None
```

### 2.3 ControlRequestStatus Enum

| Status | Meaning |
|---|---|
| PENDING | Queued, not yet polled |
| ACCEPTED | Worker acknowledged |
| RUNNING | Worker executing |
| COMPLETED | Success |
| FAILED | Execution failed |
| REJECTED | Worker rejected |
| EXPIRED | TTL expired |

---

## 3. Client Implementation: `pipeline_engine/integration/control_client.py`

### 3.1 Action Enum Mismatch

**Backend Actions:** `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS`

**Client Actions:** `START`="start", `STOP`="stop", `RESTART`="restart", `RECONFIG`="reconfig", `PAUSE_CAMERA`="pause_camera", `RESUME_CAMERA`="resume_camera"

**MISMATCH: No overlap in action names.**

---

### 3.2 Client Request/Response Models

```python
@dataclass
class ControlRequest:
    request_id: str
    action: str
    target: str  # "worker" or "camera"
    target_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class ControlResponse:
    success: bool
    action: str
    worker_id: str
    status: str  # ACCEPTED, COMPLETED, FAILED
    request_id: str
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
```

**Matches backend schemas** (field names align).

---

### 3.3 Client Polling Logic

```python
async def _poll_commands(self):
    response = await self._client.get(
        "/api/v1/ai/control/pending",
        params={"worker_id": self.config.worker_id}
    )
    if response.status_code == 200:
        commands = response.json().get("commands", [])
        # Note: backend returns "requests" not "commands"
```

**BUG:** Backend returns `{"worker_id": "...", "requests": [...]}` but client expects `{"commands": [...]}`.

---

### 3.4 Client Action Handlers

| Client Action | Handler | Backend Equivalent |
|---|---|---|
| START | `_handle_start` | START_WORKER |
| STOP | `_handle_stop` | STOP_WORKER |
| RESTART | `_handle_restart` | RESTART_WORKER |
| RECONFIG | `_handle_reconfig` | (none) |
| PAUSE_CAMERA | `_handle_pause_camera` | DISABLE_CAMERA |
| RESUME_CAMERA | `_handle_resume_camera` | ENABLE_CAMERA |
| (none) | (none) | GET_STATUS |

---

### 3.5 Client Response Submission

```python
await self._client.post(
    f"/api/v1/ai/control/{response.action}/response",
    json={...}
)
```

**BUG:** Uses client action name (`start`, `stop`) not backend action name (`START_WORKER`, `STOP_WORKER`). Backend will reject with 400.

---

## 4. Authentication

### 4.1 Admin Key (Submit Request)
```python
async def verify_admin_key(x_api_key: str = Header(..., alias="X-API-Key")):
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(503, "Admin API key not configured")
    if not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid Admin API key")
    return True
```
- Uses `secrets.compare_digest` ✅
- Returns 503 if not configured ✅

### 4.2 AI Worker Key (Health)
```python
async def verify_ai_worker_key(...):
    expected = os.environ.get("AI_WORKER_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid AI Worker API key")
```
- Uses `!=` not constant-time ❌
- Allows any key if env not set ❌

### 4.3 AI Control Key (Pending/Response)
```python
async def verify_ai_control_key(...):
    expected = os.environ.get("AI_CONTROL_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid AI Control API key")
```
- Same issues as worker key ❌

---

## 5. Route Registration

**File:** `app/main.py` line 82
```python
for router in [..., enrollment_router, ai_worker_router, ...]:
    for route in router.routes:
        app.router.routes.append(route)
```

**Base Prefix:** `ai_worker_router` has `prefix="/api/v1"` (line 28 of ai_worker.py)

**Full Paths:**
- `POST /api/v1/ai/control/{action}`
- `GET /api/v1/ai/control/pending`
- `POST /api/v1/ai/control/{action}/response`
- `GET /api/v1/ai/control/status`

---

## 6. OpenAPI Verification

**Test:** Run backend and check `/openapi.json`

```bash
python -c "from app.main import create_app; import json; app=create_app(); print(json.dumps(app.openapi()['paths'].keys(), indent=2))"
```

---

## 7. Critical Defects Summary

| # | Defect | Impact |
|---|---|---|
| 1 | Action name mismatch (backend vs client) | Control flow completely broken |
| 2 | Client expects `commands` key, backend returns `requests` | Polling returns empty |
| 3 | Client submits response with wrong action name | Response rejected 400 |
| 4 | `GET_STATUS` not implemented in client | Status queries impossible |
| 5 | `RECONFIG` not in backend | Client action unsupported |
| 6 | `ENABLE_CAMERA`/`DISABLE_CAMERA` map to `PAUSE_CAMERA`/`RESUME_CAMERA` | Semantic mismatch |
| 7 | Non-constant-time auth comparison | Timing attack vector |
| 8 | Auth allows any key if env not set | Security bypass |

---

## 8. Gate B Readiness

**Status: BLOCKED**

Multiple contract mismatches prevent end-to-end control flow. Both backend and client need alignment.

---

**Classification:** SOURCE-VERIFIED