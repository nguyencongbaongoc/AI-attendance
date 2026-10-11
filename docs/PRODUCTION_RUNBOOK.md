# Production Runbook
## AI Attendance System — Architecture A (Stream Passthrough, Singleton TensorRT, Async Pipeline)

**Version:** 1.0  
**Date:** 2026-10-10  
**Platform:** Windows 11, NVIDIA GeForce GTX 1660 Ti (6GB VRAM)  
**Certification:** PRODUCTION_READY (Phase 18)

---

## 1. System Overview

### 1.1 Architecture Summary
The AI Attendance System implements **Architecture A** with the following invariants:
- **Video Relay:** Unannotated passthrough, zero video re-encoding (no NVENC/CPU video encoding on display path)
- **Database Authority:** `app/data/attendance.db` strictly owned by Legacy Backend Resolver; AI Worker never writes directly
- **Zero Hot-Path I/O Contention:** File I/O, snapshot saving, clip trimming, notifications 100% decoupled in background threadpools
- **VRAM Budget:** < 2.2 GB total during full-stack concurrent execution on GTX 1660 Ti
- **Process Management:** Cold start and graceful termination via `bootstrap.py` / `bootstrap.bat` with zero zombie processes

### 1.2 Core Components
| Component | Technology | Port | Description |
|-----------|------------|------|-------------|
| MediaMTX | Go RTSP Server | 8554 (RTSP), 9997 (API), 8888 (HLS), 8889 (WebRTC), 1935 (RTMP) | Stream ingestion, fMP4 recording |
| Pipeline Engine | Python + TensorRT | — | NVDEC decode, face/person detection, ArcFace recognition, YOLO tracking, ReID |
| Backend API | FastAPI + Uvicorn | 8000 | REST API, WebSocket metadata stream, static file serving |
| Frontend | Vanilla JS + Canvas | 3000 (dev) / 8000 (prod) | Camera overlay UI, real-time attendance display |
| Database | SQLite (WAL mode) | — | Attendance records, evidence URIs |
| Storage Services | Python async | — | SnapshotSaver, ClipExtractor, RetentionService, DiskWatchdog |

---

## 2. Cold-Start Procedure

### 2.1 Prerequisites
- Windows 11 with latest updates
- NVIDIA GTX 1660 Ti (6GB VRAM) with driver ≥ 535.x
- CUDA Toolkit 12.x
- Python 3.12+ in `.venv2` virtual environment
- FFmpeg 6.x in PATH
- MediaMTX binary in `mediamtx/mediamtx.exe`

### 2.2 Environment Setup
```powershell
# Activate virtual environment
.\.venv2\Scripts\Activate.ps1

# Verify CUDA availability
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Verify FFmpeg
ffmpeg -version

# Verify MediaMTX
.\mediamtx\mediamtx.exe --version
```

### 2.3 Configuration
1. Copy production config template:
```powershell
copy config\default.yaml config\production.yaml
```

2. Edit `config\production.yaml` with production values:
   - Camera RTSP URLs
   - Database path
   - Evidence storage paths
   - Retention policies
   - Notification webhook URLs (from environment variables)

3. Create `.env` file from template (NOT committed to git):
```powershell
copy .env.example .env
# Edit .env with actual credentials:
# - ZALO_OA_SECRET
# - ESMS_API_KEY / SPEEDSMS_API_KEY
# - TELEGRAM_BOT_TOKEN
# - WEBHOOK_SIGNATURE_SECRET
```

### 2.4 One-Command Startup
```powershell
# Production startup (recommended)
.\bootstrap.bat

# Or direct Python (for debugging)
python bootstrap.py --config config\production.yaml
```

### 2.5 Startup Sequence (bootstrap.py orchestrates)
1. **Environment Validation** — CUDA, models, FFmpeg, disk space
2. **MediaMTX Start** — RTSP server with fMP4 recording enabled
3. **Storage Services** — SnapshotSaver, ClipExtractor, RetentionService, DiskWatchdog
4. **Pipeline Engine** — TensorRT engine initialization, camera connections
5. **Backend API** — Uvicorn server on 127.0.0.1:8000
6. **Health Checks** — All endpoints responding, cameras RUNNING

### 2.6 Verification Commands
```powershell
# Health endpoint
curl http://127.0.0.1:8000/health

# Metrics endpoint
curl http://127.0.0.1:8000/metrics

# MediaMTX API
curl http://127.0.0.1:9997/v3/paths/list

# Check recordings
dir recordings\cam1
dir recordings\cam2

# Check evidence
dir app\static\evidence\snapshots
dir app\static\evidence\clips
```

---

