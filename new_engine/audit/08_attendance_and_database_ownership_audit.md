# Attendance and Database Ownership Audit

## Attendance Engine (`attendance/attendance_engine.py`)

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

### Architecture
- Line crossing detection with configurable geometry
- Temporal debouncing and distance validation
- SQLite event store (local file)
- Callback system for real-time event notification

### Core Components

#### 1. LineGeometry
```python
@dataclass
class LineGeometry:
    p1: Tuple[float, float]  # Line start (x, y)
    p2: Tuple[float, float]  # Line end (x, y)
    direction_semantics: str  # "side_a_to_b_in" or "side_b_to_a_in"
    
    def side_of_point(point) -> int:  # 1, -1, 0
    def distance_to_line(point) -> float:
```

#### 2. CrossingPolicyConfig
```python
@dataclass
class CrossingPolicyConfig:
    min_crossing_distance: float = 50.0      # Min distance from line
    temporal_debounce_seconds: float = 2.0   # Min time between crossings
    side_confirmation_frames: int = 3        # Frames to confirm side
    max_trajectory_gap_frames: int = 5       # Max gap before reset
```

#### 3. CrossingEvent
```python
@dataclass
class CrossingEvent:
    event_id: str
    camera_id: str
    track_id: int
    direction: CrossingDirection  # IN / OUT
    crossing_point: Tuple[float, float]
    timestamp: float
    frame_index: int
    previous_position: Tuple[float, float]
    current_position: Tuple[float, float]
    person_id: Optional[str]
    person_name: Optional[str]
    identity_confidence: float
```

#### 4. CrossingEngine (per camera)
- Maintains per-track state: `current_side`, `confirmed_side`, `frames_on_current_side`
- Detects crossing: `prev_side != current_side` (both non-zero)
- Validates: debounce time, crossing distance, side confirmation
- Calculates intersection point of trajectory with line

#### 5. AttendanceStore (SQLite)
```sql
CREATE TABLE attendance_events (
    event_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    event_type TEXT NOT NULL,
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
    created_at REAL NOT NULL
);

CREATE INDEX idx_camera_timestamp ON attendance_events(camera_id, timestamp);
CREATE INDEX idx_person_timestamp ON attendance_events(person_id, timestamp);
```

### Data Flow
```
TrackingResult (from Tracker)
    → AttendanceEngine.process_tracks()
    → For each active track:
        → CrossingEngine.process_track_update()
        → If crossing detected:
            → Create CrossingEvent
            → AttendanceStore.store_event()  (SQLite INSERT)
            → Trigger callbacks
```

### Configuration (from pipeline.yaml)
```yaml
attendance:
  store_events: true
  event_db_path: "data/attendance_events.db"
  daily_records_enabled: true
  daily_db_path: "data/attendance_daily.db"
  excel_export_enabled: true
  excel_export_path: "data/exports"
  default_debounce_seconds: 2.0

cameras:
  cam1:
    geometry:
      line_start: [0, 1080]
      line_end: [3840, 1080]
      direction_semantics: "side_a_to_b_in"
    crossing_policy:
      min_crossing_distance: 50.0
      temporal_debounce_seconds: 2.0
      side_confirmation_frames: 3
      max_trajectory_gap_frames: 5
```

### Daily Summary
```python
get_daily_summary(date: "YYYY-MM-DD") → {
    "date": "2026-10-03",
    "records": [
        {"person_id": "NV001", "person_name": "John", "direction": "in", "count": 1, "first_event": ..., "last_event": ...},
        {"person_id": "NV001", "person_name": "John", "direction": "out", "count": 1, ...}
    ]
}
```

### Export
```python
export_to_json(output_path, camera_id=None, person_id=None, start_time=None, end_time=None)
```

---

## Database Ownership Analysis

### Current Databases (from pipeline.yaml integration section)
| Database | Path | Owner | Purpose |
|----------|------|-------|---------|
| Attendance Events | `data/attendance_events.db` | **PipelineEngine** | Line crossing events |
| Daily Records | `data/attendance_daily.db` | **PipelineEngine** | Aggregated daily counts |
| Exit Sessions | `data/exit_sessions.db` | **Legacy Backend** | Session tracking |
| Notification Queue | `data/notification_queue.db` | **Legacy Backend** | Push notifications |
| Parent Registry | `data/parent_registry.db` | **Legacy Backend** | Parent/student mapping |
| Embeddings | `data/embeddings.npy` | **Shared** | Face recognition DB |
| Embeddings Meta | `data/embeddings.npy.metadata.json` | **Shared** | Face metadata |

### Ownership Conflict: **CRITICAL**

**PipelineEngine** (new) creates/writes:
- `attendance_events.db` - New SQLite DB for line crossing events
- `attendance_daily.db` - New SQLite DB for daily summaries

