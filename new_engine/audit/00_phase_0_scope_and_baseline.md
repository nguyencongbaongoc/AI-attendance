# Phase 0 — Scope and Baseline

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

## Python Environment
- **Python Version**: 3.12.10 (from requirements/windows.txt)
- **Virtual Environment**: Not detected in repository root (no venv/ directory visible)

## Installed Package Versions (from requirements)
| Package | Version | Source |
|---------|---------|--------|
| pydantic | >=2.5.0,<3.0.0 | requirements/base.txt |
| pyyaml | >=6.0.1,<7.0.0 | requirements/base.txt |
| python-dotenv | >=1.0.0,<2.0.0 | requirements/base.txt |
| structlog | >=24.1.0,<25.0.0 | requirements/base.txt |
| pytest | >=7.4.0,<8.0.0 | requirements/base.txt |
| mypy | >=1.7.0,<2.0.0 | requirements/base.txt |
| torch | 2.13.0+cu126 | requirements/windows.txt |
| torchvision | 0.28.0+cu126 | requirements/windows.txt |
| torchaudio | 2.11.0+cu126 | requirements/windows.txt |
| onnxruntime-gpu | 1.28.0 | requirements/windows.txt |
| onnx | 1.22.0 | requirements/windows.txt |
| numpy | 2.5.2 | requirements/windows.txt |
| nvidia-ml-py | >=12.535.133,<13.0.0 | requirements/windows.txt |
| ffmpeg-python | >=0.2.0,<1.0.0 | requirements/windows.txt |
| psutil | >=5.9.0,<6.0.0 | requirements/windows.txt |
| pywin32 | >=306,<307 | requirements/windows.txt |
| wmi | >=1.5.1,<2.0.0 | requirements/windows.txt |

## CUDA Environment
- **CUDA Toolkit**: 13.3 (system)
- **cuDNN**: 9.10.2 (bundled with torch)
- **PyTorch CUDA**: 12.6
- **Target GPU**: GTX 1660 Ti (6GB VRAM)

## Test Framework
- **Framework**: pytest (>=7.4.0,<8.0.0)
- **Test Inventory**: No test files found in `pipeline_engine/tests/` subdirectories (unit, integration, hardware, runtime all empty)
- **pytest.ini**: Present at repository root

## Key Directories
| Directory | Purpose |
|-----------|---------|
| `pipeline_engine/` | Core pipeline implementation (NEW - untracked) |
| `config/` | Legacy configuration |
| `models/` | ONNX model files (SCRFD, ArcFace, YOLO, ReID) |
| `mediamtx/` | MediaMTX binary and configuration |
| `UI/` | Frontend HTML/JS (single index.html) |
| `data/` | Runtime data directory |
| `recordings/` | Video recordings storage |
| `logs/` | Application logs |
| `scripts/` | Utility scripts |
| `tools/` | Development tools |
| `docs/` | Documentation |
| `requirements/` | Python dependencies |
| `isolated_src/`, `isolated_tests/` | Isolated development artifacts |

## Phase 0 Scope
This audit covers **only** the `pipeline_engine/` directory and its integration with:
- MediaMTX (external process, configured via `mediamtx/mediamtx.yml`)
- Existing backend (separate from `pipeline_engine/backend/`)
- UI (`UI/index.html`)
- Model files in `models/`
- Camera RTSP streams (via MediaMTX paths `live/cam1`, `live/cam2`)

**Out of scope**: The separately stopped GPU Video Pipeline Engine repository, figma/frontend (deleted), benchmark_results, video_pipeline_v2, phase7_runtime_diagnostic.