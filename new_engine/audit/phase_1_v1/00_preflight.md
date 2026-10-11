# Phase 1.V1 Preflight Audit

**Date**: 2026-10-04
**Authorization**: Phase 1.V1 → V1.V5
**Objective**: Complete Phase 1 implementation by proving the complete runtime path

---

## 1. Repository and Git State

### Current Branch and Status
- **Repository**: `AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE`
- **Current Branch**: `main` (detached HEAD at cb34db0a)
- **Git Status**: 
  - 544 deleted files (mostly benchmark_results, frontend, figma, video_pipeline_v2, scripts)
  - 16 untracked files (UI/, app/, bootstrap.*, new_engine/, pipeline_engine/, scripts/run_worker.py, test files)
- **HEAD Commit**: cb34db0a (pre-NVENC baseline)

### Modified/Untracked Files
- `pipeline_engine/integration/event_client.py` - Event delivery to Legacy Backend
- `pipeline_engine/core/worker.py` - AI Worker lifecycle management
- `scripts/run_worker.py` - Worker entry point
- `pipeline_engine/config/pipeline.yaml` - Pipeline configuration
- `new_engine/audit/phase_1/` - Previous Phase 1 audit artifacts

---

## 2. Python Environment (.venv2)

### Interpreter
- **Python**: 3.12.10 (MSC v.1943 64-bit AMD64)
- **Virtual Environment**: `.venv2` (active)

### Installed Dependencies
| Package | Version | Notes |
|---------|---------|-------|
| torch | 2.13.0+cu126 | CUDA 12.6 |
| onnxruntime | 1.28.0 | TensorRT, CUDA, CPU providers |
| opencv-python | (system) | For camera validation |
| av (PyAV) | (system) | RTSP decoding |
| fastapi | (system) | Backend API |
| uvicorn | (system) | ASGI server |
| httpx | (system) | HTTP client |
| numpy | (system) | Numerical computing |

### CUDA/GPU
- **GPU**: NVIDIA GeForce GTX 1660 Ti
- **CUDA Available**: Yes
- **VRAM**: 6 GB
- **Device ID**: 0

### ONNX Runtime Providers
1. TensorrtExecutionProvider
2. CUDAExecutionProvider
3. CPUExecutionProvider

---

## 3. Model Files and Paths

| Model | Path | Size | Status |
|-------|------|------|--------|
| SCRFD 10G (5-point) | `models/scrfd/scrfd_10g_bnkps.onnx` | 16.9 MB | ✅ Exists |
| ArcFace (glintr100) | `models/arcface/glintr100.onnx` | 260 MB | ✅ Exists |
| YOLO11n | `models/yolo/yolo11n.onnx` | 10.7 MB | ✅ Exists |
| YOLO11n-pose | `models/yolo/yolo11n-pose.pt` | 6.3 MB | ✅ Exists |
| ReID (resnet50) | `models/reid/resnet50_reid.onnx` | 94 MB | ✅ Exists |

All model files present at expected paths per `pipeline.yaml`.

---

## 4. MediaMTX Status

### Process
- **PID**: 22484
- **Status**: Running
- **Memory**: ~84 MB WS, ~26 MB PM

### Paths Configuration
| Path | Ready | Online | Source | Codec | Resolution | FPS |
|------|-------|--------|--------|-------|------------|-----|
| live/cam1 | ✅ true | ✅ true | rtmpConn | H264 | 3840×2160 | 30 |
| live/cam1-ai | ❌ false | ❌ false | - | - | - | - |
| live/cam2 | ✅ true | ✅ true | rtmpConn | H264 | 3840×2160 | 30 |
| live/cam2-ai | ❌ false | ❌ false | - | - | - | - |

### Stream Details (cam1)
- **Codec**: H264 Main Profile Level 5.1
- **Resolution**: 3840×2160
- **Audio**: MPEG-4 AAC 44.1kHz mono
- **Inbound Bytes**: ~56 MB (growing)

### Stream Details (cam2)
- **Codec**: H264 Main Profile Level 5.1
- **Resolution**: 3840×2160
- **Audio**: MPEG-4 AAC 44.1kHz mono
- **Inbound Bytes**: ~50 MB (growing)

---

## 5. Legacy Backend Status

### Process
- **Status**: NOT RUNNING
- **Port 19146**: No response
- **Health Endpoint**: No response
- **API Endpoints**: No response

### Required Action
Backend must be started for end-to-end testing.

---

## 6. Enrollment Database Status

### Files
- `data/embeddings.npy`: ❌ NOT EXISTS
- `data/embeddings.npy.metadata.json`: ❌ NOT EXISTS
- `data/enrollment/`: ✅ Directory exists (empty)

