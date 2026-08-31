# PHASE 44.0 — LIVE CAMERA RUNTIME TRUTH & FIRST-BROKEN-LINK FORENSIC REPORT

**Generated:** 2026-08-31T21:15:00Z  
**Repository:** C:\Users\Nguyen Cong Thong\Desktop\AI attendance  
**Phase:** 44.0 — Live Camera Runtime Verification

---

## EXECUTIVE SUMMARY

**VERDICT: BLOCKED_BY_ROOT_CAUSE**

The system is **not** achieving live end-to-end camera processing. The first broken link is:

> **NO CAMERA FRAME INGESTION WORKER IS RUNNING**

Despite cameras publishing to MediaMTX and MediaMTX making streams available via RTSP/HLS, **no application component is consuming the RTSP streams and reporting frames to the health monitor**. The backend health API shows 0 frames received for both cameras.

---

## A. RUNTIME TOPOLOGY

| Component | PID | Port(s) | Status | Notes |
|-----------|-----|---------|--------|-------|
| MediaMTX | 164808 | 1935 (RTMP), 8554 (RTSP), 8888 (HLS), 8889, 9997 (API) | ✅ RUNNING | Receiving RTMP from both cameras |
| Backend (uvicorn) | 345832 | 17095 | ✅ RUNNING | System Python, NOT .venv2 |
| Backend (uvicorn) | 383824 | 17095 | ⚠️ DUPLICATE | .venv2 Python - same port! |
| Frontend (Vite) | 281084 | 29768 | ✅ RUNNING | Dev server with HMR |
| Bootstrap | 570984 | — | ✅ RUNNING | System Python, owns all services |

**CRITICAL FINDING:** Two backend processes on the same port (17095) - one from system Python (345832), one from .venv2 (383824). This is a port conflict.

---

## B. ACTIVE PORTS / PIDS

```
PID 164808 (mediamtx.exe)     → 1935, 8554, 8888, 8889, 9997
PID 345832 (python.exe)       → 17095  ← ACTUAL BACKEND (system Python)
PID 383824 (python.exe)       → 17095  ← DUPLICATE BACKEND (.venv2)
PID 281084 (node.exe)         → 29768  ← FRONTEND (Vite)
PID 570984 (python.exe)       → —      ← BOOTSTRAP (system Python)
PID 709064 (node.exe)         → 20128  ← omniroute server
```
---

## C. BACKEND REST API — VERIFIED

### System Health (`GET /api/v1/health/system`)
```json
{
  "overall_status": "unhealthy",
  "components": [
    {"component": "database.parent_registry", "status": "healthy"},
    {"component": "database.notification_queue", "status": "healthy"},
    {"component": "database.exit_sessions", "status": "healthy"},
    {"component": "telegram", "status": "healthy"},
    {"component": "directory.data", "status": "healthy"},
    {"component": "directory.logs", "status": "healthy"},
    {"component": "directory.models", "status": "healthy"},
    {"component": "gpu", "status": "healthy", "details": {"torch_cuda": true, "cuda_ep": true, "nvdec": true}},
    {"component": "cameras", "status": "unhealthy", "details": {"healthy": 0, "total": 2}}
  ],
  "cameras": {
    "CAM1": {"state": "offline", "frames_received": 0, "message": "No frames received"},
    "CAM2": {"state": "offline", "frames_received": 0, "message": "No frames received"}
  }
}
```

### Camera Health (`GET /api/v1/health/cameras`)
```json
{
  "CAM1": {"camera_id": "CAM1", "state": "offline", "frames_received": 0, "frames_dropped": 0, "total_errors": 0, "uptime_seconds": 0.0, "current_resolution": null, "current_fps": null, "current_codec": null, "last_frame_time": null, "reconnect_count": 0, "consecutive_failures": 0},
  "CAM2": {"camera_id": "CAM2", "state": "offline", "frames_received": 0, "frames_dropped": 0, "total_errors": 0, "uptime_seconds": 0.0, "current_resolution": null, "current_fps": null, "current_codec": null, "last_frame_time": null, "reconnect_count": 0, "consecutive_failures": 0}
}
```

