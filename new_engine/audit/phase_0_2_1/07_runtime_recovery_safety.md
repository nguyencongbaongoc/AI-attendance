# Phase 0.2.1 — Runtime Recovery Procedure Safety Audit

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED

---

## 1. Executive Summary

**Audit of `16_blockers_and_recovery_plan.md` reveals multiple DANGEROUS recovery instructions** that could cause data loss, process corruption, or system instability. Key issues: broad process kills (`taskkill /F /IM python.exe`), WAL/SHM file deletion, unverified working-directory assumptions, and duplicate service startup risks.

---

## 2. Dangerous Instructions Inventory

### 2.1 MediaMTX Recovery (§3.1)

| Line | Instruction | Risk | Impact |
|------|-------------|------|--------|
| 77 | `taskkill /F /IM mediamtx.exe` | FORCE KILL without graceful shutdown | MediaMTX may not flush RTSP buffers; clients disconnected abruptly |

**Safe Replacement:**
```bash
# 1. Identify exact process
Get-Process -Name mediamtx | Select-Object Id, Path, CommandLine
# 2. Graceful shutdown via MediaMTX API
curl -X POST http://localhost:9997/v3/paths/close/...  # if supported
# 3. If API unavailable, SIGTERM equivalent
Stop-Process -Id <PID> -Force:$false
# 4. Wait for exit, then force if needed
Start-Sleep 5; if (Get-Process -Id <PID> -ErrorAction SilentlyContinue) { Stop-Process -Id <PID> -Force }
```

---

### 2.2 Legacy Backend Recovery (§3.2) — CRITICAL ISSUES

| Line | Instruction | Risk | Impact |
|------|-------------|------|--------|
| 88-90 | `Get-Process | Where-Object {$_.ProcessName -like "*python*"}` then `taskkill /PID <pid> /F` | **KILLS ALL PYTHON PROCESSES** including PipelineEngine, test runners, venv scripts | Complete AI pipeline termination; potential database corruption from interrupted writes |
| 92-93 | `del data\attendance.db-shm` / `del data\attendance.db-wal` | **DELETES WAL/SHM FILES** | **DATA LOSS RISK** — WAL contains uncommitted transactions; deleting it corrupts database |
| 95 | Startup command with `sys.path.insert(0, '.')` | Unverified CWD assumption | May start with wrong CWD → wrong `data_dir` → wrong database |

**Safe Replacement:**
```bash
# 1. Identify EXACT Legacy Backend process
Get-Process -Name python | Where-Object { $_.CommandLine -like "*app.main*" } | Select-Object Id, CommandLine, Path
# 2. Verify it's the correct process (check port 19146)
netstat -ano | findstr :19146
# 3. Graceful shutdown via API
curl -X POST http://localhost:19146/api/v1/admin/shutdown  # if implemented
# 4. Or SIGTERM equivalent
Stop-Process -Id <PID> -Force:$false
# 5. Wait for clean exit (WAL checkpoint)
Start-Sleep 10
# 6. Verify database integrity BEFORE restart
python -c "import sqlite3; conn=sqlite3.connect('file:app/data/attendance.db?mode=ro', uri=True); print(conn.execute('PRAGMA integrity_check').fetchone())"
# 7. NEVER delete .db-wal or .db-shm files
```

---

### 2.3 Camera Stream Recovery (§3.3)

| Line | Instruction | Risk | Impact |
|------|-------------|------|--------|
| 106 | `netstat -an | findstr :1935` | Low — read-only | Acceptable |
| 108 | "Restart publishers (FFmpeg/camera)" | Vague — no specific procedure | May start duplicate publishers |

**Safe Replacement:** Document exact publisher startup commands with verified paths.

---

### 2.4 Full Stack Recovery (Clean Slate) (§3.4) — CRITICAL ISSUES

| Line | Instruction | Risk | Impact |
|------|-------------|------|--------|
| 116 | `taskkill /F /IM python.exe 2>nul  # CAUTION: kills all Python` | **EXPLICITLY ACKNOWLEDGES KILLING ALL PYTHON** | Terminates PipelineEngine, monitoring, tests, venv scripts — **UNACCEPTABLE** |
| 119-122 | `del data\*.db-shm`, `del data\*.db-wal`, `del app\data\*.db-shm`, `del app\data\*.db-wal` | **DELETES ALL WAL/SHM FILES** | **CATASTROPHIC DATA LOSS** — corrupts ALL SQLite databases |
| 125 | `Start-Process .\mediamtx.exe -Args ".\mediamtx.yml" -WindowStyle Hidden` | No readiness verification | MediaMTX may not be ready when backend starts |
| 128 | Backend startup with `sys.path.insert(0, '.')` | CWD-dependent | Same dual-database bug |

