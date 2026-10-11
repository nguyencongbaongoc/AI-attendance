# Attendance Event Contract

## Current Contracts

### 1. PipelineEngine CrossingEvent (Producer)
**Source**: `pipeline_engine/attendance/attendance_engine.py` lines 76-108

```python
@dataclass
class CrossingEvent:
    event_id: str                          # e.g., "CE-1-1234-1234567890123"
    camera_id: str                         # "cam1" or "cam2"
    track_id: int                          # Local track ID from tracker
    direction: CrossingDirection           # IN / OUT
    event_type: CrossingEventType = LINE_CROSSING
    crossing_point: Tuple[float, float]    # (x, y) intersection point
    timestamp: float = 0.0                 # Wall-clock (time.time())
    frame_index: int = 0                   # Frame counter
    previous_position: Tuple[float, float] # Track center before crossing
    current_position: Tuple[float, float]  # Track center after crossing
    person_id: Optional[str] = None        # From tracker identity
    person_name: Optional[str] = None      # From enrollment
    identity_confidence: float = 0.0       # Tracker identity confidence
```

**Key Characteristics**:
- Generated per line crossing with debouncing (2s default)
- Track ID is local to camera (not global)
- Person ID from tracker (ArcFace identification)
- No link to Phase 22/23/24 provenance chain
- Stored in PipelineEngine's `attendance_events.db`

### 2. Legacy Backend AttendanceRecord (Authoritative Store)
**Source**: `app/attendance/contract.py` lines 31-151

```python
@dataclass(frozen=True)
class AttendanceRecord:
    # Record identification
    attendance_record_id: str              # Deterministic: ATT-<hash(source_resolution_id)>
    
    # Identity
    identity_certainty: IdentityCertainty  # KNOWN/UNKNOWN/AMBIGUOUS/INSUFFICIENT
    identity_candidate: Optional[str]      # Person ID
    identity_confidence: float = 0.0
    identity_evidence_ref: Optional[str]   # GlobalObservation ID
    
    # Event
    direction: AttendanceDirection         # IN/OUT
    event_timestamp: float                 # Upstream event timestamp
    event_frame_index: int = -1
    
    # Camera/Track
    camera_id: str
    local_track_id: str
    global_observation_id: Optional[str]   # Cross-camera identity
    
    # Provenance Chain (CRITICAL)
    source_raw_event_id: str               # Phase 23 RawInOutEvent ID
    source_resolution_id: str              # Phase 24 ResolvedTransition ID (UNIQUE KEY)
    source_crossing_event_id: Optional[str] # Phase 22 CrossingEvent ID
    
    # Geometry Provenance
    geometry_version: int = 0
    geometry_config_hash: str = ""
    
    # Resolver Provenance
    resolver_version: str = "1.0"
    resolver_config_hash: str = ""
    
    # Derived State
    previous_state: str = "unknown"        # INSIDE/OUTSIDE/UNKNOWN
    new_state: str = "unknown"             # INSIDE/OUTSIDE/UNKNOWN
    
    # Versioning
    attendance_schema_version: str = "1.0"
    created_at: str                        # ISO8601
    persisted_at: str                      # ISO8601
```

**Key Characteristics**:
- Immutable (`frozen=True`)
- Deterministic ID from `source_resolution_id`
- Full provenance chain: AttendanceRecord → ResolvedTransition → RawInOutEvent → CrossingEvent
- Unique constraint on `source_resolution_id`
- State machine: previous_state → new_state (INSIDE/OUTSIDE/UNKNOWN)

### 3. Legacy Backend ResolvedTransition (Phase 24)
**Source**: `app/in_out/resolver_contract.py` (referenced by repository)

```python
@dataclass
class ResolvedTransition:
    resolution_id: str                     # Unique resolution ID
    source_raw_event_id: str               # Phase 23 RawInOutEvent
    camera_id: str
    local_track_id: str
    global_observation_id: Optional[str]
    direction: str                         # "in" / "out"
    is_transition: bool                    # True only for actual IN/OUT
    transition_type: TransitionType        # ENTRY/EXIT/SUPPRESSED/REJECTED
    resolution_status: ResolutionStatus    # CONFIRMED/SUPPRESSED/REJECTED
    source_timestamp: float                # Event timestamp
    source_frame_index: int
    previous_state: DerivedState
    new_state: DerivedState
    geometry_version: int
    geometry_config_hash: str
    resolver_version: str
    resolver_config_hash: str
```

## Contract Gap Analysis