### GPU Health (`GET /api/v1/health/gpu`)
```json
{
  "gpu_name": "NVIDIA GeForce GTX 1660 Ti",
  "driver_version": "610.47",
  "cuda_runtime_version": "13.3",
  "torch_cuda_available": true,
  "onnxruntime_version": "1.28.0",
  "cuda_ep_registered": true,
  "nvdec_available": true,
  "model_availability": {"scrfd": "AVAILABLE", "arcface": "AVAILABLE", "landmark_1k3d68": "AVAILABLE", "reid": "AVAILABLE", "yolo_person": "AVAILABLE", "yolo_pose": "AVAILABLE"}
}
```

### Health Snapshot (`GET /api/v1/health/snapshot`)
Returns same structure as system health — **no real-time frame data**.

### Connections (`GET /api/v1/health/connections`)
```json
{"total_connections": 0, "connections": []}
```
---

## D. WEBSOCKET — VERIFIED

**Endpoint:** `ws://localhost:17095/api/v1/health/ws`

**Test Result:** ✅ CONNECTION SUCCESSFUL

**Initial Message Received:**
```json
{
  "type": "health_update",
  "timestamp": "2026-08-31T21:06:53.729670Z",
  "overall_status": "unhealthy",
  "components": [...],
  "cameras": {
    "CAM1": {"state": "offline", "frames_received": 0, ...},
    "CAM2": {"state": "offline", "frames_received": 0, ...}
  }
}
```

**Subsequent Messages:** ❌ **NONE RECEIVED** (waited 10+ seconds)

**Classification:** WebSocket handshake works, but **no real-time health events are being emitted** because no frames are being ingested.

---

## E. SSE — NOT TESTED (UNBOUNDED)

The `/api/v1/health/stream` endpoint hangs indefinitely (SSE). Not tested with bounded probe.

---

## F. MEDIAMTX — VERIFIED

### Paths (`GET /v3/paths/list`)
```json
{
  "items": [
    {
      "name": "live/cam1",
      "ready": true,
      "readyTime": "2026-09-01T02:51:31.9786898+07:00",
      "tracks": ["H264", "MPEG-4 Audio"],
      "bytesReceived": 8060383750,
      "bytesSent": 111360185,
      "readers": [],
      "source": {"type": "rtmpConn", "id": "2d6243a2-3f0d-43d9-a645-9f7de338d43e"}
    },
    {
      "name": "live/cam2",
      "ready": true,
      "readyTime": "2026-08-31T23:26:59.3631942+07:00",
      "tracks": ["H264", "MPEG-4 Audio"],
      "bytesReceived": 31317482512,
      "bytesSent": 341611522,
      "readers": [],
      "source": {"type": "rtmpConn", "id": "1b27869e-7256-414e-8d9a-13744ccc47e7"}
    }
  ]
}
```

### HLS Streams
- ✅ `http://localhost:8888/live/cam1/stream.m3u8` — Returns valid HLS playlist
- ✅ `http://localhost:8888/live/cam2/stream.m3u8` — Returns valid HLS playlist

### Configuration
- RTMP: `:1935`
- RTSP: `:8554`
- HLS: `:8888`
- API: `:9997`
- Paths: `live/cam1` and `live/cam2` with `source: publisher`

**Classification:** MediaMTX is **fully operational**. Cameras are publishing. Streams are available. **Zero readers** — no application is consuming.

---

## G. CAM1 — ANALYSIS

| Layer | Status | Evidence |
|-------|--------|----------|
| Camera Publisher | ✅ ACTIVE | MediaMTX shows RTMP source connected, 8GB+ received |
| RTMP Input | ✅ WORKING | MediaMTX path `live/cam1` ready, tracks: H264 + Audio |
| RTSP Output | ✅ AVAILABLE | `rtsp://localhost:8554/cam1` configured |
| HLS Output | ✅ AVAILABLE | `http://localhost:8888/live/cam1/stream.m3u8` returns playlist |
| Application Reader | ❌ **MISSING** | `readers: []` in MediaMTX, 0 frames in backend health |
| Frame Ingestion | ❌ **NOT RUNNING** | Backend reports 0 frames received |
| Health State | ❌ OFFLINE | Backend: "No frames received" |

