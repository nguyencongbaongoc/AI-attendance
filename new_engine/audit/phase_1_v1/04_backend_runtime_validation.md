# Phase 1.V1 Backend Runtime Validation

**Date**: 2026-10-04
**Phase**: 1.V1 - Environment and Camera Source Recovery

---

## 1. Legacy Backend Status

### Process Check
```powershell
Get-Process -Name "*backend*" -ErrorAction SilentlyContinue
Get-Process | Where-Object {$_.ProcessName -like "*python*"} | Select-Object Id, ProcessName, CPU, WS
```

**Result**: No backend process running. No Python processes detected.

### Network Port Check
- **Port 19146**: Not listening
- **Health Endpoint**: `http://localhost:19146/health` - No response
- **API Endpoint**: `http://localhost:19146/api/v1/attendance/events` - No response

---

## 2. Backend Implementation Analysis

### Entry Point: `app/main.py`
```python
# FastAPI application with:
# - Health monitoring (/api/v1/health/system, /api/v1/health/live, /api/v1/health/ready)
# - WebSocket support
# - Attendance, persons, timetable, excel, parent_telegram, geometry, enrollment, ai_worker, replay, provenance routers
# - Static file serving for /recordings
# - Dynamic port discovery via bootstrap.port_discovery.find_backend_port()
```

### Dynamic Port Discovery
```python
from app.bootstrap.port_discovery import find_backend_port
backend_port = find_backend_port()  # Returns dynamic port, not fixed 19146
```

### Routers Included
1. `health_router` - System health
2. `websocket_router` - Real-time updates
3. `attendance_router` - Attendance records
4. `persons_router` - Person management
5. `timetable_router` - Timetable
6. `excel_router` - Excel export
7. `parent_telegram_router` - Parent notifications
8. `geometry_router` - Line/ROI geometry
9. `enrollment_router` - Person enrollment
10. `ai_worker_router` - **AI Worker integration (CRITICAL)**
11. `replay_router` - Video replay
12. `provenance_router` - Provenance chain

---

## 3. AI Worker Integration Endpoints (`app/api/ai_worker.py`)

### Authentication
```python
# Three distinct API keys required:
AI_WORKER_API_KEY    # For event ingestion + health reporting
AI_CONTROL_API_KEY   # For control command polling
ADMIN_API_KEY        # For control command submission + enrollment reload
```

### Endpoint 1: Event Ingestion
```
POST /api/v1/attendance/events
Headers: X-API-Key: <AI_WORKER_API_KEY>
Body: CrossingEventRequest
Response: CrossingEventResponse (success, event_id, source_resolution_id, status, message)

Flow:
1. Validate CrossingEvent schema
2. Convert to RawInOutEvent (Phase 23)
3. Submit to Phase 24 Resolver (RepeatedInOutResolver)
4. Return source_resolution_id immediately
5. Async: Resolver → AttendanceRecord (Phase 25)
```

### Endpoint 2: Health Heartbeat
```
POST /api/v1/health/ai-worker
Headers: X-API-Key: <AI_WORKER_API_KEY>
Body: AIWorkerHealthRequest
Response: AIWorkerHealthResponse (acknowledged, commands[], stale_threshold)

Features:
- Sequence number validation (monotonic)
- Generation tracking (restart detection)
- Stale worker detection (30s threshold)
- Returns pending control commands
```

### Endpoint 3: Control Commands (Admin → Worker)
```
POST /api/v1/ai/control/{action}
Headers: X-API-Key: <ADMIN_API_KEY>
Actions: START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS
```

### Endpoint 4: Control Polling (Worker → Backend)
```
GET /api/v1/ai/control/pending?worker_id={id}&limit=50&since={ts}
Headers: X-API-Key: <AI_CONTROL_API_KEY>
Response: PendingControlRequests {worker_id, requests[]}
```

### Endpoint 5: Control Response (Worker → Backend)
```
POST /api/v1/ai/control/{action}/response
Headers: X-API-Key: <AI_CONTROL_API_KEY>
Body: ControlResponse
```

### Endpoint 6: Enrollment Reload
```
POST /api/v1/enrollment/reload
Headers: X-API-Key: <ADMIN_API_KEY>
Body: EnrollmentReloadRequest {trigger, expected_version}
Response: EnrollmentReloadResponse
```

---

## 4. Phase 22-25 Resolver Chain (Backend)

### Phase 22: In/Out Geometry
- Line crossing detection with configurable geometry
- Side semantics: `side_a_to_b_in` or `side_b_to_a_in`

### Phase 23: RawInOutEvent
```python
RawInOutEvent(
    raw_event_id, camera_id, local_track_id, direction,
    source_timestamp, source_frame_index, track_position_x/y,
    person_id, person_name, identity_confidence,
    stream_epoch, pts, time_base_num/den,
    capture_timestamp, processing_timestamp,
    model_version, enrollment_version, provenance
)
```

