# Phase 31 — Offline Full End-to-End Gate Report

**Generated:** 2026-08-23T15:43:42.308837Z
**Verdict:** FAIL

## Summary

- **Total Pytest Suites:** 27
- **Pytest Passed:** 26
- **Pytest Failed:** 1
- **Total Acceptance Checks:** 5
- **Checks Passed:** 4
- **Checks Failed:** 1
- **Total Duration:** 144.95s

## Acceptance Checks

- **test_data_fixtures:** ✓ PASS
  - Details: CAM1: True, CAM2: True

- **enrollment_database:** ✓ PASS
  - Details: embeddings.npy: True, metadata: True

- **phase30a_report:** ✓ PASS
  - Details: Report exists: True

- **key_source_files:** ✓ PASS
  - Details: All 11 key files present: True

- **previous_benchmarks:** ✗ FAIL
  - Details: All 10 benchmark files present: False

## Pytest Results

- **phase31_integration:** ✗ FAIL
  - Exit Code: 1
  - Duration: 0.00s

- **phase_27_replay_annotation:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_27_video_evidence:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_25_attendance_contract:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_25_attendance_repository:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_30_daily_excel_contract:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_30_daily_excel_exporter:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_29_immediate_event_contract:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_29_event_publisher:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_29_event_adapters:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_23_raw_in_out_event:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_24_repeated_in_out:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_13_enrollment:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_14_matching:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_15_hard_pose:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_15_face_detection:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_16_face_crop:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_17_face_quality:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_11_tracking:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_18_association:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_23_integration:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_24_integration:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_25_integration:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_27_replay:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_29_integration:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **phase_30a_deliverables:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

- **attendance_integration:** ✓ PASS
  - Exit Code: 0
  - Duration: 0.00s

## Pipeline Verification

### Replay (Phase 20)
- **Status:** ✗ NOT VERIFIED

### CAM1
- **Status:** ✗ NOT VERIFIED

### CAM2
- **Status:** ✗ NOT VERIFIED

### Phase 15-19 Chain
- **Status:** ✗ NOT VERIFIED

### Phase 21 Fusion
- **Status:** ✗ NOT VERIFIED

### Phase 22 Geometry
- **Status:** ✗ NOT VERIFIED

### Phase 23 Raw Events
- **Status:** ✗ NOT VERIFIED

### Phase 24 Resolution
- **Status:** ✗ NOT VERIFIED

### Phase 25 Persistence
- **Status:** ✗ NOT VERIFIED

### Phase 26 Attendance Engine
- **Status:** ✗ NOT VERIFIED

### Phase 27 Evidence
- **Status:** ✗ NOT VERIFIED

### Phase 29 Immediate Output
- **Status:** ✗ NOT VERIFIED

### Phase 30 Excel Export
- **Status:** ✗ NOT VERIFIED

## Provenance Chain
- **Status:** ✗ NOT VERIFIED

## Determinism Gate
- **Status:** ✗ NOT VERIFIED

## Idempotency Gate
- **Status:** ✗ NOT VERIFIED

## Negative Cases
- **Status:** ✗ NOT VERIFIED

## Bounded Memory
- **Status:** ✗ NOT VERIFIED

## Known Limitations

- IDENTITY DISCRIMINATION: NOT VERIFIED — SYNTHETIC TEST DATA (Phase 30A limitation)
- Phase 19 matcher returns AMBIGUOUS for synthetic identical embeddings (expected behavior)
- Video evidence extraction requires ffmpeg binary (not tested in offline gate)
- Cross-camera geometry calibration not available (geometry_compatible=None in fusion)
- Person detection not integrated in replay pipeline (face-only path used)

## Phase 32 Readiness: ✗ NOT READY
