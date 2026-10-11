# Phase 1 — AI Worker Implementation & Legacy Backend Integration

**Date:** 2026-10-04  
**Phase:** 1  
**Previous Phase:** 0.2.6 — COMPLETE (Final Verdict: COMPLETE)  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main  
**Architecture:** Architecture A — APPROVED  

---

## 1. Phase 1 Mission

Implement the actual AI Worker runtime and integrate it with the existing Legacy Backend without replacing the existing attendance architecture.

**Objective:** Establish a working path:
```
Camera RTSP
→ Independent AI Video Reader
→ Frame Decode
→ SCRFD Face Detection
→ Face Alignment
→ ArcFace Embedding
→ Identity Matching
→ Tracking
→ Crossing / In-Out Event Generation
→ Health and Control Integration
→ Legacy Backend Event Ingestion
→ Existing Phase 22–25 Attendance Resolver
→ Authoritative AttendanceRecord
```

The original video path remains independent:
```
Camera RTSP
→ MediaMTX / Existing Video Relay
→ Original Unannotated Video
→ UI Video Player
```

AI metadata must be synchronized with video playback and rendered as a UI overlay. No annotated-video encoding in this phase.

---

## 2. Architecture Invariants (Mandatory)

### 2.1 Architecture A — Video and AI Independence
- Preserve original video path; avoid unnecessary transcoding
- UI video playback must not depend on AI inference
- AI failure must not terminate original video stream

### 2.2 Legacy Backend Authority
- Legacy Backend remains the ONLY attendance authority
- Phase 22–25 flow: `CrossingEvent → RawInOutEvent → ResolvedTransition → AttendanceRecord`
- AI Worker submits events through approved API only
- AI Worker MUST NOT:
  - Insert AttendanceRecord directly
  - Update attendance records directly
  - Implement competing attendance resolver
  - Bypass Phase 22–25
  - Create second authoritative attendance database

### 2.3 Database Authority
- `app/data/attendance.db`: Authoritative production attendance database (108 records verified)
- `data/attendance.db`: Secondary/benchmark database (18 records verified)
- `data/attendance_events.db`: Separate event storage, NOT AttendanceRecord authority (0 records verified)

### 2.4 Camera Isolation
Each camera must have:
- Independent reader, reconnect lifecycle, tracking state
- Independent timestamps and stream generation
- Independent health reporting
- Explicit camera identity
- NO mixing of tracking IDs between cameras without explicit cross-camera mechanism

### 2.5 Model Contracts
Preserve verified contracts:
- SCRFD detection + five-point landmarks
- ArcFace input: 112×112, output: 512D float32, L2 normalized
- Existing alignment and preprocessing conventions
- Existing enrollment embedding format
- NO silent changes to normalization, color order, dimensions, thresholds

---

## 3. Phase 0.2.6 Baseline Verification

### 3.1 Health Integration — COMPLETE
- Backend: `app/api/ai_worker.py` — 871 lines, full health state management
- Client: `pipeline_engine/integration/health_client.py` — 349 lines, 13/13 tests PASS
- Endpoints: `POST /health/ai-worker`, `GET /health/ai-worker/{worker_id}`
- Sequence/generation validation, stale detection, control command return

### 3.2 Control Integration — COMPLETE
- Backend: `app/api/ai_worker.py` — control endpoints implemented
- Client: `pipeline_engine/integration/control_client.py` — 479 lines, 17/17 tests PASS
- Canonical actions: `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS`
- Polling: `GET /ai/control/pending` → returns `requests` array
- Response: `POST /ai/control/{action}/response` with path/body validation

### 3.3 Auth & Authorization — COMPLETE
- Three distinct keys: `AI_WORKER_API_KEY`, `AI_CONTROL_API_KEY`, `ADMIN_API_KEY`
- All use `secrets.compare_digest` (constant-time)
- Fail-closed (503 if env not configured)
- Role separation enforced

### 3.4 Pipeline Engine — EXISTING
- `pipeline_engine/core/engine.py` — 591 lines, EngineState machine
- `pipeline_engine/ingestion/camera_manager.py` — 971 lines, CameraManager with full pipeline
- Models: SCRFD, ArcFace, YOLO in `pipeline_engine/inference/`
- Tracking: `pipeline_engine/tracking/tracker.py` — 685 lines
- Attendance: `pipeline_engine/attendance/attendance_engine.py` — 644 lines

