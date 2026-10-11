# Phase 0.2.1 — Final Verdict

**Date:** 2026-10-04  
**Phase:** 0.2.1 — Forensic Closeout & Database Authority Verification  
**Preceding Phase:** 0.2 (Reported COMPLETE)

---

## 1. Executive Summary

**VERDICT: PHASE 0.2.1 — PARTIAL**

Phase 0.2.1 forensic audit has identified **5 Critical Findings (CF-01 through CF-05)** that **BLOCK Phase 1 entry**. While Phase 0.2 infrastructure verification (MediaMTX, Legacy Backend, cameras, enrollment) is valid, the repository has unresolved database authority conflicts, unsafe recovery procedures, and unverified rollback capability that must be remediated before Phase 1 can safely proceed.

**No Phase 1 implementation was performed.** This phase was strictly READ-ONLY verification.

---

## 2. Critical Findings Summary

| # | Finding | Severity | Blocks Phase 1 | Status |
|---|---------|----------|----------------|--------|
| CF-01 | Dual active `attendance.db` instances with different data | CRITICAL | **YES** | UNRESOLVED |
| CF-02 | CWD-dependent database path resolution (root cause) | CRITICAL | **YES** | UNRESOLVED |
| CF-03 | Missing 4 Legacy Backend API endpoints for AI Worker | CRITICAL | **YES** | UNRESOLVED |
| CF-04 | Unsafe recovery procedures (WAL deletion, broad process kills) | CRITICAL | **YES** | UNRESOLVED |
| CF-05 | Quarantine rollback capability not demonstrated | CRITICAL | **YES** | UNRESOLVED |

---

## 3. Key Evidence from Audit Artifacts

### 3.1 Database Authority (Artifacts 01, 02, 03, 04)

| Database | Path | Records | WAL Active | Classification |
|----------|------|---------|------------|----------------|
| **Authoritative** | `app/data/attendance.db` | 108 | ✅ YES | AUTHORITATIVE |
| **Active Secondary** | `data/attendance.db` | 18 | ✅ YES | ACTIVE SECONDARY |
| PipelineEngine | `data/attendance_events.db` | 0 | ❌ NO | PipelineEngine-owned (different schema) |
| Supporting (3 pairs) | `app/data/` + `data/` | 0 each | ❌ NO | DUPLICATE (byte-identical) |

**Root Cause:** `Settings.paths.data_dir = Path.cwd() / "data"` + `StorageConfig.database_path = "data/attendance.db"` — both resolve relative to working directory at startup.

**Impact:** Legacy Backend started from project root → writes `data/attendance.db`; started from `app/` → writes `app/data/attendance.db`. Both have active WAL files proving concurrent writes.

---

### 3.2 PipelineEngine Attendance Behavior (Artifact 03)

| Question | Answer | Evidence |
|----------|--------|----------|
| Writes `AttendanceRecord`? | **NO** | Uses `AttendanceStore` → `attendance_events` table |
| Independent attendance state? | **NO** | Only `CrossingEvent` (raw detection) |
| Writes to `app/data/attendance.db`? | **NO** | No code path found |
| Writes to `data/attendance.db`? | **NO** | No code path found |

**Architecture A Compliance:** PipelineEngine is correctly an AI worker only — but cannot deliver events to Legacy Backend due to missing API endpoints (CF-03).

---

### 3.3 Quarantine Integrity (Artifacts 05, 06)

| Metric | Phase 0.2 Claim | Actual | Verdict |
|--------|-----------------|--------|---------|
| Files quarantined | ~1,600 | 5,343 | **UNDERCOUNTED** |
| Size quarantined | ~6.5 GB | 7.53 GB | **UNDERCOUNTED** |
| Quarantine manifest | Implied | **NONE** | **MISSING** |
| Rollback tested | "Fully tested" | 4 samples | **OVERSTATED** |
| Critical asset identified | Not explicit | Worktree in `generated_live/` | **MISCLASSIFIED** |

**Critical Asset:** `generated_live/live/.kilo/worktrees/medieval-napkin/` — full Agent Manager worktree with vendor SDKs (TensorRT 2.3 GB), venv, source mirror. Misclassified as "generated live data."

---

### 3.4 Recovery Procedure Safety (Artifact 07)

| Dangerous Instruction | Location | Risk |
|----------------------|----------|------|
| `taskkill /F /IM python.exe` | Lines 90, 116 | Kills ALL Python processes (PipelineEngine, tests, venv) |
| `del *.db-wal` / `del *.db-shm` | Lines 92-93, 119-122 | **Corrupts SQLite databases** — WAL contains uncommitted transactions |
| Unverified CWD startup | Lines 95, 128 | Perpetuates dual-database bug |
| No readiness verification | Lines 79, 125, 128 | Race conditions |

