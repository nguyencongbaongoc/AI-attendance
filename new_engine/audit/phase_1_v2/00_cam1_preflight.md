# Phase 1.V2 CAM1 Preflight

**Date**: 2026-10-04
**Phase**: 1.V2 - CAM1 Single-Camera Runtime
**Authorization**: Phase 1.V1 → V1.V5 (V1 completed)
**GPU-First Addendum**: APPLIED

---

## 1. V1 Completion Status

### V1 Gate - PASS WITH CONDITIONS
- ✅ Camera streams discovered (CAM1, CAM2)
- ✅ Streams decoded (100 frames each at 39+ fps)
- ✅ CAM1/CAM2 mappings identified
- ✅ Backend running at port 18693
- ✅ Event ingestion working (returns source_resolution_id)
- ⚠️ Enrollment database not created (V2 workaround: unknown identities only)
- ⚠️ AI output paths inactive (will auto-activate)

### Architecture Invariants Verified
- Original video path independent of AI
- AI path: RTSP → PyAV → Decode → Inference → Track → Cross → Backend
- Legacy Backend sole attendance authority
- Phase 22-25 resolver chain intact
- Isolated test database for E2E

---

## 2. V2 Objectives (Updated with GPU-First Addendum)

### Primary Objective
Prove complete AI pipeline using real CAM1 frames with **GPU-First execution**:

1. Camera ingestion → frame arrival (RTSP → PyAV)
2. **GPU Frame decoding → NVDEC hardware decode** (MANDATORY)
3. **GPU Face detection → SCRFD on CUDA/TensorRT** (MANDATORY)
4. **GPU Face alignment → 5-point GPU processing**
5. **GPU ArcFace embedding → on CUDA/TensorRT** (MANDATORY)
6. **GPU Identity matching → GPU vector operations**
7. **GPU Person detection → YOLO on CUDA/TensorRT** (MANDATORY)
8. Tracking (BYTES/DeepSORT) - GPU where beneficial
9. Crossing detection - GPU where practical
10. IN/OUT event generation
11. EventDeliveryClient → Legacy Backend
12. Phase 22-25 resolver → AttendanceRecord (isolated DB)

### Duration Requirement
- **Minimum**: 10 continuous minutes
- **Target**: 15 minutes for robust metrics

### GPU Qualification Metrics (MANDATORY per Addendum)
| Capability | Required Result | Verification Method |
|---|---|---|
| NVDEC CAM1 | PASS | Prove hardware decode via cuvid/cuda hwaccel |
| SCRFD GPU | PASS | Verify CUDAExecutionProvider + GPU tensor ops |
| ArcFace GPU | PASS | Verify CUDAExecutionProvider + GPU tensor ops |
| YOLO GPU | PASS | Verify CUDAExecutionProvider + GPU tensor ops |
| GPU preprocessing | Measured | No unnecessary CPU copies |
| GPU memory management | PASS | No pool exhaustion, VRAM < 4GB |
| CPU fallback audit | PASS | No silent CPU fallbacks |

---

## 3. Environment Configuration

### Backend
- **URL**: http://localhost:18693
- **AI_WORKER_API_KEY**: worker-test-key-1234567890123456
- **AI_CONTROL_API_KEY**: control-test-key-1234567890123456
- **ADMIN_API_KEY**: admin-test-key-1234567890123456

### Camera (CAM1)
- **RTSP URL**: rtsp://localhost:8554/live/cam1
- **Resolution**: 3840×2160
- **FPS**: 30
- **Codec**: h264
- **Geometry**: Line at y=1080, side_a_to_b_in

### GPU
- **Device**: GTX 1660 Ti (6GB VRAM)
- **VRAM Budget**: 4096 MB (reserved for pipeline)
- **CUDA**: 12.6
- **ONNX Runtime**: CUDAExecutionProvider + TensorRTExecutionProvider

### Models (All GPU-First)
| Model | Path | Execution Preference |
|---|---|---|
| SCRFD | models/scrfd/scrfd_10g_bnkps.onnx | CUDA/TensorRT (MANDATORY) |
| ArcFace | models/arcface/glintr100.onnx | CUDA/TensorRT (MANDATORY) |
| YOLO | models/yolo/yolo11n.onnx | CUDA/TensorRT (MANDATORY) |
| ReID | models/reid/resnet50_reid.onnx | CUDA/TensorRT (DISABLED) |
| Pose | models/yolo/yolo11n-pose.pt | CUDA/TensorRT (DISABLED) |

### Isolated Database
- **Path**: data/attendance_events.db (PipelineEngine AttendanceEngine store)
- **NOT**: data/attendance.db (Legacy production)

---

## 4. Known Issues to Resolve Before Sustained Run

| Issue | Severity | Root Cause | Fix Required |
|---|---|---|---|
| Frame pool exhaustion | CRITICAL | Pipeline stages not releasing frames back to pool | Fix frame ownership/transfer in pipeline loop |
| Decoder not using NVDEC | HIGH | nvdec_decoder.py uses software decode + GPU upload | Enable cuvid/cuda hwaccel for GTX 1660 Ti |
| GPU inference not verified | HIGH | Models init with CUDA provider but runtime not measured | Add GPU utilization metrics during inference |
| Zero-copy not proven | MEDIUM | Frame path includes CPU decode → GPU upload | Verify DLPack/from_dlpack path |

