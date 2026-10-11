# Health Source and Contract Audit

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate A  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Health Endpoint Source Audit

### 1.1 Backend Implementation: `app/api/ai_worker.py`

**Endpoint:** `POST /api/v1/health/ai-worker`

**Authentication:** `verify_ai_worker_key` (checks `AI_WORKER_API_KEY` environment variable)

**Request Model:** `AIWorkerHealthRequest`
```python
class AIWorkerHealthRequest(BaseModel):
    worker_id: str
    worker_version: str
    state: str  # "starting", "initializing", "ready", "degraded", "failed", "stopping", "stopped"
    timestamp: float
    sequence_number: int
    camera_states: Dict[str, CameraState] = {}
    model_readiness: ModelReadiness = ModelReadiness(scrfd=False, arcface=False, yolo=False)
    gpu_provider: str = "CUDAExecutionProvider"
    queue_depth: int = 0
    processing_latency_ms: float = 0.0
    dropped_frames: int = 0
    stream_epochs: Dict[str, int] = {}
    errors: List[str] = []
```

**Response Model:** `AIWorkerHealthResponse`
```python
class AIWorkerHealthResponse(BaseModel):
    success: bool
    worker_id: str
    acknowledged: bool
    server_timestamp: float
    sequence_number: int
    commands: List[str] = []
    stale_threshold_seconds: float = 30.0
```

**Handler Implementation (lines 1352–1375):**
```python
@router.post("/health/ai-worker", response_model=AIWorkerHealthResponse, dependencies=[Depends(verify_ai_worker_key)])
async def ai_worker_health(health: AIWorkerHealthRequest) -> AIWorkerHealthResponse:
    logger.debug(f"Health from {health.worker_id}: {health.state}")
    commands = []
    return AIWorkerHealthResponse(
        success=True,
        worker_id=health.worker_id,
        acknowledged=True,
        server_timestamp=time.time(),
        sequence_number=health.sequence_number,
        commands=commands,
        stale_threshold_seconds=30.0
    )
```

**Status:** **SCAFFOLDED** — No state persistence, no validation, no command generation. Merely echoes back acknowledgment.

---

### 1.2 Client Implementation: `pipeline_engine/integration/health_client.py`

**Class:** `LegacyBackendHealthClient`

**Configuration:** `HealthClientConfig`
```python
@dataclass
class HealthClientConfig:
    backend_base_url: str = "http://localhost:19146"
    worker_id: str = "pipeline_engine_1"
    worker_version: str = "1.0.0"
    api_key: Optional[str] = None
    report_interval: float = 5.0
    timeout: float = 5.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 30.0
    retry_backoff: float = 2.0
    queue_max_size: int = 100
```

**Heartbeat Payload (lines 128–143):**
```python
payload = {
    "worker_id": self.config.worker_id,
    "worker_version": self.config.worker_version,
    "state": self._get_worker_state(),
    "timestamp": time.time(),
    "sequence_number": self._sequence_number,
    "camera_states": self._build_camera_states(),
    "model_readiness": self._get_model_readiness(),
    "inference_provider": "CUDAExecutionProvider",  # MISMATCH: backend expects gpu_provider
    "queue_depth": self._get_queue_depth(),
    "processing_latency_ms": self._get_latency_ms(),
    "dropped_frame_count": self._get_dropped_frames(),
    "event_delivery_state": "operational",
    "stream_epochs": self._get_stream_epochs(),
    "errors": self._get_errors(),
}
```

**Key Mismatches:**

| Client Field | Backend Expected | Match |
|---|---|---|
| `inference_provider` | `gpu_provider` | ❌ |
| `event_delivery_state` | (not in backend model) | ❌ Extra field |

**State Mapping (lines 213–233):**
```python
def _get_worker_state(self) -> str:
    if not self.engine: return "starting"
    state = self.engine.state
    if state == EngineState.STOPPED: return "stopped"
    elif state == EngineState.STOPPING: return "stopping"
    elif state == EngineState.ERROR: return "failed"
    elif state == EngineState.DEGRADED: return "degraded"
    elif state == EngineState.RUNNING: return "ready"
    elif state == EngineState.STARTING: return "starting"
    elif state == EngineState.INITIALIZING: return "initializing"
    return "starting"
```

**Valid States per Backend:** `starting`, `initializing`, `ready`, `degraded`, `failed`, `stopping`, `stopped` ✅

**Retry Logic (lines 175–211):** Exponential backoff with max 3 retries, max 30s delay. On 401 returns False immediately.

**Queue:** Bounded asyncio.Queue (max 100) for offline buffering.

**Control Polling (lines 147–173):** Polls `/api/v1/ai/control/pending` with worker_id param. Stores commands locally.

---

### 1.3 Integration Setup: `setup_health_reporting()`

