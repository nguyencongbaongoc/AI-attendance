# Phase 0.2 — Cleanup and Relocation Plan

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage C: Repository Cleanup and Relocation

---

## 1. Current Directory Tree (Pre-Cleanup)

```
AI_ATTENDANCE/
├── .venv2/                    # 5.9 GB - Active Python runtime (KEEP)
├── app/                       # 6 MB - Legacy Backend (KEEP - Authoritative)
├── artifacts/                 # 265 MB - Generated artifacts (QUARANTINE)
├── benchmark_results/         # 750 MB - Historical benchmarks (QUARANTINE)
├── build/                     # 1.3 MB - Build artifacts (QUARANTINE)
├── CMakeFiles/                # 9 MB - CMake build (QUARANTINE)
├── config/                    # <1 MB - Configuration (KEEP)
├── data/                      # 240 KB - Duplicate DBs (QUARANTINE duplicates)
├── docs/                      # <1 MB - Documentation (KEEP)
├── live/                      # 4.2 GB - Generated test video (QUARANTINE)
├── logs/                      # <1 MB - Runtime logs (QUARANTINE)
├── mediamtx/                  # 54 MB - MediaMTX runtime (KEEP)
├── models/                    # 988 MB - AI Models (KEEP - subdirs only)
├── New folder/                # 16 MB - Empty/temp (QUARANTINE)
├── new_engine/                # 340 KB - Audit + new arch (KEEP)
├── phase7_runtime_diagnostic/ # 0 MB - Empty (QUARANTINE)
├── pipeline_engine/           # 0.8 MB - New Pipeline Engine (KEEP)
├── recordings/                # 0 MB - Empty target (KEEP)
├── reports/                   # <1 MB - Phase reports (KEEP)
├── requirements/              # <1 MB - Requirements (KEEP)
├── scripts/                   # 2.4 MB - 100+ historical scripts (QUARANTINE most)
├── TensorRT-11.3.0.99/        # 2.3 GB - NVIDIA SDK (KEEP)
├── test_data/                 # 24 MB - Test fixtures + fix scripts (REVIEW)
├── tests/                     # 10 MB - Test suite (KEEP)
├── tools/                     # <1 MB - Utility tools (KEEP)
├── UI/                        # 113 KB - Single index.html (REVIEW)
├── Video_Codec_SDK_13.0.37/   # 3.5 MB - NVIDIA SDK (KEEP)
├── video_pipeline_v2/         # 0.5 MB - Historical v2 pipeline (QUARANTINE)
├── bootstrap.py               # 24 KB - Pipeline bootstrap (KEEP)
├── bootstrap.bat              # 2.5 KB - Windows launcher (KEEP)
├── encoder_output.h264        # 9 KB - Test artifact (QUARANTINE)
├── Makefile                   # 7 KB - Build rules (KEEP)
├── nvcv_bridge.*              # 200 KB - CUDA bridge (KEEP)
├── out.txt                    # 0 B - Empty (QUARANTINE)
├── patch_submit.py            # 6 KB - Submission script (QUARANTINE)
├── pytest.ini                 # 58 B - Pytest config (KEEP)
├── real_h264.h264             # 13 KB - Test artifact (QUARANTINE)
├── submission_*.mp4           # 1.8 GB - Test outputs (QUARANTINE)
├── test_*.mp4, *.h264         # 200 MB - Test videos (QUARANTINE)
├── test.h264                  # 33 B - Test artifact (QUARANTINE)
├── yolo11n.pt                 # 5.6 MB - Root duplicate (QUARANTINE)
└── .gitignore                 # 747 B - Git ignore (KEEP)
```

---

## 2. Proposed Directory Tree (Post-Cleanup)

