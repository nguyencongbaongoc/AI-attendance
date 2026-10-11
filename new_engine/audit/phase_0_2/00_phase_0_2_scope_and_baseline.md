# Phase 0.2 — Scope and Baseline

**Date:** 2026-10-04  
**Phase:** 0.2 — Infrastructure Bring-Up, Runtime Baseline & Repository Cleanup  
**Repository:** AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE  
**Git Commit:** 5269777 (HEAD)  
**Branch:** main (assumed)

---

## 1. Phase 0.2 Objectives

Per approved mandate:

1. **Bring up and verify actual infrastructure** — MediaMTX, Legacy Backend, Camera Publishers, Python GPU Runtime
2. **Establish reproducible runtime baseline** — Environment, performance, streams, enrollment data
3. **Clean up and reorganize repository** — Remove/relocate only proven unnecessary components

**Non-Objectives (DO NOT DO):**
- Implement Architecture A AI worker
- Add new backend APIs
- Implement UI overlay
- Change attendance business logic
- Introduce batch inference
- Modify model files
- Change database schemas
- Begin Phase 1

---

## 2. Repository Root Inventory (Baseline)

| Path | Type | Git Status | Size | Notes |
|------|------|------------|------|-------|
| `.clinerules/` | Dir | Tracked | - | Kilo config |
| `.kilo/` | Dir | Tracked | - | Kilo config |
| `.pytest_cache/` | Dir | Ignored | - | Test cache |
| `.venv_38p_isolated/` | Dir | Ignored | - | Isolated venv |
| `.venv2/` | Dir | Ignored | - | **Active Python env (3.12.10, CUDA 12.6, PyTorch 2.13.0, ONNX 1.28.0)** |
| `.vscode/` | Dir | Ignored | - | VS Code settings |
| `app/` | Dir | Tracked | - | **Legacy Backend (FastAPI, SQLite, attendance logic)** |
| `artifacts/` | Dir | Untracked | - | Generated artifacts |
| `benchmark_results/` | Dir | Untracked | - | Benchmark output |
| `build/` | Dir | Ignored | - | Build artifacts |
| `CMakeFiles/` | Dir | Ignored | - | CMake build |
| `config/` | Dir | Tracked | - | Pipeline & geometry config |
| `data/` | Dir | Mixed | - | **SQLite DBs, exports, temp** |
| `docs/` | Dir | Tracked | - | Documentation |
| `isolated_src/` | Dir | Tracked | - | Isolated source |
| `isolated_tests/` | Dir | Tracked | - | Isolated tests |
| `live/` | Dir | Untracked | - | Live test data |
| `logs/` | Dir | Ignored | - | Runtime logs |
| `mediamtx/` | Dir | Tracked | - | **MediaMTX binary + config** |
| `models/` | Dir | Tracked | - | **AI Models (ONNX, PT)** |
| `New folder/` | Dir | Untracked | - | Empty/temp |
| `new_engine/` | Dir | Tracked | - | Audit & new architecture |
| `phase7_runtime_diagnostic/` | Dir | Untracked | - | Diagnostic output |
| `pipeline_engine/` | Dir | Tracked | - | **New Pipeline Engine (Architecture A target)** |
| `recordings/` | Dir | Ignored | - | Video recordings |
| `reports/` | Dir | Tracked | - | Phase reports |
| `requirements/` | Dir | Tracked | - | Requirements files |
| `scripts/` | Dir | Tracked | - | 100+ phase scripts (historical) |
| `TensorRT-11.3.0.99/` | Dir | Untracked | - | TensorRT SDK |
| `test_data/` | Dir | Tracked | - | Test data & fix scripts |
| `tests/` | Dir | Tracked | - | Unit/integration/live tests |
| `tools/` | Dir | Tracked | - | Utility tools |
| `UI/` | Dir | Untracked | - | Single index.html (React?) |
| `Video_Codec_SDK_13.0.37/` | Dir | Untracked | - | NVIDIA Video Codec SDK |
| `video_pipeline_v2/` | Dir | Tracked | - | **Historical pipeline v2 (NVENC, annotated output)** |
| `bootstrap.py` | File | Untracked | 24KB | **Pipeline bootstrap entrypoint** |
| `bootstrap.bat` | File | Untracked | 2.5KB | Windows launcher for .venv2 |
| `encoder_output.h264` | File | Untracked | 9KB | Test encoder output |
| `Makefile` | File | Tracked | 7KB | Build rules |
| `nvcv_bridge.*` | Files | Untracked | ~200KB | CUDA bridge libs |
| `*.h264, *.mp4` | Files | Untracked | 100s MB | Test video files |
| `yolo11n.pt` | File | Untracked | 5.6MB | YOLO model |

---

## 3. Key Subsystems Identified

### 3.1 Legacy Backend (`app/`)
- **Entry:** `app/main.py` → FastAPI on dynamic port
- **Database:** `app/data/attendance.db` + WAL files
- **API:** Health, Attendance, Persons, Timetable, Excel, Parent Telegram, Geometry, Enrollment, Replay, Provenance, WebSocket
- **Ownership:** Authoritative for attendance business logic, DB, state transitions

### 3.2 Pipeline Engine (`pipeline_engine/`)
- **Config:** `pipeline_engine/config/pipeline.yaml` (434 lines)
- **Modules:** config, core, decode, encode, ingestion, inference, tracking, integration, memory, monitoring, output, annotation, attendance, backend
- **Bootstrap:** `bootstrap.py` (686 lines) — orchestrates MediaMTX + PipelineEngine
- **Target:** Architecture A AI Worker (not yet implemented)

