# Risks, Blockers, and Unknowns

## Critical Risks (High Likelihood, High Impact)

### R1: Timestamp Synchronization Failure
**Description**: AI metadata (attendance events, track positions) cannot be accurately synchronized with video playback in UI.

**Root Cause**: 
- Video: HLS segments from MediaMTX, ~2-3s latency
- AI: Wall-clock timestamps + processing latency (~50ms)
- No shared clock or PTS correlation mechanism

**Impact**: UI overlays appear at wrong time/position; attendance events don't match video

**Mitigation**:
- Include `frame_pts`, `time_base`, `wall_clock_timestamp`, `processing_latency_ms` in metadata
- UI correlates `video.currentTime` with `(wall_clock - latency/1000)`
- Prototype sync mechanism in Phase 1A

**Evidence**: `GPUFrame` has PTS fields but no sync protocol; UI has no metadata handler

---

### R2: Legacy Backend Integration Blocking
**Description**: PipelineEngine cannot push attendance events to Legacy Backend; dual database conflict.

**Root Cause**:
- PipelineEngine writes to `data/attendance_events.db` (new)
- Legacy Backend owns `data/attendance.db` (authoritative)
- UI reads from Legacy Backend only
- PipelineEngine Backend attendance endpoints are stubs

**Impact**: Attendance events generated but invisible to UI; data fragmentation

**Mitigation**:
- Define Legacy Backend API contract for event ingestion
- Implement `LegacyBackendClient` in PipelineEngine
- Remove PipelineEngine local SQLite store
- Single authoritative DB: `data/attendance.db`

**Evidence**: `backend/app.py` attendance endpoints return `[]`; `attendance_engine.py` uses separate SQLite

---

### R3: Shared Model Inference Contention
**Description**: Multiple cameras sharing single model instances cause GPU memory contention and latency spikes.

**Root Cause**:
- Current: Per-camera model instances (~500MB VRAM each)
- Architecture A: Shared instances with batch queue
- No batching implementation exists
- No inference queue management

**Impact**: OOM errors, increased latency, frame drops

**Mitigation**:
- Implement batched inference (`detect_batch`, `infer_embeddings_batch`)
- Add inference queue with max batch size / max wait time
- Monitor VRAM via `GPUMemoryMonitor`, reduce batch under pressure
- Test 2-camera sustained load

**Evidence**: `CameraManager` creates separate SCRFD/ArcFace/YOLO per camera; no batch APIs

---

### R4: No True Hardware Decode on GTX 1660 Ti Windows
**Description**: NVDEC not functional; software decode bottleneck at 4K30.

**Root Cause**: 
- cuvid outputs `dxva2_vld` on Windows, not CUDA
- Current: software decode (CPU) + GPU upload (~10ms/frame)
- 2 cameras × 30 FPS = 60 frames/sec decode load

**Impact**: CPU saturation, frame drops, pipeline instability

**Mitigation**:
- Test `nvcv_bridge.pyd` for true zero-copy NVDEC
- Consider 1080p decode for AI (4× faster), 4K for video path
- Separate decode process isolates CPU load
- Profile actual decode time in runtime

**Evidence**: `nvdec_decoder.py` lines 164-171, 188-230 explicitly document this limitation

---

### R5: NVENC OSError -129 Instability
**Description**: Intermittent NVENC encoder failures requiring restart logic.

**Root Cause**: 
- Known Windows NVENC issue (FFmpeg errno -129)
- Current: Restart logic with max 3 retries, exponential backoff
- Restart clears frame queue, loses frames

**Impact**: Video output gaps, potential pipeline stall if max retries exceeded

**Mitigation**:
- Architecture A removes NVENC entirely (metadata-only output)
- If video path needs encoding, use MediaMTX stream copy
- For recording: MediaMTX native recording (no re-encode)

**Evidence**: `nvenc_encoder.py` lines 414-459 implement restart logic

---

## High Risks (Medium Likelihood, High Impact)

### R6: UI Canvas Overlay Performance at 4K
**Description**: Drawing bounding boxes, labels, lines on canvas at 4K resolution may not sustain 30 FPS.

**Root Cause**:
- Canvas size: 3840×2160 = 8.3M pixels
- Per frame: ~10 tracks × (box + label + face box) + line + diagnostics
- JavaScript canvas operations on main thread

