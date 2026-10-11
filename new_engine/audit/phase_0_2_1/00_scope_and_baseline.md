# Phase 0.2.1 — Scope and Baseline

**Date:** 2026-10-04  
**Phase:** 0.2.1 — Forensic Closeout & Database Authority Verification  
**Preceding Phase:** 0.2 (Infrastructure Bring-Up, Runtime Baseline & Repository Cleanup) — Reported COMPLETE

---

## 1. Objective

Independently verify unresolved findings from Phase 0.2 and produce a forensic closeout report establishing whether the repository is safe to enter Phase 1. This phase is strictly READ-ONLY — no modifications to application source, database schemas, database contents, runtime configuration, or infrastructure configuration.

---

## 2. Baseline from Phase 0.2 Final Verdict

| Item | Phase 0.2 Claim | Evidence Source |
|------|-----------------|-----------------|
| Repository cleanup | 1,600+ files, ~6.5 GB quarantined | `17_phase_0_2_final_verdict.md` §1.1 |
| Files kept active | ~37,000 files, ~9.3 GB | `17_phase_0_2_final_verdict.md` §1.2 |
| Protected assets | `.venv2/`, `app/data/`, `models/`, `mediamtx/`, vendor SDKs, `.git/` | `17_phase_0_2_final_verdict.md` §1.3 |
| MediaMTX runtime | Running, ports 8554/1935/9997/8888/8889/8890, 2 paths ready | `17_phase_0_2_final_verdict.md` §2 Test 2 |
| Legacy Backend runtime | Running on port 19146, 72 endpoints, health checks pass | `17_phase_0_2_final_verdict.md` §2 Test 3 |
| Camera 1 decode | RTSP decode 3840×2160 @ 29.3 fps | `17_phase_0_2_final_verdict.md` §2 Test 4 |
| Camera 2 decode | RTSP decode 3840×2160 @ 47.1 fps | `17_phase_0_2_final_verdict.md` §2 Test 5 |
| Dual-camera relay | Concurrent decode at 97+100 fps | `17_phase_0_2_final_verdict.md` §2 Test 6 |
| Enrollment state | 7 embeddings (512-dim), 1 person, valid provenance | `17_phase_0_2_final_verdict.md` §2 Test 8 |
| Architecture A compliance | Legacy Backend owns attendance; PipelineEngine DBs quarantined | `17_phase_0_2_final_verdict.md` §3 |

---

## 3. Phase 0.2.1 Verification Targets

Four primary areas requiring independent verification:

1. **Database Authority & SQLite Ownership** — Inventory all SQLite databases, trace actual paths from source, identify authoritative attendance ownership, compare active vs quarantined databases, produce definitive authority matrix.

2. **Quarantine Integrity & Recoverability** — Reconcile actual file counts/sizes vs Phase 0.2 claims, verify important quarantined assets (generated_live/, root_test_videos/, etc.), audit rollback test evidence.

3. **Runtime Recovery Procedure Safety** — Audit `16_blockers_and_recovery_plan.md` for dangerous instructions (broad process kills, WAL/SHM deletion, unverified working-directory assumptions).

4. **Phase 0.2 Artifact Consistency** — Verify artifact inventory (00–17), check artifact 06 status, validate final verdict claims against detailed artifacts.

---

## 4. Repository State at Start of Phase 0.2.1

| Metric | Value |
|--------|-------|
| Repository root | `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE` |
| Current branch | `main` (HEAD: 5269777) |
| HEAD commit | `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline` |
| `git status --short` | 2000+ deleted files (D), 2 untracked directories (UI/, new_engine/, pipeline_engine/) |
| Quarantine directory | `new_engine/audit/phase_0_2/quarantine/` (10 subdirectories) |

---

## 5. Evidence Classification Standard

Every finding in this audit will be classified as:

| Classification | Meaning |
|----------------|---------|
| **SOURCE VERIFIED** | Directly observed in source code or configuration |
| **RUNTIME VERIFIED** | Observed via live inspection (database, process, network) |
| **DOCUMENTED ONLY** | Stated in Phase 0.2 reports but not independently verified |
| **INFERRED** | Deduced from evidence but not directly observed |
| **UNKNOWN** | Cannot be determined with available read-only methods |
| **NOT TESTED** | Not yet examined in this audit |

---

## 6. Safety Confirmation

- ✅ No application source code modified
- ✅ No database schemas modified
- ✅ No database contents modified
- ✅ No runtime configuration modified
- ✅ No infrastructure configuration modified
- ✅ No processes started/stopped
- ✅ No WAL/SHM files deleted
- ✅ No cleanup scripts executed
- ✅ Git operations limited to read-only (`status`, `diff`, `log`)

---

## 7. Phase 0.2.1 Artifact Contract

| # | Artifact | Purpose |
|---|----------|---------|
| 00 | `00_scope_and_baseline.md` | This document — scope, baseline, evidence standards |
| 01 | `01_sqlite_inventory_and_integrity.md` | Complete SQLite inventory with integrity checks |
| 02 | `02_database_path_and_owner_trace.md` | Database path resolution trace from source |
| 03 | `03_attendance_authority_verdict.md` | Authority matrix for attendance data |
| 04 | `04_database_comparison.md` | Active vs quarantined database comparison |
| 05 | `05_quarantine_integrity_audit.md` | Quarantine inventory reconciliation |
| 06 | `06_rollback_evidence_audit.md` | Rollback procedure evidence assessment |
| 07 | `07_runtime_recovery_safety.md` | Recovery plan safety audit |
| 08 | `08_phase_0_2_artifact_manifest.md` | Corrected Phase 0.2 artifact manifest |
| 09 | `09_phase_1_boundary_contract.md` | Phase 1 responsibility boundaries |
| 10 | `10_open_findings_and_risk_register.md` | Unresolved findings and risks |
| 11 | `11_phase_0_2_1_final_verdict.md` | Final verdict with Phase 1 readiness decision |

---

**This scope document establishes the baseline for all subsequent Phase 0.2.1 verification work.**