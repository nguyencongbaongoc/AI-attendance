# Legacy Reuse / Adapt / Replace Matrix

## Classification Guidelines

| Classification | Definition |
|----------------|------------|
| **KEEP** | Reuse without structural change; may need config updates |
| **ADAPT** | Preserve core functionality but change integration/interface |
| **REPLACE** | New implementation needed; old code not suitable |
| **REMOVE CANDIDATE** | Appears unnecessary under Architecture A; must not delete in Phase 0 |
| **UNKNOWN** | Insufficient evidence to classify |

---

## Module Classification Matrix

| Module/File | Classification | Rationale | Dependencies | Migration Risk | Evidence |
|-------------|----------------|-----------|--------------|----------------|----------|
| **Config** | | | | | |
| `config/__init__.py` | **KEEP** | Core config loading used by all | None | LOW | Used everywhere via `get_config()` |
| `config/pipeline.yaml` | **ADAPT** | Split: video path config stays, AI path config extracted | All modules | MEDIUM | Single source of truth |
| **Core** | | | | | |
| `core/engine.py` | **REPLACE** | PipelineEngine orchestrates full pipeline; Architecture A needs AI-only orchestrator | All modules | HIGH | 591 lines, deep integration |
| **Ingestion** | | | | | |
| `ingestion/rtsp_source.py` | **KEEP** | PyAV RTSP reader works for AI path | PyAV | LOW | Standalone, well-isolated |
| `ingestion/rtmp_source.py` | **REMOVE CANDIDATE** | Stub only, not used | - | LOW | Empty implementation |
| `ingestion/packet_source.py` | **KEEP** | Base class for RTSP source | - | LOW | Minimal |
| `ingestion/camera_manager.py` | **REPLACE** | Manages full per-camera pipeline; Architecture A needs simpler AI pipeline manager | All pipeline modules | HIGH | 971 lines, creates all components |
| **Decode** | | | | | |
| `decode/nvdec_decoder.py` | **ADAPT** | Software decode + GPU upload works; move to separate process | PyAV, torch, FramePool | MEDIUM | No true NVDEC on Windows GTX 1660 Ti |
| `decode/pyav_decoder.py` | **REMOVE CANDIDATE** | Duplicate wrapper, not used | - | LOW | Unused |
| **Encode** | | | | | |
| `encode/nvenc_encoder.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (no video output for AI path) | PyAV, torch, FramePool | N/A | 616 lines, OSError -129 handling |
| `encode/pyav_encoder.py` | **REMOVE CANDIDATE** | Duplicate wrapper, not used | - | LOW | Unused |
| **Inference** | | | | | |
| `inference/face_detection.py` (SCRFD) | **KEEP** | Core AI, thread-safe with batch support needed | ONNX Runtime, torch | LOW | 585 lines, IO Binding |
| `inference/face_recognition.py` (ArcFace) | **KEEP** | Core AI, shared instance across cameras | ONNX Runtime, torch, NPY | LOW | ~500 lines, enrollment DB |
| `inference/person_detection.py` (YOLO) | **KEEP** | Core AI, thread-safe with batch support needed | ONNX Runtime, torch | LOW | ~400 lines |
| `inference/reid.py` | **REMOVE CANDIDATE** | Disabled in config, not integrated | ONNX Runtime, torch | LOW | Disabled |
| `inference/base.py` | **KEEP** | Base class for inference models | - | LOW | Shared utilities |
| `inference/preprocessing.py` | **ADAPT** | Merge with gpu_frame.py utilities | torch | LOW | Duplicate with gpu_frame.py |
| **Tracking** | | | | | |
| `tracking/tracker.py` | **ADAPT** | Make stateless per-frame, shared instance | numpy, ArcFace | MEDIUM | 685 lines, geometry-based |
| `tracking/association.py` | **KEEP** | Utility functions for tracker | numpy | LOW | Helpers |
| **Attendance** | | | | | |
| `attendance/attendance_engine.py` | **ADAPT** | Remove local SQLite, push events to Legacy Backend | Tracker, SQLite | MEDIUM | 644 lines, line crossing logic |
| **Annotation** | | | | | |
| `annotation/overlay.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (UI does overlay) | torch, GPUFrame | N/A | 365 lines, font placeholder |
| **Memory** | | | | | |
| `memory/gpu_frame.py` | **KEEP** | Core GPUFrame contract, zero-copy foundation | torch | LOW | 626 lines, DLPack support |
| `memory/frame_pool.py` | **ADAPT** | Reduce pool size (no encoder), shared across cameras | GPUFrame, torch | LOW | 466 lines, hybrid strategy |
| `memory/ownership.py` | **REMOVE CANDIDATE** | Unused, adds complexity | - | LOW | Not imported anywhere |
| `memory/memory_monitor.py` | **KEEP** | VRAM monitoring for AI process | torch | LOW | 437 lines, callbacks |
| `memory/synchronization.py` | **REMOVE CANDIDATE** | Partially used, not critical | torch | LOW | CUDASyncManager |
| **Output** | | | | | |
| `output/publisher.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (no video publish) | PyAV, subprocess | N/A | 532 lines, two implementations |
| **Backend** | | | | | |
| `backend/app.py` | **REPLACE** | Becomes internal service; Legacy Backend is public API | PipelineEngine | HIGH | 602 lines, duplicate endpoints |
| **Monitoring** | | | | | |
| `monitoring/__init__.py` | **REMOVE CANDIDATE** | Skeleton only, no implementation | - | LOW | Empty |
| **Integration** | | | | | |
| `integration/__init__.py` | **ADAPT** | Becomes LegacyBackendClient for event push | Legacy Backend API | MEDIUM | Stub only |

---

## External Dependencies Classification

| Dependency | Classification | Rationale |
|------------|----------------|-----------|
| MediaMTX | **KEEP** | Video path relay, recording, HLS/WebRTC |
| PyAV | **KEEP** | RTSP reading, decode, DLPack |
| FFmpeg | **KEEP** | Via PyAV, MediaMTX |
| ONNX Runtime | **KEEP** | AI inference (SCRFD, ArcFace, YOLO) |
| PyTorch CUDA | **KEEP** | GPU tensors, preprocessing, DLPack |
| CUDA Toolkit | **KEEP** | GPU compute |
| cuDNN | **KEEP** | Deep learning primitives |
| TensorRT | **REMOVE CANDIDATE** | Not used (SDK present but no integration) |
| nvcv_bridge | **UNKNOWN** | Custom .pyd exists, untested for NVDEC |
| Legacy Backend | **KEEP** | Authoritative attendance data owner |
| UI (index.html) | **ADAPT** | Canvas overlay for AI metadata |

---

## Data Flow Classification

| Data Flow | Classification | Notes |
|-----------|----------------|-------|
| Camera → MediaMTX (RTMP) | **KEEP** | Video path |
| MediaMTX → UI (HLS/WebRTC) | **KEEP** | Video path |
| Camera → PyAV → Decode → AI | **KEEP** | AI path |
| AI → Tracker → Attendance | **KEEP** | AI path |
| Attendance → Legacy Backend | **ADAPT** | New: HTTP push from PipelineEngine |
| Attendance → UI (WebSocket) | **ADAPT** | Legacy Backend broadcasts |
| AI → Annotator → Encoder → MediaMTX | **REMOVE CANDIDATE** | Architecture A: no annotation/encode |
| Geometry config (UI ↔ PipelineEngine) | **ADAPT** | UI → Legacy Backend → PipelineEngine |
| Enrollment NPY (UI → PipelineEngine) | **ADAPT** | Single shared ArcFace instance |

---

## Configuration Classification

| Config Section | Classification | Architecture A Handling |
|----------------|----------------|------------------------|
| `runtime` | **KEEP** | AI process runtime settings |
| `gpu` | **KEEP** | AI process GPU settings |
| `cameras` (input) | **KEEP** | AI path RTSP URLs |
| `cameras` (output) | **REMOVE CANDIDATE** | No AI video output |
| `cameras` (geometry) | **ADAPT** | Legacy Backend owns, pushes to AI |
| `cameras` (decode) | **KEEP** | AI decode settings |
| `cameras` (encode) | **REMOVE CANDIDATE** | No AI encoding |
| `decode` | **KEEP** | AI decode defaults |
| `inference` | **KEEP** | AI inference settings |
| `models` | **KEEP** | AI model paths |
| `tracking` | **KEEP** | AI tracking settings |
| `attendance` | **ADAPT** | Legacy Backend DB paths |
| `annotation` | **REMOVE CANDIDATE** | No GPU annotation |
| `encode` | **REMOVE CANDIDATE** | No AI encoding |
| `output` | **REMOVE CANDIDATE** | No AI publishing |
| `backend` | **REMOVE CANDIDATE** | PipelineEngine internal only |
| `frontend` | **REMOVE CANDIDATE** | Legacy Backend serves UI |
| `monitoring` | **ADAPT** | AI process monitoring |
| `integration` | **ADAPT** | Legacy Backend client config |

---

## Detailed Migration Notes

### HIGH PRIORITY: Must Adapt for Architecture A

1. **`camera_manager.py` → New AI Pipeline Manager**
   - Remove: encoder, publisher, annotator creation
   - Remove: per-camera model instantiation
   - Add: Shared model registry, batch inference queue
   - Simplify: Only RTSP source, decoder, AI inference, tracker, attendance

2. **`attendance_engine.py` → Legacy Backend Client**
   - Remove: `AttendanceStore` (SQLite)
   - Add: `LegacyBackendClient.push_event(event)`
   - Add: Retry logic, batching
   - Keep: `CrossingEngine` logic (pure geometry)

3. **`tracker.py` → Stateless Tracker**
   - Remove: Internal track state (`self._tracks`)
   - Add: `process_frame(prev_tracks, detections, embeddings) → new_tracks`
   - Make: Pure function, no internal state
   - Shared: Single instance across cameras

4. **Inference Models → Batched Inference**
   - Add: `detect_batch(frames: List[GPUFrame]) → List[List[Detection]]`
   - Add: `infer_embeddings_batch(crops: List[Tensor]) → List[Embedding]`
   - Thread-safe: Lock or queue per model

5. **`frame_pool.py` → Shared Pool Manager**
   - Reduce: `max_size` from 32 to 16 (no encoder frames)
   - Share: Single FramePoolManager across cameras
   - Add: `acquire_batch(count) → List[GPUFrame]`

### MEDIUM PRIORITY: Replace with New Implementation

1. **`core/engine.py` → AI Pipeline Orchestrator**
   - New: `AIPipelineOrchestrator`
   - Responsibilities: Start AI process, health monitoring, model loading, batch queue
   - No: Camera lifecycle, encoder, publisher, annotation

2. **`backend/app.py` → Internal AI Service**
   - New: `AIInternalAPI` (FastAPI on internal port)
   - Endpoints: `/health`, `/metrics`, `/control` (start/stop AI)
   - No: Public attendance, camera, geometry endpoints
   - Push: Events to Legacy Backend

### LOW PRIORITY: Remove (Phase 1+)

1. `encode/nvenc_encoder.py` - Delete after Architecture A verified
2. `output/publisher.py` - Delete after Architecture A verified
3. `annotation/overlay.py` - Delete after Architecture A verified
4. `memory/ownership.py` - Delete (unused)
5. `memory/synchronization.py` - Delete (minimal use)
6. `monitoring/__init__.py` - Delete (empty)
7. `integration/__init__.py` - Replace with LegacyBackendClient
8. `ingestion/rtmp_source.py` - Delete (stub)
9. `decode/pyav_decoder.py` - Delete (unused wrapper)
10. `encode/pyav_encoder.py` - Delete (unused wrapper)
11. `inference/reid.py` - Delete (disabled)

---

## Effort Estimation

| Classification | Count | Estimated Effort |
|----------------|-------|------------------|
| KEEP | 12 | Low (config updates only) |
| ADAPT | 10 | Medium (interface changes) |
| REPLACE | 3 | High (new implementations) |
| REMOVE CANDIDATE | 12 | Low (deletion after verification) |
| UNKNOWN | 1 | Investigation needed |

**Total modules**: 38 (including submodules)

---

## Phase 0 Constraint Compliance

> **Do not delete, rename, move, overwrite, or rewrite existing source files.**

All **REMOVE CANDIDATE** and **REPLACE** items are **NOT deleted in Phase 0**. They are marked for Phase 1+ action after Architecture A verification.

Phase 0 deliverable: This classification matrix only.