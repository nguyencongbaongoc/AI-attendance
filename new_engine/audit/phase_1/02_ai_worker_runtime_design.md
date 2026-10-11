# Gate A — AI Worker Runtime Foundation Design

**Date:** 2026-10-04  
**Phase:** 1  
**Gate:** A  
**Status:** DESIGN PHASE  

---

## 1. Objective

Implement a real, controllable AI Worker runtime that:
- Manages complete lifecycle: STARTING → INITIALIZING → RUNNING → DEGRADED → STOPPING → STOPPED/FAILED
- Integrates with existing PipelineEngine, CameraManager, and models
- Reports health to Legacy Backend via health_client.py
- Accepts control commands from Legacy Backend via control_client.py
- Submits attendance events to Legacy Backend (new event_client.py)
- Does NOT report RUNNING before all required components initialized

---

## 2. Worker Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Worker Process                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐    ┌───────────┐  │
│  │  Health Client   │    │  Control Client  │    │Event Client│  │
│  │ (heartbeat send) │    │ (poll + execute) │    │(submit)   │  │
│  └────────┬─────────┘    └────────┬─────────┘    └─────┬─────┘  │
│           │                       │                      │        │
│           ▼                       ▼                      ▼        │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    Worker Core                               │  │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │  │
│  │  │ State   │ │ Config   │ │ Metrics  │ │ Enrollment    │   │  │
│  │  │ Machine │ │ Manager  │ │ Aggregator│ │ Watcher      │   │  │
│  │  └────┬────┘ └────┬─────┘ └────┬─────┘ └───────┬───────┘   │  │
│  └───────│───────────│───────────│────────────────│───────────┘  │
│          │           │           │                │              │
│          ▼           ▼           ▼                ▼              │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                    PipelineEngine                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │  │
│  │  │ CameraManager│  │  Inference  │  │  Tracking +        │  │  │
│  │  │  (cam1)     │  │  (SCRFD,    │  │  AttendanceEngine  │  │  │
│  │  │  (cam2)     │  │   ArcFace,  │  │  (crossing events) │  │  │
│  │  └─────────────┘  │   YOLO)     │  └─────────────────────┘  │  │
│  │                   └─────────────┘                            │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Worker State Machine

### States
| State | Description | Transitions To |
|-------|-------------|----------------|
| `STARTING` | Process launched, loading config | `INITIALIZING`, `FAILED` |
| `INITIALIZING` | Loading models, connecting cameras, validating | `RUNNING`, `DEGRADED`, `FAILED` |
| `RUNNING` | All cameras healthy, inference operational, event delivery working | `DEGRADED`, `STOPPING` |
| `DEGRADED` | Some cameras unhealthy OR inference degraded OR event delivery issues | `RUNNING`, `STOPPING`, `FAILED` |
| `STOPPING` | Graceful shutdown in progress | `STOPPED` |
| `STOPPED` | Clean shutdown complete | — |
| `FAILED` | Unrecoverable error | `STOPPING` (for cleanup) |

### State Distinctions (Must NOT collapse)
1. **Process alive** — OS process exists
2. **Worker initialized** — Config loaded, components created
3. **Camera connected** — RTSP streams established, readiness passed
4. **Model initialized** — SCRFD, ArcFace, YOLO loaded and warm
5. **Inference operational** — Producing detections/embeddings
6. **Event delivery operational** — Backend reachable, events acknowledged

---

## 4. Component Design

### 4.1 WorkerConfig
```python
@dataclass
class WorkerConfig:
    # Identity
    worker_id: str = "pipeline_engine_1"
    worker_version: str = "1.0.0"
    
    # Backend connection
    backend_base_url: str = "http://localhost:19146"
    ai_worker_api_key: str = ""  # From env
    ai_control_api_key: str = ""  # From env
    
    # PipelineEngine config
    pipeline_config_path: Optional[Path] = None
    
    # Health reporting
    health_report_interval: float = 5.0
    health_timeout: float = 5.0
    health_max_retries: int = 3
    
    # Control polling
    control_poll_interval: float = 2.0
    control_timeout: float = 5.0
    
    # Event delivery
    event_queue_max_size: int = 1000
    event_delivery_interval: float = 1.0
    event_delivery_timeout: float = 10.0
    event_max_retries: int = 3
    
    # Enrollment watching
    enrollment_watch_enabled: bool = True
    enrollment_watch_interval: float = 30.0
    
    # Graceful shutdown
    shutdown_timeout: float = 30.0
```

