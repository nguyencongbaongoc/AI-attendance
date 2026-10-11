# Phase 0.2 — Startup and Shutdown Procedures

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up

---

## 1. Startup Order (Dependency-Aware)

### 1.1 Required Order

```
1. MediaMTX          (port 8554, 1935, 9997) — NO dependencies
   ↓ wait for API ready (port 9997)
2. Camera Publishers (push RTMP to MediaMTX :1935/live/cam1, :1935/live/cam2)
   ↓ wait for paths ready (API shows ready=true)
3. Legacy Backend    (port dynamic, e.g., 19146) — needs data/ databases
   ↓ wait for /health/ready
4. Pipeline Engine   (AI Worker) — needs MediaMTX RTSP, Legacy Backend API, models
   ↓ wait for camera RTSP decode, model sessions
5. UI Frontend       (if implemented) — needs Legacy Backend API, MediaMTX HLS/WebRTC
```

### 1.2 Verification Gates

| Step | Verification | Timeout |
|------|--------------|---------|
| 1. MediaMTX | `curl http://localhost:9997/v3/paths/list` returns 200 | 15 sec |
| 2. Cameras | `live/cam1` and `live/cam2` show `ready: true` | 30 sec |
| 3. Backend | `GET /api/v1/health/ready` returns `{"status": "ready"}` | 15 sec |
| 4. Pipeline | `bootstrap.py --check` passes, RTSP decode works | 30 sec |
| 5. UI | `GET /` returns frontend | 10 sec |

---

## 2. Startup Commands

### 2.1 MediaMTX
```powershell
cd mediamtx
.\mediamtx.exe .\mediamtx.yml
```
**Or as background:**
```powershell
Start-Process -FilePath ".\mediamtx.exe" -ArgumentList ".\mediamtx.yml" -WorkingDirectory ".\mediamtx" -WindowStyle Hidden
```

### 2.2 Camera Publishers
**Manual (for testing):**
```bash
# Camera 1
ffmpeg -re -stream_loop -1 -i test_video.mp4 -c copy -f flv rtmp://localhost:1935/live/cam1

# Camera 2  
ffmpeg -re -stream_loop -1 -i test_video2.mp4 -c copy -f flv rtmp://localhost:1935/live/cam2
```

**Production:** Hardware cameras configured to push RTMP to `rtmp://<server>:1935/live/cam1` and `cam2`.

### 2.3 Legacy Backend
```powershell
# Option A: bootstrap.py (orchestrates everything)
.venv2\Scripts\python.exe bootstrap.py

# Option B: Direct (for backend only)
.venv2\Scripts\python.exe -c "
import sys
sys.path.insert(0, 'C:\...\AI_ATTENDANCE')
from app.main import create_app
import uvicorn
app = create_app()
uvicorn.run(app, host='0.0.0.0', port=19146, log_level='info')
"
```

### 2.4 Pipeline Engine (Architecture A - Future)
```powershell
.venv2\Scripts\python.exe bootstrap.py --camera cam1 --camera cam2
```

---

## 3. Shutdown Order (Reverse)

```
5. UI Frontend       (if running)
4. Pipeline Engine   (graceful stop, wait for engine.stop())
3. Legacy Backend    (Ctrl+C / SIGTERM)
2. Camera Publishers (stop FFmpeg / camera push)
1. MediaMTX          (Ctrl+BREAK / SIGTERM)
```

### 3.1 Shutdown Commands

**Graceful shutdown (Ctrl+C handled by bootstrap.py):**
```bash
# If started via bootstrap.py
Ctrl+C  # triggers bootstrap.stop() → engine.stop() → service_manager.stop_mediamtx()

# If started individually:
# Legacy Backend: Ctrl+C in terminal
# MediaMTX: Ctrl+BREAK in terminal (Windows) or kill PID
```

**Force shutdown (if graceful fails):**
```powershell
# MediaMTX
taskkill /F /IM mediamtx.exe

# Python processes
taskkill /F /FI "IMAGENAME eq python.exe"  # CAUTION: kills ALL python
```

---

## 4. Bootstrap.py Built-in Orchestration

The `bootstrap.py` implements the complete startup/shutdown sequence:

### 4.1 Startup (bootstrap.start())
1. `EnvironmentValidator.validate_all()` — Python, CUDA, deps, config, models, cameras, MediaMTX, FFmpeg, dirs
2. `ServiceManager.start_mediamtx()` — starts MediaMTX if not running
3. `PipelineEngine(config_path)` — load config, initialize, start
4. `_verify_health()` — wait for cameras RUNNING (30s timeout)
5. `_run_supervisor()` — monitor loop with status printing

### 4.2 Shutdown (bootstrap.stop())
1. `engine.stop()` — graceful pipeline shutdown
2. `service_manager.stop_mediamtx()` — stop MediaMTX if we started it

### 4.3 Signal Handling
- SIGINT (Ctrl+C) → `_shutdown_requested = True`
- SIGTERM → same
- SIGBREAK (Windows) → same

---

## 5. Current Working Commands (Validated)

### 5.1 Verified Working Sequence
```powershell
# 1. Start MediaMTX
cd mediamtx
Start-Process -FilePath ".\mediamtx.exe" -ArgumentList ".\mediamtx.yml" -WindowStyle Hidden

# 2. Verify MediaMTX
Start-Sleep 3
curl http://localhost:9997/v3/paths/list

# 3. Start Legacy Backend (background)
$env:PYTHONPATH = "C:\...\AI_ATTENDANCE"
Start-Process -FilePath ".\.venv2\Scripts\python.exe" -ArgumentList "-c \"import sys; sys.path.insert(0, 'C:\...\AI_ATTENDANCE'); from app.main import create_app; import uvicorn; app = create_app(); uvicorn.run(app, host='0.0.0.0', port=19146, log_level='info')\"" -WindowStyle Hidden

# 4. Verify Backend
Start-Sleep 3
curl http://localhost:19146/api/v1/health/ready

# 5. Test streams
.venv2\Scripts\python.exe -c "
import av
for u in ['rtsp://localhost:8554/live/cam1', 'rtsp://localhost:8554/live/cam2']:
    c = av.open(u); print(u, 'OK'); c.close()
"
```

### 5.2 Health Check All
```powershell
.venv2\Scripts\python.exe bootstrap.py --check
```

---

## 6. Shutdown Verification

After shutdown:
- ✅ No python.exe processes from our sessions
- ✅ No mediamtx.exe process
- ✅ Ports 8554, 1935, 9997, 19146 released
- ✅ SQLite WAL files cleaned up (-shm, -wal removed)

---

## 7. What NOT to Do

| Anti-Pattern | Why |
|--------------|-----|
| `taskkill /F /IM python.exe` | Kills ALL Python (venv, other tools, IDE) |
| `git clean -fd` | Deletes .venv2, models, SDKs, user data |
| Kill MediaMTX before publishers | Publishers reconnect storm |
| Stop backend before pipeline | Pipeline tries to write to dead API |
| Skip health verification | Services may not be ready |

---

## 8. Recovery Procedures

### 8.1 MediaMTX Won't Start
```bash
# Check port conflicts
netstat -an | findstr :8554
# Kill existing
taskkill /F /IM mediamtx.exe
# Check config syntax
.\mediamtx.exe .\mediamtx.yml  # run in foreground to see errors
```

### 8.2 Backend Port Conflict
```bash
# Find free port (bootstrap does this automatically)
.venv2\Scripts\python.exe -c "from app.bootstrap.port_discovery import find_backend_port; print(find_backend_port())"
```

### 8.3 Database Locked
```bash
# Remove WAL files (safe if no process using DB)
del data\attendance.db-shm
del data\attendance.db-wal
```

### 8.4 Camera Streams Not Ready
```bash
# Check MediaMTX paths
curl http://localhost:9997/v3/paths/list
# Verify publishers pushing to RTMP :1935
# Check camera hardware/network
```

---

## 9. Summary: Minimal Viable Startup

For Phase 0.2 verification only:
```bash
# Terminal 1: MediaMTX
cd mediamtx && .\mediamtx.exe .\mediamtx.yml

# Terminal 2: Legacy Backend  
.venv2\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.main import create_app; import uvicorn; uvicorn.run(create_app(), host='0.0.0.0', port=19146)"

# Terminal 3: Verification
.venv2\Scripts\python.exe bootstrap.py --check
# Test streams
.venv2\Scripts\python.exe -c "import av; [print(av.open(u).close()) for u in ['rtsp://localhost:8554/live/cam1', 'rtsp://localhost:8554/live/cam2']]"
```