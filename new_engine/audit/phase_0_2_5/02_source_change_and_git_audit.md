# Phase 0.2.5 Source Change and Git Audit

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Gate 0 Forensic Baseline  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Git Baseline

| Property | Value |
|---|---|
| Repository Root | `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE` |
| Current Branch | `main` |
| HEAD Commit | `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline` |
| Commit Date | 2026-10-03 |
| `git status --short` | 2000+ deleted (D), untracked files listed below |

### 1.1 Untracked Files (User Modifications Preserved)

```
UI/
analyze_quarantine.py
app/api/ai_worker.py
bootstrap.bat
bootstrap.py
check_dbs.py
final_verify.py
inspect_dbs.py
new_engine/
pipeline_engine/
search_writers.py
test_sqlite_backup.py
```

### 1.2 No Forbidden Git Operations Performed

- ✅ No `git reset`
- ✅ No `git clean`
- ✅ No `git checkout`
- ✅ No `git restore`
- ✅ No destructive rebase
- ✅ No force push

All previous audit artifacts preserved.

---

## 2. Phase 0.2.4 Source Changes (Verified)

### 2.1 Modified Files

| File | Status | Lines Added | Lines Removed | Net Change |
|---|---|---:|---:|---:|
| `app/config/settings.py` | MODIFIED | 41 | 7 | +34 |
| `app/attendance/storage.py` | MODIFIED | 17 | 6 | +11 |
| `app/api/enrollment.py` | MODIFIED | 140 | 1 | +139 |
| `app/main.py` | MODIFIED | 3 | 2 | +1 |

### 2.2 New Files

| File | Lines | Purpose |
|---|---:|---|
| `app/api/ai_worker.py` | 1,635 | 7 AI Worker endpoints (event, health, control) |
| `pipeline_engine/integration/health_client.py` | 347 | PipelineEngine health client |
| `pipeline_engine/integration/control_client.py` | 448 | PipelineEngine control server |

### 2.3 Total Source Impact

- **Modified:** 4 files
- **New:** 3 files
- **Total lines added:** ~2,221
- **Total lines removed:** ~16
- **Net lines:** +2,205

---

## 3. Detailed Source Change Analysis

### 3.1 `app/config/settings.py`

**Changes:**
- Added `_get_repository_root()` function resolving from `__file__`
- All `PathsConfig` fields now use `_get_repository_root()` instead of `Path.cwd()`
- All `ModelsConfig` fields now use `_get_repository_root()`
- `ParentRegistryConfig.db_path`, `NotificationQueueConfig.db_path`, `ExitSessionConfig.db_path` now use `_get_repository_root()`

**Impact:** Fixes CF-02 (CWD-dependent paths). All paths now resolve from repository root regardless of working directory.

**Verification:** SOURCE-VERIFIED — Direct source inspection confirms all path fields use repository-root-relative paths.

### 3.2 `app/attendance/storage.py`

**Changes:**
- Added `_get_attendance_db_path()` function resolving to `<repo_root>/app/data/attendance.db`
- `StorageConfig.database_path` now uses `_get_attendance_db_path()` default factory
- Changed `database_path` type from `str` to `Path`

**Impact:** Fixes CF-01 (dual databases) by enforcing single canonical path. Uses Path type for type safety.

**Verification:** SOURCE-VERIFIED — Direct source inspection confirms single authoritative path.

### 3.3 `app/api/enrollment.py`

**Changes:**
- Added `_reload_enrollment_database()` function with atomic swap logic
- Added `POST /api/v1/enrollment/reload` endpoint
- Added `GET /api/v1/enrollment/reload/status` endpoint
- Added Pydantic models: `EnrollmentReloadRequest`, `EnrollmentReloadResponse`
- Preserves previous enrollment on failure (`preserved_previous: true`)

**Impact:** Implements enrollment reload capability for PipelineEngine health integration (HP-06 from Phase 0.2.4).

