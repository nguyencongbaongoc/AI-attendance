# Gate A — Health Backend State Management

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Gate A  
**Classification:** SOURCE-VERIFIED / IMPLEMENTATION DESIGN

---

## 1. Executive Summary

This document defines the Legacy Backend health state management system. It specifies how the backend receives, validates, stores, and serves health state from PipelineEngine workers. The backend is the authoritative source of worker health truth.

---

## 2. Backend Health State Model

### 2.1 Stored State per Worker

```python
@dataclass
class WorkerHealthState:
    worker_id: str
    worker_version: str
    state: WorkerState  # Enum: STARTING, INITIALIZING, READY, DEGRADED, FAILED, STOPPING, STOPPED
    last_report_timestamp: float
    last_report_sequence: int
    camera_states: Dict[str, CameraHealthState]
    model_readiness: Dict[str, bool]
    inference_provider: str
    queue_depth: int
    processing_latency_ms: float
    dropped_frame_count: int
    event_delivery_state: str
    error_code: Optional[str]
    error_message: Optional[str]
    stream_epochs: Dict[str, int]
    last_report_received: float  # When backend received the report
    report_count: int
    first_report_received: float
    state_changed_at: float
```

### 2.2 Camera Health State

```python
@dataclass
class CameraHealthState:
    state: CameraState  # live, connecting, disconnected, error
    stream_epoch: int
    stream_connected: bool
    last_frame_timestamp: float
    last_inference_timestamp: float
    decode_fps: float
    inference_fps: float
    track_count: int
    last_updated: float
```

---

## 2.3 State Storage

**Storage Mechanism:** In-memory dictionary with optional persistence hook.

```python
# In app/api/ai_worker.py or new health module
_worker_health_states: Dict[str, WorkerHealthState] = {}
```

**Persistence:** Optional JSON file dump for debugging/restart recovery. Not required for Phase 0.2.4.

---

## 2. State Transitions

### 2.1 Valid State Transitions

| From \ To | STARTING | INITIALIZING | READY | DEGRADED | FAILED | STOPPING | STOPPED |
|---|---|---|---|---|---|---|---|
| STARTING | - | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| INITIALIZING | ❌ | - | ✅ | ❌ | ✅ | ❌ | ❌ |
| READY | ❌ | ❌ | - | ✅ | ✅ | ✅ | ❌ |
| DEGRADED | ❌ | ✅ | ✅ | - | ✅ | ✅ | ❌ |
| FAILED | ❌ | ✅ | ❌ | ❌ | - | ❌ | ✅ |
| STOPPING | ❌ | ❌ | ❌ | ❌ | ❌ | - | ✅ |
| STOPPED | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | - |

### 2.2 Transition Triggers

| Transition | Trigger |
|---|---|
| STARTING → INITIALIZING | Worker reports INITIALIZING |
| INITIALIZING → READY | All cameras live, models ready, inference active |
| READY → DEGRADED | Any camera disconnected, high latency, dropped frames |
| DEGRADED → READY | All cameras live, latency normal, no dropped frames |
| * → FAILED | Critical error, no cameras, GPU failure |
| * → STOPPING | Worker reports STOPPING |
| STOPPING → STOPPED | Worker stops reporting |

---

## 3. Stale Heartbeat Detection

### 3.1 Staleness Criteria

A worker report is **stale** if:
- No report received within `stale_threshold_seconds` (default 30s)
- Sequence number has gaps > 1
- Timestamp regression detected

### 3.2 Stale Handling

| Condition | Action |
|---|---|
| Single missed heartbeat | Mark DEGRADED, continue monitoring |
| 2+ missed heartbeats | Mark FAILED, alert |
| Worker restart detected (stream_epoch change) | Reset state to STARTING |
| Sequence gap > 1 | Log warning, request retransmission (future) |

### 3.3 Stale Threshold Configuration

```python
STALE_THRESHOLD_SECONDS = 30.0  # Configurable
DEGRADED_THRESHOLD_SECONDS = 10.0  # Earlier warning
```

---

## 4. Sequence Number Handling

### 4.1 Sequence Number Rules

- Monotonically increasing per worker
- First report: sequence_number = 1
- Increment by 1 per heartbeat
- Gaps > 1 trigger warning
- Reset on worker restart (stream_epoch change)

### 4.2 Duplicate/Out-of-Order Handling

