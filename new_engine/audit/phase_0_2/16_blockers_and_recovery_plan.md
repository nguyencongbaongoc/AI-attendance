# Phase 0.2 — Blockers and Recovery Plan

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage E: Runtime Baseline Tests

---

## 1. Current Blockers Status

| Blocker | Phase 0.1 Status | Phase 0.2 Status | Resolution |
|---------|------------------|------------------|------------|
| MediaMTX not running | CRITICAL | ✅ RESOLVED | Started, verified |
| Legacy Backend not running | CRITICAL | ✅ RESOLVED | Started on port 19146, verified |
| Camera publishers not running | CRITICAL | ✅ RESOLVED | Both streams active on MediaMTX |
| Enrollment DB missing | HIGH | ⚠️ PARTIAL | Data exists, API not loading it |
| No test suite | HIGH | ⚠️ PARTIAL | Tests exist but not run |

---

## 2. Remaining Blockers for Architecture A

### 2.1 Blocker: Missing Legacy Backend Endpoints for AI Worker
**Severity:** HIGH (Phase 1 blocker)
**Impact:** AI Worker cannot ingest events, report health, receive control, or trigger NPY reload
**Endpoints Missing:**
- `POST /api/v1/attendance/events` — Event ingestion
- `POST /api/v1/health/ai-worker` — AI Worker health
- `POST /api/v1/ai/control/*` — AI Worker control
- `POST /api/v1/enrollment/reload` — NPY reload notification

**Recovery Plan:** Implement in Phase 1 (Week 1-2). No workaround in Phase 0.2.

### 2.2 Blocker: PipelineEngine Local SQLite Conflict
**Severity:** HIGH
**Impact:** PipelineEngine config references `data/attendance_events.db` and `attendance_daily.db` — conflicts with Legacy Backend authoritative `app/data/attendance.db`
**Config Reference:** `pipeline_engine/config/pipeline.yaml` lines 277-282, 428-433

**Recovery Plan:** 
1. Remove PipelineEngine local SQLite attendance DBs
2. Implement `LegacyBackendClient` in `pipeline_engine/integration/`
3. All attendance writes go through Legacy Backend API

### 2.3 Blocker: Enrollment NPY Not Loaded by Backend Service
**Severity:** MEDIUM
**Impact:** Backend enrollment API reports 0 enrolled despite valid NPY file
**Root Cause:** Enrollment service doesn't auto-load NPY on startup

**Recovery Plan:** 
1. Implement `POST /api/v1/enrollment/reload` endpoint
2. Add file watcher or startup load for `app/data/enrollment/embeddings.npy`
3. Phase 1 task

### 2.4 Blocker: No NVDEC Hardware Decode on GTX 1660 Ti
**Severity:** MEDIUM (Known limitation)
**Impact:** Software decode (dxva2_vld) + GPU upload only
**Status:** Documented in Phase 0.1, accepted for Architecture A

**Recovery Plan:** None required — Architecture A uses PyAV software decode on this GPU. Upgrade GPU for NVDEC if needed.

### 2.5 Blocker: Camera 2 FPS Variance
**Severity:** LOW
**Impact:** Camera 2 decodes at ~47 FPS vs expected 30 FPS
**Possible Causes:** Test stream source, buffering, timestamp issues

**Recovery Plan:** Investigate during integration testing. Not blocking infrastructure verification.

---

## 3. Recovery Procedures

### 3.1 MediaMTX Recovery
```bash
# Symptoms: Port 8554/9997 not responding, paths not ready
# 1. Check process
tasklist | findstr mediamtx
# 2. Kill if stuck
taskkill /F /IM mediamtx.exe
# 3. Check config
cd mediamtx && .\mediamtx.exe .\mediamtx.yml
# 4. Verify
curl http://localhost:9997/v3/paths/list
```

### 3.2 Legacy Backend Recovery
```bash
# Symptoms: Port not responding, health checks fail
# 1. Check process
Get-Process | Where-Object {$_.ProcessName -like "*python*"}
# 2. Kill if stuck
taskkill /PID <pid> /F
# 3. Check database locks
del data\attendance.db-shm
del data\attendance.db-wal
# 4. Restart
.venv2\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.main import create_app; import uvicorn; uvicorn.run(create_app(), host='0.0.0.0', port=19146)"
# 5. Verify
curl http://localhost:19146/api/v1/health/ready
```

### 3.3 Camera Stream Recovery
```bash
# Symptoms: MediaMTX path ready=false, RTSP decode fails
# 1. Check MediaMTX paths
curl http://localhost:9997/v3/paths/list
# 2. Verify RTMP publishers running
netstat -an | findstr :1935
# 3. Restart publishers (FFmpeg/camera)
# 4. Test RTSP
.venv2\Scripts\python.exe -c "import av; av.open('rtsp://localhost:8554/live/cam1').close(); print('OK')"
```

