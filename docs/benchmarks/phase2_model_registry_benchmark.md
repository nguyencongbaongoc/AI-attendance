# Phase 2: Model Registry Benchmark Report

**Generated:** 2026-08-16
**Phase:** 2 - Model Registry
**Status:** COMPLETE

---

## Executive Summary

Phase 2 successfully implements a single authoritative Model Registry for the Windows native AI attendance system. The registry provides a unified source of truth for all model metadata, ensuring consistency across all pipelines (IMAGE → .npy, VIDEO → .npy, LIVE CAMERA → inference).

### Key Achievements

- ✅ **86 unit tests passed** with 100% coverage of registry functionality
- ✅ **6 production models registered** with complete metadata contracts
- ✅ **SHA256 hash verification** implemented for model integrity
- ✅ **Dataset compatibility metadata** for preventing cross-model contamination
- ✅ **Phase 1 integration** with existing configuration system

---

## Test Results

### Summary

| Metric | Value |
|--------|-------|
| Total Tests | 86 |
| Passed | 86 |
| Failed | 0 |
| Warnings | 1 (Pydantic V2 deprecation - fixed) |
| Duration | 0.68s |

### Test Categories

| Category | Tests | Status |
|----------|-------|--------|
| Registry Lookup | 6 | ✅ PASS |
| Unknown Model Rejection | 3 | ✅ PASS |
| All Models Registered | 3 | ✅ PASS |
| Filename Resolution | 6 | ✅ PASS |
| Model Path Resolution | 6 | ✅ PASS |
| Expected SHA256 Metadata | 6 | ✅ PASS |
| Missing Model Detection | 3 | ✅ PASS |
| Hash Mismatch Detection | 2 | ✅ PASS |
| Verified Model Detection | 3 | ✅ PASS |
| Input Shape Metadata | 6 | ✅ PASS |
| Output Contract Metadata | 6 | ✅ PASS |
| Embedding Dimensions | 5 | ✅ PASS |
| SCRFD Contract | 5 | ✅ PASS |
| Model Version Metadata | 3 | ✅ PASS |
| Dataset Compatibility | 4 | ✅ PASS |
| Model Format and Provider | 2 | ✅ PASS |
| Required Models | 4 | ✅ PASS |
| Hash Computation | 4 | ✅ PASS |
| Registry Serialization | 2 | ✅ PASS |
| Singleton Pattern | 2 | ✅ PASS |
| Check All Models | 4 | ✅ PASS |

---

## Registered Models

### Production Models (6)

| Model ID | Display Name | Format | Provider | Required |
|----------|--------------|--------|----------|----------|
| scrfd | SCRFD Face Detector | ONNX | ONNXRUNTIME | ✅ Yes |
| arcface | ArcFace Face Recognition | ONNX | ONNXRUNTIME | ✅ Yes |
| landmark_1k3d68 | 1K3D68 Face Landmark | ONNX | ONNXRUNTIME | No |
| reid | ResNet50 ReID | ONNX | ONNXRUNTIME | No |
| yolo_person | YOLO11n Person Detector | PyTorch | ULTRALYTICS | No |
| yolo_pose | YOLO11n-Pose | PyTorch | ULTRALYTICS | No |

### Model Contracts

#### SCRFD Face Detector

| Property | Value |
|----------|-------|
| Filename | scrfd_10g_bnkps.onnx |
| Input Shape | (1, 3, 960, 960) |
| Output Type | detection |
| Keypoints | 5 per face |
| Confidence Threshold | 0.55 |
| NMS Threshold | 0.45 |
| SHA256 | 5838f7fe...b85b5b91 |

#### ArcFace Face Recognition

| Property | Value |
|----------|-------|
| Filename | glintr100.onnx |
| Input Shape | (1, 3, 112, 112) |
| Output Type | embedding |
| Embedding Dimension | 512 |
| Distance Threshold | 0.6 |
| SHA256 | 4ab1d643...f534cdf |

#### 1K3D68 Face Landmark

| Property | Value |
|----------|-------|
| Filename | 1k3d68.onnx |
| Input Shape | (1, 3, 192, 192) |
| Output Type | landmarks |
| Landmarks | 68 (3D) |
| SHA256 | df5c06b8...9a45cc |

#### ResNet50 ReID

| Property | Value |
|----------|-------|
| Filename | resnet50_reid.onnx |
| Input Shape | (1, 3, 256, 128) |
| Output Type | embedding |
| Embedding Dimension | 2048 |
| SHA256 | 09d39890...c9613d2 |

