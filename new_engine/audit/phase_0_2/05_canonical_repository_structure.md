# Phase 0.2 — Canonical Repository Structure

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage B: Define Canonical Repository Structure

---

## 1. Actual Subsystem Boundaries Identified

Based on forensic inventory, the repository contains these **independent, authoritative subsystems**:

| Subsystem | Location | Role | Authority |
|-----------|----------|------|-----------|
| **Legacy Backend** | `app/` | FastAPI REST API, attendance business logic, SQLite DB, WebSocket | **Attendance authority** |
| **Pipeline Engine** | `pipeline_engine/` | New Architecture A AI Worker (in progress) | AI inference pipeline |
| **MediaMTX** | `mediamtx/` | RTSP/RTMP/HLS/WebRTC media server | Video relay |
| **AI Models** | `models/` | ONNX/PT model files | Model storage |
| **Configuration** | `config/` | Pipeline YAML, geometry, port config | Config source |
| **Enrollment Data** | `app/data/enrollment/` | Embeddings NPY + metadata | Identity data |
| **Legacy DBs** | `app/data/` | SQLite databases | Attendance data |
| **Bootstrap** | `bootstrap.py`, `bootstrap.bat` | Pipeline orchestration | Startup entrypoint |
| **Tests** | `tests/` | Unit, integration, live tests | Verification |
| **Historical v2** | `video_pipeline_v2/` | Superseded NVENC pipeline | Reference only |
| **Documentation** | `docs/`, `reports/`, `new_engine/audit/` | Architecture, audit, ops docs | Knowledge base |

---

## 2. Proposed Canonical Structure

