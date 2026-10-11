# Phase 1.V3 CAM2 and Dual-Camera Runtime Preflight

**Date**: 2026-10-04
**Phase**: 1.V3 - CAM2 and Dual-Camera Runtime
**Authorization**: Phase 1.V1 → V1.V5 (V1, V2 completed)

---

## 1. V1 & V2 Completion Status

### V1 - Environment Recovery: PASS
- Camera streams discovered (CAM1, CAM2)
- Streams decoded (100 frames each at 39+ fps)
- Backend running at port 18693
- Event ingestion working

### V2 - CAM1 Single-Camera: CONDITIONAL PASS
- CAM1 frames traverse complete pipeline
- SCRFD/YOLO GPU inference working (28ms)
- ArcFace GPU initialized (0 inferences - no faces)
- Tracking/Crossing engines initialized
- Event delivery architecture ready
- Camera isolation verified
- GPU memory stable (1.5-1.7 GB)
- Frame pool exhaustion fixed

### Conditions from V2
1. Duration: Only 30s tested (need 10+ min)
2. ArcFace: Not exercised (no faces)
3. Crossings: Not tested (empty scene)
4. NVENC: Failing (encoder optional)
5. Metrics: AI FPS/timing needs fix

---

## 2. V3 Objectives

### Primary Objectives
1. **CAM2 Independent Qualification** (10+ minutes)
2. **Dual-Camera Concurrent Operation** (30+ minutes)
3. **Timestamp Synchronization Validation**
4. **Camera Isolation Under Load**

### Duration Requirements
| Test | Minimum Duration | Target |
|------|------------------|--------|
| CAM2 Standalone | 10 minutes | 15 minutes |
| Dual-Camera Concurrent | 30 minutes | 30 minutes |

---

## 3. CAM2 Configuration

### Camera Setup
- **CAM2**: rtsp://localhost:8554/live/cam2
- **Resolution**: 3840×2160 @ 30fps
- **Codec**: h264
- **Geometry**: Line at y=1080, side_a_to_b_in

### Pipeline Components (Same as CAM1)
| Component | Status |
|-----------|--------|
| RTSP Source | Ready (V1 validated) |
| NVDEC Decoder | Software fallback |
| Frame Pool | 32 frames |
| SCRFD | CUDAExecutionProvider |
| ArcFace | CUDAExecutionProvider |
| YOLO | CUDAExecutionProvider |
| Tracker | Independent instance |
| Attendance | Independent engine |

---

## 4. Dual-Camera Architecture

### Independence Guarantees
| Resource | Per-Camera | Shared |
|----------|------------|--------|
| RTSP Source | ✅ | - |
| Decoder | ✅ | - |
| Frame Pool | ✅ | - |
| SCRFD Model | ✅ | Weights |
| ArcFace Model | ✅ | Weights |
| YOLO Model | ✅ | Weights |
| Tracker | ✅ | - |
| Attendance Engine | ✅ | - |
| Encoder | ✅ | - |
| Publisher | ✅ | - |

### GPU Memory Budget
| Camera | Frame Pool | Models | Total |
|--------|------------|--------|-------|
| CAM1 | ~1.5 GB | ~0.3 GB | ~1.8 GB |
| CAM2 | ~1.5 GB | ~0.3 GB | ~1.8 GB |
| **Total** | **~3.0 GB** | **~0.6 GB** | **~3.6 GB** |
| **Budget** | | | **4.0 GB** |
| **Headroom** | | | **~0.4 GB** |

---

## 5. Timestamp Synchronization

### Requirements
- Each camera has independent `stream_epoch`
- Frame sequence per camera
- PTS/timebase from RTSP stream
- Capture timestamp at frame acquisition
- Processing timestamp at AI completion

### Synchronization Analysis
| Aspect | CAM1 | CAM2 | Sync Method |
|--------|------|------|-------------|
| Timebase | 1/90000 | 1/90000 | Same |
| PTS Offset | Positive | Negative initial | Track per-camera |
| Capture Clock | Wall-clock | Wall-clock | Same host |
| Stream Epoch | 0 | 0 | Increment on reconnect |

