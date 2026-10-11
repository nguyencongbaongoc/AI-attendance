# Phase 0.2.6 Control Contract Before/After

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Gate B  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE

---

## 1. Contract Changes Summary

| Component | Before (0.2.5) | After (0.2.6) |
|---|---|---|
| Backend Action Names | `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS` | Same (canonical) |
| Client Action Names | `start`, `stop`, `restart`, `reconfig`, `pause_camera`, `resume_camera` | **Aligned to backend** |
| Polling Response Key | Backend: `requests`, Client expected: `commands` | **Aligned: `requests`** |
| Response Endpoint | Client used local action enum | **Uses `response.action`** |
| GET_STATUS Handler | Missing in client | **Added** |
| Path/Body Validation | None | **Added** |
| History Endpoint | Missing | **Added** |

---

## 2. Action Vocabulary Alignment

### Before (Mismatched)

| Context | Actions |
|---|---|
| Backend (ControlAction enum) | `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS` |
| Client (Action enum) | `start`, `stop`, `restart`, `reconfig`, `pause_camera`, `resume_camera` |
| Overlap | **ZERO** |

### After (Aligned)

| Context | Actions |
|---|---|
| Backend | `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS` |
| Client | `START_WORKER`, `STOP_WORKER`, `RESTART_WORKER`, `ENABLE_CAMERA`, `DISABLE_CAMERA`, `GET_STATUS` |
| Overlap | **COMPLETE** |

---

## 3. Polling Response Schema

### Before
- **Backend returns:** `{"worker_id": "...", "requests": [...]}`
- **Client expects:** `data.get("commands", [])`
- **Result:** Always empty command list

### After
- **Backend returns:** `{"worker_id": "...", "requests": [...]}`
- **Client uses:** `data.get("requests", [])` → extracts action from each request
- **Result:** Correctly retrieves pending commands

---

## 4. Response Endpoint

### Before
- **Client posts to:** `/api/v1/ai/control/{local_action}/response` (e.g., `/start/response`)
- **Backend expects:** `/api/v1/ai/control/{BACKEND_ACTION}/response` (e.g., `/START_WORKER/response`)
- **Result:** 400 Invalid Action

### After
- **Client posts to:** `/api/v1/ai/control/{response.action}/response`
- **Backend validates:** `path_action == response.action`
- **Result:** 200 OK

---

## 5. New Features (0.2.6)

| Feature | Description |
|---|---|
| GET_STATUS Handler | Added to client, returns worker/camera status |
| Path/Body Validation | Backend rejects if path action ≠ body action |
| History Endpoint | `GET /api/v1/ai/control/history` (admin only) |
| Auth Hardening | Worker/Control keys now fail-closed + constant-time |

---

## 6. Test Results

| Test Category | Tests | Pass | Fail |
|---|---:|---:|---:|
| Backend Endpoints | 5 | 5 | 0 |
| Client Contract Alignment | 5 | 5 | 0 |
| E2E Client Simulation | 2 | 2 | 0 |
| Control Lifecycle | 2 | 2 | 0 |
| Authorization | 3 | 3 | 0 |
| **Total** | **17** | **17** | **0** |

**Gate B: PASS**