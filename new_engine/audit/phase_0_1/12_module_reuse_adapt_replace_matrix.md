# Module Reuse / Adapt / Replace Matrix

## Classification Guidelines

| Classification | Definition |
|----------------|------------|
| **KEEP** | Reuse without structural change; may need config updates |
| **ADAPT** | Preserve core functionality but change integration/interface |
| **REPLACE** | New implementation needed; old code not suitable |
| **REMOVE CANDIDATE** | Appears unnecessary under Architecture A; must not delete in Phase 0.1 |
| **UNKNOWN** | Insufficient evidence to classify |

---

## PipelineEngine Modules

### Config
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `config/__init__.py` | **KEEP** | Core config loading used by all | LOW |
| `config/pipeline.yaml` | **ADAPT** | Split: video path config stays, AI path config extracted | MEDIUM |

### Core
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `core/engine.py` | **REPLACE** | PipelineEngine orchestrates full pipeline; Architecture A needs AI-only orchestrator | HIGH |

### Ingestion
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `ingestion/rtsp_source.py` | **KEEP** | PyAV RTSP reader works for AI path | LOW |
| `ingestion/rtmp_source.py` | **REMOVE CANDIDATE** | Stub only, not used | LOW |
| `ingestion/packet_source.py` | **KEEP** | Base class for RTSP source | LOW |
| `ingestion/camera_manager.py` | **REPLACE** | Manages full per-camera pipeline; Architecture A needs simpler AI pipeline manager | HIGH |

### Decode
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `decode/nvdec_decoder.py` | **ADAPT** | Software decode + GPU upload works; move to separate process | MEDIUM |
| `decode/pyav_decoder.py` | **REMOVE CANDIDATE** | Duplicate wrapper, not used | LOW |

### Encode
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `encode/nvenc_encoder.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (no video output for AI path) | N/A |
| `encode/pyav_encoder.py` | **REMOVE CANDIDATE** | Duplicate wrapper, not used | LOW |

### Inference
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `inference/face_detection.py` (SCRFD) | **KEEP** | Core AI, thread-safe with batch support needed | LOW |
| `inference/face_recognition.py` (ArcFace) | **KEEP** | Core AI, shared instance across cameras | LOW |
| `inference/person_detection.py` (YOLO) | **KEEP** | Core AI, thread-safe with batch support needed | LOW |
| `inference/reid.py` | **REMOVE CANDIDATE** | Disabled in config, not integrated | LOW |
| `inference/base.py` | **KEEP** | Base class for inference models | LOW |
| `inference/preprocessing.py` | **ADAPT** | Merge with gpu_frame.py utilities | LOW |

### Tracking
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `tracking/tracker.py` | **ADAPT** | Make stateless per-frame, shared instance | MEDIUM |
| `tracking/association.py` | **KEEP** | Utility functions for tracker | LOW |

### Attendance
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `attendance/attendance_engine.py` | **ADAPT** | Remove local SQLite, push events to Legacy Backend | MEDIUM |

### Annotation
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `annotation/overlay.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (UI does overlay) | N/A |

### Memory
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `memory/gpu_frame.py` | **KEEP** | Core GPUFrame contract, zero-copy foundation | LOW |
| `memory/frame_pool.py` | **ADAPT** | Reduce pool size (no encoder), shared across cameras | LOW |
| `memory/ownership.py` | **REMOVE CANDIDATE** | Unused, adds complexity | LOW |
| `memory/memory_monitor.py` | **KEEP** | VRAM monitoring for AI process | LOW |
| `memory/synchronization.py` | **REMOVE CANDIDATE** | Partially used, not critical | LOW |

### Output
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `output/publisher.py` | **REMOVE CANDIDATE** | Not needed in Architecture A (no video publish) | N/A |

### Backend
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `backend/app.py` | **REPLACE** | Becomes internal service; Legacy Backend is public API | HIGH |

### Monitoring
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `monitoring/__init__.py` | **REMOVE CANDIDATE** | Skeleton only, no implementation | LOW |

### Integration
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `integration/__init__.py` | **ADAPT** | Becomes LegacyBackendClient for event push | MEDIUM |

