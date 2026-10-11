# Phase 0.1 — Scope and Baseline

## Repository Information
- **Absolute Path**: `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE`
- **Repository Root**: `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE`
- **Working Directory**: `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE`

## Git Baseline
- **Current Branch**: `recovery/cpu-encoder-last-good`
- **HEAD Commit**: `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline`
- **Git Status**: 
  - 100+ deleted files from `figma/` and `frontend/` directories (untracked deletion)
  - `UI/` directory is untracked
  - `pipeline_engine/` directory is untracked
  - `bootstrap.py`, `bootstrap.bat` are untracked
  - Various test video files are untracked
- **Working Tree**: Clean except for untracked files and deleted files from figma/frontend

## Phase 0 Results Summary
**Phase 0 Verdict**: `PHASE 0 PARTIAL`
- All pipeline modules implemented (~13,500 lines, 32 files)
- Zero runtime verification - BLOCKED by missing environment
- Zero automated tests - all test directories empty
- No end-to-end execution ever demonstrated

## Phase 0.1 Objectives
Resolve six critical areas:
A. Actual environment verification
B. MediaMTX and camera runtime verification
C. Legacy backend forensic inspection
D. Architecture A integration contract
E. Timestamp synchronization design
F. Runtime qualification and performance measurement plan

## Key Directories Identified
| Directory | Purpose |
|-----------|---------|
| `pipeline_engine/` | Core pipeline implementation (NEW - untracked) |
| `app/` | Legacy backend (FastAPI) - authoritative attendance owner |
| `models/` | ONNX model files (SCRFD, ArcFace, YOLO, ReID) |
| `mediamtx/` | MediaMTX binary and configuration |
| `UI/` | Frontend HTML/JS (single index.html) |
| `data/` | Runtime data directory (SQLite, NPY files) |
| `recordings/` | Video recordings storage |
| `logs/` | Application logs |
| `config/` | Legacy configuration |
| `requirements/` | Python dependencies |

## Architecture A Definition (Previously Approved)

### Video Path (Passthrough)
```
Camera 1 + Camera 2
    → MediaMTX / existing FFmpeg relay
    → Original live video
    → UI video player
```

### AI Path (Independent)
```
Camera RTSP
    → Independent PyAV reader
    → Decode
    → SCRFD / ArcFace / YOLO
    → Tracking
    → Attendance
    → Existing backend
    → UI metadata overlay
```

## Safety Constraints (Non-Negotiable)
1. Do not modify existing application source code
2. Do not delete, rename, move, overwrite, or regenerate existing files
3. Do not modify database contents or schemas
4. Do not modify MediaMTX configuration
5. Do not modify camera publishers or camera settings
6. Do not install, uninstall, upgrade, or downgrade packages
7. Do not run Git reset, clean, checkout, restore, rebase, or destructive operations
8. Do not overwrite existing user changes
9. Do not start Phase 1
10. Do not implement any API endpoint, adapter, pipeline component, or UI functionality
11. Do not use mock data as evidence of actual runtime functionality
12. Do not assume previous audit statements are correct without verifying them

## Deliverables Required
15 audit artifacts under `new_engine/audit/phase_0_1/`:
1. 00_phase_0_1_scope_and_baseline.md
2. 01_environment_verification.md
3. 02_gpu_cuda_onnx_verification.md
4. 03_mediamtx_runtime_verification.md
5. 04_camera_stream_verification.md
6. 05_legacy_backend_architecture.md
7. 06_legacy_backend_api_inventory.md
8. 07_database_ownership_and_schema.md
9. 08_attendance_event_contract.md
10. 09_ai_worker_backend_integration_contract.md
11. 10_timestamp_synchronization_design.md
12. 12_module_reuse_adapt_replace_matrix.md
13. 13_performance_and_observability_plan.md
14. 14_blockers_and_risk_register.md
15. 15_phase_0_1_final_verdict.md