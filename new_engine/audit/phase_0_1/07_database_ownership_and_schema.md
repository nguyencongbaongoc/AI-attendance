# Database Ownership and Schema

## Database Files Identified

### Legacy Backend Databases (Authoritative)
From `app/config/settings.py` references and `app/api/health.py` checks:

| Database | Path | Purpose | Owner |
|----------|------|---------|-------|
| Attendance | `data/attendance.db` | Phase 25 AttendanceRecord storage | **Legacy Backend** |
| Parent Registry | `data/parent_registry.db` | Parent/student mapping, Telegram chat_ids | **Legacy Backend** |
| Notification Queue | `data/notification_queue.db` | Telegram notification queue | **Legacy Backend** |
| Exit Sessions | `data/exit_sessions.db` | Exit session tracking | **Legacy Backend** |

### PipelineEngine Databases (New - Conflict)
From `pipeline_engine/config/pipeline.yaml` integration section:
| Database | Path | Purpose | Owner |
|----------|------|---------|-------|
| Attendance Events | `data/attendance_events.db` | CrossingEvent storage | PipelineEngine |
| Daily Records | `data/attendance_daily.db` | Daily summaries | PipelineEngine |

### Shared Data
| File | Path | Purpose | Access |
|-------|------|---------|--------|
| Embeddings | `data/embeddings.npy` | Face recognition database | **Both** (Legacy writes, PipelineEngine reads) |
| Embeddings Meta | `data/embeddings.npy.metadata.json` | Enrollment metadata | **Both** |

## Schema Analysis

### Legacy Backend: `attendance.db` (Authoritative)

**Table**: `attendance_records` (from `app/attendance/storage.py`)

```sql
CREATE TABLE attendance_records (
    attendance_record_id TEXT PRIMARY KEY,  -- Deterministic from source_resolution_id
    identity_certainty TEXT NOT NULL,       -- KNOWN/UNKNOWN/AMBIGUOUS/INSUFFICIENT
    identity_candidate TEXT,                -- Person ID if known
    identity_confidence REAL DEFAULT 0.0,
    identity_evidence_ref TEXT,             -- GlobalObservation ID
    direction TEXT NOT NULL,                -- IN/OUT
    event_timestamp REAL NOT NULL,          -- Wall-clock from upstream
    event_frame_index INTEGER DEFAULT -1,
    camera_id TEXT NOT NULL,
    local_track_id TEXT NOT NULL,
    global_observation_id TEXT,             -- Cross-camera identity
    source_raw_event_id TEXT NOT NULL,      -- Phase 23 RawInOutEvent ID
    source_resolution_id TEXT NOT NULL UNIQUE, -- Phase 24 ResolvedTransition ID
    source_crossing_event_id TEXT,          -- Phase 22 CrossingEvent ID
    geometry_version INTEGER DEFAULT 0,
    geometry_config_hash TEXT DEFAULT '',
    resolver_version TEXT DEFAULT '1.0',
    resolver_config_hash TEXT DEFAULT '',
    previous_state TEXT NOT NULL,           -- INSIDE/OUTSIDE/UNKNOWN
    new_state TEXT NOT NULL,                -- INSIDE/OUTSIDE/UNKNOWN
    attendance_schema_version TEXT DEFAULT '1.0',
    created_at TEXT NOT NULL,               -- Event creation (ISO8601)
    persisted_at TEXT NOT NULL              -- Persistence time (ISO8601)
);

-- Indexes
CREATE INDEX idx_source_resolution ON attendance_records(source_resolution_id);
CREATE INDEX idx_camera_time ON attendance_records(camera_id, event_timestamp);
CREATE INDEX idx_global_obs ON attendance_records(global_observation_id);
CREATE INDEX idx_identity_time ON attendance_records(identity_candidate, event_timestamp);
```

### PipelineEngine: `attendance_events.db` (New - Conflict)

**Table**: `attendance_events` (from `pipeline_engine/attendance/attendance_engine.py`)

```sql
CREATE TABLE attendance_events (
    event_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    direction TEXT NOT NULL,                -- IN/OUT
    event_type TEXT NOT NULL,               -- LINE_CROSSING
    crossing_point_x REAL NOT NULL,
    crossing_point_y REAL NOT NULL,
    timestamp REAL NOT NULL,
    frame_index INTEGER NOT NULL,
    previous_position_x REAL NOT NULL,
    previous_position_y REAL NOT NULL,
    current_position_x REAL NOT NULL,
    current_position_y REAL NOT NULL,
    person_id TEXT,
    person_name TEXT,
    identity_confidence REAL,
    created_at REAL NOT NULL                -- Unix timestamp
);

-- Indexes
CREATE INDEX idx_camera_timestamp ON attendance_events(camera_id, timestamp);
CREATE INDEX idx_person_timestamp ON attendance_events(person_id, timestamp);
```

### PipelineEngine: `attendance_daily.db` (New - Conflict)

Daily summaries table (from `attendance_engine.py`)

