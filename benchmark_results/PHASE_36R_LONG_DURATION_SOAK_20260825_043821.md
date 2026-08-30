# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T04:38:21.275445Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 3.19 minutes
**Startup Duration:** 7.71 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T11:35:17.728175Z
**Start:** 2026-08-25T11:35:10.018804Z
**End:** 2026-08-25T11:38:21.274907Z
**Termination Reason:** CAM1_stream_ended
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

- **Duration:** 137.87s
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
- **Total Unhealthy Duration:** 7.71s
- **Longest Unhealthy Interval:** 7.71s
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

- **Duration:** 129.81s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9955s
- **P95 Frame Interval:** 1.0114s
- **P99 Frame Interval:** 1.0167s
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
- **Inference Latency Mean:** 288.59ms
- **Inference Latency Median:** 276.45ms
- **Inference Latency P95:** 347.91ms
- **Inference Latency P99:** 386.66ms
- **Inference Latency Max:** 425.61ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.47
- **Source FPS Mean:** 1.01

## CAM1 SOAK Metrics

- **Duration:** 70.06s
- **Total Frames:** 69
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0006s
- **P95 Frame Interval:** 1.0172s
- **P99 Frame Interval:** 1.0256s
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
- **Inference Latency Mean:** 296.90ms
- **Inference Latency Median:** 288.13ms
- **Inference Latency P95:** 367.25ms
- **Inference Latency P99:** 382.80ms
- **Inference Latency Max:** 406.47ms
- **Processing FPS Mean:** 1.01
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## CAM2 STARTUP Metrics

- **Duration:** 137.87s
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

- **Duration:** 129.88s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9965s
- **P95 Frame Interval:** 1.0089s
- **P99 Frame Interval:** 1.0162s
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
- **Inference Latency Mean:** 284.53ms
- **Inference Latency Median:** 278.19ms
- **Inference Latency P95:** 334.63ms
- **Inference Latency P99:** 420.59ms
- **Inference Latency Max:** 428.68ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.47
- **Source FPS Mean:** 1.00

## CAM2 SOAK Metrics

- **Duration:** 70.07s
- **Total Frames:** 70
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0005s
- **P95 Frame Interval:** 1.0305s
- **P99 Frame Interval:** 1.2692s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 136.86s
- **Longest Unhealthy Interval:** 136.86s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 282.49ms
- **Inference Latency Median:** 272.52ms
- **Inference Latency P95:** 360.09ms
- **Inference Latency P99:** 402.11ms
- **Inference Latency Max:** 442.47ms
- **Processing FPS Mean:** 1.01
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.01

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

### Overall
- **Initial RSS:** 866.09 MB
- **Final RSS:** 1913.24 MB
- **Min RSS:** 866.09 MB
- **Max RSS:** 1920.06 MB
- **Mean RSS:** 1768.36 MB
- **Absolute Growth:** 1047.15 MB
- **Percentage Growth:** 120.90%
- **Linear Slope:** 44.1989 MB/sample
- **Mean CPU:** 298.30%
- **Max CPU:** 789.70%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 6.38%
- **Max GPU Memory:** 1171.94 MB

### By Phase
#### WARMUP
- **Samples:** 6
- **Initial RSS:** 866.09 MB
- **Final RSS:** 1783.69 MB
- **Absolute Growth:** 917.59 MB
- **Percentage Growth:** 105.95%
- **Linear Slope:** 129.3445 MB/sample
- **Mean CPU:** 253.50%
- **Max CPU:** 789.70%

#### SOAK
- **Samples:** 7
- **Initial RSS:** 1805.74 MB
- **Final RSS:** 1913.24 MB
- **Absolute Growth:** 107.50 MB
- **Percentage Growth:** 5.95%
- **Linear Slope:** 19.4291 MB/sample
- **Mean CPU:** 336.70%
- **Max CPU:** 698.10%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 139
- **Mean:** 289.64ms
- **Median:** 279.83ms
- **P95:** 367.29ms
- **P99:** 397.92ms
- **Max:** 442.47ms
- **Min:** 172.73ms

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

- Soak terminated early: CAM1_stream_ended
- Soak did not complete full duration: 3.2/31.1 min

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
| Safe shutdown | ✗ FAIL | NOT_VERIFIED |

## Phase 37 Readiness: NOT READY
