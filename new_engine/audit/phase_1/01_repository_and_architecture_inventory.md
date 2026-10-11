# Phase 1 — Repository and Architecture Inventory

**Date:** 2026-10-04  
**Phase:** 1  
**Artifact:** 01  

---

## 1. Repository Root Structure

```
AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE/
├── .kilo/                    # Kilo configuration
├── .venv_38p_isolated/       # Isolated Python 3.8 venv
├── .venv2/                   # Primary venv
├── .vscode/                  # VS Code settings
├── app/                      # Legacy Backend API
│   ├── api/                  # REST endpoints
│   ├── attendance/           # Phase 22-25 attendance pipeline
│   ├── config/               # Settings
│   ├── data/                 # Databases (attendance.db: 108 records)
│   ├── main.py               # FastAPI app entry
│   └── vision/               # Vision/enrollment
├── benchmark_results/        # Phase 3-44 artifacts
├── config/                   # Config files
├── data/                     # Secondary databases (attendance.db: 18 records, attendance_events.db: 0)
├── docs/                     # Documentation
├── isolated_src/             # Isolated source
├── isolated_tests/           # Isolated tests
├── logs/                     # Runtime logs
├── mediamtx/                 # MediaMTX server
├── models/                   # Model files
│   ├── arcface/glintr100.onnx (260MB)
│   ├── scrfd/scrfd_10g_bnkps.onnx (16MB)
│   ├── yolo/yolo11n.onnx (10MB)
│   └── ...
├── new_engine/               # Phase audit artifacts
│   └── audit/phase_0_2_6/    # Phase 0.2.6 artifacts (18 files)
├── pipeline_engine/          # AI Worker / PipelineEngine
│   ├── config/pipeline.yaml  # Dual-camera config
│   ├── core/engine.py        # PipelineEngine (591 lines)
│   ├── inference/            # SCRFD, ArcFace, YOLO
│   ├── ingestion/            # CameraManager, RTSPSource
│   ├── tracking/tracker.py   # Tracking (685 lines)
│   ├── attendance/attendance_engine.py  # Crossing/Attendance (644 lines)
│   ├── integration/          # Health & Control clients
│   └── ...
├── scripts/                  # Utility scripts
├── TensorRT-11.3.0.99/       # TensorRT
├── test_data/                # Test data
├── tools/                    # Tools
├── UI/                       # Frontend source
├── Video_Codec_SDK_13.0.37/  # NVIDIA SDK
└── bootstrap.py              # Startup script
```

---

## 2. Key Source Files Inventory

### 2.1 Legacy Backend (`app/`)

| File | Lines | Purpose |
|------|-------|---------|
| `app/main.py` | 149 | FastAPI app, lifespan, routers, static mounts |
| `app/api/ai_worker.py` | 871 | Health + Control + Event ingestion endpoints |
| `app/api/enrollment.py` | 347 | Enrollment endpoints + NPY reload |
| `app/api/health.py` | ~200 | System health endpoints |
| `app/api/attendance.py` | ~300 | Attendance query endpoints |
| `app/api/persons.py` | ~200 | Person management |
| `app/api/timetable.py` | ~250 | Timetable management |
| `app/api/excel.py` | ~200 | Excel export |
| `app/api/parent_telegram.py` | ~300 | Telegram integration |
| `app/api/geometry.py` | ~200 | Geometry config |
| `app/api/replay.py` | ~200 | Video replay |
| `app/api/provenance.py` | ~200 | Provenance chain |
| `app/api/websocket.py` | ~200 | WebSocket/SSE |
| `app/attendance/storage.py` | 750 | SQLite storage for AttendanceRecord |
| `app/attendance/contract.py` | 359 | AttendanceRecord definition |
| `app/attendance/engine.py` | 28738 | Attendance engine (Phase 24 resolver) |
| `app/attendance/repository.py` | 12495 | Repository layer |
| `app/in_out/raw_event.py` | 261 | Phase 23 RawInOutEvent |
| `app/in_out/resolver.py` | ~300 | Phase 24 resolver |
| `app/config/settings.py` | 445 | Comprehensive settings |

### 2.2 PipelineEngine (`pipeline_engine/`)

| File | Lines | Purpose |
|------|-------|---------|
| `pipeline_engine/core/engine.py` | 591 | PipelineEngine state machine |
| `pipeline_engine/ingestion/camera_manager.py` | 971 | CameraManager - full pipeline per camera |
| `pipeline_engine/ingestion/rtsp_source.py` | ~200 | RTSP source with reconnect |
| `pipeline_engine/inference/face_detection.py` | 585 | SCRFD detector |
| `pipeline_engine/inference/face_recognition.py` | 441 | ArcFace recognizer |
| `pipeline_engine/inference/person_detection.py` | ~160 | YOLO person detector |
| `pipeline_engine/tracking/tracker.py` | 685 | Tracker with identity fusion |
| `pipeline_engine/attendance/attendance_engine.py` | 644 | Crossing engine + AttendanceEngine |
| `pipeline_engine/integration/health_client.py` | 349 | Health heartbeat client |
| `pipeline_engine/integration/control_client.py` | 479 | Control command server |
| `pipeline_engine/config/pipeline.yaml` | 434 | Complete dual-camera config |
| `pipeline_engine/config/__init__.py` | ~100 | Config loader |
| `pipeline_engine/decode/nvdec_decoder.py` | ~300 | NVDEC decoder |
| `pipeline_engine/encode/nvenc_encoder.py` | ~300 | NVENC encoder |
| `pipeline_engine/output/publisher.py` | ~200 | RTSP publisher |
| `pipeline_engine/annotation/overlay.py` | ~200 | GPU annotation |
| `pipeline_engine/memory/frame_pool.py` | ~200 | GPU frame pool |
| `pipeline_engine/memory/gpu_frame.py` | ~300 | GPUFrame wrapper |