| Scenario | Handling |
|---|---|
| Duplicate sequence | Acknowledge, ignore duplicate |
| Out-of-order (late) | Accept if within window, log warning |
| Gap > 1 | Log warning, request gap fill (future) |
| Reset to 1 | Treat as worker restart |

---

## 3. Worker Restart Detection

### 3.1 Detection Signals

| Signal | Indicates |
|---|---|
| `stream_epoch` increase | Stream restarted |
| `worker_version` change | Worker software updated |
| Sequence reset to 1 | Worker process restarted |
| `worker_id` change | New worker instance |

### 3.2 Restart Handling

| Event | Action |
|---|---|
| Stream epoch change | Reset camera states for that camera, increment epoch |
| Worker restart | Reset worker state to STARTING, clear camera states |
| Version change | Reset model_readiness to false |

---

## 4. Data Structures

### 4.1 In-Memory Store

```python
# In app/api/ai_worker.py or new health module
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime
import time

@dataclass
class CameraHealthState:
    state: str = "disconnected"
    stream_epoch: int = 0
    stream_connected: bool = False
    last_frame_timestamp: float = 0.0
    last_inference_timestamp: float = 0.0
    decode_fps: float = 0.0
    inference_fps: float = 0.0
    track_count: int = 0
    last_updated: float = field(default_factory=time.time)

@dataclass
class WorkerHealthState:
    worker_id: str
    worker_version: str = ""
    state: str = "STARTING"
    last_report_timestamp: float = 0.0
    last_report_sequence: int = 0
    camera_states: Dict[str, CameraHealthState] = field(default_factory=dict)
    model_readiness: Dict[str, bool] = field(default_factory=lambda: {"scrfd": False, "arcface": False, "yolo": False})
    inference_provider: str = "CUDAExecutionProvider"
    queue_depth: int = 0
    processing_latency_ms: float = 0.0
    dropped_frame_count: int = 0
    event_delivery_state: str = "unknown"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    stream_epochs: Dict[str, int] = field(default_factory=dict)
    last_report_received: float = field(default_factory=time.time)
    report_count: int = 0
    first_report_received: float = field(default_factory=time.time)
    state_changed_at: float = field(default_factory=time.time)

# Global state
_worker_health_states: Dict[str, WorkerHealthState] = {}
```

---

## 5. API Implementation

### 5.1 Receive Health Report

**Endpoint:** `POST /api/v1/health/ai-worker` (existing)

```python
@router.post("/health/ai-worker", response_model=AIWorkerHealthResponse)
async def ai_worker_health(
    health: AIWorkerHealthRequest,
    _: bool = Depends(verify_ai_worker_key),
) -> AIWorkerHealthResponse:
    # 1. Validate payload
    # 2. Update worker state
    # 3. Detect state transitions
    # 4. Check for stale workers
    # 4. Return acknowledgment with commands
```

### 4.2 State Update Logic

```python
def update_worker_health(health: AIWorkerHealthRequest) -> AIWorkerHealthResponse:
    worker_state = _worker_health_states.get(health.worker_id)
    
    if not worker_state:
        worker_state = WorkerHealthState(worker_id=health.worker_id)
        _worker_health_states[health.worker_id] = worker_state
    
    # Detect restart
    if health.stream_epochs:
        for cam_id, epoch in health.stream_epochs.items():
            if cam_id in worker_state.camera_states:
                if epoch != worker_state.camera_states[cam_id].stream_epoch:
                    # Stream restart detected
                    worker_state.camera_states[cam_id].stream_epoch = epoch
                    worker_state.camera_states[cam_id].stream_connected = False
    
    # Update state
    old_state = worker_state.state
    new_state = _determine_state(health, worker_state)
    
    if old_state != new_state:
        worker_state.state = new_state
        worker_state.state_changed_at = time.time()
    
    # Update all fields
    worker_state.worker_version = health.worker_version
    worker_state.last_report_timestamp = health.timestamp
    worker_state.last_report_sequence = health.sequence_number
    worker_state.camera_states = _build_camera_states(health)
    worker_state.model_readiness = health.model_readiness
    worker_state.inference_provider = health.inference_provider
    worker_state.queue_depth = health.queue_depth
    worker_state.processing_latency_ms = health.processing_latency_ms
    worker_state.dropped_frame_count = health.dropped_frame_count
    worker_state.event_delivery_state = health.event_delivery_state
    worker_state.error_code = health.error_code
    worker_state.error_message = health.error_message
    worker_state.stream_epochs = health.stream_epochs
    worker_state.last_report_received = time.time()
    worker_state.report_count += 1
    
    # Determine commands to send back
    commands = _determine_commands(worker_state)
    
    return AIWorkerHealthResponse(
        success=True,
        worker_id=health.worker_id,
        acknowledged=True,
        server_timestamp=time.time(),
        sequence_number=health.sequence_number,
        commands=commands,
        stale_threshold_seconds=STALE_THRESHOLD_SECONDS,
    )
```

