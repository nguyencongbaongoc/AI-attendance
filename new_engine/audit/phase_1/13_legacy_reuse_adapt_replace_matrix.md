# Phase 1 Artifact 13: Legacy Reuse, Adapt, Replace Matrix

**Date**: 2026-10-04
**Phase**: 1.V5 - Final Qualification and Closeout
**Status**: UPDATED WITH V1-V5 EVIDENCE

---

## 1. Component Classification

| Component | Status | Action | Evidence |
|-----------|--------|--------|----------|
| MediaMTX | Legacy | REUSE | Running, stable |
| Legacy Backend | Legacy | REUSE | Attendance authority |
| Phase 22-25 Resolver | Legacy | REUSE | Implemented |
| SCRFD | Legacy | ADAPT | GPU + IO Binding |
| ArcFace | Legacy | ADAPT | GPU + IO Binding |
| YOLO | Legacy | ADAPT | GPU + IO Binding |
| NVDEC Decoder | Legacy | ADAPT | Software fallback |
| NVENC Encoder | Legacy | ADAPT | Failing (known) |
| PipelineEngine | New | CREATE | V1-V3 implemented |
| CameraManager | New | CREATE | V1-V3 implemented |
| EventDeliveryClient | New | CREATE | V1-V4 implemented |
| AIWorker | New | CREATE | V1-V4 implemented |

---

## 2. Reuse Matrix

| Component | Source | Reused | Adapted | Replaced | Rationale |
|-----------|--------|--------|---------|----------|-----------|
| MediaMTX | Phase 32 | ✅ | - | - | Stable, proven |
| Legacy Backend | Phase 22-25 | ✅ | - | - | Attendance authority |
| Phase 22-25 | Phase 22-25 | ✅ | - | - | Proven resolver |
| SCRFD | Phase 7 | - | ✅ | - | GPU + IO Binding |
| ArcFace | Phase 12 | - | ✅ | - | GPU + IO Binding |
| YOLO | Phase 9 | - | ✅ | - | GPU + IO Binding |
| NVDEC | Phase 36 | - | ✅ | - | Software fallback |
| NVENC | Phase 8 | - | ⚠️ | - | Failing on GTX 1660 Ti |
| PipelineEngine | - | - | - | ✅ | New architecture |
| CameraManager | - | - | - | ✅ | Per-camera isolation |
| EventDeliveryClient | - | - | - | ✅ | Backend integration |
| AIWorker | - | - | - | ✅ | Lifecycle management |

---

## 3. Adaptation Details

### SCRFD (Phase 7 → PipelineEngine)
| Change | Detail |
|--------|--------|
| IO Binding | Added CUDA IO Binding |
| Preprocessing | GPU letterbox resize |
| Output | 5-point landmarks |
| Provider | CUDAExecutionProvider |

### ArcFace (Phase 12 → PipelineEngine)
| Change | Detail |
|--------|--------|
| IO Binding | Added CUDA IO Binding |
| Normalization | (x - 127.5) / 128.0 |
| L2 Norm | On GPU |
| Enrollment | Hot reload support |

### YOLO (Phase 9 → PipelineEngine)
| Change | Detail |
|--------|--------|
| IO Binding | Added CUDA IO Binding |
| Person Class | Class 0 only |
| Output | PersonDetection format |

### NVDEC (Phase 36 → PipelineEngine)
| Change | Detail |
|--------|--------|
| Fallback | Software decode + GPU upload |
| Reason | GTX 1660 Ti cuvid → dxva2_vld |

---

## 4. Replacement Justification

### PipelineEngine (New)
- **Replaces**: Monolithic video_pipeline_v2
- **Reason**: Per-camera isolation, GPU-first, modular

### CameraManager (New)
- **Replaces**: video_pipeline_v2 camera handling
- **Reason**: Per-camera independence, frame pool isolation

### EventDeliveryClient (New)
- **Replaces**: Legacy event submission
- **Reason**: Idempotency, retry, observability

### AIWorker (New)
- **Replaces**: Manual process management
- **Reason**: Lifecycle, health, control, enrollment watch

---

## 5. Verdict

**LEGACY REUSE/ADAPT/REPLACE: VALIDATED**

- ✅ 3 components reused (MediaMTX, Backend, Phase 22-25)
- ✅ 5 components adapted (SCRFD, ArcFace, YOLO, NVDEC, NVENC)
- ✅ 4 components created new (PipelineEngine, CameraManager, EventDeliveryClient, AIWorker)
- ✅ NVENC known limitation documented
- ✅ Zero legacy code copied without adaptation