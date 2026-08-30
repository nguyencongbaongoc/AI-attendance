# Phase 22 — IN/OUT Geometry UI & Crossing Semantics Report

**Generated:** 2026-08-21T19:40:19.466143Z
**Verdict:** FAIL

## Summary

- **Total Tests:** 34
- **Passed:** 33
- **Failed:** 1

## Key Validation Results

- **Geometry Contract:** ✅ PASS
- **ORIGINAL_FRAME Coordinates:** ✅ PASS
- **Line Serialization:** ✅ PASS
- **Zone Serialization:** ✅ PASS
- **Geometry Versioning:** ✅ PASS
- **Camera Isolation:** ✅ PASS
- **Display→Source Transform:** ✅ PASS
- **Source→Display Transform:** ✅ PASS
- **Transform Round-trip:** ✅ PASS
- **Line Side Calculation:** ✅ PASS
- **Valid IN Crossing:** ✅ PASS
- **Valid OUT Crossing:** ✅ PASS
- **Reverse Crossing:** ✅ PASS
- **Parallel Movement:** ✅ PASS
- **Line Touch (No Crossing):** ✅ PASS
- **Jitter/Hysteresis:** ✅ PASS
- **Debounce:** ✅ PASS
- **Multiple Crossings:** ✅ PASS
- **Stationary Person:** ✅ PASS
- **Missing Samples:** ✅ PASS
- **Out-of-Order Timestamps:** ✅ PASS
- **Zone Entry (Outside→Inside):** ✅ PASS
- **Zone Exit (Inside→Outside):** ✅ PASS
- **Ambiguous Identity:** ✅ PASS
- **Phase 21 Integration:** ✅ PASS
- **Provenance:** ✅ PASS
- **Deterministic Replay:** ✅ PASS
- **Bounded Memory:** ✅ PASS
- **Multi-Camera Isolation:** ❌ FAIL
- **Config Save/Reload:** ✅ PASS
- **Negative Tests:** ✅ PASS
- **N-Camera Architecture:** ✅ PASS

## Detailed Test Results

### ✅ test_geometry_contract_exists
**Message:** CameraGeometryConfig contract exists and is valid
**Duration:** 0.30 ms
**Details:**
  - line_config_hash: e0da1b509d3357c8
  - zone_config_hash: b282861df1ffa68c

### ✅ test_original_frame_coordinates
**Message:** All geometry operates in ORIGINAL_FRAME coordinates
**Duration:** 0.12 ms
**Details:**
  - coordinate_space: original_frame

### ✅ test_line_serialization
**Message:** Line geometry serializes and deserializes correctly
**Duration:** 0.13 ms
**Details:**
  - config_hash: 722373a80441116c

### ✅ test_zone_serialization
**Message:** Zone geometry serializes and deserializes correctly
**Duration:** 0.17 ms
**Details:**
  - config_hash: 46b7d0114585f93c

### ✅ test_geometry_versioning
**Message:** Geometry versioning works correctly
**Duration:** 0.15 ms
**Details:**
  - v1_hash: e0da1b509d3357c8
  - v2_hash: 2187b2fc3e8ab6d5

### ✅ test_camera_isolation
**Message:** Camera geometries are properly isolated
**Duration:** 0.13 ms
**Details:**
  - cam1_line_x: 1000
  - cam2_line_x: 2000

### ✅ test_display_to_source_transform
**Message:** Display to source transform works correctly
**Duration:** 0.05 ms
**Details:**
  - scale: 0.5
  - offset_x: 0.0
  - offset_y: 0.0

### ✅ test_source_to_display_transform
**Message:** Source to display transform works correctly
**Duration:** 0.03 ms
**Details:**
  - scale: 0.5

### ✅ test_transform_round_trip
**Message:** Coordinate round-trip is accurate within tolerance
**Duration:** 2.12 ms
**Details:**
  - max_error: 0.0
  - tests: 100

### ✅ test_line_side_calculation
**Message:** Line side calculation works correctly
**Duration:** 0.08 ms

### ✅ test_valid_in_crossing
**Message:** Valid IN crossing detected correctly
**Duration:** 0.30 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - crossing_point: {'x': 1000.0, 'y': 1080.0}

### ✅ test_valid_out_crossing
**Message:** Valid OUT crossing detected correctly
**Duration:** 0.24 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - direction: out

