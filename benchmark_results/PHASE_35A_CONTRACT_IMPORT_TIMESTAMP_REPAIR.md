# Phase 35A — Contract / Import Repair & Timestamp Precision

**Timestamp:** 2026-08-24T17:21:19.034000Z
**Verdict:** PASS WITH DOCUMENTED LIMITATION

## Summary

- **Total Pytest Suites:** 11
- **Pytest Passed:** 11
- **Pytest Failed:** 0
- **Total Acceptance Checks:** 12
- **Checks Verified:** 11
- **Checks Not Verified:** 1
- **LIVE_RUNTIME_VERIFIED:** 7
- **OFFLINE_VERIFIED:** 4
- **NOT_VERIFIED:** 1
- **Total Duration:** 85.70s

## Root Causes

| Issue | Root Cause | Fix |
|-------|------------|-----|
| **immediate_event** | Phase 35 script used non-existent `EventType` enum and incorrect `ImmediateEvent` constructor fields (`timestamp` vs `event_timestamp`, `payload` field) | Fixed by using `ImmediateEventType` enum and correct constructor fields |
| **backpressure** | Same `EventType` issue plus incorrect `ImmediateEvent` construction | Fixed by using `ImmediateEventType.RAW_IN` and proper constructor |
| **determinism_idempotency** | Missing import for `AttendanceDecisionContext` from `app.attendance.engine` | Fixed by adding import |
| **timestamp_fps_precision** | CAM1 reported 90000 FPS due to RTSP source using frame_index/FPS fallback instead of wall-clock timestamps for live streams | Fixed `RTSPSource` to use wall-clock receive time for live streams |
| **replay** | Phase 35 script referenced non-existent `VideoEvidenceCapture` and `VideoEvidenceConfig` classes | Fixed by using canonical `VideoEvidenceRetriever`, `VideoSourceInfo`, `VideoSegmentRequest`, `VideoSegmentResult` classes |
| **real_failure_recovery** | Requires controlled RTMP publisher stop/restart which could disrupt live infrastructure | Not performed to avoid damaging MediaMTX configuration |

## Files Changed

- `scripts/phase35_realtime_e2e.py`
- `scripts/phase35_realtime_performance.py`
- `app/streaming/rtsp_source.py`

## Contract / API Repairs

### immediate_event
- Fixed `EventType` → `ImmediateEventType` enum usage
- Added required `direction`, `identity_certainty`, `source_raw_event_id` fields
- Changed `timestamp` to `event_timestamp`

### backpressure
- Fixed `EventType` → `ImmediateEventType` enum usage
- Corrected `ImmediateEvent` constructor

### determinism_idempotency
- Added `AttendanceDecisionContext` import from `app.attendance.engine`

### replay
- Fixed imports to use canonical `VideoEvidenceRetriever`, `VideoSourceInfo`, `VideoSegmentRequest`, `VideoSegmentResult`

## Timestamp / FPS Precision Repair

### Problem
CAM1 reported 90000 FPS due to timestamp precision issue - RTSP source used frame_index/FPS fallback (1/30 = 0.033s) but frame_index was not incrementing properly, causing near-zero intervals.

### Solution
Modified `RTSPSource.get_next_frame()` to use wall-clock receive time for live streams, initializing `_start_time` on first frame and computing `live_timestamp = frame_receive_time - _start_time`.

### Result
- CAM1 now reports ~4.6-5.1 FPS (realistic for live stream processing)
- CAM2 reports ~4.7-5.1 FPS
- Both cameras now use same measurement semantics (wall-clock based)
- Frame continuity and timestamp monotonicity now verified

## Replay Repair Status
Fixed imports to use canonical Phase 27 video evidence classes. `VideoEvidenceRetriever` now available and verified.

## Backpressure Repair Status
Verified DROP_OLDEST policy works correctly with bounded queues, history, and deduplication cache.

## Determinism / Idempotency Repair Status
`AttendanceDecisionContext` import fixed. Attendance engine idempotency verified - same inputs produce same `decision_id`.

## Real CAM1/CAM2 Measurements

### CAM1
- Frames Received: 30
- Duration: 8.24s
- Observed FPS: 4.63
- Inference Latency (mean): 197.01ms
- Frame Interval Mean: 0.219s
- Frame Continuity: ✓
- Timestamp Monotonicity: ✓
- Camera ID Integrity: ✓

### CAM2
- Frames Received: 30
- Duration: 8.20s
- Observed FPS: 4.74
- Inference Latency (mean): 192.59ms
- Frame Interval Mean: 0.214s
- Frame Continuity: ✓
- Timestamp Monotonicity: ✓
- Camera ID Integrity: ✓

### Dual Camera
- Simultaneous Operation: ✓

## Live Verification Classification

### LIVE_RUNTIME_VERIFIED (7)
- performance_baseline
- performance_invariants
- attendance
- immediate_event
- replay
- backpressure
- determinism_idempotency

### OFFLINE_VERIFIED (4)
- cross_camera
- in_out_events
- live_ui
- recovery

### NOT_VERIFIED (1)
- real_failure_recovery

## Regression Results
All Phase 20-34 regression tests PASS:
- Phase 32 Streaming Contracts: PASS
- Phase 32 MediaMTX Config: PASS
- Phase 33 Health Events: PASS
- Phase 33 Health Monitor: PASS
- Phase 31 Offline Full E2E: PASS
- Phase 23 Integration: PASS
- Phase 24 Integration: PASS
- Phase 27 Replay: PASS
- Phase 29 Integration: PASS
- Phase 30A Deliverables: PASS
- Attendance Integration: PASS

## Remaining NOT_VERIFIED Items

| Item | Reason |
|------|--------|
| real_failure_recovery | Requires controlled RTMP publisher stop/restart which could disrupt live infrastructure. Not performed to avoid damaging MediaMTX configuration. Health monitor failure isolation and recovery verified offline. |

## Phase 36 Readiness: READY

## Artifacts
- `scripts/phase35_realtime_performance.py`
- `scripts/phase35_realtime_e2e.py`
- `tests/unit/test_phase35_performance.py`
- `tests/integration/test_phase35_realtime_e2e.py`
- `benchmark_results/PHASE_35_REALTIME_PERFORMANCE.json`
- `benchmark_results/PHASE_35_REALTIME_PERFORMANCE.md`
- `benchmark_results/PHASE_35A_CONTRACT_IMPORT_TIMESTAMP_REPAIR.json`
- `benchmark_results/PHASE_35A_CONTRACT_IMPORT_TIMESTAMP_REPAIR.md`