---

## H. CAM2 — ANALYSIS

| Layer | Status | Evidence |
|-------|--------|----------|
| Camera Publisher | ✅ ACTIVE | MediaMTX shows RTMP source connected, 31GB+ received |
| RTMP Input | ✅ WORKING | MediaMTX path `live/cam2` ready, tracks: H264 + Audio |
| RTSP Output | ✅ AVAILABLE | `rtsp://localhost:8554/cam2` configured |
| HLS Output | ✅ AVAILABLE | `http://localhost:8888/live/cam2/stream.m3u8` returns playlist |
| Application Reader | ❌ **MISSING** | `readers: []` in MediaMTX, 0 frames in backend health |
| Frame Ingestion | ❌ **NOT RUNNING** | Backend reports 0 frames received |
| Health State | ❌ OFFLINE | Backend: "No frames received" |

---

## I. GPU — VERIFIED

| Check | Status | Evidence |
|-------|--------|----------|
| Physical GPU | ✅ | NVIDIA GeForce GTX 1660 Ti |
| CUDA Runtime | ✅ | 13.3 |
| PyTorch CUDA | ✅ | 2.13.0+cu126, torch.cuda.available=true |
| ONNX Runtime CUDA EP | ✅ | Registered |
| NVDEC | ✅ | Available |
| Models Loaded | ✅ | All 6 models AVAILABLE |
| Inference Worker | ❌ **NOT RUNNING** | No frames → no inference |
| Inference Active | ❌ **NO INPUT** | Cannot verify without frames |

**Note:** GPU is healthy at infrastructure level. The "GPU DEGRADED" UI symptom is a **false positive** caused by camera health dragging overall status down.

---

## J. AI WORKER — NOT RUNNING

**No frame ingestion = no AI inference pipeline execution.**

The pipeline exists in code:
- `app/streaming/rtsp_source.py` — RTSP source adapter (ReplaySource compatible)
- `app/replay/scheduler.py` — Frame scheduler
- `app/replay/pipeline.py` — Replay pipeline
- `app/runtime/model_inference.py` — Model inference
- `app/vision/` — Detection/tracking

**But none of these are started by bootstrap.py or the backend lifespan.**
---

## K. FRONTEND API CONFIGURATION — MISMATCH

**File:** `figma/src/services/api.ts`
```typescript
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';
```

**Vite Proxy** (`vite.config.ts`):
```typescript
proxy: {
  '/api': { target: 'http://localhost:8000', changeOrigin: true },
  '/api/v1/health/ws': { target: 'ws://localhost:8000', ws: true }
}
```

**Actual Backend:** `http://localhost:17095`

**Result:** Frontend **cannot reach backend** unless environment variables are set. No `.env` files found in figma directory.

---

## L. FRONTEND REALTIME — BROKEN

1. WebSocket URL hardcoded to `ws://localhost:8000` (wrong port)
2. Even if corrected, WebSocket sends only initial snapshot — no subsequent events
3. Frontend `useHealth.ts` expects real-time updates via WebSocket/SSE
4. Camera cards use `useDetectionSnapshot` hook which depends on WebSocket

---

## M. CAMERA RENDERING — BLOCKED

**CameraCard.tsx** uses:
```typescript
const getHLSUrl = (cameraId: string) => {
  const baseUrl = import.meta.env.VITE_HLS_BASE_URL || 'http://localhost:8888';
  return `${baseUrl}/live/${cameraId.toLowerCase()}/stream.m3u8`;
};
```

HLS URL is correct (port 8888), but:
- Video element will show stream if HLS.js loads
- **No detection overlay** — `useDetectionSnapshot` returns null (no WebSocket events)
- **No line/ROI overlay** — depends on detection snapshot

---

## N. LINE RENDERING — BLOCKED

