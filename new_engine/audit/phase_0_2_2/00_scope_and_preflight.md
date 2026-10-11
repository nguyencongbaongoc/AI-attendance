# Phase 0.2.2 — Scope and Preflight

**Date:** 2026-10-04  
**Phase:** 0.2.2 — Critical Findings Remediation  
**Previous Phase:** 0.2.1 — Forensic Closeout (VERDICT: PARTIAL)  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main  
**Git Status:** 2000+ deleted files (D), 2 untracked directories (UI/, new_engine/, pipeline_engine/)

---

## 1. Mission

Execute controlled remediation of five Critical Findings from Phase 0.2.1:

| ID | Finding | Target |
|---|---|---|
| CF-01 | Dual active attendance.db instances | Gate A |
| CF-02 | CWD-dependent database path resolution | Gate B |
| CF-03 | Missing 4 Legacy Backend API endpoints | Gate E |
| CF-04 | Unsafe recovery procedures | Gate C |
| CF-05 | Incomplete quarantine manifest/rollback | Gate D |

---

## 2. Repository Baseline (Pre-Remediation)

### 2.1 Git State

```
Repository root: C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE
Branch: main
HEAD: 5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline
Git status: 2000+ deleted files (D), untracked: UI/, bootstrap.bat, bootstrap.py, check_dbs.py, new_engine/, pipeline_engine/
```

### 2.2 Database State (from Phase 0.2.1)

| Database | Path | Records | WAL Active | Classification |
|---|---|---|---|---|
| Authoritative | `app/data/attendance.db` | 108 | ✅ YES | AUTHORITATIVE |
| Active Secondary | `data/attendance.db` | 18 | ✅ YES | ACTIVE SECONDARY |
| PipelineEngine | `data/attendance_events.db` | 0 | ❌ NO | PipelineEngine-owned |

### 2.3 Quarantine State

- Location: `new_engine/audit/phase_0_2/quarantine/`
- 5,343 files, 7.53 GB (per Phase 0.2.1)
- Contains misclassified Agent Manager worktree with vendor SDKs

### 2.4 Runtime State (from Phase 0.2)

- MediaMTX: Running (ports 8554/1935/9997/8888/8889/8890)
- Legacy Backend: Running on port 19146
- Camera 1/2: RTSP decode verified
- Both attendance.db instances have active WAL/SHM

---

## 3. Safety Baseline

### 3.1 Protected Assets (Never Touch)

- `.venv2/` — Python environment
- `app/data/` — Attendance DB, enrollment embeddings
- `models/` — All ONNX/PT models
- `mediamtx/mediamtx.exe`, `mediamtx.yml` — MediaMTX runtime
- `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/` — Vendor SDKs
- `.git/` — Git metadata
- Both `attendance.db` instances — Preserve both datasets

### 3.2 Forbidden Operations

- `taskkill /F /IM python.exe` — Broad process kill
- `del *.db-wal` / `del *.db-shm` — WAL/SHM deletion
- `git reset` / `git clean` / `git restore` — Git history modification
- Force-kill MediaMTX or Legacy Backend
- Schema migrations without ownership verification
- Copy active SQLite databases via file copy

---

## 4. Execution Model: Five Gates

| Gate | Target | Depends On |
|---|---|---|
| A | Database Containment & Authority (CF-01) | — |
| B | Deterministic Path Resolution (CF-02) | A |
| C | Safe Runtime Recovery (CF-04) | A, B |
| D | Quarantine Integrity & Rollback (CF-05) | A, B, C |
| E | Legacy Backend API Contracts (CF-03) | A, B, C, D |

**Gate Order:** A → B → C → D → E

---

## 5. Acceptance Criteria per Gate

### Gate A — PASS if:
- `app/data/attendance.db` verified as sole authoritative attendance database
- Ownership proven by source + runtime evidence
- All unintended writers identified
- Secondary database preserved
- No records lost/merged/overwritten
- WAL state valid
- No silent secondary database recreation possible

### Gate B — PASS if:
- All startup contexts resolve same authoritative database
- No accidental `data/attendance.db` created
- CWD-independent resolution implemented

### Gate C — PASS if:
- Dangerous recovery instructions removed/replaced
- PID-specific graceful shutdown procedures tested
- WAL/SHM preserved
- No broad destructive commands in active docs

### Gate D — PASS if:
- Complete SHA256 manifest exists
- No unexplained missing files
- Agent Manager worktree correctly classified
- Critical user data not disposable
- Restoration tests pass for all categories

### Gate E — PASS if:
- Four API areas implemented or blockers documented
- Tests prove correct integration
- Attendance authority unchanged (Phase 22-25 resolver authoritative)

---

## 6. Evidence Classification

Every claim must be tagged:

| Classification | Meaning |
|---|---|
| SOURCE-VERIFIED | Direct source code inspection |
| STATIC-ANALYSIS | Tool-based analysis |
| UNIT-TESTED | Unit test execution |
| INTEGRATION-TESTED | Integration test execution |
| RUNTIME-VERIFIED | Live runtime observation |
| NOT-VERIFIED | Not yet examined |

---

## 7. Artifacts to Create

`new_engine/audit/phase_0_2_2/`

| # | File | Gate |
|---|---|---|
| 00 | `00_scope_and_preflight.md` | — |
| 01 | `01_database_containment.md` | A |
| 02 | `02_database_path_remediation.md` | B |
| 03 | `03_database_authority_proof.md` | A |
| 04 | `04_recovery_safety_remediation.md` | C |
| 05 | `05_quarantine_sha256_manifest.csv` | D |
| 06 | `06_quarantine_classification.md` | D |
| 07 | `07_rollback_verification.md` | D |
| 08 | `08_api_contracts.md` | E |
| 09 | `09_api_implementation.md` | E |
| 10 | `10_api_test_evidence.md` | E |
| 11 | `11_architecture_invariant_audit.md` | A-E |
| 12 | `12_gate_A_to_C_verdicts.md` | A-C |
| 13 | `13_gate_D_and_E_verdicts.md` | D-E |
| 14 | `14_open_findings_and_risk_register.md` | — |
| 15 | `15_phase_0_2_2_final_verdict.md` | — |

---

**Preflight complete. Starting Gate A: Database Containment and Authority.**