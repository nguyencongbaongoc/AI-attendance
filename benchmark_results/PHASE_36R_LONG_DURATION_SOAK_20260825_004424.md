# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T00:44:24.317570Z
**Verdict:** FAIL
**Configured Soak Duration:** 0.1 minutes
**Configured Warm-up:** 5.0 seconds
**Actual Duration:** 1.86 minutes
**Startup Duration:** 9.04 seconds
**Warm-up Duration:** 5.00 seconds
**Soak Duration:** 6.00 seconds
**First Live Timestamp:** 2026-08-25T07:42:41.660195Z
**Start:** 2026-08-25T07:42:32.618554Z
**End:** 2026-08-25T07:44:24.316497Z
**Termination Reason:** completed
**Soak Completed:** True
**Camera States:** CAM1=LIVE, CAM2=LIVE
**Memory Growth Threshold:** 20.0%

## Verification Classification (SOAK Phase - Critical)

### CAM1 (SOAK)
- **frame_continuity**: ✗ NOT_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### CAM2 (SOAK)
- **frame_continuity**: ✗ NOT_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### Cross-Camera (Overall)
- **contamination**: ✓ LIVE_RUNTIME_VERIFIED

### System Resources (SOAK)
- **memory_stability**: ✗ NOT_VERIFIED

### Event Bus
- **boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### Regression
- **regression**: ✗ NOT_VERIFIED

### Determinism
- **idempotency**: ✓ LIVE_RUNTIME_VERIFIED

## Verification Classification (Startup/Warm-up - Informational)

### CAM1 (Startup/Warm-up)
#### STARTUP
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

#### WARMUP
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### CAM2 (Startup/Warm-up)
#### STARTUP
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

#### WARMUP
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

## CAM1 STARTUP Metrics

- **Duration:** 49.18s
- **Total Frames:** 0
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.0000s
- **P95 Frame Interval:** 0.0000s
- **P99 Frame Interval:** 0.0000s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 1
- **Total Unhealthy Duration:** 9.04s
- **Longest Unhealthy Interval:** 9.04s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 0.00ms
- **Inference Latency Median:** 0.00ms
- **Inference Latency P95:** 0.00ms
- **Inference Latency P99:** 0.00ms
- **Inference Latency Max:** 0.00ms
- **Processing FPS Mean:** 0.00
- **Processing FPS Min:** 0.00
- **Processing FPS Max:** 0.00
- **Source FPS Mean:** 0.00

## CAM1 WARMUP Metrics

- **Duration:** 39.51s
- **Total Frames:** 10
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.4756s
- **P95 Frame Interval:** 0.5298s
- **P99 Frame Interval:** 0.5343s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 273.15ms
- **Inference Latency Median:** 275.28ms
- **Inference Latency P95:** 317.16ms
- **Inference Latency P99:** 320.46ms
- **Inference Latency Max:** 321.29ms
- **Processing FPS Mean:** 1.79
- **Processing FPS Min:** 1.17
- **Processing FPS Max:** 1.93
- **Source FPS Mean:** 2.19

## CAM1 SOAK Metrics

- **Duration:** 34.74s
- **Total Frames:** 188
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 77
- **Mean Frame Interval:** 0.5175s
- **P95 Frame Interval:** 0.5197s
- **P99 Frame Interval:** 1.4198s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 260.77ms
- **Inference Latency Median:** 260.00ms
- **Inference Latency P95:** 303.59ms
- **Inference Latency P99:** 323.65ms
- **Inference Latency Max:** 331.66ms
- **Processing FPS Mean:** 1.97
- **Processing FPS Min:** 1.93
- **Processing FPS Max:** 1.99
- **Source FPS Mean:** 2.00

## CAM2 STARTUP Metrics

- **Duration:** 49.18s
- **Total Frames:** 0
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.0000s
- **P95 Frame Interval:** 0.0000s
- **P99 Frame Interval:** 0.0000s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 0.00ms
- **Inference Latency Median:** 0.00ms
- **Inference Latency P95:** 0.00ms
- **Inference Latency P99:** 0.00ms
- **Inference Latency Max:** 0.00ms
- **Processing FPS Mean:** 0.00
- **Processing FPS Min:** 0.00
- **Processing FPS Max:** 0.00
- **Source FPS Mean:** 0.00

## CAM2 WARMUP Metrics

- **Duration:** 39.76s
- **Total Frames:** 10
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.5029s
- **P95 Frame Interval:** 0.5339s
- **P99 Frame Interval:** 0.5362s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 291.63ms
- **Inference Latency Median:** 270.82ms
- **Inference Latency P95:** 385.93ms
- **Inference Latency P99:** 439.30ms
- **Inference Latency Max:** 452.64ms
- **Processing FPS Mean:** 1.81
- **Processing FPS Min:** 1.21
- **Processing FPS Max:** 1.93
- **Source FPS Mean:** 1.99

## CAM2 SOAK Metrics

- **Duration:** 34.78s
- **Total Frames:** 185
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 77
- **Mean Frame Interval:** 0.5247s
- **P95 Frame Interval:** 0.5346s
- **P99 Frame Interval:** 0.8994s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 288.88ms
- **Inference Latency Median:** 287.16ms
- **Inference Latency P95:** 360.88ms
- **Inference Latency P99:** 367.90ms
- **Inference Latency Max:** 376.30ms
- **Processing FPS Mean:** 1.98
- **Processing FPS Min:** 1.93
- **Processing FPS Max:** 2.00
- **Source FPS Mean:** 2.00

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

