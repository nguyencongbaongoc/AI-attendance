# Phase 0.2.4 — Scope and Preflight

**Date:** 2026-10-04  
**Phase:** 0.2.4 — Health & Control Integration Completion  
**Previous Phase:** 0.2.3 — PARTIAL  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main  
**Git Status:** 2000+ deleted files (D), untracked: UI/, analyze_quarantine.py, app/api/ai_worker.py, bootstrap.bat, bootstrap.py, check_dbs.py, final_verify.py, new_engine/, pipeline_engine/, search_writers.py, inspect_dbs.py, final_verify.py, analyze_quarantine.py

---

## 1. Mission

Complete the remaining Health and Control integration gaps reported in Phase 0.2.3.

Phase 0.2.3 reported:

| Finding | Phase 0.2.3 Status | Phase 0.2.4 Objective |
|---|---|---|
| CF-01 — Dual attendance databases | RESOLVED | Regression verification |
| CF-02 — CWD-dependent paths | RESOLVED | Multi-CWD regression verification |
| CF-03 — Missing API integration | PARTIAL | Complete health/control integration and verify all API contracts |
| CF-04 — Unsafe recovery | RESOLVED | Regression audit |
| CF-05 — Quarantine rollback | PARTIAL (reported) | Verify 7/7 rollback tests |

Existing implementation from Phase 0.2.3:
- `app/api/ai_worker.py` — 4 AI Worker endpoints (event ingestion, health, control)
- `app/api/enrollment.py` — Enrollment reload endpoints
- `pipeline_engine/integration/health_client.py` — PipelineEngine health client
- `pipeline_engine/integration/control_client.py` — PipelineEngine control server

Missing or incomplete Legacy Backend endpoints:
- `GET /ai/control/pending` — Not implemented
- `POST /ai/control/{action}/response` — Not implemented

Primary objective: establish a secure, bounded, testable, bidirectional integration between Legacy Backend and PipelineEngine.

---

## 2. Baseline State

### 2.1 Repository State

| Metric | Value |
|---|---|
| Repository root | `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE` |
| Current branch | `main` |
| HEAD commit | `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline` |
| `git status --short` | 2000+ deleted files (D), untracked: UI/, analyze_quarantine.py, app/api/ai_worker.py, bootstrap.bat, bootstrap.py, check_dbs.py, final_verify.py, new_engine/, pipeline_engine/, search_writers.py, inspect_dbs.py, final_verify.py, analyze_quarantine.py |

### 2.2 Database State (from Phase 0.2.3)

| Database | Path | Records | WAL Active | Classification |
|---|---|---|---|---|
| Authoritative | `app/data/attendance.db` | 108 | ✅ YES | AUTHORITATIVE |
| Secondary (preserved) | `data/attendance.db` | 18 | ✅ YES | SECONDARY |
| PipelineEngine events | `data/attendance_events.db` | 0 | ❌ NO | PipelineEngine-owned |

### 2.3 Phase 0.2.3 Source Changes (Verified)

| File | Change |
|---|---|
| `app/config/settings.py` | `_get_repository_root()` + CWD-independent paths |
| `app/attendance/storage.py` | `_get_attendance_db_path()` + Path type |
| `app/api/ai_worker.py` | **NEW**: 4 AI Worker endpoints |
| `app/api/enrollment.py` | Enrollment reload endpoints (`/reload`, `/reload/status`) |
| `app/main.py` | Register `ai_worker_router` |
| `pipeline_engine/integration/health_client.py` | **NEW**: Health client |
| `pipeline_engine/integration/control_client.py` | **NEW**: Control server |

### 2.4 Phase 0.2.3 Artifacts (18 files)

All 18 artifacts exist in `new_engine/audit/phase_0_2_3/`.

---

## 3. Phase 0.2.4 Objectives

Seven gates to complete:

| Gate | Addresses | Objective |
|---|---|---|
| A | Health Contract Completion | Complete health schema, backend state management |
| B | Health Client & Backend Integration | PipelineEngine health client ↔ Legacy Backend |
| C | Control API Contract | Finalize control schema, pending/response endpoints |
| D | Control Client & End-to-End Flow | PipelineEngine control server ↔ Legacy Backend |
| E | Security & Enrollment Regression | Auth, enrollment authorization regression |
| F | Database & Architecture Invariant Regression | Verify all 14 invariants |
| G | Documentation & Contract Reconciliation | Endpoint matrix, final reconciliation |

---

## 4. Safety Rules (Non-Negotiable)

- No `taskkill /F /IM python.exe`
- No `del *.db-wal` / `del *.db-shm`
- No broad process kills by name or port
- No deletion of WAL/SHM files
- No merging of attendance databases
- No test writes to production attendance history
- No Phase 1 implementation
- Preserve quarantine source files
- Use isolated test fixtures for all write operations

---

## 5. Evidence Classification

| Level | Meaning |
|---|---|
| SOURCE-VERIFIED | Direct source code inspection |
| STATIC-ANALYSIS | Tool-based analysis |
| UNIT-TESTED | Unit test execution |
| INTEGRATION-TESTED | Integration test execution |
| RUNTIME-VERIFIED | Live runtime observation |
| NOT-VERIFIED | Not yet examined |

---

## 6. Artifacts to Create

`new_engine/audit/phase_0_2_4/`

| # | File | Gate |
|---|---|---|
| 00 | `00_scope_and_preflight.md` | — |
| 01 | `01_phase_0_2_3_findings_reconciliation.md` | Preflight |
| 02 | `02_health_contract_final.md` | A |
| 03 | `03_health_backend_state_management.md` | A |
| 04 | `04_health_client_completion.md` | B |
| 05 | `05_health_integration_test_evidence.md` | B |
| 06 | `06_control_contract_final.md` | C |
| 07 | `07_control_pending_endpoint.md` | C |
| 08 | `08_control_response_endpoint.md` | C |
| 09 | `09_control_client_completion.md` | D |
| 10 | `10_control_lifecycle_and_idempotency.md` | D |
| 11 | `11_control_end_to_end_tests.md` | D |
| 12 | `12_security_and_enrollment_regression.md` | E |
| 13 | `13_database_and_architecture_invariants.md` | F |
| 14 | `14_api_endpoint_reconciliation.md` | G |
| 15 | `15_full_regression_test_report.md` | All |
| 16 | `16_source_change_manifest.md` | — |
| 17 | `17_open_findings_and_risks.md` | — |
| 18 | `18_phase_0_2_4_final_verdict.md` | — |
| 19 | `19_phase_1_entry_assessment.md` | — |

---

## 7. Phase 0.2.3 Source Change Verification

**Verified:** Phase 0.2.3 modified exactly 7 source files as documented in Phase 0.2.3 final verdict.

| File | Verified |
|---|---|
| `app/config/settings.py` | ✅ |
| `app/attendance/storage.py` | ✅ |
| `app/api/ai_worker.py` | ✅ (NEW) |
| `app/api/enrollment.py` | ✅ |
| `app/main.py` | ✅ |
| `pipeline_engine/integration/health_client.py` | ✅ (NEW) |
| `pipeline_engine/integration/control_client.py` | ✅ (NEW) |

No additional source changes detected beyond the 7 documented files.

---

**Preflight complete. Starting Gate A: Health Contract Completion.**