```
AI_ATTENDANCE/
├── .venv2/                    # 5.9 GB - Active Python runtime
├── app/                       # 6 MB - Legacy Backend (Attendance Authority)
│   ├── main.py
│   ├── api/                   # 11 routers
│   ├── attendance/            # Policy engine, daily resolution, etc.
│   ├── bootstrap/             # MediaMTX readiness, port discovery
│   ├── config/                # Settings, paths
│   ├── data/                  # Authoritative DBs + Enrollment
│   │   ├── attendance.db
│   │   ├── exit_sessions.db
│   │   ├── parent_registry.db
│   │   ├── notification_queue.db
│   │   └── enrollment/
│   │       ├── embeddings.npy
│   │       └── embeddings.npy.metadata.json
│   ├── geometry/              # Crossing geometry
│   ├── in_out/                # Raw events, resolvers
│   ├── logging/               # Structured logging
│   ├── models/                # Pydantic contracts
│   ├── operational/           # CLI tools
│   ├── output/                # Adapters, publishers
│   ├── replay/                # Annotated replay
│   ├── runtime/               # CUDA, GPU abstractions
│   ├── streaming/             # 20+ streaming modules
│   ├── video/                 # PyNvCodec
│   └── vision/                # 30+ vision modules
├── pipeline_engine/           # 0.8 MB - Architecture A AI Worker
│   ├── config/                # pipeline.yaml
│   ├── core/                  # PipelineEngine
│   ├── ingestion/             # RTMP source
│   ├── decode/                # PyAV NVDEC
│   ├── encode/                # PyAV NVENC
│   ├── inference/             # SCRFD, ArcFace, YOLO
│   ├── tracking/              # Tracker, association
│   ├── integration/           # Legacy backend adapter
│   ├── monitoring/            # Health, metrics
│   ├── output/                # Publisher
│   ├── runtime/               # Runtime management
│   ├── attendance/            # Attendance adapter (NOT authority)
│   ├── backend/               # Legacy backend adapter
│   ├── memory/                # Frame pool, GPU memory
│   └── annotation/            # Overlay rendering
├── mediamtx/                  # 54 MB - MediaMTX Runtime
│   ├── mediamtx.exe
│   ├── mediamtx.yml
│   ├── auto.crt
│   ├── auto.key
│   └── LICENSE
├── models/                    # 988 MB - AI Models
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
├── config/                    # <1 MB - Shared Configuration
│   ├── default.yaml
│   ├── runtime-ports.json
│   └── geometry/
│       ├── CAM1.json
│       ├── CAM2.json
│       └── submission_geometry.json
├── data/                      # <1 MB - Pipeline-specific data
│   ├── attendance_events.db   # (if needed by PipelineEngine)
│   └── attendance_daily.db    # (if needed by PipelineEngine)
├── recordings/                # 0 MB - Video recordings target
├── scripts/                   # <1 MB - Active operational scripts only
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
├── tests/                     # 10 MB - Test Suite
│   ├── unit/
│   ├── integration/
│   ├── live/
│   ├── forensics/
│   └── benchmark_results/     # Moved from root
├── docs/                      # <1 MB - Documentation
│   ├── architecture/
│   ├── operations/
│   └── development/
├── new_engine/                # 340 KB - New Architecture Work + Audit
│   └── audit/
│       ├── phase_0/
│       ├── phase_0_1/
│       └── phase_0_2/
├── tools/                     # <1 MB - Utility Tools
│   ├── create_arcface_npy.py
│   ├── render_submission.py
│   └── step14/
├── requirements/              # <1 MB - Dependencies
│   ├── base.txt
│   └── windows.txt
├── bootstrap.py               # 24 KB - Pipeline bootstrap
├── bootstrap.bat              # 2.5 KB - Windows launcher
├── Makefile                   # 7 KB - Build rules
├── pytest.ini                 # 58 B - Pytest config
├── .gitignore                 # 747 B - Git ignore
├── nvcv_bridge.*              # 200 KB - CUDA bridge libs
├── TensorRT-11.3.0.99/        # 2.3 GB - NVIDIA SDK
├── Video_Codec_SDK_13.0.37/   # 3.5 MB - NVIDIA SDK
└── .venv_38p_isolated/        # 11 MB - Isolated venv
```

---

## 3. Files Classification Summary

