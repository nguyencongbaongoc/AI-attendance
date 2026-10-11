# AI Worker / Legacy Backend Integration Contract

## Integration Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ARCHITECTURE A INTEGRATION                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  VIDEO PATH                    AI PATH                      UI             │
│  ─────────────                 ────────                      ──            │
│  Camera 1 ─────┐              ┌─────────────┐               │             │
│                ├──► MediaMTX ◄──┤ AI Worker 1 │──► Events ──►│             │
│  Camera 2 ─────┘              │   (cam1)    │     (REST)   │  Legacy     │
│                               └─────────────┘               │  Backend    │
│                               ┌─────────────┐               │             │
│                               │ AI Worker 2 │──► Events ──►│             │
│                               │   (cam2)    │     (REST)   │             │
│                               └─────────────┘               │             │
│                                                                    │        │
│                                    WebSocket ◄─────────────────┘        │
│                                    (health, attendance)                │
│                                                                    │        │
│                                    ▼                                  │
│                                 UI (hls.js + Canvas)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## AI Worker Responsibilities

### Per-Camera AI Worker Process
1. **RTSP Ingestion**: PyAV reader → `live/cam1` or `live/cam2`
2. **Decode**: Software decode + GPU upload (no true NVDEC on Windows)
3. **Inference**: SCRFD (faces) + YOLO (persons) + ArcFace (embeddings)
4. **Tracking**: Geometry-based + face association + identity fusion
5. **Attendance**: Line crossing detection with debouncing
6. **Event Emission**: POST to Legacy Backend `/api/v1/attendance/events`
7. **Health Reporting**: Periodic health to Legacy Backend

### Shared Resources (Single GPU)
- **Single Model Instances**: One SCRFD, one YOLO, one ArcFace per GPU
- **Batch Inference Queue**: Accumulate frames, process in batches
- **Frame Pool**: Shared FramePoolManager across cameras
- **VRAM Monitoring**: GPUMemoryMonitor with pressure callbacks

## Integration Contract

### 1. Event Ingestion Endpoint (REQUIRED - NOT YET IMPLEMENTED)

**Endpoint**: `POST /api/v1/attendance/events` (Legacy Backend)
**Authentication**: Internal (network-level trust)

**Request**:
```json
{
  "source": "ai_worker",
  "worker_id": "ai_worker_cam1",
  "camera_id": "cam1",
  "stream_epoch": 3,
  "frame_pts": 2700000,
  "time_base_num": 1,
  "time_base_den": 90000,
  "capture_timestamp": 1234567890.123,
  "processing_timestamp": 1234567890.265,
  "track_id": "track_42",
  "global_track_id": "cam1_epoch3_track42",
  "bbox": [1000, 500, 1200, 900],
  "identity": {
    "person_id": "NV001",
    "person_name": "John Doe",
    "confidence": 0.94,
    "certainty": "KNOWN",
    "global_observation_id": "GO-abc123"
  },
  "event": {
    "type": "LINE_CROSSING",
    "direction": "IN",
    "crossing_point": [1500, 1080],
    "timestamp": 1234567890.123,
    "frame_index": 12345,
    "previous_position": [1450, 1100],
    "current_position": [1550, 1060]
  },
  "geometry": {
    "version": 1,
    "config_hash": "sha256:abc123...",
    "line_start": [0, 1080],
    "line_end": [3840, 1080],
    "direction_semantics": "side_a_to_b_in"
  },
  "resolver": {
    "version": "2.0",
    "config_hash": "sha256:def456...",
    "previous_state": "OUTSIDE",
    "new_state": "INSIDE"
  },
  "attendance_schema_version": "1.0"
}
```

**Response**: `202 Accepted` with `{ "event_id": "ATT-<hash>", "status": "accepted" }`

**Idempotency**: Legacy Backend deduplicates by `source_resolution_id` (generated from event fields)

### 2. Geometry Configuration Sync

**Legacy Backend Owns Geometry**
- UI saves geometry via `PUT /api/v1/geometry/lines/{camera_id}`
- Legacy Backend pushes to AI Workers via config reload signal