### Overall
- **Initial RSS:** 866.45 MB
- **Final RSS:** 1860.47 MB
- **Min RSS:** 866.45 MB
- **Max RSS:** 1860.47 MB
- **Mean RSS:** 1684.61 MB
- **Absolute Growth:** 994.02 MB
- **Percentage Growth:** 114.72%
- **Linear Slope:** 85.3530 MB/sample
- **Mean CPU:** 504.74%
- **Max CPU:** 831.10%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 7.50%
- **Max GPU Memory:** 1208.86 MB

### By Phase
#### WARMUP
- **Samples:** 1
- **Initial RSS:** 866.45 MB
- **Final RSS:** 866.45 MB
- **Absolute Growth:** 0.00 MB
- **Percentage Growth:** 0.00%
- **Linear Slope:** 0.0000 MB/sample
- **Mean CPU:** 525.60%
- **Max CPU:** 525.60%

#### SOAK
- **Samples:** 7
- **Initial RSS:** 1777.00 MB
- **Final RSS:** 1860.47 MB
- **Absolute Growth:** 83.47 MB
- **Percentage Growth:** 4.70%
- **Linear Slope:** 11.1494 MB/sample
- **Mean CPU:** 501.76%
- **Max CPU:** 831.10%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 373
- **Mean:** 237.91ms
- **Median:** 231.53ms
- **P95:** 324.91ms
- **P99:** 362.72ms
- **Max:** 386.03ms
- **Min:** 165.45ms

### 5-10min
- **Count:** 0 (no data)

### 10-15min
- **Count:** 0 (no data)

### 15-20min
- **Count:** 0 (no data)

### 20-25min
- **Count:** 0 (no data)

### 25-30min
- **Count:** 0 (no data)

## Event Bus Boundedness

- **Events Published:** 0
- **Events Delivered:** 0
- **Duplicates Suppressed:** 0
- **Dropped Events:** 0
- **Max History Size:** 0
- **Max Dedup Cache Size:** 0
- **Max Subscriber Count:** 0
- **Subscriber Errors:** 0
- **History Bounded:** True
- **Dedup Cache Bounded:** True

## Regression Tests

- **Overall:** ✗ FAIL (NOT_VERIFIED)

- **Phase 32 Streaming Contracts** (tests/unit/test_streaming_contracts.py): ✓
- **Phase 32 MediaMTX Config** (tests/unit/test_streaming_mediamtx.py): ✓
- **Phase 33 Health Events** (tests/unit/test_streaming_health_events.py): ✓
- **Phase 33 Health Monitor** (tests/unit/test_streaming_health.py): ✓
- **Phase 34 Live Dual Camera E2E** (N/A): ✗
  - Error: NOT_FOUND
- **Phase 34-R Live Dual Camera E2E Revalidation** (N/A): ✗
  - Error: NOT_FOUND
- **Phase 35 Realtime Performance** (tests/unit/test_phase35_performance.py): ✓
- **Phase 35A Contract Import Timestamp Repair** (N/A): ✗
  - Error: NOT_FOUND
- **Phase 31 Offline Full E2E** (tests/integration/test_phase31_offline_full_e2e.py): ✓
- **Phase 23 Raw IN/OUT Event** (tests/unit/test_raw_in_out_event.py): ✓
- **Phase 24 Repeated IN/OUT Resolution** (tests/unit/test_repeated_in_out.py): ✓
- **Phase 25 Attendance Persistence** (N/A): ✗
  - Error: NOT_FOUND
- **Phase 26 Attendance Engine** (tests/unit/test_attendance_engine.py): ✓
- **Phase 29 Immediate Event Output** (tests/unit/test_immediate_event_contract.py): ✓
- **Phase 30A Enrollment Database** (tests/unit/test_phase30a_enrollment.py): ✓

## Determinism / Idempotency

- **Verified:** True
- **Decision 1 ID:** DEC-test_resolution-v1.0-114e5cc352475ccc
- **Decision 2 ID:** DEC-test_resolution-v1.0-114e5cc352475ccc

## Known Limitations

- None

## Acceptance Criteria Summary

| Criterion | Status | Level |
|-----------|--------|-------|
| Real CAM1 connected | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Real CAM2 connected | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dual-camera simultaneous | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| 30-minute soak completed | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Warm-up separated from soak | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak frame continuity | ✗ FAIL | NOT_VERIFIED |
| CAM2 soak frame continuity | ✗ FAIL | NOT_VERIFIED |
| CAM1 soak timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Camera ID integrity (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| No cross-camera contamination | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak health stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak health stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| No uncontrolled retry loop (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Queue boundedness (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Buffer boundedness (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Steady-state memory stability | ✗ FAIL | NOT_VERIFIED |
| CPU/resource stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Inference latency stability (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Regression suite | ✗ FAIL | NOT_VERIFIED |
| Safe shutdown | ✓ PASS | LIVE_RUNTIME_VERIFIED |

## Phase 37 Readiness: NOT READY
