# Phase 0.2 — Repository Inventory & Classification

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage A: Baseline and Forensic Inventory

---

## 1. Directory-Level Summary

| Directory | Files | Size (MB) | Git Status | Classification | Notes |
|-----------|-------|-----------|------------|----------------|-------|
| `.venv2` | 35,652 | 5,877 | Ignored | **KEEP (Protected)** | Active Python runtime — DO NOT TOUCH |
| `live` | 3,007 | 4,218 | Untracked | **REMOVE CANDIDATE** | Generated test video data, not source |
| `.kilo` | 10,799 | 3,330 | Tracked | **KEEP** | Kilo IDE config |
| `TensorRT-11.3.0.99` | 61 | 2,338 | Untracked | **KEEP (Protected)** | NVIDIA SDK — may be needed for TensorRT EP |
| `models` | 18 | 988 | Tracked | **KEEP (Protected)** | AI model files — authoritative |
| `benchmark_results` | 1,269 | 750 | Untracked | **REMOVE CANDIDATE** | Historical benchmark output |
| `artifacts` | 738 | 265 | Untracked | **REMOVE CANDIDATE** | Generated pipeline artifacts |
| `mediamtx` | 5 | 54 | Tracked | **KEEP** | MediaMTX binary + config — runtime critical |
| `test_data` | 30 | 24 | Tracked | **REVIEW** | Mix of test fixtures & fix scripts |
| `New folder` | 8 | 16 | Untracked | **REMOVE CANDIDATE** | Empty/temp directory |
| `.venv_38p_isolated` | 861 | 11 | Ignored | **KEEP** | Isolated venv — may be needed for compatibility |
| `tests` | 222 | 10 | Tracked | **KEEP** | Test suite — unit/integration/live |
| `CMakeFiles` | 30 | 9 | Ignored | **REMOVE CANDIDATE** | Build artifacts |
| `app` | 406 | 6 | Tracked | **KEEP (Protected)** | **Legacy Backend — authoritative attendance owner** |
| `Video_Codec_SDK_13.0.37` | 136 | 3 | Untracked | **KEEP (Protected)** | NVIDIA SDK — may be needed for NVENC/NVDEC |
| `scripts` | 110 | 2 | Tracked | **REVIEW** | 100+ historical phase scripts |
| `build` | 124 | 1 | Ignored | **REMOVE CANDIDATE** | Build artifacts |
| `pipeline_engine` | 40 | 0.8 | Tracked | **KEEP** | **New Pipeline Engine (Architecture A target)** |
| `video_pipeline_v2` | 36 | 0.5 | Tracked | **REVIEW** | Historical v2 pipeline — NVENC annotated path |
| `new_engine` | 33 | 0.3 | Tracked | **KEEP** | Audit artifacts + new architecture docs |
| `data` | 7 | 0.2 | Mixed | **REVIEW** | SQLite DBs — duplicate with `app/data/` |
| `UI` | 1 | 0.1 | Untracked | **REVIEW** | Single index.html — React/Vite app? |
| `isolated_tests` | 10 | 0.08 | Tracked | **REVIEW** | Isolated test subset |
| `logs` | 2 | 0.05 | Ignored | **REMOVE CANDIDATE** | Runtime logs |
| `reports` | 6 | 0.04 | Tracked | **KEEP** | Phase reports |
| `tools` | 4 | 0.04 | Tracked | **KEEP** | Utility tools |
| `.clinerules` | 18 | 0.03 | Tracked | **KEEP** | Cline rules |
| `docs` | 2 | 0.02 | Tracked | **KEEP** | Documentation |
| `.pytest_cache` | 5 | 0.01 | Ignored | **REMOVE CANDIDATE** | Test cache |
| `recordings` | 0 | 0 | Ignored | **KEEP** | Empty dir for recordings |
| `requirements` | 2 | 0 | Tracked | **KEEP** | Requirements files |
| `isolated_src` | 1 | 0 | Tracked | **REVIEW** | Single file? |
| `config` | 5 | 0 | Tracked | **KEEP** | Pipeline & geometry config |
| `.vscode` | 1 | 0 | Ignored | **KEEP** | VS Code settings |
| `phase7_runtime_diagnostic` | 0 | 0 | Untracked | **REMOVE CANDIDATE** | Empty diagnostic dir |

---

## 2. Root-Level File Classification