## 3. Daily Operational Checks

### 3.1 Morning Checklist (Run at start of day)
- [ ] System running: `bootstrap.bat` process active
- [ ] Both cameras RUNNING: Check `/health` endpoint
- [ ] MediaMTX recording: New fMP4 segments in `recordings/cam1/`, `recordings/cam2/`
- [ ] GPU VRAM: < 2.2 GB (check `/metrics` or nvidia-smi)
- [ ] Disk space: > 20% free on evidence and recording volumes
- [ ] Database integrity: `sqlite3 app/data/attendance.db "PRAGMA integrity_check;"` returns `ok`
- [ ] Notification dispatch: Check logs for successful ZNS/SMS/Telegram sends

### 3.2 Health Monitoring Endpoints
| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /health` | Overall system health | `{"status": "healthy", "cameras": {"cam1": "RUNNING", "cam2": "RUNNING"}, "vram_mb": 1850}` |
| `GET /metrics` | Prometheus metrics | Pipeline FPS, VRAM, queue depths, event counts |
| `GET /api/attendance/stats` | Attendance statistics | Daily counts, by camera, by direction |
| `GET /api/storage/status` | Storage services status | Retention, disk watchdog, backup status |

### 3.3 Key Metrics to Monitor
| Metric | Warning Threshold | Critical Threshold |
|--------|-------------------|---------------------|
| Camera FPS | < 27 FPS | < 25 FPS |
| GPU VRAM Reserved | > 2.0 GB | > 2.2 GB |
| Frame Drops | > 0 | > 0 |
| Disk Usage | > 80% | > 90% |
| DB Lock Errors | > 0/hour | > 0 |
| Notification Failures | > 5% | > 10% |

---

## 4. Storage Capacity Planning

### 4.1 Disk Growth Estimates (Per Camera, Per Day)

| Stream Config | Bitrate | fMP4 Recording | Snapshots | Clips (30s/event) | Total/Day |
|---------------|---------|----------------|-----------|-------------------|-----------|
| 4K @ 30fps H.264 | 8 Mbps | ~86 GB | ~50 MB (100 events) | ~1.5 GB (50 events) | **~88 GB** |
| 1080p @ 30fps H.264 | 4 Mbps | ~43 GB | ~50 MB | ~750 MB | **~44 GB** |
| 720p @ 30fps H.264 | 2 Mbps | ~21 GB | ~50 MB | ~375 MB | **~22 GB** |

### 4.2 Retention Policies (Configured in `config/production.yaml`)
```yaml
storage:
  retention:
    recordings:
      max_age_days: 30
      preserve_recent: 7
    snapshots:
      max_age_days: 90
      preserve_recent: 30
    clips:
      max_age_days: 90
      preserve_recent: 30
    database_backups:
      max_age_days: 30
      preserve_recent: 7
```

### 4.3 Disk Watchdog Thresholds
- **Warning:** 80% disk usage → Log alert
- **Critical:** 90% disk usage → Emergency purge oldest recordings (preserves snapshots/clips)
- **Emergency:** 95% disk usage → Aggressive purge, reduce recording quality

### 4.4 Recommended Minimum Disk
| Deployment | Cameras | Retention | Minimum SSD |
|------------|---------|-----------|-------------|
| Small School | 2 | 30 days | 2 TB |
| Medium School | 4 | 30 days | 4 TB |
| Large Campus | 8 | 30 days | 8 TB |

---

## 5. Backup, Restore & Disaster Recovery

### 5.1 Automated Backups (Built-in)
- **Database:** Hourly SQLite backup via `DatabaseMaintenance` (WAL-safe)
- **Configuration:** Version-controlled in git
- **Models:** Stored separately (not in repo)

### 5.2 Manual Backup Procedure
```powershell
# 1. Stop system gracefully
# Ctrl+C in bootstrap terminal, wait for clean shutdown (< 5s)

# 2. Backup database
copy app\data\attendance.db backups\attendance_$(Get-Date -Format "yyyyMMdd_HHmmss").db

# 3. Backup evidence (optional, large)
robocopy app\static\evidence backups\evidence_$(Get-Date -Format "yyyyMMdd") /MIR

# 4. Backup recordings (optional, very large)
robocopy recordings backups\recordings_$(Get-Date -Format "yyyyMMdd") /MIR

# 5. Restart system
.\bootstrap.bat
```

### 5.3 Restore Procedure
```powershell
# 1. Stop system
# 2. Restore database
copy backups\attendance_20261010_060000.db app\data\attendance.db

# 3. Verify integrity
sqlite3 app/data/attendance.db "PRAGMA integrity_check;"

