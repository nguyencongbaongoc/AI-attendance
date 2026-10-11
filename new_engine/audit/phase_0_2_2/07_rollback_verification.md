# Gate D — Rollback Verification (CF-05)

**Date:** 2026-10-04  
**Phase:** 0.2.2 — Gate D (Rollback Tests)  
**Classification:** RUNTIME-VERIFIED (PENDING)

---

## 1. Executive Summary

**ROLLBACK VERIFICATION: PENDING**

Test plan designed for 5 critical categories. Tests not yet executed to preserve quarantine integrity. Test procedures documented for execution.

---

## 2. Test Categories

| # | Category | Test Item | Source Path | Criticality |
|---|---|---|---|---|
| 1 | Python Source | `phase33_live_health_failover.py` | `historical_scripts/phase33_live_health_failover.py` | MEDIUM |
| 2 | Vendor SDK | TensorRT directory | `generated_live/live/.kilo/worktrees/medieval-napkin/TensorRT-11.3.0.99/` | **CRITICAL** |
| 3 | Model | `glintr100.onnx` | `root_model_duplicates/glintr100.onnx` | **CRITICAL** |
| 4 | Video | `submission_4k_canonical.mp4` | `root_test_videos/submission_4k_canonical.mp4` | MEDIUM |
| 5 | Source Tree | `video_pipeline_v2/` | `video_pipeline_v2/` | MEDIUM |

---

## 3. Test Procedure Template

For each test item:

### 3.1 Pre-Test
1. Record source SHA256 from manifest (`05_quarantine_sha256_manifest.csv`)
2. Create isolated test destination: `C:\temp\rollback_test\<category>\`
3. Ensure destination is empty

### 3.2 Restoration
```powershell
# Example: Python script
$src = "C:\...\new_engine\audit\phase_0_2\quarantine\historical_scripts\phase33_live_health_failover.py"
$dst = "C:\temp\rollback_test\historical_scripts\phase33_live_health_failover.py"
Copy-Item $src -Destination $dst
```

### 3.3 Verification
1. Compute SHA256 of restored file
2. Compare with manifest hash
2. Verify file size matches
3. For directories: verify file count and recursive structure

### 3.4 Recording
| Test Item | Source Hash | Restored Hash | Size Match | Structure Match | Result |
|---|---|---|---|---|---|
| [item] | [from manifest] | [computed] | Y/N | Y/N | PASS/FAIL |

---

## 4. Test Execution Log (TO BE COMPLETED)

### Test 1: Python Script
- **Item:** `historical_scripts/phase33_live_health_failover.py`
- **Manifest Hash:** `257D34C5F2779057B9317CFE9EB3EDE93249A43C459A7BD810AC4891542F5624`
- **Status:** NOT EXECUTED
- **Result:** PENDING

### Test 2: Vendor SDK (TensorRT)
- **Item:** `TensorRT-11.3.0.99/` directory
- **Status:** NOT EXECUTED (large directory, ~2.3 GB)
- **Note:** Test subset of files (bin/, lib/, include/) for practicality
- **Result:** PENDING

### Test 3: ArcFace Model
- **Item:** `glintr100.onnx`
- **Manifest Hash:** `4AB1D6435D639628A6F3E5008DD4F929EDF4C4124B1A7169E1048F9FEF534CDF`
- **Matches Enrollment Metadata:** ✅ YES
- **Status:** NOT EXECUTED
- **Result:** PENDING

### Test 4: Test Video
- **Item:** `submission_4k_canonical.mp4`
- **Manifest Hash:** `9FC6A3B375B0B1646045E16E1CC1D12F6A87ABB604927A48A9C4C82D49E7C29E`
- **Status:** NOT EXECUTED
- **Result:** PENDING

### Test 5: Pipeline Source Tree
- **Item:** `video_pipeline_v2/` (36 files)
- **Status:** NOT EXECUTED
- **Result:** PENDING

---

## 5. Rollback Integrity Requirements

A rollback test PASSES only if ALL conditions met:
1. ✅ Restored file SHA256 matches manifest exactly
2. ✅ Restored file size matches manifest exactly  
3. ✅ For directories: file count matches, recursive structure preserved
4. ✅ No quarantine source files modified during test
5. ✅ Test destination is isolated (not live project paths)

---

## 6. Execution Schedule

| Test | Scheduled | Executed By | Evidence Artifact |
|---|---|---|---|
| Python script | After Gate E | [TBD] | `07_rollback_verification.md` update |
| Vendor SDK | After Gate E | [TBD] | `07_rollback_verification.md` update |
| ArcFace model | After Gate E | [TBD] | `07_rollback_verification.md` update |
| Test video | After Gate E | [TBD] | `07_rollback_verification.md` update |
| Pipeline tree | After Gate E | [TBD] | `07_rollback_verification.md` update |

---

## 6. Note on Quarantine Preservation

**All tests must use COPY operations only.** The quarantine source must remain unmodified. Test destinations must be outside the project root (e.g., `C:\temp\rollback_test\`).

---

**Rollback verification pending test execution. Document will be updated with results.**

---

## 7. Artifact Reference

This document corresponds to: `new_engine/audit/phase_0_2_2/07_rollback_verification.md`