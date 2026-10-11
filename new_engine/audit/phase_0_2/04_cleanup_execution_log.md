# Phase 0.2 — Cleanup Execution Log

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage C: Repository Cleanup and Relocation

---

## 1. Quarantine Directory Structure Created

```
new_engine/audit/phase_0_2/quarantine/
├── root_test_videos/
├── root_model_duplicates/
├── data_duplicate_dbs/
├── historical_scripts/
├── generated_artifacts/
├── build_artifacts/
├── empty_dirs/
├── generated_live/
└── video_pipeline_v2/
```

---

## 2. Files Moved to Quarantine (with SHA256)

### 2.1 Root Test Videos (18 files, ~1.6 GB)

| File | SHA256 | Size | Destination |
|------|--------|------|-------------|
| encoder_output.h264 | 3366B26D1C486B05DAADB5DC46CB955B2F834E6D1BC0EA3D4967B50212F482D8 | 9 KB | root_test_videos/ |
| real_h264.h264 | 9EDF5917E534E9D227EA601279E20746A6DEBD30A927FBA778C4EAA090D31151 | 13 KB | root_test_videos/ |
| test_output_r5.h264 | 76075F151D454B104F5FEA1D14E75C8BDA6CFF44EC52ED90C3A713D58DBCD8BC | 13 KB | root_test_videos/ |
| test_output.h264 | E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855 | 0 B | root_test_videos/ |
| test.h264 | 79EB4B8A1E6F7CB7A2EDDF599BBD8D887E830C6B727A24997F3C772BD4FF54CA | 33 B | root_test_videos/ |
| submission_4k_canonical.mp4 | 9FC6A3B375B0B1646045E16E1CC1D12F6A87ABB604927A48A9C4C82D49E7C29E | 27 MB | root_test_videos/ |
| submission_4k_yolo_arcface_facebox_y1350.mp4 | 1597B6D5199E62E409B90464C6FD5C208C749C9A8908B54CE79A0EBC8B77D9F6 | 3.8 MB | root_test_videos/ |
| submission_4k_yolo_arcface_facebox_y2000.mp4 | E758C7AF9756D2625CA22B1E246E0AB97DE6E2661DA72B57A90521D386C36789 | 407 MB | root_test_videos/ |
| submission_4k_yolo_arcface_full.mp4 | E42E77E4F8C154F5154BDAAA46FCB2C8F38404613EABE050F97E60968CAD12C7 | 380 MB | root_test_videos/ |
| submission_4k_yolo_arcface_name_overlay.mp4 | F7F653C7E6020C4A6B748EFC9C5284321E1589B6697E5438B71EFC9F7D634BA8 | 407 MB | root_test_videos/ |
| submission_4k.mp4 | 4EF1160F717CC9467B6BE23560135D1B05614C24653E53B0D972DF31825F9832 | 2 MB | root_test_videos/ |
| submission_remediated_4k.mp4 | 790CB8EE92CFC5951F5767F22B56BAEB2FE551D8D6E92422C1A23B51410ECAC9 | 223 MB | root_test_videos/ |
| submission_remediated_4k1.mp4 | CC86DCD47698B90C9B66FC5032432FA789E6DED237BC5ABA789FF54E91136224 | 409 MB | root_test_videos/ |
| submission.mp4 | 92511A07D55E15EDFC4DEADD87D37FA7159108963ADF010F4E340A4589762EE4 | 3.4 MB | root_test_videos/ |
| test_encoder.mp4 | E999E5ADFD802623178DA539F218279554E94A730AD97532868E91688EA16AB7 | 1.3 MB | root_test_videos/ |
| test_video_long.mp4 | FACBE9F3E2D1FBC6E26108C5780B05747166BADEAB01E9675F024C7DCB510571 | 171 MB | root_test_videos/ |
| test_video.mp4 | A9ACA95EFC52788970D590FE52FEE611E09E601028DCAF30CACA1531F10614A7 | 29 MB | root_test_videos/ |
| yolo11n.pt (root) | 0EBBC80D4A7680D14987A577CD21342B65ECFD94632BD9A8DA63AE6417644EE1 | 5.6 MB | root_test_videos/ |

### 2.2 Root Model Duplicates (3 files, ~350 MB)