**Legacy Backend** (old) owns:
- `attendance.db` - Authoritative attendance records
- `exit_sessions.db` - Session management
- `notification_queue.db` - Notifications
- `parent_registry.db` - Enrollment data

### Problem
1. **Two attendance databases**: PipelineEngine writes to `attendance_events.db`, Legacy Backend owns `attendance.db`
2. **No synchronization**: Events in PipelineEngine not propagated to Legacy Backend
3. **Duplicate schemas**: Both track IN/OUT events with person_id, timestamp
4. **UI consumes from Legacy Backend**: Existing UI reads from old backend API
5. **PipelineEngine backend** has empty attendance endpoints (return `[]`)

### Evidence from Backend API (`backend/app.py`)
```python
@app.get("/api/v1/attendance/events")
async def get_attendance_events(...):
    # This would need access to attendance engine
    # For now return empty list
    return []

@app.get("/api/v1/attendance/daily/{date}")
async def get_daily_attendance(date: str):
    return {"date": date, "records": []}
```

### Required Integration
PipelineEngine must **NOT** be authoritative attendance store. Options:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A: PipelineEngine → Legacy Backend API | Push events via REST | Clear ownership | Network dependency, latency |
| B: PipelineEngine → Legacy Backend DB | Direct SQLite write | Fast, simple | Coupling, schema sync |
| C: Legacy Backend reads PipelineEngine DB | Legacy polls new DB | Decoupled | Polling latency, two DBs |
| D: Shared DB (recommended) | Both use same `attendance.db` | Single source | Migration needed |

### Recommended: Option D (Shared DB)
1. Migrate PipelineEngine to use `data/attendance.db` (legacy schema)
2. Remove `attendance_events.db` and `attendance_daily.db`
3. PipelineEngine writes events, Legacy Backend reads same table
4. Add `source` column to distinguish: `pipeline_engine` vs `legacy`

---

## Enrollment Database (NPY)

### Structure
```python
# embeddings.npy: np.ndarray (N, 512) float32 - L2 normalized
# embeddings.npy.metadata.json: List[dict]
[
    {"id": "NV001", "name": "John Doe", "department": "Engineering", "camera": "cam1", "created_at": "2026-01-15"},
    ...
]
```

### Loading (ArcFaceRecognizer)
```python
def load_enrollment_database(self, embeddings_path, metadata_path):
    embeddings = np.load(embeddings_path)  # (N, 512)
    with open(metadata_path) as f:
        metadata = json.load(f)
    self._enrollment_embeddings = torch.from_numpy(embeddings).to(device)
    self._enrollment_metadata = {m["id"]: m for m in metadata}
```

### Usage
- ArcFace creates tensor on GPU at load time (~N × 512 × 4 bytes)
- For 1000 faces: ~2 MB GPU memory
- Identify: `embedding @ enrollment_embeddings.T` → cosine similarity

### Ownership
- **Created by**: UI enrollment page (ArcFace / NPY page)
- **Read by**: PipelineEngine (ArcFaceRecognizer per camera)
- **Updated by**: UI (add/delete), Legacy Backend (sync)
- **Conflict risk**: Multiple ArcFaceRecognizer instances (per camera) load same NPY → duplicate GPU memory

---

## Video Recording vs AI Event Storage

### Current State
| Storage | Location | Owner | Content |
|---------|----------|-------|---------|
| Video recordings | `recordings/` | MediaMTX | fMP4 segments, 1h each, 24h retention |
| AI Events | `data/attendance_events.db` | PipelineEngine | CrossingEvent records |
| Daily Summary | `data/attendance_daily.db` | PipelineEngine | Aggregated counts |

### MediaMTX Recording Config
```yaml
pathDefaults:
  record: no  # Disabled by default
  recordPath: ./recordings/%path/%Y-%m-%d_%H-%M-%S-%f
  recordFormat: fmp4
  recordPartDuration: 1s
  recordSegmentDuration: 1h
  recordDeleteAfter: 24h
```

### Separation Analysis
- **Video**: Continuous, high-volume, MediaMTX-managed
- **Events**: Sparse, low-volume, PipelineEngine-managed
- **No linkage**: No foreign key from event → video segment
- **Replay**: UI would need to correlate timestamp → video file

### Architecture A Requirement
> "Whether video recording can be separated from AI event storage"

**Answer**: Already separated. MediaMTX handles video, PipelineEngine handles events. 
**Gap**: No correlation ID to link event → video segment for replay.

---

## Data Retention & Cleanup