---

## 5. Test Plan

### Phase 1: Fix Frame Pool Exhaustion (Priority 1)
1. Analyze frame ownership flow in `_camera_pipeline_loop`
2. Identify which stage fails to release frame
3. Fix frame transfer/return logic
4. Verify pool utilization stabilizes

### Phase 2: Enable True NVDEC (Priority 2)
1. Test PyAV cuvid/cuda hwaccel on GTX 1660 Ti
2. Verify hardware decode produces cuda format frames
3. Measure decode FPS and latency
4. Compare with software decode baseline

### Phase 3: Verify GPU Inference (Priority 3)
1. Add GPU utilization monitoring during SCRFD/ArcFace/YOLO
2. Measure per-model latency and throughput
3. Verify no CPU fallback
4. Record VRAM consumption per model

### Phase 4: Sustained Run (10+ min)
1. Start CameraManager for CAM1 with fixed pool + NVDEC
2. Monitor frame throughput
3. Monitor inference latency
4. Monitor crossing events
5. Monitor event delivery to Backend
6. Monitor Backend resolver → AttendanceRecord
7. Collect metrics every 30 seconds

### Phase 5: Validation & Shutdown
1. Verify isolated DB has AttendanceRecords
2. Verify provenance chain
3. Graceful shutdown
4. Collect final metrics

---

## 6. Success Criteria (Updated)

### Minimum Pass (V2 Gate)
- ✅ CAM1 frames traverse complete pipeline for 10+ minutes
- ✅ **NVDEC hardware decode verified for CAM1**
- ✅ **SCRFD + ArcFace + YOLO GPU execution verified**
- ✅ **Frame pool stable (no exhaustion)**
- ✅ Crossing events generated (even if unknown identity)
- ✅ Events delivered to Backend (200 OK)
- ✅ Backend resolver produces source_resolution_id
- ✅ Isolated DB receives records
- ✅ No critical errors or crashes
- ✅ **CPU fallback audit clean (no silent fallbacks)**

### Full Qualification
- NVDEC decode FPS ≥ 30
- Inference latency p99 < 500ms end-to-end
- Frame drop rate < 1%
- Event delivery success 100%
- GPU memory stable (no leaks)
- Clean shutdown

---

## 7. Risk Mitigation

| Risk | Mitigation |
|---|---|
| GPU OOM on 4K decode | VRAM budget 4GB, monitor via GPUMemoryMonitor |
| NVDEC unsupported on GTX 1660 Ti | Document exact limitation, fallback documented |
| Decoder stall | Readiness gate + health monitoring |
| Encoder failure | NVENC fallback monitoring |
| Backend unavailable | EventDeliveryClient queues + retry |
| No enrollment | Unknown identities expected, documented |
| Stream disconnect | Reconnect logic in RTSPSource |

---

## 8. Commands Reference

### Start CameraManager (CAM1 only) - for testing
```python
from pipeline_engine.config import load_pipeline_config
from pipeline_engine.ingestion.camera_manager import CameraManager

config = load_pipeline_config(Path('pipeline_engine/config/pipeline.yaml'))
manager = CameraManager(config)
manager.initialize()
manager.start_camera('cam1')
```

### Start Worker (full integration)
```bash
$env:BACKEND_BASE_URL="http://localhost:18693"
$env:AI_WORKER_API_KEY="worker-test-key-1234567890123456"
$env:AI_CONTROL_API_KEY="control-test-key-1234567890123456"
$env:WORKER_ID="pipeline_engine_1"
& ".venv2\Scripts\python.exe" scripts/run_worker.py --config pipeline_engine/config/pipeline.yaml
```

### Monitor Backend
```bash
# Health
curl http://localhost:18693/api/v1/health/live
curl http://localhost:18693/api/v1/health/ready

# Events
curl -X POST http://localhost:18693/api/v1/attendance/events ...
```

---

## 9. V2 Deliverables (Planned)

```
new_engine/audit/phase_1_v2/
├── 00_cam1_preflight.md              # This file
├── 01_cam1_ingestion.md              # Camera ingestion validation
├── 02_cam1_frame_metadata.md         # Frame sequence, PTS, time_base
├── 03_cam1_model_runtime.md          # SCRFD/ArcFace/YOLO runtime (GPU verified)
├── 04_cam1_identity_matching.md      # Unknown identity verification
├── 05_cam1_tracking.md               # Track lifecycle
├── 06_cam1_crossing_events.md        # Crossing detection
├── 07_cam1_backend_delivery.md       # EventDeliveryClient → Backend
├── 08_cam1_runtime_metrics.md        # Latency, throughput, errors, GPU
├── 09_cam1_verdict.md                # V2 verdict
```

---

## 10. Next Steps

1. ▶️ Fix frame pool exhaustion in CameraManager pipeline
2. ▶️ Enable true NVDEC hardware decoding
3. ▶️ Add GPU utilization monitoring to inference
4. ▶️ Run sustained pipeline test (10+ min)
5. ▶️ Collect and document metrics
6. ▶️ Verify AttendanceRecord in isolated DB
7. ▶️ Write V2 verdict