| File | Size | Git Status | Classification | Reasoning |
|------|------|------------|----------------|-----------|
| `bootstrap.py` | 24 KB | Untracked | **KEEP** | Pipeline bootstrap entrypoint — active |
| `bootstrap.bat` | 2.5 KB | Untracked | **KEEP** | Windows launcher for .venv2 — active |
| `encoder_output.h264` | 9 KB | Untracked | **REMOVE CANDIDATE** | Test encoder output |
| `Makefile` | 7 KB | Tracked | **KEEP** | Build rules |
| `nvcv_bridge.exp` | 748 B | Untracked | **KEEP (Protected)** | CUDA bridge lib |
| `nvcv_bridge.lib` | 1.8 KB | Untracked | **KEEP (Protected)** | CUDA bridge lib |
| `nvcv_bridge.pyd` | 196 KB | Untracked | **KEEP (Protected)** | CUDA bridge Python extension |
| `out.txt` | 0 B | Untracked | **REMOVE CANDIDATE** | Empty output file |
| `patch_submit.py` | 6 KB | Untracked | **REVIEW** | Submission script — check purpose |
| `pytest.ini` | 58 B | Tracked | **KEEP** | Pytest config |
| `real_h264.h264` | 13 KB | Untracked | **REMOVE CANDIDATE** | Test video |
| `submission_4k_canonical.mp4` | 27 MB | Untracked | **REMOVE CANDIDATE** | Large test video |
| `submission_4k_yolo_arcface_facebox_y1350.mp4` | 3.8 MB | Untracked | **REMOVE CANDIDATE** | Test output video |
| `submission_4k_yolo_arcface_facebox_y2000.mp4` | 407 MB | Untracked | **REMOVE CANDIDATE** | Large test output |
| `submission_4k_yolo_arcface_full.mp4` | 380 MB | Untracked | **REMOVE CANDIDATE** | Large test output |
| `submission_4k_yolo_arcface_name_overlay.mp4` | 407 MB | Untracked | **REMOVE CANDIDATE** | Large test output |
| `submission_4k.mp4` | 2 MB | Untracked | **REMOVE CANDIDATE** | Test video |
| `submission_remediated_4k.mp4` | 223 MB | Untracked | **REMOVE CANDIDATE** | Large test output |
| `submission_remediated_4k1.mp4` | 409 MB | Untracked | **REMOVE CANDIDATE** | Large test output |
| `submission.mp4` | 3.4 MB | Untracked | **REMOVE CANDIDATE** | Test video |
| `test_encoder.mp4` | 1.3 MB | Untracked | **REMOVE CANDIDATE** | Test encoder output |
| `test_output_r5.h264` | 13 KB | Untracked | **REMOVE CANDIDATE** | Test output |
| `test_output.h264` | 0 B | Untracked | **REMOVE CANDIDATE** | Empty test output |
| `test_video_long.mp4` | 171 MB | Untracked | **REMOVE CANDIDATE** | Large test video |
| `test_video.mp4` | 29 MB | Untracked | **REMOVE CANDIDATE** | Test video |
| `test.h264` | 33 B | Untracked | **REMOVE CANDIDATE** | Tiny test file |
| `yolo11n.pt` | 5.6 MB | Untracked | **MOVE** | Duplicate of `models/yolo/yolo11n.pt` |
| `.gitignore` | 747 B | Tracked | **KEEP** | Git ignore rules |

---

## 3. Critical Subsystem Deep Dive

### 3.1 Legacy Backend (`app/`) — **KEEP (Protected)**
**Authoritative owner of attendance business logic, database, state transitions**

