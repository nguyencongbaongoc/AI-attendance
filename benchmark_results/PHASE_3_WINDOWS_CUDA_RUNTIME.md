# PHASE 3 — WINDOWS NVIDIA CUDA RUNTIME VALIDATION

## Benchmark Report

**Generated:** 2026-08-16T17:01:00.595802
**Verdict:** PARTIAL

> **Key distinction:**
> - **CUDA RUNTIME FOUNDATION = PASS** (all runtime components verified)
> - **PRODUCTION MODEL RUNTIME = BLOCKED** (all 6 production models MISSING)

---

## Summary

This phase validates the complete Windows NVIDIA AI runtime stack.
The CUDA runtime foundation is fully validated. Production ONNX model
runtime proof is BLOCKED because all six production model files are
still MISSING from disk (not downloaded).

---

## 1. Environment

| Property | Value |
|----------|-------|
| Windows Version | Windows-11-10.0.26200-SP0 |
| Architecture | AMD64 |
| Python Version | 3.12.10 |
| Python Executable | `c:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv\Scripts\python.exe` |
| Virtual Environment | Active |
| Venv Path | `c:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv` |

---

## 2. NVIDIA

| Property | Value |
|----------|-------|
| GPU Name | NVIDIA GeForce GTX 1660 Ti |
| Driver Version | 610.47 |
| CUDA Runtime (UMD) | 13.3 |
| CUDA Toolkit (nvcc) | 13.3 |

---

## 3. CUDA

### CUDA Toolkit
- nvcc version: `13.3`

### CUDA Driver (nvidia-smi)
- CUDA UMD Version: `13.3`
- Driver Version: `610.47`

---

## 4. cuDNN

- cuDNN Version: cuDNN 91.2 (bundled with torch)
- Note: cuDNN is bundled with PyTorch (cudnn64_9.dll in torch/lib)

---

## 5. PyTorch

| Property | Value |
|----------|-------|
| Version | 2.13.0+cu126 |
| CUDA Version (compiled) | 12.6 |
| CUDA Available | True |
| Device Count | 1 |
| Device Name | NVIDIA GeForce GTX 1660 Ti |
| Compute Capability | 7.5 |
| Total Memory | 6143 MB |
| CUDA Tensor Operation | PASS |
| Operation Output Shape | (100, 100) |
| Operation Elapsed | 200.93 ms |

### PyTorch CUDA Operation Verification

```
# CPU tensor → CUDA tensor → CUDA matmul → CPU result
x = torch.randn(100, 100).cuda()
y = torch.randn(100, 100).cuda()
z = torch.matmul(x, y)
result = z.cpu()
# Result shape: (100, 100)
# Elapsed: 200.93 ms
```

**Status:** PASS

---

## 6. ONNX Runtime

| Property | Value |
|----------|-------|
| Version | 1.28.0 |
| Package | onnxruntime-gpu |
| Available Providers | ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider'] |
| CUDA EP Registered | True |
| CPU EP Registered | True |
| TensorRT EP Registered | True |

---

## 7. Provider Registration

- CUDAExecutionProvider: REGISTERED ✅
- CPUExecutionProvider: REGISTERED ✅
- TensorrtExecutionProvider: REGISTERED ✅ (bonus)

> ⚠️ Note: Provider registration only proves the EP is available in
> the ORT build. Session creation and actual inference are validated below.

---

## 8. CUDA EP Session Creation

| Property | Value |
|----------|-------|
| Success | True |
| Session Providers | ['CUDAExecutionProvider', 'CPUExecutionProvider'] |
| CUDA EP First | True |
| Error | None |

**Status:** PASS

---

## 9. Actual ONNX CUDA Inference

| Property | Value |
|----------|-------|
| Model Type | Minimal non-production test model (MatMul) |
| Production Model | NOT USED — SCRFD is MISSING |
| Providers | ['CUDAExecutionProvider', 'CPUExecutionProvider'] |
| Input Shape | [1, 3, 3] |
| Output Shape | [1, 3, 3] |
| Output Dtype | float32 |
| Inference Success | True |
| Elapsed | 9.179 ms |
| Error | None |

### ⚠️ Production Model Runtime: BLOCKED

SCRFD production ONNX model (`scrfd_10g_bnkps.onnx`) is MISSING.
SHA256 could not be verified against production model.
All 6 production models are MISSING from disk.

