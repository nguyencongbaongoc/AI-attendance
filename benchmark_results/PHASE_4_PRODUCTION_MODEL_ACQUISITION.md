# PHASE 4 — PRODUCTION MODEL ACQUISITION & CONTRACT VALIDATION

**Timestamp:** 2026-08-16T17:56:34.688491

**VERDICT:** PASS

## Model Inventory

| Model ID | Filename | Path | Size | SHA256 Match | Integrity | Contract | Registry |
|----------|----------|------|------|--------------|-----------|----------|----------|
| scrfd | scrfd_10g_bnkps.onnx | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\scrfd\scrfd_10g_bnkps.onnx | 16.14 MB | True | VALID | VERIFIED | available |
| arcface | glintr100.onnx | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\arcface\glintr100.onnx | 248.59 MB | True | VALID | VERIFIED | available |
| landmark_1k3d68 | 1k3d68.onnx | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\landmark\1k3d68.onnx | 136.95 MB | True | VALID | VERIFIED | available |
| reid | resnet50_reid.onnx | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\reid\resnet50_reid.onnx | 89.60 MB | True | VALID | VERIFIED | available |
| yolo_person | yolo11n.pt | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\yolo\yolo11n.pt | 5.35 MB | True | VALID | VERIFIED | available |
| yolo_pose | yolo11n-pose.pt | C:\Users\Nguyen Cong Thong\Desktop\AI attendance\models\yolo\yolo11n-pose.pt | 5.97 MB | True | VALID | VERIFIED | available |

## SHA256 Verification

| Model | Expected SHA256 | Actual SHA256 | Match |
|-------|-----------------|---------------|-------|
| scrfd | `5838f7fe053675b1...` | `5838f7fe053675b1...` | YES |
| arcface | `4ab1d6435d639628...` | `4ab1d6435d639628...` | YES |
| landmark_1k3d68 | `df5c06b8a0c12e42...` | `df5c06b8a0c12e42...` | YES |
| reid | `09d398902020205d...` | `09d398902020205d...` | YES |
| yolo_person | `0ebbc80d4a7680d1...` | `0ebbc80d4a7680d1...` | YES |
| yolo_pose | `869e83fcdffdc737...` | `869e83fcdffdc737...` | YES |

## ONNX Integrity

| Model | Valid | Opset | IR Version | Inputs | Outputs |
|-------|-------|-------|------------|--------|--------|
| scrfd | YES | 11 | 6 | 1 | 9 |
| arcface | YES | 11 | 6 | 1 | 1 |
| landmark_1k3d68 | YES | 12 | 7 | 1 | 1 |
| reid | YES | 17 | 8 | 1 | 1 |

## YOLO Integrity

| Model | Load Success | Model Type | Task Type |
|-------|--------------|------------|-----------|
| yolo_person | YES | yolo11n | detect |
| yolo_pose | YES | yolo11n | pose |

## Registry Resolution

- Registered: 6/6
- Present: 6/6
- Verified: 6/6

## Contract Validation

| Model | Input Size | Output | Status |
|-------|------------|--------|--------|
| scrfd | 960 × 960 | Face boxes + 5 keypoints | VERIFIED |
| arcface | 112 × 112 | 512D embedding | VERIFIED |
| landmark_1k3d68 | 192 × 192 | 68 3D landmarks | VERIFIED |
| reid | 256 × 128 | 2048D embedding | VERIFIED |
| yolo_person | 640 × 640 | Person detection | VERIFIED |
| yolo_pose | 640 × 640 | 17 keypoints | VERIFIED |

## Safety Verification

- Camera accessed: NO
- MediaMTX started: NO
- RTMP accessed: NO
- RTSP accessed: NO
- FFmpeg streaming: NO
- IPC started: NO
- Legacy production code copied: NO
- Model files modified: NO

## Files Created

- `app/models/validation.py` - Model validation module
- `tests/unit/test_models_validation.py` - Phase 4 unit tests
- `scripts/check_model_hashes.py` - Hash verification script
- `benchmark_results/PHASE_4_PRODUCTION_MODEL_ACQUISITION.md` - This report
- `benchmark_results/PHASE_4_PRODUCTION_MODEL_ACQUISITION.json` - JSON report
- `benchmark_results/PHASE_4_MODEL_INVENTORY.json` - Model inventory

## Files Modified

- `models/arcface/glintr100.onnx` - Copied from legacy project
- `models/landmark/1k3d68.onnx` - Copied from legacy project
- `models/reid/resnet50_reid.onnx` - Copied from legacy project

## Provenance

All six production models were imported from the legacy project without modification.
SHA256 hashes were verified against the expected values from the registry.

---

**READY FOR NEXT PHASE:** YES