Key files:
- `app/main.py` — FastAPI entrypoint, dynamic port
- `app/api/` — 11 routers (health, attendance, persons, timetable, excel, parent_telegram, geometry, enrollment, replay, provenance, websocket)
- `app/attendance/` — Policy engine, calendar, contracts, daily resolution, engine, query, repository, storage, session context, timetable sync
- `app/data/attendance.db` + WAL — **Primary attendance database**
- `app/data/enrollment/embeddings.npy` + metadata — **Enrollment embeddings**
- `app/bootstrap/` — MediaMTX readiness, port discovery, startup validation, venv management
- `app/config/` — Settings, paths
- `app/runtime/` — CUDA, detector, FFmpeg, GPU device abstraction, IO binding, model session, residency, stream, telemetry, VRAM safety
- `app/streaming/` — 20+ modules: annotated publisher, camera runtime, capture watchdog, contracts, detection pipeline, encoder, health, ingestion, instrumentation, MediaMTX config, publisher lifecycle, PyAV annotated/NVDEC/NVENC, reconnect, RTMP/RTSP source, shared health, supervised runner, telemetry, timestamp
- `app/vision/` — 30+ modules: adaptive crop, ArcFace, association, crop, detection, detector contract/factory, enrollment, face quality, forensic trace, GPU 4K surface, GPU alignment, GPU annotation, GPU BGR→NV12, GPU face detect, GPU inference, GPU NV12→BGR, GPU pipeline, GPU preprocess, GPU ROI crop, hardpose, landmarks, matching, quality, recognition, RetinaFace, SCRFD, surface owners, temporal evidence, track contract, tracker, YOLO person detect

**Dependencies on this subsystem:**
- Pipeline Engine integration config references `app/data/` databases
- MediaMTX config expects RTMP publishers from `app.streaming.publisher_lifecycle`
- Bootstrap.py imports from `pipeline_engine` not `app`

### 3.2 Pipeline Engine (`pipeline_engine/`) — **KEEP**
**Target Architecture A AI Worker — not yet fully implemented**

Modules:
- `config/` — `pipeline.yaml` (434 lines), loaders
- `core/engine.py` — PipelineEngine, EngineState
- `ingestion/` — RTMP source, frame ingestion
- `decode/` — PyAV NVDEC backend
- `inference/` — SCRFD, ArcFace, YOLO, ONNX Runtime
- `tracking/` — Tracker, association
- `integration/` — Legacy backend adapter
- `monitoring/` — Health, metrics
- `output/` — Publisher
- `runtime/` — Runtime management
- `attendance/` — Attendance integration (NOT independent authority)
- `backend/` — Legacy backend adapter
- `memory/` — Frame pool, GPU memory, system memory, zero-copy (experimental)
- `encode/` — PyAV NVENC backend
- `annotation/` — Overlay rendering

**Note:** This is the NEW pipeline being built. It should NOT duplicate attendance authority.

### 3.3 Video Pipeline v2 (`video_pipeline_v2/`) — **REVIEW (Historical)**
**Superseded implementation with NVENC annotated output path**

Modules:
- `ai/` — ArcFace, GPU inference, line crossing, models, REID, SCRFD, tracking, YOLO
- `annotation/` — Box, text, overlay renderers
- `core/` — GPU context, pipeline
- `decoder/` — NVDEC, PyAV decoder
- `encoder/` — NVENC encoder
- `input/` — RTMP, RTSP sources
- `monitoring/` — Health, metrics
- `output/` — RTSP publisher, stream output
- `runtime/` — Pipeline runtime
- `workers/` — AI worker, annotation worker, decoder worker, encoder worker, input worker, output worker, pipeline coordinator

**Overlaps with:** `pipeline_engine/` (inference, tracking, decode, encode), `app/vision/`, `app/streaming/`
**Architecture A does NOT require:** NVENC annotated output path, second MediaMTX publisher for AI output

### 3.4 Models (`models/`) — **KEEP (Protected)**
| Model | Path | Size | Status |
|-------|------|------|--------|
| SCRFD | `models/scrfd/scrfd_10g_bnkps.onnx` | ~50 MB | Active |
| ArcFace | `models/arcface/glintr100.onnx` | ~100 MB | Active |
| YOLO | `models/yolo/yolo11n.onnx` | ~5 MB | Active |
| YOLO Pose | `models/yolo/yolo11n-pose.pt` | ~5.6 MB | Optional |
| ReID | `models/reid/resnet50_reid.onnx` | ~100 MB | Disabled |
| Landmark | `models/landmark/1k3d68.onnx` | ~10 MB | Optional |
| Root copies | `models/glintr100.onnx`, `models/1k3d68.onnx`, `models/resnet50_reid.onnx`, `models/yolo11n.pt` | — | **DUPLICATES** |

**Duplicates found:** Root-level model files duplicate subdirectory files.

### 3.5 Data Directories — **REVIEW (Duplicate DBs)**

