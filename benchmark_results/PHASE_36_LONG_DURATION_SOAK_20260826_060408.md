# Phase 36 — Long-Duration Soak Test Report

**Timestamp:** 2026-08-26T06:04:08.778634Z
**Verdict:** FAIL
**Configured Duration:** 0.1 minutes
**Actual Duration:** 0.81 minutes
**Start:** 2026-08-26T13:03:20.361640Z
**End:** 2026-08-26T13:04:08.778635Z
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

- **Duration:** 33.72s
- **Total Frames:** 81
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 59
- **Mean Frame Interval:** 0.5564s
- **P95 Frame Interval:** 0.5076s
- **P99 Frame Interval:** 1.5349s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 3
- **Total Unhealthy Duration:** 3.60s
- **Longest Unhealthy Interval:** 3.60s
- **Reconnect Attempts:** 0
- **Successful Reconnects:** 0
- **Failed Reconnects:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 120.33ms
- **Inference Latency Median:** 119.33ms
- **Inference Latency P95:** 180.54ms
- **Inference Latency P99:** 289.60ms
- **Inference Latency Max:** 433.21ms
- **Processing FPS Mean:** 2.04
- **Processing FPS Min:** 1.52
- **Processing FPS Max:** 2.59
- **Source FPS Mean:** 2.00

## CAM2 Metrics

- **Duration:** 33.73s
- **Total Frames:** 86
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 1
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 59
- **Mean Frame Interval:** 0.5200s
- **P95 Frame Interval:** 0.5186s
- **P99 Frame Interval:** 0.8382s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 3
- **Total Unhealthy Duration:** 3.60s
- **Longest Unhealthy Interval:** 3.60s
- **Reconnect Attempts:** 0
- **Successful Reconnects:** 0
- **Failed Reconnects:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 96.58ms
- **Inference Latency Median:** 90.04ms
- **Inference Latency P95:** 166.82ms
- **Inference Latency P99:** 276.71ms
- **Inference Latency Max:** 420.86ms
- **Processing FPS Mean:** 2.06
- **Processing FPS Min:** 1.56
- **Processing FPS Max:** 2.71
- **Source FPS Mean:** 2.00

## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

- **Initial RSS:** 1306.92 MB
- **Final RSS:** 2062.00 MB
- **Min RSS:** 1306.92 MB
- **Max RSS:** 2110.06 MB
- **Mean RSS:** 1943.59 MB
- **Absolute Growth:** 755.08 MB
- **Percentage Growth:** 57.78%
- **Linear Slope:** 103.7155 MB/sample
- **Mean CPU:** 163.53%
- **Max CPU:** 548.50%
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
- **Phase 30A Enrollment Database**: ✗
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
