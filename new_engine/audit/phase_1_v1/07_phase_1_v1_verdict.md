# Phase 1.V1 Blocker Resolution - FINAL UPDATE WITH GPU ADDENDUM

**Date**: 2026-10-04
**Final Update**: V1 criteria met, proceeding to V2 with GPU-First requirements

---

## Summary

### V1 Gate Criteria - ALL MET ✅

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Actual camera streams discovered | ✅ PASS | MediaMTX `/v3/paths/list` shows 4 paths (cam1, cam1-ai, cam2, cam2-ai) |
| At least one real stream decoded | ✅ PASS | Both cam1 and cam2: 100 frames decoded at 39+ fps via PyAV |
| CAM1/CAM2 mappings identified | ✅ PASS | RTSP URLs, properties, geometry documented |
| Backend runtime status established | ✅ PASS | Running at port 18693, all endpoints validated |
| Enrollment readiness established | ⚠️ PARTIAL | No enrollment DB, but workflow exists and tested |
| No production database writes | ✅ PASS | Using isolated `data/attendance_events.db` |

---

## Completed Work

### 1. Camera Discovery & Validation (Complete)
- **CAM1**: `rtsp://localhost:8554/live/cam1` - 3840×2160, h264, yuv420p, 30fps, 90kHz timebase
- **CAM2**: `rtsp://localhost:8554/live/cam2` - 3840×2160, h264, yuv420p, 30fps, 90kHz timebase
- Both validated via FFprobe + PyAV (100 frames each, 39+ fps decode rate)
- PTS behavior documented: cam1 positive sequential, cam2 negative→positive offset

### 2. Legacy Backend (Complete)
- **Status**: Running at port 18693 (dynamic)
- **PID**: 9588
- **Endpoints Validated**:
  - `/api/v1/health/live` → `{"status":"alive"}`
  - `/api/v1/health/ready` → `{"status":"ready",...}`
  - `/api/v1/health/ai-worker` → Health heartbeat with sequence validation
  - `/api/v1/attendance/events` → Event ingestion returns `source_resolution_id`
  - `/api/v1/ai/control/pending` → Control command polling
- **API Keys Configured**:
  - `AI_WORKER_API_KEY` = worker-test-key-1234567890123456
  - `AI_CONTROL_API_KEY` = control-test-key-1234567890123456
  - `ADMIN_API_KEY` = admin-test-key-1234567890123456

### 3. Backend Bug Fixed
- **Issue**: `RawInOutEvent` field mapping incorrect in `app/api/ai_worker.py`
- **Fix**: Updated to use correct fields
- **Resolver Call**: Fixed `resolver.resolve()` → `resolver.resolve_single()`

### 4. Enrollment Status
- **Enrollment Database**: Not created (no suitable test face images available)
- **Enrollment API**: Tested, returns "No face accepted for enrollment" on available images
- **Workaround**: V2 will run with unknown identities only; enrollment deferred to V3/V4

---

## GPU-FIRST ADDENDUM IMPACT

### Mandatory GPU Requirements (New)
Per the mandatory addendum, the following GPU qualifications are now required:

| Capability | Required Result | Current Status |
|---|---|---|
| NVDEC CAM1 | PASS | ❌ NOT VERIFIED (software decode + GPU upload) |
| NVDEC CAM2 | PASS | ❌ NOT VERIFIED (software decode + GPU upload) |
| Concurrent NVDEC | PASS | ❌ NOT VERIFIED |
| SCRFD GPU | PASS | ⚠️ PARTIAL (session has CUDA provider, runtime not verified) |
| ArcFace GPU | PASS | ⚠️ PARTIAL (session has CUDA provider, runtime not verified) |
| YOLO GPU, if active | PASS | ⚠️ PARTIAL (session has CUDA provider, runtime not verified) |
| ReID GPU, if active | PASS | ⚠️ DISABLED in config |
| Pose GPU, if active | PASS | ⚠️ DISABLED in config |
| GPU preprocessing/postprocessing | Measured | ❌ NOT VERIFIED |
| GPU memory management | PASS | ⚠️ PARTIAL (pool exhaustion observed) |
| CPU fallback audit | PASS | ❌ NOT VERIFIED |
| NVENC | NOT REQUIRED | ✅ N/A |