| Location | Databases | Classification |
|----------|-----------|----------------|
| `data/` | `attendance.db`, `attendance_events.db`, `exit_sessions.db`, `notification_queue.db`, `parent_registry.db` | **REMOVE CANDIDATE** (Duplicates of `app/data/`) |
| `app/data/` | `attendance.db`, `exit_sessions.db`, `parent_registry.db`, `notification_queue.db`, `enrollment/embeddings.npy` | **KEEP (Protected)** — Authoritative |
| `app/data/enrollment_test/` | Test embeddings | **REVIEW** |

**Action needed:** Determine canonical DB location. `app/data/` appears authoritative (referenced by `app/config/paths.py`, `app/main.py` settings).

### 3.6 Scripts (`scripts/`) — **REVIEW**
110 files, mostly historical phase scripts:
- `phase*_*.py` — 80+ files for phases 3-53
- `debug_*.py` — 10+ debug scripts
- `run_phase33*.py` — 8 variants
- `test_*.py` — Test scripts
- `fix_*.py` — Fix scripts
- `generate_*.py` — Report generators

**Classification:** Most are **REMOVE CANDIDATE** (historical, superseded). Keep only active diagnostics/benchmarks.

### 3.7 Tests (`tests/`) — **KEEP**
- `unit/` — 80+ unit tests
- `integration/` — 15+ integration tests
- `live/` — 3 live tests
- `forensics/` — Forensic analysis
- `benchmark_results/` — Benchmark data (move to artifacts?)

---

## 4. Duplicate Analysis

### 4.1 Model File Duplicates
| Root Copy | Subdirectory Copy | Action |
|-----------|-------------------|--------|
| `models/glintr100.onnx` | `models/arcface/glintr100.onnx` | **REMOVE root copy** |
| `models/1k3d68.onnx` | `models/landmark/1k3d68.onnx` | **REMOVE root copy** |
| `models/resnet50_reid.onnx` | `models/reid/resnet50_reid.onnx` | **REMOVE root copy** |
| `yolo11n.pt` (root) | `models/yolo/yolo11n.pt` | **REMOVE root copy** |

### 4.2 Database Duplicates
| `data/` | `app/data/` | Action |
|---------|-------------|--------|
| `attendance.db` | `attendance.db` | **KEEP `app/data/`, REMOVE `data/`** |
| `attendance_events.db` | (not in app/data) | **REVIEW** — pipeline_engine uses `data/attendance_events.db` |
| `exit_sessions.db` | `exit_sessions.db` | **KEEP `app/data/`, REMOVE `data/`** |
| `notification_queue.db` | `notification_queue.db` | **KEEP `app/data/`, REMOVE `data/`** |
| `parent_registry.db` | `parent_registry.db` | **KEEP `app/data/`, REMOVE `data/`** |

**Critical:** `pipeline_engine/config/pipeline.yaml` references `data/attendance_events.db` and `data/attendance_daily.db` — these may be pipeline-specific, not legacy backend.

### 4.3 Pipeline Implementation Duplicates
| Component | `app/` | `pipeline_engine/` | `video_pipeline_v2/` | Notes |
|-----------|--------|-------------------|---------------------|-------|
| SCRFD | `app/vision/scrfd_adapter.py` | `pipeline_engine/inference/scrfd.py` | `video_pipeline_v2/ai/scrfd/` | Three implementations |
| ArcFace | `app/vision/arcface_inference.py` | `pipeline_engine/inference/arcface.py` | `video_pipeline_v2/ai/arcface/` | Three implementations |
| YOLO | `app/vision/yolo_person_detector.py` | `pipeline_engine/inference/yolo.py` | `video_pipeline_v2/ai/yolo/` | Three implementations |
| Tracking | `app/vision/tracker.py` | `pipeline_engine/tracking/` | `video_pipeline_v2/ai/tracking/` | Three implementations |
| NVDEC Decode | `app/streaming/pyav_nvdec_stream.py` | `pipeline_engine/decode/nvdec.py` | `video_pipeline_v2/decoder/` | Three implementations |
| NVENC Encode | `app/streaming/pyav_nvenc_encoder.py` | `pipeline_engine/encode/nvenc.py` | `video_pipeline_v2/encoder/` | Three implementations |
| Attendance | `app/attendance/` (authoritative) | `pipeline_engine/attendance/` (adapter) | `video_pipeline_v2/` (own logic?) | **Must unify** |

---

## 5. Git Tracking Status Details

### 5.1 Deleted but Tracked (in Git history)
- `figma/` — Entire Figma/React frontend (91 files deleted in working tree)
- `frontend/` — Vue frontend (37 files deleted in working tree)