### 3.5 Configuration — EXISTING
- `pipeline_engine/config/pipeline.yaml` — Complete dual-camera config
- `app/config/settings.py` — 445 lines, comprehensive settings

---

## 4. Phase 1 Gates Overview

| Gate | Objective | Status |
|------|-----------|--------|
| **A** | AI Worker Runtime Foundation | PENDING |
| **B** | Camera Ingestion & Frame Pipeline | PENDING |
| **C** | Model Inference Integration | PENDING |
| **D** | Tracking & Crossing Events | PENDING |
| **E** | Legacy Backend Event Integration | PENDING |
| **F** | Video & AI Metadata Synchronization | PENDING |
| **G** | Dual-Camera Qualification | PENDING |
| **H** | Failure & Recovery | PENDING |
| **I** | Regression, Security & Data Integrity | PENDING |

---

## 5. Pre-Flight Checklist (Completed)

- ✅ Inspected current repository root
- ✅ Recorded Git branch (main) and HEAD (5269777)
- ✅ Inspected `git status --short` (clean working tree)
- ✅ Inspected all Phase 0.2.6 changes (4 files modified)
- ✅ Read all 18 Phase 0.2.6 artifacts
- ✅ Read Phase 0.2.6 final verdict
- ✅ Inspected actual implementations:
  - `app/api/ai_worker.py` ✅
  - `app/attendance/storage.py` ✅
  - `app/config/settings.py` ✅
  - `app/api/enrollment.py` ✅
  - `app/main.py` ✅
  - `pipeline_engine/integration/health_client.py` ✅
  - `pipeline_engine/integration/control_client.py` ✅
- ✅ Inspected existing model loading and inference implementations
- ✅ Inspected camera ingestion, tracking, event generation
- ✅ Inspected existing Phase 22–25 attendance pipeline
- ✅ Verified database states (app/data/attendance.db: 108 records, data/attendance.db: 18 records, data/attendance_events.db: 0 records)
- ✅ Verified model files exist (SCRFD, ArcFace, YOLO)

---

## 6. Phase 1 Execution Order

1. **Preflight & Baseline** — COMPLETE (this artifact)
2. **Architecture/Source Inventory** — Next artifact
3. **Gate A** — Worker Runtime Foundation
4. **Gate B** — Camera Ingestion & Frame Pipeline
5. **Gate C** — Model Inference Integration
6. **Gate D** — Tracking & Crossing Events
7. **Gate E** — Legacy Backend Event Integration
8. **Gate F** — Timestamp Synchronization
9. **Gate G** — Dual-Camera Qualification
10. **Gate H** — Failure & Recovery
11. **Gate I** — Regression & Data Integrity
12. **Audit Artifacts & Final Verdict**

---

## 7. Key Implementation Requirements

### Worker Lifecycle States
- STARTING → INITIALIZING → RUNNING → DEGRADED → STOPPING → STOPPED/FAILED
- Must NOT report RUNNING before all components initialized
- Distinguish: process alive, worker initialized, camera connected, model initialized, inference operational, event delivery operational

### Frame Contract
Each frame must preserve:
- camera_id, stream_epoch, frame_sequence, PTS, time_base
- capture_timestamp, frame dimensions, decode timestamp
- NO substitution of processing time for capture time

### Event Schema
Must use Legacy Backend contract from `app/api/ai_worker.py:CrossingEventRequest`:
- event_id, camera_id, track_id, direction, event_type
- crossing_point, timestamp, frame_index, positions
- person_id, person_name, identity_confidence
- stream_epoch, pts, time_base, capture_timestamp, processing_timestamp
- model_version, enrollment_version, provenance, schema_version

### Synchronization Contract
Must define mapping between:
- Camera PTS/time_base
- Stream epoch
- Capture timestamp
- Relay timestamp (if available)
- Browser playback timeline
- AI inference timestamp
- Metadata delivery timestamp

---

## 8. Success Criteria for Phase 1 COMPLETE

- All 9 Gates PASS with reproducible runtime evidence
- Dual-camera sustained qualification (30 min concurrent, 10 min each individual)
- Legacy Backend attendance flow verified end-to-end
- Timestamp correlation reliable (not just wall-clock)
- Production database integrity maintained
- No attendance data corrupted by tests

---

## 9. Authorization

**Phase 1 is explicitly APPROVED by user.**

Do not start Phase 2 automatically even if Phase 1 COMPLETE. Wait for explicit user approval.

---

*Created as part of Phase 1 audit trail.*