The runtime itself IS validated using a minimal MatMul ONNX test model.
This proves: ONNX → CUDA EP → actual GPU execution → output.

**Runtime inference status:** PASS (using minimal non-production model)
**Production model inference status:** BLOCKED (all models missing)

---

## 10. CPU Fallback

| Property | Value |
|----------|-------|
| CPU Session Providers | ['CPUExecutionProvider'] |
| CPU Inference Success | True |
| Output Shape | [1, 3, 3] |
| Elapsed | 0.11 ms |

### Provider Priority Logic

```
CUDA available → CUDA preferred (CUDA EP in first position)
CUDA disabled  → CPU fallback (CPUExecutionProvider only)
CUDA unavailable → CPU fallback (CPUExecutionProvider only)
```

**Status:** PASS

---

## 11. Model Availability

| Model | Status | SHA256 | Path |
|--------|--------|--------|------|
| scrfd | MISSING | `N/A` | `hong\Desktop\AI attendance\models\scrfd\scrfd_10g_bnkps.onnx` |
| arcface | MISSING | `N/A` | `ng Thong\Desktop\AI attendance\models\arcface\glintr100.onnx` |
| landmark_1k3d68 | MISSING | `N/A` | `Cong Thong\Desktop\AI attendance\models\landmark\1k3d68.onnx` |
| reid | MISSING | `N/A` | `g Thong\Desktop\AI attendance\models\reid\resnet50_reid.onnx` |
| yolo_person | MISSING | `N/A` | `uyen Cong Thong\Desktop\AI attendance\models\yolo\yolo11n.pt` |
| yolo_pose | MISSING | `N/A` | `Cong Thong\Desktop\AI attendance\models\yolo\yolo11n-pose.pt` |

### Model SHA256 Reference Values

| Model | Expected SHA256 | Actual SHA256 | Match |
|--------|----------------|---------------|-------|
| scrfd | `5838f7fe053675b1...` | `MISSING` | ❌ BLOCKED |
| arcface | `4ab1d6435d639628...` | `MISSING` | ❌ BLOCKED |
| landmark_1k3d68 | `df5c06b8a0c12e42...` | `MISSING` | ❌ BLOCKED |
| reid | `09d398902020205d...` | `MISSING` | ❌ BLOCKED |
| yolo_person | `0ebbc80d4a7680d1...` | `MISSING` | ❌ BLOCKED |
| yolo_pose | `869e83fcdffdc737...` | `MISSING` | ❌ BLOCKED |

---

## 12. GPU/RAM Observations

- GPU Memory Before: ~8.2 MB allocated
- GPU Memory After: ~8.24 MB allocated
- GPU Memory Delta: ~0.04 MB (minimal model)
- VRAM Total: 6143 MB
- GPU Utilization: ~5% (idle)
- Temperature: 49°C
- Power: ~14.9 W

---

## 13. Tests

### Phase 3 Unit Tests

| Category | Tests |
|----------|-------|
| NVIDIA GPU Validation | 5 passed |
| PyTorch CUDA | 7 passed |
| ONNX Runtime Validation | 5 passed |
| CUDA EP Session Creation | 2 passed |
| ONNX CUDA Inference | 4 passed |
| CPU Fallback | 3 passed |
| cuDNN Detection | 2 passed |
| Visual C++ Runtime | 1 passed |
| CUDA Toolkit Detection | 2 passed |
| Model Availability | 7 passed |
| Runtime Snapshot | 3 passed |
| Runtime Error Classification | 2 passed |
| Phase 3 Safety / Phase Boundary | 7 passed |
| **Total** | **50 passed, 0 failed** |

### Regression Tests (Phase 1 + Phase 2)

| Phase | Tests | Status |
|-------|-------|--------|
| Phase 1 | Phase 1 files unchanged | PASS |
| Phase 2 | Phase 2 files unchanged | PASS |

### Full Suite Summary

| Metric | Count |
|--------|-------|
| Total Tests | 211 |
| Passed | 206 |
| Failed | 0 |
| Skipped | 5 |

---

## 14. Modified Files

No Phase 1 or Phase 2 files were modified. Only new files were created
for Phase 3, plus `requirements/windows.txt` was updated with AI runtime
package versions.

---

## 15. Limitations

