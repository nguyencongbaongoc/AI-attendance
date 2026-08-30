# Phase 36 — Long-Duration Soak Test Report

**Timestamp:** 2026-08-25T00:19:40.685054Z
**Verdict:** FAIL
**Configured Duration:** 0.1 minutes
**Actual Duration:** 0.97 minutes
**Start:** 2026-08-25T07:18:42.777642Z
**End:** 2026-08-25T07:19:40.683443Z
**Termination Reason:** completed
**Camera States:** CAM1=LIVE, CAM2=LIVE

## Verification Classification

### CAM1
- **frame_continuity**: ✗ NOT_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✗ NOT_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### CAM2
- **frame_continuity**: ✗ NOT_VERIFIED
- **timestamp_monotonicity**: ✓ LIVE_RUNTIME_VERIFIED
- **camera_id_integrity**: ✓ LIVE_RUNTIME_VERIFIED
- **health_stability**: ✗ NOT_VERIFIED
- **no_uncontrolled_retry**: ✓ LIVE_RUNTIME_VERIFIED
- **queue_boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### Cross-Camera
- **contamination**: ✓ LIVE_RUNTIME_VERIFIED

### System Resources
- **memory_stability**: ✗ NOT_VERIFIED

### Event Bus
- **boundedness**: ✓ LIVE_RUNTIME_VERIFIED

### Regression
- **regression**: ✗ NOT_VERIFIED

### Determinism
- **idempotency**: ✓ LIVE_RUNTIME_VERIFIED

## CAM1 Metrics

- **Duration:** 39.15s
- **Total Frames:** 95
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 59
- **Mean Frame Interval:** 0.5097s
- **P95 Frame Interval:** 0.5320s
- **P99 Frame Interval:** 0.6240s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 1
- **Total Unhealthy Duration:** 9.01s
- **Longest Unhealthy Interval:** 9.01s
- **Reconnect Attempts:** 0
- **Successful Reconnects:** 0
- **Failed Reconnects:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 290.67ms
- **Inference Latency Median:** 283.32ms
- **Inference Latency P95:** 341.87ms
- **Inference Latency P99:** 361.58ms
- **Inference Latency Max:** 365.34ms
- **Processing FPS Mean:** 1.95
- **Processing FPS Min:** 1.22
- **Processing FPS Max:** 1.99
- **Source FPS Mean:** 2.01

## CAM2 Metrics

- **Duration:** 39.15s
- **Total Frames:** 91
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 59
- **Mean Frame Interval:** 0.5358s
- **P95 Frame Interval:** 0.5220s
- **P99 Frame Interval:** 0.8993s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 3
- **Total Unhealthy Duration:** 9.01s
- **Longest Unhealthy Interval:** 9.01s
- **Reconnect Attempts:** 0
- **Successful Reconnects:** 0
- **Failed Reconnects:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 288.40ms
- **Inference Latency Median:** 280.08ms
- **Inference Latency P95:** 353.08ms
- **Inference Latency P99:** 381.02ms
- **Inference Latency Max:** 389.38ms
- **Processing FPS Mean:** 1.95
- **Processing FPS Min:** 1.21
- **Processing FPS Max:** 1.99
- **Source FPS Mean:** 2.01

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

- **Initial RSS:** 866.03 MB
- **Final RSS:** 1836.33 MB
- **Min RSS:** 866.03 MB
- **Max RSS:** 1841.16 MB
- **Mean RSS:** 1740.61 MB
- **Absolute Growth:** 970.30 MB
- **Percentage Growth:** 112.04%
- **Linear Slope:** 25.5871 MB/sample
- **Mean CPU:** 461.07%
- **Max CPU:** 814.50%
- **GPU Telemetry:** AVAILABLE

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

- **Phase 32 Streaming Contracts**: ✓
- **Phase 32 MediaMTX Config**: ✓
- **Phase 33 Health Events**: ✓
- **Phase 33 Health Monitor**: ✓
- **Phase 31 Offline Full E2E**: ✗
  - Error: NOT_FOUND
- **Phase 23 Raw IN/OUT Event**: ✗
  - Error: NOT_FOUND
- **Phase 24 Repeated IN/OUT Resolution**: ✗
  - Error: NOT_FOUND
- **Phase 25 Attendance Persistence**: ✗
  - Error: NOT_FOUND
- **Phase 26 Attendance Engine**: ✗
  - Error: NOT_FOUND
- **Phase 29 Immediate Event Output**: ✗
  - Error: NOT_FOUND
- **Phase 30A Enrollment Database**: ✓

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
| Long-duration completed | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 frame continuity | ✗ FAIL | NOT_VERIFIED |
| CAM2 frame continuity | ✗ FAIL | NOT_VERIFIED |
| CAM1 timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 timestamp monotonicity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Camera ID integrity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| No cross-camera contamination | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Health stability | ✗ FAIL | NOT_VERIFIED |
| No uncontrolled retry loop | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Queue boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Buffer boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Memory stability | ✗ FAIL | NOT_VERIFIED |
| CPU/resource stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Inference latency stability | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Regression suite | ✗ FAIL | NOT_VERIFIED |
| Safe shutdown | ✓ PASS | LIVE_RUNTIME_VERIFIED |

## Phase 37 Readiness: NOT READY