---

## 3. Architecture Components Map

### 3.1 Video Path (Independent — Architecture A)

```
Camera RTSP
    ↓
MediaMTX (RTMP input :1935, RTSP output :8554)
    ↓
Original Unannotated Video → UI Video Player (HLS/WebRTC)
```

**Key Files:**
- `app/config/settings.py:CamerasConfig` — MediaMTX ports, camera URLs
- `pipeline_engine/config/pipeline.yaml:cameras` — cam1/cam2 RTSP URLs
- `app/main.py` — Static mount `/recordings` for replay

### 3.2 AI Path (Independent — Architecture A)

```
Camera RTSP
    ↓
RTSPSource (per camera, independent reconnect)
    ↓
NVDECDecoder (GPU, per camera)
    ↓
Frame Pool (GPU frames, NV12)
    ↓
SCRFDDetector (face + landmarks)
    ↓
Face Alignment (extract 112x112)
    ↓
ArcFaceRecognizer (512D embedding, L2 norm)
    ↓
Identity Matching (enrollment DB)
    ↓
YOLOPersonDetector (person bbox)
    ↓
Tracker (geometry + face association + identity)
    ↓
AttendanceEngine (line crossing → CrossingEvent)
    ↓
CrossingEvent → Legacy Backend API (/api/v1/attendance/events)
    ↓
Phase 23 RawInOutEvent → Phase 24 Resolver → Phase 25 AttendanceRecord
```

**Key Files:**
- `pipeline_engine/ingestion/camera_manager.py:_camera_pipeline_loop` — Full pipeline (lines 497-748)
- `pipeline_engine/inference/face_detection.py:detect()` — SCRFD inference
- `pipeline_engine/inference/face_recognition.py:infer_embedding()` — ArcFace inference
- `pipeline_engine/tracking/tracker.py:process_frame()` — Tracking
- `pipeline_engine/attendance/attendance_engine.py:process_tracks()` — Crossing detection

### 3.3 Integration Points

| Integration | Backend Endpoint | PipelineEngine Client |
|-------------|------------------|----------------------|
| Event Ingestion | `POST /api/v1/attendance/events` | Not yet implemented |
| Health Heartbeat | `POST /api/v1/health/ai-worker` | `health_client.py` ✅ |
| Health Status | `GET /api/v1/health/ai-worker/{worker_id}` | Not needed |
| Control Submit | `POST /api/v1/ai/control/{action}` | Not needed |
| Control Poll | `GET /api/v1/ai/control/pending` | `control_client.py` ✅ |
| Control Response | `POST /api/v1/ai/control/{action}/response` | `control_client.py` ✅ |
| Enrollment Reload | `POST /api/v1/enrollment/reload` | Not yet implemented |

---

## 4. Model Pipeline Contracts

### 4.1 SCRFD (Face Detection)
- **Model:** `models/scrfd/scrfd_10g_bnkps.onnx` (16.9MB)
- **Input:** 640×640 BGR, normalized (ImageNet mean/std)
- **Output:** Scores, bboxes, 5-point landmarks per stride (8, 16, 32)
- **Config:** confidence_threshold=0.5, nms_threshold=0.4
- **Implementation:** `pipeline_engine/inference/face_detection.py:SCRFDDetector`

### 4.2 ArcFace (Face Recognition)
- **Model:** `models/arcface/glintr100.onnx` (260MB)
- **Input:** 112×112 BGR, normalized: (x - 127.5) / 128.0
- **Output:** 512D embedding (L2 normalized on GPU)
- **Config:** similarity_threshold=0.6
- **Enrollment:** `data/embeddings.npy` + `data/embeddings.npy.metadata.json`
- **Implementation:** `pipeline_engine/inference/face_recognition.py:ArcFaceRecognizer`

### 4.3 YOLO (Person Detection)
- **Model:** `models/yolo/yolo11n.onnx` (10.7MB)
- **Input:** 640×640
- **Output:** Person bboxes (class_id=0)
- **Config:** confidence_threshold=0.5, nms_threshold=0.45
- **Implementation:** `pipeline_engine/inference/person_detection.py:YOLOPersonDetector`

---

## 5. Camera Configuration (from pipeline.yaml)