### 4.2 WorkerCore (Main Class)

```python
class AIWorker:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self._state = WorkerState.STARTING
        self._state_lock = asyncio.Lock()
        self._start_time: Optional[float] = None
        
        # PipelineEngine (existing)
        self.engine: Optional[PipelineEngine] = None
        
        # Integration clients
        self.health_client: Optional[LegacyBackendHealthClient] = None
        self.control_server: Optional[PipelineEngineControlServer] = None
        self.event_client: Optional[EventDeliveryClient] = None
        
        # Enrollment watcher
        self._enrollment_watcher_task: Optional[asyncio.Task] = None
        
        # Metrics
        self._metrics = WorkerMetrics()
        
        # Event queue for delivery
        self._event_queue: asyncio.Queue = asyncio.Queue(maxsize=config.event_queue_max_size)
        self._event_delivery_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self._state_callbacks: List[Callable] = []
        
    async def start(self) -> bool:
        """Start worker - complete initialization sequence."""
        async with self._state_lock:
            if self._state != WorkerState.STARTING:
                return False
            self._set_state(WorkerState.INITIALIZING)
        
        try:
            # 1. Load PipelineEngine config
            self.engine = PipelineEngine(self.config.pipeline_config_path)
            if not self.engine.load_config():
                raise RuntimeError("PipelineEngine config load failed")
            
            # 2. Initialize PipelineEngine (cameras, memory, models)
            if not self.engine.initialize():
                raise RuntimeError("PipelineEngine initialization failed")
            
            # 3. Verify model readiness
            if not await self._verify_model_readiness():
                raise RuntimeError("Model readiness verification failed")
            
            # 4. Start PipelineEngine (cameras + supervisor)
            if not self.engine.start():
                raise RuntimeError("PipelineEngine start failed")
            
            # 5. Verify camera connectivity
            if not await self._verify_camera_connectivity():
                raise RuntimeError("Camera connectivity verification failed")
            
            # 6. Initialize integration clients
            await self._initialize_integration_clients()
            
            # 7. Register event callback with AttendanceEngine
            self._register_event_callback()
            
            # 8. Start event delivery loop
            self._event_delivery_task = asyncio.create_task(self._event_delivery_loop())
            
            # 9. Start enrollment watcher
            if self.config.enrollment_watch_enabled:
                self._enrollment_watcher_task = asyncio.create_task(self._enrollment_watch_loop())
            
            # All components ready
            self._start_time = time.time()
            async with self._state_lock:
                self._set_state(WorkerState.RUNNING)
            
            logger.info(f"AI Worker {self.config.worker_id} started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Worker start failed: {e}")
            async with self._state_lock:
                self._set_state(WorkerState.FAILED)
            await self._cleanup_on_failure()
            return False
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Graceful shutdown."""
        async with self._state_lock:
            if self._state in (WorkerState.STOPPING, WorkerState.STOPPED):
                return
            self._set_state(WorkerState.STOPPING)
        
        # Stop event delivery
        if self._event_delivery_task:
            self._event_delivery_task.cancel()
            try:
                await asyncio.wait_for(self._event_delivery_task, timeout=5.0)
            except asyncio.CancelledError:
                pass
        
        # Stop enrollment watcher
        if self._enrollment_watcher_task:
            self._enrollment_watcher_task.cancel()
            try:
                await asyncio.wait_for(self._enrollment_watcher_task, timeout=5.0)
            except asyncio.CancelledError:
                pass
        
        # Stop integration clients
        if self.health_client:
            await self.health_client.stop()
        if self.control_server:
            await self.control_server.stop()
        if self.event_client:
            await self.event_client.stop()
        
        # Stop PipelineEngine
        if self.engine:
            self.engine.stop(timeout=timeout)
        
        async with self._state_lock:
            self._set_state(WorkerState.STOPPED)
        
        logger.info(f"AI Worker {self.config.worker_id} stopped")
    
    def _set_state(self, state: WorkerState) -> None:
        old_state = self._state
        self._state = state
        if old_state != state:
            logger.info(f"Worker state: {old_state.value} -> {state.value}")
            for cb in self._state_callbacks:
                try:
                    cb(old_state, state)
                except Exception as e:
                    logger.error(f"State callback error: {e}")
```