### 3.1 KEEP (No Changes)
- `.venv2/`, `.venv_38p_isolated/` — Python environments
- `app/` — Legacy Backend (authoritative)
- `pipeline_engine/` — New Pipeline Engine
- `mediamtx/` — MediaMTX runtime
- `models/` subdirectories — AI models
- `config/` — Configuration
- `app/data/` — Authoritative databases + enrollment
- `tests/` — Test suite
- `docs/`, `reports/`, `new_engine/audit/` — Documentation
- `tools/`, `requirements/` — Tooling
- `bootstrap.py`, `bootstrap.bat` — Entrypoints
- `Makefile`, `pytest.ini`, `.gitignore` — Build/test config
- `nvcv_bridge.*` — CUDA bridge
- `recordings/` — Empty target
- `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/` — Vendor SDKs
- `.kilo/`, `.clinerules/`, `.vscode/` — Tooling config

### 3.2 MOVE (Wrong Location → Correct Location)
| Source | Destination | Reason |
|--------|-------------|--------|
| `yolo11n.pt` (root) | Already in `models/yolo/` | Remove duplicate |
| `models/glintr100.onnx` (root) | → Quarantine | Duplicate of `models/arcface/` |
| `models/1k3d68.onnx` (root) | → Quarantine | Duplicate of `models/landmark/` |
| `models/resnet50_reid.onnx` (root) | → Quarantine | Duplicate of `models/reid/` |
| `benchmark_results/` (root) | `tests/benchmark_results/` | Part of test structure |

### 3.3 QUARANTINE (Safe to Remove After Verification)
| Source | Quarantine Location | Size | Reason |
|--------|---------------------|------|--------|
| Root test videos (18 files) | `quarantine/root_test_videos/` | 1.6 GB | Generated test data |
| Root model duplicates (3 files) | `quarantine/root_model_duplicates/` | 350 MB | Duplicates in subdirs |
| Duplicate DBs (4 files) | `quarantine/data_duplicate_dbs/` | <1 MB | Duplicates of `app/data/` |
| Historical scripts (80+) | `quarantine/historical_scripts/` | 2 MB | Superseded phase scripts |
| Generated artifacts | `quarantine/generated_artifacts/` | 1 GB | `artifacts/`, `benchmark_results/`, `out.txt` |
| Build artifacts | `quarantine/build_artifacts/` | 10 MB | `build/`, `CMakeFiles/`, `.pytest_cache/` |
| Runtime logs | `quarantine/runtime_logs/` | <1 MB | `logs/` |
| Empty directories | `quarantine/empty_dirs/` | 0 | `phase7_runtime_diagnostic/`, `New folder/` |
| Generated live data | `quarantine/generated_live/` | 4.2 GB | `live/` |
| Video pipeline v2 | `quarantine/video_pipeline_v2/` | 0.5 MB | Superseded pipeline |
| `patch_submit.py` | `quarantine/historical_scripts/` | 6 KB | Unknown purpose |

### 3.4 REVIEW (Human Decision Needed)
| Item | Decision Needed |
|------|-----------------|
| `UI/index.html` | Active frontend? Move to `app/frontend/` or quarantine? |
| `test_data/` | Unique test fixtures? Extract fixtures, quarantine rest |
| `isolated_src/`, `isolated_tests/` | Purpose? Keep or remove? |
| `data/attendance_events.db`, `attendance_daily.db` | Used by PipelineEngine? Keep in `data/` or move? |

---

## 4. Dependency/Impact Analysis

### 4.1 Imports Verified Safe
- `bootstrap.py` → imports `pipeline_engine.config`, `pipeline_engine.core.engine` ✅
- `app/main.py` → imports `app.api.*`, `app.config.settings`, `app.bootstrap.*` ✅
- `pipeline_engine.config.pipeline.yaml` → references `models/scrfd/...`, `models/arcface/...`, `models/yolo/...` ✅
- `mediamtx/mediamtx.yml` → no external file refs ✅

### 4.2 Configuration References Verified
- `pipeline_engine/config/pipeline.yaml`:
  - Model paths: `models/scrfd/...`, `models/arcface/...`, `models/yolo/...` ✅
  - Data paths: `data/attendance_events.db`, `data/attendance_daily.db` ⚠️ (PipelineEngine specific)
  - Integration DBs: `data/attendance.db` → should be `app/data/attendance.db` (Phase 1 fix)