```
AI_ATTENDANCE/
│
├── app/                          # LEGACY BACKEND (authoritative attendance owner)
│   ├── main.py                   # FastAPI entrypoint
│   ├── api/                      # 11 routers (health, attendance, persons, timetable, excel, parent_telegram, geometry, enrollment, replay, provenance, websocket)
│   ├── attendance/               # Policy engine, calendar, contracts, daily resolution, engine, query, repository, storage, session, timetable
│   ├── bootstrap/                # MediaMTX readiness, port discovery, startup validation, venv management
│   ├── config/                   # Settings, paths
│   ├── data/                     # AUTHORITATIVE DATABASES
│   │   ├── attendance.db         # Primary attendance DB
│   │   ├── attendance.db-shm     # WAL
│   │   ├── attendance.db-wal     # WAL
│   │   ├── exit_sessions.db      # Exit sessions
│   │   ├── parent_registry.db    # Parent registry
│   │   ├── notification_queue.db # Notifications
│   │   └── enrollment/           # Enrollment embeddings
│   │       ├── embeddings.npy
│   │       └── embeddings.npy.metadata.json
│   ├── geometry/                 # Crossing geometry, transforms
│   ├── in_out/                   # Raw events, resolvers
│   ├── logging/                  # Structured logging
│   ├── models/                   # Pydantic contracts, exceptions, hashing, registry, validation
│   ├── operational/              # CLI tools
│   ├── output/                   # Adapters, publishers, UI adapter
│   ├── replay/                   # Annotated replay, annotation, appearance, clock, fusion, manifest, pipeline, recording, scheduler, source, video evidence
│   ├── runtime/                  # CUDA, detector, FFmpeg, GPU abstractions, IO binding, model session, residency, stream, telemetry, VRAM safety
│   ├── streaming/                # Annotated publisher, camera runtime, capture watchdog, contracts, detection pipeline, encoder, health, ingestion, instrumentation, MediaMTX config, publisher lifecycle, PyAV annotated/NVDEC/NVENC, reconnect, RTMP/RTSP source, shared health, supervised runner, telemetry, timestamp
│   ├── video/                    # PyNvCodec encoder, error, frame, GPU format, metrics, stream
│   └── vision/                   # Adaptive crop, ArcFace, association, crop, detection, detector contract/factory, enrollment, face quality, forensic trace, GPU 4K surface, GPU alignment, GPU annotation, GPU BGR↔NV12, GPU face detect, GPU inference, GPU pipeline, GPU preprocess, GPU ROI crop, hardpose, landmarks, matching, quality, recognition, RetinaFace, SCRFD, surface owners, temporal evidence, track contract, tracker, YOLO person detect
│
├── pipeline_engine/              # ARCHITECTURE A — AI WORKER (NEW)
│   ├── config/
│   │   └── pipeline.yaml         # Single pipeline config (434 lines)
│   ├── core/
│   │   └── engine.py             # PipelineEngine, EngineState
│   ├── ingestion/                # RTMP source, frame ingestion
│   ├── decode/                   # PyAV NVDEC backend
│   ├── encode/                   # PyAV NVENC backend
│   ├── inference/                # SCRFD, ArcFace, YOLO, ONNX Runtime
│   ├── tracking/                 # Tracker, association
│   ├── integration/              # Legacy backend adapter (HTTP client)
│   ├── monitoring/               # Health, metrics
│   ├── output/                   # Publisher (RTSP to MediaMTX)
│   ├── runtime/                  # Runtime management
│   ├── attendance/               # Attendance integration (ADAPTER ONLY — not authority)
│   ├── backend/                  # Legacy backend adapter
│   ├── memory/                   # Frame pool, GPU memory, system memory
│   └── annotation/               # Overlay rendering (for future UI)
│
├── mediamtx/                     # MEDIAMTX RUNTIME
│   ├── mediamtx.exe              # Binary (54 MB)
│   ├── mediamtx.yml              # Config (719 lines)
│   ├── auto.crt                  # TLS cert
│   ├── auto.key                  # TLS key
│   └── LICENSE                   # License
│
├── models/                       # AI MODELS (protected)
│   ├── scrfd/
│   │   └── scrfd_10g_bnkps.onnx
│   ├── arcface/
│   │   └── glintr100.onnx
│   ├── yolo/
│   │   ├── yolo11n.onnx
│   │   └── yolo11n-pose.pt
│   ├── reid/
│   │   └── resnet50_reid.onnx
│   ├── landmark/
│   │   └── 1k3d68.onnx
│   └── README.md
│
├── config/                       # SHARED CONFIGURATION
│   ├── default.yaml              # Pipeline defaults
│   ├── runtime-ports.json        # Port assignments
│   └── geometry/
│       ├── CAM1.json
│       ├── CAM2.json
│       └── submission_geometry.json
│
├── data/                         # PIPELINE-SPECIFIC DATA (not legacy attendance)
│   ├── attendance_events.db      # PipelineEngine event log (if needed)
│   └── attendance_daily.db       # PipelineEngine daily aggregates (if needed)
│   # NOTE: Legacy attendance.db stays in app/data/
│
├── recordings/                   # VIDEO RECORDINGS (empty target)
│
├── scripts/                      # ACTIVE OPERATIONAL SCRIPTS ONLY
│   ├── startup/
│   │   ├── start_mediamtx.ps1
│   │   ├── start_backend.ps1
│   │   ├── start_publishers.ps1
│   │   └── start_pipeline.ps1
│   ├── diagnostics/
│   │   ├── check_environment.py
│   │   ├── check_gpu.py
│   │   ├── check_models.py
│   │   └── check_streams.py
│   └── maintenance/
│       ├── cleanup_quarantine.py
│       └── rotate_logs.py
│
├── tests/                        # TEST SUITE
│   ├── unit/
│   ├── integration/
│   ├── live/
│   ├── forensics/
│   └── benchmark_results/        # Move from root benchmark_results/
│
├── docs/                         # DOCUMENTATION
│   ├── architecture/
│   │   ├── architecture_A.md
│   │   ├── data_ownership.md
│   │   └── integration_contracts.md
│   ├── operations/
│   │   ├── startup_shutdown.md
│   │   ├── media_mtx_config.md
│   │   └── camera_setup.md
│   └── development/
│       ├── adding_models.md
│       └── testing.md
│
├── new_engine/                   # NEW ARCHITECTURE WORK + AUDIT
│   └── audit/
│       ├── phase_0/
│       ├── phase_0_1/
│       └── phase_0_2/
│
├── tools/                        # UTILITY TOOLS
│   ├── create_arcface_npy.py
│   ├── render_submission.py
│   └── step14/
│
├── requirements/
│   ├── base.txt
│   └── windows.txt
│
├── bootstrap.py                  # Pipeline bootstrap (Python)
├── bootstrap.bat                 # Pipeline bootstrap (Windows)
├── Makefile
├── pytest.ini
├── .gitignore
└── README.md
```

---

## 3. Key Design Decisions

### 3.1 Legacy Backend Stays at `app/`
- **Reason:** 406 files, 6 MB, authoritative attendance owner
- **No move to `app/legacy/` or similar** — it IS the canonical backend
- Pipeline Engine integrates via HTTP client, not by merging code

### 3.2 Pipeline Engine Stays at `pipeline_engine/`
- **Reason:** 40 files, 0.8 MB, Architecture A target implementation
- **No merge with `app/`** — separate process, separate responsibility
- **No rename** — module name `pipeline_engine` used in imports

