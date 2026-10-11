# Phase 0.2.1 — Phase 1 Boundary Contract

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED / ARCHITECTURAL DECISION REQUIRED

---

## 1. Executive Summary

This contract defines the formal responsibility boundaries between **Legacy Backend** (authoritative attendance system) and **PipelineEngine** (AI worker) for Phase 1 implementation. It identifies all shared contracts requiring formal design before Phase 1 can proceed safely.

---

## 2. Legacy Backend Responsibilities (AUTHORITATIVE)

### 2.1 Attendance Database Ownership
- **Single authoritative `attendance.db`** at `app/data/attendance.db` (fixed absolute path)
- Phase 25 `AttendanceRecord` persistence with full provenance chain
- Idempotent insert by `source_resolution_id`
- Query, export, chronological retrieval, filtering
- Schema versioning and migration

### 2.2 Phase 22–25 Event & Provenance Pipeline
- **Phase 22:** CrossingEvent generation (geometry, debounce, direction semantics)
- **Phase 23:** RawInOutEvent creation (track → raw event)
- **Phase 24:** RepeatedInOutResolver (transition resolution, state derivation)
- **Phase 25:** AttendanceRecord creation & persistence (provenance preservation)

### 2.3 Attendance State Transitions
- `DerivedState` machine: UNKNOWN → INSIDE/OUTSIDE → UNKNOWN
- Idempotent transition persistence
- Current state queries by track / global observation
- Duplicate event suppression

### 2.4 Enrollment Data Ownership
- `app/data/enrollment/embeddings.npy` + metadata.json (single source)
- Embedding management (add, update, delete, quality gate)
- ArcFace model version tracking
- NPY reload notification endpoint

### 2.5 API Authentication & Validation
- All external API access authenticated
- Request validation (Pydantic models)
- Rate limiting, CORS, security headers
- WebSocket/SSE for real-time updates

### 2.6 Idempotency & Duplicate Event Handling
- `source_resolution_id` unique constraint
- `attendance_record_id` deterministic generation
- Client-side idempotency keys supported
- Duplicate detection at API boundary

---

## 3. PipelineEngine Responsibilities (AI WORKER ONLY)

### 3.1 RTSP Ingestion
- MediaMTX RTSP client (`rtsp://localhost:8554/live/cam1`, `cam2`)
- PyAV NVDEC decode (or software fallback)
- Frame timestamp preservation (PTS, time_base)
- Reconnection with exponential backoff
- Readiness gate (bytes progress validation)

### 3.2 Frame Decode
- GPU decode surfaces (configurable pool)
- NV12 → BGR/RGB conversion (GPU)
- Frame metadata: `stream_epoch`, `frame_index`, `capture_timestamp`, `pts`

### 3.3 SCRFD Detection
- Face detection on decoded frames
- 5-point landmarks
- Detection confidence filtering
- BBox + landmarks output

### 3.4 ArcFace Embedding & Matching
- Aligned face crop (similarity transform)
- ArcFace embedding extraction (512-dim)
- Cosine similarity vs enrollment gallery
- Identity assignment with confidence threshold

### 3.5 YOLO Person Detection
- Person detection (class 0)
- BBox + confidence
- Max detections limit

### 3.6 Tracking with Camera-Isolated State
- IoU + face association
- Per-camera track state (NO cross-camera fusion)
- Track lifecycle: NEW → ACTIVE → LOST → REMOVED
- Track metadata: `track_id`, `camera_id`, `person_id`, `identity_confidence`

### 3.7 Crossing/Event Candidate Generation
- Line crossing geometry (configurable per camera)
- Temporal debounce, distance threshold, side confirmation
- Output: `CrossingEvent` with full provenance:
  - `event_id`, `camera_id`, `track_id`, `direction`
  - `crossing_point`, `timestamp`, `frame_index`
  - `previous_position`, `current_position`
  - `person_id`, `person_name`, `identity_confidence`

### 3.8 Event Delivery to Legacy Backend
- **HTTP POST** to `POST /api/v1/attendance/events` (to be implemented)
- Payload: `CrossingEvent` + enriched metadata
- Retry with exponential backoff + jitter
- Idempotency key: `event_id` (or `source_resolution_id` after resolver)
- Acknowledgment required before local cleanup

### 3.9 Health Reporting & Runtime Telemetry
- `/api/v1/health/ai-worker` heartbeat (to be implemented)
- Metrics: decode FPS, inference FPS, track counts, queue depths
- GPU memory, CUDA stream status
- Structured JSON logging

---

## 4. Shared Contracts Requiring Formal Design

### 4.1 Event Schema: `CrossingEvent` → Legacy Backend API