# 4. Restore evidence/recordings if needed
robocopy backups\evidence_20261010 app\static\evidence /MIR

# 5. Start system
.\bootstrap.bat
```

### 5.4 Disaster Recovery Scenarios

| Scenario | RTO | RPO | Procedure |
|----------|-----|-----|-----------|
| Database corruption | 15 min | 1 hour | Restore from latest hourly backup |
| Disk failure (recordings) | 30 min | 24 hours | Replace disk, restore from offsite backup |
| GPU failure | 2 hours | 0 | Replace GPU, reinstall drivers, restart |
| Complete server loss | 4 hours | 24 hours | Provision new server, restore from backups |

---

## 6. Common Failure Modes & Remediation

### 6.1 Camera Connection Issues

| Symptom | Cause | Remediation |
|---------|-------|-------------|
| Camera state `CONNECTING` > 30s | Network/RTSP unreachable | Check camera IP, ping, RTSP port 554, credentials |
| Camera state `RECONNECTING` | Stream interruption | Check network stability, camera health, MediaMTX logs |
| `decode_errors` > 0 | Corrupt stream/keyframe issues | Restart camera stream, check GOP settings |

**Quick Fix:**
```powershell
# Restart specific camera via API
curl -X POST http://127.0.0.1:8000/api/cameras/cam1/restart
```

### 6.2 GPU/VRAM Issues

| Symptom | Cause | Remediation |
|---------|-------|-------------|
| VRAM > 2.2 GB | Memory leak / too many models | Restart pipeline engine, check TensorRT engine singleton |
| `CUDA_OUT_OF_MEMORY` | Batch size too large | Reduce `max_batch_size` in config, restart |
| FPS drops suddenly | Thermal throttling | Check GPU temp (`nvidia-smi`), clean fans, reduce load |

### 6.3 Database Lock Contention

| Symptom | Cause | Remediation |
|---------|-------|-------------|
| `database is locked` errors | Concurrent writers | Verify only Legacy Backend writes; check WAL mode |
| Slow queries | Missing indexes / large DB | Run `VACUUM`, check indexes, consider archiving old data |

**Diagnostic:**
```powershell
sqlite3 app/data/attendance.db "PRAGMA journal_mode; PRAGMA busy_timeout; PRAGMA integrity_check;"
```

### 6.4 MediaMTX Recording Issues

| Symptom | Cause | Remediation |
|---------|-------|-------------|
| No fMP4 segments | Recording not enabled | Check `mediamtx.yml` `record: yes` for paths |
| Segments not playable | Incomplete segments | Wait for segment finalization (60s), check `recordPartDuration` |
| Disk full | Retention not running | Check `DiskWatchdog` and `RetentionService` logs |

### 6.5 Notification Failures

| Channel | Common Issues | Debug Commands |
|---------|---------------|----------------|
| Zalo ZNS | Invalid OA secret, template rejected | Check `.env` ZALO_OA_SECRET, verify template ID |
| SMS (eSMS/SpeedSMS) | Insufficient balance, invalid API key | Check API key, account balance, sender ID registration |
| Telegram | Bot token invalid, chat ID wrong | Test with `curl -X POST https://api.telegram.org/bot<TOKEN>/sendMessage` |

---

## 7. Log Interpretation Guide

### 7.1 Log Locations
| Component | Log Location |
|-----------|--------------|
| Bootstrap/Orchestrator | Console output (stdout/stderr) |
| Pipeline Engine | Console + `logs/pipeline.log` |
| Backend API | Console + `logs/backend.log` |
| MediaMTX | Console + `mediamtx/mediamtx.log` |
| Storage Services | Console + `logs/storage.log` |

### 7.2 Key Log Patterns

**Normal Operation:**
```
[INFO] Camera cam1 state: RUNNING
[INFO] SOAK [300s] cam1: fps=28.5 frames=8550 drops=0 VRAM=1850MB
[INFO] Attendance event recorded: cam1, track_123, in, confidence=0.95
[INFO] Snapshot saved: /static/evidence/snapshots/evt_123_face.jpg
[INFO] Clip extracted: /static/evidence/clips/evt_123.mp4
[INFO] Notification sent: ZNS to 090****123
```

**Warning Patterns:**
```
[WARNING] cam1 FPS below 27: 25.2
[WARNING] VRAM approaching limit: 2100MB / 2252MB
[WARNING] Disk usage 85% - retention may trigger
[WARNING] Notification retry: ZNS failed, attempt 2/3
```