| File | SHA256 | Destination |
|------|--------|-------------|
| models/glintr100.onnx | 4AB1D6435D639628A6F3E5008DD4F929EDF4C4124B1A7169E1048F9FEF534CDF | root_model_duplicates/ |
| models/1k3d68.onnx | DF5C06B8A0C12E422B2ED8947B8869FAA4105387F199C477AF038AA01F9A45CC | root_model_duplicates/ |
| models/resnet50_reid.onnx | 09D398902020205DD4AA80495B2A8FCEECD64BA610E6B72AFC1F93965C9613D2 | root_model_duplicates/ |

### 2.3 Duplicate Databases (4 files, <1 MB)

| File | SHA256 | Destination |
|------|--------|-------------|
| data/attendance.db | 30FB1F177F284B3FD573D2BAA46538DA2993B0BF5B6C6CB48717116A429D7080 | data_duplicate_dbs/ |
| data/exit_sessions.db | EEEFDE20E6D9D3314C9A72A32A8B4B38101958D042E1F12EAD3AC947741A724A | data_duplicate_dbs/ |
| data/parent_registry.db | 0AA11DAB160117070214CE16125E476D98BFBFD8FF48CB4A06B7F81A79B96EC8 | data_duplicate_dbs/ |
| data/notification_queue.db | 670211D208999B820855C2244DA5D8BCEBDF4A731BCFC22BDD08F019EEA49894 | data_duplicate_dbs/ |

**Note:** These 4 databases were RESTORED to `data/` after quarantine to support Legacy Backend operation (which expects DBs in `data/` per `app/config/settings.py`).

### 2.4 Historical Scripts (80+ files, ~2 MB)

All phase/debug/fix/generate/test scripts moved to `quarantine/historical_scripts/`. Key examples:

| File | SHA256 |
|------|--------|
| phase33_live_health_failover.py | 257D34C5F2779057B9317CFE9EB3EDE93249A43C459A7BD810AC4891542F5624 |
| phase36k_final_report.py | 69EF44DFA8EC3B201117890750D0B2FCBD8D74C87E798900F24126CD6DF67495 |
| phase36k_subagent1_e2e_trace.py | 6200A0A97E3D2EBCFD35385EF6B45C8293F0EAB1742AA54B4723F253CBF9960E |
| phase36k_subagent10_hardware_headroom.py | 7E35BE9659EE0615ACD5B28A4894F2A45C7D0909DDA7CDE9C7D1A2341D6CD872 |
| run_phase33_final.py | 8F4FA31891D2258D823EDF9D092F55526B8E531E68FD996B925C7B54AD90A065 |
| run_phase33_simple.py | C8C7795D47C619F18F3EDB28A8E55CDD6E078C93C2B34830A6830D8CF8DCC72B |
| debug_phase22_geometry_versioning.py | 033F0594AAADF86B21412EEF8746CF19776D6DCBBE0B4D0C1535C92D533497EA |
| fix_check_health.py | C3C27032BBBFB5A283DFCC1CCFA491DACF24F56FB86D6C98580E843C523FC533 |
| test_cuda_ort.py | 6D170D8B1E51EF02E2D4EA05A2F21412424D544843242E65F589427421AE5E79 |
| update_health.py | 99B7A18DFCF2FB39754716620CEBF6A8FDC1926FE77FC134B21CB87D5C10FABB |
| ... and 70+ more | ... |

### 2.5 Generated Artifacts

| Source | Destination | Size |
|--------|-------------|------|
| artifacts/ | generated_artifacts/ | 265 MB |
| benchmark_results/ (root) | generated_artifacts/ | 750 MB |
| out.txt | generated_artifacts/ | 0 B |
| patch_submit.py | historical_scripts/ | 6 KB |

### 2.6 Build Artifacts

| Source | Destination | Size |
|--------|-------------|------|
| build/ | build_artifacts/ | 1.3 MB |
| CMakeFiles/ | build_artifacts/ | 9 MB |
| .pytest_cache/ | build_artifacts/ | <1 MB |

### 2.7 Runtime Logs

| Source | Destination | Size |
|--------|-------------|------|
| logs/ | runtime_logs/ | <1 MB |

### 2.8 Empty Directories

| Source | Destination |
|--------|-------------|
| phase7_runtime_diagnostic/ | empty_dirs/ |
| New folder/ | empty_dirs/ |

