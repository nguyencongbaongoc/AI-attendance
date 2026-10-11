# Phase 0.2 — Git and User Data Protection

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage A: Baseline and Forensic Inventory

---

## 1. Repository Identity

| Property | Value |
|----------|-------|
| **Repository Root** | `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE` |
| **Git Branch** | `main` (assumed - no branch name visible, HEAD at `5269777`) |
| **Git HEAD** | `5269777 feat: Add Camera Supervisor and Runtime for V2 GPU-first video pipeline` |
| **Git Status** | Working tree has 128 deletions (figma/, frontend/), no staged changes |

---

## 2. Git Status Details

### 2.1 Working Tree Deletions (Not Staged)

The following directories were previously committed but are now deleted in the working tree:

- **`figma/`** — 91 files (React/TypeScript frontend, Vite, pnpm)
- **`frontend/`** — 37 files (Vue.js frontend, Vite, pnpm)

**Impact:** These exist in Git history at commit `5269777` and earlier. They are NOT in the current working tree. Recovery is possible via `git restore` or checking out earlier commits.

**Protection:** Do NOT run `git clean -fd` or similar destructive commands. These deletions are intentional working tree state.

### 2.2 Untracked Directories (Not in Git)

| Directory | Size | Classification | Risk if Deleted |
|-----------|------|----------------|-----------------|
| `.venv2/` | 5.9 GB | Active Python runtime | HIGH — Active environment |
| `live/` | 4.2 GB | Generated test video | LOW — Generated data |
| `.kilo/` | 3.3 GB | Kilo IDE config | MEDIUM — IDE config |
| `TensorRT-11.3.0.99/` | 2.3 GB | NVIDIA SDK | HIGH — Vendor SDK, may be needed |
| `models/` | 988 MB | AI models | CRITICAL — Protected |
| `benchmark_results/` | 750 MB | Generated benchmarks | LOW — Historical |
| `artifacts/` | 265 MB | Generated artifacts | LOW — Generated |
| `mediamtx/` | 54 MB | MediaMTX runtime | CRITICAL — Runtime dependency |
| `test_data/` | 24 MB | Test fixtures + fix scripts | MEDIUM — May have unique fixtures |
| `Video_Codec_SDK_13.0.37/` | 3.5 MB | NVIDIA SDK | HIGH — Vendor SDK |
| `scripts/` | 2.4 MB | Historical phase scripts | LOW — Mostly historical |
| `UI/` | 113 KB | Frontend entrypoint | UNKNOWN — Verify if active |
| `new_engine/` | 340 KB | Audit + new arch | KEEP — Audit artifacts |
| `data/` | 240 KB | SQLite DBs (duplicates) | MEDIUM — Duplicate of app/data |
| `Video files (root)` | ~1.6 GB | Test videos | LOW — Generated/test |

---

## 3. Protected Assets Inventory (NEVER DELETE/RELOCATE)

### 3.1 Active Runtime Environment
- **`.venv2/`** — Python 3.12.10, PyTorch 2.13.0+cu126, ONNX Runtime 1.28.0
- **`mediamtx/mediamtx.exe`** — MediaMTX binary (54 MB)
- **`mediamtx/mediamtx.yml`** — MediaMTX configuration
- **`nvcv_bridge.pyd/.lib/.exp`** — CUDA bridge Python extension

### 3.2 AI Model Files
- **`models/scrfd/scrfd_10g_bnkps.onnx`** — Face detection
- **`models/arcface/glintr100.onnx`** — Face recognition (261 MB)
- **`models/yolo/yolo11n.onnx`** — Person detection
- **`models/yolo/yolo11n-pose.pt`** — Pose estimation
- **`models/reid/resnet50_reid.onnx`** — ReID (disabled)
- **`models/landmark/1k3d68.onnx`** — Landmark detection

### 3.3 Authoritative Databases & Enrollment
- **`app/data/attendance.db`** + WAL/SHM — Primary attendance database
- **`app/data/exit_sessions.db`** — Exit session tracking
- **`app/data/parent_registry.db`** — Parent registry
- **`app/data/notification_queue.db`** — Notification queue
- **`app/data/enrollment/embeddings.npy`** — Face embeddings
- **`app/data/enrollment/embeddings.npy.metadata.json`** — Embedding metadata

### 3.4 Configuration & Secrets
- **`config/default.yaml`** — Pipeline configuration
- **`config/runtime-ports.json`** — Port assignments
- **`config/geometry/CAM1.json`**, **`CAM2.json`** — Camera geometry
- **`.env` files** — Not currently present but protected if found
- **`mediamtx/auto.crt`, `auto.key`** — TLS certificates

### 3.5 Source Code (Authoritative Implementations)
- **`app/`** — Legacy Backend (FastAPI, attendance authority)
- **`pipeline_engine/`** — New Pipeline Engine (Architecture A)
- **`app/vision/`** — Vision modules (SCRFD, ArcFace, YOLO, tracking)
- **`app/streaming/`** — Streaming modules (NVDEC, NVENC, RTMP/RTSP)

### 3.6 Vendor SDKs (Required for GPU Operations)
- **`TensorRT-11.3.0.99/`** — TensorRT 11.3 (for TensorRT EP)
- **`Video_Codec_SDK_13.0.37/`** — NVIDIA Video Codec SDK (for NVENC/NVDEC)

### 3.7 Git Metadata
- **`.git/`** — Git repository (never delete)

---

## 4. User Data That May Be in Untracked Directories

### 4.1 Potentially User-Created Content