**Impact**: UI jank, dropped frames, poor UX

**Mitigation**:
- Downscale canvas to display size (CSS transform)
- Use `OffscreenCanvas` + Web Worker
- Limit draw calls: batch boxes, use path2D
- Profile with Chrome DevTools

**Evidence**: UI uses canvas for line drawing tool; no bbox rendering implemented

---

### R7: NPY Hot-Reload Race Conditions
**Description**: Enrollment updates (new NPY) not propagated to running AI pipeline.

**Root Cause**:
- ArcFaceRecognizer loads NPY at startup
- UI writes new `embeddings.npy` 
- PipelineEngine has per-camera instances (2× GPU memory)
- No file watcher or API notification

**Impact**: New enrollments not recognized until restart

**Mitigation**:
- Single shared ArcFaceRecognizer instance
- File watcher on `embeddings.npy` → reload on change
- Or: Legacy Backend API notifies PipelineEngine

**Evidence**: `CameraManager` creates ArcFace per camera; `load_enrollment_database` called once at init

---

### R8: Geometry Config Sync Drift
**Description**: Line geometry changes in UI not reflected in AI pipeline.

**Root Cause**:
- UI saves lines via WebSocket `/api/line`
- PipelineEngine reads from `pipeline.yaml` at startup
- Backend PUT `/geometry/lines` restarts camera
- No real-time config push

**Impact**: Wrong attendance counting, crossed lines not detected

**Mitigation**:
- Legacy Backend owns geometry config
- PipelineEngine subscribes to config changes (WebSocket or polling)
- Atomic config update without camera restart (tracker reset only)

**Evidence**: `backend/app.py` PUT endpoint calls `CameraManager.update_camera_config()` which restarts camera

---

## Medium Risks

### R9: FramePool Exhaustion Under Load
**Description**: Frame pool runs out during bursts, dropping frames silently.

**Current**: Pool size 32, exhaustion logs warning, drops frame
**No backpressure to RTSP source**

**Mitigation**: 
- Increase pool size or dynamic growth
- Add backpressure signal to RTSP reader
- Monitor `exhaustion_events` metric

---

### R10: Reconnection Storm
**Description**: Multiple cameras reconnecting simultaneously overwhelm MediaMTX/GPU.

**Current**: Independent exponential backoff per camera
**No coordination**

**Mitigation**:
- Jitter already implemented (±10%)
- Add global reconnection semaphore
- Stagger startup

---

### R11: Attendance Event Burst Loss
**Description**: Many simultaneous crossings exceed callback processing capacity.

**Current**: Synchronous callback execution in `process_tracks()`
**No queue**

**Mitigation**:
- Async event queue with worker thread
- Batch push to Legacy Backend
- Circuit breaker if Legacy Backend unavailable

---

### R12: CUDA OOM During Model Load
**Description**: Loading 3 models × 2 cameras = 6 model instances may exceed 6GB VRAM.

**Models**: SCRFD (~100MB), ArcFace (~300MB), YOLO (~100MB) per instance
**Total**: ~1GB per camera × 2 = 2GB + frames + overhead

**Mitigation**:
- Architecture A: Shared models (1× each)
- Lazy load: Load on first use
- FP16 quantization (if supported)

---

## Blockers (Verification Prevented)

### B1: No Runtime Environment
**Status**: **BLOCKED** - Cannot run any component
**Requirements**: 
- GTX 1660 Ti + CUDA 12.6
- MediaMTX running
- 2x RTSP streams (cameras or test videos)
- Legacy Backend on port 8000
- Enrollment NPY database

**Impact**: All runtime verification BLOCKED

---

### B2: No Automated Test Suite
**Status**: **BLOCKED** - Cannot verify correctness
**Requirements**: 
- pytest tests for each module
- Integration tests for pipeline
- CI/CD pipeline

**Impact**: No regression detection, no confidence in changes

---

### B3: Legacy Backend Unavailable
**Status**: **BLOCKED** - Cannot test integration
**Impact**: Attendance flow, UI data flow, config sync untestable

---

### B4: Enrollment Database Missing
**Status**: **BLOCKED** - ArcFace identification untestable
**File**: `data/embeddings.npy` + metadata.json
**Impact**: Face recognition, tracking identity, attendance person_id all untested

---

## Unknowns (Insufficient Evidence)

