# Blockers and Risk Register

## Critical Blockers (Phase 0.1 Execution Blocked)

### B1: MediaMTX Not Running
- **Impact**: No RTSP/HLS/WebRTC streams available for any verification
- **Evidence**: `Get-Process mediamtx` returns nothing; `netstat` shows no ports 8554, 8888, 8889, 9997, 1935 listening
- **Resolution**: Start `mediamtx.exe` from `mediamtx/` directory
- **Dependencies**: Camera publishers must push RTMP to :1935/live/cam1 and :1935/live/cam2

### B2: Legacy Backend Not Running
- **Impact**: No API endpoints, no WebSocket, no database access, no attendance event ingestion
- **Evidence**: No FastAPI process on any port; `Get-Process python` returns nothing
- **Resolution**: Run `python app/main.py` or `bootstrap.py`
- **Dependencies**: Requires `data/` directory with SQLite databases

### B3: Camera Publishers Not Running
- **Impact**: Even with MediaMTX running, no video streams available
- **Evidence**: No connections to RTMP port 1935
- **Resolution**: Configure cameras to push RTMP to MediaMTX, or use test video files
- **Unknowns**: Camera IPs, RTMP configuration, whether cameras are physical or simulated

### B4: Enrollment Database Missing
- **Impact**: ArcFace identification cannot work; all persons will be UNKNOWN
- **Evidence**: `data/embeddings.npy` and `data/embeddings.npy.metadata.json` not verified
- **Resolution**: Run enrollment process or create test embeddings
- **Dependencies**: Legacy Backend enrollment API or manual NPY creation

### B5: PipelineEngine Backend Not Running
- **Impact**: PipelineEngine's own API unavailable (though Architecture A uses Legacy Backend)
- **Evidence**: No process on dynamic port
- **Resolution**: Not required for Architecture A (Legacy Backend is authoritative)

### B6: No Automated Test Suite
- **Impact**: Cannot verify correctness, no regression detection
- **Evidence**: All `pipeline_engine/tests/` subdirectories empty
- **Resolution**: Develop test suite in Phase 1+

---

## High Risks (Likely to Impact Phase 1)

### R1: Timestamp Synchronization Failure
- **Probability**: HIGH
- **Impact**: HIGH - AI metadata overlays appear at wrong time/position on video
- **Root Cause**: HLS `video.currentTime` (2-4s behind live) ≠ RTSP PTS (90kHz) ≠ Wall-clock timestamps
- **Mitigation**: 
  - Implement synchronization contract with `stream_epoch`, `frame_pts`, `time_base`, `capture_timestamp`, `processing_timestamp`
  - UI correlates `video.currentTime` with `(capture_timestamp - latency)`
  - Prototype in Phase 1A before full integration
- **Evidence**: `GPUFrame` has PTS fields but no sync protocol; UI has no metadata handler

### R2: Legacy Backend Integration - Dual Database Conflict
- **Probability**: HIGH
- **Impact**: HIGH - Attendance events generated but invisible to UI; data fragmentation
- **Root Cause**: PipelineEngine writes to `attendance_events.db`, Legacy Backend owns `attendance.db`
- **Mitigation**:
  - Define Legacy Backend API contract for event ingestion (`POST /api/v1/attendance/events`)
  - Implement `LegacyBackendClient` in PipelineEngine
  - Remove PipelineEngine local SQLite store
  - Single authoritative DB: `data/attendance.db`
- **Evidence**: `backend/app.py` attendance endpoints return `[]`; `attendance_engine.py` uses separate SQLite

### R3: Shared Model Inference Contention
- **Probability**: HIGH
- **Impact**: HIGH - OOM errors, increased latency, frame drops
- **Root Cause**: Current per-camera model instances (~500MB VRAM each); Architecture A requires shared instances with batch queue
- **Mitigation**:
  - Implement batched inference (`detect_batch`, `infer_embeddings_batch`)
  - Add inference queue with max batch size / max wait time
  - Monitor VRAM via `GPUMemoryMonitor`, reduce batch under pressure
  - Test 2-camera sustained load
- **Evidence**: `CameraManager` creates separate SCRFD/ArcFace/YOLO per camera; no batch APIs