| Field | Type | Required | Creator | Validator | Persister |
|-------|------|----------|---------|-----------|-----------|
| `event_id` | string (UUID) | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `camera_id` | string | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `track_id` | integer | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `direction` | "in" \| "out" | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `crossing_point` | {x: float, y: float} | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `timestamp` | float (unix epoch) | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `frame_index` | integer | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `previous_position` | {x: float, y: float} | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `current_position` | {x: float, y: float} | YES | PipelineEngine | Legacy Backend | Legacy Backend |
| `person_id` | string? | NO | PipelineEngine | Legacy Backend | Legacy Backend |
| `person_name` | string? | NO | PipelineEngine | Legacy Backend | Legacy Backend |
| `identity_confidence` | float | NO | PipelineEngine | Legacy Backend | Legacy Backend |
| `stream_epoch` | integer | **OPEN** | PipelineEngine | Legacy Backend | Legacy Backend |
| `pts` | integer | **OPEN** | PipelineEngine | Legacy Backend | Legacy Backend |
| `time_base` | {num: int, den: int} | **OPEN** | PipelineEngine | Legacy Backend | Legacy Backend |
| `capture_timestamp` | float | **OPEN** | PipelineEngine | Legacy Backend | Legacy Backend |
| `processing_timestamp` | float | **OPEN** | PipelineEngine | Legacy Backend | Legacy Backend |

**OPEN FIELDS:** `stream_epoch`, `pts`, `time_base`, `capture_timestamp`, `processing_timestamp` — need formal definition for timestamp synchronization.

---

### 4.2 Camera Identity Contract

| Field | Type | Required | Creator | Validator | Persister |
|-------|------|----------|---------|-----------|-----------|
| `camera_id` | string | YES | Config (both) | Both | Legacy Backend |
| `camera_name` | string | NO | Config (both) | Both | Legacy Backend |
| `geometry` | LineGeometry | YES | Config (both) | Legacy Backend | Legacy Backend |
| `stream_url` | string | YES | Config (both) | PipelineEngine | — |

**Resolution:** Legacy Backend owns camera registry; PipelineEngine receives config at startup.

---

### 4.3 `stream_epoch` Contract — **OPEN**

**Purpose:** Monotonically increasing epoch per camera stream session. Resets on reconnection.

| Question | Status |
|----------|--------|
| Who assigns? | **OPEN** — PipelineEngine at stream start? Legacy Backend via config? |
| Scope? | Per-camera? Global? |
| Persistence? | In-memory only? Survive restart? |
| API exposure? | Included in every event? |

**Recommendation:** PipelineEngine assigns at stream connection; included in every `CrossingEvent`; Legacy Backend validates monotonic increase per camera.

---

### 4.4 Frame PTS Contract — **OPEN**

| Field | Type | Description |
|-------|------|-------------|
| `pts` | integer | Presentation timestamp from container (PyAV `frame.pts`) |
| `time_base` | {num, den} | Stream time base (e.g., {1, 90000} for 90kHz) |
| `capture_timestamp` | float | Wall-clock time at frame capture (best effort) |
| `processing_timestamp` | float | Wall-clock time at AI processing complete |

**Questions:**
- Are PTS values monotonic across reconnections? (Likely NO — reset on new stream)
- How to synchronize PTS across cameras? (Need `stream_epoch` + PTS)
- Who converts PTS → unix timestamp? (PipelineEngine at capture; Legacy Backend validates)

---

### 4.5 Event ID / Idempotency Key Contract

| Field | Format | Creator | Scope |
|-------|--------|---------|-------|
| `event_id` (CrossingEvent) | `CE-{track_id}-{frame_index}-{timestamp_ms}` | PipelineEngine | Per-camera, per-session |
| `source_resolution_id` (ResolvedTransition) | `RES-{uuid}` | Legacy Backend (Phase 24) | Global, persistent |
| `attendance_record_id` (AttendanceRecord) | `ATT-{sha256(source_resolution_id)}` | Legacy Backend (Phase 25) | Global, persistent |

**Idempotency:** Legacy Backend MUST deduplicate on `source_resolution_id`. PipelineEngine SHOULD include `event_id` for traceability.

---

### 4.6 Identity Reference Contract

| Field | Type | Description |
|-------|------|-------------|
| `person_id` | string | Enrollment ID (e.g., `STU-99999`) |
| `person_name` | string | Display name |
| `identity_confidence` | float | ArcFace cosine similarity (0-1) |
| `global_observation_id` | string? | Phase 18+ temporal identity link |

**Contract:** PipelineEngine provides `person_id` + `identity_confidence` from matching. Legacy Backend validates against enrollment gallery version.

---

### 4.7 Confidence & Provenance Contract

