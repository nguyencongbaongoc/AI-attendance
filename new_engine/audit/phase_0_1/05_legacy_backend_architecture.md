# Legacy Backend Architecture

## Application Structure

### Entry Point
**File**: `app/main.py` (148 lines)
- FastAPI application with lifespan manager
- Dynamic port discovery via `find_backend_port()`
- CORS enabled for all origins
- Static file mount for `/recordings`
- 11 API routers included manually (due to FastAPI version issue)

### Routers Included
1. `health_router` - `/api/v1/health` - System health, camera health, GPU status, metrics
2. `websocket_router` - `/api/v1/health/ws` - WebSocket/SSE real-time health
3. `attendance_router` - `/api/v1/attendance` - Attendance records, queries
4. `persons_router` - Person management
5. `timetable_router` - Timetable management
6. `excel_router` - Excel export
7. `parent_telegram_router` - Parent notifications
8. `geometry_router` - Line geometry management
9. `enrollment_router` - Face enrollment / NPY management
10. `replay_router` - Video replay
11. `provenance_router` - Provenance chain

### Configuration
**File**: `app/config/settings.py` (not read yet, but referenced)
- Loads settings via `load_settings()`
- Settings include: paths, runtime, parent_registry, notification_queue, exit_session, telegram
- Directories ensured on startup

### Bootstrap
**File**: `app/bootstrap/port_discovery.py` - Dynamic port allocation
**File**: `bootstrap.py` - Main bootstrap script at repo root

## Core Subsystems

### 1. Health Monitoring (`app/streaming/`)
- `shared_health.py` - Shared health monitor across processes
- `health_events.py` - HealthEvent, HealthEventType for real-time propagation
- Camera health tracking: frames received/dropped, errors, reconnects, FPS, resolution
- Inference active flag per camera

### 2. Attendance System (`app/attendance/`)
- `contract.py` - AttendanceRecord (immutable), AttendanceDirection (IN/OUT), IdentityCertainty (KNOWN/UNKNOWN/AMBIGUOUS/INSUFFICIENT)
- `repository.py` - AttendanceRepository bridges Phase 24 ResolutionResult to storage
- `storage.py` - SQLite storage with full query capabilities
- `query.py` - AttendanceQueryBuilder, summaries, timelines
- `policy_engine/` - In/Out policy, deduplication, Telegram notifications, exit sessions, parent registry

### 3. Streaming Pipeline (`app/streaming/`)
- `camera_supervisor.py` - Camera lifecycle management
- `annotated_publisher.py` - AnnotatedFramePublisher for AI overlay
- `rtmp_source.py` / `rtsp_source.py` - Stream ingestion
- `shared_health.py` - Cross-process health monitor

### 4. In/Out Resolution (`app/in_out/`)
- `resolver.py` - Phase 24 resolver converting RawInOutEvent to ResolvedTransition
- `resolver_contract.py` - ResolvedTransition, ResolutionResult, DerivedState
- `event.py` - RawInOutEvent, CrossingEvent from Phase 22/23

### 5. Geometry (`app/geometry/`)
- Line geometry management
- Camera-specific line configuration

### 6. Enrollment / NPY (`app/vision/`, `app/api/enrollment.py`)
- Face detection, alignment, embedding generation
- NPY database management

### 7. Replay (`app/replay/`, `app/api/replay.py`)
- Video segment listing
- Playback endpoints

### 8. Provenance (`app/provenance/`, `app/api/provenance.py`)
- Full chain: AttendanceRecord -> ResolvedTransition -> RawInOutEvent -> CrossingEvent

## Data Flow (Legacy Backend)

```
Camera RTMP → MediaMTX → RTSP → app.streaming (rtsp_source)
    → Frame processing → Crossing detection → RawInOutEvent
    → Phase 24 Resolver → ResolvedTransition
    → Phase 25 AttendanceRepository → AttendanceRecord (SQLite)
    → API / WebSocket → UI
```

## Key Design Principles

### Immutable Records
- `AttendanceRecord` is frozen dataclass (`frozen=True`)
- Deterministic ID generation from `source_resolution_id`
- Full provenance chain preserved

### Idempotent Persistence
- `AttendanceRepository.persist_resolution_result()` skips duplicates by `source_resolution_id`
- `AttendanceStorage.insert()` returns False if duplicate

### Phase Separation
- Phase 22: CrossingEvent (geometry)
- Phase 23: RawInOutEvent (camera tracker)
- Phase 24: ResolvedTransition (resolver with debouncing)
- Phase 25: AttendanceRecord (persisted, queryable)

## Process Architecture

### Single Process (Current)
All components run in single FastAPI process:
- Camera supervisors
- Stream ingestion
- Inference (if enabled)
- Attendance resolution
- API serving
- WebSocket broadcasting

### Health Monitor
- `app/streaming/shared_health.py` - SharedHealthMonitor
- Singleton per process
- Tracks per-camera state, inference activity
- WebSocket broadcasts health snapshots every 5s
- Heartbeat/ping every 10s

