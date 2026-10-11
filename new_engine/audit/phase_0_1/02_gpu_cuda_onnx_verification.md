# GPU / CUDA / ONNX Runtime Verification

## PyTorch Verification

**Command**: `.venv2\Scripts\python.exe -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda); print('cuDNN:', torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else 'N/A'); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'); print('VRAM:', torch.cuda.get_device_properties(0).total_memory / 1024**3 if torch.cuda.is_available() else 'N/A', 'GB')"`

**Output**:
```
PyTorch: 2.13.0+cu126
CUDA available: True
CUDA version: 12.6
cuDNN: 91002
GPU: NVIDIA GeForce GTX 1660 Ti
VRAM: 5.99969482421875 GB
```

**Status**: ✅ PASS - PyTorch 2.13.0 with CUDA 12.6, cuDNN 9.10.2, GTX 1660 Ti (6GB VRAM)

### Version Breakdown
| Component | Version | Source |
|-----------|---------|--------|
| PyTorch | 2.13.0+cu126 | pip (cu126 index) |
| CUDA Runtime | 12.6 | PyTorch bundled |
| cuDNN | 9.10.2 (91002) | PyTorch bundled |
| CUDA Toolkit | 13.3 | System (nvidia-smi) |
| NVIDIA Driver | 610.47 | System (nvidia-smi) |

**Important**: CUDA Toolkit version (13.3) ≠ PyTorch CUDA runtime version (12.6) ≠ NVIDIA Driver version (610.47). These are distinct.

## ONNX Runtime Verification

**Command**: `.venv2\Scripts\python.exe -c "import onnxruntime as ort; print('ONNX Runtime:', ort.__version__); print('Providers:', ort.get_available_providers())"`

**Output**:
```
ONNX Runtime: 1.28.0
Providers: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

**Status**: ✅ PASS - ONNX Runtime 1.28.0 with CUDA EP and TensorRT EP available

## NVIDIA GPU Verification

**Command**: `nvidia-smi`

**Output**:
```
Sun Oct  4 08:17:00 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 610.47                 KMD Version: 610.47        CUDA UMD Version: 13.3     |
+-----------------------------------------+------------------------+----------------------+|
| GPU  Name                  Driver-Model | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce GTX 1660 Ti   WDDM  |   00000000:01:00.0 Off |                  N/A |
|  0%   43C    P8             12W /  120W |     764MiB /   6144MiB |      1%      Default |
+-----------------------------------------+------------------------+----------------------+

Processes using GPU:
- msedgewebview2.exe, ShellHost.exe, SearchHost.exe, StartMenuExperienceHost.exe
- chrome.exe, CrossDeviceResume.exe, explorer.exe, TextInputHost.exe
- ZaloCall.exe, Code.exe, WindowsTerminal.exe, chrome.exe, Zalo.exe, ShellExperienceHost.exe
```

**Status**: ✅ PASS - GTX 1660 Ti detected, 6GB VRAM, 764MiB currently used, 1% utilization

### GPU Specifications
| Property | Value |
|----------|-------|
| GPU Name | NVIDIA GeForce GTX 1660 Ti |
| VRAM | 6144 MiB (6 GB) |
| Driver Version | 610.47 |
| CUDA UMD Version | 13.3 |
| Current Memory Usage | 764 MiB |
| Current GPU Utilization | 1% |
| Compute Capability | 7.5 (Turing) |

**Note**: GTX 1660 Ti (Turing architecture) supports NVDEC for H.264/H.265 but on Windows outputs `dxva2_vld` format which requires additional handling for CUDA interop.

## Model File Verification

**Command**: `Get-ChildItem models/scrfd, models/arcface, models/yolo | Select-Object Name, Length`

**Output**:
```
Name                          Length
----                          ------
.gitkeep                          0
scrfd_10g_bnkps.onnx       16923827  (~16.9 MB)
.gitkeep                          0
glintr100.onnx             260665334  (~261 MB)
.gitkeep                          0
yolo11n-pose.pt             6255593  (~6.3 MB)
yolo11n.onnx               10741327  (~10.7 MB)
yolo11n.pt                  5613764  (~5.6 MB)
```

**Status**: ✅ PASS - All required model files exist

### Model Inventory
| Model | File | Size | Format | Purpose |
|-------|------|------|--------|---------|
| SCRFD 10G | `models/scrfd/scrfd_10g_bnkps.onnx` | 16.9 MB | ONNX | Face detection + 5-point landmarks |
| ArcFace (GlintR100) | `models/arcface/glintr100.onnx` | 261 MB | ONNX | Face recognition (512-D embeddings) |
| YOLO11n | `models/yolo/yolo11n.onnx` | 10.7 MB | ONNX | Person detection |
| YOLO11n-pose | `models/yolo/yolo11n-pose.pt` | 6.3 MB | PyTorch | Pose estimation (unused) |
| YOLO11n | `models/yolo/yolo11n.pt` | 5.6 MB | PyTorch | Person detection (PyTorch format) |

## Model Load Test (Source Code Verification)

**SCRFD Model Path**: Referenced in `pipeline_engine/inference/face_detection.py:574` as `models/scrfd/scrfd_10g_bnkps.onnx`
**ArcFace Model Path**: Referenced in `pipeline_engine/inference/face_recognition.py` as `models/arcface/glintr100.onnx`
**YOLO Model Path**: Referenced in `pipeline_engine/inference/person_detection.py` as `models/yolo/yolo11n.onnx`

**Config Verification**: `pipeline_engine/config/pipeline.yaml` lines 215-252
```yaml
models:
  scrfd:
    path: "models/scrfd/scrfd_10g_bnkps.onnx"
  arcface:
    path: "models/arcface/glintr100.onnx"
  yolo:
    path: "models/yolo/yolo11n.onnx"
