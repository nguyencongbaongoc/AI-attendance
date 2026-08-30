# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T04:34:32.575421Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 2.37 minutes
**Startup Duration:** 8.48 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T11:32:18.748981Z
**Start:** 2026-08-25T11:32:10.267328Z
**End:** 2026-08-25T11:34:32.574397Z
**Termination Reason:** user_interrupt
**Soak Completed:** False
**Camera States:** CAM1=LIVE, CAM2=LIVE
**Memory Growth Threshold:** 20.0%

## Verification Classification (SOAK Phase - Critical)

### CAM1 (SOAK)
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✓ LIVE_RUNTIME_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### CAM2 (SOAK)
- **frame_continuity**: ✓ LIVE_RUNTIME_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✗ NOT_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### Cross-Camera (Overall)
- **contamination**: ✓ LIVE_RUNTIME_VERIFIED

### System Resources (SOAK)
- **memory_stability**: ✓ LIVE_RUNTIME_VERIFIED

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

- **Duration:** 91.64s
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
- **Total Unhealthy Duration:** 8.48s
- **Longest Unhealthy Interval:** 8.48s
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

- **Duration:** 82.81s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9953s
- **P95 Frame Interval:** 1.0070s
- **P99 Frame Interval:** 1.0095s
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
- **Inference Latency Mean:** 283.60ms
- **Inference Latency Median:** 276.47ms
- **Inference Latency P95:** 343.80ms
- **Inference Latency P99:** 359.71ms
- **Inference Latency Max:** 375.16ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.49
- **Source FPS Mean:** 1.01

## CAM1 SOAK Metrics

- **Duration:** 23.09s
- **Total Frames:** 23
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0008s
- **P95 Frame Interval:** 1.0075s
- **P99 Frame Interval:** 1.0079s
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
- **Inference Latency Mean:** 284.52ms
- **Inference Latency Median:** 275.51ms
- **Inference Latency P95:** 338.84ms
- **Inference Latency P99:** 344.69ms
- **Inference Latency Max:** 346.30ms
- **Processing FPS Mean:** 1.01
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## CAM2 STARTUP Metrics

- **Duration:** 91.64s
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

- **Duration:** 82.87s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9964s
- **P95 Frame Interval:** 1.0058s
- **P99 Frame Interval:** 1.0080s
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
- **Inference Latency Mean:** 296.56ms
- **Inference Latency Median:** 289.82ms
- **Inference Latency P95:** 352.15ms
- **Inference Latency P99:** 388.27ms
- **Inference Latency Max:** 438.16ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.51
- **Source FPS Mean:** 1.01

## CAM2 SOAK Metrics

- **Duration:** 23.08s
- **Total Frames:** 23
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0007s
- **P95 Frame Interval:** 1.0070s
- **P99 Frame Interval:** 1.1516s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 90.68s
- **Longest Unhealthy Interval:** 90.68s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 297.71ms
- **Inference Latency Median:** 289.90ms
- **Inference Latency P95:** 342.99ms
- **Inference Latency P99:** 344.63ms
- **Inference Latency Max:** 345.01ms
- **Processing FPS Mean:** 1.01
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

### Overall
- **Initial RSS:** 865.68 MB
- **Final RSS:** 1858.15 MB
- **Min RSS:** 865.68 MB
- **Max RSS:** 1858.15 MB
- **Mean RSS:** 1695.74 MB
- **Absolute Growth:** 992.47 MB
- **Percentage Growth:** 114.65%
- **Linear Slope:** 67.3381 MB/sample
- **Mean CPU:** 252.68%
- **Max CPU:** 789.70%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 8.22%
- **Max GPU Memory:** 1081.41 MB

### By Phase
#### WARMUP
- **Samples:** 6
- **Initial RSS:** 865.68 MB
- **Final RSS:** 1782.21 MB
- **Absolute Growth:** 916.53 MB
- **Percentage Growth:** 105.87%
- **Linear Slope:** 129.3463 MB/sample
- **Mean CPU:** 225.23%
- **Max CPU:** 598.40%

#### SOAK
- **Samples:** 3
- **Initial RSS:** 1803.90 MB
- **Final RSS:** 1858.15 MB
- **Absolute Growth:** 54.25 MB
- **Percentage Growth:** 3.01%
- **Linear Slope:** 27.1250 MB/sample
- **Mean CPU:** 307.57%
- **Max CPU:** 789.70%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 46
- **Mean:** 291.11ms
- **Median:** 282.89ms
- **P95:** 342.57ms
- **P99:** 345.72ms
- **Max:** 346.30ms
- **Min:** 231.94ms

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

- Soak terminated early: user_interrupt
- Soak did not complete full duration: 2.4/31.1 min

## Acceptance Criteria Summary

| Criterion | Status | Level |
|-----------|--------|-------|
| Real CAM1 connected | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Real CAM2 connected | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dual-camera simultaneous | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| 30-minute soak completed | ✗ FAIL | NOT_VERIFIED |
| Warm-up separated from soak | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak frame continuity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak frame continuity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Camera ID integrity (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| No cross-camera contamination | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak health stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak health stability | ✗ FAIL | NOT_VERIFIED |
| No uncontrolled retry loop (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Queue boundedness (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Buffer boundedness (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Steady-state memory stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CPU/resource stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Inference latency stability (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Regression suite | ✗ FAIL | NOT_VERIFIED |
| Safe shutdown | ✓ PASS | LIVE_RUNTIME_VERIFIED |

## Phase 37 Readiness: NOT READY