---

## 5. Integration Client: EventDeliveryClient

### 5.1 Purpose
Submit CrossingEvents to Legacy Backend `/api/v1/attendance/events` with:
- Idempotent delivery (dedup by event_id)
- Bounded retry with exponential backoff
- Observable queue state
- Error classification

### 5.2 Design

```python
@dataclass
class EventDeliveryConfig:
    backend_base_url: str = "http://localhost:19146"
    api_key: str = ""  # AI_WORKER_API_KEY
    queue_max_size: int = 1000
    delivery_interval: float = 1.0
    timeout: float = 10.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 30.0
    retry_backoff: float = 2.0

@dataclass
class QueuedEvent:
    event: CrossingEventRequest
    attempt: int = 0
    first_attempt_time: float = field(default_factory=time.time)
    last_error: Optional[str] = None

class EventDeliveryClient:
    def __init__(self, config: EventDeliveryConfig):
        self.config = config
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=config.queue_max_size)
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._pending_count = 0
        self._delivered_count = 0
        self._failed_count = 0
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.config.backend_base_url,
            timeout=httpx.Timeout(self.config.timeout),
            headers={"X-API-Key": self.config.api_key} if self.config.api_key else {},
        )
        self._stop_event.clear()
        self._task = asyncio.create_task(self._delivery_loop())
    
    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
    
    async def submit_event(self, event: CrossingEventRequest) -> bool:
        """Queue event for delivery. Returns True if queued, False if queue full."""
        try:
            queued = QueuedEvent(event=event)
            self._queue.put_nowait(queued)
            async with self._lock:
                self._pending_count += 1
            return True
        except asyncio.QueueFull:
            logger.warning("Event delivery queue full, dropping event")
            async with self._lock:
                self._failed_count += 1
            return False
    
    async def _delivery_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Process queue
                await self._process_queue()
            except Exception as e:
                logger.error(f"Event delivery loop error: {e}")
            await asyncio.sleep(self.config.delivery_interval)
    
    async def _process_queue(self) -> None:
        """Process all queued events."""
        processed = []
        
        while not self._queue.empty():
            try:
                queued = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            success = await self._deliver_with_retry(queued)
            
            if success:
                processed.append(queued)
                async with self._lock:
                    self._delivered_count += 1
                    self._pending_count -= 1
            else:
                # Re-queue for retry (if not exceeded max retries)
                if queued.attempt < self.config.max_retries:
                    queued.attempt += 1
                    await self._queue.put(queued)
                else:
                    logger.error(f"Event {queued.event.event_id} failed after {queued.attempt} attempts")
                    async with self._lock:
                        self._failed_count += 1
                        self._pending_count -= 1
    
    async def _deliver_with_retry(self, queued: QueuedEvent) -> bool:
        """Deliver single event with retry."""
        for attempt in range(queued.attempt, self.config.max_retries + 1):
            try:
                response = await self._client.post(
                    "/api/v1/attendance/events",
                    json=queued.event.dict()
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        logger.debug(f"Event {queued.event.event_id} delivered successfully")
                        return True
                    else:
                        queued.last_error = data.get("message", "Unknown error")
                elif response.status_code == 401:
                    logger.error("Event delivery: Invalid API key")
                    return False
                else:
                    queued.last_error = f"HTTP {response.status_code}: {response.text}"
                    
            except httpx.TimeoutException:
                queued.last_error = "Timeout"
            except httpx.ConnectError:
                queued.last_error = "Connection failed"
            except Exception as e:
                queued.last_error = str(e)
            
            if attempt < self.config.max_retries:
                delay = min(
                    self.config.base_retry_delay * (self.config.retry_backoff ** attempt),
                    self.config.max_retry_delay
                )
                await asyncio.sleep(delay)
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "pending": self._pending_count,
            "delivered": self._delivered_count,
            "failed": self._failed_count,
            "queue_depth": self._queue.qsize(),
            "queue_max": self.config.queue_max_size,
        }
```

