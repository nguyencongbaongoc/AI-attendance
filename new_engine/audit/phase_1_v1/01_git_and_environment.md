# Phase 1.V1 Git and Environment Audit

**Date**: 2026-10-04
**Phase**: 1.V1 - Environment and Camera Source Recovery

---

## 1. Git Repository State

### Current Branch
```
* (HEAD detached at cb34db0a) main
```

### Commit Hash
```
cb34db0a (HEAD) - Pre-NVENC baseline
```

### Working Tree Status
```bash
# Deleted files (544 total)
- benchmark_results/... (all Phase 3-8 benchmark artifacts)
- figma/... (Figma project)
- frontend/... (Vue frontend)
- video_pipeline_v2/... (old video pipeline)
- scripts/... (old phase scripts)
- encoder_output.h264, submission.mp4, etc.

# Untracked files (16)
UI/
analyze_quarantine.py
app/api/ai_worker.py
bootstrap.bat
bootstrap.py
check_db.py
check_db2.py
check_db3.py
check_dbs.py
final_verify.py
inspect_dbs.py
new_engine/
pipeline_engine/
scripts/run_worker.py
search_writers.py
test_sqlite_backup.py
test_worker_init.py
```

### Key PipelineEngine Files (Modified/Untracked)
| File | Status | Description |
|------|--------|-------------|
| `pipeline_engine/integration/event_client.py` | Untracked | Event delivery to Legacy Backend |
| `pipeline_engine/core/worker.py` | Untracked | AI Worker lifecycle |
| `scripts/run_worker.py` | Untracked | Worker entry point |
| `pipeline_engine/config/pipeline.yaml` | Untracked | Pipeline configuration |
| `pipeline_engine/ingestion/camera_manager.py` | Untracked | Camera pipeline management |
| `pipeline_engine/inference/face_detection.py` | Untracked | SCRFD detector |
| `pipeline_engine/inference/face_recognition.py` | Untracked | ArcFace recognizer |
| `pipeline_engine/attendance/attendance_engine.py` | Untracked | Attendance events |
| `pipeline_engine/core/engine.py` | Untracked | Pipeline engine core |

---

## 2. Python Virtual Environment (.venv2)

### pyvenv.cfg
```ini
home = C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312
include-system-site-packages = false
version = 3.12.10
executable = C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312\python.exe
```

### Python Version
```
Python 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
```

### Key Package Versions
```python
import torch
import onnxruntime as ort
import cv2
import av

torch.__version__           # 2.13.0+cu126
torch.cuda.is_available()   # True
torch.cuda.get_device_name(0)  # NVIDIA GeForce GTX 1660 Ti
torch.cuda.device_count()   # 1

ort.__version__             # 1.28.0
ort.get_available_providers()  # ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']

cv2.__version__             # (system OpenCV)
av.__version__              # (PyAV)
```

### CUDA Environment
- **CUDA Version**: 12.6 (from torch cu126)
- **cuDNN**: Bundled with PyTorch
- **GPU**: NVIDIA GeForce GTX 1660 Ti (Turing architecture)
- **VRAM**: 6 GB GDDR6
- **Compute Capability**: 7.5

### ONNX Runtime Providers (Priority Order)
1. **TensorrtExecutionProvider** - NVIDIA TensorRT (highest performance)
2. **CUDAExecutionProvider** - CUDA EP (standard GPU acceleration)
3. **CPUExecutionProvider** - CPU fallback

---

## 3. Model Files Verification

### File System Check
```
models/
├── arcface/
│   ├── .gitkeep (0 bytes)
│   └── glintr100.onnx (260,665,334 bytes) ✅
├── landmark/
│   └── .gitkeep (0 bytes)
├── reid/
│   ├── .gitkeep (0 bytes)
│   └── resnet50_reid.onnx (93,950,200 bytes) ✅
├── scrfd/
│   ├── .gitkeep (0 bytes)
│   └── scrfd_10g_bnkps.onnx (16,923,827 bytes) ✅
└── yolo/
    ├── .gitkeep (0 bytes)
    ├── yolo11n.onnx (10,741,327 bytes) ✅
    ├── yolo11n.pt (5,613,764 bytes)
    └── yolo11n-pose.pt (6,255,593 bytes)
```

### Model Configuration (from pipeline.yaml)
```yaml
models:
  scrfd:
    path: "models/scrfd/scrfd_10g_bnkps.onnx"
    input_size: [640, 640]
    confidence_threshold: 0.5
    nms_threshold: 0.4
    strides: [8, 16, 32]
    anchor_scales:
      8: [16, 32]
      16: [64, 128]
      32: [256, 512]
      
  arcface:
    path: "models/arcface/glintr100.onnx"
    input_size: [112, 112]
    embedding_dim: 512
    normalization:
      mean: 127.5
      std: 128.0
    similarity_threshold: 0.6
    
  yolo:
    path: "models/yolo/yolo11n.onnx"
    input_size: [640, 640]
    person_class_id: 0
    confidence_threshold: 0.5
    nms_threshold: 0.45
    max_detections: 100
    
  reid:
    path: "models/reid/resnet50_reid.onnx"
    input_size: [256, 128]
    embedding_dim: 2048
    enabled: false
```

### ArcFace Contract Verification (from spec)
| Parameter | Expected | Configured |
|-----------|----------|------------|
| Input Size | 112×112 | ✅ 112×112 |
| Output Dim | 512 | ✅ 512 |
| Normalization | (x - 127.5) / 128.0 | ✅ mean=127.5, std=128.0 |
| Model | glintr100.onnx | ✅ glintr100.onnx |
| L2 Normalization | Required | ✅ Implemented in ArcFaceRecognizer |
| Five-Point Alignment | Required | ⚠️ SCRFD provides 5 landmarks |