### 3.3 Duplicate Databases Resolved
| Database | Canonical Location | Action |
|----------|-------------------|--------|
| `attendance.db` | `app/data/` | **KEEP** — Legacy Backend authoritative |
| `exit_sessions.db` | `app/data/` | **KEEP** — Legacy Backend |
| `parent_registry.db` | `app/data/` | **KEEP** — Legacy Backend |
| `notification_queue.db` | `app/data/` | **KEEP** — Legacy Backend |
| `attendance_events.db` | `data/` | **KEEP** — PipelineEngine event log (if used) |
| `attendance_daily.db` | `data/` | **KEEP** — PipelineEngine daily agg (if used) |
| `data/attendance.db` (root) | — | **REMOVE** — Duplicate of `app/data/` |

### 3.4 Model Files — Subdirectories Only
- **Remove root duplicates:** `models/glintr100.onnx`, `models/1k3d68.onnx`, `models/resnet50_reid.onnx`, `yolo11n.pt` (root)
- **Keep subdirectory structure** — matches `pipeline_engine/config/pipeline.yaml` paths

### 3.5 Historical Scripts — Archive, Don't Delete
- Move `scripts/phase*.py`, `scripts/debug*.py`, `scripts/run_phase33*.py`, `scripts/fix*.py`, `scripts/generate*.py` → `scripts/archive/` or quarantine
- Keep only active operational scripts in `scripts/startup/`, `scripts/diagnostics/`, `scripts/maintenance/`

### 3.6 Video Pipeline v2 — Quarantine/Archive
- `video_pipeline_v2/` is superseded by Architecture A
- Contains reusable components (NVDEC, NVENC, tracking) but duplicates `pipeline_engine/` and `app/`
- **Action:** Move to `archive/video_pipeline_v2/` or quarantine for component extraction

### 3.7 Generated/Test Data — Quarantine
- `live/` (4.2 GB), `benchmark_results/` (750 MB), `artifacts/` (265 MB) → quarantine
- Root `*.mp4`, `*.h264` (1.6 GB) → quarantine
- `test_data/` — verify fixtures first, then quarantine fix/debug scripts

### 3.8 UI — Determine Status
- `UI/index.html` (113 KB) — single file, unclear if active
- **Action:** Verify if this is the current frontend or abandoned
- If active: move to `app/frontend/` or `frontend/` with proper structure
- If abandoned: quarantine

---

## 4. Import/Reference Impact Analysis

### 4.1 Imports That Must Not Break

**Legacy Backend (`app/`) internal imports:**
- `from app.api import ...`
- `from app.attendance import ...`
- `from app.config import ...`
- `from app.data import ...`
- `from app.runtime import ...`
- `from app.streaming import ...`
- `from app.vision import ...`

**Pipeline Engine (`pipeline_engine/`) imports:**
- `from pipeline_engine.config import load_pipeline_config`
- `from pipeline_engine.core.engine import PipelineEngine`
- `from pipeline_engine.inference import ...`
- `from pipeline_engine.integration import LegacyBackendClient`

**Bootstrap (`bootstrap.py`):**
- `from pipeline_engine.config import load_pipeline_config`
- `from pipeline_engine.core.engine import PipelineEngine`

**MediaMTX Config (`mediamtx.yml`):**
- References paths: `live/cam1`, `live/cam2`, `live/cam1-ai`, `live/cam2-ai`
- No file system paths outside `mediamtx/`

### 4.2 Configuration References

**`pipeline_engine/config/pipeline.yaml`:**
- Models: `models/scrfd/scrfd_10g_bnkps.onnx`, `models/arcface/glintr100.onnx`, `models/yolo/yolo11n.onnx`
- Data: `data/attendance_events.db`, `data/attendance_daily.db`
- Integration databases: `data/attendance.db` → should be `app/data/attendance.db`
- Output: MediaMTX `localhost:8554`, API `localhost:9997`

**`app/config/paths.py` (inferred):**
- Defines `data_dir`, `models_dir`, `logs_dir`, `recordings_dir`
- Used by `app/main.py` settings

**`config/default.yaml`:**
- Shared defaults for pipeline

---

## 5. Relocation Plan Summary

### 5.1 Files to MOVE (with destination)