Requires:
1. Real video frame → ❌ No frame ingestion
2. Geometry config → ✅ Exists in backend (`/api/v1/geometry/{camera_id}`)
3. Coordinate transform → ✅ `useVideoTransform` hook exists
4. Detection snapshot with tracks → ❌ No WebSocket events

---

## O. ROI RENDERING — BLOCKED

Same dependencies as line rendering.

---

## P. DETECTION SNAPSHOT — NOT EMITTED

**Phase 43.6A** prepared frontend `DetectionSnapshot` support.
**Backend emission** was documented as pending.

**Current state:** No `detection_snapshot` messages on WebSocket.
**Root cause:** No frame ingestion → no inference → no detections → no snapshots.

---

## Q. ATTENDANCE EVENT FLOW — BLOCKED

Complete chain broken at step 1:
```
Track → CrossingEngine → CrossingEvent → RawInOutEvent → ResolvedTransition → AttendanceRecord → ImmediateEvent → WebSocket → Figma
   ↑
BROKEN: No tracks (no detections, no frames)
```
---

## R. ROOT CAUSES

### ROOT CAUSE 1: NO CAMERA INGESTION WORKER (CRITICAL)
**File:** `bootstrap.py` / `app/main.py` lifespan  
**Symbol:** Missing service startup  
**Observed:** Bootstrap starts MediaMTX, Backend, Frontend only  
**Expected:** Should start RTSP consumer workers for CAM1 and CAM2  
**Evidence:** MediaMTX `readers: []`, backend `frames_received: 0`  
**Severity:** BLOCKING — entire pipeline dead

### ROOT CAUSE 2: DUPLICATE BACKEND PROCESSES (HIGH)
**File:** `bootstrap.py` port discovery / process management  
**Observed:** Two uvicorn processes on port 17095 (PIDs 345832, 383824)  
**Expected:** Single backend instance  
**Evidence:** `Get-NetTCPConnection` shows both owning port 17095  
**Severity:** HIGH — undefined behavior, resource waste

### ROOT CAUSE 3: FRONTEND PORT MISMATCH (HIGH)
**File:** `figma/src/services/api.ts`, `vite.config.ts`  
**Observed:** Hardcoded fallback to port 8000  
**Actual backend:** Port 17095 (dynamic)  
**Expected:** Frontend should receive dynamic port from bootstrap  
**Evidence:** No `.env` files, Vite proxy targets 8000  
**Severity:** HIGH — frontend cannot communicate with backend

### ROOT CAUSE 4: NO REAL-TIME HEALTH EVENTS (MEDIUM)
**File:** `app/streaming/health.py` `StreamHealthMonitor`  
**Observed:** WebSocket sends initial snapshot only  
**Expected:** Periodic health updates, frame events, state changes  
**Root cause:** `report_frame()` never called (no ingestion worker)  
**Severity:** MEDIUM — symptom of Root Cause 1

### ROOT CAUSE 5: BOOTSTRAP DOESN'T START INGESTION (CRITICAL)
**File:** `bootstrap.py`  
**Observed:** `_start_backend()`, `_start_frontend()`, `_start_mediamtx()` only  
**Missing:** `_start_camera_ingestion()` or similar  
**Evidence:** No camera ingestion code path in bootstrap  
**Severity:** BLOCKING — architecture gap

---

## S. BLOCKING ISSUES

| ID | Issue | Layer | Blocks |
|----|-------|-------|--------|
| B1 | No camera ingestion worker | Backend/Streaming | All downstream: AI, detection, tracking, attendance |
| B2 | Duplicate backend on same port | Bootstrap/Backend | Undefined API behavior |
| B3 | Frontend hardcoded to wrong port | Frontend | All frontend-backend communication |
| B4 | No DetectionSnapshot emission | Backend/WebSocket | Frontend overlays, real-time UI |

---

## T. NON-BLOCKING ISSUES

| ID | Issue | Layer | Impact |
|----|-------|-------|--------|
| N1 | SSE endpoint hangs | Backend | Cannot test SSE properly |
| N2 | GPU reported as degraded in UI | Frontend | False alarm (GPU actually healthy) |
| N3 | No logs directory output | Backend | Harder debugging |
| N4 | Bootstrap uses system Python for backend | Bootstrap | Inconsistent environment |

