# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T04:24:06.823540Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 8.56 minutes
**Startup Duration:** 12.56 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T11:15:45.916578Z
**Start:** 2026-08-25T11:15:33.354779Z
**End:** 2026-08-25T11:24:06.822539Z
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

- **Duration:** 462.64s
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
- **Total Unhealthy Duration:** 12.56s
- **Longest Unhealthy Interval:** 12.56s
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

- **Duration:** 449.76s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9958s
- **P95 Frame Interval:** 1.0102s
- **P99 Frame Interval:** 1.0230s
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
- **Inference Latency Mean:** 283.07ms
- **Inference Latency Median:** 271.09ms
- **Inference Latency P95:** 342.17ms
- **Inference Latency P99:** 361.86ms
- **Inference Latency Max:** 364.59ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.51
- **Source FPS Mean:** 1.01

## CAM1 SOAK Metrics

- **Duration:** 390.01s
- **Total Frames:** 386
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0006s
- **P95 Frame Interval:** 1.0155s
- **P99 Frame Interval:** 1.1091s
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
- **Inference Latency Mean:** 287.24ms
- **Inference Latency Median:** 277.25ms
- **Inference Latency P95:** 354.55ms
- **Inference Latency P99:** 405.49ms
- **Inference Latency Max:** 456.18ms
- **Processing FPS Mean:** 1.00
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## CAM2 STARTUP Metrics

- **Duration:** 462.64s
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

- **Duration:** 449.79s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9963s
- **P95 Frame Interval:** 1.0114s
- **P99 Frame Interval:** 1.0190s
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
- **Inference Latency Median:** 280.30ms
- **Inference Latency P95:** 340.19ms
- **Inference Latency P99:** 379.75ms
- **Inference Latency Max:** 383.43ms
- **Processing FPS Mean:** 1.05
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.49
- **Source FPS Mean:** 1.00

## CAM2 SOAK Metrics

- **Duration:** 390.01s
- **Total Frames:** 387
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0007s
- **P95 Frame Interval:** 1.0144s
- **P99 Frame Interval:** 1.0524s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 458.90s
- **Longest Unhealthy Interval:** 458.90s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 286.80ms
- **Inference Latency Median:** 278.48ms
- **Inference Latency P95:** 341.74ms
- **Inference Latency P99:** 375.63ms
- **Inference Latency Max:** 428.58ms
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
- **Initial RSS:** 868.77 MB
- **Final RSS:** 1964.59 MB
- **Min RSS:** 868.77 MB
- **Max RSS:** 1983.26 MB
- **Mean RSS:** 1869.96 MB
- **Absolute Growth:** 1095.82 MB
- **Percentage Growth:** 126.13%
- **Linear Slope:** 7.9575 MB/sample
- **Mean CPU:** 235.82%
- **Max CPU:** 814.50%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 10.18%
- **Max GPU Memory:** 1189.55 MB

### By Phase
#### WARMUP
- **Samples:** 6
- **Initial RSS:** 868.77 MB
- **Final RSS:** 1781.25 MB
- **Absolute Growth:** 912.47 MB
- **Percentage Growth:** 105.03%
- **Linear Slope:** 128.9254 MB/sample
- **Mean CPU:** 222.87%
- **Max CPU:** 587.70%

#### SOAK
- **Samples:** 39
- **Initial RSS:** 1781.40 MB
- **Final RSS:** 1964.59 MB
- **Absolute Growth:** 183.19 MB
- **Percentage Growth:** 10.28%
- **Linear Slope:** 5.2616 MB/sample
- **Mean CPU:** 237.81%
- **Max CPU:** 814.50%

### Soak Phase: First 5 min vs Last 5 min Comparison
- **First 5 min Mean RSS:** 1850.12 MB
- **Last 5 min Mean RSS:** 1961.95 MB
- **First 5 min Max RSS:** 1928.23 MB
- **Last 5 min Max RSS:** 1983.26 MB
- **Growth (Mean):** 111.84 MB
- **Growth (Mean %):** 6.04%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 600
- **Mean:** 289.44ms
- **Median:** 280.06ms
- **P95:** 359.58ms
- **P99:** 407.90ms
- **Max:** 456.18ms
- **Min:** 186.61ms

### 5-10min
- **Count:** 173
- **Mean:** 278.61ms
- **Median:** 270.35ms
- **P95:** 334.55ms
- **P99:** 352.46ms
- **Max:** 355.87ms
- **Min:** 168.65ms

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
- Soak did not complete full duration: 8.6/31.2 min

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