| Source | Destination | Reason |
|--------|-------------|--------|
| `yolo11n.pt` (root) | `models/yolo/yolo11n.pt` (already exists) | Remove duplicate |
| `models/glintr100.onnx` (root) | QUARANTINE | Duplicate of `models/arcface/` |
| `models/1k3d68.onnx` (root) | QUARANTINE | Duplicate of `models/landmark/` |
| `models/resnet50_reid.onnx` (root) | QUARANTINE | Duplicate of `models/reid/` |
| `data/attendance.db` | QUARANTINE | Duplicate of `app/data/` |
| `data/exit_sessions.db` | QUARANTINE | Duplicate of `app/data/` |
| `data/parent_registry.db` | QUARANTINE | Duplicate of `app/data/` |
| `data/notification_queue.db` | QUARANTINE | Duplicate of `app/data/` |
| Root `*.mp4`, `*.h264` test videos | `quarantine/root_test_videos/` | Generated test data |
| `submission_*.mp4` | `quarantine/root_test_videos/` | Test outputs |
| `test_video*.mp4` | `quarantine/root_test_videos/` | Test videos |
| `encoder_output.h264`, `real_h264.h264`, `test_output*.h264`, `test.h264` | `quarantine/root_test_videos/` | Test artifacts |
| `live/` | `quarantine/generated_live/` | Generated test data (4.2 GB) |
| `benchmark_results/` (root) | `tests/benchmark_results/` | Move into test structure |
| `artifacts/` | `quarantine/generated_artifacts/` | Generated artifacts |
| `scripts/phase*.py`, `debug*.py`, `run_phase33*.py`, `fix*.py`, `generate*.py` | `quarantine/historical_scripts/` | Historical scripts |
| `video_pipeline_v2/` | `quarantine/video_pipeline_v2/` | Superseded pipeline |
| `build/`, `CMakeFiles/` | `quarantine/build_artifacts/` | Build artifacts |
| `logs/` | `quarantine/runtime_logs/` | Runtime logs |
| `phase7_runtime_diagnostic/` | `quarantine/empty_dirs/` | Empty |
| `New folder/` | `quarantine/empty_dirs/` | Empty |
| `.pytest_cache/` | `quarantine/build_artifacts/` | Test cache |

### 5.2 Files to KEEP in Place (No Changes)

All source code in:
- `app/` — Legacy Backend
- `pipeline_engine/` — New Pipeline Engine
- `mediamtx/` — MediaMTX runtime
- `models/` subdirectories — AI models
- `config/` — Configuration
- `app/data/` — Authoritative databases
- `tests/` — Test suite
- `docs/`, `reports/`, `new_engine/audit/` — Documentation
- `tools/` — Utility tools
- `requirements/` — Dependencies
- `bootstrap.py`, `bootstrap.bat` — Entrypoints
- `Makefile`, `pytest.ini`, `.gitignore` — Build/test config
- `nvcv_bridge.*` — CUDA bridge
- `recordings/` — Empty target
- `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/` — Vendor SDKs
- `.venv2/`, `.venv_38p_isolated/` — Python environments
- `.kilo/`, `.clinerules/`, `.vscode/` — Tooling config

### 5.3 Files Requiring Human Decision (REVIEW)

| Item | Decision Needed |
|------|-----------------|
| `UI/index.html` | Active frontend? Move to `app/frontend/` or quarantine? |
| `test_data/` | Unique test fixtures? Extract fixtures, quarantine rest |
| `isolated_src/`, `isolated_tests/` | Purpose? Keep or remove? |
| `patch_submit.py` | Active submission script? Keep in `tools/` or remove? |
| `data/attendance_events.db`, `attendance_daily.db` | Used by PipelineEngine? Keep in `data/` or move to `pipeline_engine/data/`? |

---

## 6. Validation Requirements After Relocation

1. **Bootstrap check:** `python bootstrap.py --check` passes
2. **Legacy Backend import:** `python -c "from app.main import create_app; print('OK')"` passes
3. **Pipeline Engine import:** `python -c "from pipeline_engine.core.engine import PipelineEngine; print('OK')"` passes
4. **Config load:** `python -c "from pipeline_engine.config import load_pipeline_config; c=load_pipeline_config(); print('OK')"` passes
5. **Model paths:** All model paths in `pipeline.yaml` resolve to existing files
6. **MediaMTX config:** `mediamtx.yml` unchanged, binary runs
7. **Database access:** `app/data/attendance.db` accessible
8. **Enrollment load:** `app/data/enrollment/embeddings.npy` loadable

---

## 7. Rollback Procedure

1. All moves go to `new_engine/audit/phase_0_2/quarantine/` with preserved structure
2. Each move logged with: source, destination, SHA256, timestamp, reason
3. Rollback: `Move-Item` from quarantine back to original path
4. Git can restore any tracked file modifications
5. `.venv2/`, `models/`, `mediamtx/`, `app/data/` never touched

---

## 8. Approval Required

Before executing cleanup:
- [ ] User approves canonical structure
- [ ] User approves quarantine list
- [ ] User confirms `UI/` status
- [ ] User confirms `test_data/` fixtures
- [ ] User confirms `data/attendance_events.db` usage

---

## 9. Next Steps

1. Present this structure for approval
2. Create detailed cleanup plan (`03_cleanup_and_relocation_plan.md`)
3. Execute quarantine moves
4. Run validation checks
5. Begin infrastructure bring-up (Stage D)