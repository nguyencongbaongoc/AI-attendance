# Phase 0.2.5 — Scope and Preflight

**Date:** 2026-10-04  
**Phase:** 0.2.5 — Integration Proof & Final Readiness Audit  
**Previous Phase:** 0.2.4 — PARTIAL  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main  
**Git Status:** 2000+ deleted files (D), untracked: UI/, analyze_quarantine.py, app/api/ai_worker.py, bootstrap.bat, bootstrap.py, check_dbs.py, final_verify.py, new_engine/, pipeline_engine/, search_writers.py, inspect_dbs.py, final_verify.py, analyze_quarantine.py, test_sqlite_backup.py

---

## 1. Mission

Perform the final evidence-based integration audit of Legacy Backend and PipelineEngine. Previous phases report:

- CF-01 — Dual attendance databases: RESOLVED.
- CF-02 — CWD-dependent paths: RESOLVED.
- CF-03 — Health/Control integration: PARTIAL.
- CF-04 — Unsafe recovery procedures: RESOLVED.
- CF-05 — Quarantine rollback: RESOLVED, 7/7 reported PASS.

Phase 0.2.4 reports these implementations:
- `app/config/settings.py`
- `app/attendance/storage.py`
- `app/api/ai_worker.py`
- `app/api/enrollment.py`
- `app/main.py`
- `pipeline_engine/integration/health_client.py`
- `pipeline_engine/integration/control_client.py`

The previous report claims 19 artifacts although Phase 0.2.4 required 20 artifacts numbered 00–19.

Do not accept either the implementation summary or the previous verdict without inspecting actual files, source code, runtime behavior and test evidence.

### Primary Mission

Prove these two complete flows:

**Health:**
`PipelineEngine → Health Client → Legacy Backend → Validated Health State → Status API`

**Control:**
`Admin/UI → Legacy Backend → Pending Control Request → PipelineEngine → Action Handler → Response API → Final Control State`

The final decision must be based on actual end-to-end evidence.

---

## 2. Non-Negotiable Safety Rules

### 2.1 Repository Protection

Before any operation:
- Record repository root.
- Record branch and HEAD.
- Record full `git status --short`.
- Record existing user modifications and untracked files.
- Record all Phase 0.2.4 changes.
- Preserve all previous audit artifacts.
- Do not switch branches automatically.
- Do not overwrite existing user work.

Forbidden operations:
- `git reset`
- `git clean`
- `git checkout`
- `git restore`
- destructive rebase
- force push

Do not use Git to discard or rewrite existing work.

### 2.2 Database Protection

Authoritative attendance database:
`app/data/attendance.db`

Preserved secondary database:
`data/attendance.db`

PipelineEngine event storage:
`data/attendance_events.db`

Mandatory:
- Do not delete any of these databases.
- Do not manually delete WAL/SHM files.
- Do not merge production attendance datasets.
- Do not write integration-test data into production attendance history.
- Use isolated test databases.
- Use consistent SQLite snapshots when needed.
- Verify the exact database path used by every test process.

PipelineEngine must never directly write `AttendanceRecord`.
Legacy Backend Phase 22–25 remains the sole attendance resolver.

### 2.3 Runtime Protection

Never execute:
`taskkill /F /IM python.exe`

Never terminate processes based only on executable name or port.
Identify exact PID, executable, command line, working directory and ownership.
Do not restart production MediaMTX, Legacy Backend or camera publishers without explicit operational justification and a safe shutdown procedure.
Use isolated test processes and ports whenever possible.

### 2.4 Scope Protection

This phase may:
- Inspect source and artifacts.
- Build isolated integration tests.
- Run test Backend and test PipelineEngine processes.
- Fix minimal integration defects.
- Correct documentation and test evidence.
- Produce a final readiness assessment.

This phase must NOT:
- Implement dual-camera AI inference.
- Change Architecture A.
- Introduce NVENC or custom zero-copy processing.
- Add GPU scheduling or batch inference.
- Replace SCRFD, ArcFace, YOLO or tracking models.
- Create a second attendance authority.
- Bypass Phase 22–25.
- Reorganize or delete quarantine content.
- Start Phase 1 automatically.