### Enrollment API
- **Endpoint**: `/api/v1/enrollment/persons` (POST multipart)
- **Reload Endpoint**: `/api/v1/enrollment/reload` (POST, admin key required)
- **Dependencies**: `app.vision.enrollment` module
- **Models Used**: SCRFD + ArcFace (glintr100)
- **Output**: `app/data/enrollment/embeddings.npy` + metadata

### Enrollment Pipeline
1. `process_image_enrollment()` - Face detection + quality + embedding extraction
2. `build_enrollment_database()` - Aggregates vectors → NPY + metadata.json
3. ArcFace recognizer loads via `load_enrollment_database()`

### Required Action
At least one person must be enrolled via the enrollment API before identity matching can succeed.

---

## 7. PipelineEngine Components Status

### Existing Implementation (Inspected)
| Component | File | Status |
|-----------|------|--------|
| EventDeliveryClient | `pipeline_engine/integration/event_client.py` | ✅ Implemented |
| AIWorker | `pipeline_engine/core/worker.py` | ✅ Implemented |
| CameraManager | `pipeline_engine/ingestion/camera_manager.py` | ✅ Implemented |
| RTSPSource | `pipeline_engine/ingestion/rtsp_source.py` | ✅ Implemented |
| NVDECDecoder | `pipeline_engine/decode/nvdec_decoder.py` | (referenced) |
| NVENCEncoder | `pipeline_engine/encode/nvenc_encoder.py` | (referenced) |
| SCRFDDetector | `pipeline_engine/inference/face_detection.py` | ✅ Implemented |
| ArcFaceRecognizer | `pipeline_engine/inference/face_recognition.py` | ✅ Implemented |
| YOLOPersonDetector | `pipeline_engine/inference/person_detection.py` | (referenced) |
| Tracker | `pipeline_engine/tracking/tracker.py` | (referenced) |
| AttendanceEngine | `pipeline_engine/attendance/attendance_engine.py` | ✅ Implemented |
| PipelineEngine | `pipeline_engine/core/engine.py` | ✅ Implemented |

### Configuration
- **Config File**: `pipeline_engine/config/pipeline.yaml`
- **Cameras**: cam1, cam2 (both enabled)
- **RTSP URLs**: 
  - cam1: `rtsp://localhost:8554/live/cam1`
  - cam2: `rtsp://localhost:8554/live/cam2`
- **GPU**: Device 0, VRAM budget 4096 MB
- **Models**: SCRFD, ArcFace, YOLO paths configured
- **Backend**: `http://localhost:19146`

---

## 8. Architecture Invariants Check

### Architecture A (Original Video Path)
- Camera 1 + Camera 2 → MediaMTX/FFmpeg relay → original unannotated video → UI player
- **Status**: MediaMTX running, cam1/cam2 paths online ✅

### Independent AI Path
- RTSP → PyAV reader per camera → decode → inference → tracking → crossing events → Backend API
- **Status**: Components implemented, not yet running

### Legacy Backend Authority
- Legacy Backend remains sole attendance authority
- Phase 22-25 resolver: `CrossingEvent → RawInOutEvent → ResolvedTransition → AttendanceRecord`
- AI Worker must NOT write directly to AttendanceRecord
- **Status**: API endpoints implemented (`app/api/ai_worker.py`), Backend not running

### Data Integrity
- Isolated test database required for E2E verification
- Camera ID, stream epoch, frame sequence, PTS, time_base, capture timestamp must be preserved
- Track ID ≠ Person Identity
- Unknown identities must remain unknown
- **Status**: EventDeliveryClient preserves required fields; AttendanceEngine stores events

---

## 9. Preflight Verdict

**V1 READINESS**: CONDITIONAL PASS

### Blockers Requiring Resolution (V1.6)
1. **Legacy Backend not running** - Must start `app.main` on port 19146
2. **No enrollment database** - Must enroll at least one person via `/api/v1/enrollment/persons`
3. **AI Worker API keys not configured** - Need `AI_WORKER_API_KEY`, `AI_CONTROL_API_KEY`, `ADMIN_API_KEY` in environment

### Available for Immediate Testing
- ✅ Both camera streams discovered and verified (FFprobe + PyAV decode)
- ✅ Model files present and loadable
- ✅ GPU with CUDA + TensorRT + CUDAExecutionProvider available
- ✅ PipelineEngine components implemented
- ✅ CameraManager ready for cam1/cam2 independent operation
- ✅ MediaMTX running with both source streams online

### Next Steps (V1.6 Blocker Resolution)
1. Start Legacy Backend
2. Create test enrollment via enrollment API
3. Configure API keys
4. Proceed to V2 (CAM1 single-camera runtime)

---

## Evidence Artifacts
- MediaMTX paths list JSON (captured above)
- FFprobe output for cam1/cam2 (h264, 3840×2160, yuv420p, 30fps)
- PyAV decode test: 100 frames decoded in ~2.56s (39 fps) for both cameras
- Python environment verification (torch, onnxruntime, providers)
- Model file inventory
- Git status output