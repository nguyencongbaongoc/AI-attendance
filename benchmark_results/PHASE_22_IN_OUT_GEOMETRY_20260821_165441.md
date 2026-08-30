# Phase 22 — IN/OUT Geometry UI & Crossing Semantics Report

**Generated:** 2026-08-21T16:54:41.040368Z
**Verdict:** FAIL

## Summary

- **Total Tests:** 34
- **Passed:** 25
- **Failed:** 9

## Key Validation Results

- **Geometry Contract:** ✅ PASS
- **ORIGINAL_FRAME Coordinates:** ✅ PASS
- **Line Serialization:** ✅ PASS
- **Zone Serialization:** ✅ PASS
- **Geometry Versioning:** ❌ FAIL
- **Camera Isolation:** ✅ PASS
- **Display→Source Transform:** ✅ PASS
- **Source→Display Transform:** ✅ PASS
- **Transform Round-trip:** ✅ PASS
- **Line Side Calculation:** ❌ FAIL
- **Valid IN Crossing:** ✅ PASS
- **Valid OUT Crossing:** ✅ PASS
- **Reverse Crossing:** ❌ FAIL
- **Parallel Movement:** ✅ PASS
- **Line Touch (No Crossing):** ❌ FAIL
- **Jitter/Hysteresis:** ❌ FAIL
- **Debounce:** ❌ FAIL
- **Multiple Crossings:** ❌ FAIL
- **Stationary Person:** ✅ PASS
- **Missing Samples:** ❌ FAIL
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
**Duration:** 0.15 ms
**Details:**
  - config_hash: 46b7d0114585f93c

### ❌ Geometry versioning
**Message:** Test exception: 
**Duration:** 0.11 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_camera_isolation
**Message:** Camera geometries are properly isolated
**Duration:** 0.14 ms
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
**Duration:** 3.01 ms
**Details:**
  - max_error: 0.0
  - tests: 100

### ❌ Line side calculation
**Message:** Test exception: 
**Duration:** 0.08 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_valid_in_crossing
**Message:** Valid IN crossing detected correctly
**Duration:** 0.37 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - crossing_point: {'x': 1000.0, 'y': 1080.0}

### ✅ test_valid_out_crossing
**Message:** Valid OUT crossing detected correctly
**Duration:** 0.26 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - direction: out

### ❌ Reverse crossing
**Message:** Test exception: 
**Duration:** 0.26 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_parallel_movement
**Message:** Parallel movement does not trigger crossing
**Duration:** 0.21 ms
**Details:**
  - events: 0

### ❌ Line touch without crossing
**Message:** Test exception: name 'CrossingPolicy' is not defined
**Duration:** 0.01 ms
**Details:**
  - exception: name 'CrossingPolicy' is not defined
  - type: NameError

### ❌ Jitter/hysteresis
**Message:** Test exception: Frame 1: Jitter should not trigger crossing
**Duration:** 0.25 ms
**Details:**
  - exception: Frame 1: Jitter should not trigger crossing
  - type: AssertionError

### ❌ Debounce
**Message:** Test exception: 
**Duration:** 0.17 ms
**Details:**
  - exception: 
  - type: AssertionError

### ❌ Multiple crossings
**Message:** Test exception: 
**Duration:** 0.49 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_stationary_person
**Message:** Stationary person does not trigger crossing
**Duration:** 0.50 ms
**Details:**
  - frames: 20
  - events: 0

### ❌ Missing trajectory samples
**Message:** Test exception: 
**Duration:** 0.24 ms
**Details:**
  - exception: 
  - type: AssertionError

### ✅ test_out_of_order_timestamps
**Message:** Out-of-order timestamps handled without crash
**Duration:** 0.25 ms
**Details:**
  - events: 1

### ✅ test_zone_outside_to_inside
**Message:** Zone entry (outside→inside) detected correctly
**Duration:** 0.33 ms
**Details:**
  - event_type: zone_entry
  - direction: in

### ✅ test_zone_inside_to_outside
**Message:** Zone exit (inside→outside) detected correctly
**Duration:** 0.34 ms
**Details:**
  - event_type: zone_exit
  - direction: out

### ✅ test_ambiguous_identity_crossing
**Message:** Crossing detection works with unknown/ambiguous identity
**Duration:** 0.31 ms
**Details:**
  - unknown_id_events: 1
  - ambiguous_id_events: 1

### ✅ test_phase21_global_observation_integration
**Message:** Phase 21 GlobalObservation integrates with crossing detection
**Duration:** 0.64 ms
**Details:**
  - global_obs_id: GO-cd5c724c3b44
  - event_go_id: GO-cd5c724c3b44

### ✅ test_provenance
**Message:** Crossing event preserves full provenance
**Duration:** 0.24 ms
**Details:**
  - event_id: CE-LI-4a40f72e27
  - config_hash: d37ed85cbd8a8481

### ✅ test_deterministic_replay
**Message:** Crossing detection is deterministic across runs
**Duration:** 1.24 ms
**Details:**
  - runs: 5
  - events_per_run: 1

### ✅ test_bounded_trajectory_memory
**Message:** Trajectory history is bounded
**Duration:** 8.25 ms
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
**Duration:** 17.92 ms
**Details:**
  - config_hash: e0da1b509d3357c8

### ✅ test_negative_invalid_geometry
**Message:** Invalid geometry configurations rejected
**Duration:** 0.13 ms

### ✅ test_invalid_coordinate_space
**Message:** Invalid coordinate space rejected
**Duration:** 0.34 ms

### ✅ test_invalid_frame_dimensions
**Message:** Invalid frame dimensions rejected
**Duration:** 0.09 ms

### ✅ test_n_camera_architecture
**Message:** Architecture supports N cameras (tested with 5)
**Duration:** 0.33 ms
**Details:**
  - cameras: 5
  - camera_ids: ['CAM1', 'CAM2', 'CAM3', 'CAM4', 'CAM5']

## Limitations

- Tests use synthetic trajectories (no real video)
- Phase 21 integration uses minimal GlobalObservation
- UI rendering not tested (headless)

## Phase 23 Readiness

**Ready:** No