### Phase 24: RepeatedInOutResolver
```python
resolver.resolve(raw_event) -> ResolutionResult
ResolutionResult.transitions[] -> ResolvedTransition
ResolvedTransition.resolution_id -> Used as source_resolution_id
```

### Phase 25: AttendancePersistence
- ResolvedTransition → AttendanceRecord in database
- Daily records, Excel export, timetable integration

---

## 5. Database Configuration

### Legacy Databases (from pipeline.yaml integration.databases)
```yaml
databases:
  attendance: "data/attendance.db"           # Primary attendance records
  exit_sessions: "data/exit_sessions.db"     # Exit session tracking
  notification_queue: "data/notification_queue.db"
  parent_registry: "data/parent_registry.db"
  embeddings: "data/embeddings.npy"          # ArcFace embeddings
  embeddings_metadata: "data/embeddings.npy.metadata.json"
```

### Existing Database Files
| File | Size | Purpose |
|------|------|---------|
| data/attendance.db | 64 KB | Legacy attendance |
| data/attendance_events.db | 20 KB | PipelineEngine AttendanceEngine store |
| data/exit_sessions.db | 24 KB | Exit sessions |
| data/notification_queue.db | 32 KB | Notifications |
| data/parent_registry.db | 45 KB | Parent registry |

---

## 6. Required Backend Startup

### Command
```bash
cd C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE
& ".venv2\Scripts\python.exe" -m app.main
```

### Expected Behavior
1. Load settings from `app/config/settings.py`
2. Dynamic port discovery (finds free port, likely 19146 if available)
3. Start uvicorn on 0.0.0.0:{port}
4. Initialize all routers
5. Health endpoints available immediately
6. AI Worker endpoints require API keys in environment

### Environment Variables Needed
```bash
AI_WORKER_API_KEY=<secure-random-key>
AI_CONTROL_API_KEY=<secure-random-key>
ADMIN_API_KEY=<secure-random-key>
# Optional overrides:
BACKEND_BASE_URL=http://localhost:19146
WORKER_ID=pipeline_engine_1
```

---

## 7. Backend Runtime Validation Plan

### Pre-Start Checks
- [ ] Environment variables configured
- [ ] Database files accessible
- [ ] Enrollment database exists (or enrollment API ready)
- [ ] Port 19146 available (or dynamic discovery works)

### Post-Start Validation
1. **Health Endpoints**
   - `GET /api/v1/health/live` → `{"status": "alive"}`
   - `GET /api/v1/health/ready` → `{"status": "ready", "checks": {...}}`
   - `GET /api/v1/health/system` → Full system health

2. **AI Worker Endpoints (require auth)**
   - `POST /api/v1/health/ai-worker` → 401 without key, 400 with invalid sequence
   - `POST /api/v1/attendance/events` → 401 without key
   - `GET /api/v1/ai/control/pending` → 401 without key

3. **Enrollment Endpoints**
   - `POST /api/v1/enrollment/persons` → 401 without admin key
   - `POST /api/v1/enrollment/reload` → 401 without admin key

---

## 8. Current Blocker Status

**BACKEND NOT RUNNING** - Critical blocker for:
- V2: Event delivery testing (EventDeliveryClient → Backend)
- V4: End-to-end attendance proof (CrossingEvent → AttendanceRecord)
- V5: Final qualification

### Resolution Required
Start Legacy Backend with API keys configured before proceeding to V2.

---

## 9. Architecture Compliance Check

| Requirement | Status | Notes |
|-------------|--------|-------|
| Legacy Backend sole attendance authority | ✅ Implemented | ai_worker.py only ingests events |
| Phase 22-25 resolver chain | ✅ Implemented | RawInOutEvent → Resolver → AttendanceRecord |
| AI Worker never writes AttendanceRecord directly | ✅ Verified | EventDeliveryClient posts to /api/v1/attendance/events |
| Three-tier API key separation | ✅ Implemented | WORKER, CONTROL, ADMIN keys |
| Idempotent event ingestion | ✅ Implemented | CrossingEventRequest.event_id deduplication |
| Sequence validation on health | ✅ Implemented | Monotonic sequence + generation tracking |
| Stale worker detection | ✅ Implemented | 30s threshold |

---

## 10. Backend Validation Verdict

**STATUS**: ❌ **NOT RUNNING** - Blocker for V2+

**Required Action**: Start Legacy Backend with:
1. `AI_WORKER_API_KEY`, `AI_CONTROL_API_KEY`, `ADMIN_API_KEY` in environment
2. Verify health endpoints respond
3. Verify AI Worker endpoints accept authenticated requests
4. Verify enrollment API can create test enrollments

**Next Step**: Resolve in V1.6 Blocker Resolution before V2.