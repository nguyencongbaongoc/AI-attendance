# Phase 0 Final Verdict

## Executive Summary

**VERDICT: PHASE 0 PARTIAL**

Phase 0 forensic audit completed with comprehensive static analysis of the `pipeline_engine/` codebase. All 15 required audit artifacts created under `new_engine/audit/`. Runtime verification **BLOCKED** due to missing environment dependencies (CUDA, MediaMTX, cameras, Legacy Backend).

---

## Answers to Required Questions

### 1. What currently works?
**Source code implementation is complete** for all pipeline modules:
- Configuration loading (Pydantic + YAML)
- Pipeline orchestration (state machine, supervisor, health monitoring)
- RTSP ingestion (PyAV, reconnection, readiness gate, health monitoring)
- Video decode (software decode + GPU upload, FramePool integration)
- AI inference (SCRFD face detection, ArcFace recognition, YOLO person detection - all ONNX Runtime CUDA EP with IO Binding)
- Tracking (geometry-based, face association, identity fusion)
- Attendance (line crossing detection, debouncing, SQLite store)
- GPU annotation (NV12↔BGR conversions, box/label/line drawing)
- Video encode (NVENC, zero-copy DLPack, OSError -129 restart logic)
- MediaMTX publishing (PyAV RTSP muxer, FFmpeg fallback)
- GPU memory management (GPUFrame contract, FramePool, VRAM monitoring)
- Internal REST API (FastAPI, camera control, health, geometry, WebSocket)

### 2. What only exists as source code?
**Everything** - No component has been runtime verified. All modules exist as Python source files (~13,500 lines across 32 files) but have never executed in the target environment.

### 3. What has been tested?
**Only mock tests in `__main__` blocks** (4 modules):
- `tracking/tracker.py` - Mock detections → track creation/identity assignment
- `attendance/attendance_engine.py` - Mock tracks crossing line → IN/OUT events
- `memory/frame_pool.py` - Acquire/release cycles, pool reuse
- `memory/memory_monitor.py` - Tensor allocation triggers pressure callbacks

**Zero automated tests** - All `pipeline_engine/tests/` subdirectories empty.

### 4. What has been verified in actual runtime?
**Nothing** - All runtime verification **BLOCKED** by missing:
- NVIDIA GTX 1660 Ti + CUDA 12.6 environment
- MediaMTX server running on ports 8554/8888/8889/9997
- 2x RTSP camera streams (or test video files)
- Legacy Backend API on port 8000
- Enrollment database (`data/embeddings.npy` + metadata)

### 5. What prevents the current engine from operating end-to-end?

| Blocker | Severity | Components Affected |
|---------|----------|---------------------|
| No GPU/CUDA environment | CRITICAL | All inference, decode, encode, memory |
| No MediaMTX running | CRITICAL | RTSP ingestion, encoding output, UI playback |
| No camera streams | CRITICAL | Ingestion, decode, full pipeline |
| No Legacy Backend | CRITICAL | Attendance events, UI data, config sync |
| No enrollment DB | HIGH | Face recognition, tracking identity, attendance person_id |
| No test suite | HIGH | Regression prevention, CI/CD |
| NVENC OSError -129 | MEDIUM | Encoder stability (mitigated by restart logic) |
| No true NVDEC on Windows | MEDIUM | Decode performance (software fallback works) |

### 6. Which components can be reused?

| Component | Classification | Notes |
|-----------|----------------|-------|
| `config/__init__.py` + `pipeline.yaml` | **KEEP** | Core config system |
| `ingestion/rtsp_source.py` | **KEEP** | PyAV RTSP reader |
| `inference/face_detection.py` (SCRFD) | **KEEP** | Core AI, needs batch support |
| `inference/face_recognition.py` (ArcFace) | **KEEP** | Core AI, needs shared instance |
| `inference/person_detection.py` (YOLO) | **KEEP** | Core AI, needs batch support |
| `memory/gpu_frame.py` | **KEEP** | GPUFrame contract, DLPack zero-copy |
| `memory/frame_pool.py` | **ADAPT** | Reduce size, share across cameras |
| `memory/memory_monitor.py` | **KEEP** | VRAM monitoring |
| `tracking/tracker.py` | **ADAPT** | Stateless, shared instance |
| `attendance/attendance_engine.py` | **ADAPT** | Remove SQLite, push to Legacy Backend |
| MediaMTX | **KEEP** | Video path relay, recording, HLS/WebRTC |

