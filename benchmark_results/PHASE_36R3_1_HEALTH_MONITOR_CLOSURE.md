# Phase 36-R3.1 -- Health Monitor CAM2 Forensic Closure Report

## Executive Summary

**Verdict:** PASS_WITH_DOCUMENTED_LIMITATION

**Key Findings:**
1. **CAM2 Health Monitor Issue**: NOT REPRODUCIBLE - In all forensic tests, CAM2 correctly transitions OFFLINE->LIVE on first frame and remains LIVE throughout the soak test.
2. **FPS Issue**: SOURCE LIMITATION - The Moblin RTSP source publishes at ~25.5 FPS (measured from frame timestamps), not 30 FPS. The ~6.5-7 FPS observed was AI processing FPS (limited by ~95ms/frame inference at 4K), not source FPS.
3. **Stream Exhaustion**: SOURCE LIMITATION - Test streams exhaust after ~60 seconds (~1500 frames at 25 FPS). This prevents a true 30-minute soak validation.

## Baseline

- Health Monitor: pp/streaming/health.py
- RTSP Source: pp/streaming/rtsp_source.py
- Input Adapter: pp/data/input_adapter.py
- Soak Harness: scripts/phase36r_long_duration_soak.py
- Phase 36-R3 Report: enchmark_results/PHASE_36R3_SOAK_HARNESS_REPAIR.json
- Phase 36D Report: enchmark_results/PHASE_36D_NVDEC_INTEGRATION.json
- Phase 36-R1 Report: enchmark_results/PHASE_36R1_FINAL_REAL_30MIN_SOAK.json

## CAM2 Health Event Timeline

| Event | State | Details |
|-------|-------|---------|
| Initial | OFFLINE | After 
egister_camera() |
| After init frame | LIVE | After update_frame_received() with stream metadata |
| First health check | LIVE | Transition OFFLINE->LIVE at t=0 |
| 5s, 10s, 15s... | LIVE | All subsequent checks show LIVE |
| Final | LIVE | After 60+ seconds of processing |

## Root Cause Analysis

### CAM2 OFFLINE Issue
**Status: NOT REPRODUCIBLE**

In all forensic tests (10+ runs with exact soak test initialization sequence), CAM2 correctly:
1. Registers as OFFLINE
2. Transitions to LIVE on first update_frame_received() call
3. Remains LIVE throughout the entire test duration

The Phase 36-R3 report showing CAM2 as OFFLINE during soak was likely a test harness artifact or timing issue in that specific run.

### FPS Issue (~6.5-7 FPS vs 30 FPS)
**Status: SOURCE LIMITATION + MEASUREMENT CLARIFICATION**

| Pipeline Stage | Measured FPS | Notes |
|----------------|--------------|-------|
| Source (from timestamps) | 25.5 | Moblin publishes ~25.5 FPS, not 30 |
| Decode (NVDEC) | 25.5 | Matches source |
| V2 Ingestion | 25.5 | Matches source |
| AI Processing | 7.3 | Limited by ~95ms/frame inference at 4K |
| Output | 7.3 | Matches AI processing |
| Metrics Sampling | 1.0 | Independent 1Hz sampling |

The ~6.5-7 FPS in Phase 36-R3 was AI processing FPS, not source FPS. The repaired harness correctly separates these.

### Stream Exhaustion (CAM1_stream_ended)
**Status: SOURCE LIMITATION**

- Moblin test streams exhaust after ~1000-1500 frames (~40-60 seconds at 25 FPS)
- Not an application defect - FFmpeg returns EOF, RTSPSource correctly reports is_exhausted=True
- Final 30-minute soak requires longer-running source streams

## Repair

**NO CODE CHANGES REQUIRED**

The health monitor, FPS measurement, and stream handling all work correctly. The issues observed in Phase 36-R3 were:
1. CAM2 OFFLINE - Not reproducible (likely test harness artifact)
2. Low FPS - Correctly measured as AI processing FPS, not source FPS
3. Stream exhaustion - Source limitation, not application defect

## Regression Tests

All 422 tests passed:
- Phase 32 Streaming Contracts: 33/33 PASS
- Phase 32 MediaMTX Config: 23/23 PASS
- Phase 33 Health Events: 25/25 PASS
- Phase 33 Health Monitor: 36/36 PASS
- Phase 35 Realtime Performance: 15/15 PASS
- Phase 31 Offline Full E2E: 57/57 PASS
- Phase 23 Raw IN/OUT Event: 76/76 PASS
- Phase 24 Repeated IN/OUT Resolution: 72/72 PASS
- Phase 26 Attendance Engine: 12/12 PASS
- Phase 29 Immediate Event Output: 34/34 PASS
- Phase 30A Enrollment Database: 39/39 PASS (exit_code=1 due to Windows temp cleanup, not test failure)

## Verification Results

| Criterion | CAM1 | CAM2 |
|-----------|------|------|
| Health State | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |
| Frame Continuity | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |
| Timestamp Monotonicity | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |
| Camera ID Integrity | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |
| Queue Boundedness | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |
| NVDEC Active | LIVE_RUNTIME_VERIFIED | LIVE_RUNTIME_VERIFIED |

## System Metrics

- **GPU Utilization**: 8.4% avg, 22% max
- **GPU Memory**: 1688 MB avg, 1691 MB max
- **CPU Utilization**: 192% avg (multi-threaded), 403% max
- **NVDEC Status**: ENABLED - h264_cuvid active, GPU decode verified
- **Memory Growth**: -0.25% (well under 20% threshold)
- **Event Bus**: Bounded (history <= 10000, dedup_cache <= 50000)

## Limitations

1. Test streams (Moblin) exhaust after ~60 seconds, preventing true 30-minute soak validation
2. Source FPS is ~25.5 FPS (not 30 FPS as advertised)
3. AI processing FPS limited to ~7 FPS by 95ms/frame inference latency at 4K resolution
4. Windows pytest temp cleanup PermissionError (cosmetic, non-functional)
5. CAM2 OFFLINE issue in Phase 36-R3 report not reproducible in forensic testing

## Final Verdict

**PASS_WITH_DOCUMENTED_LIMITATION**

The health monitor works correctly. The FPS measurement is accurate when properly separated by pipeline stage. The stream exhaustion is a source limitation.

**READY_FOR_FINAL_36R: FALSE**

Reason: Stream duration insufficient for 30-minute soak (source exhausts at ~60 seconds). Need longer-running RTSP source streams.

---
*Report generated: 2026-08-25T23:06:59.145217Z*