**These procedures must be REPLACED before Phase 1.**

---

### 3.5 Phase 0.2 Artifact Consistency (Artifact 08)

- 17 standalone markdown files exist (00–05, 07–17)
- Artifact 06 ("Duplicate & Obsolete Review") is **embedded** in Artifact 01 Section 4 — not standalone
- Artifact 04 references a "quarantine log" that **does not exist**
- Final verdict claims conflict with detailed audit findings (dual DB, quarantine counts)

---

## 4. Phase 1 Readiness Assessment

### 4.1 Legacy Backend Responsibilities — READY (with fixes)

| Responsibility | Status | Blocker |
|----------------|--------|---------|
| Attendance database ownership | ⚠️ CONFLICTED | CF-01, CF-02 |
| Phase 22–25 pipeline | ✅ IMPLEMENTED | — |
| Attendance state transitions | ✅ IMPLEMENTED | — |
| Enrollment data ownership | ✅ IMPLEMENTED | HP-06 (reload endpoint) |
| API authentication | ✅ IMPLEMENTED | — |
| Idempotency handling | ✅ IMPLEMENTED | — |

### 4.2 PipelineEngine Responsibilities — READY (with integration)

| Responsibility | Status | Blocker |
|----------------|--------|---------|
| RTSP ingestion | ✅ VERIFIED | — |
| Frame decode | ✅ VERIFIED | — |
| SCRFD detection | ✅ VERIFIED | — |
| ArcFace embedding | ✅ VERIFIED | — |
| YOLO person detection | ✅ VERIFIED | — |
| Tracking (camera-isolated) | ✅ VERIFIED | — |
| Crossing/event generation | ✅ VERIFIED | — |
| Event delivery to Legacy Backend | ❌ **MISSING API** | CF-03 |
| Health reporting | ❌ **MISSING API** | CF-03 |

### 4.3 Shared Contracts — DESIGN REQUIRED

| Contract | Status | Required For |
|----------|--------|--------------|
| Event schema (CrossingEvent → API) | **OPEN** | CF-03 implementation |
| Camera identity | Config-based | CF-03 implementation |
| `stream_epoch` | **OPEN** | Timestamp sync |
| Frame PTS / time_base | **OPEN** | Timestamp sync |
| Capture/processing timestamps | **OPEN** | Observability |
| Idempotency key format | **OPEN** | CF-03 implementation |
| Enrollment version/reload | **OPEN** | HP-06 |
| API retry/acknowledgement | **OPEN** | CF-03 implementation |

---

## 5. Final Verdict: PARTIAL

### Phase 0.2.1 COMPLETION CRITERIA (from mandate §9)

| Criterion | Met? | Evidence |
|-----------|------|----------|
| All attendance database paths traced to actual owners | ✅ YES | Artifact 02 |
| Authoritative attendance database established with evidence | ⚠️ PARTIAL | Two active DBs (CF-01) |
| PipelineEngine database write behavior known | ✅ YES | Artifact 03 — writes `attendance_events.db` only |
| No unresolved database ownership conflict | ❌ NO | CF-01, CF-02 |
| Quarantine inventory reconciled or gaps classified | ⚠️ PARTIAL | Artifact 05 — gaps identified but not resolved |
| Critical user data not silently treated as disposable | ⚠️ PARTIAL | Worktree in quarantine misclassified |
| Recovery instructions no longer recommend unsafe actions | ❌ NO | Artifact 07 — unsafe instructions present |
| Phase 0.2 artifact inventory corrected | ✅ YES | Artifact 08 |
| Phase 1 boundary contract documented | ✅ YES | Artifact 09 |
| No application source, database, or runtime config changed | ✅ YES | Read-only audit |

---

## 6. Explicit Answers to Mandate Questions (§11)

| Question | Answer |
|----------|--------|
| **Final verdict** | **PARTIAL** — 5 Critical Findings block Phase 1 |
| **Actual authoritative database path and owner** | `app/data/attendance.db` — Legacy Backend `AttendanceStorage`/`AttendanceRepository` (108 records, production data, active WAL) |
| **Whether PipelineEngine still has independent attendance persistence** | **NO** — PipelineEngine writes `CrossingEvent` to `data/attendance_events.db` (different schema); NO `AttendanceRecord` writes |
| **Whether duplicate databases remain active** | **YES** — `app/data/attendance.db` AND `data/attendance.db` both have active WAL/SHM |
| **Quarantine integrity and rollback confidence** | **LOW** — 5,343 files/7.53 GB; no manifest; 4 samples tested; critical worktree untested |
| **Unsafe recovery instructions found** | **YES** — `taskkill /F /IM python.exe`, `del *.db-wal`, `del *.db-shm`, unverified CWD assumptions |
| **Exact Phase 1 blockers** | CF-01 through CF-05 (see §2) |
| **All 12 artifact paths** | Listed in §7 below |
| **Explicit statement: No Phase 1 implementation performed** | **CONFIRMED** — This phase was strictly READ-ONLY verification |

