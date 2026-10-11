# Phase 0.2 — Python GPU Model Runtime Baseline

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up (Test 1)

---

## 1. Environment Verification

| Component | Version | Status |
|-----------|---------|--------|
| Python | 3.12.10 (tags/v3.12.10:0cc8128, Apr 8 2025) | ✅ PASS |
| PyTorch | 2.13.0+cu126 | ✅ PASS |
| CUDA Runtime | 12.6 (via PyTorch) | ✅ PASS |
| cuDNN | 9.10.2 (bundled with PyTorch) | ✅ PASS |
| ONNX Runtime | 1.28.0 | ✅ PASS |
| ONNX Runtime Providers | CUDAExecutionProvider, TensorrtExecutionProvider, CPUExecutionProvider | ✅ PASS |
| GPU | NVIDIA GeForce GTX 1660 Ti (6.0 GB VRAM) | ✅ PASS |
| Driver | 610.47 (Windows) | ✅ PASS |
| NumPy | 2.5.2 | ✅ PASS |
| OpenCV | 5.0.0 | ✅ PASS |
| PyAV (av) | 18.1.0 | ✅ PASS |
| FFmpeg | 9.0.2-full_build-www.gyan.dev | ✅ PASS |

**Virtual Environment:** `.venv2` (active, 5.9 GB)

---

## 2. GPU Verification

```python
import torch
torch.cuda.is_available()  # True
torch.cuda.device_count()  # 1
torch.cuda.get_device_properties(0)
# name: 'NVIDIA GeForce GTX 1660 Ti'
# total_memory: 6442450944 (6.0 GB)
# major: 7, minor: 5 (Turing architecture)
```

**Note:** GTX 1660 Ti does NOT support NVDEC hardware decoding (Turing NVENC only). PyAV will use software decode (dxva2_vld or software) with GPU upload. This is a known limitation documented in Phase 0.1.

---

## 3. Model Session Initialization

### 3.1 SCRFD (Face Detection)
- **Path:** `models/scrfd/scrfd_10g_bnkps.onnx`
- **Size:** 16.1 MB
- **Providers:** CUDAExecutionProvider, CPUExecutionProvider
- **Input:** `input.1` — shape `[1, 3, ?, ?]` (dynamic H/W), type `tensor(float)`
- **Outputs:** 9 outputs — bbox, score, landmark at 3 strides (8, 16, 32)
- **Inference Test:** ✅ SUCCESS (dummy 640×640 input)

### 3.2 ArcFace (Face Recognition)
- **Path:** `models/arcface/glintr100.onnx`
- **Size:** 248.6 MB
- **Providers:** CUDAExecutionProvider, CPUExecutionProvider
- **Input:** `input.1` — shape `[None, 3, 112, 112]`, type `tensor(float)`
- **Output:** `1333` — shape `[1, 512]`, type `tensor(float)` (L2-normalized embedding)
- **Inference Test:** ✅ SUCCESS (dummy 112×112 input)

### 3.3 YOLO11n (Person Detection)
- **Path:** `models/yolo/yolo11n.onnx`
- **Size:** 10.2 MB
- **Providers:** CUDAExecutionProvider, CPUExecutionProvider
- **Input:** `images` — shape `[1, 3, 640, 640]`, type `tensor(float)`
- **Output:** `output0` — shape `[1, 84, 8400]`, type `tensor(float)` (84 = 4 bbox + 80 classes)
- **Inference Test:** ✅ SUCCESS (dummy 640×640 input)

### 3.4 Model File Integrity (SHA256)
| Model | Expected SHA256 (from enrollment metadata) | Actual File |
|-------|--------------------------------------------|-------------|
| ArcFace (glintr100.onnx) | 4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf | `models/arcface/glintr100.onnx` ✅ |
| SCRFD | 5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91 | `models/scrfd/scrfd_10g_bnkps.onnx` ✅ |

**Root duplicates removed to quarantine:** `models/glintr100.onnx`, `models/1k3d68.onnx`, `models/resnet50_reid.onnx`

---

## 4. Bootstrap Environment Check

```
$ python bootstrap.py --check

Validating environment...
Python 3.12.10 OK
CUDA available: 1 device(s)
  GPU 0: NVIDIA GeForce GTX 1660 Ti (6.0 GB VRAM)
  torch: 2.13.0+cu126 OK
  onnxruntime: 1.28.0 OK
  av: 18.1.0 OK
  numpy: 2.5.2 OK
  cv2: 5.0.0 OK
  fastapi: 0.141.1 OK
  uvicorn: 0.52.4 OK
  pydantic: 2.13.5 OK
  yaml: 6.0.3 OK
Configuration loaded from default
  Model scrfd: models\scrfd\scrfd_10g_bnkps.onnx (16.1 MB) OK
  Model arcface: models\arcface\glintr100.onnx (248.6 MB) OK
  Model yolo: models\yolo\yolo11n.onnx (10.2 MB) OK
  Camera cam1: rtsp://localhost:8554/live/cam1
  Camera cam2: rtsp://localhost:8554/live/cam2
FFmpeg: ffmpeg version 9.0.2-full_build-www.gyan.dev
Directory data: OK
Directory logs: OK
Directory recordings: OK
WARNING - Camera cam1: connection failed (will retry at runtime)
WARNING - Camera cam2: connection failed (will retry at runtime)
WARNING - MediaMTX: Not running on port 8554 (will need to start)
Environment validation PASSED
Environment check PASSED
```

---

## 5. Import Verification

| Module | Import Status |
|--------|---------------|
| `app.main` (Legacy Backend) | ✅ OK |
| `pipeline_engine.core.engine.PipelineEngine` | ✅ OK |
| `pipeline_engine.config.load_pipeline_config` | ✅ OK |
| `onnxruntime` | ✅ OK |
| `torch` | ✅ OK |
| `av` (PyAV) | ✅ OK |

---

## 6. Verdict

**TEST 1 — ENVIRONMENT: PASS**

All Python, CUDA, ONNX Runtime, and model session initializations successful. Environment is ready for pipeline execution.

**Known Limitation:** No true NVDEC hardware decoding on GTX 1660 Ti. Software decode (dxva2_vld) + GPU upload is the production path. This is documented and accepted per Architecture A.

---

## 7. Evidence Commands

```bash
# Environment check
.venv2\Scripts\python.exe bootstrap.py --check

# GPU verification
.venv2\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# ONNX providers
.venv2\Scripts\python.exe -c "import onnxruntime; print(onnxruntime.get_available_providers())"

# Model session test
.venv2\Scripts\python.exe -c "
import onnxruntime as ort, numpy as np
for m in ['models/scrfd/scrfd_10g_bnkps.onnx', 'models/arcface/glintr100.onnx', 'models/yolo/yolo11n.onnx']:
    s = ort.InferenceSession(m, providers=['CUDAExecutionProvider'])
    print(m, s.get_providers())
"

# Import test
.venv2\Scripts\python.exe -c "from app.main import create_app; print('Legacy OK')"
.venv2\Scripts\python.exe -c "from pipeline_engine.core.engine import PipelineEngine; print('Pipeline OK')"
```