**Safe Replacement:**
```bash
# 1. Identify and gracefully stop EACH service by PID
$services = @(
    @{ Name="MediaMTX"; ProcessName="mediamtx"; Port=8554 },
    @{ Name="LegacyBackend"; CommandLine="*app.main*"; Port=19146 },
    @{ Name="PipelineEngine"; CommandLine="*pipeline_engine*"; Port=0 }
)

foreach ($svc in $services) {
    $proc = Get-Process | Where-Object { 
        ($_.ProcessName -eq $svc.ProcessName) -or ($_.CommandLine -like $svc.CommandLine)
    }
    if ($proc) {
        Stop-Process -Id $proc.Id -Force:$false
        Start-Sleep 5
        if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {
            Stop-Process -Id $proc.Id -Force
        }
    }
}

# 2. PRESERVE WAL/SHM — NEVER DELETE
# 3. Verify database integrity
python -c "
import sqlite3, glob
for db in glob.glob('app/data/*.db') + glob.glob('data/*.db'):
    try:
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        result = conn.execute('PRAGMA integrity_check').fetchone()
        print(f'{db}: {result[0]}')
    except Exception as e:
        print(f'{db}: ERROR - {e}')
"

# 4. Start MediaMTX with readiness wait
cd mediamtx; Start-Process .\mediamtx.exe -Args ".\mediamtx.yml"
# Wait for API ready
for ($i=0; $i -lt 30; $i++) { 
    try { curl -s http://localhost:9997/v3/paths/list | ConvertFrom-Json; break } 
    catch { Start-Sleep 1 } 
}

# 5. Start Legacy Backend with EXPLICIT CWD
cd <PROJECT_ROOT>
.venv2\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.');
from app.main import create_app;
import uvicorn;
uvicorn.run(create_app(), host='0.0.0.0', port=19146)
"

# 6. Verify ALL health endpoints
.venv2\Scripts\python.exe bootstrap.py --check
```

---

## 3. Summary of Risky Patterns

| Pattern | Occurrences | Severity |
|---------|-------------|----------|
| `taskkill /F /IM python.exe` | 2 (lines 90, 116) | **CRITICAL** — kills all Python processes |
| `taskkill /F /IM mediamtx.exe` | 1 (line 77) | HIGH — force kill without grace |
| `del *.db-wal` / `del *.db-shm` | 4 (lines 92-93, 119-122) | **CRITICAL** — database corruption |
| Unverified CWD assumption | 2 (lines 95, 128) | HIGH — causes dual database bug |
| No readiness verification | 3 (lines 79, 125, 128) | MEDIUM — race conditions |
| Vague "restart publishers" | 1 (line 108) | LOW — incomplete procedure |

---

## 4. Safe Recovery Procedure Framework

### 4.1 Principles

1. **Identify by PID + CommandLine + Port** — never by process name alone
2. **Graceful shutdown first** — SIGTERM / API shutdown, wait, then force
3. **PRESERVE WAL/SHM** — never delete; they contain uncommitted data
4. **Verify database integrity** before and after restart
5. **Explicit CWD** — always `cd <PROJECT_ROOT>` before starting backend
6. **Readiness gates** — wait for health endpoints before dependent services

### 4.2 Required Recovery Procedures for Phase 1

| Procedure | Required Gates |
|-----------|----------------|
| MediaMTX restart | API `/v3/paths/list` shows `live/cam1` and `live/cam2` ready |
| Legacy Backend restart | `/api/v1/health/ready` returns `status: ready` with all checks true |
| PipelineEngine restart | All 3 model sessions initialize on CUDA EP |
| Full stack restart | All 3 services healthy + bootstrap check passes |

---

## 5. Verdict

**Phase 0.2 recovery procedures are UNSAFE FOR PRODUCTION USE.** They contain:
- Commands that destroy data (WAL/SHM deletion)
- Commands that kill unrelated processes (broad `taskkill /F /IM python.exe`)
- Unverified assumptions causing the dual-database bug
- No readiness verification

**These must be REPLACED before Phase 1** with the safe procedures outlined above.

---

**End of Runtime Recovery Safety Audit**