**AI Worker Config Reload**
- Watch config file or receive SIGHUP / HTTP reload endpoint
- On reload: Update `CrossingEngine` with new `LineGeometry` and `CrossingPolicyConfig`

### 3. Enrollment / NPY Sync

**Legacy Backend Owns NPY**
- UI enrollment writes `data/embeddings.npy` + metadata
- Legacy Backend signals AI Workers on NPY change

**AI Worker NPY Reload**
- ArcFaceRecognizer watches `embeddings.npy` (file modification time)
- On change: Reload enrollment database without restart

### 4. Health Reporting

**AI Worker → Legacy Backend**
- Periodic POST to `/api/v1/health/ai-worker` (NEW ENDPOINT NEEDED)
- Payload:
```json
{
  "worker_id": "ai_worker_cam1",
  "camera_id": "cam1",
  "status": "HEALTHY|DEGRADED|UNHEALTHY",
  "stream_epoch": 3,
  "input_fps": 29.8,
  "decode_fps": 29.5,
  "inference_fps": 28.0,
  "tracking_fps": 28.0,
  "attendance_events_count": 142,
  "queue_depth": 3,
  "frame_age_ms": 45,
  "gpu_memory_mb": 3420,
  "gpu_utilization_pct": 68,
  "decode_errors": 0,
  "inference_errors": 1,
  "last_event_timestamp": 1234567890.123,
  "errors": []
}
```

**Legacy Backend → UI**: Aggregated via WebSocket `/api/v1/health/ws`

### 4. Control Interface

**Legacy Backend → AI Worker** (NEW ENDPOINTS NEEDED)

| Action | Endpoint | Payload |
|--------|----------|---------|
| Start Camera | `POST /api/v1/ai/control/start` | `{"camera_id": "cam1"}` |
| Stop Camera | `POST /api/v1/ai/control/stop` | `{"camera_id": "cam1"}` |
| Restart Camera | `POST /api/v1/ai/control/restart` | `{"camera_id": "cam1"}` |
| Reload Config | `POST /api/v1/ai/control/reload` | `{"camera_id": "cam1"}` |
| Reload NPY | `POST /api/v1/ai/control/reload-npy` | `{"camera_id": "cam1"}` |

## Configuration Management

### AI Worker Config Sources (Priority Order)
1. **Legacy Backend API** (runtime overrides)
2. **Config File** (`pipeline.yaml` subset for AI path)
3. **Environment Variables**

### AI Worker Config Subset (from pipeline.yaml)
```yaml
# Only AI-relevant config
gpu:
  device_id: 0
  vram_budget_mb: 4096

cameras:
  cam1:
    input:
      url: "rtsp://localhost:8554/live/cam1"
      transport: "tcp"
    expected:
      codec: "h264"
      width: 3840
      height: 2160
      fps: 30
    decode:
      backend: "software_cuda_upload"
      gpu_device: 0
      surfaces: 16
    geometry:
      line_start: [0, 1080]
      line_end: [3840, 1080]
      direction_semantics: "side_a_to_b_in"
    crossing_policy:
      min_crossing_distance: 50.0
      temporal_debounce_seconds: 2.0
      side_confirmation_frames: 3
      max_trajectory_gap_frames: 5

models:
  scrfd:
    path: "models/scrfd/scrfd_10g_bnkps.onnx"
    input_size: [640, 640]
    confidence_threshold: 0.5
    nms_threshold: 0.4
  arcface:
    path: "models/arcface/glintr100.onnx"
    input_size: [112, 112]
    similarity_threshold: 0.6
  yolo:
    path: "models/yolo/yolo11n.onnx"
    input_size: [640, 640]
    confidence_threshold: 0.5
    nms_threshold: 0.45

tracking:
  min_iou_threshold: 0.3
  max_lost_frames: 10
  use_face_association: true
  face_center_weight: 0.5

attendance:
  default_debounce_seconds: 2.0
```