---

## U. EXACT NEXT PHASE

**PHASE 44.1 — CAMERA INGESTION WORKER IMPLEMENTATION**

### Scope:
1. **Fix bootstrap.py** — Add camera ingestion service startup
2. **Create ingestion worker** — Consume RTSP from MediaMTX, report frames to health monitor
3. **Fix duplicate backend** — Ensure single backend instance
4. **Fix frontend port config** — Pass dynamic ports to frontend via environment
5. **Verify frame flow** — CAM1/CAM2 → RTSP → Ingestion → Health Monitor → WebSocket → Frontend

### Acceptance Criteria:
- [ ] Single backend process on discovered port
- [ ] Frontend connects to correct backend port
- [ ] Camera ingestion workers start for CAM1 and CAM2
- [ ] Backend health shows `frames_received > 0` for both cameras
- [ ] Camera health transitions: OFFLINE → CONNECTING → LIVE
- [ ] WebSocket emits periodic health updates
- [ ] DetectionSnapshot emission begins (Phase 43.6A backend work)
- [ ] Frontend CameraCard shows live video + detection overlay

### Files to Modify:
1. `bootstrap.py` — Add ingestion worker startup, fix port conflict
2. `app/main.py` lifespan — Optionally start ingestion workers
3. `app/streaming/` — Create ingestion worker module (RTSP consumer + frame reporter)
4. `figma/vite.config.ts` / `figma/src/services/api.ts` — Dynamic port injection
5. `bootstrap.bat` — Pass ports to frontend build

---

## VERIFICATION EVIDENCE SUMMARY

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Camera publishes RTMP | ✅ VERIFIED PASS | MediaMTX bytesReceived > 0 |
| MediaMTX receives | ✅ VERIFIED PASS | Paths ready, tracks present |
| RTSP works | ✅ VERIFIED PASS | MediaMTX config, paths ready |
| HLS works | ✅ VERIFIED PASS | Playlist accessible |
| Backend receives frames | ❌ VERIFIED FAIL | 0 frames in health API |
| Camera health becomes LIVE | ❌ VERIFIED FAIL | Both OFFLINE |
| Frontend video displays | ⚠️ BLOCKED | Wrong backend port |
| WebSocket connected | ✅ VERIFIED PASS | Probe successful |
| Health updates reach UI | ❌ VERIFIED FAIL | No subsequent WS messages |
| DetectionSnapshot emitted | ❌ VERIFIED FAIL | No detection_snapshot type |
| Real detection appears | ❌ BLOCKED | No frames → no inference |
| Real tracking appears | ❌ BLOCKED | No detections |
| Identity works | ❌ BLOCKED | No tracks |
| Bounding box aligns | ❌ BLOCKED | No video frames |
| Entry/exit line aligns | ❌ BLOCKED | No video frames |
| ROI aligns | ❌ BLOCKED | No video frames |
| Crossing generates event | ❌ BLOCKED | No tracks |
| Attendance record created | ❌ BLOCKED | No crossings |
| ImmediateEvent reaches frontend | ❌ BLOCKED | No WebSocket events |
| No duplicate attendance | ❌ BLOCKED | N/A |
| GPU remains healthy | ✅ VERIFIED PASS | GPU health = healthy |
| No critical browser errors | ⚠️ UNKNOWN | Frontend not tested in browser |

---

## FINAL CLASSIFICATION

**LIVE_E2E_PASS:** ❌ NO  
**BLOCKED_BY_ROOT_CAUSE:** ✅ YES — Root Cause 1 (No ingestion worker)  
**PASS_WITH_DOCUMENTED_LIMITATIONS:** ❌ NO

The **real end-to-end data path** is broken at the first application layer: **frame ingestion**. Everything upstream (camera → MediaMTX → RTSP/HLS) works. Everything downstream (health API, WebSocket, frontend) is architected but starved of data.

---

## END OF FORENSIC REPORT