---

## 5. Stale Detection Background Task

```python
async def stale_detection_loop():
    while True:
        await asyncio.sleep(10.0)  # Check every 10 seconds
        
        now = time.time()
        stale_threshold = STALE_THRESHOLD_SECONDS
        degraded_threshold = DEGRADED_THRESHOLD_SECONDS
        
        for worker_id, state in _worker_health_states.items():
            time_since_report = now - state.last_report_received
            
            if time_since_report > stale_threshold:
                if state.state != "FAILED":
                    state.state = "FAILED"
                    state.state_changed_at = time.time()
                    logger.warning(f"Worker {worker_id} marked FAILED: no heartbeat for {time_since_report:.1f}s")
            elif time_since_report > degraded_threshold:
                if state.state == "READY":
                    state.state = "DEGRADED"
                    state.state_changed_at = time.time()
                    logger.warning(f"Worker {worker_id} marked DEGRADED: no heartbeat for {time_since_report:.1f}s")

# Start at application startup
asyncio.create_task(stale_detection_loop())
```

---

## 5. Health Query Endpoints

### 5.1 Get Worker Health

```python
@router.get("/health/ai-worker/{worker_id}")
async def get_worker_health(worker_id: str) -> WorkerHealthState:
    state = _worker_health_states.get(worker_id)
    if not state:
        raise HTTPException(404, f"Worker {worker_id} not found")
    return state
```

### 5.2 Get All Workers Health

```python
@router.get("/health/ai-workers")
async def get_all_workers_health() -> Dict[str, WorkerHealthState]:
    return _worker_health_states
```

### 5.3 Health Status Endpoint (existing)

```python
@router.get("/health/system")
async def system_health():
    # Extended to include AI worker status
    workers = []
    for wid, state in _worker_health_states.items():
        workers.append({
            "worker_id": wid,
            "state": state.state,
            "last_report": state.last_report_received,
            "cameras": {cid: cs.state for cid, cs in state.camera_states.items()},
        })
    
    return {
        "status": "healthy" if all(w.state == "READY" for w in _worker_health_states.values()) else "degraded",
        "workers": workers,
    }
```

---

## 6. Configuration

```python
# In app/config/settings.py
class HealthConfig(BaseModel):
    stale_threshold_seconds: float = Field(default=30.0, description="Seconds before worker marked stale")
    degraded_threshold_seconds: float = Field(default=10.0, description="Seconds before worker marked degraded")
    max_sequence_gap: int = Field(default=5, description="Max allowed sequence gap")
    state_persistence_enabled: bool = Field(default=False, description="Persist state to disk")
    state_persistence_path: str = Field(default="data/health_state.json", description="Persistence file path")
```

---

## 7. Integration with Health Contract

This backend state management implements the contract defined in `02_health_contract_final.md`:

| Contract Requirement | Backend Implementation |
|---|---|
| Receive health reports | `POST /api/v1/health/ai-worker` |
| Validate payload | `AIWorkerHealthRequest` validation |
| Track worker state | `WorkerHealthState` per worker |
| Detect stale workers | Background stale detection loop |
| Detect worker restarts | `stream_epoch` / sequence tracking |
| Track state transitions | State machine with valid transitions |
| Return commands | `AIWorkerHealthResponse.commands` |
| Stale threshold config | Configurable via settings |

---

## 8. Gate A Backend State Management: COMPLETE

This document specifies the complete backend health state management. Implementation requires:

1. **Add health state models** to `app/api/ai_worker.py` or new module
2. **Update `POST /api/v1/health/ai-worker`** with state update logic
3. **Add stale detection background task** at startup
4. **Add health query endpoints** for monitoring
5. **Add configuration** to settings

**Gate A Backend State Management: DESIGN COMPLETE** — Ready for implementation.