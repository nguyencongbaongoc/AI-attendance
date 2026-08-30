# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T13:10:59.134146Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 14.57 minutes
**Startup Duration:** 6.49 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T19:56:31.266248Z
**Start:** 2026-08-25T19:56:24.774688Z
**End:** 2026-08-25T20:10:59.132983Z
**Termination Reason:** CAM2_stream_ended
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

- **Duration:** 826.63s
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
- **Total Unhealthy Duration:** 6.49s
- **Longest Unhealthy Interval:** 6.49s
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

- **Duration:** 820.10s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0009s
- **P95 Frame Interval:** 1.0141s
- **P99 Frame Interval:** 1.0204s
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
- **Inference Latency Mean:** 140.46ms
- **Inference Latency Median:** 116.67ms
- **Inference Latency P95:** 290.40ms
- **Inference Latency P99:** 504.11ms
- **Inference Latency Max:** 751.57ms
- **Processing FPS Mean:** 1.06
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.74
- **Source FPS Mean:** 1.00

## CAM1 SOAK Metrics

- **Duration:** 760.05s
- **Total Frames:** 756
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0006s
- **P95 Frame Interval:** 1.0128s
- **P99 Frame Interval:** 1.0177s
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
- **Inference Latency Mean:** 129.38ms
- **Inference Latency Median:** 107.80ms
- **Inference Latency P95:** 278.47ms
- **Inference Latency P99:** 394.64ms
- **Inference Latency Max:** 431.20ms
- **Processing FPS Mean:** 1.00
- **Processing FPS Min:** 1.00
- **Processing FPS Max:** 1.01
- **Source FPS Mean:** 1.00

## CAM2 STARTUP Metrics

- **Duration:** 826.64s
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

- **Duration:** 819.82s
- **Total Frames:** 60
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 0.9961s
- **P95 Frame Interval:** 1.0106s
- **P99 Frame Interval:** 1.0122s
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
- **Inference Latency Mean:** 150.83ms
- **Inference Latency Median:** 138.45ms
- **Inference Latency P95:** 354.87ms
- **Inference Latency P99:** 414.99ms
- **Inference Latency Max:** 470.27ms
- **Processing FPS Mean:** 1.06
- **Processing FPS Min:** 1.01
- **Processing FPS Max:** 1.71
- **Source FPS Mean:** 1.01

## CAM2 SOAK Metrics

- **Duration:** 760.05s
- **Total Frames:** 755
- **Dropped Frames:** 0
- **Stale Frames:** 0
- **Discontinuities:** 0
- **Timestamp Regressions:** 0
- **Duplicate Frame Indices:** 0
- **Max Gap:** 0
- **Mean Frame Interval:** 1.0007s
- **P95 Frame Interval:** 1.0114s
- **P99 Frame Interval:** 1.0161s
- **Timestamp Regressions Count:** 0
- **Max Timestamp Regression:** 0.0000s
- **Camera ID Violations:** 0
- **State Transitions:** 0
- **Total Unhealthy Duration:** 822.04s
- **Longest Unhealthy Interval:** 822.04s
- **Reconnect Attempts:** 0
- **Max Queue Depth:** 0
- **Avg Queue Depth:** 0.00
- **P95 Queue Depth:** 0.00
- **P99 Queue Depth:** 0.00
- **Queue Capacity:** 10
- **Overflow Count:** 0
- **Inference Latency Mean:** 133.39ms
- **Inference Latency Median:** 114.03ms
- **Inference Latency P95:** 311.85ms
- **Inference Latency P99:** 386.49ms
- **Inference Latency Max:** 439.49ms
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
- **Initial RSS:** 851.86 MB
- **Final RSS:** 1184.37 MB
- **Min RSS:** 851.86 MB
- **Max RSS:** 1366.47 MB
- **Mean RSS:** 1272.64 MB
- **Absolute Growth:** 332.51 MB
- **Percentage Growth:** 39.03%
- **Linear Slope:** -1.7766 MB/sample
- **Mean CPU:** 30.47%
- **Max CPU:** 302.40%
- **GPU Telemetry:** AVAILABLE
- **Mean GPU Utilization:** 9.56%
- **Max GPU Memory:** 2715.21 MB

### By Phase
#### WARMUP
- **Samples:** 6
- **Initial RSS:** 851.86 MB
- **Final RSS:** 1315.37 MB
- **Absolute Growth:** 463.51 MB
- **Percentage Growth:** 54.41%
- **Linear Slope:** 66.2042 MB/sample
- **Mean CPU:** 19.12%
- **Max CPU:** 114.70%

#### SOAK
- **Samples:** 75
- **Initial RSS:** 1316.57 MB
- **Final RSS:** 1184.37 MB
- **Absolute Growth:** -132.20 MB
- **Percentage Growth:** -10.04%
- **Linear Slope:** -2.5087 MB/sample
- **Mean CPU:** 31.38%
- **Max CPU:** 302.40%

### Soak Phase: First 5 min vs Last 5 min Comparison
- **First 5 min Mean RSS:** 1324.69 MB
- **Last 5 min Mean RSS:** 1201.30 MB
- **First 5 min Max RSS:** 1366.47 MB
- **Last 5 min Max RSS:** 1319.44 MB
- **Growth (Mean):** -123.39 MB
- **Growth (Mean %):** -9.31%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 600
- **Mean:** 133.03ms
- **Median:** 112.36ms
- **P95:** 297.67ms
- **P99:** 392.56ms
- **Max:** 430.74ms
- **Min:** 53.72ms

### 5-10min
- **Count:** 600
- **Mean:** 134.45ms
- **Median:** 111.88ms
- **P95:** 326.66ms
- **P99:** 397.31ms
- **Max:** 439.49ms
- **Min:** 51.60ms

### 10-15min
- **Count:** 311
- **Mean:** 122.29ms
- **Median:** 106.83ms
- **P95:** 283.84ms
- **P99:** 357.49ms
- **Max:** 372.22ms
- **Min:** 47.40ms

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

- Soak terminated early: CAM2_stream_ended
- Soak did not complete full duration: 14.6/31.1 min

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