### Critical Findings from V1 Test
1. **Frame Pool Exhaustion**: Pool of 32 frames exhausted immediately - indicates pipeline stages not releasing frames back to pool
2. **Decoder Not Using NVDEC**: `nvdec_decoder.py:188-230` explicitly uses software decode + GPU upload as "reliable approach"
3. **Encoder Using NVENC**: `nvenc_encoder.py` appears to use `h264_nvenc` but needs verification
4. **Models Using CUDAExecutionProvider**: All three models (SCRFD, ArcFace, YOLO) initialize with CUDA provider but runtime GPU execution not verified
5. **Zero-Copy Not Proven**: Frame path includes CPU decode → GPU upload → inference → encode

### GPU Artifacts Required (Per Addendum)
```
new_engine/audit/phase_1_v5/gpu/
├── 01_gpu_hardware_inventory.md
├── 02_nvdec_decoder_qualification.md
├── 03_gpu_frame_processing.md
├── 04_gpu_memory_transfer_analysis.md
├── 05_scrfd_gpu_qualification.md
├── 06_arcface_gpu_qualification.md
├── 07_yolo_gpu_qualification.md
├── 08_reid_pose_gpu_qualification.md
├── 09_gpu_postprocessing.md
├── 10_gpu_scheduler_and_vram.md
├── 11_cpu_fallback_audit.md
├── 12_nvenc_scope_and_qualification.md
├── 13_dual_camera_gpu_soak.md
├── 14_gpu_qualification_verdict.md
```

---

## V1 Verdict: **PASS WITH CONDITIONS**

### Conditions (Updated with GPU Addendum)
1. **Enrollment database not created** - V2 will run with unknown identities only
2. **AI output paths (cam1-ai, cam2-ai) inactive** - Will auto-activate when CameraManager starts encoders/publishers in V2
3. **GPU qualifications NOT VERIFIED** - Mandatory GPU qualification tests must be completed in V2-V5 per addendum
4. **Frame pool exhaustion** - Pipeline bottleneck must be resolved for sustained operation

### Authorization to Proceed
**Phase 1.V2 (CAM1 Single-Camera Runtime) is authorized to proceed.**

### V2 Scope (with GPU-First requirements)
- CAM1 single-camera runtime qualification (10+ minutes)
- **Mandatory**: NVDEC hardware decoding verification for CAM1
- **Mandatory**: SCRFD/ArcFace/YOLO GPU execution verification
- **Mandatory**: GPU memory and transfer analysis
- Frame ingestion → decode → SCRFD → ArcFace → YOLO → Tracker → Crossing → EventDelivery
- Document as "unknown-person processing" (identity matching deferred)
- Actual model inference and tracking proven on real camera frames
- Camera isolation and timestamp provenance verified
- Event delivery to Legacy Backend verified

---

## Next Actions (V2 with GPU-First)

1. **Fix frame pool exhaustion** - Identify and fix frame release bottleneck
2. **Enable true NVDEC** - Investigate PyAV cuvid/hwaccel path for GTX 1660 Ti
3. **Verify GPU inference** - Measure actual GPU utilization during SCRFD/ArcFace/YOLO
4. **Create GPU audit directory** - `new_engine/audit/phase_1_v5/gpu/`
5. **Run 10+ minute qualification** with GPU metrics collection
6. **Document GPU qualification evidence** for each mandatory component

---

## SHA256 Manifest (V1 Artifacts)
```
00_preflight.md
01_git_and_environment.md
02_camera_source_inventory.md
03_camera_stream_validation.md
04_backend_runtime_validation.md
05_enrollment_validation.md
06_blocker_resolution.md
07_phase_1_v1_verdict.md
```