| Location | Content Type | Verification Needed |
|----------|--------------|---------------------|
| `recordings/` | User video recordings | Check if empty or has user content |
| `data/exports/` | Excel exports | User-generated reports |
| `app/data/temp/` | Temporary processing | May have user uploads |
| `logs/` | Application logs | Operational history |

### 4.2 Verification Commands

```bash
# Check recordings directory
ls -la recordings/

# Check exports
ls -la data/exports/ app/data/exports/

# Check temp directories
ls -la app/data/temp/ data/temp/

# Check for any .env files
find . -name ".env*" -not -path "./.venv2/*" -not -path "./.venv_38p_isolated/*"

# Check for user uploads
find . -name "*.jpg" -o -name "*.png" -o -name "*.jpeg" | head -20
```

---

## 5. Git Protection Rules for This Phase

### 5.1 Commands NEVER to Run
- `git reset --hard` — Would lose working tree deletions (figma/, frontend/)
- `git clean -fd` — Would delete untracked protected assets (.venv2, models, mediamtx, SDKs)
- `git checkout --` — Would restore deleted directories unexpectedly
- `git restore` — Same as above
- `git commit` — Not authorized unless explicitly requested
- `git rebase`, `git filter-branch`, `git push --force` — History rewrite forbidden

### 5.2 Safe Commands
- `git status` — Read-only
- `git diff` — Read-only
- `git log` — Read-only
- `git show` — Read-only
- `git ls-files` — Read-only

### 5.3 File Operations Policy
- **Move:** Use `Move-Item` (PowerShell) or `shutil.move()` with hash verification
- **Copy:** Use `Copy-Item` or `shutil.copy2()` with hash verification
- **Delete:** ONLY after quarantine period and validation
- **Quarantine Location:** `new_engine/audit/phase_0_2/quarantine/`

---

## 6. Quarantine Protocol

### 6.1 Quarantine Directory Structure
```
new_engine/audit/phase_0_2/quarantine/
├── root_test_videos/
├── root_model_duplicates/
├── data_duplicate_dbs/
├── historical_scripts/
├── generated_artifacts/
├── build_artifacts/
└── empty_dirs/
```

### 6.2 Quarantine Process
1. Identify candidate with evidence
2. Verify no references (imports, config, scripts, entrypoints)
3. Verify not protected asset
4. Move to quarantine (preserve directory structure)
5. Record: original path, destination, hash, reason, timestamp
6. Run validation (bootstrap check, import test, config test)
7. Wait for explicit approval before permanent deletion

### 6.3 Quarantine Log Template
| Original Path | Destination | Hash (SHA256) | Size | Reason | Date | Verified By |
|---------------|-------------|---------------|------|--------|------|-------------|

---

## 7. Rollback Plan

### 7.1 Git-Based Rollback
- All source code changes tracked in Git
- `git status` shows current state
- `git diff` shows modifications
- `git stash` can preserve local changes
- `git restore <file>` can restore individual files

### 7.2 File-Based Rollback (for moved files)
- Quarantine preserves original content
- Hash verification ensures integrity
- Original paths recorded for restoration
- `Move-Item` back to original location

### 7.3 Environment Rollback
- `.venv2/` never modified
- If Python packages changed: `pip install -r requirements/base.txt -r requirements/windows.txt`
- MediaMTX config never modified in this phase
- Model files never modified

---

## 8. Verification Checklist Before Any Destructive Action

- [ ] Asset classified as REMOVE CANDIDATE (not KEEP, not MOVE)
- [ ] Evidence documented: duplicate, obsolete, unused, incompatible
- [ ] No imports/references found in active code
- [ ] Not in entrypoint scripts (bootstrap.py, bootstrap.bat)
- [ ] Not in configuration files (pipeline.yaml, mediamtx.yml, config/*.yaml)
- [ ] Not a protected asset (models, DBs, enrollment, SDKs, venvs, certs)
- [ ] Not user data (recordings, exports, uploads, logs)
- [ ] Moved to quarantine (not deleted)
- [ ] Validation tests pass after move
- [ ] Explicit approval for permanent deletion obtained

---

## 9. Current Protection Status

| Asset | Protected | In Quarantine | Deleted |
|-------|-----------|---------------|---------|
| `.venv2/` | ✅ | ❌ | ❌ |
| `app/data/` | ✅ | ❌ | ❌ |
| `models/` subdirs | ✅ | ❌ | ❌ |
| `mediamtx/` | ✅ | ❌ | ❌ |
| `TensorRT-11.3.0.99/` | ✅ | ❌ | ❌ |
| `Video_Codec_SDK_13.0.37/` | ✅ | ❌ | ❌ |
| `nvcv_bridge.*` | ✅ | ❌ | ❌ |
| `.git/` | ✅ | ❌ | ❌ |
| `figma/` (in Git) | ✅ (in history) | ❌ | ✅ (working tree) |
| `frontend/` (in Git) | ✅ (in history) | ❌ | ✅ (working tree) |
| Root test videos | ❌ | ⏳ Pending | ❌ |
| Root model duplicates | ❌ | ⏳ Pending | ❌ |
| `data/` duplicate DBs | ❌ | ⏳ Pending | ❌ |
| `scripts/` historical | ❌ | ⏳ Pending | ❌ |
| `live/` generated | ❌ | ⏳ Pending | ❌ |

---

## 10. Next Actions

1. Complete file-level classification for REVIEW items
2. Create canonical structure document
3. Produce cleanup plan with specific quarantine actions
4. Begin infrastructure bring-up (Stage D) — this does not require cleanup first