| Item | Status | Detail |
|------|--------|--------|
| SCRFD production model | BLOCKED | File `scrfd_10g_bnkps.onnx` not present on disk |
| ArcFace production model | BLOCKED | File `glintr100.onnx` not present on disk |
| 1K3D68 production model | BLOCKED | File `1k3d68.onnx` not present on disk |
| ReID production model | BLOCKED | File `resnet50_reid.onnx` not present on disk |
| YOLO Person model | BLOCKED | File `yolo11n.pt` not present on disk |
| YOLO Pose model | BLOCKED | File `yolo11n-pose.pt` not present on disk |
| CUDA Runtime Foundation | VERIFIED | All components PASS |
| Production Model Inference | BLOCKED | Models not downloaded (correct for Phase 3) |

---

## 16. CUDA/cuDNN Compatibility

| Component | Version | Status |
|-----------|---------|--------|
| NVIDIA Driver (KMD) | 610.47 | VERIFIED |
| CUDA UMD | 13.3 | VERIFIED (via nvidia-smi) |
| CUDA Toolkit (nvcc) | 13.3 | VERIFIED |
| PyTorch CUDA | 12.6 | VERIFIED (bundled cudart64_12.dll) |
| cuDNN | cuDNN 91.2 (bundled with torch) | VERIFIED (bundled with torch) |
| ONNX Runtime | 1.28.0 | VERIFIED |
| ONNX Runtime CUDA EP | CUDAExecutionProvider | VERIFIED |

### Compatibility Analysis

The NVIDIA driver (610.47) reports CUDA UMD version 13.3,
and the CUDA toolkit (nvcc) is version 13.3.
PyTorch 2.13.0+cu126 bundles its own CUDA 12.6 runtime,
which is backward-compatible with the driver.
ONNX Runtime 1.28.0 GPU build includes CUDAExecutionProvider
which successfully loads and executes on the GPU.
cuDNN 9.10.2 is bundled with PyTorch and used by CUDA EP.

---

## Final Verdict

## PARTIAL

### CUDA RUNTIME FOUNDATION: **PASS**

All runtime components are verified and working:
- ✅ Windows 11 detected
- ✅ NVIDIA GeForce GTX 1660 Ti (6144 MB VRAM)
- ✅ NVIDIA Driver 610.47
- ✅ CUDA runtime (13.3 via nvidia-smi, 12.6 via torch)
- ✅ CUDA Toolkit 13.3 (nvcc)
- ✅ cuDNN 9.10.2 (bundled with torch)
- ✅ PyTorch 2.13.0+cu126 with CUDA tensor operation
- ✅ ONNX Runtime 1.28.0 (onnxruntime-gpu)
- ✅ CUDAExecutionProvider registered
- ✅ CUDA EP session creation succeeds
- ✅ ONNX CUDA inference succeeds (minimal test model)
- ✅ CPU fallback inference succeeds
- ✅ Visual C++ runtime available
- ✅ FFmpeg 9.0 available

### PRODUCTION MODEL RUNTIME: **BLOCKED**

All six production ONNX/PyTorch models are MISSING from disk.
This is the correct state for Phase 3 — models are not downloaded
until an explicitly dedicated phase (Phase 4+ model acquisition).
The CUDA runtime itself is fully validated using a minimal non-production
test model, proving the ONNX → CUDA EP → GPU execution pipeline works.

### Phase Boundary Compliance

| Check | Status |
|-------|--------|
| No MediaMTX started | ✅ |
| No RTMP | ✅ |
| No RTSP | ✅ |
| No StreamKeeper | ✅ |
| No CameraCapture | ✅ |
| No IPC | ✅ |
| No real camera accessed | ✅ |
| No FFmpeg streaming | ✅ |
| No tracking | ✅ |
| No identity | ✅ |
| No attendance | ✅ |
| No line crossing | ✅ |
| No stranger detection | ✅ |
| No annotation | ✅ |
| No API | ✅ |
| No database | ✅ |
| No AI model files modified | ✅ |
| No legacy production code modified | ✅ |

### Ready for Phase 4

YES — The Windows NVIDIA CUDA runtime stack is fully validated.
The production model acquisition and runtime will be the subject of
a later phase that handles model downloads.

---

*Generated by Phase 3 — CUDA Runtime Validation Script*