### U1: nvcv_bridge.pyd Capability
**File**: `nvcv_bridge.pyd` (196KB) in repo root
**Unknown**: Whether it enables true NVDEC on Windows GTX 1660 Ti
**Investigation**: Import and test in Python; check symbols

---

### U2: TensorRT 11.3 Integration Potential
**Directory**: `TensorRT-11.3.0.99/` in repo root
**Unknown**: Whether ONNX models can be converted to TensorRT engines for faster inference
**Investigation**: Check ONNX compatibility, build engines, benchmark

---

### U3: Video_Codec_SDK_13.0.37 Usage
**Directory**: `Video_Codec_SDK_13.0.37/` in repo root
**Unknown**: Whether needed for nvcv_bridge or custom NVDEC/NVENC
**Investigation**: Check nvcv_bridge dependencies

---

### U4: Isolated_src/ and Isolated_tests/ Content
**Directories**: `isolated_src/`, `isolated_tests/`
**Unknown**: Whether they contain alternative implementations or tests
**Investigation**: Explore contents

---

### U5: Phase7 Runtime Diagnostic Results
**Directory**: `phase7_runtime_diagnostic/`
**Unknown**: Previous runtime test results, performance baselines
**Investigation**: Read any logs/reports

---

### U6: Benchmark Results
**Directory**: `benchmark_results/`
**Unknown**: Historical performance data
**Investigation**: Check for CSV/JSON results

---

### U7: Actual Camera Stream Specifications
**Unknown**: Real camera bitrate, GOP, codec profile, keyframe interval
**Impact**: Decoder/encoder config tuning, stream copy feasibility
**Investigation**: Analyze live streams with ffprobe

---

### U8: Legacy Backend Actual API Schema
**Unknown**: Exact endpoints, request/response formats, WebSocket messages
**Impact**: Integration contract definition
**Investigation**: Access Legacy Backend source or Swagger/OpenAPI spec

---

### U9: Production Load Characteristics
**Unknown**: Peak concurrent persons, crossing rate, enrollment size
**Impact**: Tracker memory bounds, DB sizing, inference batching
**Investigation**: Analyze production logs or simulate

---

### U10: GPU Memory Fragmentation Over Time
**Unknown**: Whether FramePool + model tensors cause fragmentation after hours/days
**Impact**: Silent performance degradation, allocation failures
**Investigation**: Long-running stress test with memory profiling

---

## Risk Register Summary

| ID | Risk | Likelihood | Impact | Phase 0 Action |
|----|------|------------|--------|----------------|
| R1 | Timestamp sync failure | HIGH | HIGH | Document sync protocol for Phase 1 |
| R2 | Legacy Backend integration | HIGH | HIGH | Define API contract |
| R3 | Model contention | HIGH | HIGH | Design batch inference queue |
| R4 | No true NVDEC | HIGH | HIGH | Test nvcv_bridge |
| R5 | NVENC instability | MEDIUM | HIGH | Remove NVENC in Arch A |
| R6 | UI overlay perf | MEDIUM | MEDIUM | Prototype canvas overlay |
| R7 | NPY hot-reload | MEDIUM | MEDIUM | Design shared ArcFace + watcher |
| R8 | Geometry sync | MEDIUM | MEDIUM | Legacy Backend owns config |
| R9 | FramePool exhaustion | LOW | MEDIUM | Monitor metrics |
| R10 | Reconnection storm | LOW | MEDIUM | Add coordination |
| R11 | Event burst loss | LOW | MEDIUM | Async queue |
| R12 | CUDA OOM on load | MEDIUM | HIGH | Shared models, lazy load |

---

## Blocker Resolution Priority

1. **B1** (Runtime env) - Prerequisite for all verification
2. **B3** (Legacy Backend) - Prerequisite for integration
3. **B4** (Enrollment DB) - Prerequisite for face recognition
4. **B2** (Test suite) - Can be developed in parallel

---

## Unknown Resolution Priority

1. **U1** (nvcv_bridge) - Could solve R4
2. **U8** (Legacy Backend API) - Prerequisite for R2
3. **U7** (Camera specs) - Needed for decoder/encoder tuning
4. **U2/U3** (TensorRT/Video SDK) - Performance optimization
5. **U4/U5/U6** (Historical data) - Context for decisions