### ✅ test_reverse_crossing
**Message:** Reverse crossings detected correctly
**Duration:** 0.42 ms
**Details:**
  - events: ['in', 'out', 'in']

### ✅ test_parallel_movement
**Message:** Parallel movement does not trigger crossing
**Duration:** 0.22 ms
**Details:**
  - events: 0

### ✅ test_line_touch_without_crossing
**Message:** Line touch without crossing does not trigger event
**Duration:** 0.16 ms
**Details:**
  - events: 0

### ✅ test_jitter_hysteresis
**Message:** Jitter around line is suppressed by hysteresis
**Duration:** 0.41 ms
**Details:**
  - jitter_events: 0
  - crossing_events: 1

### ✅ test_debounce
**Message:** Temporal debounce prevents rapid crossing events
**Duration:** 0.43 ms
**Details:**
  - events: 2
  - directions: ['in', 'out']

### ✅ test_multiple_crossings
**Message:** Multiple crossings tracked correctly
**Duration:** 0.56 ms
**Details:**
  - crossings: 5
  - sequence: ['in', 'out', 'in', 'out', 'in']

### ✅ test_stationary_person
**Message:** Stationary person does not trigger crossing
**Duration:** 0.49 ms
**Details:**
  - frames: 20
  - events: 0

### ✅ test_missing_trajectory_samples
**Message:** Missing trajectory samples handled correctly
**Duration:** 0.28 ms
**Details:**
  - events: 2
  - gap_handling: within_limit_then_exceeds

### ✅ test_out_of_order_timestamps
**Message:** Out-of-order timestamps handled without crash
**Duration:** 0.27 ms
**Details:**
  - events: 2

### ✅ test_zone_outside_to_inside
**Message:** Zone entry (outside→inside) detected correctly
**Duration:** 0.33 ms
**Details:**
  - event_type: zone_entry
  - direction: in

### ✅ test_zone_inside_to_outside
**Message:** Zone exit (inside→outside) detected correctly
**Duration:** 0.32 ms
**Details:**
  - event_type: zone_exit
  - direction: out

### ✅ test_ambiguous_identity_crossing
**Message:** Crossing detection works with unknown/ambiguous identity
**Duration:** 0.46 ms
**Details:**
  - unknown_id_events: 1
  - ambiguous_id_events: 1

### ✅ test_phase21_global_observation_integration
**Message:** Phase 21 GlobalObservation integrates with crossing detection
**Duration:** 0.39 ms
**Details:**
  - global_obs_id: GO-cd5c724c3b44
  - event_go_id: GO-cd5c724c3b44

### ✅ test_provenance
**Message:** Crossing event preserves full provenance
**Duration:** 0.22 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - config_hash: d37ed85cbd8a8481

### ✅ test_deterministic_replay
**Message:** Crossing detection is deterministic across runs
**Duration:** 1.15 ms
**Details:**
  - runs: 5
  - events_per_run: 2

### ✅ test_bounded_trajectory_memory
**Message:** Trajectory history is bounded
**Duration:** 8.91 ms
**Details:**
  - max_history: 10
  - actual_history: 10

### ❌ Multi-camera geometry isolation
**Message:** Test exception: 
**Duration:** 0.25 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_configuration_save_reload
**Message:** Configuration save/reload works correctly
**Duration:** 18.19 ms
**Details:**
  - config_hash: e0da1b509d3357c8

### ✅ test_negative_invalid_geometry
**Message:** Invalid geometry configurations rejected
**Duration:** 0.08 ms

### ✅ test_invalid_coordinate_space
**Message:** Invalid coordinate space rejected
**Duration:** 0.14 ms

### ✅ test_invalid_frame_dimensions
**Message:** Invalid frame dimensions rejected
**Duration:** 0.06 ms

### ✅ test_n_camera_architecture
**Message:** Architecture supports N cameras (tested with 5)
**Duration:** 0.31 ms
**Details:**
  - cameras: 5
  - camera_ids: ['CAM1', 'CAM2', 'CAM3', 'CAM4', 'CAM5']

## Limitations

- Tests use synthetic trajectories (no real video)
- Phase 21 integration uses minimal GlobalObservation
- UI rendering not tested (headless)

## Phase 23 Readiness

**Ready:** No