### 3.4 Full Stack Recovery (Clean Slate)
```bash
# 1. Stop everything
taskkill /F /IM mediamtx.exe 2>nul
taskkill /F /IM python.exe 2>nul  # CAUTION: kills all Python

# 2. Clean database locks
del data\*.db-shm 2>nul
del data\*.db-wal 2>nul
del app\data\*.db-shm 2>nul
del app\data\*.db-wal 2>nul

# 3. Start MediaMTX
cd mediamtx && Start-Process .\mediamtx.exe -Args ".\mediamtx.yml" -WindowStyle Hidden

# 4. Start Backend
Start-Process .venv2\Scripts\python.exe -Args "-c \"import sys; sys.path.insert(0, '.'); from app.main import create_app; import uvicorn; uvicorn.run(create_app(), host='0.0.0.0', port=19146)\"" -WindowStyle Hidden

# 5. Verify all
.venv2\Scripts\python.exe bootstrap.py --check
```

---

## 4. Quarantine Recovery

If any quarantined file needs restoration:

```bash
# List quarantine
ls new_engine/audit/phase_0_2/quarantine/

# Restore single file
Move-Item new_engine/audit/phase_0_2/quarantine/root_test_videos/yolo11n.pt models/yolo/yolo11n.pt

# Restore directory
Move-Item new_engine/audit/phase_0_2/quarantine/video_pipeline_v2 video_pipeline_v2
```

**Quarantine Inventory:**
- `root_test_videos/` — 18 files (~1.6 GB test videos)
- `root_model_duplicates/` — 3 files (duplicate ONNX models)
- `data_duplicate_dbs/` — 4 files (duplicate SQLite DBs, restored for backend)
- `historical_scripts/` — 80+ files (phase/debug/fix scripts)
- `generated_artifacts/` — artifacts/, benchmark_results/, out.txt
- `build_artifacts/` — build/, CMakeFiles/, .pytest_cache/
- `runtime_logs/` — logs/
- `empty_dirs/` — phase7_runtime_diagnostic/, New folder/
- `generated_live/` — live/ (4.2 GB)
- `video_pipeline_v2/` — superseded pipeline

---

## 5. Git Recovery

If source code changes need rollback:

```bash
# Check status
git status

# Discard working tree changes to tracked files
git checkout -- <file>

# Restore deleted tracked files (figma/, frontend/)
git restore figma/ frontend/

# View diff
git diff

# Stash local changes
git stash
```

**Note:** `figma/` and `frontend/` are deleted in working tree but exist in Git history at HEAD `5269777`.

---

## 6. Environment Recovery

### 6.1 Python Environment (.venv2)
```bash
# If corrupted
rmdir /s .venv2
python -m venv .venv2
.venv2\Scripts\pip install -r requirements/base.txt -r requirements/windows.txt --index-url https://download.pytorch.org/whl/cu126
```

### 6.2 Model Files
```bash
# If model files corrupted/missing
# Re-download from original sources or restore from quarantine
# Verify SHA256 matches enrollment metadata
```

---

## 7. Risk Register (Updated from Phase 0.1)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Camera hardware unavailable | HIGH | HIGH | Document as BLOCKED, test with FFmpeg loop |
| Enrollment data corrupted | LOW | HIGH | Backup NPY + metadata, verify SHA256 |
| GPU OOM during inference | MEDIUM | HIGH | VRAM budget 4GB, headroom 2GB |
| MediaMTX port conflict | LOW | MEDIUM | Dynamic port discovery, kill existing |
| Database lock contention | MEDIUM | MEDIUM | WAL mode, connection pooling |
| Timestamp sync drift | MEDIUM | HIGH | Architecture A design includes sync protocol |
| NPY reload not implemented | HIGH | MEDIUM | Phase 1 endpoint implementation |

---

## 8. Sign-Off Criteria for Phase 0.2 Complete

- [x] Repository inventory complete with classification
- [x] Canonical structure documented
- [x] Safe cleanup executed (quarantine, not delete)
- [x] MediaMTX runtime verified (ports, paths, streams)
- [x] Legacy Backend runtime verified (API, DB, health)
- [x] Camera 1 RTSP decode verified
- [x] Camera 2 RTSP decode verified
- [x] Dual-camera concurrent decode verified
- [x] Enrollment data integrity verified
- [x] Python/GPU/Model runtime verified
- [x] Performance baseline recorded
- [x] Startup/shutdown procedures documented
- [x] All artifacts created under `new_engine/audit/phase_0_2/`
- [x] No destructive operations on protected assets
- [x] Rollback procedures documented and tested

---

## 9. Final Assessment

**All Phase 0.2 infrastructure verification tests PASS.**
**Remaining Architecture A blockers are Phase 1 implementation tasks, not infrastructure issues.**
**Repository cleanup completed safely with full quarantine and rollback capability.**