**Error Patterns (Require Action):**
```
[ERROR] FRAME DROPS DETECTED: 15
[ERROR] VRAM EXCEEDED: 2300MB > 2252MB
[ERROR] Database locked after 5s timeout
[ERROR] MediaMTX process exited unexpectedly
[ERROR] CUDA_OUT_OF_MEMORY in TensorRT inference
```

---

## 8. Rapid Remediation Commands

### 8.1 Service Restart (No Full Reboot)
```powershell
# Restart backend only
# In bootstrap terminal: Ctrl+C, then restart backend service

# Restart pipeline engine only
curl -X POST http://127.0.0.1:8000/api/admin/pipeline/restart

# Restart MediaMTX only
# Kill MediaMTX process, bootstrap will restart it (if supervised)
```

### 8.2 Emergency Procedures

**Emergency Stop (Preserves Data):**
```powershell
# In bootstrap terminal: Ctrl+C
# Wait for "Graceful shutdown completed" (< 5s)
# All processes terminated cleanly
```

**Force Kill (If Graceful Fails):**
```powershell
# Find and kill all related processes
taskkill /F /IM mediamtx.exe
taskkill /F /IM python.exe
# Then restart with bootstrap.bat
```

**Clear Stuck Recordings:**
```powershell
# Stop system
# Remove incomplete segments
Remove-Item recordings\cam1\*.part -Force
Remove-Item recordings\cam2\*.part -Force
# Restart
```

---

## 9. Configuration Reference

### 9.1 Production Config (`config/production.yaml`)
```yaml
# Critical production settings
pipeline:
  tensorrt:
    workspace_size_mb: 1024
    fp16_mode: true
    max_batch_size: 1
  
  cameras:
    cam1:
      rtsp_url: "rtsp://camera1:554/stream1"
      resolution: [3840, 2160]
      fps: 30
    cam2:
      rtsp_url: "rtsp://camera2:554/stream1"
      resolution: [3840, 2160]
      fps: 30

storage:
  evidence_path: "app/static/evidence"
  recordings_path: "recordings"
  retention: *as_above*
  disk_watchdog:
    check_interval_seconds: 60
    warning_threshold_pct: 80
    critical_threshold_pct: 90
    emergency_threshold_pct: 95

backend:
  host: "127.0.0.1"  # CRITICAL: Never 0.0.0.0 in production
  port: 8000
  workers: 1
  log_level: "info"

notifications:
  zns:
    enabled: true
    endpoint: "https://business.openapi.zalo.me/message/template"
  sms:
    enabled: true
    provider: "esms"  # or speedsms
  telegram:
    enabled: true
  cooldown_seconds: 300  # Anti-spam
```

### 9.2 Environment Variables (`.env`)
```bash
# Required - Never commit these
ZALO_OA_SECRET=your_zalo_oa_secret
ZALO_TEMPLATE_ID=your_template_id
ESMS_API_KEY=your_esms_key
ESMS_SECRET_KEY=your_esms_secret
SPEEDSMS_API_KEY=your_speedsms_key
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
WEBHOOK_SIGNATURE_SECRET=your_webhook_secret

# Optional - System config
LOG_LEVEL=info
CUDA_VISIBLE_DEVICES=0
```

---

## 10. Security Hardening Checklist

### 10.1 Pre-Deployment
- [ ] `.env` file created with production secrets (NOT in git)
- [ ] `.gitignore` contains `.env`, `.env.*`, `data/`, `recordings/`, `logs/`
- [ ] All API keys rotated from development values
- [ ] Database WAL mode enabled (`PRAGMA journal_mode=WAL;`)
- [ ] Backend binds to `127.0.0.1` only (not `0.0.0.0`)
- [ ] MediaMTX API binds to `127.0.0.1:9997` (configure in `mediamtx.yml`)
- [ ] HTTPS/TLS configured for external access (reverse proxy)
- [ ] Firewall rules: Only necessary ports open (8000, 8554, 8888, 8889, 1935)

### 10.2 Runtime Security
- [ ] Log redaction active (phone numbers masked as `090****123`)
- [ ] No secrets in log output
- [ ] Database file permissions: `600` (owner read/write only)
- [ ] Evidence directory permissions: `700`
- [ ] Regular secret rotation schedule (quarterly)

---

## 11. Upgrade & Maintenance Procedures

### 11.1 Rolling Update (Zero Downtime for API)
```powershell
# 1. Pull latest code
git pull origin main

# 2. Update dependencies
.\.venv2\Scripts\pip install -r requirements.txt

# 3. Run migrations if any
python -m app.attendance.migrations.run_migrations

# 4. Graceful restart backend only
curl -X POST http://127.0.0.1:8000/api/admin/restart

# 5. Verify health
curl http://127.0.0.1:8000/health
```