---

## 6. Event Callback Integration

### 6.1 AttendanceEngine Callback

In `pipeline_engine/attendance/attendance_engine.py`, the `AttendanceEngine` already has:
```python
def register_event_callback(self, callback: callable) -> None:
    self._event_callbacks.append(callback)
```

Worker will register:
```python
def _register_event_callback(self) -> None:
    def on_attendance_event(event: CrossingEvent):
        # Convert to CrossingEventRequest
        request = self._convert_to_crossing_event_request(event)
        # Queue for delivery
        asyncio.create_task(self.event_client.submit_event(request))
    
    self.engine._engines[camera_id].register_event_callback(on_attendance_event)
    # Actually need to register for ALL cameras
    for camera_id in self.engine._engines:
        self.engine._engines[camera_id].register_event_callback(on_attendance_event)
```

### 6.2 CrossingEvent → CrossingEventRequest Conversion

Must map all fields from `pipeline_engine.attendance.attendance_engine.CrossingEvent` to `app.api.ai_worker.CrossingEventRequest`:
- event_id, camera_id, track_id, direction, event_type
- crossing_point (x, y)
- timestamp, frame_index
- previous_position, current_position
- person_id, person_name, identity_confidence
- stream_epoch, pts, time_base (from track)
- capture_timestamp, processing_timestamp
- model_version, enrollment_version, provenance, schema_version

---

## 7. Enrollment Watcher

```python
async def _enrollment_watch_loop(self) -> None:
    """Watch for enrollment database changes and reload models."""
    last_mtime = 0
    embeddings_path = Path("data/embeddings.npy")
    metadata_path = Path("data/embeddings.npy.metadata.json")
    
    while not self._stop_event.is_set():
        try:
            if embeddings_path.exists() and metadata_path.exists():
                mtime = max(embeddings_path.stat().st_mtime, metadata_path.stat().st_mtime)
                if mtime > last_mtime:
                    logger.info("Enrollment database changed, reloading...")
                    await self._reload_enrollment()
                    last_mtime = mtime
                    
                    # Notify backend
                    await self._notify_backend_enrollment_reload()
        except Exception as e:
            logger.error(f"Enrollment watch error: {e}")
        
        await asyncio.sleep(self.config.enrollment_watch_interval)

async def _reload_enrollment(self) -> None:
    """Reload enrollment in ArcFace recognizers."""
    for camera_id in self.engine.camera_manager.get_camera_list():
        camera = self.engine.camera_manager._cameras.get(camera_id)
        if camera and camera.get("arcface"):
            camera["arcface"].load_enrollment_database(
                "data/embeddings.npy",
                "data/embeddings.npy.metadata.json"
            )

async def _notify_backend_enrollment_reload(self) -> None:
    """Call backend reload endpoint."""
    if self.event_client and self.event_client._client:
        try:
            await self.event_client._client.post(
                "/api/v1/enrollment/reload",
                json={"trigger": "file_watcher"}
            )
        except Exception as e:
            logger.warning(f"Backend enrollment reload notification failed: {e}")
```

---

## 8. Health Reporting Integration

Worker must update `LegacyBackendHealthClient` with current state:

```python
def _build_health_payload(self) -> Dict[str, Any]:
    """Build health payload from current state."""
    engine_health = self.engine.get_health() if self.engine else {}
    
    # Determine worker state
    worker_state = self._state.value
    if self._state == WorkerState.INITIALIZING:
        worker_state = "initializing"
    elif self._state == WorkerState.RUNNING:
        # Check if any camera degraded
        cameras = engine_health.get("cameras", {})
        if any(c.get("state") == "degraded" for c in cameras.values()):
            worker_state = "degraded"
    
    return {
        "worker_id": self.config.worker_id,
        "worker_version": self.config.worker_version,
        "state": worker_state,
        "timestamp": time.time(),
        "sequence_number": self._health_sequence,  # Managed by health client
        "camera_states": self._build_camera_states(engine_health),
        "model_readiness": self._get_model_readiness(),
        "gpu_provider": "CUDAExecutionProvider",
        "queue_depth": self.event_client._queue.qsize() if self.event_client else 0,
        "processing_latency_ms": self._metrics.avg_latency_ms,
        "dropped_frames": self._metrics.dropped_frames,
        "stream_epochs": self._get_stream_epochs(),
        "errors": self._get_current_errors(),
    }
```

---

## 9. Gate A Tests

| Test | Description | Pass Criteria |
|------|-------------|---------------|
| T1 | Worker starts from STOPPED | State reaches RUNNING, all components initialized |
| T2 | Worker stops cleanly | State reaches STOPPED, all resources released |
| T3 | Duplicate START is safe | Second start returns True, no duplicate resources |
| T4 | STOP during INITIALIZING | Cleanup without deadlock, state STOPPED |
| T5 | Model init failure observable | State FAILED, error logged, health reports failure |
| T6 | Camera init failure observable | State DEGRADED or FAILED, health reflects camera state |
| T7 | Worker restart | Stop → Start works, no resource leaks |
| T8 | Health reports actual state | Health state matches actual component states |
| T9 | Shutdown releases resources | GPU memory, threads, connections cleaned up |

---

## 10. Implementation Files

| File | Status | Description |
|------|--------|-------------|
| `pipeline_engine/integration/event_client.py` | NEW | Event delivery to Legacy Backend |
| `pipeline_engine/core/worker.py` | NEW | AIWorker main class |
| `scripts/run_worker.py` | NEW | Worker entry point script |
| `pipeline_engine/attendance/attendance_engine.py` | PATCH | Ensure event callback registration |
| `pipeline_engine/integration/__init__.py` | PATCH | Export new clients |

---

## 11. Dependencies

- Existing: `pipeline_engine.core.engine.PipelineEngine`
- Existing: `pipeline_engine.integration.health_client.LegacyBackendHealthClient`
- Existing: `pipeline_engine.integration.control_client.PipelineEngineControlServer`
- New: `pipeline_engine.integration.event_client.EventDeliveryClient`
- Config: `pipeline_engine.config.PipelineConfig` (from pipeline.yaml)

---

## 12. Sequence Diagram: Worker Startup

```
Worker.start()
    │
    ├─► PipelineEngine.load_config()
    │       └─► Read pipeline.yaml
    │
    ├─► PipelineEngine.initialize()
    │       ├─► MemoryMonitor.start()
    │       ├─► CameraManager.initialize()
    │       │       └─► Create RTSPSource, models, trackers per camera
    │       └─► Validate cameras (connectivity test)
    │
    ├─► _verify_model_readiness()
    │       └─► Check SCRFD, ArcFace, YOLO initialized
    │
    ├─► PipelineEngine.start()
    │       ├─► CameraManager.start_all()
    │       │       └─► Per camera: RTSPSource → Decoder → Encoder → Publisher → PipelineThread
    │       └─► SupervisorThread.start()
    │
    ├─► _verify_camera_connectivity()
    │       └─► Check RTSPState == READY for all cameras
    │
    ├─► _initialize_integration_clients()
    │       ├─► HealthClient.start()  ──► Heartbeat loop
    │       ├─► ControlServer.start() ──► Poll loop
    │       └─► EventClient.start()   ──► Delivery loop
    │
    ├─► _register_event_callback()
    │       └─► AttendanceEngine.register_event_callback() per camera
    │
    ├─► _event_delivery_task.start()
    │
    └─► State = RUNNING
```

---

*Design complete. Ready for implementation.*