---

## Legacy Backend Modules (`app/`)

### Core
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `main.py` | **KEEP** | FastAPI entry point | LOW |
| `config/settings.py` | **KEEP** | Central configuration | LOW |
| `bootstrap/port_discovery.py` | **KEEP** | Dynamic port allocation | LOW |

### API Routers
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `api/health.py` | **KEEP** | Health monitoring | LOW |
| `api/attendance.py` | **ADAPT** | Add AI worker event ingestion endpoint | MEDIUM |
| `api/websocket.py` | **KEEP** | Real-time health + attendance | LOW |
| `api/geometry.py` | **KEEP** | Geometry management (UI + AI sync) | LOW |
| `api/enrollment.py` | **ADAPT** | Add NPY reload notification | MEDIUM |
| `api/replay.py` | **KEEP** | Video replay | LOW |
| `api/persons.py` | **KEEP** | Person management | LOW |
| `api/timetable.py` | **KEEP** | Timetable management | LOW |
| `api/excel.py` | **KEEP** | Excel export | LOW |
| `api/parent_telegram.py` | **KEEP** | Notifications | LOW |
| `api/provenance.py` | **KEEP** | Provenance chain | LOW |

### Attendance System
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `attendance/contract.py` | **KEEP** | Core data contracts | LOW |
| `attendance/repository.py` | **KEEP** | Persistence layer | LOW |
| `attendance/storage.py` | **KEEP** | SQLite storage | LOW |
| `attendance/query.py` | **KEEP** | Query builder | LOW |
| `attendance/policy_engine/` | **KEEP** | Business logic | LOW |

### Streaming Pipeline
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `streaming/camera_supervisor.py` | **KEEP** | Camera lifecycle (video path) | LOW |
| `streaming/annotated_publisher.py` | **REMOVE CANDIDATE** | Not needed (Architecture A: no annotation in pipeline) | MEDIUM |
| `streaming/rtsp_source.py` | **KEEP** | RTSP ingestion (video path) | LOW |
| `streaming/rtmp_source.py` | **KEEP** | RTMP ingestion (video path) | LOW |
| `streaming/shared_health.py` | **KEEP** | Cross-process health | LOW |

### In/Out Resolution
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `in_out/resolver.py` | **KEEP** | Phase 24 resolution | LOW |
| `in_out/resolver_contract.py` | **KEEP** | Data contracts | LOW |
| `in_out/event.py` | **KEEP** | Raw events | LOW |

### Geometry
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `geometry/` | **KEEP** | Line management | LOW |

### Vision / Enrollment
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `vision/` | **ADAPT** | Add NPY reload notification | MEDIUM |

### Replay / Provenance / Output
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `replay/` | **KEEP** | Video replay | LOW |
| `provenance/` | **KEEP** | Provenance chain | LOW |
| `output/` | **KEEP** | Static file serving | LOW |

### Models / Data / Logging / Operational / Runtime
| Module | Classification | Rationale | Migration Risk |
|--------|----------------|-----------|----------------|
| `models/` | **KEEP** | Database models | LOW |
| `data/` | **KEEP** | Data directory management | LOW |
| `logging/` | **KEEP** | Logging config | LOW |
| `operational/` | **KEEP** | Operational tools | LOW |
| `runtime/` | **KEEP** | Runtime snapshot | LOW |

---

## External Dependencies

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

## Summary Statistics

| Classification | PipelineEngine | Legacy Backend | External |
|----------------|----------------|----------------|----------|
| **KEEP** | 7 | 28 | 7 |
| **ADAPT** | 10 | 4 | 1 |
| **REPLACE** | 4 | 0 | 0 |
| **REMOVE CANDIDATE** | 12 | 1 | 1 |
| **UNKNOWN** | 0 | 0 | 1 |

---

## Phase 0.1 Constraint Compliance

> **Do not delete, rename, move, overwrite, or rewrite existing source files.**

All **REMOVE CANDIDATE** and **REPLACE** items are **NOT deleted in Phase 0.1**. They are marked for Phase 1+ action after Architecture A verification.

Phase 0.1 deliverable: This classification matrix only.