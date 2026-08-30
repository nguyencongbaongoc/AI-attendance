# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T13:48:47.305030Z
**Verdict:** FAIL
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 32.37 minutes
**Startup Duration:** 9.56 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T20:16:34.903645Z
**Start:** 2026-08-25T20:16:25.339056Z
**End:** 2026-08-25T20:48:47.301820Z
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

- **Duration:** 1890.16s
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
- **Total Unhealthy Duration:** 9.57s
- **Longest Unhealthy Interval:** 9.57s
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

- **Duration:** 1880.54s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0009s
- **P95 Frame Interval:** 1.0149s
- **P99 Frame Interval:** 1.0304s
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
- **Inference Latency Mean:** 156.37ms
- **Inference Latency Median:** 130.69ms
- **Inference Latency P95:** 350.29ms
- **Inference Latency P99:** 486.52ms
- **Inference Latency Max:** 649.74ms
- **Processing FPS Mean:** 1.07
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.78
- **Source FPS Mean:** 1.00

## CAM1 SOAK Metrics

- **Duration:** 1820.49s
- **Total Frames:** 1870
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 1879
- **Mean Frame Interval:** 1.0015s
- **P95 Frame Interval:** 1.0133s
- **P99 Frame Interval:** 1.0183s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 2
- **Total Unhealthy Duration:** 0.00s
- **Longest Unhealthy Interval:** 0.00s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 130.36ms
- **Inference Latency Median:** 113.60ms
- **Inference Latency P95:** 282.80ms
- **Inference Latency P99:** 369.58ms
- **Inference Latency Max:** 423.52ms
- **Processing FPS Mean:** 1.00
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## CAM2 STARTUP Metrics

- **Duration:** 1890.16s
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

- **Duration:** 1880.29s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9964s
- **P95 Frame Interval:** 1.0192s
- **P99 Frame Interval:** 1.0280s
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
- **Inference Latency Mean:** 139.18ms
- **Inference Latency Median:** 118.13ms
- **Inference Latency P95:** 284.66ms
- **Inference Latency P99:** 370.53ms
- **Inference Latency Max:** 383.85ms
- **Processing FPS Mean:** 1.07
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.75
- **Source FPS Mean:** 1.00

## CAM2 SOAK Metrics

- **Duration:** 1820.51s
- **Total Frames:** 1869
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 1879
- **Mean Frame Interval:** 1.0019s
- **P95 Frame Interval:** 1.0138s
- **P99 Frame Interval:** 1.0188s
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
- **Inference Latency Mean:** 125.58ms
- **Inference Latency Median:** 112.05ms
- **Inference Latency P95:** 268.66ms
- **Inference Latency P99:** 358.32ms
- **Inference Latency Max:** 409.83ms
- **Processing FPS Mean:** 1.00
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

### Overall
- **Initial RSS:** 858.00 MB
- **Final RSS:** 1189.20 MB
- **Min RSS:** 858.00 MB
- **Max RSS:** 1370.39 MB
- **Mean RSS:** 1212.94 MB
- **Absolute Growth:** 331.20 MB
- **Percentage Growth:** 38.60%
- **Linear Slope:** -0.5025 MB/sample
- **Mean CPU:** 35.87%
- **Max CPU:** 299.20%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 9.10%
- **Max GPU Memory:** 2650.90 MB

### By Phase
#### WARMUP
- **Samples:** 6
- **Initial RSS:** 858.00 MB
- **Final RSS:** 1319.54 MB
- **Absolute Growth:** 461.55 MB
- **Percentage Growth:** 53.79%
- **Linear Slope:** 65.5594 MB/sample
- **Mean CPU:** 49.87%
- **Max CPU:** 216.10%

#### SOAK
- **Samples:** 180
- **Initial RSS:** 1320.23 MB
- **Final RSS:** 1189.20 MB
- **Absolute Growth:** -131.04 MB
- **Percentage Growth:** -9.93%
- **Linear Slope:** -0.5195 MB/sample
- **Mean CPU:** 35.40%
- **Max CPU:** 299.20%

### Soak Phase: First 5 min vs Last 5 min Comparison
- **First 5 min Mean RSS:** 1304.15 MB
- **Last 5 min Mean RSS:** 1194.09 MB
- **First 5 min Max RSS:** 1370.39 MB
- **Last 5 min Max RSS:** 1236.43 MB
- **Growth (Mean):** -110.06 MB
- **Growth (Mean %):** -8.44%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 600
- **Mean:** 130.44ms
- **Median:** 110.52ms
- **P95:** 290.38ms
- **P99:** 361.06ms
- **Max:** 395.58ms
- **Min:** 52.79ms

### 5-10min
- **Count:** 600
- **Mean:** 129.64ms
- **Median:** 113.01ms
- **P95:** 283.78ms
- **P99:** 375.43ms
- **Max:** 400.73ms
- **Min:** 54.98ms

### 10-15min
- **Count:** 600
- **Mean:** 129.96ms
- **Median:** 116.37ms
- **P95:** 264.58ms
- **P99:** 352.70ms
- **Max:** 391.46ms
- **Min:** 56.14ms

### 15-20min
- **Count:** 600
- **Mean:** 128.50ms
- **Median:** 112.14ms
- **P95:** 271.80ms
- **P99:** 359.91ms
- **Max:** 399.39ms
- **Min:** 51.78ms

### 20-25min
- **Count:** 598
- **Mean:** 123.16ms
- **Median:** 111.49ms
- **P95:** 221.49ms
- **P99:** 327.36ms
- **Max:** 404.38ms
- **Min:** 51.47ms

### 25-30min
- **Count:** 600
- **Mean:** 125.74ms
- **Median:** 112.70ms
- **P95:** 252.31ms
- **P99:** 367.63ms
- **Max:** 423.52ms
- **Min:** 50.79ms

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
- **Phase 30A Enrollment Database** (tests/unit/test_phase30a_enrollment.py): ✗
  - Error: -packages\_pytest\warnings.py", line 119, in pytest_sessionfinish
    return (yield)
            ^^^^^
  File "C:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv\Lib\site-packages\pluggy\_callers.

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
| Steady-state memory stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CPU/resource stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Inference latency stability (soak) | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Regression suite | ✗ FAIL | NOT_VERIFIED |
| Safe shutdown | ✓ PASS | LIVE_RUNTIME_VERIFIED |

## Phase 37 Readiness: NOT READY