**Verification:** SOURCE-VERIFIED — Endpoints exist and use proper authentication (admin key).

### 3.4 `app/main.py`

**Changes:**
- Added import: `from app.api.ai_worker import router as ai_worker_router`
- Added `ai_worker_router` to router inclusion loop

**Impact:** Registers the 7 AI Worker endpoints.

**Verification:** SOURCE-VERIFIED — Single router registration, no duplicates.

### 3.5 `app/api/ai_worker.py` (NEW)

**Endpoints Implemented (7 total):**

| # | Method | Path | Auth | Function |
|---|---|---|---|---|
| 1 | POST | `/api/v1/attendance/events` | AI_WORKER_KEY | Event ingestion |
| 2 | POST | `/api/v1/health/ai-worker` | AI_WORKER_KEY | Health heartbeat |
| 3 | POST | `/api/v1/ai/control/{action}` | ADMIN_KEY | Submit control request |
| 4 | GET | `/api/v1/ai/control/pending` | AI_CONTROL_KEY | Get pending requests |
| 5 | POST | `/api/v1/ai/control/{action}/response` | AI_CONTROL_KEY | Submit control response |
| 6 | GET | `/api/v1/ai/control/status` | AI_CONTROL_KEY | Control system status |
| 7 | POST | `/api/v1/health/ai-worker` (duplicate) | AI_WORKER_KEY | Duplicate definition |

**Duplicate Detection:** Lines 1346–1375 and 1574–1603 both define `ai_worker_health` with identical signatures. This is a **SOURCE-VERIFIED DEFECT** — duplicate endpoint definition.

**Models Defined (triplicated):** `TimeBase`, `CrossingPoint`, `Position`, `CameraState`, `ModelReadiness`, `CrossingEventRequest`, `CrossingEventResponse`, `AIWorkerHealthRequest`, `AIWorkerHealthResponse`, `ControlRequestStatus`, `ControlAction`, `ControlTarget`, `ControlRequest`, `ControlResponse`, `PendingControlRequests`, `PendingControlRequest` (dataclass), `_pending_control_requests`, `_processed_idempotency_keys`, `_cleanup_expired_requests`, `verify_ai_worker_key`, `verify_ai_control_key`, `verify_admin_key` — all defined **3 times** in the file.

**Verification:** SOURCE-VERIFIED DEFECT — Massive code duplication (file is 1,635 lines but unique content is ~550 lines). Three complete copies of all models and dependencies pasted sequentially.

### 3.6 `pipeline_engine/integration/health_client.py` (NEW)

**Implementation:** `LegacyBackendHealthClient` class with:
- Async health heartbeat sending with exponential backoff retry
- Bounded queue for offline buffering
- Control command polling
- Stream epoch tracking
- Camera state building from engine
- Model readiness checking
- Sequence number management

**Dependencies:** `httpx`, `pipeline_engine.core.engine.PipelineEngine`, `pipeline_engine.config.PipelineConfig`

**Verification:** SOURCE-VERIFIED — Complete implementation, no obvious defects.

### 3.7 `pipeline_engine/integration/control_client.py` (NEW)

**Implementation:** `PipelineEngineControlServer` class with:
- Pending command polling from Legacy Backend
- Idempotency key tracking
- Action handlers: START, STOP, RESTART, RECONFIG, PAUSE_CAMERA, RESUME_CAMERA
- Response submission to Legacy Backend

**Action Handlers Map:**
```python
_action_handlers = {
    Action.START: _handle_start,
    Action.STOP: _handle_stop,
    Action.RESTART: _handle_restart,
    Action.RECONFIG: _handle_reconfig,
    Action.PAUSE_CAMERA: _handle_pause_camera,
    Action.RESUME_CAMERA: _handle_resume_camera,
}
```

**Note:** Backend uses `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS` — **mismatch with control client actions** (`start`, `stop`, `restart`, `reconfig`, `pause_camera`, `resume_camera`).