### 7. Which components need adaptation?

| Component | Adaptation Required |
|-----------|---------------------|
| `camera_manager.py` | Remove encoder/publisher/annotator; shared models; batch queue |
| `nvdec_decoder.py` | Move to separate process; software decode acceptable |
| `tracker.py` | Make stateless per-frame function; single shared instance |
| `attendance_engine.py` | Remove local SQLite; add LegacyBackendClient HTTP push |
| `frame_pool.py` | Reduce max_size (no encoder); shared pool manager |
| `pipeline.yaml` | Split: video path config vs AI path config |
| `integration/__init__.py` | Implement LegacyBackendClient for event push |
| `inference/*.py` | Add `detect_batch()`, `infer_embeddings_batch()` methods |

### 8. Which components appear unnecessary under Architecture A?

| Component | Classification | Reason |
|-----------|----------------|--------|
| `encode/nvenc_encoder.py` | **REMOVE CANDIDATE** | No video output for AI path |
| `output/publisher.py` | **REMOVE CANDIDATE** | No video publishing for AI path |
| `annotation/overlay.py` | **REMOVE CANDIDATE** | UI does canvas overlay |
| `core/engine.py` | **REPLACE** | Full pipeline orchestrator not needed |
| `backend/app.py` | **REPLACE** | Becomes internal service only |
| `camera_manager.py` | **REPLACE** | Simplified AI pipeline manager |
| `ingestion/rtmp_source.py` | **REMOVE CANDIDATE** | Stub only |
| `decode/pyav_decoder.py` | **REMOVE CANDIDATE** | Unused wrapper |
| `encode/pyav_encoder.py` | **REMOVE CANDIDATE** | Unused wrapper |
| `inference/reid.py` | **REMOVE CANDIDATE** | Disabled in config |
| `memory/ownership.py` | **REMOVE CANDIDATE** | Unused |
| `memory/synchronization.py` | **REMOVE CANDIDATE** | Minimal use |
| `monitoring/__init__.py` | **REMOVE CANDIDATE** | Empty |

### 9. What backend integration is required?

**Critical**: PipelineEngine must **NOT** be authoritative attendance store.

Required integration:
1. **Legacy Backend API contract** for event ingestion: `POST /api/v1/attendance/events`
2. **PipelineEngine → Legacy Backend**: HTTP push with retry/batching
3. **Legacy Backend → UI**: WebSocket broadcast of attendance events
4. **Single DB**: `data/attendance.db` owned by Legacy Backend
5. **Config sync**: Legacy Backend owns geometry/camera config; pushes to PipelineEngine
6. **NPY management**: Single shared ArcFaceRecognizer; file watcher or API notification

### 10. What are the unresolved synchronization and performance risks?

| Risk | Status | Mitigation |
|------|--------|------------|
| Timestamp sync (AI metadata ↔ video playback) | **UNRESOLVED** | PTS + wall-clock + latency in metadata; UI correlates |
| Shared model inference contention | **UNRESOLVED** | Batch inference queue, max batch size, VRAM monitoring |
| No true NVDEC on GTX 1660 Ti Windows | **UNRESOLVED** | Test nvcv_bridge.pyd; accept software decode |
| UI canvas overlay at 4K | **UNRESOLVED** | Downscale canvas, OffscreenCanvas, Web Worker |
| NPY hot-reload | **UNRESOLVED** | Shared ArcFace + file watcher |
| Geometry config sync drift | **UNRESOLVED** | Legacy Backend owns config, WebSocket push |

### 11. What is the recommended Phase 1 scope?

