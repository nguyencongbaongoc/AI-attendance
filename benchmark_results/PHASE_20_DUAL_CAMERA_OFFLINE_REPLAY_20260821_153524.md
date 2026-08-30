# Phase 20 — Dual-Camera Offline Replay Report

**Generated:** 2026-08-21T15:35:24.207234Z
**Verdict:** PASS

## Summary

- **Total Tests:** 22
- **Passed:** 22
- **Failed:** 0

## Camera Frame Counts

- **CAM1 Total Frames:** 30
- **CAM1 Processed Frames:** 30
- **CAM2 Total Frames:** 25
- **CAM2 Processed Frames:** 25

## Key Validation Results

- **Timestamp Ordering:** ✅ PASS
- **Deterministic Replay:** ✅ PASS
- **Camera Isolation:** ✅ PASS
- **Provenance Preserved:** ✅ PASS
- **Bounded Memory:** ✅ PASS
- **N-Camera Architecture:** ✅ PASS

## Integration Gates (Phase 15-19)

- **test_phase15_integration:** ✅ PASS
- **test_phase16_integration:** ✅ PASS
- **test_phase17_integration:** ✅ PASS
- **test_phase18_integration:** ✅ PASS
- **test_phase19_integration:** ✅ PASS

## Detailed Test Results

### ✅ test_replay_clock
**Message:** ReplayClock generates deterministic timestamps
**Duration:** 0.06 ms
**Details:**
  - timestamps: [0.0, 0.03333333333333333, 0.06666666666666667]

### ✅ test_valid_source_opens
**Message:** Valid video sources open correctly
**Duration:** 54.11 ms
**Details:**
  - cam1_frames: 30
  - cam2_frames: 25
  - cam1_fps: 30.0
  - cam2_fps: 25.0

### ✅ test_canonical_frame_reused
**Message:** Replay produces CanonicalFrame with camera_id and replay metadata
**Duration:** 26.34 ms
**Details:**
  - frames_checked: 5

### ✅ test_replay_manifest
**Message:** ReplayManifest creates, serializes, and loads correctly
**Duration:** 30.59 ms
**Details:**
  - replay_id: replay_387c30878391
  - num_sources: 2

### ✅ test_dual_camera_scheduling
**Message:** Dual-camera scheduler orders frames by timestamp
**Duration:** 95.24 ms
**Details:**
  - cam1_frames: 30
  - cam2_frames: 25
  - total_frames: 55
  - timestamp_ordered: True

### ✅ test_timestamp_ordering
**Message:** Frames are correctly ordered by replay timestamp
**Duration:** 81.05 ms
**Details:**
  - total_frames: 35
  - violations: 0

### ✅ test_camera_isolation
**Message:** Camera namespaces remain isolated
**Duration:** 95.72 ms
**Details:**
  - cam1_frame_indices: [0, 1, 2, 3, 4]
  - cam2_frame_indices: [0, 1, 2, 3, 4]

### ✅ test_early_camera_termination
**Message:** Early camera termination handled correctly
**Duration:** 77.23 ms
**Details:**
  - cam1_frames: 10
  - cam2_frames: 25
  - cam1_exhausted_at_cam2_frame: 9

### ✅ test_invalid_source_handling
**Message:** Invalid sources handled with ReplaySourceError
**Duration:** 556.28 ms
**Details:**
  - corrupt_opened: False
  - empty_opened: False
  - missing_opened: False

### ✅ test_deterministic_replay
**Message:** Replay is deterministic across runs
**Duration:** 193.41 ms
**Details:**
  - sequence_length: 55

### ✅ test_bounded_memory
**Message:** Scheduler respects bounded memory limits
**Duration:** 99.19 ms
**Details:**
  - max_global_buffer: 19
  - max_cam1_buffer: 4
  - max_cam2_buffer: 4

### ✅ test_provenance_preserved
**Message:** Provenance chain preserved from source through replay
**Duration:** 28.95 ms
**Details:**
  - chain_length: 3
  - sample: {'camera_id': 'CAM1', 'source_id': 'C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance\\test_data\\phase20\\cam1_test.mp4', 'frame_index': 0, 'timestamp': 0.0, 'replay_timestamp': {'value': 0.0, 'source': 'frame_index_fps'}, 'replay_frame_index': 0}

### ✅ test_phase15_integration
**Message:** Phase 15 Face Detection contract composes correctly
**Duration:** 3562.05 ms
**Details:**
  - frames_processed: 10
  - detections_found: 846

### ✅ test_phase16_integration
**Message:** Phase 16 Adaptive Crop contract composes correctly
**Duration:** 2843.34 ms
**Details:**
  - frames_processed: 10
  - face_crops_produced: 846

### ✅ test_phase17_integration
**Message:** Phase 17 Face Quality contract composes correctly
**Duration:** 3244.00 ms
**Details:**
  - frames_processed: 10
  - quality_results: 846

### ✅ test_phase18_integration
**Message:** Phase 18 Temporal Evidence contract composes correctly
**Duration:** 3285.10 ms
**Details:**
  - frames_processed: 10
  - hypotheses: 10

### ✅ test_phase19_integration
**Message:** Phase 19 Matching Calibration contract composes correctly
**Duration:** 13.18 ms
**Details:**
  - calibration_status: not_calibrated
  - threshold: 0.4

### ✅ test_cam1_actual_frames
**Message:** CAM1 decodes and processes actual frames
**Duration:** 41.57 ms
**Details:**
  - total_frames: 30
  - processed_frames: 30

### ✅ test_cam2_actual_frames
**Message:** CAM2 decodes and processes actual frames
**Duration:** 33.46 ms
**Details:**
  - total_frames: 25
  - processed_frames: 25

### ✅ test_dual_camera_e2e
**Message:** Dual-camera E2E replay with pipeline works
**Duration:** 10732.76 ms
**Details:**
  - cam1_processed: 10
  - cam2_processed: 25
  - total_pipeline_results: 35

### ✅ test_n_camera_architecture
**Message:** Architecture supports N cameras (tested with 3)
**Duration:** 114.96 ms
**Details:**
  - CAM1: 10
  - CAM2: 25
  - CAM3: 10

### ✅ test_offline_dependency_safety
**Message:** No live/streaming dependencies in replay modules
**Duration:** 7.64 ms
**Details:**
  - modules_checked: 5

## Limitations

- Test videos are synthetic (640x480, no real faces)
- Phase 14/19 matching not fully exercised (no enrollment DB)
- Person detection (YOLO) not integrated in pipeline
- ArcFace inference not integrated in pipeline

## Phase 21 Readiness

**Ready:** Yes