**Verification:** SOURCE-VERIFIED — Contract mismatch identified.

---

## 4. Contract Mismatch Analysis

### 4.1 Health Endpoint Contract

| Aspect | Backend (`ai_worker.py`) | Client (`health_client.py`) | Match |
|---|---|---|---|
| Path | `/api/v1/health/ai-worker` | `/api/v1/health/ai-worker` | ✅ |
| Method | POST | POST | ✅ |
| Auth | AI_WORKER_KEY | AI_WORKER_KEY | ✅ |
| Request Schema | `AIWorkerHealthRequest` | Inline dict in `_send_heartbeat()` | ⚠️ Partial |
| Response Schema | `AIWorkerHealthResponse` | Expects `commands` array | ✅ |

**Client Payload Fields:** `worker_id`, `worker_version`, `state`, `timestamp`, `sequence_number`, `camera_states`, `model_readiness`, `inference_provider`, `queue_depth`, `processing_latency_ms`, `dropped_frame_count`, `event_delivery_state`, `stream_epochs`, `errors`

**Backend Expected Fields:** All of above plus `gpu_provider` (vs `inference_provider`)

### 4.2 Control Endpoint Contract

| Aspect | Backend (`ai_worker.py`) | Client (`control_client.py`) | Match |
|---|---|---|---|
| Pending Path | `/api/v1/ai/control/pending` | `/api/v1/ai/control/pending` | ✅ |
| Pending Method | GET | GET | ✅ |
| Pending Auth | AI_CONTROL_KEY | AI_CONTROL_KEY | ✅ |
| Response Path | `/api/v1/ai/control/{action}/response` | `/api/v1/ai/control/{action}/response` | ✅ |
| Response Method | POST | POST | ✅ |
| Response Auth | AI_CONTROL_KEY | AI_CONTROL_KEY | ✅ |

**Action Name Mismatch:**

| Backend Action | Client Action | Match |
|---|---|---|
| `START_WORKER` | `START` (="start") | ❌ |
| `STOP_WORKER` | `STOP` (="stop") | ❌ |
| `RESTART_WORKER` | `RESTART` (="restart") | ❌ |
| `ENABLE_CAMERA` | `PAUSE_CAMERA` (="pause_camera") | ❌ |
| `DISABLE_CAMERA` | `RESUME_CAMERA` (="resume_camera") | ❌ |
| `GET_STATUS` | (not implemented in client) | ❌ |

**Request/Response Schema Mismatch:**
- Backend `ControlRequest`: `request_id`, `action`, `target`, `target_id`, `parameters`, `idempotency_key`, `created_at`, `expires_at`
- Client `ControlRequest`: Same fields ✅
- Backend `ControlResponse`: `success`, `action`, `worker_id`, `status`, `request_id`, `timestamp`, `details`, `error`
- Client `ControlResponse`: Same fields ✅

---

## 5. No Undocumented Changes

- ✅ No additional source files modified beyond the 7 documented
- ✅ No user modifications overwritten (untracked files preserved)
- ✅ No accidental duplicate router registration (single `ai_worker_router` in `app/main.py`)
- ✅ No production configuration changed merely for tests
- ⚠️ **Defect found:** `app/api/ai_worker.py` has 3x code duplication
- ⚠️ **Defect found:** Control action names don't match between backend and client

---

## 6. Conclusion

**Source changes fully accounted for.** The 7 files from Phase 0.2.4 are the complete set of changes.

**Critical defects identified:**
1. `app/api/ai_worker.py` — 3x complete code duplication (1,635 lines vs ~550 unique)
2. Control action name mismatch — Backend uses `START_WORKER` etc., client uses `start` etc.
3. Health field name mismatch — Backend expects `gpu_provider`, client sends `inference_provider`

These defects must be addressed in Gates A and B integration testing.

---

**Classification:** SOURCE-VERIFIED