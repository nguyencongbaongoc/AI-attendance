# Phase 36T - Production Live GPU Integration & Verification

**Timestamp:** 2026-08-27T01:49:12.057840Z
**Verdict:** NOT_READY

## Integration Point

- **Factory:** app/vision/detector_factory.py get_detector_for_live()
- **Files Modified:**

## GPU Runtime Evidence

- **detector_type:** GPUFaceDetector
- **gpu_available:** True
- **cuda_ep_used:** True
- **io_binding_active:** True
- **gpu_preprocessing_active:** True
- **provider:** CUDAExecutionProvider

## CAM1 Results

- **camera_id:** CAM1
- **rtsp_url:** rtsp://127.0.0.1:8554/live/cam1
- **frames_processed:** 30
- **detections_total:** 0
- **timestamps_monotonic:** True
- **frame_continuity:** True
- **camera_id_integrity:** False
- **health_state:** LIVE
- **queue_depth_max:** 0
- **errors:** []
- **avg_processing_ms:** 29.186603333073435
- **p50_processing_ms:** 19.32890000171028
- **p95_processing_ms:** 21.93540000007488
- **fps_estimate:** 34.262294539317914

## CAM2 Results

- **camera_id:** CAM2
- **rtsp_url:** rtsp://127.0.0.1:8554/live/cam2
- **frames_processed:** 0
- **detections_total:** 0
- **timestamps_monotonic:** False
- **frame_continuity:** False
- **camera_id_integrity:** False
- **health_state:** UNAVAILABLE
- **queue_depth_max:** 0
- **errors:** ['Failed to open RTSP source: Failed to open video: rtsp://127.0.0.1:8554/live/cam2?transport=tcp']

## FPS Measurement

- **method:** live_stream_validation
- **cam1:** {'fps': 34.262294539317914, 'avg_latency_ms': 29.186603333073435, 'p50_ms': 19.32890000171028, 'p95_ms': 21.93540000007488}
- **cam2:** {'fps': 0, 'avg_latency_ms': 0, 'p50_ms': 0, 'p95_ms': 0}
- **combined_avg_fps:** 0

## Comparison

### 36-S CPU Production Path
- AI throughput: ~7.5 FPS
- NVDEC GPU->CPU: ~36.3 ms/frame
- CPU preprocessing: ~19.2 ms/frame
- SCRFD inference: ~95 ms/frame

### 36-H GPU Validation Harness
- ~17-20 FPS per camera

### 36-T GPU Production Path
- Measured FPS: NOT_VERIFIED
- Avg latency: NOT_VERIFIED ms

## Known Limitations

- GPU available=True, CAM1 frames=30, CAM2 frames=0

## Verdict: NOT_READY
