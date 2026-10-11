# Phase 0.2.6 — Scope and Execution Baseline

**Date:** 2026-10-04  
**Phase:** 0.2.6 — Health & Control Contract Remediation  
**Previous Phase:** 0.2.5 — BLOCKED  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main  
**Git Status:** 2000+ deleted files (D), untracked: UI/, analyze_quarantine.py, app/api/ai_worker.py, bootstrap.bat, bootstrap.py, check_dbs.py, final_verify.py, inspect_dbs.py, new_engine/, pipeline_engine/, search_writers.py, test_sqlite_backup.py

---

## 1. Mission

Resolve the remaining Health and Control integration blockers from Phase 0.2.5 and produce independently verifiable evidence.

Phase 0.2.5 concluded with verdict **BLOCKED** and three critical blockers:

1. **Health Backend State Management (Gate A)** — `POST /api/v1/health/ai-worker` is a scaffold that accepts reports but does not maintain reliable observable health state. No sequence validation, no status retrieval endpoint.

2. **Control Client Contract Mismatches (Gate B)** — Three fundamental mismatches prevent ANY control action execution:
   - Action vocabulary: Backend uses `START_WORKER` etc., Client uses `start` etc. (zero overlap)
   - Polling response key: Backend returns `"requests"`, Client expects `"commands"`
   - Response endpoint: Client posts to `/start/response`, Backend expects `/START_WORKER/response`

3. **Missing Phase 0.2.4 Artifact 11** — Control end-to-end test evidence artifact not created (numbering discrepancy: two artifact 10s, offset from 12 onwards).

---

## 2. Repository Baseline

### 2.1 Git State

| Property | Value |
|---|---|
| Repository Root | `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE` |
| Branch | `main` |
| HEAD Commit | `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline` |
| Untracked Files | UI/, analyze_quarantine.py, app/api/ai_worker.py, bootstrap.bat, bootstrap.py, check_dbs.py, final_verify.py, inspect_dbs.py, new_engine/, pipeline_engine/, search_writers.py, test_sqlite_backup.py |

### 2.2 Phase 0.2.5 Source Changes (Current State)

| File | Status |
|---|---|
| `app/config/settings.py` | MODIFIED — CWD-independent paths |
| `app/attendance/storage.py` | MODIFIED — Fixed attendance DB path |
| `app/api/ai_worker.py` | NEW (1,635 lines) — **Has 3x code duplication bug** |
| `app/api/enrollment.py` | MODIFIED — Enrollment reload endpoints |
| `app/main.py` | MODIFIED — Registers ai_worker_router |
| `pipeline_engine/integration/health_client.py` | NEW — Complete health client |
| `pipeline_engine/integration/control_client.py` | NEW — Control client with contract mismatches |

### 2.3 Key Source Files to Modify

**Health Backend:** `app/api/ai_worker.py` — Needs health state management, status retrieval, sequence validation

**Health Client:** `pipeline_engine/integration/health_client.py` — Complete, just needs field name fix (`inference_provider` → `gpu_provider`)

**Control Backend:** `app/api/ai_worker.py` — Functional, needs minor fixes (path/body validation, history endpoint)

**Control Client:** `pipeline_engine/integration/control_client.py` — Needs contract alignment (action names, polling key, response path)

---

## 3. Phase 0.2.4 Artifact Audit (Gate E Pre-work)

### 3.1 Actual Phase 0.2.4 Artifacts (19 files)

| # | Filename | Notes |
|---|---|---|
| 00 | `00_scope_and_preflight.md` | ✅ |
| 01 | `01_phase_0_2_3_findings_reconciliation.md` | ✅ |
| 02 | `02_health_contract_final.md` | ✅ |
| 03 | `03_health_backend_state_management.md` | ✅ |
| 04 | `04_health_client_completion.md` | ✅ (was 05 in spec) |
| 05 | `05_health_integration_test_evidence.md` | ✅ |
| 06 | `06_control_contract_final.md` | ✅ |
| 07 | `07_control_pending_endpoint.md` | ✅ |
| 08 | `08_control_response_endpoint.md` | ✅ |
| 09 | `09_control_client_completion.md` | ✅ |
| 10 | `10_control_end_to_end_tests.md` | **Duplicate 10** |
| 10 | `10_control_lifecycle_and_idempotency.md` | **Duplicate 10** |
| 11 | `12_security_and_enrollment_regression.md` | Should be 11 |
| 12 | `13_database_and_architecture_invariants.md` | Should be 12 |
| 13 | `14_api_endpoint_reconciliation.md` | Should be 13 |
| 14 | `15_full_regression_test_report.md` | Should be 14 |
| 15 | `16_source_change_manifest.md` | Should be 15 |
| 16 | `17_open_findings_and_risks.md` | Should be 16 |
| 17 | `18_phase_0_2_4_final_verdict.md` | Should be 17 |
| 18 | `19_phase_1_entry_assessment.md` | Should be 18 |