#### YOLO11n Person Detector

| Property | Value |
|----------|-------|
| Filename | yolo11n.pt |
| Input Shape | (1, 3, 640, 640) |
| Output Type | detection |
| Confidence Threshold | 0.5 |
| NMS Threshold | 0.45 |
| SHA256 | 0ebbc80d...7644ee1 |

#### YOLO11n-Pose

| Property | Value |
|----------|-------|
| Filename | yolo11n-pose.pt |
| Input Shape | (1, 3, 640, 640) |
| Output Type | pose |
| Pose Keypoints | 17 (COCO) |
| SHA256 | 869e83fc...9319dc0 |

---

## Module Structure

```
app/models/
├── __init__.py          # Public API exports
├── contracts.py         # ModelDefinition dataclasses
├── exceptions.py        # Model-related exceptions
├── hashing.py           # SHA256 hash computation
└── registry.py          # ModelRegistry singleton
```

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| app/models/__init__.py | 79 | Public API exports |
| app/models/contracts.py | 528 | ModelDefinition and related dataclasses |
| app/models/exceptions.py | 72 | Model-related exception classes |
| app/models/hashing.py | 165 | SHA256 hash computation and verification |
| app/models/registry.py | 522 | ModelRegistry singleton with 6 models |
| tests/unit/test_models_registry.py | 648 | Comprehensive unit tests |

**Total:** 2,014 lines of production code + tests

---

## Phase Boundary Compliance

### ✅ This Module Does NOT

- Start MediaMTX
- Start FFmpeg
- Access a camera
- Perform live inference
- Modify model weights

### ✅ This Module DOES

- Define model identity
- Define model file paths
- Define SHA256 hashes
- Define input shapes
- Define output contracts
- Define preprocessing requirements
- Define normalization parameters
- Define alignment requirements
- Define postprocessing requirements
- Define embedding dimensions
- Define thresholds
- Define provider requirements
- Define model versions

---

## Integration with Phase 1

The Model Registry integrates with Phase 1 configuration:

```python
from app.config.paths import get_project_paths
from app.models import get_model_registry

# Get registry (uses Phase 1 paths by default)
registry = get_model_registry()

# Get model path (integrates with Phase 1 models_dir)
model_path = registry.get_model_path("scrfd")
# Returns: C:/Users/.../models/scrfd/scrfd_10g_bnkps.onnx
```

---

## Dataset Compatibility

The registry provides dataset compatibility metadata to prevent cross-model contamination:

```python
compat = registry.get_dataset_compatibility("arcface")
# Returns:
# DatasetCompatibility(
#     model_id='arcface',
#     model_version='1.0.0',
#     model_sha256='4ab1d643...',
#     preprocessing_version='1.0',
#     contract_version='1.0',
#     embedding_dimension=512
# )
```

This ensures:
- IMAGE → .npy artifacts record model metadata
- VIDEO → .npy artifacts record model metadata
- LIVE CAMERA inference verifies model compatibility

---

## SHA256 Verification

### Reference Hashes

All models have reference SHA256 hashes from legacy evidence:

| Model | SHA256 (first 16 chars) |
|-------|-------------------------|
| SCRFD | 5838f7fe053675b1 |
| ArcFace | 4ab1d6435d639628 |
| 1K3D68 | df5c06b8a0c12e42 |
| ReID | 09d398902020205d |
| YOLO11n | 0ebbc80d4a7680d1 |
| YOLO11n-Pose | 869e83fcdffdc737 |

### Verification Status

| Status | Description |
|--------|-------------|
| VERIFIED | File exists and hash matches |
| MISSING | File does not exist |
| HASH_MISMATCH | File exists but hash differs |
| NOT_VERIFIED | File exists but no expected hash |
| NO_EXPECTED_HASH | No expected hash recorded |

---

## Next Steps

### Phase 3: Inference Engine

The Model Registry provides the foundation for Phase 3:

1. Load models using registry metadata
2. Verify model integrity before loading
3. Apply preprocessing from registry config
4. Generate outputs matching registry contract
5. Record dataset compatibility in .npy artifacts

---

## Conclusion

Phase 2 successfully establishes a single authoritative Model Registry with:

- Complete metadata for 6 production models
- SHA256 verification for model integrity
- Dataset compatibility tracking
- Comprehensive test coverage (86 tests)
- Phase 1 configuration integration

The registry is ready for Phase 3 inference engine implementation.