### Current
| Data | Retention | Cleanup |
|------|-----------|---------|
| Video (MediaMTX) | 24h | Automatic (`recordDeleteAfter: 24h`) |
| Attendance Events | Forever | Manual (no cleanup) |
| Daily Summary | Forever | Manual |
| Embeddings NPY | Forever | Manual |
| Exit Sessions | Forever | Legacy Backend |
| Notifications | Forever | Legacy Backend |

### Missing
- No automatic attendance event cleanup
- No GDPR/compliance deletion
- No archive/compress old events

---

## Attendance Event Schema Comparison

### PipelineEngine (New)
```sql
attendance_events:
  event_id, camera_id, track_id, direction, event_type,
  crossing_point_x, crossing_point_y, timestamp, frame_index,
  previous_position_x, previous_position_y,
  current_position_x, current_position_y,
  person_id, person_name, identity_confidence, created_at
```

### Legacy Backend (Existing - inferred)
```sql
attendance (likely):
  id, person_id, person_name, camera_id, direction, 
  timestamp, confidence, track_id, verified, created_at
```

### Mapping Needed
| PipelineEngine | Legacy Backend |
|----------------|----------------|
| event_id | id (or external_id) |
| camera_id | camera_id |
| track_id | track_id |
| direction | direction |
| timestamp | timestamp |
| person_id | person_id |
| person_name | person_name |
| identity_confidence | confidence |
| crossing_point | (not stored) |
| frame_index | (not stored) |

---

## Backend Integration Points

### PipelineEngine Backend (New) - `pipeline_engine/backend/app.py`
- **Endpoints**: `/api/v1/attendance/events`, `/api/v1/attendance/daily`, `/api/v1/attendance/export`
- **Status**: Empty implementations, return `[]` or placeholder
- **WebSocket**: No attendance event broadcasting

### Legacy Backend (Old) - Not in this repo
- **Assumed endpoints**: `/api/v1/attendance`, `/api/v1/attendance/events`, `/api/v1/attendance/daily`
- **Assumed WebSocket**: Real-time attendance events
- **Database**: `data/attendance.db` (authoritative)

### Required: Single Authoritative Backend
Per constraints: "The existing backend must remain the only authoritative attendance data owner."

**Action Required**:
1. PipelineEngine backend attendance endpoints → proxy to Legacy Backend
2. OR PipelineEngine writes directly to Legacy Backend DB
3. OR PipelineEngine pushes events to Legacy Backend via API
4. Remove PipelineEngine's local SQLite attendance DBs

---

## Callback System (Unused)

### AttendanceEngine Callbacks
```python
def register_event_callback(self, callback: callable):
    self._event_callbacks.append(callback)

# In process_tracks():
for callback in self._event_callbacks:
    callback(event)
```

### PipelineEngine Registration
```python
# In engine.py lifespan():
def health_callback(health):
    asyncio.create_task(manager.broadcast({"type": "health", "data": health}))

engine.register_health_callback(health_callback)
# NO attendance event callback registered!
```

### Gap
- Attendance events generated but **not broadcast via WebSocket**
- UI cannot receive real-time attendance updates
- Backend `/api/v1/attendance/events` returns empty

---

## Summary: Database Ownership Verdict

| Database | Current Owner | Required Owner | Action |
|----------|---------------|----------------|--------|
| `attendance.db` | Legacy Backend | Legacy Backend | **KEEP** (authoritative) |
| `attendance_events.db` | PipelineEngine | **REMOVE** | Migrate events to legacy DB |
| `attendance_daily.db` | PipelineEngine | **REMOVE** | Compute on-demand from legacy DB |
| `exit_sessions.db` | Legacy Backend | Legacy Backend | **KEEP** |
| `notification_queue.db` | Legacy Backend | Legacy Backend | **KEEP** |
| `parent_registry.db` | Legacy Backend | Legacy Backend | **KEEP** |
| `embeddings.npy` | Shared | Shared | **KEEP** (single source) |
| `embeddings.metadata.json` | Shared | Shared | **KEEP** |

---

## Migration Plan for Architecture A

1. **Remove** PipelineEngine's `AttendanceStore` (SQLite)
2. **Add** `LegacyBackendClient` in PipelineEngine to push events
3. **Implement** event push: `POST /api/v1/attendance/events` to Legacy Backend
4. **Update** PipelineEngine backend attendance endpoints → proxy to Legacy Backend
5. **Add** WebSocket broadcast for attendance events in Legacy Backend
6. **Verify** UI consumes from Legacy Backend only

---

## Runtime Verification

**ALL ATTENDANCE COMPONENTS: BLOCKED**

Requires:
- Running pipeline with tracked persons crossing lines
- SQLite write permissions in `data/`
- Legacy Backend API running for integration test

Cannot verify:
- Crossing detection accuracy
- Debounce effectiveness
- Daily summary correctness
- Export functionality
- Legacy Backend integration
- WebSocket event broadcasting