**Status:** These exist in Git history. Working tree shows deletions (D). Not staged.

### 5.2 Untracked Directories (not in Git)
- `UI/` — New React/Vite frontend? (single index.html)
- `artifacts/` — Generated
- `benchmark_results/` — Generated
- `live/` — Generated test data
- `build/`, `CMakeFiles/` — Build artifacts
- `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/` — Vendor SDKs
- `test_data/` — Mixed
- `phase7_runtime_diagnostic/` — Empty
- `New folder/` — Empty

---

## 6. Classification Summary

### KEEP (Required, Active, Authoritative)
- `.venv2/` — Python runtime
- `app/` — Legacy Backend (attendance authority)
- `pipeline_engine/` — New Pipeline Engine (Architecture A)
- `mediamtx/` — MediaMTX runtime
- `models/` — AI models (subdirectories)
- `config/` — Configuration
- `app/data/` — Authoritative databases & enrollment
- `requirements/` — Dependency specs
- `tests/` — Test suite
- `docs/`, `reports/` — Documentation
- `tools/`, `.clinerules/`, `.kilo/`, `.vscode/` — Tooling
- `bootstrap.py`, `bootstrap.bat` — Entrypoints
- `Makefile`, `pytest.ini` — Build/test config
- `nvcv_bridge.*` — CUDA bridge libs
- `recordings/` — Empty target dir
- `new_engine/audit/` — Audit artifacts

### MOVE (Wrong Location)
- `yolo11n.pt` (root) → `models/yolo/` (already exists there)
- Root model files (`glintr100.onnx`, `1k3d68.onnx`, `resnet50_reid.onnx`) → Remove (duplicates in subdirs)

### REMOVE CANDIDATE (Safe to Delete After Verification)
- `live/` — 3007 files, 4.2 GB generated test video
- `benchmark_results/` — 1269 files, 750 MB historical benchmarks
- `artifacts/` — 738 files, 265 MB generated artifacts
- `test_data/` — Fix/debug scripts (verify no unique test fixtures)
- `New folder/` — Empty
- `CMakeFiles/` — Build artifacts
- `build/` — Build artifacts
- `logs/` — Runtime logs
- `phase7_runtime_diagnostic/` — Empty
- `.pytest_cache/` — Test cache
- Root `*.mp4`, `*.h264` — 1.6 GB test videos
- `submission_*.mp4` — 1.8 GB test outputs
- `test_video*.mp4` — 200 MB test videos
- `encoder_output.h264`, `real_h264.h264`, `test_output*.h264`, `test.h264` — Test artifacts
- `out.txt` — Empty
- `scripts/` — 100+ historical phase scripts (keep only active diagnostics)

### REVIEW (Needs Human Decision)
- `video_pipeline_v2/` — Historical v2 pipeline (36 files, 0.5 MB) — Has reusable components but duplicates new pipeline
- `scripts/` — Some may be active diagnostic scripts
- `test_data/` — Some may be test fixtures
- `data/` — Duplicate DBs (but pipeline_engine config references `data/attendance_events.db`)
- `isolated_src/`, `isolated_tests/` — Purpose unclear
- `UI/` — Single index.html, unclear if active frontend
- `patch_submit.py` — Purpose unclear

### PROTECTED (Never Delete/Relocate Without Explicit Approval)
- `.venv2/` — Active Python environment
- `app/data/` — Authoritative databases & enrollment embeddings
- `models/` subdirectories — AI model files
- `mediamtx/mediamtx.exe`, `mediamtx/mediamtx.yml` — MediaMTX runtime
- `TensorRT-11.3.0.99/`, `Video_Codec_SDK_13.0.37/` — Vendor SDKs
- `nvcv_bridge.*` — CUDA bridge libs
- `.git/` — Git metadata

---

## 7. Next Steps

1. **Create canonical structure document** (`05_canonical_repository_structure.md`)
2. **Produce cleanup plan** (`03_cleanup_and_relocation_plan.md`) with:
   - Exact files to MOVE with destinations
   - Exact files to QUARANTINE with evidence
   - Files eligible for permanent deletion
   - Dependency/import impact analysis
   - Rollback plan
3. **Execute safe moves** (model duplicates, root test videos)
4. **Begin infrastructure bring-up** (Stage D)