### 11.2 Full Restart (Required for Pipeline Changes)
```powershell
# 1. Stop gracefully
# Ctrl+C in bootstrap terminal

# 2. Update code/dependencies
git pull origin main
.\.venv2\Scripts\pip install -r requirements.txt

# 3. Run migrations
python -m app.attendance.migrations.run_migrations

# 4. Start
.\bootstrap.bat
```

### 11.3 Model Updates
```powershell
# 1. Replace model files in models/ (scrfd, arcface, landmark, reid, yolo)
# 2. Update model versions in config
# 3. Full restart required (TensorRT engine rebuild)
```

---

## 12. Contact & Escalation

### 12.1 Support Tiers
| Tier | Response Time | Contact |
|------|---------------|---------|
| P0 - System Down | 15 min | On-call engineer + Team lead |
| P1 - Degraded Performance | 1 hour | On-call engineer |
| P2 - Non-critical Issue | 4 hours | Team Slack / Email |
| P3 - Enhancement | Next sprint | GitHub Issues |

### 12.2 Key Contacts
- **System Architect:** [Name/Contact]
- **DevOps Lead:** [Name/Contact]
- **ML Engineer:** [Name/Contact]
- **Vendor (Camera/NVR):** [Vendor Support Info]

---

## 13. Appendices

### Appendix A: Port Reference
| Port | Service | Protocol | Binding | External Access |
|------|---------|----------|---------|-----------------|
| 8000 | Backend API | HTTP/WS | 127.0.0.1 | Via reverse proxy |
| 8554 | MediaMTX RTSP | RTSP | 0.0.0.0 | Camera publishers only |
| 9997 | MediaMTX API | HTTP | 127.0.0.1 | Internal only |
| 8888 | MediaMTX HLS | HTTP | 0.0.0.0 | Frontend playback |
| 8889 | MediaMTX WebRTC | HTTP | 0.0.0.0 | Frontend playback |
| 1935 | MediaMTX RTMP | RTMP | 0.0.0.0 | Stream publishers |

### Appendix B: Directory Structure
```
AI_ATTENDANCE/
├── bootstrap.py / bootstrap.bat      # Orchestration entry point
├── config/
│   ├── default.yaml                  # Base configuration
│   └── production.yaml               # Production overrides
├── mediamtx/
│   ├── mediamtx.exe                  # RTSP server binary
│   └── mediamtx.yml                  # MediaMTX configuration
├── pipeline_engine/                  # Core AI pipeline
├── app/
│   ├── attendance/                   # Legacy backend (DB writes)
│   ├── storage/                      # Evidence storage services
│   ├── backend/                      # FastAPI application
│   ├── frontend/                     # Static web assets
│   ├── data/
│   │   └── attendance.db             # SQLite database (WAL)
│   └── static/evidence/              # Served snapshots/clips
├── recordings/
│   ├── cam1/                         # fMP4 segments
│   └── cam2/
├── models/                           # AI models (gitignored)
├── logs/                             # Application logs
├── tests/                            # Test suites
├── artifacts/                        # Phase deliverables
├── docs/                             # Documentation
└── .env                              # Secrets (gitignored)
```

### Appendix C: Phase 18 Certification Evidence
All Phase 18 deliverables in `artifacts/phase_18/`:
- `00_phase18_preflight.md` — Architecture inventory & hardware state
- `01_golden_soak_600s_report.md` — 600s soak test telemetry
- `02_database_integrity_audit.md` — Concurrency stress results
- `03_security_and_secrets_audit.md` — Redaction & credential scan
- `04_production_readiness_checklist.md` — 25-point verification matrix
- `PRODUCTION_RUNBOOK.md` — This document
- `PHASE_18_FINAL_REPORT.md` — Executive sign-off

---

## 14. Sign-Off

**Certification Authority:** AI Attendance System Engineering  
**Date:** 2026-10-10  
**Platform:** Windows 11, NVIDIA GTX 1660 Ti (6GB VRAM)  
**Git Commit:** [Current working tree]

### Production Readiness Certification
> **PRODUCTION_READY** — The AI Attendance System has passed all Phase 18 acceptance criteria:
> - 600-second golden soak test: ≥25 FPS/camera, VRAM < 2.2 GB, 0 frame drops, 100% evidence fidelity
> - Database integrity: Zero locks, zero corruptions, WAL mode verified, authority boundaries enforced
> - Security audit: Zero credential leaks, logging redaction verified, network isolation confirmed
> - Production runbook complete with all operational procedures

**Approved By:** _________________________  
**Date:** _________________________

---

*End of Production Runbook*