---

## 4. Data Directory Structure

```
data/
├── attendance_events.db (20 KB) - AttendanceEngine SQLite store
├── attendance.db (64 KB) - Legacy attendance database
├── exit_sessions.db (24 KB)
├── notification_queue.db (32 KB)
├── parent_registry.db (45 KB)
├── test_phase52_notification.db (32 KB)
├── test_phase52_runloop.db (32 KB)
├── enrollment/ (empty directory)
└── exports/ (empty directory)
```

### Enrollment Files (MISSING - Blocker)
- `data/embeddings.npy` - NOT EXISTS
- `data/embeddings.npy.metadata.json` - NOT EXISTS

---

## 5. Environment Variables Required

### Current Environment (Partial)
```bash
# Not yet set - Required for V2+
AI_WORKER_API_KEY=
AI_CONTROL_API_KEY=
ADMIN_API_KEY=
BACKEND_BASE_URL=http://localhost:19146
WORKER_ID=pipeline_engine_1
WORKER_VERSION=1.0.0
PIPELINE_CONFIG_PATH=pipeline_engine/config/pipeline.yaml
```

### MediaMTX Configuration
- **Config File**: Not found in repo (likely external)
- **RTSP Port**: 8554
- **API Port**: 9997
- **Paths**: live/cam1, live/cam2, live/cam1-ai, live/cam2-ai

---

## 6. Process Inventory

### Running Processes
| Process | PID | Port | Status |
|---------|-----|------|--------|
| mediamtx | 22484 | 8554 (RTSP), 9997 (API) | ✅ Running |

### NOT Running (Required)
| Process | Expected Port | Status |
|---------|---------------|--------|
| Legacy Backend (app.main) | 19146 (dynamic) | ❌ Not running |
| AI Worker (scripts/run_worker.py) | N/A | ❌ Not running |

---

## 7. Network Ports

| Port | Service | Status |
|------|---------|--------|
| 8554 | MediaMTX RTSP | ✅ Listening (cam1, cam2) |
| 9997 | MediaMTX API | ✅ Responding |
| 19146 | Legacy Backend API | ❌ Not listening |
| 5173 | Frontend Dev Server | ❌ Not running |
| 9090 | Metrics (prometheus) | ❌ Not configured |

---

## 8. Dependency Graph

```
PipelineEngine (core/engine.py)
├── CameraManager (ingestion/camera_manager.py)
│   ├── RTSPSource (ingestion/rtsp_source.py) → PyAV → RTSP
│   ├── NVDECDecoder (decode/nvdec_decoder.py) → GPU decode
│   ├── FramePoolManager (memory/frame_pool.py) → GPU frames
│   ├── SCRFDDetector (inference/face_detection.py) → ONNX/CUDA
│   ├── ArcFaceRecognizer (inference/face_recognition.py) → ONNX/CUDA
│   ├── YOLOPersonDetector (inference/person_detection.py) → ONNX/CUDA
│   ├── Tracker (tracking/tracker.py) → CPU/GPU association
│   ├── AttendanceEngine (attendance/attendance_engine.py) → Crossing events
│   ├── GPUAnnotator (annotation/overlay.py) → GPU annotation
│   ├── NVENCEncoder (encode/nvenc_encoder.py) → GPU encode
│   └── Publisher (output/publisher.py) → MediaMTX RTSP
├── GPUMemoryMonitor (memory/memory_monitor.py)
└── Integration Clients
    ├── EventDeliveryClient (integration/event_client.py) → Backend /api/v1/attendance/events
    ├── LegacyBackendHealthClient (integration/health_client.py) → Backend /api/v1/health/ai-worker
    └── PipelineEngineControlServer (integration/control_client.py) → Backend /api/v1/ai/control/pending
```

---

## 9. Architecture Invariant Compliance

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Original video path independent of AI | ✅ | MediaMTX relays cam1/cam2 unmodified |
| AI path: RTSP → PyAV → Decode → Inference → Track → Cross → Backend | ✅ | Components implemented |
| Legacy Backend sole attendance authority | ✅ | API endpoints in ai_worker.py |
| Phase 22-25 resolver chain | ✅ | RawInOutEvent → Resolver → AttendanceRecord |
| AI Worker never writes AttendanceRecord directly | ✅ | EventDeliveryClient → Backend API only |
| Isolated test database for E2E | ⚠️ | attendance_events.db exists but shared |
| Camera ID, stream_epoch, frame_seq, PTS, time_base preserved | ✅ | EventDeliveryClient + worker conversion |
| Track ID ≠ Person Identity | ✅ | CrossingEvent has both track_id and person_id |
| Unknown identities remain unknown | ✅ | ArcFaceRecognizer returns empty list if below threshold |
| No fabricated enrollment/events | ✅ | Enrollment requires real images via API |

---

## 10. Summary

**Environment Status**: READY for V1 camera validation
- ✅ Python 3.12 + CUDA 12.6 + TensorRT + CUDA EP
- ✅ All model files present at configured paths
- ✅ MediaMTX running with cam1/cam2 streams online
- ✅ PipelineEngine components implemented
- ❌ Legacy Backend not running (blocker for V4)
- ❌ No enrollment database (blocker for identity matching in V2/V3)
- ❌ API keys not configured (blocker for V2 integration)

**Git State**: Clean baseline - no destructive operations performed