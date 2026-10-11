# Existing Backend Integration Audit

## PipelineEngine Backend (New) - `pipeline_engine/backend/app.py`

**Status: IMPLEMENTED, PARTIAL**

### Overview
FastAPI application providing REST + WebSocket API for pipeline control and monitoring.

### Endpoints

#### Health
| Endpoint | Method | Response | Status |
|----------|--------|----------|--------|
| `/api/v1/health/live` | GET | `{"status": "alive"}` | ✅ Working |
| `/api/v1/health/ready` | GET | `HealthResponse{status, checks}` | ✅ Checks CUDA, engine |
| `/api/v1/health/system` | GET | `PipelineStatusResponse` | ✅ Engine metrics |

#### Pipeline Control
| Endpoint | Method | Action | Status |
|----------|--------|--------|--------|
| `/api/v1/pipeline/control` | POST | start/stop/restart (global or per-camera) | ✅ Implemented |
| `/api/v1/pipeline/status` | GET | Pipeline status | ✅ Implemented |
| `/api/v1/pipeline/config` | GET | Full config (sanitized) | ✅ Implemented |

#### Cameras
| Endpoint | Method | Action | Status |
|----------|--------|--------|--------|
| `/api/v1/cameras` | GET | List camera IDs | ✅ Implemented |
| `/api/v1/cameras/{id}` | GET | Camera metrics + state | ✅ Implemented |
| `/api/v1/cameras/{id}/health` | GET | Health check | ✅ Implemented |
| `/api/v1/cameras/{id}/start` | POST | Start camera | ✅ Implemented |
| `/api/v1/cameras/{id}/stop` | POST | Stop camera | ✅ Implemented |
| `/api/v1/cameras/{id}/restart` | POST | Restart camera | ✅ Implemented |
| `/api/v1/cameras/{id}/config` | PUT | Update config (restarts) | ✅ Implemented |

#### Attendance (STUB)
| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/attendance/events` | GET | Returns `[]` |
| `/api/v1/attendance/daily/{date}` | GET | Returns empty |
| `/api/v1/attendance/export` | GET | Not implemented |

#### Geometry
| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/geometry/lines` | GET | ✅ Returns line config |
| `/api/v1/geometry/lines/{id}` | GET | ✅ Returns line config |
| `/api/v1/geometry/lines/{id}` | PUT | ✅ Updates via CameraManager |

#### Models
| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/models` | GET | ✅ Lists configured models |
| `/api/v1/models/status` | GET | Returns empty |

#### Video Streams
| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/video/streams` | GET | ✅ Returns input/output URLs |

#### WebSocket
| Endpoint | Status |
|----------|--------|
| `/api/v1/ws` | ✅ Connection manager, echoes messages |

#### Metrics
| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/metrics` | GET | ✅ Returns `engine.get_health()` |

### Integration with PipelineEngine
```python
# lifespan():
engine = PipelineEngine()
engine.load_config()
engine.initialize()

def health_callback(health):
    asyncio.create_task(manager.broadcast({"type": "health", "data": health}))

engine.register_health_callback(health_callback)
# MISSING: Attendance event callback registration
```

### CORS
```python
allow_origins: ["*"]
allow_credentials: true
allow_methods: ["*"]
allow_headers: ["*"]
```

### Configuration (from pipeline.yaml)
```yaml
backend:
  host: "0.0.0.0"
  port: 0  # Dynamic
  cors: ...
  api_prefix: "/api/v1"
  pipeline_prefix: "/api/v1/pipeline"
  websocket:
    enabled: true
    path: "/ws"
    heartbeat_interval: 30
```

---

## Legacy Backend (Old) - NOT IN THIS REPO

### Inferred from Configuration
From `pipeline.yaml` integration section:
```yaml
integration:
  databases:
    attendance: "data/attendance.db"
    exit_sessions: "data/exit_sessions.db"
    notification_queue: "data/notification_queue.db"
    parent_registry: "data/parent_registry.db"
    embeddings: "data/embeddings.npy"
    embeddings_metadata: "data/embeddings.npy.metadata.json"
