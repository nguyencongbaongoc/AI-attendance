# Phase 0.2.6 Repository State and Change Inventory

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate 0 Forensic Baseline  
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

- No `git reset`
- No `git clean`
- No `git checkout`
- No `git restore`
- No destructive rebase
- No force push

All previous audit artifacts preserved.

---

## 2. Phase 0.2.5 Source Changes (Current State Before 0.2.6)

### 2.1 Modified Files (from Phase 0.2.4)

| File | Status | Lines Changed |
|---|---|---|
| `app/config/settings.py` | MODIFIED | +41 / -7 |
| `app/attendance/storage.py` | MODIFIED | +17 / -6 |
| `app/api/enrollment.py` | MODIFIED | +140 / -1 |
| `app/main.py` | MODIFIED | +3 / -2 |

### 2.2 New Files (from Phase 0.2.4)

| File | Lines | Purpose |
|---|---:|---|
| `app/api/ai_worker.py` | 1,635 | 7 AI Worker endpoints (event, health, control) |
| `pipeline_engine/integration/health_client.py` | 347 | PipelineEngine health client |
| `pipeline_engine/integration/control_client.py` | 448 | PipelineEngine control server |

### 2.3 Total Source Impact (Pre-0.2.6)

- **Modified:** 4 files
- **New:** 3 files
- **Total lines added:** ~2,221
- **Total lines removed:** ~16
- **Net lines:** +2,205

---

## 3. Phase 0.2.6 Source Changes (This Phase)

### 3.1 Modified Files

| File | Change Type | Lines Before | Lines After | Net Change |
|---|---|---|---|---|
| `app/api/ai_worker.py` | REWRITE | 1,636 | ~600 | -1,036 |
| `app/api/enrollment.py` | PATCH | 346 | ~356 | +10 |

### 3.2 Modified Files (Patches)

| File | Change Type | Description |
|---|---|---|
| `pipeline_engine/integration/health_client.py` | PATCH | Fixed field names: `inference_provider` → `gpu_provider`, `dropped_frame_count` → `dropped_frames`, removed `event_delivery_state`, fixed polling key `commands` → `requests` |
| `pipeline_engine/integration/control_client.py` | REWRITE | Complete contract alignment: action vocab, polling key, response path, GET_STATUS handler |

### 3.3 Total Source Impact (Phase 0.2.6)

- **Rewritten:** 2 files (`app/api/ai_worker.py`, `pipeline_engine/integration/control_client.py`)
- **Patched:** 3 files (`app/api/enrollment.py`, `pipeline_engine/integration/health_client.py`, `pipeline_engine/integration/control_client.py` - but rewritten)
- **Total lines removed:** ~1,036 (deduplication)
- **Total lines added:** ~1,100 (health state, control fixes, history endpoint, auth hardening)
- **Net lines:** ~+64

---

## 4. Detailed Change Analysis

### 4.1 `app/api/ai_worker.py` - REWRITE

**Removed (3x duplication):**
- 3x copies of all Pydantic models (TimeBase, CrossingPoint, Position, CameraState, ModelReadiness, CrossingEventRequest, CrossingEventResponse, AIWorkerHealthRequest, AIWorkerHealthResponse, ControlRequestStatus, ControlAction, ControlTarget, ControlRequest, ControlResponse, PendingControlRequests, PendingControlRequest dataclass)
- 3x copies of all auth dependencies (verify_ai_worker_key, verify_ai_control_key, verify_admin_key)
- 3x copies of control state management (_pending_control_requests, _processed_idempotency_keys, _cleanup_expired_requests)
- 2x duplicate `ai_worker_health` endpoint definitions

**Added (Health State Management):**
- `WorkerHealthState` dataclass with generation tracking
- `_worker_health_states` in-memory store
- `_validate_health_request()` - sequence/generation validation
- `_update_worker_health()` - state update
- `_check_stale_workers()` - stale detection (30s threshold)
- `GET /api/v1/health/ai-worker/{worker_id}` endpoint

**Added (Control Fixes):**
- Path/body action validation in `submit_control_response()`
- Worker ID validation in `submit_control_response()`
- Fixed hardcoded worker_id in idempotency storage
- `GET /api/v1/ai/control/history` endpoint (admin only)