| Aspect | PipelineEngine CrossingEvent | Legacy AttendanceRecord | Gap |
|--------|------------------------------|-------------------------|-----|
| **Event ID** | `CE-{track}-{frame}-{ts}` | `ATT-<hash(resolution_id)>` | Different schemes |
| **Track ID** | Local camera track (int) | `local_track_id` (string) | Type mismatch |
| **Identity** | `person_id`, `person_name`, `confidence` | `identity_candidate`, `identity_confidence`, `identity_certainty` | Partial match |
| **Provenance** | None | Full chain (Phase 22-25) | **Major gap** |
| **Geometry** | Crossing point only | Version + config hash | **Missing** |
| **Resolver State** | None | `previous_state`/`new_state` | **Missing** |
| **Schema Version** | None | `attendance_schema_version` | **Missing** |
| **Uniqueness** | Per crossing | Per `source_resolution_id` | Different |

## Required Contract for Architecture A

### AI Worker → Legacy Backend Event Format

**Proposed**: `POST /api/v1/attendance/events` (NEW ENDPOINT NEEDED)

```json
{
  "source": "ai_worker",
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

### Field Mapping: PipelineEngine → Legacy Backend

| PipelineEngine | Legacy Backend | Transformation |
|----------------|----------------|----------------|
| `event_id` | `source_crossing_event_id` | Pass through |
| `camera_id` | `camera_id` | Pass through |
| `track_id` (int) | `local_track_id` (str) | `str(track_id)` |
| `direction` | `direction` | Pass through (IN/OUT) |
| `timestamp` | `event_timestamp` | Pass through |
| `frame_index` | `event_frame_index` | Pass through |
| `person_id` | `identity_candidate` | Pass through |
| `person_name` | (lookup) | Legacy Backend resolves |
| `identity_confidence` | `identity_confidence` | Pass through |
| `crossing_point` | (geometry provenance) | Store in `geometry_version` + `geometry_config_hash` |
| `stream_epoch` | (new field) | Add to metadata |

### Required Legacy Backend Fields (Missing from PipelineEngine)

These MUST be provided by AI worker or derived by Legacy Backend:

1. **`source_resolution_id`** - Legacy Backend generates from `source_crossing_event_id` + stream_epoch
2. **`source_raw_event_id`** - Phase 23 event ID (Legacy Backend creates)
3. **`global_observation_id`** - From tracker if cross-camera
4. **`geometry_version` / `geometry_config_hash`** - From geometry config
5. **`resolver_version` / `resolver_config_hash`** - From resolver
6. **`previous_state` / `new_state`** - Derived from direction (OUTSIDE→INSIDE for IN)
7. **`attendance_schema_version`** - "1.0"

## Idempotency Requirements

### Legacy Backend Deduplication
- Unique constraint on `source_resolution_id`
- PipelineEngine must generate deterministic `source_resolution_id`
- Suggested: `RES-{camera_id}-{stream_epoch}-{track_id}-{frame_index}`

### Retry Behavior
- AI worker retries with exponential backoff
- Legacy Backend: insert ignores duplicates (idempotent)
- AI worker tracks sent events locally for reconciliation

## Geometry Contract

### Line Geometry (Shared)
```json
{
  "camera_id": "cam1",
  "version": 1,
  "config_hash": "sha256:abc123...",
  "line_start": [0, 1080],
  "line_end": [3840, 1080],
  "direction_semantics": "side_a_to_b_in"
}
```
- Stored in both systems
- Version increments on change
- Hash for change detection

## Identity Contract

### Certainty Levels
| Legacy | PipelineEngine | Meaning |
|--------|----------------|---------|
| `KNOWN` | confidence ≥ 0.6 | Enrolled person recognized |
| `UNKNOWN` | confidence < 0.6 or no match | Not enrolled / low confidence |
| `AMBIGUOUS` | Multiple matches | Multiple candidates |
| `INSUFFICIENT` | No face detected | Cannot determine |

## Evidence References

| Contract | File | Lines |
|----------|------|-------|
| CrossingEvent | `pipeline_engine/attendance/attendance_engine.py` | 76-108 |
| AttendanceRecord | `app/attendance/contract.py` | 31-151 |
| ResolvedTransition | `app/in_out/resolver_contract.py` | (referenced) |
| IdentityCertainty | `app/attendance/contract.py` | 23-28 |
| AttendanceDirection | `app/attendance/contract.py` | 17-20 |

## Verification Status

| Contract | Source Verified | Runtime Verified |
|----------|-----------------|------------------|
| CrossingEvent | ✅ | ❌ BLOCKED |
| AttendanceRecord | ✅ | ❌ BLOCKED |
| ResolvedTransition | ✅ (referenced) | ❌ BLOCKED |
| Proposed AI Contract | ❌ DESIGN ONLY | ❌ N/A |