```

### Assumed Legacy Backend Responsibilities
Based on database ownership and UI requirements:

1. **Attendance API** - Authoritative attendance records (`data/attendance.db`)
2. **Enrollment API** - Person management, NPY database sync
3. **Camera Management** - Camera config, RTMP/RTSP endpoints
4. **Recording API** - Video playback, segment access
5. **Notification API** - Push notifications, Telegram
6. **Timetable API** - Schedule management
7. **Parent/Student API** - Registry, relationships
8. **Health/Metrics** - System monitoring
9. **WebSocket** - Real-time attendance events, camera health

### Legacy Backend Port
- Likely runs on port **8000** (UI config: `API_CONFIG.baseURL = 'http://localhost:8000'`)

---

## Integration Gaps

### 1. Attendance Data Flow
```
PipelineEngine (AttendanceEngine)
    → AttendanceStore (SQLite: attendance_events.db)
    → NO connection to Legacy Backend
    → PipelineEngine Backend attendance endpoints return []
    → UI calls Legacy Backend (port 8000) for attendance
    → Legacy Backend reads data/attendance.db (different DB!)
```

### 2. Camera Management
```
PipelineEngine Backend: /api/v1/cameras/* → CameraManager
Legacy Backend: /api/v1/cameras/* → data/attendance.db + config
UI: Uses Legacy Backend for camera list
Conflict: Two camera configuration sources
```

### 3. Enrollment / NPY
```
PipelineEngine: ArcFaceRecognizer loads embeddings.npy per camera
Legacy Backend: Manages enrollment, writes embeddings.npy
UI: ArcFace/NPY page writes embeddings.npy
Conflict: Multiple ArcFaceRecognizer instances (per camera) load same file
```

### 4. Geometry / Line Config
```
PipelineEngine Backend: PUT /api/v1/geometry/lines/{id} → CameraManager.update_camera_config()
Legacy Backend: Likely has own geometry API
UI: Live Monitoring page saves lines via WebSocket /api/line
Conflict: Two configuration paths
```

### 5. Health/Monitoring
```
PipelineEngine Backend: /api/v1/health/*, /api/v1/metrics → engine.get_health()
Legacy Backend: Likely has /health, /metrics
UI: Dashboard shows health from Legacy Backend WebSocket
```

### 6. Video Streams
```
PipelineEngine Backend: /api/v1/video/streams → Returns MediaMTX URLs
Legacy Backend: Likely same
MediaMTX: Single source of truth for stream paths
Status: CONSISTENT (both point to MediaMTX)
```

---

## Duplicate Responsibilities

| Responsibility | PipelineEngine Backend | Legacy Backend | Conflict |
|----------------|------------------------|----------------|----------|
| Camera start/stop | ✅ | ✅ (assumed) | YES |
| Camera config | ✅ | ✅ (assumed) | YES |
| Attendance events | ✅ (stub) | ✅ (authoritative) | YES |
| Geometry lines | ✅ | ✅ (assumed) | YES |
| Model management | ✅ | ✅ (assumed) | YES |
| Health metrics | ✅ | ✅ (assumed) | YES |
| Enrollment/NPY | ❌ | ✅ | NO (PipelineEngine reads only) |
| Video recording | ❌ | ✅ (MediaMTX) | NO |
| Notifications | ❌ | ✅ | NO |

---

## Required: Single Authoritative Backend

Per constraints: **"The existing backend must remain the only authoritative attendance data owner."**

### Integration Strategy

#### Option 1: PipelineEngine as Worker, Legacy Backend as API Gateway
- PipelineEngine exposes **internal gRPC/HTTP** for Legacy Backend to control
- Legacy Backend exposes **public REST/WebSocket** for UI
- PipelineEngine pushes attendance events to Legacy Backend
- Legacy Backend owns all databases

#### Option 2: PipelineEngine Backend → Proxy to Legacy Backend
- PipelineEngine Backend attendance endpoints proxy to Legacy Backend
- PipelineEngine Backend camera endpoints proxy to Legacy Backend
- Legacy Backend remains single API entry point

#### Option 3: Merge Backends (Not Recommended)
- Too much churn, violates constraint

### Recommended: Option 1 (PipelineEngine as Internal Service)

```
UI (port 5173/80)
    │
    ▼
Legacy Backend (port 8000) ← PUBLIC API
    │
    ├── REST: /api/v1/attendance, /api/v1/cameras, /api/v1/enrollment...
    ├── WebSocket: /ws (attendance events, health)
    │
    ▼ (internal)
PipelineEngine (internal port, e.g., 8081) ← INTERNAL API
    │
    ├── Control: start/stop cameras, restart pipeline
    ├── Metrics: get_health(), get_camera_metrics()
    ├── Events: AttendanceEngine callbacks → push to Legacy Backend
    │
    ▼
MediaMTX (port 8554, 9997)
```

### Required Changes

1. **PipelineEngine Backend**: 
   - Remove attendance endpoints (or make them proxy)
   - Remove camera management endpoints (or make them proxy)
   - Add internal event push to Legacy Backend

2. **Legacy Backend**:
   - Add internal API client for PipelineEngine
   - Receive attendance events from PipelineEngine
   - Broadcast attendance events via WebSocket
   - Own all databases

3. **AttendanceEngine**:
   - Add `LegacyBackendClient` to push events
   - Remove local SQLite `AttendanceStore`
   - Use `register_event_callback()` to push to Legacy Backend

4. **Configuration**:
   - PipelineEngine reads camera config from Legacy Backend (or shared config)
   - Single source of truth for camera geometry, line config

---

## Camera Configuration Sync

### Current
- PipelineEngine: `pipeline.yaml` (cameras section)
- Legacy Backend: `data/attendance.db` + config files
- UI: Reads from Legacy Backend

### Required
- Single config source (Legacy Backend DB or shared YAML)
- PipelineEngine loads config at startup from Legacy Backend
- Runtime config changes → Legacy Backend → PipelineEngine (via internal API)

---

## Enrollment/NPY Sync

### Current
- UI ArcFace page: Writes `embeddings.npy` + metadata
- PipelineEngine: Each camera loads NPY at startup (duplicate GPU memory)
- Legacy Backend: Presumably manages enrollment DB

### Required
- Single NPY file managed by Legacy Backend
- PipelineEngine: Shared ArcFaceRecognizer instance (not per-camera)
- Hot-reload NPY on enrollment changes (file watcher or API notification)

---

## WebSocket Integration

### PipelineEngine WebSocket (`/api/v1/ws`)
- Accepts connections, echoes messages
- Health broadcasts via `health_callback`
- **Missing**: Attendance event broadcasts

### Legacy Backend WebSocket (assumed)
- UI connects to `ws://localhost:8000/api/v1/health/ws`
- Receives: health updates, attendance events, camera status

### Required
- PipelineEngine pushes attendance events to Legacy Backend
- Legacy Backend broadcasts to UI WebSocket clients
- Unified message format

---

## Configuration Conflicts

### PipelineEngine Config (`pipeline.yaml`)
```yaml
cameras:
  cam1:
    input: {url: "rtsp://localhost:8554/live/cam1"}
    output: {path: "live/cam1-ai"}
    geometry: {line_start: [0,1080], line_end: [3840,1080]}
    ...
```

### Legacy Backend Config (inferred)
- Camera RTMP input URLs (for MediaMTX)
- Line geometry for attendance
- Model paths
- Database paths

### Resolution
- Legacy Backend owns camera configuration
- PipelineEngine receives config via internal API at startup
- Or: Both read from shared `pipeline.yaml` (Legacy Backend writes, PipelineEngine reads)

---

## Summary: Backend Integration Verdict

| Aspect | Status | Action Required |
|--------|--------|-----------------|
| Attendance ownership | CONFLICT | PipelineEngine → push to Legacy Backend |
| Camera management | CONFLICT | Legacy Backend authoritative |
| Geometry config | CONFLICT | Legacy Backend authoritative |
| Enrollment/NPY | PARTIAL CONFLICT | Shared NPY, single ArcFace instance |
| Health/metrics | DUPLICATE | Legacy Backend aggregates |
| Video streams | CONSISTENT | MediaMTX single source |
| Model management | DUPLICATE | Legacy Backend authoritative |

**PipelineEngine Backend should become an INTERNAL service**, not a public API gateway.