| Field | Type | Creator | Purpose |
|-------|------|---------|---------|
| `detection_confidence` | float | PipelineEngine (SCRFD) | Face detection quality |
| `identity_confidence` | float | PipelineEngine (ArcFace) | Matching confidence |
| `geometry_version` | integer | Legacy Backend (config) | Line geometry version |
| `geometry_config_hash` | string (sha256) | Legacy Backend (config) | Config integrity |
| `resolver_version` | string | Legacy Backend (Phase 24) | Resolver version |
| `resolver_config_hash` | string | Legacy Backend (Phase 24) | Resolver config integrity |

---

### 4.8 API Retry & Acknowledgement Behavior — **OPEN**

| Parameter | Value | Status |
|-----------|-------|--------|
| Initial retry delay | 1s? 5s? | **OPEN** |
| Max retries | 3? 5? | **OPEN** |
| Backoff multiplier | 2.0? | **OPEN** |
| Max retry delay | 60s? | **OPEN** |
| Jitter | 0.1? | **OPEN** |
| Acknowledgement required | YES | **DECIDED** |
| Timeout per request | 10s? | **OPEN** |
| Circuit breaker | After N failures? | **OPEN** |

---

### 4.9 Enrollment Version & Reload Semantics — **OPEN**

| Aspect | Status |
|--------|--------|
| Enrollment version identifier | **OPEN** — file mtime? hash? explicit version? |
| Reload trigger | **OPEN** — `POST /api/v1/enrollment/reload` + file watcher? |
| PipelineEngine notification | **OPEN** — push via WebSocket? poll? |
| Graceful transition | **OPEN** — dual-gallery during reload? |
| Rollback on failure | **OPEN** — automatic revert? |

---

## 5. Critical Invariants (NON-NEGOTIABLE)

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | **One authoritative attendance database** | Config: absolute path `app/data/attendance.db`; CWD-independent |
| 2 | **One attendance resolver** | Legacy Backend Phase 24 only; PipelineEngine has NO resolver |
| 3 | **No PipelineEngine writes to `AttendanceRecord`** | Code review: PipelineEngine imports only `AttendanceStore` (CrossingEvent) |
| 4 | **Camera tracking states remain isolated** | PipelineEngine: no cross-camera track fusion; Legacy Backend: per-camera state |
| 5 | **Video & AI metadata timestamps synchronizable** | `stream_epoch` + PTS + time_base in every event |
| 6 | **No silent frame dropping or resolution/FPS reduction** | PipelineEngine: configurable drop policy; metrics exposed |
| 7 | **No automatic CPU fallback to hide GPU overload** | PipelineEngine: fail fast on GPU OOM; alert, don't silently degrade |
| 8 | **No duplicate backend or attendance service** | Single Legacy Backend process; single PipelineEngine process |
| 9 | **All AI event delivery auditable and idempotent** | `source_resolution_id` unique constraint; delivery logs persisted |

---

## 6. Phase 1 Implementation Sequence (Dependency Order)

### Week 1: Legacy Backend API Endpoints
1. `POST /api/v1/attendance/events` — Event ingestion (idempotent)
2. `POST /api/v1/health/ai-worker` — AI Worker health
3. `POST /api/v1/ai/control/*` — AI Worker control (start/stop/reconfig)
4. `POST /api/v1/enrollment/reload` — NPY reload notification

### Week 2-3: PipelineEngine Refactor
1. Remove local `AttendanceStore` (or make read-only cache)
2. Implement `LegacyBackendClient` with retry/acknowledgement
3. Add `stream_epoch`, PTS, time_base to `CrossingEvent`
4. Implement event delivery with idempotency

### Week 3: Integration
1. End-to-end test: Camera → PipelineEngine → Legacy Backend → AttendanceRecord
2. Timestamp sync validation (PTS → unix time)
3. Duplicate event injection test (idempotency)

### Week 4: UI Integration
1. hls.js player for `live/cam1-ai`, `live/cam2-ai`
2. Canvas overlay (boxes, labels, crossing line)
3. WebSocket/SSE for real-time events

### Week 5: Validation
1. Long-duration soak test
2. Failure injection (network, GPU, DB)
3. Performance baseline

---

## 7. Open Fields Requiring Phase 1 Design Decisions

| Field | Component | Decision Needed |
|-------|-----------|-----------------|
| `stream_epoch` | Both | Assignment, scope, persistence |
| `pts` + `time_base` | PipelineEngine → Legacy Backend | Format, synchronization |
| `capture_timestamp` | PipelineEngine | Precision, source |
| `processing_timestamp` | PipelineEngine | Precision, purpose |
| Idempotency key format | Both | `event_id` vs `source_resolution_id` |
| Enrollment version | Legacy Backend | Identifier scheme |
| Enrollment reload API | Legacy Backend | Contract, notification |
| API retry policy | PipelineEngine | Parameters |
| Circuit breaker | PipelineEngine | Thresholds, behavior |

---

**This boundary contract must be reviewed and approved before Phase 1 implementation begins. All OPEN fields require explicit design decisions.**

---

**End of Phase 1 Boundary Contract**