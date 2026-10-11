# Phase 0.2.1 — Quarantine Integrity Audit

**Date:** 2026-10-04  
**Classification:** RUNTIME VERIFIED / DOCUMENTED ONLY / UNKNOWN

---

## 1. Executive Summary

**Phase 0.2 claimed ~1,600 files, ~6.5 GB quarantined.** Actual count: **5,343 files, 7.53 GB**. The discrepancy is primarily due to `generated_live/` (3,008 files, 4.12 GB) containing nested `.kilo/worktrees/` directories with full project copies. No quarantine manifest with hashes exists — rollback verification is incomplete.

---

## 2. Quarantine Inventory — Actual vs Claimed

| Category | Phase 0.2 Claim | Actual Count | Actual Size | Status |
|----------|-----------------|--------------|-------------|--------|
| Root test videos | 18 files, 1.6 GB | 18 files, 1.93 GB | ✅ MATCH (size diff: +0.3 GB) |
| Root model duplicates | 3 files, 350 MB | 3 files, 0.46 GB | ⚠️ SIZE DIFF (+110 MB) |
| Data duplicate DBs | 4 files, <1 MB | 0 files, 0 GB | ❌ EMPTY — DBs "restored" to `data/` |
| Historical scripts | 80+ files, 2 MB | 101 files, ~0 MB | ✅ MATCH |
| Generated artifacts | 700+ files, 1 GB | 2,008 files, 0.99 GB | ⚠️ COUNT DIFF (2x claimed) |
| Build artifacts | 150+ files, 10 MB | 159 files, 0.01 GB | ✅ MATCH |
| Empty directories | 2 dirs | 8 files (in 2 dirs) | ⚠️ FILES IN "EMPTY" DIRS |
| Generated live data | 3,000+ files, 4.2 GB | 3,008 files, 4.12 GB | ✅ MATCH |
| Video pipeline v2 | 36 files, 0.5 MB | 36 files, ~0 MB | ✅ MATCH |
| Runtime logs | 2 files, <1 MB | 2 files, ~0 MB | ✅ MATCH |
| **TOTAL** | **~1,600 files, ~6.5 GB** | **5,343 files, 7.53 GB** | **❌ SIGNIFICANT DISCREPANCY** |

---

## 3. Detailed Category Analysis

### 3.1 `root_test_videos/` — 18 files, 1.93 GB

**Files match Phase 0.2 list** (encoder_output.h264, real_h264.h264, submission_*.mp4, test_*.mp4, yolo11n.pt).

**Classification:** Test videos, submission outputs, one model file (yolo11n.pt). The model file should be in `models/yolo/` — this appears to be a root-level duplicate.

**Risk:** LOW — all appear to be generated/test artifacts.

**Evidence:** RUNTIME VERIFIED — file listing matches cleanup log.

---

### 3.2 `root_model_duplicates/` — 3 files, 0.46 GB

| File | SHA256 (from cleanup log) | Size |
|------|---------------------------|------|
| glintr100.onnx | 4AB1D6435D639628A6F3E5008DD4F929EDF4C4124B1A7169E1048F9FEF534CDF | ~180 MB |
| 1k3d68.onnx | DF5C06B8A0C12E422B2ED8947B8869FAA4105387F199C477AF038AA01F9A45CC | ~140 MB |
| resnet50_reid.onnx | 09D398902020205DD4AA80495B2A8FCEECD64BA610E6B72AFC1F93965C9613D2 | ~140 MB |

**Phase 0.2 claimed 350 MB; actual 460 MB.** These are the canonical model files that should be in `models/` subdirectories.

**Risk:** MEDIUM — `glintr100.onnx` is the ArcFace model (verified by enrollment metadata SHA256 match). If `models/arcface/glintr100.onnx` is missing, this is the only copy.

**Evidence:** DOCUMENTED ONLY (cleanup log hashes) — not independently hash-verified in this audit.

---

### 3.3 `data_duplicate_dbs/` — 0 files, 0 GB

**EMPTY.** Phase 0.2 claimed 4 databases quarantined then "restored to `data/`". The 4 databases exist in `data/` and `app/data/` (byte-identical pairs for 3, different for `attendance.db`).

**Risk:** HIGH — No quarantine copy exists to verify restoration integrity.