**Phase 1A: AI Pipeline Core** (Week 1-2)
- Extract PyAV reader + decoder + AI models into standalone process
- Implement batch inference queue (SCRFD, YOLO, ArcFace)
- Shared model instances (single per GPU)
- Stateless tracker as pure function
- AttendanceEngine → Legacy Backend HTTP push

**Phase 1B: Legacy Backend Integration** (Week 2-3)
- Legacy Backend receives events via API
- Legacy Backend broadcasts via WebSocket
- Legacy Backend owns `data/attendance.db`
- Remove PipelineEngine local SQLite

**Phase 1C: UI Overlay** (Week 3-4)
- hls.js plays raw streams (`live/cam1`, `live/cam2`)
- Canvas overlay renders tracks/boxes/lines from WebSocket
- Coordinate transform video→canvas
- Line drawing tool saves to Legacy Backend

**Phase 1D: Testing & Hardening** (Week 4-5)
- End-to-end 2-camera test
- Reconnection handling
- 4K30 sustained load test
- Timestamp sync verification

---

## Evidence Summary

| Artifact | File | Status |
|----------|------|--------|
| 00 Scope & Baseline | `00_phase_0_scope_and_baseline.md` | ✅ Complete |
| 01 Repository Inventory | `01_repository_inventory.md` | ✅ Complete |
| 02 File Inventory | `02_pipeline_engine_file_inventory.md` | ✅ Complete |
| 03 Module Dependency Map | `03_module_dependency_map.md` | ✅ Complete |
| 04 Data Flow & Call Graph | `04_actual_dataflow_and_callgraph.md` | ✅ Complete |
| 05 Video Ingestion/Decode/Encode | `05_video_ingestion_decode_encode_audit.md` | ✅ Complete |
| 06 GPU Memory & Frame Ownership | `06_gpu_memory_and_frame_ownership_audit.md` | ✅ Complete |
| 07 AI Inference & Tracking | `07_ai_inference_tracking_audit.md` | ✅ Complete |
| 08 Attendance & Database Ownership | `08_attendance_and_database_ownership_audit.md` | ✅ Complete |
| 09 Existing Backend Integration | `09_existing_backend_integration_audit.md` | ✅ Complete |
| 10 UI Integration | `10_ui_integration_audit.md` | ✅ Complete |
| 11 Runtime & Test Evidence | `11_runtime_and_test_evidence.md` | ✅ Complete |
| 12 Architecture A Evaluation | `12_architecture_a_evaluation.md` | ✅ Complete |
| 13 Legacy Reuse Matrix | `13_legacy_reuse_adapt_replace_matrix.md` | ✅ Complete |
| 14 Risks & Blockers | `14_risks_blockers_and_unknowns.md` | ✅ Complete |
| 15 Final Verdict | `15_phase_0_final_verdict.md` | ✅ Complete |

---

## Phase 0 Compliance Check

| Constraint | Compliance |
|------------|------------|
| No file deletion/renaming | ✅ No source files modified |
| No backend/UI/database changes | ✅ Read-only analysis |
| No dependency changes | ✅ No pip install/upgrade |
| No production processing | ✅ No runtime execution |
| No camera config changes | ✅ Read-only |
| No Git history modification | ✅ No commits |
| No mock results as runtime evidence | ✅ Explicitly marked BLOCKED |
| No unverified GPU claims | ✅ Documented software decode fallback |
| No external repo dependency | ✅ Self-contained audit |
| Static inspection for risky checks | ✅ All analysis static |

---

## Final Determination

**PHASE 0 PARTIAL**

**Reason**: All audit artifacts created with comprehensive static analysis, but runtime verification **BLOCKED** by missing environment. Phase 0 cannot be COMPLETE without at least one successful end-to-end pipeline execution in target environment.

**Next Step**: Set up runtime environment (CUDA, MediaMTX, cameras, Legacy Backend) and execute manual verification before proceeding to Phase 1.

**Approval Required**: Explicit user approval to proceed to Phase 1 implementation of Architecture A.