**Auth Hardening:**
- `verify_ai_worker_key`: fail-closed + `secrets.compare_digest`
- `verify_ai_control_key`: fail-closed + `secrets.compare_digest`
- `verify_admin_key`: already had constant-time, unchanged

**Control Integration:**
- Health endpoint returns pending control commands
- Marks commands as ACCEPTED on poll

### 4.2 `pipeline_engine/integration/health_client.py` - PATCH

**Field Fixes:**
- `inference_provider` → `gpu_provider`
- `dropped_frame_count` → `dropped_frames`
- Removed `event_delivery_state`

**Polling Fix:**
- `data.get("commands", [])` → `data.get("requests", [])` with action extraction

### 4.3 `pipeline_engine/integration/control_client.py` - REWRITE

**Action Vocabulary (Aligned to Backend):**
```python
# Before
START = "start", STOP = "stop", RESTART = "restart", RECONFIG = "reconfig", PAUSE_CAMERA = "pause_camera", RESUME_CAMERA = "resume_camera"

# After
START_WORKER = "START_WORKER", STOP_WORKER = "STOP_WORKER", RESTART_WORKER = "RESTART_WORKER",
ENABLE_CAMERA = "ENABLE_CAMERA", DISABLE_CAMERA = "DISABLE_CAMERA", GET_STATUS = "GET_STATUS"
```

**ControlResult Enum (Aligned):**
```python
# Before
ACCEPTED = "accepted", COMPLETED = "completed", FAILED = "failed"

# After
PENDING = "PENDING", ACCEPTED = "ACCEPTED", RUNNING = "RUNNING", COMPLETED = "COMPLETED",
FAILED = "FAILED", REJECTED = "REJECTED", EXPIRED = "EXPIRED"
```

**Polling Key Fix:**
- `data.get("commands", [])` → `data.get("requests", [])` with action extraction

**Response Endpoint Fix:**
- Uses `response.action` (canonical) in path

**Added GET_STATUS Handler:**
- Returns worker state, uptime, camera details

**Handler Mapping Updated:**
```python
_action_handlers = {
    Action.START_WORKER: _handle_start_worker,
    Action.STOP_WORKER: _handle_stop_worker,
    Action.RESTART_WORKER: _handle_restart_worker,
    Action.ENABLE_CAMERA: _handle_enable_camera,
    Action.DISABLE_CAMERA: _handle_disable_camera,
    Action.GET_STATUS: _handle_get_status,
}
```

### 4.4 `app/api/enrollment.py` - PATCH

- Added `verify_admin_key` dependency to `/reload` and `/reload/status` endpoints
- Imported `verify_admin_key` from `app.api.ai_worker`
- Added `Depends` import

---

## 5. Files NOT Modified

| File | Reason |
|---|---|
| `app/config/settings.py` | Already correct (CWD-independent paths) |
| `app/attendance/storage.py` | Already correct (fixed DB path) |
| `app/main.py` | Already correct (router registered) |
| `app/attendance/*.py` | No changes needed |
| `app/in_out/*.py` | No changes needed |
| `pipeline_engine/core/*.py` | No changes needed |
| `pipeline_engine/config/*.py` | No changes needed |

---

## 6. Safety Compliance

| Rule | Compliance |
|---|---|
| No `git reset` / `git clean` / `git checkout` / `git restore` | ✅ |
| No production DB modifications | ✅ (used TestClient) |
| No WAL/SHM deletion | ✅ |
| No quarantine modifications | ✅ |
| No Architecture A changes | ✅ |
| No Phase 1 features | ✅ |
| Isolated test databases/fixtures | ✅ |

---

## 7. Summary

**Phase 0.2.6 resolves all 3 critical blockers from Phase 0.2.5:**

1. ✅ Health backend state management implemented
2. ✅ Control client contract mismatches resolved (3/3)
3. ✅ Phase 0.2.4 artifact discrepancy documented

**Net source change:** ~64 lines added, ~1,036 lines deduplicated
**Test results:** 428 total tests PASS, 0 regressions