## Error Handling & Retry

### Event Posting Retry
- Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s (max)
- Max retries: 10
- Local persistence of unsent events (SQLite queue)
- Reconciliation on startup: query Legacy Backend for missing events

### Circuit Breaker
- If Legacy Backend returns 5xx or timeout > 30s for 5 consecutive requests
- Open circuit: queue locally, stop posting
- Half-open: test request every 60s
- Close: 3 consecutive successes

### Error Classification
| Error Type | Action |
|------------|--------|
| 4xx (validation) | Log, don't retry, alert |
| 5xx (server) | Retry with backoff |
| Timeout | Retry with backoff |
| Connection refused | Retry with backoff |
| Duplicate (409) | Accept, don't retry |

## Authentication & Security

### Current State: NONE
- No authentication between AI Worker and Legacy Backend
- Assumes trusted internal network

### Required for Production
- mTLS between AI Worker and Legacy Backend
- Or: Shared secret HMAC on requests
- Or: Network segmentation (separate VLAN)

## Deployment Topology

### Option 1: Same Host (Current Dev)
- Legacy Backend: Port 8000 (dynamic)
- AI Worker cam1: Internal port 8081
- AI Worker cam2: Internal port 8082
- MediaMTX: Ports 8554, 8888, 8889, 9997, 1935

### Option 2: Separate Hosts (Production)
- Legacy Backend: Dedicated server
- AI Workers: GPU servers (one per GPU)
- MediaMTX: Media server
- Network: Private VLAN, firewall rules

## Startup Sequence

### Legacy Backend
1. Start FastAPI on dynamic port
2. Initialize databases, health monitor
3. Start WebSocket broadcast task
4. Wait for AI Workers to register (health endpoint)

### AI Worker (per camera)
1. Load config (Legacy Backend API → config file → env)
2. Initialize models (SCRFD, YOLO, ArcFace)
3. Load enrollment NPY
4. Connect to RTSP stream (`live/cam1` or `live/cam2`)
5. Start decode → inference → tracking → attendance loop
6. Register with Legacy Backend (health endpoint)
7. Begin event posting

## Shutdown Sequence

### AI Worker
1. Receive stop signal (SIGTERM / HTTP)
2. Stop accepting new frames
3. Flush event queue to Legacy Backend (with timeout)
4. Close RTSP connection
5. Release GPU resources (models, frame pool)
6. Exit

### Legacy Backend
1. Stop accepting new connections
2. Wait for AI Workers to disconnect gracefully
3. Close databases
4. Exit

## Evidence References

| Component | File | Lines |
|-----------|------|-------|
| PipelineEngine CameraManager | `pipeline_engine/ingestion/camera_manager.py` | 270-434 |
| PipelineEngine AttendanceEngine | `pipeline_engine/attendance/attendance_engine.py` | 456-579 |
| Legacy Backend Attendance API | `app/api/attendance.py` | 1-369 |
| Legacy Backend Health API | `app/api/health.py` | 1-560 |
| Legacy Backend WebSocket | `app/api/websocket.py` | 1-602 |
| PipelineEngine Config | `pipeline_engine/config/pipeline.yaml` | 1-434 |
| Legacy Backend Config | `app/config/settings.py` | (referenced) |

## Verification Status

| Contract Element | Source Verified | Legacy Backend Implemented | AI Worker Implemented |
|------------------|-----------------|----------------------------|----------------------|
| Event Ingestion POST | ❌ DESIGN | ❌ MISSING | ❌ MISSING |
| Geometry Sync | ❌ DESIGN | ✅ PUT exists | ❌ MISSING |
| NPY Reload | ❌ DESIGN | ❌ MISSING | ⚠️ File watcher possible |
| AI Health Reporting | ❌ DESIGN | ❌ MISSING | ❌ MISSING |
| AI Control Endpoints | ❌ DESIGN | ❌ MISSING | ❌ MISSING |
| Config Management | ✅ pipeline.yaml | ✅ settings.py | ✅ CameraManager loads config |