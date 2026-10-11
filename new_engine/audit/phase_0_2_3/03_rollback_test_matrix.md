# Gate A — Rollback Test Matrix

**Date:** 2026-10-04  
**Phase:** 0.2.3 — Gate A  
**Classification:** SOURCE-VERIFIED / RUNTIME-VERIFIED

---

## 1. Executive Summary

Seven-category rollback test matrix for quarantine restoration verification. Each category targets a critical asset type from the quarantine manifest.

---

## 2. Test Categories

| # | Category | Manifest Category | Test Item | Source Path | Criticality |
|---|---|---|---|---|---|
| 1 | Python Source/Script | `historical_scripts` | `phase33_live_health_failover.py` | `historical_scripts/phase33_live_health_failover.py` | HIGH |
| 2 | Vendor SDK | `generated_live` | TensorRT directory | `generated_live/live/.kilo/worktrees/medieval-napkin/TensorRT-11.3.0.99/` | **CRITICAL** |
| 3 | Model | `root_model_duplicates` | ArcFace `glintr100.onnx` | `root_model_duplicates/glintr100.onnx` | **CRITICAL** |
| 4 | Video | `root_test_videos` | `submission_4k_canonical.mp4` | `root_test_videos/submission_4k_canonical.mp4` | HIGH |
| 5 | SQLite Snapshot | (from Phase 0.2.2) | `app/data/attendance.db` | N/A (use backup API) | **CRITICAL** |
| 6 | Configuration | `generated_artifacts` | Sample config | `generated_artifacts/artifacts/phase8_encoder/...` | HIGH |
| 7 | Directory Tree | `video_pipeline_v2` | Pipeline source tree | `video_pipeline_v2/` | HIGH |

---

## 3. Test Procedure Template

For each test item:

### 3.1 Pre-Test
1. Record source quarantine path.
2. Verify source SHA256 from manifest.
3. Create isolated temporary destination: `C:\temp\rollback_test\<category>\`
4. Ensure destination is empty.

### 3.2 Restoration
```powershell
# Copy operation (no move to preserve quarantine)
Copy-Item -Path "<source>" -Destination "<destination>" -Recurse
```

### 3.3 Verification
1. Compute SHA256 of restored file(s).
2. Compare with manifest hash.
3. Verify file size matches.
4. For directories: verify file count and recursive structure.
5. Run format-specific validation:
   - Python: syntax check (`python -m py_compile`)
   - Video: probe with ffprobe
   - Model: load with ONNX Runtime (CPU)
   - SQLite: `PRAGMA integrity_check`
   - SDK: verify key headers/libs present

### 3.4 Recording
| Test ID | Category | Item | Source Hash | Restored Hash | Size Match | Structure Match | Validation | Result |
|---|---|---|---|---|---|---|---|---|
| RB-01 | Python Script | phase33_live_health_failover.py | [manifest] | [computed] | Y/N | Y/N | Syntax OK | PASS/FAIL |
| RB-02 | Vendor SDK | TensorRT/ | [manifest] | [computed] | Y/N | Y/N | Key libs present | PASS/FAIL |
| RB-03 | Model | glintr100.onnx | [manifest] | [computed] | Y/N | N/A | ONNX load OK | PASS/FAIL |
| RB-04 | Video | submission_4k_canonical.mp4 | [manifest] | [computed] | Y/N | N/A | ffprobe OK | PASS/FAIL |
| RB-05 | SQLite | attendance.db | [backup] | [computed] | Y/N | Schema OK | Integrity OK | PASS/FAIL |
| RB-06 | Config | phase8_encoder/... | [manifest] | [computed] | Y/N | Structure OK | Parse OK | PASS/FAIL |
| RB-07 | Dir Tree | video_pipeline_v2/ | [manifest] | [computed] | Y/N | 36 files | Structure OK | PASS/FAIL |

---

## 4. Category-Specific Procedures

### Category 1: Python Source/Script (RB-01)
- **Source:** `historical_scripts/phase33_live_health_failover.py`
- **Manifest Hash:** `257D34C5F2779057B9317CFE9EB3EDE93249A43C459A7BD810AC4891542F5624`
- **Validation:** `python -m py_compile <restored_file>`

### Category 2: Vendor SDK — TensorRT (RB-02)
- **Source:** `generated_live/live/.kilo/worktrees/medieval-napkin/TensorRT-11.3.0.99/`
- **Validation:** Verify `bin/`, `lib/`, `include/` directories exist; check `lib/nvinfer.lib` present

### Category 3: Model — ArcFace (RB-03)
- **Source:** `root_model_duplicates/glintr100.onnx`
- **Manifest Hash:** `4AB1D6435D639628A6F3E5008DD4F929EDF4C4124B1A7169E1048F9FEF534CDF`
- **Validation:** Load with ONNX Runtime CPU provider: `ort.InferenceSession(model, providers=['CPUExecutionProvider'])`

### Category 4: Video (RB-04)
- **Source:** `root_test_videos/submission_4k_canonical.mp4`
- **Manifest Hash:** `9FC6A3B375B0B1646045E16E1CC1D12F6A87ABB604927A48A9C4C82D49E7C29E`
- **Validation:** `ffprobe -v error -show_format -show_streams <file>`

### Category 5: SQLite Snapshot (RB-05)
- **Source:** Create online backup of `app/data/attendance.db` using SQLite backup API
- **Validation:** 
  1. Restore to isolated path
  2. `PRAGMA integrity_check` → `ok`
  3. Verify schema matches Phase 25 (23 columns, 10 indexes, 7 constraints)
  4. Verify record count (108)

### Category 6: Configuration (RB-06)
- **Source:** Sample from `generated_artifacts/artifacts/phase8_encoder/`
- **Validation:** Parse as YAML/JSON, verify structure

### Category 7: Directory Tree (RB-07)
- **Source:** `video_pipeline_v2/`
- **Validation:** Verify 36 files, recursive structure preserved

---

## 6. Execution Constraints

| Constraint | Enforcement |
|---|---|
| No live destination overwrite | Test destination: `C:\temp\rollback_test\` (outside project) |
| No quarantine source modification | COPY only, never MOVE |
| SQLite test uses backup API | Never copy active DB files |
| Isolated test environment | `C:\temp\rollback_test\` cleaned between tests |
| No GPU requirement | CPU-only validation |

---

## 7. Success Criteria

A test PASSES only if ALL conditions met:
1. ✅ Restored SHA256 matches manifest exactly
2. ✅ Restored file size matches manifest exactly
3. ✅ For directories: file count matches, recursive structure preserved
4. ✅ Format-specific validation passes
4. ✅ No quarantine source files modified
5. ✅ Test destination is isolated (not live project paths)

---

## 7. Test Execution Schedule

| Test ID | Category | Scheduled | Status |
|---|---|---|---|
| RB-01 | Python Script | Gate A | PENDING |
| RB-02 | Vendor SDK (TensorRT) | Gate A | PENDING |
| RB-03 | Model (ArcFace) | Gate A | PENDING |
| RB-04 | Video | Gate A | PENDING |
| RB-05 | SQLite Snapshot | Gate A | PENDING |
| RB-06 | Configuration | Gate A | PENDING |
| RB-07 | Directory Tree | Gate A | PENDING |

---

**Test matrix complete. Proceeding to execution.**