```python
async def setup_health_reporting(engine: "PipelineEngine", config: Optional[HealthClientConfig] = None) -> LegacyBackendHealthClient:
    client = create_health_client(config, engine)
    await client.start()
    
    def health_callback(health: Dict[str, Any]):
        client.update_health({
            "state": health["engine"]["state"],
            "cameras": health["cameras"],
            "memory": health.get("memory", {}),
            "uptime": health["engine"]["uptime_seconds"],
        })
    
    engine.register_health_callback(health_callback)
    return client
```

**Dependencies:** Requires `PipelineEngine` with `register_health_callback` method and specific health dict structure.

---

## 2. Contract Completeness Analysis

### 2.1 Missing Backend Features

| Feature | Status | Required For |
|---|---|---|
| Health state persistence | ❌ MISSING | Status retrieval |
| Sequence validation (stale/duplicate/out-of-order) | ❌ MISSING | Reliability |
| Model readiness tracking | ❌ MISSING | Operational visibility |
| Camera state tracking | ❌ MISSING | Operational visibility |
| Stream epoch tracking | ❌ MISSING | Timestamp sync |
| Error tracking | ❌ MISSING | Observability |
| Stale worker detection | ❌ MISSING | Health monitoring |
| Command queue for worker | ⚠️ PARTIAL | Control flow (returns empty) |

### 2.2 Missing Client Features

| Feature | Status |
|---|---|
| Health state cache for status API | ❌ MISSING |
| Backend health query endpoint | ❌ MISSING |
| Metrics export | ❌ MISSING |

---

## 3. Authentication Audit

**Backend:** `verify_ai_worker_key` (line 35–41)
```python
async def verify_ai_worker_key(x_api_key: str = Header(..., alias="X-API-Key")):
    expected = os.environ.get("AI_WORKER_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid AI Worker API key")
    return True
```

**Client:** Sets header `X-API-Key` from `AI_WORKER_API_KEY` env var (line 74, 79)

**Issues:**
1. If `AI_WORKER_API_KEY` not set in env, backend allows any key (empty string check passes)
2. No constant-time comparison (uses `!=` instead of `secrets.compare_digest`)
3. Same dependency defined 3 times in file (duplication)

---

## 4. Router Registration

**File:** `app/main.py` lines 78–80
```python
for router in [health_router, websocket_router, attendance_router, persons_router, timetable_router, excel_router, parent_telegram_router, geometry_router, enrollment_router, ai_worker_router, replay_router, provenance_router]:
    for route in router.routes:
        app.router.routes.append(route)
```

**Endpoint Registered:** `POST /api/v1/health/ai-worker` via `ai_worker_router`

**Note:** Manual route registration due to "FastAPI version issue" — non-standard but functional.

---

## 5. Evidence Classification

| Component | Evidence Level | Notes |
|---|---|---|
| Backend endpoint exists | SOURCE-VERIFIED | Code present |
| Backend validates schema | SOURCE-VERIFIED | Pydantic model |
| Backend persists state | NOT-VERIFIED | No persistence code |
| Backend validates sequence | NOT-VERIFIED | No sequence logic |
| Client constructs valid payload | SOURCE-VERIFIED | Code present |
| Client authenticates | SOURCE-VERIFIED | Header set |
| Client retries on failure | SOURCE-VERIFIED | Retry logic present |
| Client polls commands | SOURCE-VERIFIED | Polling loop present |
| End-to-end integration | NOT-VERIFIED | No runtime test |

---

## 6. Gate A Readiness Assessment

**Current State:** Backend endpoint is a **scaffold** — accepts requests but does not persist state, validate sequences, or provide status retrieval.

**Required for PASS:**
1. Backend persists health state per worker
2. Backend validates sequence_number (monotonic, no gaps > threshold)
3. Backend tracks camera states, model readiness, stream epochs
4. Backend provides status retrieval endpoint (not implemented)
5. Client successfully sends heartbeat to real backend
6. Backend returns acknowledgment with commands
7. Stale/out-of-order reports rejected
8. Backend failure doesn't block camera processing

**Verdict:** **NOT READY** — Backend health endpoint is non-functional scaffold. Integration test will fail at step 5 (state persistence) and step 6 (status retrieval).

---

## 7. Required Remediation for Gate A

### 7.1 Backend Changes Needed

1. **Add in-memory health state storage** (per worker_id)
2. **Implement sequence validation** — reject stale/duplicate/out-of-order
3. **Add GET /api/v1/health/ai-worker/{worker_id}** for status retrieval
4. **Track camera states, model readiness, stream epochs, errors**
5. **Implement stale worker detection** (threshold from response)
6. **Return pending commands from control queue** (integration with control endpoints)

### 7.2 Client Changes Needed

1. **Fix field name:** `inference_provider` → `gpu_provider`
2. **Remove extra field:** `event_delivery_state`
3. **Handle backend validation errors** (400 responses)

---

**Classification:** SOURCE-VERIFIED (code audit), NOT-VERIFIED (runtime behavior)