### R4: No True NVDEC on GTX 1660 Ti Windows
- **Probability**: HIGH (Confirmed)
- **Impact**: MEDIUM - Software decode bottleneck at 4K30 (~10ms/frame CPU)
- **Root Cause**: cuvid outputs `dxva2_vld` on Windows, not CUDA tensors
- **Mitigation**:
  - Test `nvcv_bridge.pyd` for true NVDEC (196KB .pyd in repo root)
  - Accept software decode + GPU upload (proven fallback)
  - Consider 1080p decode for AI (4× faster), 4K for video path
  - Separate decode process isolates CPU load
- **Evidence**: `nvdec_decoder.py` lines 164-171, 188-230 explicitly document this limitation

### R5: UI Canvas Overlay Performance at 4K
- **Probability**: MEDIUM
- **Impact**: MEDIUM - UI jank, dropped frames, poor UX
- **Root Cause**: Canvas size 3840×2160 = 8.3M pixels; per frame: ~10 tracks × drawing operations
- **Mitigation**:
  - Downscale canvas to display size (CSS transform)
  - Use `OffscreenCanvas` + Web Worker
  - Limit draw calls: batch boxes, use Path2D
  - Profile with Chrome DevTools
- **Evidence**: UI uses canvas for line drawing tool; no bbox rendering implemented

### R6: NPY Hot-Reload Race Conditions
- **Probability**: MEDIUM
- **Impact**: MEDIUM - New enrollments not recognized until restart
- **Root Cause**: ArcFaceRecognizer loads NPY at startup; UI writes new NPY; per-camera instances (2× GPU memory)
- **Mitigation**:
  - Single shared ArcFaceRecognizer instance
  - File watcher on `embeddings.npy` → reload on change
  - Or: Legacy Backend API notifies PipelineEngine
- **Evidence**: `CameraManager` creates ArcFace per camera; `load_enrollment_database` called once at init

### R7: Geometry Config Sync Drift
- **Probability**: MEDIUM
- **Impact**: MEDIUM - Wrong attendance counting, crossed lines not detected
- **Root Cause**: UI saves lines via WebSocket; PipelineEngine reads from `pipeline.yaml` at startup
- **Mitigation**:
  - Legacy Backend owns geometry config
  - PipelineEngine subscribes to config changes (WebSocket or polling)
  - Atomic config update without camera restart (tracker reset only)
- **Evidence**: `backend/app.py` PUT endpoint calls `CameraManager.update_camera_config()` which restarts camera

---

## Medium Risks

### R8: FramePool Exhaustion Under Load
- **Probability**: LOW
- **Impact**: MEDIUM - Silent frame drops
- **Mitigation**: Increase pool size, add backpressure to RTSP source, monitor `exhaustion_events`

### R9: Reconnection Storm
- **Probability**: LOW
- **Impact**: MEDIUM - Multiple cameras reconnecting simultaneously overwhelm MediaMTX/GPU
- **Mitigation**: Jitter implemented (±10%), add global reconnection semaphore, stagger startup

### R10: Attendance Event Burst Loss
- **Probability**: LOW
- **Impact**: MEDIUM - Many simultaneous crossings exceed callback capacity
- **Mitigation**: Async event queue with worker thread, batch push to Legacy Backend, circuit breaker

### R11: CUDA OOM During Model Load
- **Probability**: MEDIUM
- **Impact**: HIGH - 3 models × 2 cameras = 6 instances may exceed 6GB VRAM
- **Mitigation**: Architecture A shared models (1× each), lazy load, FP16 quantization

### R12: NVENC OSError -129 Instability
- **Probability**: LOW (Architecture A removes NVENC)
- **Impact**: HIGH - Intermittent encoder failures
- **Mitigation**: Architecture A removes NVENC entirely (metadata-only output)

---

## Unknowns (Insufficient Evidence)

### U1: nvcv_bridge.pyd Capability
- **File**: `nvcv_bridge.pyd` (196KB) in repo root
- **Unknown**: Whether it enables true NVDEC on Windows GTX 1660 Ti
- **Investigation**: Import and test in Python; check symbols
- **Priority**: HIGH - Could solve R4

### U2: TensorRT 11.3 Integration Potential
- **Directory**: `TensorRT-11.3.0.99/` in repo root
- **Unknown**: Whether ONNX models can be converted to TensorRT engines for faster inference
- **Investigation**: Check ONNX compatibility, build engines, benchmark
- **Priority**: MEDIUM - Performance optimization