## Ownership Conflict Analysis

### Current State
1. **Legacy Backend** owns `data/attendance.db` - authoritative for UI, queries, exports
2. **PipelineEngine** writes to `data/attendance_events.db` - separate SQLite DB
3. **UI** reads from Legacy Backend API (`/api/v1/attendance/*`)
4. **PipelineEngine Backend** attendance endpoints return empty (`[]`)

### Conflict Points

| Aspect | Legacy Backend | PipelineEngine | Conflict |
|--------|----------------|----------------|----------|
| Attendance Storage | `attendance.db` (Phase 25) | `attendance_events.db` (CrossingEvent) | **Two independent DBs** |
| Schema | Full provenance (Phase 22-25) | Simplified crossing event | **Incompatible** |
| Query API | Full (`/records`, `/summary`, `/timeline`) | None (stubs) | **PipelineEngine not integrated** |
| UI Consumption | Yes (Legacy Backend) | No | **Data invisible to UI** |
| Export | Excel via Legacy Backend | JSON via PipelineEngine | **Fragmented** |

### Provenance Chain Difference

**Legacy Backend** (Full Chain):
```
AttendanceRecord 
  → source_resolution_id (Phase 24 ResolvedTransition)
  → source_raw_event_id (Phase 23 RawInOutEvent)  
  → source_crossing_event_id (Phase 22 CrossingEvent)
  → geometry_version + geometry_config_hash
  → resolver_version + resolver_config_hash
  → previous_state / new_state (INSIDE/OUTSIDE)
```

**PipelineEngine** (Simplified):
```
CrossingEvent
  → track_id, camera_id
  → person_id (from tracker)
  → crossing_point, timestamp
  → direction (IN/OUT)
  → NO link to Phase 22/23/24
```

## Required Resolution for Architecture A

### Constraint
> "The existing backend must remain the only authoritative attendance data owner."

### Required Changes

1. **PipelineEngine MUST NOT write to separate SQLite DB**
   - Remove `AttendanceStore` class in `pipeline_engine/attendance/attendance_engine.py`
   - Remove `attendance_events.db` and `attendance_daily.db` creation

2. **PipelineEngine MUST push events to Legacy Backend**
   - Implement `LegacyBackendClient` with `push_attendance_event(event)`
   - Target endpoint: `POST /api/v1/attendance/events` (NEEDS TO BE ADDED to Legacy Backend)
   - Or: Direct SQLite write to `data/attendance.db` (NOT RECOMMENDED - tight coupling)

3. **Legacy Backend MUST accept AI worker events**
   - Add `POST /api/v1/attendance/events` endpoint
   - Accept `CrossingEvent` format, convert to `AttendanceRecord`
   - Or accept `AttendanceRecord` directly

4. **Single Source of Truth**
   - `data/attendance.db` remains authoritative
   - Legacy Backend handles all queries, exports, WebSocket broadcasts
   - PipelineEngine is event producer only

### Event Format Conversion

**PipelineEngine CrossingEvent** → **Legacy Backend AttendanceRecord**

| CrossingEvent Field | AttendanceRecord Field | Notes |
|---------------------|------------------------|-------|
| `event_id` | `source_crossing_event_id` | |
| `camera_id` | `camera_id` | |
| `track_id` | `local_track_id` | String conversion |
| `direction` | `direction` | IN/OUT |
| `crossing_point` | (geometry provenance) | Store in metadata |
| `timestamp` | `event_timestamp` | Wall-clock |
| `frame_index` | `event_frame_index` | |
| `person_id` | `identity_candidate` | |
| `person_name` | (lookup from registry) | |
| `identity_confidence` | `identity_confidence` | |
| (new) | `source_resolution_id` | Generate from crossing_event_id |
| (new) | `global_observation_id` | From tracker if available |
| (new) | `previous_state` / `new_state` | Derive from direction |

## Evidence Summary

| Database | File | Owner | Verification |
|----------|------|-------|--------------|
| `attendance.db` | Legacy `storage.py` | Legacy Backend | ✅ SOURCE-VERIFIED |
| `parent_registry.db` | Health checks | Legacy Backend | ✅ SOURCE-VERIFIED |
| `notification_queue.db` | Health checks | Legacy Backend | ✅ SOURCE-VERIFIED |
| `exit_sessions.db` | Health checks | Legacy Backend | ✅ SOURCE-VERIFIED |
| `attendance_events.db` | PipelineEngine `attendance_engine.py` | PipelineEngine | ✅ SOURCE-VERIFIED |
| `attendance_daily.db` | PipelineEngine `attendance_engine.py` | PipelineEngine | ✅ SOURCE-VERIFIED |
| `embeddings.npy` | Both read | Shared | ✅ FILE EXISTS |

## Verdict

**CRITICAL CONFLICT**: Two independent attendance databases with incompatible schemas.

**Resolution**: PipelineEngine must be refactored to push events to Legacy Backend API. Legacy Backend must expose ingestion endpoint. Single authoritative store: `data/attendance.db`.