### 3.3 MediaMTX (`mediamtx/`)
- **Binary:** `mediamtx/mediamtx.exe`
- **Config:** `mediamtx/mediamtx.yml` (719 lines)
- **Ports:** RTSP 8554, RTMP 1935, API 9997, HLS 8888, WebRTC 8889
- **Paths:** `live/cam1`, `live/cam2` (input), `live/cam1-ai`, `live/cam2-ai` (output)

### 3.4 Video Pipeline v2 (`video_pipeline_v2/`)
- **Historical** implementation with NVENC annotated output
- **Modules:** ai, annotation, core, decoder, encoder, input, monitoring, output, runtime, workers, tests
- **Status:** Superseded by Architecture A but contains reusable components

### 3.5 Models (`models/`)
- SCRFD: `models/scrfd/scrfd_10g_bnkps.onnx`
- ArcFace: `models/arcface/glintr100.onnx`
- YOLO: `models/yolo/yolo11n.onnx`, `yolo11n-pose.pt`
- ReID: `models/reid/resnet50_reid.onnx`
- Landmark: `models/landmark/1k3d68.onnx`

### 3.6 Data (`data/`, `app/data/`)
- `data/attendance.db`, `attendance_events.db`, `exit_sessions.db`, `notification_queue.db`, `parent_registry.db`
- `app/data/attendance.db`, `exit_sessions.db`, `parent_registry.db`, `notification_queue.db`
- `app/data/enrollment/embeddings.npy` + metadata

### 3.7 Python Environment (`.venv2/`)
- Python 3.12.10
- PyTorch 2.13.0+cu126 (CUDA 12.6)
- ONNX Runtime 1.28.0 (CUDAExecutionProvider, TensorrtExecutionProvider)
- GPU: Available (verified)

---

## 4. Git Status Summary

- **Deleted in working tree (not staged):** `figma/` (entire directory, 91 files), `frontend/` (entire directory, 37 files) — These were previously committed, now deleted
- **No staged changes**
- **Untracked:** `UI/`, `artifacts/`, `bootstrap.py`, `bootstrap.bat`, `new_engine/`, `pipeline_engine/`, `test_encoder.mp4`, various video files

---

## 5. Phase 0.1 Audit Artifacts (Reference)

Located at `new_engine/audit/phase_0_1/`:
1. `00_phase_0_1_scope_and_baseline.md`
2. `01_environment_verification.md`
3. `02_gpu_cuda_onnx_verification.md`
4. `03_mediamtx_runtime_verification.md`
5. `04_camera_stream_verification.md`
6. `05_legacy_backend_architecture.md`
7. `06_legacy_backend_api_inventory.md`
8. `07_database_ownership_and_schema.md`
9. `08_attendance_event_contract.md`
10. `09_ai_worker_backend_integration_contract.md`
11. `10_timestamp_synchronization_design.md`
12. `11_ui_video_metadata_alignment.md`
13. `12_module_reuse_adapt_replace_matrix.md`
14. `13_performance_and_observability_plan.md`
15. `14_blockers_and_risk_register.md`
16. `15_phase_0_1_final_verdict.md` — **PARTIAL**

---

## 6. Phase 0.2 Execution Plan

### Stage A: Baseline & Forensic Inventory (This artifact)
- [x] Repository root inventory
- [x] Key subsystem identification
- [ ] Complete file-level inventory with classification (KEEP/MOVE/REMOVE CANDIDATE)

### Stage B: Canonical Repository Structure
- [ ] Define target structure based on actual boundaries
- [ ] Document in `05_canonical_repository_structure.md`

### Stage C: Cleanup & Relocation
- [ ] Produce `03_cleanup_and_relocation_plan.md`
- [ ] Execute safe moves, quarantine candidates
- [ ] Log in `04_cleanup_execution_log.md`

### Stage D: Infrastructure Bring-Up
- [ ] Python GPU runtime baseline (`07_python_gpu_model_runtime.md`)
- [ ] MediaMTX runtime baseline (`08_mediamtx_runtime_baseline.md`)
- [ ] Legacy Backend runtime baseline (`09_legacy_backend_runtime_baseline.md`)
- [ ] Camera 1 runtime baseline (`10_camera_1_runtime_baseline.md`)
- [ ] Camera 2 runtime baseline (`11_camera_2_runtime_baseline.md`)
- [ ] Dual-camera relay (`12_dual_camera_runtime_baseline.md`)
- [ ] Enrollment data integrity (`13_enrollment_data_integrity.md`)

### Stage E: Runtime Baseline Tests
- [ ] Performance baseline (`14_resource_and_performance_baseline.md`)
- [ ] Startup/shutdown procedures (`15_startup_shutdown_procedure.md`)
- [ ] Blockers & recovery (`16_blockers_and_recovery_plan.md`)
- [ ] Final verdict (`17_phase_0_2_final_verdict.md`)

---

## 7. Immediate Blockers / Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Camera publishers not found/configured | Cannot verify RTSP streams | Document as BLOCKED if hardware unavailable |
| No enrollment embeddings | AI readiness incomplete | Document status, don't fabricate |
| Duplicate DBs (`data/` vs `app/data/`) | Confusion on canonical source | Identify authoritative owner |
| `video_pipeline_v2` overlaps with `pipeline_engine` | Duplicate AI logic | Classify as historical, review for reuse |
| `figma/`, `frontend/` deleted but in Git history | Recovery possible | Document, don't purge Git history |

---

## 8. Next Actions

1. Complete file-level inventory (Stage A continued)
2. Read phase_0_1 verdict for context
3. Define canonical structure
4. Begin infrastructure verification