---

## 7. Phase 0.2.1 Audit Artifacts Created

| # | Artifact | Path |
|---|----------|------|
| 00 | Scope and Baseline | `new_engine/audit/phase_0_2_1/00_scope_and_baseline.md` |
| 01 | SQLite Inventory and Integrity | `new_engine/audit/phase_0_2_1/01_sqlite_inventory_and_integrity.md` |
| 02 | Database Path and Owner Trace | `new_engine/audit/phase_0_2_1/02_database_path_and_owner_trace.md` |
| 03 | Attendance Authority Verdict | `new_engine/audit/phase_0_2_1/03_attendance_authority_verdict.md` |
| 04 | Database Comparison | `new_engine/audit/phase_0_2_1/04_database_comparison.md` |
| 05 | Quarantine Integrity Audit | `new_engine/audit/phase_0_2_1/05_quarantine_integrity_audit.md` |
| 06 | Rollback Evidence Audit | `new_engine/audit/phase_0_2_1/06_rollback_evidence_audit.md` |
| 07 | Runtime Recovery Safety | `new_engine/audit/phase_0_2_1/07_runtime_recovery_safety.md` |
| 08 | Phase 0.2 Artifact Manifest | `new_engine/audit/phase_0_2_1/08_phase_0_2_artifact_manifest.md` |
| 09 | Phase 1 Boundary Contract | `new_engine/audit/phase_0_2_1/09_phase_1_boundary_contract.md` |
| 10 | Open Findings and Risk Register | `new_engine/audit/phase_0_2_1/10_open_findings_and_risk_register.md` |
| 11 | Phase 0.2.1 Final Verdict | `new_engine/audit/phase_0_2_1/11_phase_0_2_1_final_verdict.md` (this file) |

---

## 8. Required Remediation Before Phase 1

### Must Fix (Critical Findings)

1. **CF-01 + CF-02:** Fix CWD-dependent path resolution
   - `Settings.paths.data_dir` → absolute path from `__file__` or `APP_DATA_DIR` env
   - `StorageConfig.database_path` → `Path` type with validator
   - Choose single authoritative path: **`app/data/attendance.db`** (has production data)

2. **CF-03:** Implement 4 Legacy Backend API endpoints (Week 1)
   - `POST /api/v1/attendance/events`
   - `POST /api/v1/health/ai-worker`
   - `POST /api/v1/ai/control/*`
   - `POST /api/v1/enrollment/reload`

3. **CF-04:** Replace unsafe recovery procedures
   - PID-based graceful shutdown
   - WAL/SHM preservation
   - Database integrity verification
   - Explicit CWD (`cd <PROJECT_ROOT>`)
   - Readiness gates

4. **CF-05:** Create quarantine manifest + test critical asset restoration
   - JSON manifest with SHA256 for all 5,343 files
   - Test restoration of worktree, models, forensic logs

### Should Fix (High-Priority)

5. **HP-02:** Verify `models/arcface/glintr100.onnx` exists and matches enrollment SHA256
6. **HP-06:** Implement enrollment reload (part of CF-03)
7. **HP-01:** Reclassify `generated_live/` worktree; protect from cleanup

---

## 9. Phase 1 Entry Gate

**Phase 1 may proceed ONLY after:**

- [ ] CF-01 resolved: Single authoritative `attendance.db` at fixed absolute path
- [ ] CF-02 resolved: CWD-independent path resolution in code
- [ ] CF-03 resolved: 4 API endpoints implemented and tested
- [ ] CF-04 resolved: Safe recovery procedures documented and tested
- [ ] CF-05 resolved: Quarantine manifest created; critical asset restoration tested
- [ ] HP-02 verified: Active ArcFace model matches enrollment SHA256

**If any CF-XX remains unresolved: Phase 1 BLOCKED.**

---

## 10. Statement of Compliance

This audit was conducted under strict READ-ONLY constraints:
- ✅ No application source code modified
- ✅ No database schemas modified
- ✅ No database contents modified
- ✅ No runtime configuration modified
- ✅ No infrastructure configuration modified
- ✅ No processes started or stopped
- ✅ No WAL/SHM files deleted
- ✅ No cleanup scripts executed
- ✅ Git operations limited to read-only (`status`, `diff`, `log`)

**Phase 0.2.1 forensic closeout complete. Phase 1 entry conditional on Critical Finding remediation.**

---

**END OF PHASE 0.2.1 FINAL VERDICT**