### CAM1
- **RTSP URL:** `rtsp://localhost:8554/live/cam1`
- **Output (AI):** `rtsp://localhost:8554/live/cam1-ai`
- **Resolution:** 3840×2160 @ 30fps, H.264
- **Decoder:** PyAV NVDEC, GPU 0, 32 surfaces
- **Encoder:** PyAV NVENC, H.264, 8000 kbps, CBR, preset p4, tune ll
- **Geometry Line:** (0, 1080) → (3840, 1080), direction: side_a_to_b_in
- **Crossing Policy:** min_distance=50, debounce=2s, confirm_frames=3

### CAM2
- **RTSP URL:** `rtsp://localhost:8554/live/cam2`
- **Output (AI):** `rtsp://localhost:8554/live/cam2-ai`
- **Resolution:** 3840×2160 @ 30fps, H.264
- **Decoder:** PyAV NVDEC, GPU 0, 32 surfaces
- **Encoder:** PyAV NVENC, H.264, 8000 kbps, CBR, preset p4, tune ll
- **Geometry Line:** (0, 1080) → (3840, 1080), direction: side_a_to_b_in
- **Crossing Policy:** Same as CAM1

---

## 6. Database Inventory

| Database | Path | Records | Purpose |
|----------|------|---------|---------|
| attendance.db (primary) | `app/data/attendance.db` | 108 | Authoritative AttendanceRecord |
| attendance.db (secondary) | `data/attendance.db` | 18 | Benchmark/secondary |
| attendance_events.db | `data/attendance_events.db` | 0 | PipelineEngine event store |
| exit_sessions.db | `app/data/exit_sessions.db` | - | Exit session persistence |
| notification_queue.db | `app/data/notification_queue.db` | - | Telegram queue |
| parent_registry.db | `app/data/parent_registry.db` | - | Parent linking |

---

## 7. Configuration Files

| File | Purpose |
|------|---------|
| `pipeline_engine/config/pipeline.yaml` | Single source of truth for PipelineEngine |
| `app/config/settings.py` | Legacy Backend settings (Pydantic Settings) |
| `config/` | Additional config files |
| `.env` | Environment variables (API keys) |

---

## 8. Git State

- **Branch:** main
- **HEAD:** 5269777 (feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline)
- **Status:** Clean working tree (only untracked files: UI/, new_engine/, analyze_quarantine.py, check_dbs.py, etc.)
- **Recent commits:**
  - 5269777: feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline
  - a31439c: về đây nếu 12 lỗi
  - 1fe2044: checkpoint: before readiness timeout fix
  - e402eba: RTMP Remediation
  - 4d32ffb: reconcile previously verified PASS remediations

---

## 9. Existing Tests

| Test File | Purpose |
|-----------|---------|
| `tests/` | Various test files |
| `scripts/*.py` | Phase scripts (phase22-phase36) |
| `new_engine/audit/phase_0_2_6/health_integration_test.py` | 13 health tests |
| `new_engine/audit/phase_0_2_6/control_integration_test.py` | 17 control tests |
| `pipeline_engine/tests/` | PipelineEngine unit tests |

---

## 10. Phase 1 Implementation Gap Analysis

### What EXISTS (Reusable)
✅ PipelineEngine core with state machine
✅ CameraManager with full per-camera pipeline
✅ SCRFD, ArcFace, YOLO model implementations (GPU, IO Binding)
✅ Tracker with identity fusion
✅ AttendanceEngine with line crossing detection
✅ Health client (heartbeat sending)
✅ Control client (command polling + execution)
✅ Legacy Backend health/control/event endpoints
✅ Dual-camera configuration
✅ Model files on disk
✅ Attendance database schema

### What NEEDS IMPLEMENTATION
❌ **Event Delivery** — PipelineEngine → Legacy Backend event submission (`POST /api/v1/attendance/events`)
❌ **Worker Runtime** — Standalone worker process with lifecycle management
❌ **Enrollment Reload Integration** — PipelineEngine watching for enrollment changes
❌ **Timestamp Synchronization Contract** — Video ↔ AI metadata correlation
❌ **UI Metadata Overlay** — Canvas overlay for AI metadata on original video
❌ **End-to-End Test** — Full flow: Camera → AI → Event → Backend → AttendanceRecord
❌ **Dual-Camera Qualification** — Sustained runtime evidence
❌ **Failure/Recovery Tests** — Disconnect, GPU OOM, Backend down, etc.

---

## 11. Files Requiring Modification (Estimated)

| File | Change Type | Gate |
|------|-------------|------|
| `pipeline_engine/integration/event_client.py` | NEW — Event delivery to Backend | E |
| `pipeline_engine/core/worker.py` | NEW — Worker runtime | A |
| `pipeline_engine/ingestion/camera_manager.py` | PATCH — Event callback integration | D, E |
| `pipeline_engine/attendance/attendance_engine.py` | PATCH — Event callback to client | E |
| `pipeline_engine/config/__init__.py` | PATCH — Worker config | A |
| `app/api/ai_worker.py` | PATCH — Event schema alignment if needed | E |
| `scripts/phase1_worker.py` | NEW — Worker entry point | A |
| `bootstrap.py` | PATCH — Worker startup integration | A |

---

*End of Architecture Inventory*