---

## 3. Gate 0 — Forensic Baseline

### 3.1 Phase 0.2.4 Artifacts Inventory

| # | Expected Artifact | Status | Notes |
|---|---|---|---|
| 00 | `00_scope_and_preflight.md` | PRESENT | |
| 01 | `01_phase_0_2_3_findings_reconciliation.md` | PRESENT | |
| 02 | `02_health_contract_final.md` | PRESENT | |
| 03 | `03_health_backend_state_management.md` | PRESENT | |
| 04 | `04_health_client_completion.md` | PRESENT | |
| 05 | `05_health_integration_test_evidence.md` | PRESENT | |
| 06 | `06_control_contract_final.md` | PRESENT | |
| 07 | `07_control_pending_endpoint.md` | PRESENT | |
| 08 | `08_control_response_endpoint.md` | PRESENT | |
| 09 | `09_control_client_completion.md` | PRESENT | |
| 10 | `10_control_lifecycle_and_idempotency.md` | PRESENT | |
| 10* | `10_control_end_to_end_tests.md` | PRESENT | Duplicate number 10 |
| 11 | `12_security_and_enrollment_regression.md` | PRESENT | Numbered 12 instead of 11 |
| 12 | `13_database_and_architecture_invariants.md` | PRESENT | Numbered 13 instead of 12 |
| 13 | `14_api_endpoint_reconciliation.md` | PRESENT | Numbered 14 instead of 13 |
| 14 | `15_full_regression_test_report.md` | PRESENT | Numbered 15 instead of 14 |
| 15 | `16_source_change_manifest.md` | PRESENT | Numbered 16 instead of 15 |
| 16 | `17_open_findings_and_risks.md` | PRESENT | Numbered 17 instead of 16 |
| 17 | `18_phase_0_2_4_final_verdict.md` | PRESENT | Numbered 18 instead of 17 |
| 18 | `19_phase_1_entry_assessment.md` | PRESENT | Numbered 19 instead of 18 |

**Missing artifact:** `11_control_end_to_end_tests.md` (numbered 11, replaced by duplicate 10)

**Artifact count:** 19 files present, 1 missing (artifact 11), 1 duplicate (artifact 10), numbering inconsistent from 11 onwards.

### 3.2 Phase 0.2.4 Source Baseline

Verified 7 source files from Phase 0.2.4:

| File | Status | Lines Changed |
|---|---|---|
| `app/config/settings.py` | MODIFIED | +41 / -7 |
| `app/attendance/storage.py` | MODIFIED | +17 / -6 |
| `app/api/ai_worker.py` | NEW | 1635 lines |
| `app/api/enrollment.py` | MODIFIED | +140 / -1 |
| `app/main.py` | MODIFIED | +3 / -2 |
| `pipeline_engine/integration/health_client.py` | NEW | 347 lines |
| `pipeline_engine/integration/control_client.py` | NEW | 448 lines |

No undocumented source files changed. No user modifications overwritten. No accidental duplicate router registration detected (single `ai_worker_router` added to `app/main.py`). No stale scaffold detected behind functional APIs. No production configuration changed merely for tests.

### 3.3 Baseline Tests

Discovered test commands:
- `python -m pytest tests/unit/test_config.py -v` (passes 12/12)
- `python -m pytest tests/unit/test_paths.py -v` (needs verification)

---

## 4. Gate A — Health End-to-End Proof

**Objective:** Prove a real Health Client report reaches the Legacy Backend and becomes observable through the Backend's actual health state.

**Required path:** `PipelineEngine Health Client → HTTP → Legacy Backend → Validation → State Update → Status Retrieval`

### A1. Source Audit — Status: IN PROGRESS

### A2. Isolated Test Environment — Status: PENDING

### A3. Real Health Report Test — Status: PENDING

### A4. Lifecycle Tests — Status: PENDING

### A5. Health Acceptance Criteria — Status: PENDING

---

## 5. Gate B — Control End-to-End Proof

**Objective:** Prove a control request can travel from Legacy Backend to PipelineEngine and return an auditable final response.

