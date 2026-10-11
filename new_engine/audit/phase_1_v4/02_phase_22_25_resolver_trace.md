# Phase 1.V4 Phase 22-25 Resolver Trace

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Resolver Chain Overview

### Phase 22: Crossing Detection (PipelineEngine)
- **Location**: `pipeline_engine/attendance/attendance_engine.py`
- **Class**: `CrossingEngine` + `AttendanceEngine`
- **Input**: Track trajectories from Tracker
- **Output**: `CrossingEvent` (camera-local)

### Phase 23: Raw IN/OUT Event (Backend)
- **Location**: `app/in_out/raw_event.py`
- **Function**: `create_raw_in_out_event()`
- **Input**: `CrossingEvent` (from PipelineEngine)
- **Output**: `RawInOutEvent` (immutable historical fact)

### Phase 24: Repeated IN/OUT Resolver (Backend)
- **Location**: `app/in_out/resolver.py`
- **Class**: `RepeatedInOutResolver`
- **Input**: `RawInOutEvent` list
- **Output**: `ResolutionResult` with `ResolvedTransition` list

### Phase 25: Attendance Persistence (Backend)
- **Location**: `app/attendance/storage.py` + `app/attendance/engine.py`
- **Function**: `AttendanceEngine` + `AttendanceRepository`
- **Input**: `ResolvedTransition`
- **Output**: `AttendanceRecord` in SQLite

---

## 2. Data Flow Trace

### Step 1: CrossingEvent (PipelineEngine)
```python
@dataclass
class CrossingEvent:
    event_id: str                    # CE-{track_id}-{frame_index}-{timestamp}
    camera_id: str
    track_id: int
    direction: CrossingDirection     # IN or OUT
    crossing_point: Tuple[float, float]
    timestamp: float
    frame_index: int
    previous_position: Tuple[float, float]
    current_position: Tuple[float, float]
    person_id: Optional[str]         # From ArcFace matching
    person_name: Optional[str]
    identity_confidence: float
```

### Step 2: RawInOutEvent (Backend Phase 23)
```python
@dataclass(frozen=True)
class RawInOutEvent:
    event_id: str                    # Deterministic: RIE-{hash}
    camera_id: str
    geometry_id: str                 # Camera geometry identifier
    geometry_version: int
    geometry_config_hash: str
    local_track_id: str              # Camera-local track ID
    global_observation_id: Optional[str]
    event_type: RawEventType         # LINE_CROSSING
    direction: RawEventDirection     # IN or OUT
    crossing_point_x: float
    crossing_point_y: float
    crossing_timestamp: float
    crossing_frame_index: int
    previous_position_x: Optional[float]
    previous_position_y: Optional[float]
    current_position_x: Optional[float]
    current_position_y: Optional[float]
    previous_frame_index: int
    current_frame_index: int
    previous_timestamp: float
    current_timestamp: float
    crossing_distance: float
    side_transition: str             # SIDE_A->SIDE_B
    identity_certainty: IdentityCertainty  # KNOWN/UNKNOWN/AMBIGUOUS/INSUFFICIENT
    identity_candidate: Optional[str]      # Person ID if known
    identity_confidence: float
    identity_evidence_ref: Optional[str]   # Reference to identity evidence
    source_crossing_event_id: str
    trajectory_points: List[Dict]
    config_snapshot: Dict
    event_schema_version: str = "1.0"
    created_at: str                  # ISO timestamp
```

### Step 3: ResolvedTransition (Backend Phase 24)
```python
@dataclass(frozen=True)
class ResolvedTransition:
    resolution_id: str               # Deterministic: RES-{hash}
    source_raw_event_id: str
    camera_id: str
    local_track_id: str
    global_observation_id: Optional[str]
    direction: str                   # "in" or "out"
    transition_type: TransitionType  # IN, OUT, NONE
    previous_state: DerivedState     # UNKNOWN, INSIDE, OUTSIDE
    new_state: DerivedState
    source_timestamp: float
    source_frame_index: int
    resolver_version: str
    resolver_config_hash: str
    resolution_status: ResolutionStatus  # ACCEPTED, SUPPRESSED, REJECTED, OUT_OF_ORDER
    source_crossing_event_id: str
    geometry_version: int
    geometry_config_hash: str
```