**Missing Artifact 11:** `11_control_end_to_end_tests.md` (from Phase 0.2.4 spec)

**Resolution for Phase 0.2.6:** Document this discrepancy in Gate E artifacts, create reconciliation evidence.

---

## 4. Safety Rules Confirmation

- ✅ No `git reset` / `git clean` / `git checkout` / `git restore`
- ✅ No production database modifications
- ✅ No WAL/SHM file deletions
- ✅ No quarantine modifications
- ✅ No Architecture A changes
- ✅ No Phase 1 features
- ✅ Using isolated test databases and fixtures only

---

## 5. Execution Plan

### Gate A: Health Backend State Management
1. Remove 3x code duplication in `app/api/ai_worker.py` (keep single definitions)
2. Implement `WorkerHealthState` in-memory store with:
   - worker_id, status, health_status, last_report_timestamp, last_sequence, generation_id
   - camera_states, model_readiness, stream_epochs, errors
3. Add sequence validation (monotonic, reject duplicates/out-of-order)
4. Add generation tracking for worker restarts
5. Add `GET /api/v1/health/ai-worker/{worker_id}` status retrieval endpoint
6. Fix field name: backend expects `gpu_provider` (client sends `inference_provider`)
7. Add stale worker detection (30s threshold)
8. Integrate with control queue to return pending commands

### Gate B: Control Contract Alignment
1. Define canonical contract schema in shared location or single source
2. Align `pipeline_engine/integration/control_client.py` action vocabulary to backend (`START_WORKER`, etc.)
3. Fix polling response key: `data.get("requests", [])` not `data.get("commands", [])`
4. Fix response endpoint path: use `request.action` from backend response
5. Add `GET_STATUS` handler to client
6. Fix hardcoded worker_id in idempotency storage
7. Add path/body action validation in backend response endpoint
8. Add completed command history endpoint

### Gate C: End-to-End Integration Tests
1. Health: Client → Backend → State Store → Status Retrieval
2. Control: Admin Command → Backend → Client Poll → Handler → Response → Backend State

### Gate D: Security & Invariants
1. Verify attendance database invariants unchanged
2. Verify auth separation
3. Verify no secrets in logs

### Gate E: Artifact Reconciliation
1. Document Phase 0.2.4 artifact discrepancy
2. Create Phase 0.2.6 18 artifacts with proper numbering

### Gate F: Regression Tests
1. Run existing test suites
2. Run new health/control integration tests

### Gate G: Final Forensic Audit
1. git diff review
2. SHA256 manifest
3. Final verdict

---

## 6. Phase 0.2.6 Artifacts to Create (18 files)

| # | File |
|---|---|
| 00 | `00_phase_scope_and_execution_baseline.md` |
| 01 | `01_repository_state_and_change_inventory.md` |
| 02 | `02_health_contract_before_after.md` |
| 03 | `03_health_state_model.md` |
| 04 | `04_health_sequence_and_generation_policy.md` |
| 05 | `05_health_backend_implementation.md` |
| 06 | `06_health_client_integration.md` |
| 07 | `07_health_test_evidence.md` |
| 08 | `08_control_contract_before_after.md` |
| 09 | `09_control_canonical_schema.md` |
| 10 | `10_control_lifecycle_and_idempotency.md` |
| 11 | `11_control_backend_client_alignment.md` |
| 12 | `12_control_security_audit.md` |
| 13 | `13_control_test_evidence.md` |
| 14 | `14_end_to_end_integration_evidence.md` |
| 15 | `15_attendance_and_database_invariants.md` |
| 16 | `16_regression_and_failure_test_results.md` |
| 17 | `17_final_verdict_and_phase_1_readiness.md` |

---

## 7. Current Blocker Status

| Blocker | Gate | Status | Resolution Path |
|---|---|---|---|
| Health backend scaffold | A | OPEN | Implement state store + validation + retrieval |
| Health client field mismatch | A | OPEN | Fix `inference_provider` → `gpu_provider` |
| Control action vocabulary | B | OPEN | Align client to backend enum |
| Control polling key mismatch | B | OPEN | Fix client to use `requests` |
| Control response endpoint | B | OPEN | Fix client path construction |
| Missing artifact 11 | E | OPEN | Document reconciliation |

---

**Ready to begin Gate A implementation.**