### 2.9 Generated Live Data

| Source | Destination | Size |
|--------|-------------|------|
| live/ | generated_live/ | 4.2 GB (3,007 files) |

### 2.10 Video Pipeline v2

| Source | Destination | Size |
|--------|-------------|------|
| video_pipeline_v2/ | video_pipeline_v2/ | 0.5 MB (36 files) |

---

## 3. Post-Cleanup Verification Results

| Check | Command | Result |
|-------|---------|--------|
| Bootstrap environment | `python bootstrap.py --check` | ✅ PASS |
| Legacy Backend import | `from app.main import create_app` | ✅ PASS |
| Pipeline Engine import | `from pipeline_engine.core.engine import PipelineEngine` | ✅ PASS |
| Pipeline Config load | `load_pipeline_config()` | ✅ PASS |
| MediaMTX start | `mediamtx.exe mediamtx.yml` | ✅ PASS |
| Legacy Backend start | `uvicorn.run(app, port=19146)` | ✅ PASS |
| Camera 1 RTSP decode | `av.open(rtsp://localhost:8554/live/cam1)` | ✅ PASS (29.3 fps) |
| Camera 2 RTSP decode | `av.open(rtsp://localhost:8554/live/cam2)` | ✅ PASS (47.1 fps) |
| Dual-camera concurrent | Threaded decode both | ✅ PASS (97+100 fps) |
| AI Model sessions | ONNX Runtime CUDA EP | ✅ PASS (all 3 models) |
| Enrollment data | `np.load(embeddings.npy)` | ✅ PASS (7×512) |

---

## 4. Files NOT Moved (Correctly Kept)

### Active Runtime
- `.venv2/` — 5.9 GB, 35,652 files
- `mediamtx/` — 54 MB, 5 files
- `models/` subdirectories — 988 MB, 15 files
- `app/data/` — 7 files (DBs + enrollment)
- `nvcv_bridge.*` — 200 KB

### Source Code
- `app/` — 406 files, 6 MB (Legacy Backend)
- `pipeline_engine/` — 40 files, 0.8 MB (Architecture A)
- `tests/` — 222 files, 10 MB
- `tools/` — 4 files
- `config/` — 5 files

### Configuration & Documentation
- `config/` — Configuration
- `requirements/` — base.txt, windows.txt
- `docs/`, `reports/`, `new_engine/audit/` — Documentation
- `bootstrap.py`, `bootstrap.bat` — Entrypoints
- `Makefile`, `pytest.ini`, `.gitignore` — Build config

### Vendor SDKs
- `TensorRT-11.3.0.99/` — 2.3 GB
- `Video_Codec_SDK_13.0.37/` — 3.5 MB

### Tooling
- `.kilo/`, `.clinerules/`, `.vscode/` — IDE config
- `.venv_38p_isolated/` — Isolated venv
- `recordings/` — Empty target

---

## 5. Items Requiring Human Decision (REVIEW)

| Item | Status | Recommendation |
|------|--------|----------------|
| `UI/index.html` | Kept in place | Verify if active frontend; if not, quarantine |
| `test_data/` | Kept in place | Extract unique test fixtures, quarantine fix scripts |
| `isolated_src/`, `isolated_tests/` | Kept in place | Investigate purpose |
| `data/attendance_events.db`, `attendance_daily.db` | Kept in `data/` | PipelineEngine config references these; keep if used |

---

## 6. Rollback Test Results

| Restore Test | Command | Result |
|--------------|---------|--------|
| Single file | `Move-Item quarantine/root_test_videos/yolo11n.pt models/yolo/yolo11n.pt` | ✅ Works |
| Directory | `Move-Item quarantine/video_pipeline_v2 video_pipeline_v2` | ✅ Works |
| Script | `Move-Item quarantine/historical_scripts/phase33_live_health_failover.py scripts/` | ✅ Works |
| Git restore | `git restore figma/ frontend/` | ✅ Works (from history) |

---

## 7. Summary

**Total quarantined:** ~1,600 files, ~6.5 GB  
**Total kept active:** ~37,000 files, ~9.3 GB  
**Verification:** All 8 infrastructure tests PASS  
**Rollback:** Fully tested and working  

**Cleanup execution: COMPLETE**