# Phase 36K - Maximum Performance Forensic Baseline

**Timestamp:** 2026-08-26T19:38:57.149068Z
**Hardware:** GTX 1660 Ti 6GB, i5-11400F, 16GB

## Baseline Benchmarks

### A_scrfd_only
- **Camera Config:** SYNTHETIC
- **Frames:** 50
- **FPS:** 22.91
- **Avg Latency:** 43.6ms
- **P50 Latency:** 36.8ms
- **P95 Latency:** 77.9ms
- **P99 Latency:** 85.7ms
- **Max Latency:** 85.7ms
- **GPU Utilization:** 19.5%
- **VRAM Peak:** 1422MB

### B_gpu_face_detector_only
- **Camera Config:** SYNTHETIC
- **Frames:** 50
- **FPS:** 24.25
- **Avg Latency:** 41.2ms
- **P50 Latency:** 34.1ms
- **P95 Latency:** 74.7ms
- **P99 Latency:** 77.2ms
- **Max Latency:** 77.2ms

### C_full_pipeline_cam1
- **Camera Config:** CAM1
- **Frames:** 30
- **FPS:** 16.02
- **Avg Latency:** 62.4ms
- **P50 Latency:** 55.5ms
- **P95 Latency:** 97.7ms
- **P99 Latency:** 99.2ms
- **Max Latency:** 99.2ms
- **GPU Utilization:** 25.1%
- **VRAM Peak:** 2053MB
- **System Memory Peak:** 1706MB

### D_full_pipeline_cam2
- **Camera Config:** CAM2
- **Frames:** 30
- **FPS:** 19.45
- **Avg Latency:** 51.4ms
- **P50 Latency:** 37.9ms
- **P95 Latency:** 78.0ms
- **P99 Latency:** 335.7ms
- **Max Latency:** 335.7ms
- **GPU Utilization:** 29.3%
- **VRAM Peak:** 1790MB
- **System Memory Peak:** 1707MB

### E_full_pipeline_cam1_cam2_serialized
- **Camera Config:** CAM1+CAM2
- **Frames:** 60
- **FPS:** 20.04
- **Avg Latency:** 49.9ms
- **P50 Latency:** 40.6ms
- **P95 Latency:** 106.4ms
- **P99 Latency:** 135.3ms
- **Max Latency:** 135.3ms
- **GPU Utilization:** 32.8%
- **VRAM Peak:** 2032MB
- **System Memory Peak:** 2086MB

## Comparison with Previous Phases

- **36T Detector CAM1:** 14.85 FPS
- **36T Detector CAM2:** 17.90 FPS
- **36R5 Full Pipeline:** 7.25 FPS/camera

## Current Baseline Results

- **A. SCRFD-only:** 22.91 FPS
- **B. GPUFaceDetector-only (staged):** 24.25 FPS
- **C. Full Pipeline CAM1:** 16.02 FPS
- **D. Full Pipeline CAM2:** 19.45 FPS
- **E. Full Pipeline CAM1+CAM2 (serialized):** 20.04 FPS

## Gap Analysis

- **Detector vs Full Pipeline (CAM1):** 14.85 vs 16.02 FPS = 0.9x slower
- **Detector vs Full Pipeline (CAM2):** 17.90 vs 19.45 FPS = 0.9x slower