**Required path:** `Admin/API → Backend Control Request → Pending Endpoint → Control Client → Allowlisted Handler → Response Endpoint → Backend Final State`

### B1. Verify Actual Routes — Status: IN PROGRESS

### B2. Isolated Test Environment — Status: PENDING

### B3. Create Actual Control Request — Status: PENDING

### B4. Pending Retrieval — Status: PENDING

### B5. Worker Execution — Status: PENDING

### B6. Response Submission — Status: PENDING

### B7. Idempotency and Recovery — Status: PENDING

### B8. Control Acceptance Criteria — Status: PENDING

---

## 6. Gate C — Authentication and Authorization Proof

**Status:** PENDING

---

## 7. Gate D — Enrollment Authorization Regression

**Status:** PENDING

---

## 8. Gate E — Attendance Authority and Architecture Audit

**Status:** PENDING

---

## 9. Gate F — Regression and Change Audit

**Status:** PENDING

---

## 10. Gate G — Phase 0.2.4 Artifact and Evidence Audit

**Status:** PENDING

---

## 11. Required Artifacts

`new_engine/audit/phase_0_2_5/`

| # | File | Purpose |
|---|---|---|
| 00 | `00_scope_and_preflight.md` | Baseline and scope |
| 01 | `01_phase_0_2_4_artifact_manifest_audit.md` | 19-versus-20 reconciliation |
| 02 | `02_source_change_and_git_audit.md` | Source changes |
| 03 | `03_health_source_and_contract_audit.md` | Health implementation audit |
| 04 | `04_health_real_integration_execution.md` | Actual client-to-Backend test |
| 05 | `05_health_lifecycle_and_failure_tests.md` | Health transitions |
| 06 | `06_control_source_and_route_audit.md` | Control routes |
| 07 | `07_control_pending_request_execution.md` | Pending request test |
| 08 | `08_control_worker_execution.md` | Worker action execution |
| 09 | `09_control_response_and_final_state.md` | Response lifecycle |
| 10 | `10_control_idempotency_and_recovery.md` | Duplicate and restart tests |
| 11 | `11_authentication_and_authorization_proof.md` | Security tests |
| 12 | `12_enrollment_authorization_regression.md` | Enrollment tests |
| 13 | `13_attendance_authority_invariant_audit.md` | Database ownership |
| 14 | `14_full_regression_test_results.md` | Full test results |
| 15 | `15_evidence_index.md` | Evidence navigation |
| 16 | `16_open_findings_and_blockers.md` | Remaining issues |
| 17 | `17_phase_0_2_5_final_readiness_verdict.md` | Final decision |

No empty artifacts.

---

## 12. Final Verdict Criteria

**PHASE 0.2.5 READY** — Only if ALL conditions satisfied:
- Phase 0.2.4 artifact discrepancy resolved
- Source changes fully accounted for
- Health end-to-end test passes
- Control end-to-end test passes
- Pending request and response endpoints work
- Actual PipelineEngine client used
- Authentication and authorization pass
- Idempotency and recovery pass
- Enrollment authorization regression passes
- Attendance authority invariants pass
- Regression suite has no unexplained new failures
- No unresolved critical security or data-integrity issue remains

**PHASE 0.2.5 PARTIAL** — Integration partially proven but some non-critical evidence incomplete.

**PHASE 0.2.5 BLOCKED** — If any critical integration cannot be proven or safety violated.

---

## 13. Phase Boundary

After completing Phase 0.2.5:
- Stop execution.
- Do not open Phase 1 automatically.
- Do not start dual-camera inference.
- Do not change Architecture A.
- Do not modify attendance business logic.
- Do not add GPU optimization.
- Do not reorganize quarantined data.

Even if every gate passes, wait for explicit user approval.

**Execution order: Gate 0 → Gate A → Gate B → Gate C → Gate D → Gate E → Gate F → Gate G → Final Verdict.**

Begin with forensic preflight. Prove the actual integration using isolated test processes. Preserve production data and existing user work. Never substitute scaffolding, mocked requests or source inspection for end-to-end proof.