- `app/config/settings.py`:
  - `data_dir: Path.cwd() / "data"` → points to root `data/` (has restored DBs) ✅
  - `models_dir: Path.cwd() / "models"` ✅

---

## 5. Rollback Plan

### 5.1 Quarantine-Based Rollback
All moves to `new_engine/audit/phase_0_2/quarantine/` with preserved structure:
```
quarantine/
├── root_test_videos/          # 18 files
├── root_model_duplicates/     # 3 files
├── data_duplicate_dbs/        # 4 files (restored for backend)
├── historical_scripts/        # 80+ files
├── generated_artifacts/       # artifacts/, benchmark_results/, out.txt
├── build_artifacts/           # build/, CMakeFiles/, .pytest_cache/
├── runtime_logs/              # logs/
├── empty_dirs/                # phase7_runtime_diagnostic/, New folder/
├── generated_live/            # live/ (4.2 GB)
└── video_pipeline_v2/         # superseded pipeline
```

**Rollback command example:**
```powershell
# Restore single file
Move-Item quarantine/root_test_videos/yolo11n.pt models/yolo/yolo11n.pt

# Restore directory
Move-Item quarantine/video_pipeline_v2 video_pipeline_v2

# Restore scripts
Move-Item quarantine/historical_scripts/phase33_live_health_failover.py scripts/
```

### 5.2 Git-Based Rollback
- `git status` shows current state
- `git checkout -- <file>` restores tracked files
- `git restore figma/ frontend/` restores deleted directories from history

### 5.3 Environment Rollback
- `.venv2/` never modified
- If packages changed: `pip install -r requirements/base.txt -r requirements/windows.txt`
- MediaMTX config never modified
- Model files never modified

---

## 6. Expected Effects on Runtime Commands

| Command | Before | After | Status |
|---------|--------|-------|--------|
| `python bootstrap.py --check` | Works | Works | ✅ Verified |
| `python -c "from app.main import create_app"` | Works | Works | ✅ Verified |
| `python -c "from pipeline_engine.core.engine import PipelineEngine"` | Works | Works | ✅ Verified |
| `cd mediamtx && .\mediamtx.exe .\mediamtx.yml` | Works | Works | ✅ Verified |
| `curl http://localhost:9997/v3/paths/list` | Works | Works | ✅ Verified |
| RTSP decode test | Works | Works | ✅ Verified |

---

## 7. Execution Log (Completed)

| Step | Action | Result |
|------|--------|--------|
| 1 | Create quarantine directory structure | ✅ Done |
| 2 | Move root test videos (18 files) | ✅ Done |
| 3 | Move root model duplicates (3 files) | ✅ Done |
| 4 | Move duplicate DBs (4 files) | ✅ Done |
| 5 | Move historical scripts (80+ files) | ✅ Done |
| 6 | Move generated artifacts | ✅ Done |
| 7 | Move build artifacts | ✅ Done |
| 8 | Move runtime logs | ✅ Done |
| 9 | Move empty directories | ✅ Done |
| 10 | Move generated live data | ✅ Done |
| 11 | Move video_pipeline_v2 | ✅ Done |
| 12 | Restore DBs to `data/` for backend | ✅ Done |
| 13 | Verify bootstrap.py --check | ✅ PASS |
| 14 | Verify Legacy Backend import | ✅ PASS |
| 15 | Verify Pipeline Engine import | ✅ PASS |
| 16 | Verify config load | ✅ PASS |
| 17 | Start MediaMTX | ✅ PASS |
| 18 | Start Legacy Backend | ✅ PASS |
| 19 | Verify camera streams | ✅ PASS |
| 20 | Verify dual-camera decode | ✅ PASS |
| 21 | Verify AI model sessions | ✅ PASS |
| 22 | Verify enrollment data | ✅ PASS |

---

## 8. Approval

**Cleanup plan executed successfully. All verification tests pass. Ready for Phase 1.**