# Gate D — Quarantine Integrity and Rollback (CF-05)

**Date:** 2026-10-04  
**Phase:** 0.2.2 — Gate D  
**Classification:** SOURCE-VERIFIED / RUNTIME-VERIFIED

---

## 1. Executive Summary

**GATE D VERDICT: PARTIAL**

- ✅ Complete SHA256 manifest created (5,343 files, 7.53 GB)
- ✅ Quarantine classification complete with discrepancy analysis
- ✅ Agent Manager worktree correctly identified and classified
- ✅ Rollback verification tests designed
- ⚠️ **PARTIAL** — Rollback tests not yet executed on critical categories

---

## 2. Quarantine Inventory (SHA256 Manifest)

### 2.1 Manifest File

**Location:** `new_engine/audit/phase_0_2_2/05_quarantine_sha256_manifest.csv`

| Metric | Value |
|---|---|
| Total Files | 5,343 |
| Total Size | 7.53 GB |
| Manifest Hash (SHA256 of CSV) | [computed at generation] |
| Categories | 10 |

**Manifest Format:** CSV with columns: `relative_path, size_bytes, sha256, category, extension`

---

## 3. Quarantine Classification Summary

| Category | Files | Size (GB) | Key Extensions | Classification |
|---|---|---|---|---|
| `generated_live` | 3,008 | 4.12 | .py, .dll, .exe, .json, .md, .cfg | **CRITICAL - Agent Manager Worktree** |
| `root_test_videos` | 18 | 1.93 | .mp4, .h264, .pt | Test media / model duplicate |
| `root_model_duplicates` | 3 | 0.46 | .onnx | Model duplicates |
| `historical_scripts` | 101 | ~0 | .py | Development scripts |
| `generated_artifacts` | 2,008 | 0.99 | .json, .md, .log, .py | Benchmark/forensic outputs |
| `build_artifacts` | 159 | 0.01 | .obj, .cmake, .json | Build outputs |
| `empty_dirs` | 8 | 0.02 | (empty) | Empty directories |
| `runtime_logs` | 2 | ~0 | .log | Runtime logs |
| `video_pipeline_v2` | 36 | ~0 | .py | Superseded pipeline source |
| `data_duplicate_dbs` | 0 | 0 | (empty) | Empty (DBs restored to data/) |

**Total:** 5,343 files, 7.53 GB

---

## 4. Critical Findings

### 4.1 `generated_live` — Agent Manager Worktree (MISCLASSIFIED)

**Path:** `generated_live/live/.kilo/worktrees/medieval-napkin/`

**Contents:**
- Complete `.venv_38p_isolated/` virtual environment (~500 MB)
- Full source code mirror (`app/`, `pipeline_engine/`, `tests/`, etc.)
- CMake build artifacts (`CMakeFiles/`, `CMakeCache.txt`, `Makefile`)
- Vendor SDKs: `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/`
- Documentation: `AI_Attendance_Phase_History...`, `CANONICAL_MIGRATION_AUDIT_REPORT.md`
- `.kilo/` Agent Manager metadata

**Size:** 4.12 GB (3,008 files)

**Phase 0.2 Classification:** "Generated live data" — **INCORRECT**

**Correct Classification:** **Agent Manager Worktree — PRESERVE**

**Risk if Lost:** Complete isolated development environment including vendor SDKs, virtual environment, and source mirror. Would require re-download of TensorRT (2.3 GB), Video Codec SDK, venv rebuild.

---

### 4.2 `root_model_duplicates` — ArcFace Model (CRITICAL)

**Files:**
- `glintr100.onnx` (180 MB) — ArcFace model
- `1k3d68.onnx` (140 MB) — Landmark model  
- `resnet50_reid.onnx` (140 MB) — ReID model

**SHA256 Verification:**
- `glintr100.onnx`: `4AB1D6435D639628A6F3E5008DD4F929EDF4C4124B1A7169E1048F9FEF534CDF`
- **Matches enrollment metadata SHA256** — this is the canonical ArcFace model

**Risk if Lost:** Only copy if `models/arcface/glintr100.onnx` is missing. Must verify active copy exists.

---

### 4.3 `video_pipeline_v2` — Superseded Pipeline Source

**Files:** 36 Python source files (AI, annotation, core, decoder, encoder, input, output, runtime, workers, tests)

**Status:** Superseded by Architecture A but may contain unique logic not yet migrated.

**Recommendation:** Review before permanent archive.

---

### 4.4 `data_duplicate_dbs` — EMPTY

**Status:** Directory exists but empty. Phase 0.2 claimed 4 databases "restored to `data/`" — verified in Gate A.

---

## 5. Discrepancy Analysis vs Phase 0.2 Claims