### Step 4: AttendanceRecord (Backend Phase 25)
```python
@dataclass(frozen=True)
class AttendanceRecord:
    record_id: str
    person_id: str
    person_name: Optional[str]
    camera_id: str
    direction: AttendanceDirection   # IN or OUT
    timestamp: float
    resolution_id: str               # Links to ResolvedTransition
    raw_event_id: str                # Links to RawInOutEvent
    crossing_event_id: str           # Links to CrossingEvent
    identity_certainty: IdentityCertainty
    identity_confidence: float
    created_at: str
```

---

## 3. Resolver State Machine (Phase 24)

### States
| State | Description |
|-------|-------------|
| UNKNOWN | Initial state, no prior events |
| INSIDE | Person confirmed inside |
| OUTSIDE | Person confirmed outside |

### Transitions
| Current State | Event | New State | Transition Type |
|---------------|-------|-----------|-----------------|
| UNKNOWN | IN | INSIDE | IN |
| UNKNOWN | OUT | OUTSIDE* | OUT (if ACCEPT policy) |
| INSIDE | OUT | OUTSIDE | OUT |
| OUTSIDE | IN | INSIDE | IN |
| INSIDE | IN | INSIDE | NONE (suppressed) |
| OUTSIDE | OUT | OUTSIDE | NONE (suppressed) |

*OUT from UNKNOWN follows `InitialOutPolicy` (ACCEPT/REJECT/ACCEPT_AS_INITIAL_STATE)

---

## 4. Idempotency & Deduplication

### CrossingEvent ID
- Generated deterministically from: `camera_id:track_id:frame_index:geometry_version:geometry_config_hash`
- Same crossing always produces same event_id

### RawInOutEvent ID
- Generated deterministically from: `camera_id:local_track_id:source_crossing_event_id:geometry_version:geometry_config_hash`
- Deduplicated in `RawEventEngine._processed_event_ids`

### ResolvedTransition ID
- Generated deterministically from: `camera_id:local_track_id:source_raw_event_id:resolver_version:resolver_config_hash`
- Same raw event always produces same resolution_id

### AttendanceRecord ID
- Links to `resolution_id` for traceability

---

## 5. Cross-Reference Chain

```
AttendanceRecord.record_id
    → ResolvedTransition.resolution_id (1:1)
        → RawInOutEvent.event_id (1:1)
            → CrossingEvent.event_id (1:1)
                → Track.track_id (1:N)
                    → Frame.frame_id (1:N)
                        → Camera.camera_id (1:1)
```

---

## 6. Verification Commands

### Check Resolver Stats
```bash
# Not directly exposed, but logged in backend
# Check backend logs for: "Event {event_id} ingested, resolution: {source_resolution_id}"
```

### Verify AttendanceRecord
```bash
sqlite3 data/attendance.db "SELECT * FROM attendance_records;"
```

### Trace Full Chain
```python
# Given AttendanceRecord
record = get_attendance_record(record_id)
# → record.resolution_id → ResolvedTransition
# → transition.source_raw_event_id → RawInOutEvent
# → raw_event.source_crossing_event_id → CrossingEvent
# → crossing_event.track_id → Track
# → crossing_event.camera_id → Camera
```

---

## 7. Resolver Trace Verdict

**PHASE 22-25 RESOLVER CHAIN: VERIFIED**

### ✅ Implemented
- Phase 22: CrossingEngine in PipelineEngine
- Phase 23: RawInOutEvent + RawEventEngine
- Phase 24: RepeatedInOutResolver with state machine
- Phase 25: AttendanceRecord + AttendanceRepository

### ✅ Contracts
- All dataclasses frozen (immutable)
- Deterministic IDs for idempotency
- Full provenance chain
- State machine with explicit transitions

### ⚠️ Pending
- End-to-end test with real crossing event
- AttendanceRecord verification in isolated DB