**Evidence:** RUNTIME VERIFIED — directory is empty.

---

### 3.4 `historical_scripts/` — 101 files

**Contents:** Phase/debug/fix/generate/test scripts (phase33_live_health_failover.py, phase36k_*.py, run_phase33_*.py, debug_*.py, fix_*.py, test_*.py, update_health*.py, etc.)

**Risk:** LOW — All appear to be development/debug scripts. No unique source code.

**Evidence:** RUNTIME VERIFIED — file listing.

---

### 3.5 `generated_artifacts/` — 2,008 files, 0.99 GB

**Contents:** Nested benchmark results, phase artifacts, forensic logs, runtime traces, CMake build outputs, submission video demo logs.

**Phase 0.2 claimed 700+ files.** Actual is ~3x higher due to nested benchmark result directories.

**Notable subdirectories:**
- `artifacts/` — Phase 8, 11, 36, etc. forensic logs
- `benchmark_results/` — Phase 1-8, 36k, 4, 5, 6, 7 benchmark outputs
- `phase44/` — Phase 44 runtime forensic data

**Risk:** LOW — All appear to be generated/test artifacts. However, some forensic logs may contain unique runtime evidence.

**Evidence:** RUNTIME VERIFIED — directory structure inspection.

---

### 3.6 `generated_live/` — 3,008 files, 4.12 GB ⚠️ CRITICAL

**Contents:** Contains **nested full project copies** under `.kilo/worktrees/`:
```
generated_live/live/.kilo/worktrees/medieval-napkin/
├── app/
├── pipeline_engine/
├── models/
├── .venv_38p_isolated/ (full venv)
├── TensorRT-11.3.0.99/
├── Video_Codec_SDK_13.0.37/
├── benchmark_results/
├── artifacts/
└── ... (complete project mirror)
```

**This is NOT "generated live data" — it's a full Agent Manager worktree snapshot** including vendor SDKs (TensorRT 2.3 GB, Video_Codec_SDK 3.5 MB), venv, and all source code.

**Phase 0.2 classification as "generated live data" is INCORRECT.** This appears to be a `.kilo` worktree that was caught in the cleanup.

**Risk:** **CRITICAL** — Contains:
- Vendor SDKs (TensorRT, Video_Codec_SDK) — should be in protected assets
- Full `.venv_38p_isolated/` — Python environment
- Complete source code mirrors
- If deleted, would lose isolated worktree state

**Evidence:** RUNTIME VERIFIED — directory structure shows full project mirror.

---

### 3.7 `video_pipeline_v2/` — 36 files

**Contents:** Superseded pipeline v2 source code (ai/, annotation/, core/, decoder/, encoder/, input/, output/, runtime/, workers/, tests/).

**Risk:** MEDIUM — This is **source code** for an alternative pipeline implementation. While superseded, it may contain unique logic not yet migrated.

**Evidence:** RUNTIME VERIFIED — source code files present.

---

## 4. Quarantine Manifest & Hash Verification

### 4.1 Manifest Files Found

**NO quarantine manifest file found** with:
- File inventory with SHA256 hashes
- Original paths
- Quarantine timestamps
- Restoration verification records

### 4.2 Hash Verification Status

| Category | Phase 0.2 Hashes Provided | Independent Verification |
|----------|---------------------------|--------------------------|
| Root test videos | ✅ 18 SHA256 in cleanup log | NOT TESTED |
| Root model duplicates | ✅ 3 SHA256 in cleanup log | NOT TESTED |
| Data duplicate DBs | ✅ 4 SHA256 in cleanup log | NOT TESTED (quarantine empty) |
| Historical scripts | ✅ 10 SHA256 samples in cleanup log | NOT TESTED |
| Generated artifacts | ❌ NO | NOT TESTED |
| Generated live | ❌ NO | NOT TESTED |
| Video pipeline v2 | ❌ NO | NOT TESTED |

**Conclusion:** Cannot verify quarantine integrity — no hash manifest exists for independent verification.

---

## 5. Important Quarantined Assets — Classification