### Cross-Camera Correlation
- Events have `camera_id` for attribution
- `stream_epoch` distinguishes reconnect sessions
- `capture_timestamp` enables temporal correlation
- No shared clock assumption

---

## 6. Test Plan

### Phase 1: CAM2 Standalone (10+ min)
1. Disable CAM1, enable CAM2 only
2. Run full pipeline (encoder disabled for AI testing)
3. Collect metrics every 30s
4. Verify identical behavior to CAM1

### Phase 2: Dual-Camera Concurrent (30+ min)
1. Enable both CAM1 and CAM2
2. Run full pipelines concurrently
2. Monitor for interference
3. Verify camera isolation
4. Check GPU memory sharing
5. Validate timestamp attribution

### Phase 3: Synchronization Validation
1. Verify per-camera frame metadata
2. Check stream_epoch independence
3. Validate capture_timestamp correlation
4. Test reconnect behavior

---

## 7. Success Criteria

### CAM2 Standalone (V3 Gate 1)
- ✅ CAM2 frames traverse pipeline 10+ min
- ✅ SCRFD/YOLO GPU inference working
- ✅ ArcFace GPU initialized
- ✅ Tracking/Crossing engines working
- ✅ Camera isolation (CAM1 stopped)
- ✅ GPU memory stable

### Dual-Camera (V3 Gate 2)
- ✅ Both cameras running 30+ min
- ✅ No frame pool exhaustion
- ✅ No GPU OOM
- ✅ Camera isolation under load
- ✅ Events attributed to correct camera
- ✅ Timestamp provenance per camera

### Synchronization
- ✅ Per-camera frame metadata preserved
- ✅ stream_epoch independent per camera
- ✅ capture_timestamp enables correlation
- ✅ Reconnect handling per camera

---

## 8. Known Issues to Monitor

| Issue | From | Mitigation |
|-------|------|------------|
| NVENC failing | V1/V2 | Encoder optional for AI pipeline |
| AI FPS = 0.0 | V2 | Metrics fix needed |
| ArcFace 0 inferences | V2 | Test with faces |
| Frame timing not aggregated | V2 | Metrics fix needed |
| Dual-camera GPU memory | V3 | Monitor VRAM |

---

## 9. Test Commands

### CAM2 Only
```bash
python -c "
from pipeline_engine.config import load_pipeline_config
from pipeline_engine.ingestion.camera_manager import CameraManager
config = load_pipeline_config(Path('pipeline_engine/config/pipeline.yaml'))
config.cameras['cam1']['enabled'] = False
config.cameras['cam2']['encode']['enabled'] = False
config.cameras['cam2']['output']['enabled'] = False
manager = CameraManager(config)
manager.initialize()
manager.start_camera('cam2')
# monitor 10+ minutes
manager.stop_camera('cam2')
"
```

### Dual-Camera
```bash
python -c "
from pipeline_engine.config import load_pipeline_config
from pipeline_engine.ingestion.camera_manager import CameraManager
config = load_pipeline_config(Path('pipeline_engine/config/pipeline.yaml'))
config.cameras['cam1']['encode']['enabled'] = False
config.cameras['cam1']['output']['enabled'] = False
config.cameras['cam2']['encode']['enabled'] = False
config.cameras['cam2']['output']['enabled'] = False
manager = CameraManager(config)
manager.initialize()
manager.start_camera('cam1')
manager.start_camera('cam2')
# monitor 30+ minutes
manager.stop_all()
"
```

---

## 10. V3 Deliverables

```
new_engine/audit/phase_1_v3/
├── 00_cam2_preflight.md
├── 01_cam2_runtime.md
├── 02_cam2_model_runtime.md
├── 03_cam2_tracking_and_events.md
├── 04_dual_camera_architecture_verification.md
├── 05_dual_camera_concurrency.md
├── 06_dual_camera_metrics.md
├── 07_dual_camera_soak_30min.md
├── 08_camera_isolation_and_recovery.md
├── 09_phase_1_v3_verdict.md
```