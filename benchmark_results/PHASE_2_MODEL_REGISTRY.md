# PHASE 2 — MODEL REGISTRY & SINGLE SOURCE OF TRUTH

## Benchmark Report

**Generated:** 2026-08-16
**Verdict:** PASS

---

## Registry Architecture

The Model Registry is implemented as a thread-safe singleton (`ModelRegistry`) that serves as the single source of truth for all model metadata in the project.

```
app/models/
├── __init__.py          # Public API exports
├── contracts.py         # ModelDefinition dataclasses (Pydantic-based)
├── exceptions.py        # Model-related exceptions
├── hashing.py           # SHA256 hash computation & verification
└── registry.py          # ModelRegistry singleton
```

---

## Registered Models

Six production models are registered with complete metadata contracts:

1. **SCRFD Face Detector** (`scrfd`)
   - Filename: `scrfd_10g_bnkps.onnx`
   - Format: ONNX
   - Provider: ONNX Runtime
   - Input Shape: `(1, 3, 960, 960)`
   - Output Contract: `detection` with 5 keypoints per face
   - Thresholds: Confidence `0.55`, NMS `0.45`
   - Reference SHA256: `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91`

2. **ArcFace Face Recognition** (`arcface`)
   - Filename: `glintr100.onnx`
   - Format: ONNX
   - Provider: ONNX Runtime
   - Input Shape: `(1, 3, 112, 112)`
   - Output Contract: `embedding` (512-dimensional)
   - Reference SHA256: `4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf`

3. **1K3D68 Face Landmark** (`landmark_1k3d68`)
   - Filename: `1k3d68.onnx`
   - Format: ONNX
   - Provider: ONNX Runtime
   - Input Shape: `(1, 3, 192, 192)`
   - Output Contract: `landmarks` (68 3D landmarks)
   - Reference SHA256: `df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc`

4. **ResNet50 ReID** (`reid`)
   - Filename: `resnet50_reid.onnx`
   - Format: ONNX
   - Provider: ONNX Runtime
   - Input Shape: `(1, 3, 256, 128)`
   - Output Contract: `embedding` (2048-dimensional)
   - Reference SHA256: `09d398902020205dd4aa80495b2a8fceecd64ba610e6b72afc1f93965c9613d2`

5. **YOLO11n Person Detector** (`yolo_person`)
   - Filename: `yolo11n.pt`
   - Format: PyTorch
   - Provider: Ultralytics
   - Input Shape: `(1, 3, 640, 640)`
   - Output Contract: `detection` (person class)
   - Reference SHA256: `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`

6. **YOLO11n-Pose** (`yolo_pose`)
   - Filename: `yolo11n-pose.pt`
   - Format: PyTorch
   - Provider: Ultralytics
   - Input Shape: `(1, 3, 640, 640)`
   - Output Contract: `pose` (17 COCO keypoints)
   - Reference SHA256: `869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`

---

## Model Availability & SHA256 Status

Since model files are not downloaded in Phase 2, they are correctly marked as `MISSING` at runtime:

- **SCRFD:** `MISSING` (Expected hash: `5838f7fe...`)
- **ArcFace:** `MISSING` (Expected hash: `4ab1d643...`)
- **1K3D68:** `MISSING` (Expected hash: `df5c06b8...`)
- **ReID:** `MISSING` (Expected hash: `09d39890...`)
- **YOLO Person:** `MISSING` (Expected hash: `0ebbc80d...`)
- **YOLO Pose:** `MISSING` (Expected hash: `869e83fc...`)

The registry implements robust hash validation that detects missing files, computes actual SHA256 hashes when files are present, and flags mismatches as `HASH_MISMATCH` / `ModelStatus.CORRUPT`.

---

## Preprocessing & Output Contracts

The registry defines complete preprocessing and output contracts for all models:

- **Preprocessing:** Captures input dimensions, channel order (RGB), data type (float32), normalization parameters, resize modes, and alignment requirements (e.g., 32-pixel alignment for YOLO).
- **Output Contracts:** Captures output types (`detection`, `embedding`, `landmarks`, `pose`), embedding dimensions (512 for ArcFace, 2048 for ReID), keypoint counts (5 for SCRFD, 17 for YOLO pose), and postprocessing requirements (NMS).

---

## Versioning & Dataset Compatibility

The registry establishes a robust versioning strategy to prevent cross-model contamination in future pipelines:

- **ModelVersion:** Tracks model version, architecture, training dataset, source, contract version, and preprocessing version.
- **DatasetCompatibility:** Consumed by future `.npy` pipelines to record model ID, version, SHA256, preprocessing version, and contract version. This ensures that downstream pipelines can reject incompatible artifacts (e.g., embeddings generated with a different model version).

---

## Test Results

Comprehensive unit tests were implemented under `tests/unit/test_models_registry.py` and executed successfully:

- **Passed:** 86 tests
- **Failed:** 0 tests
- **Skipped:** 0 tests

Tests cover registry lookup, unknown model rejection, filename/path resolution, expected SHA256 metadata, missing model detection, hash mismatch detection, verified model detection (using temporary test fixtures), input/output contracts, embedding dimensions, and dataset compatibility.

---

## Files Created

The following files were created for Phase 2:

1. `app/models/__init__.py` (79 lines)
2. `app/models/contracts.py` (528 lines)
3. `app/models/exceptions.py` (72 lines)
4. `app/models/hashing.py` (165 lines)
5. `app/models/registry.py` (522 lines)
6. `tests/unit/test_models_registry.py` (648 lines)
7. `docs/benchmarks/phase2_model_registry_benchmark.md` (Markdown report)
8. `docs/benchmarks/phase2_model_registry_benchmark.json` (JSON report)
9. `benchmark_results/PHASE_2_MODEL_REGISTRY.md` (This report)
10. `benchmark_results/PHASE_2_MODEL_REGISTRY.json` (JSON report)

---

## Files Modified

No Phase 1 files were modified. The registry integrates seamlessly with Phase 1 configuration and paths modules without requiring any changes to them.

---

## Phase Boundary Verification

All phase boundary checks passed:

- **Camera accessed:** NO
- **MediaMTX started:** NO
- **FFmpeg streaming:** NO
- **AI inference executed:** NO
- **Model files modified:** NO
- **Legacy production code modified:** NO

---

## Limitations

- Production model files are currently missing from disk (as expected for Phase 2), so their runtime status is `MISSING`.
- Normalization parameters for ONNX models (SCRFD, ArcFace, 1K3D68, ReID) are marked as `None` (unverified) since they were not established in the legacy evidence. They will be verified and updated when the actual model files are available.

---

## Final Verdict

**PASS** - The Model Registry is fully implemented, verified, and ready for Phase 3.