## Configuration Management

### Settings (`app/config/settings.py`)
Central configuration object with:
- `paths` - data_dir, models_dir, logs_dir, recordings_dir
- `runtime` - debug, log_level
- `parent_registry` - db_path
- `notification_queue` - db_path
- `exit_session` - db_path
- `telegram` - bot_token, chat_ids

### Directory Structure
```
data/
  attendance.db           # Phase 25 attendance records
  parent_registry.db      # Parent/student mapping
  notification_queue.db   # Telegram notifications
  exit_sessions.db        # Exit session tracking
logs/
models/
recordings/               # MediaMTX fMP4 recordings
```

## Database Schema (Attendance)

**File**: `app/attendance/storage.py` (referenced by repository)

### AttendanceRecord Table
Primary fields from `AttendanceRecord`:
- `attendance_record_id` (PK, deterministic from source_resolution_id)
- `identity_certainty` - KNOWN/UNKNOWN/AMBIGUOUS/INSUFFICIENT
- `identity_candidate` - Person ID if known
- `identity_confidence` - Float
- `direction` - IN/OUT
- `event_timestamp` - Wall-clock from upstream
- `event_frame_index` - Frame index
- `camera_id` - Camera identifier
- `local_track_id` - Track ID within camera
- `global_observation_id` - Cross-camera identity
- `source_raw_event_id` - Phase 23 event ID
- `source_resolution_id` - Phase 24 resolution ID (unique key)
- `source_crossing_event_id` - Phase 22 crossing ID
- `geometry_version` / `geometry_config_hash` - Geometry provenance
- `resolver_version` / `resolver_config_hash` - Resolver provenance
- `previous_state` / `new_state` - INSIDE/OUTSIDE/UNKNOWN
- `created_at` / `persisted_at` - Timestamps

### Indexes
- `source_resolution_id` (unique)
- `camera_id` + `event_timestamp`
- `global_observation_id`
- `identity_candidate` + `event_timestamp`

## API Design Patterns

### Response Models
All endpoints use Pydantic models for request/response validation.

### Error Handling
- HTTPException with appropriate status codes
- Consistent error response format

### Query Pattern
- `AttendanceQueryBuilder` for flexible filtering
- Supports: camera_id, track_id, global_observation_id, direction, identity_certainty, time range
- Pagination with limit/offset
- Ordering by event_timestamp

### Real-time Updates
- WebSocket `/api/v1/health/ws` with sequence numbers
- SSE `/api/v1/health/stream` with last_seq for reconnect
- Explicit ping/pong for stale detection
- Sync protocol for reconnection recovery

## Integration Points

### Camera Management
- Camera health reported via `/api/v1/health/cameras`
- Frame/error/reconnect reporting endpoints for streaming pipeline
- Geometry management via `/api/v1/geometry/lines`

### Attendance Events
- Generated from Phase 24 resolver
- Persisted via AttendanceRepository
- Queried via `/api/v1/attendance/records`
- Real-time via WebSocket health events

### Enrollment
- Face detection/crop/embedding via `/api/v1/enrollment/`
- NPY database management

### Video
- Recordings served statically from `/recordings/`
- Replay endpoints for segment listing

## Authentication/Authorization

**Current**: No authentication implemented
- CORS allows all origins
- No JWT, API keys, or session management
- Internal network assumption

## Observability

### Metrics
- Camera: frames_received, frames_dropped, FPS, errors, uptime
- Queue: pending/sent/failed, latency percentiles
- Database: parent counts, exit session stats
- GPU: VRAM, utilization, model availability

### Health Checks
- Liveness: `/api/v1/health/live`
- Readiness: `/api/v1/health/ready` (checks DB files, directories)
- System: `/api/v1/health/system` (comprehensive)

## Version Information
- API Version: 1.0.0
- Attendance Schema: 1.0
- Resolver Version: 1.0 (from ResolvedTransition)

## Evidence Summary

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Main Entry | `app/main.py` | 148 | ✅ SOURCE-VERIFIED |
| Health API | `app/api/health.py` | 560 | ✅ SOURCE-VERIFIED |
| Attendance API | `app/api/attendance.py` | 369 | ✅ SOURCE-VERIFIED |
| WebSocket | `app/api/websocket.py` | 602 | ✅ SOURCE-VERIFIED |
| Attendance Contract | `app/attendance/contract.py` | 359 | ✅ SOURCE-VERIFIED |
| Attendance Repository | `app/attendance/repository.py` | 355 | ✅ SOURCE-VERIFIED |
| Main Bootstrap | `bootstrap.py` | ~200 | ✅ EXISTS |
| Config | `app/config/settings.py` | - | ⚠️ NOT READ |

**Runtime Status**: NOT RUNNING - No FastAPI process detected, no ports listening on expected ports (8000, 8554, 8888, 8889, 9997)