| Asset | Path | Classification | Risk if Lost |
|-------|------|----------------|--------------|
| ArcFace model (glintr100.onnx) | `root_model_duplicates/glintr100.onnx` | **UNIQUE ORIGINAL** (matches enrollment metadata SHA256) | HIGH — only copy if `models/arcface/` missing |
| Video pipeline v2 source | `video_pipeline_v2/` | **SOURCE CODE** (superseded but unique) | MEDIUM |
| Agent Manager worktree | `generated_live/live/.kilo/worktrees/medieval-napkin/` | **FULL PROJECT MIRROR** (SDKs, venv, source) | **CRITICAL** — vendor SDKs, isolated environment |
| Phase forensic logs | `generated_artifacts/artifacts/` | **RUNTIME EVIDENCE** (unique forensic data) | MEDIUM |
| Benchmark results | `generated_artifacts/benchmark_results/` | **GENERATED TEST DATA** | LOW |

---

## 6. Rollback Capability Assessment

### 6.1 Phase 0.2 Claimed Rollback Tests (from `04_cleanup_execution_log.md` §6)

| Test | Command | Claimed Result |
|------|---------|----------------|
| Single file | `Move-Item quarantine/root_test_videos/yolo11n.pt models/yolo/yolo11n.pt` | ✅ Works |
| Directory | `Move-Item quarantine/video_pipeline_v2 video_pipeline_v2` | ✅ Works |
| Script | `Move-Item quarantine/historical_scripts/phase33_live_health_failover.py scripts/` | ✅ Works |
| Git restore | `git restore figma/ frontend/` | ✅ Works (from history) |

### 6.2 Actual Rollback Evidence

- **Tested on 4 samples only** (1 file, 1 directory, 1 script, 1 git restore)
- **No hash verification** after restoration
- **No test on critical assets** (model files, worktree, forensic logs)
- **No test on `generated_live/`** (4.12 GB, 3,008 files)

### 6.3 Rollback Confidence Assessment

| Asset Category | Rollback Tested? | Hash Verified? | Confidence |
|----------------|------------------|----------------|------------|
| Root test videos | 1 file (yolo11n.pt) | ❌ NO | LOW |
| Root model duplicates | ❌ NO | ❌ NO | **NONE** |
| Historical scripts | 1 script | ❌ NO | LOW |
| Video pipeline v2 | 1 directory | ❌ NO | LOW |
| Generated live (worktree) | ❌ NO | ❌ NO | **NONE** |
| Forensic logs | ❌ NO | ❌ NO | **NONE** |
| Git-tracked files | `figma/`, `frontend/` | N/A (git) | HIGH |

**Overall rollback confidence: LOW** — Only 4 trivial samples tested, no hash verification, critical assets untested.

---

## 7. Files Requiring Human Decision (Per Phase 0.2 §5)

| Item | Phase 0.2 Status | Current Assessment | Recommendation |
|------|------------------|-------------------|----------------|
| `UI/index.html` | Kept in place | Untracked, not in quarantine | Verify if active; if not, quarantine |
| `test_data/` | Kept in place | Contains unique test fixtures + fix scripts | Extract fixtures, quarantine scripts |
| `isolated_src/`, `isolated_tests/` | Kept in place | Not found in current filesystem | Investigate — may be in quarantine |
| `data/attendance_events.db`, `attendance_daily.db` | Kept in `data/` | `attendance_events.db` exists (empty); `attendance_daily.db` missing | Keep `attendance_events.db` for PipelineEngine |

---

## 8. Summary & Verdict

| Metric | Phase 0.2 Claim | Actual | Verdict |
|--------|-----------------|--------|---------|
| File count | ~1,600 | 5,343 | **UNDERCOUNTED** |
| Total size | ~6.5 GB | 7.53 GB | **UNDERCOUNTED** |
| Manifest with hashes | Implied | **NONE** | **MISSING** |
| Rollback tested | "Fully tested" | 4 samples only | **OVERSTATED** |
| Critical assets identified | Not explicitly | Worktree in `generated_live/` | **MISCLASSIFIED** |

**Quarantine integrity: PARTIALLY VERIFIED — SIGNIFICANT GAPS**

- ✅ File counts/sizes reconciled (with explanations)
- ❌ No hash manifest for independent verification
- ❌ Rollback only tested on trivial samples
- ❌ Critical asset (Agent Manager worktree) misclassified as "generated live data"
- ❌ Database quarantine empty — no verification of "restored" files

---

**End of Quarantine Integrity Audit**