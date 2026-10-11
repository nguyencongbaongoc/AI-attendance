# Gates A–C Verdicts

**Date:** 2026-10-04  
**Phase:** 0.2.2  
**Classification:** SOURCE-VERIFIED / RUNTIME-VERIFIED

---

## Gate A: Database Containment and Authority (CF-01) — PASS

### Verdict: PASS

### Summary
Both `attendance.db` instances inspected and writers identified. Authoritative database established as `app/data/attendance.db` (108 records, production data). Secondary `data/attendance.db` (18 records, benchmark only) preserved. No records lost, merged, or overwritten. WAL state valid.

### Evidence
- **Authoritative DB:** `app/data/attendance.db` — 108 records, Phase 22-25 provenance, real 2026 timestamps
- **Secondary DB:** `data/attendance.db` — 18 records, benchmark only, timestamps 6-100s
- **Both WAL/SHM:** Checkpointed (WAL=0 bytes), SHM=32KB active
- **Ownership:** Legacy Backend `AttendanceStorage` → `AttendanceRepository` chain
- **No data loss:** Both databases intact, distinct SHA256

### Acceptance Criteria Met
- ✅ `app/data/attendance.db` verified as sole authoritative
- ✅ Ownership proven by source + runtime
- ✅ All unintended writers identified (CWD-dependent path resolution)
- ✅ Secondary database preserved
- ✅ No records lost/merged/overwritten
- ✅ WAL state valid
- ⚠️ Silent secondary recreation possible (addressed in Gate B)

---

## Gate B: Deterministic Database Path Resolution (CF-02) — PASS

### Verdict: PASS

### Summary
All Legacy Backend database paths made CWD-independent by resolving from module `__file__` location (repository root). No accidental secondary database creation possible.

### Changes Made
1. **`app/config/settings.py`** — Added `_get_repository_root()` using `Path(__file__).resolve().parent.parent.parent`. Updated `PathsConfig`, `ModelsConfig`, and supporting DB configs to use repository-root-relative paths.
2. **`app/attendance/storage.py`** — Added `_get_attendance_db_path()` returning canonical `app/data/attendance.db`. Changed `StorageConfig.database_path` from `str` to `Path` with `field(default_factory=...)`.

### Verification
| Path | Resolved To |
|---|---|
| `settings.paths.data_dir` | `<repo>/app/data` |
| `StorageConfig.database_path` | `<repo>/app/data/attendance.db` |
| Supporting DBs | `<repo>/app/data/*.db` |

### Startup Context Tests
All contexts resolve to same authoritative DB:
- Project root ✅
- `app/` directory ✅  
- `pipeline_engine/` directory ✅
- Any CWD ✅ (import-time fixed)

### Acceptance Criteria Met
- ✅ All startup contexts resolve same authoritative database
- ✅ No accidental `data/attendance.db` created
- ✅ CWD-independent resolution implemented
- ✅ Legacy Backend starts correctly
- ✅ No silent secondary database possible

---

## Gate C: Safe Runtime Recovery (CF-04) — PASS

### Verdict: PASS

### Summary
All dangerous recovery instructions from `16_blockers_and_recovery_plan.md` identified and replaced with safe, process-specific, SQLite-aware procedures.

### Dangerous Instructions Removed
| Original | Risk |
|---|---|
| `taskkill /F /IM python.exe` | Kills ALL Python processes |
| `del *.db-wal` / `del *.db-shm` | Corrupts SQLite databases |
| Broad `taskkill /F /IM mediamtx.exe` | Force kill without grace |
| Unverified CWD startup | Perpetuates dual DB bug |

### Safe Replacements Implemented
1. **Process Identification** — `Get-ProjectProcesses` by PID/CommandLine/Port/CWD
2. **Graceful Shutdown** — SIGTERM/API first, wait, force only if needed
3. **WAL/SHM Preservation** — Never delete; integrity checks instead
3. **Database Integrity Verification** — `PRAGMA integrity_check` before/after
4. **Explicit CWD** — `cd <REPO_ROOT>` before backend start
5. **Readiness Gates** — MediaMTX API, Backend `/health/ready` polling

### Documentation
- Deprecated original sections in `16_blockers_and_recovery_plan.md`
- Created safe recovery procedures in `04_recovery_safety_remediation.md`

### Acceptance Criteria Met
- ✅ Dangerous `taskkill /F /IM python.exe` removed
- ✅ Dangerous `del *.db-wal`/`del *.db-shm` removed
- ✅ Broad process kills replaced with PID-specific
- ✅ Graceful shutdown procedures documented
- ✅ Database integrity verification included
- ✅ Readiness gates implemented
- ✅ Explicit CWD for backend startup
- ✅ No silent secondary DB creation (Gate B)

---

## Overall Gates A–C Status

| Gate | Status | Critical Findings Resolved |
|---|---|---|
| A | ✅ PASS | CF-01 |
| B | ✅ PASS | CF-02 |
| C | ✅ PASS | CF-04 |

**Gates A–C COMPLETE. Proceeding to Gates D–E.**