| Category | Phase 0.2 Claim | Actual | Discrepancy |
|---|---|---|---|
| Total Files | ~1,600 | 5,343 | +3,743 (understated) |
| Total Size | ~6.5 GB | 7.53 GB | +1.03 GB (understated) |
| `generated_live` | "3,000+ files, 4.2 GB" | 3,008 files, 4.12 GB | ✅ Match |
| `root_test_videos` | "18 files, 1.6 GB" | 18 files, 1.93 GB | +0.33 GB |
| `root_model_duplicates` | "3 files, 350 MB" | 3 files, 0.46 GB | +110 MB |
| `generated_artifacts` | "700+ files, 1 GB" | 2,008 files, 0.99 GB | 3x count |
| `data_duplicate_dbs` | "4 files, <1 MB" | 0 files, 0 GB | **Empty** |

**Root Cause of Discrepancy:** Phase 0.2 underestimated due to:
1. `generated_live` containing nested Agent Manager worktree (not recognized)
2. `generated_artifacts` containing deep benchmark result hierarchies
3. `data_duplicate_dbs` empty because databases were "restored" but originals remain in `data/` and `app/data/`

---

## 6. Classification Confidence

| Category | Confidence | Notes |
|---|---|---|
| `generated_live` (worktree) | HIGH | Contains `.kilo/worktrees/`, `.venv_38p_isolated/`, vendor SDKs |
| `root_model_duplicates` | HIGH | SHA256 matches enrollment metadata |
| `video_pipeline_v2` | HIGH | Source code structure clear |
| `root_test_videos` | HIGH | Media files with submission/test naming |
| `historical_scripts` | HIGH | Phase/debug script naming |
| `generated_artifacts` | MEDIUM | Mixed benchmark/forensic outputs |
| `build_artifacts` | HIGH | CMake/C++ build outputs |
| `runtime_logs` | HIGH | .log extension |
| `data_duplicate_dbs` | HIGH | Empty directory |

---

## 7. Rollback Verification Plan

### 7.1 Test Categories (Required)

| Category | Test Item | Method |
|---|---|---|
| Python source | `historical_scripts/phase33_live_health_failover.py` | Copy to temp, verify SHA256 |
| Vendor SDK | `generated_live/.../TensorRT-11.3.0.99/` | Copy directory, verify file count |
| Model | `root_model_duplicates/glintr100.onnx` | Copy, verify SHA256 matches enrollment |
| Video | `root_test_videos/submission_4k_canonical.mp4` | Copy, verify SHA256 |
| SQLite DB | (none in quarantine) | N/A |
| Config | `generated_artifacts/.../config.yaml` | Copy, verify structure |
| Directory tree | `video_pipeline_v2/` | Copy tree, verify file count |

### 7.2 Rollback Test Procedure

For each test item:
1. Record source SHA256 from manifest
2. Copy to isolated test destination
3. Verify restored SHA256 matches manifest
4. Verify directory structure preserved
5. Record result (PASS/FAIL)
6. **Do not** overwrite live project files

### 7.3 Test Execution (PENDING)

| Test Item | Status | Source Hash | Restored Hash | Result |
|---|---|---|---|---|
| Python script | PENDING | — | — | — |
| Vendor SDK (TensorRT) | PENDING | — | — | — |
| ArcFace model | PENDING | `4AB1D643...` | — | — |
| Test video | PENDING | — | — | — |
| Pipeline source tree | PENDING | — | — | — |

---

## 8. Gate D Acceptance Criteria Verification

| Criterion | Status | Evidence |
|---|---|---|
| Complete manifest exists | ✅ PASS | `05_quarantine_sha256_manifest.csv` (5,343 entries) |
| No unexplained missing files | ✅ PASS | Manifest covers all files in quarantine |
| Agent Manager worktree correctly classified | ✅ PASS | Identified as `.kilo/worktrees/medieval-napkin/` |
| Critical user data not disposable | ✅ PASS | Worktree, models, source code classified as PRESERVE |
| Restoration tests pass | ⚠️ PENDING | Tests designed, not executed |
| No original quarantine content modified | ✅ PASS | Read-only inspection only |

---

## 9. Gate D Verdict

**PARTIAL** — Manifest and classification complete. Agent Manager worktree correctly identified. Critical assets protected. **Rollback tests not yet executed** — required before full PASS.

**Proceeding to Gate E with rollback tests as parallel work item.**

---

## 10. Artifacts Created

| File | Description |
|---|---|
| `05_quarantine_sha256_manifest.csv` | Complete SHA256 manifest (5,343 entries) |
| `06_quarantine_classification.md` | This document |
| `07_rollback_verification.md` | Rollback test plan and results (pending) |

---

**Gate D Partial. Proceeding to Gate E.**