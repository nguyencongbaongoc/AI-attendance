# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T13:14:28.729275Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 30.0 minutes
**Configured Warm-up:** 60.0 seconds
**Actual Duration:** 0.96 minutes
**Startup Duration:** 8.87 seconds
**Warm-up Duration:** 60.00 seconds
**Soak Duration:** 1800.00 seconds
**First Live Timestamp:** 2026-08-25T20:13:39.864372Z
**Start:** 2026-08-25T20:13:30.991821Z
**End:** 2026-08-25T20:14:28.728256Z
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
### CAM2 (Startup/Warm-up)
## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

### Overall
- **Initial RSS:** 843.85 MB
- **Final RSS:** 843.85 MB
- **Min RSS:** 843.85 MB
- **Max RSS:** 843.85 MB
- **Mean RSS:** 843.85 MB
- **Absolute Growth:** 0.00 MB
- **Percentage Growth:** 0.00%
- **Linear Slope:** 0.0000 MB/sample
- **Mean CPU:** 0.00%
- **Max CPU:** 0.00%
- **GPU Telemetry:** NOT_AVAILABLE
- **Mean GPU Utilization:** 0.00%
- **Max GPU Memory:** 1701.25 MB

### By Phase
#### WARMUP
- **Samples:** 1
- **Initial RSS:** 843.85 MB
- **Final RSS:** 843.85 MB
- **Absolute Growth:** 0.00 MB
- **Percentage Growth:** 0.00%
- **Linear Slope:** 0.0000 MB/sample
- **Mean CPU:** 0.00%
- **Max CPU:** 0.00%

## Inference Latency by Time Window (SOAK Phase)

### 0-5min
- **Count:** 0 (no data)

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
- Soak did not complete full duration: 1.0/31.1 min
- GPU telemetry not available

## Acceptance Criteria Summary

| Criterion | Status | Level |
|-----------|--------|-------|
| Real CAM1 connected | ✗ FAIL | NOT_VERIFIED |
| Real CAM2 connected | ✗ FAIL | NOT_VERIFIED |
| Dual-camera simultaneous | ✗ FAIL | NOT_VERIFIED |
| 30-minute soak completed | ✗ FAIL | NOT_VERIFIED |
| Warm-up separated from soak | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM1 soak frame continuity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| CAM2 soak frame continuity | ✓ PASS | LIVE_RUNTIME_VERIFIED |
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
| Inference latency stability (soak) | ✗ FAIL | NOT_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Regression suite | ✗ FAIL | NOT_VERIFIED |
| Safe shutdown | ✗ FAIL | NOT_VERIFIED |

## Phase 37 Readiness: NOT READY
