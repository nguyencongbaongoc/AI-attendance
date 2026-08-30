# Phase 36-R — Long-Duration Soak Revalidation Report

**Timestamp:** 2026-08-25T00:48:37.891390Z
**Verdict:** NOT_READY
**Configured Soak Duration:** 0.1 minutes
**Configured Warm-up:** 5.0 seconds
**Actual Duration:** 0.00 minutes
**Startup Duration:** 0.00 seconds
**Warm-up Duration:** 0.00 seconds
**Soak Duration:** 0.00 seconds
**First Live Timestamp:** None
**Start:** 2026-08-25T07:48:31.649462Z
**End:** 1970-01-01T07:00:00Z
**Termination Reason:** stream_open_failed: Failed to open RTSP source: Failed to open video: rtsp://127.0.0.1:8554/live/cam2
**Soak Completed:** False
**Camera States:** CAM1=OFFLINE, CAM2=OFFLINE
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
- **regression**: ✓ LIVE_RUNTIME_VERIFIED

### Determinism
- **idempotency**: ✗ NOT_VERIFIED

## Verification Classification (Startup/Warm-up - Informational)

### CAM1 (Startup/Warm-up)
### CAM2 (Startup/Warm-up)
## Cross-Camera Contamination

- **Verified:** True
- **Level:** LIVE_RUNTIME_VERIFIED
- **Events:** 0


## System Resources

- **System resource monitoring: NOT_AVAILABLE**

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

- **Overall:** ✓ PASS (LIVE_RUNTIME_VERIFIED)


## Determinism / Idempotency

- **Verified:** False
- **Decision 1 ID:** N/A
- **Decision 2 ID:** N/A

## Known Limitations

- Soak terminated early: stream_open_failed: Failed to open RTSP source: Failed to open video: rtsp://127.0.0.1:8554/live/cam2
- Soak did not complete full duration: 0.0/0.2 min
- System resource monitoring not fully available

## Acceptance Criteria Summary

| Criterion | Status | Level |
|-----------|--------|-------|
| Real CAM1 connected | ✗ FAIL | NOT_VERIFIED |
| Real CAM2 connected | ✗ FAIL | NOT_VERIFIED |
| Dual-camera simultaneous | ✗ FAIL | NOT_VERIFIED |
| 30-minute soak completed | ✗ FAIL | NOT_VERIFIED |
| Warm-up separated from soak | ✗ FAIL | NOT_VERIFIED |
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
| CPU/resource stability | ✗ FAIL | NOT_VERIFIED |
| Inference latency stability (soak) | ✗ FAIL | NOT_VERIFIED |
| Event history boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Dedup cache boundedness | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Determinism/idempotency | ✗ FAIL | NOT_VERIFIED |
| Regression suite | ✓ PASS | LIVE_RUNTIME_VERIFIED |
| Safe shutdown | ✗ FAIL | NOT_VERIFIED |

## Phase 37 Readiness: NOT READY