### U3: Video_Codec_SDK_13.0.37 Usage
- **Directory**: `Video_Codec_SDK_13.0.37/` in repo root
- **Unknown**: Whether needed for nvcv_bridge or custom NVDEC/NVENC
- **Investigation**: Check nvcv_bridge dependencies
- **Priority**: LOW

### U4: Isolated_src/ and Isolated_tests/ Content
- **Directories**: `isolated_src/`, `isolated_tests/`
- **Unknown**: Whether they contain alternative implementations or tests
- **Investigation**: Explore contents
- **Priority**: LOW

### U5: Phase7 Runtime Diagnostic Results
- **Directory**: `phase7_runtime_diagnostic/`
- **Unknown**: Previous runtime test results, performance baselines
- **Investigation**: Read any logs/reports
- **Priority**: MEDIUM - Could provide baseline data

### U6: Benchmark Results
- **Directory**: `benchmark_results/`
- **Unknown**: Historical performance data
- **Investigation**: Check for CSV/JSON results
- **Priority**: LOW

### U7: Actual Camera Stream Specifications
- **Unknown**: Real camera bitrate, GOP, codec profile, keyframe interval
- **Impact**: Decoder/encoder config tuning, stream copy feasibility
- **Investigation**: Analyze live streams with ffprobe
- **Priority**: HIGH - Needed for decoder tuning

### U8: Legacy Backend Actual API Schema
- **Unknown**: Exact endpoints, request/response formats, WebSocket messages
- **Impact**: Integration contract definition
- **Investigation**: Access Legacy Backend source (already done in Phase 0.1) or Swagger/OpenAPI spec
- **Priority**: HIGH - Contract definition complete in 09_ai_worker_backend_integration_contract.md

### U9: Production Load Characteristics
- **Unknown**: Peak concurrent persons, crossing rate, enrollment size
- **Impact**: Tracker memory bounds, DB sizing, inference batching
- **Investigation**: Analyze production logs or simulate
- **Priority**: MEDIUM

### U10: GPU Memory Fragmentation Over Time
- **Unknown**: Whether FramePool + model tensors cause fragmentation after hours/days
- **Impact**: Silent performance degradation, allocation failures
- **Investigation**: Long-running stress test with memory profiling
- **Priority**: MEDIUM

---

## Risk Register Summary

| ID | Risk | Probability | Impact | Phase 0.1 Action |
|----|------|-------------|--------|------------------|
| B1 | MediaMTX not running | BLOCKED | CRITICAL | Document start procedure |
| B2 | Legacy Backend not running | BLOCKED | CRITICAL | Document start procedure |
| B3 | Camera publishers not running | BLOCKED | CRITICAL | Document as unknown |
| B4 | Enrollment DB missing | BLOCKED | HIGH | Document as unknown |
| R1 | Timestamp sync failure | HIGH | HIGH | Design sync contract (done in 10) |
| R2 | Legacy Backend integration | HIGH | HIGH | Define API contract (done in 09) |
| R3 | Model contention | HIGH | HIGH | Design batch queue (planned) |
| R4 | No true NVDEC | HIGH | MEDIUM | Test nvcv_bridge (planned) |
| R5 | UI overlay perf | MEDIUM | MEDIUM | Design downscaling (planned) |
| R6 | NPY hot-reload | MEDIUM | MEDIUM | Design file watcher (planned) |
| R7 | Geometry sync | MEDIUM | MEDIUM | Legacy Backend owns config (done) |
| U1 | nvcv_bridge capability | UNKNOWN | HIGH | Investigate in Phase 1 |
| U7 | Camera stream specs | UNKNOWN | HIGH | Need live stream |
| U8 | Legacy Backend API | PARTIAL | HIGH | Documented in 06, 09 |

---

## Blocker Resolution Priority

1. **B1** (MediaMTX) - Prerequisite for all stream verification
2. **B2** (Legacy Backend) - Prerequisite for API integration
3. **B3** (Camera publishers) - Prerequisite for end-to-end
4. **B4** (Enrollment DB) - Prerequisite for face recognition
5. **B6** (Test suite) - Can be developed in parallel

---

## Unknown Resolution Priority

1. **U1** (nvcv_bridge) - Could solve R4
2. **U8** (Legacy Backend API) - Already documented in Phase 0.1
3. **U7** (Camera specs) - Needed for decoder/encoder tuning
4. **U2/U3** (TensorRT/Video SDK) - Performance optimization
5. **U4/U5/U6** (Historical data) - Context for decisions