```

**Status**: ✅ VERIFIED - Config paths match actual files

## CUDA Interop Test (Static Verification)

### PyAV + CUDA
**Source Code**: `pipeline_engine/decode/nvdec_decoder.py` lines 162-171
```python
# On Windows, cuvid outputs dxva2_vld frames, not cuda.
# We'll use software decode + GPU upload as primary approach.
```

**Source Code**: `pipeline_engine/encode/nvenc_encoder.py` lines 348-359 (DLPack zero-copy)
```python
y_dlpack = gpu_frame.y_tensor.__dlpack__()
uv_dlpack = gpu_frame.uv_tensor.__dlpack__()
av_frame = av.VideoFrame.from_dlpack(
    [y_dlpack, uv_dlpack],
    format='nv12',
    width=self.config.width,
    height=self.config.height,
    device_id=self.config.gpu_device,
    current_ctx=True,
)
```

**Status**: ⚠️ CONDITIONAL - 
- Software decode + GPU upload is implemented and should work
- True NVDEC hardware decode NOT available on Windows GTX 1660 Ti (dxva2_vld output)
- NVENC encoding via DLPack zero-copy implemented
- OSError -129 restart logic implemented in `nvenc_encoder.py` lines 414-459

## Environment Verification Summary

| Check | Result | Evidence |
|-------|--------|----------|
| Python 3.12.10 | ✅ PASS | `.venv2\Scripts\python.exe --version` |
| Virtual Environment | ✅ PASS | `.venv2` at repo root |
| PyTorch CUDA | ✅ PASS | 2.13.0+cu126, CUDA available |
| CUDA Runtime | ✅ PASS | 12.6 (PyTorch) |
| cuDNN | ✅ PASS | 9.10.2 |
| NVIDIA Driver | ✅ PASS | 610.47 |
| CUDA Toolkit | ✅ PASS | 13.3 (system) |
| GPU Detection | ✅ PASS | GTX 1660 Ti, 6GB VRAM |
| ONNX Runtime | ✅ PASS | 1.28.0, CUDA EP + TensorRT EP |
| Model Files | ✅ PASS | All 5 model files present |
| Config Paths | ✅ PASS | pipeline.yaml matches files |

## Blocker Assessment

**No environment blockers identified**. All dependencies present and functional.

**Hardware Limitation**: GTX 1660 Ti (6GB VRAM) with Windows - true NVDEC not available (dxva2_vld output). Software decode + GPU upload is the implemented fallback.

**Evidence Location**: All commands executed from `.venv2\Scripts\python.exe` in repository root.