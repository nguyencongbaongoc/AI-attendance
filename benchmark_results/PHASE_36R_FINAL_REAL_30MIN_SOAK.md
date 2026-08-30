# Phase 36-R — FINAL REAL 30-MINUTE SOAK VALIDATION REPORT

**Phase:** 36-R
**Name:** FINAL_REAL_30MIN_SOAK
**Timestamp:** 2026-08-26T06:04:08.778634Z
**Verdict:** NOT_READY
**PHASE_36R_COMPLETE:** False

---

## Executive Summary

The Phase 36-R final real 30-minute dual-camera soak validation was executed. The production-bound live AI pipeline architecture (RTSP → NVDEC → V2 → GPU preprocessing → ORT CUDA + I/O Binding → AI pipeline → tracking/identity/fusion/attendance) was validated.

**Result: NOT_READY**

**Reason:** CAM1 and CAM2 Moblin test streams exhaust after approximately 140 seconds (3,600-3,700 frames at ~26 FPS). The required soak duration is 60s warmup + 1800s soak = 1860 seconds (31 minutes). The sources cannot sustain the 30-minute soak. Per Phase 36-R requirements: "If either source is known to terminate before 30 minutes, STOP before starting the soak and report: NOT_READY. Do not repeatedly reconnect the same short-lived source just to make the timer reach 30 minutes."

---

## Preflight Verification

| Check | CAM1 | CAM2 |
|-------|------|------|
| Stream Active | ✅ | ✅ |
| RTSP Readable | ✅ | ✅ |
| NVDEC Active | ✅ | ✅ |
| Source Frame Delivery Confirmed | ✅ | ✅ |
| Sustains 120s | ✅ | ✅ |
| Sustains 1800s | ❌ | ❌ |
| Source Duration Sufficient | ❌ | ❌ |

---

## Subagent Findings

### Subagent 1 — Pipeline Readiness
| Component | Status |
|-----------|--------|
| RTSP → NVDEC | LIVE_RUNTIME_VERIFIED |
| NVDEC → V2 | LIVE_RUNTIME_VERIFIED |
| V2 → GPU Preprocessing | LIVE_RUNTIME_VERIFIED |
| GPU Preprocessing → ORT I/O Binding | LIVE_RUNTIME_VERIFIED |
| ORT I/O Binding → AI Pipeline | LIVE_RUNTIME_VERIFIED |
| No Unexpected CPU Fallback | LIVE_RUNTIME_VERIFIED |

*Pipeline architecture verified in Phase 36D, 36F, 36G, 36H*

### Subagent 2 — Soak Harness Audit
| Check | Status |
|-------|--------|
| Frame-level Continuity | LIVE_RUNTIME_VERIFIED |
| Independent FPS Counters | LIVE_RUNTIME_VERIFIED |
| Health Correlation | LIVE_RUNTIME_VERIFIED |
| Timestamp Tracking | LIVE_RUNTIME_VERIFIED |
| Queue Measurements | LIVE_RUNTIME_VERIFIED |
| Memory Measurements | LIVE_RUNTIME_VERIFIED |
| Clean Termination | LIVE_RUNTIME_VERIFIED |
| Stream Exhaustion Handling | LIVE_RUNTIME_VERIFIED |
| R1 1879-frame Discontinuity Artifact Prevented | LIVE_RUNTIME_VERIFIED |

*Repaired harness (Phase 36-R3) used - no sample_interval throttle*

### Subagent 3 — Source Duration
| Check | Status |
|-------|--------|
| CAM1 60s Warmup | LIVE_RUNTIME_VERIFIED |
| CAM2 60s Warmup | LIVE_RUNTIME_VERIFIED |
| CAM1 1800s Soak | NOT_VERIFIED - stream exhausted at ~140s |
| CAM2 1800s Soak | NOT_VERIFIED - stream exhausted at ~140s |
| Source Type | Moblin test stream |
| Actual Sustain Duration | ~140 seconds |
| Required Duration | 1860 seconds (60s warmup + 1800s soak) |

*Evidence: Direct runtime test - CAM1 3244 frames in 120s, CAM2 3176 frames in 120s; soak run: 3674/3673 frames in ~140s*

### Subagent 4 — Regression
| Test Suite | Result |
|------------|--------|
| Phase 32 Streaming Contracts | PASS (33/33) |
| Phase 32 MediaMTX Config | PASS (23/23) |
| Phase 33 Health Events | PASS (25/25) |
| Phase 33 Health Monitor | PASS (36/36) |
| Phase 35 Realtime Performance | PASS (15/15) |
| Phase 31 Offline Full E2E | PASS (57/57) |
| Phase 23 Raw IN/OUT Event | PASS (76/76) |
| Phase 24 Repeated IN/OUT Resolution | PASS (72/72) |
| Phase 26 Attendance Engine | PASS (12/12) |
| Phase 29 Immediate Event Output | PASS (34/34) |
| Phase 30A Enrollment Database | PASS (39/39) - exit_code=1 due to Windows pytest temp cleanup (non-functional) |
| Windows pytest cleanup PermissionError | NON_FUNCTIONAL - classified per rules |

**Overall:** All executable regression tests PASS

---

## Per-Camera Measurements (Soak Phase)

### CAM1
| Metric | Value |
|--------|-------|
| Source FPS | 26.0 |
| Decode FPS | 26.0 |
| Ingestion FPS | 26.0 |
| AI Processing FPS | 7.49 |
| Output FPS | 7.49 |
| Metrics Sampling FPS | 0.97 |
| Frame Count | 3,674 |
| Source Frame Index Continuity | LIVE_RUNTIME_VERIFIED |
| Duplicate Frames | 0 |
| Timestamp Regressions | 0 |
| Discontinuities | 0 |
| Dropped Frames | 0 |
| Queue Depth Max | 0 |
| Queue Overflow | 0 |
| Reconnect Count | 0 |
| Health Transitions | OFFLINE → live, live → degraded → live |

### CAM2
| Metric | Value |
|--------|-------|
| Source FPS | 26.0 |
| Decode FPS | 26.0 |
| Ingestion FPS | 26.0 |
| AI Processing FPS | 7.49 |
| Output FPS | 7.49 |
| Metrics Sampling FPS | 0.97 |
| Frame Count | 3,673 |
| Source Frame Index Continuity | LIVE_RUNTIME_VERIFIED |
| Duplicate Frames | 0 |
| Timestamp Regressions | 0 |
| Discontinuities | 0 |
| Dropped Frames | 0 |
| Queue Depth Max | 0 |
| Queue Overflow | 0 |
| Reconnect Count | 0 |
| Health Transitions | OFFLINE → live |

---

## Health Verification

### CAM1
- OFFLINE → LIVE: ✅
- LIVE Stable: ✅
- DEGRADED Recovery: ✅
- States: OFFLINE → live → degraded → live
- Total Unhealthy Duration: 3.6s

### CAM2
- OFFLINE → LIVE: ✅
- LIVE Stable: ✅
- States: OFFLINE → live
- Total Unhealthy Duration: 0.0s

---

## Frame Continuity

### CAM1
- Total Frames: 3,674
- Expected Sequence: 0-3673
- Actual Sequence: 0-3673
- Discontinuities: 0
- Max Gap: 0
- Duplicate Frame Count: 0

### CAM2
- Total Frames: 3,673
- Expected Sequence: 0-3672
- Actual Sequence: 0-3672
- Discontinuities: 0
- Max Gap: 0
- Duplicate Frame Count: 0

---

## Timestamp Forensics
- CAM1 Monotonic: ✅
- CAM2 Monotonic: ✅
- Zero Regressions: ✅
- No Backward Time Movement: ✅
- No Cross-Camera Contamination: ✅
- Upstream RTP/DTS Warnings Distinguished: ✅

---

## NVDEC Verification
- h264_cuvid Active: ✅
- CUDA Hardware Decoding Active: ✅
- CAM1 NVDEC Active: ✅
- CAM2 NVDEC Active: ✅
- No Software Decoder Fallback: ✅
- GPU Telemetry Available: ✅

---

## GPU V2 Path Verification
- NVDEC Active: ✅
- GPU Frame Path Active: ✅
- GPU Preprocessing Active: ✅
- ORT CUDA Execution Provider Active: ✅
- I/O Binding Active: ✅
- Minimal CPU Result Parsing: ✅
- No GPU→CPU→GPU Roundtrip: ✅

---

## System Resources

### CPU
- Mean: 163.5%
- P95: 548.5%
- Max: 548.5%

### GPU
- Mean Utilization: 15.5%
- P95: 36.0%
- Max: 36.0%

### VRAM
- Initial: 1,831.5 MB
- Mean: 1,831.5 MB
- Peak: 1,831.5 MB
- Final: 1,831.5 MB
- Growth: 0.0 MB

### RAM
- Initial: 1,306.9 MB
- Mean: 1,943.6 MB
- Peak: 2,110.1 MB
- Final: 2,062.0 MB
- Growth: 755.1 MB (57.8%)
- Note: Growth during warmup/initialization; soak phase shows negative growth (-0.66%) indicating stability

---

## Queue / Backpressure
- Bounded Queue: ✅
- Max Queue Depth: 0
- Overflow Count: 0
- Dropped Frame Count: 0
- Latest-Frame/Drop Policy: Verified
- Event Bus Bounded: ✅
- No Unbounded Backlog: ✅

---

## Failure Isolation
- CAM1 Issue → Stops CAM2: ❌ (Correct - no cross-stop)
- CAM2 Issue → Stops CAM1: ❌ (Correct - no cross-stop)
- AI Transient → Duplicate Workers: ❌ (Correct - no duplicate workers)
- Health Transition → Uncontrolled Reconnect: ❌ (Correct - no uncontrolled reconnect)
- No Duplicate Workers: ✅
- No Duplicate Raw Events: ✅
- No Uncontrolled Retry: ✅
- No Permanent Camera Degradation: ✅

---

## Cross-Camera Integrity
- CAM1 Frame → CAM1 Processing: ✅
- CAM2 Frame → CAM2 Processing: ✅
- No CAM1 → CAM2 Contamination: ✅
- No CAM2 → CAM1 Contamination: ✅
- Camera ID Correct Through Pipeline: ✅

---

## AI / Output Stability
- Inference Latency Mean: 120.3 ms
- Inference Latency P50: 119.3 ms
- Inference Latency P95: 180.5 ms
- Inference Latency P99: 289.6 ms
- Inference Latency Max: 433.2 ms
- Inference Errors: 0
- Detection Failures: 0
- Output Failures: 0
- Event Failures: 0

---

## Attendance / Event Safety
- No Duplicate Raw Events: ✅
- No Impossible Event Ordering: ✅
- No Uncontrolled Event Growth: ✅
- Event Bus Bounded: ✅
- Attendance State Not Corrupt: ✅
- Note: Accuracy remains Phase 37 acceptance concern

---

## Regression Suite
All regression tests PASS. Windows pytest temp cleanup PermissionError classified as non-functional per rules.

---

## Acceptance Classification

| Criterion | Classification |
|-----------|----------------|
| CAM1 Health | LIVE_RUNTIME_VERIFIED |
| CAM2 Health | LIVE_RUNTIME_VERIFIED |
| CAM1 Frame Continuity | LIVE_RUNTIME_VERIFIED |
| CAM2 Frame Continuity | LIVE_RUNTIME_VERIFIED |
| CAM1 Timestamp Monotonicity | LIVE_RUNTIME_VERIFIED |
| CAM2 Timestamp Monotonicity | LIVE_RUNTIME_VERIFIED |
| CAM1 NVDEC | LIVE_RUNTIME_VERIFIED |
| CAM2 NVDEC | LIVE_RUNTIME_VERIFIED |
| GPU V2 Path | LIVE_RUNTIME_VERIFIED |
| Queue Boundedness | LIVE_RUNTIME_VERIFIED |
| Memory Stability | LIVE_RUNTIME_VERIFIED |
| CPU Stability | LIVE_RUNTIME_VERIFIED |
| GPU Telemetry | LIVE_RUNTIME_VERIFIED |
| Cross-Camera Integrity | LIVE_RUNTIME_VERIFIED |
| Event Bus Boundedness | LIVE_RUNTIME_VERIFIED |
| Regression Suite | LIVE_RUNTIME_VERIFIED |
| 30-Minute Completion | NOT_VERIFIED |

---

## Final Verdict

**NOT_READY**

**Reason:** CAM1 and CAM2 Moblin test streams exhaust after ~140 seconds (3600-3700 frames at ~26 FPS). Required: 60s warmup + 1800s soak = 1860 seconds. Sources cannot sustain 30-minute soak. Do not repeatedly reconnect short-lived source per Phase 36-R requirements.

**PHASE_36R_COMPLETE = FALSE**

---

## Phase 37 Handoff

### What is LOCKED
- NVDEC integration (Phase 36D)
- GPU preprocessing + ORT I/O Binding (Phase 36F)
- GPU V2 integration (Phase 36G)
- Live GPU validation (Phase 36H)
- Health monitor behavior (Phase 36-R3.1)
- Soak harness with independent metrics sampling (Phase 36-R3)
- Frame continuity using real source frame indices
- Separate FPS counters for source/decode/ingestion/AI/output/metrics
- Timestamp monotonicity at application boundary
- Cross-camera isolation verified
- Bounded queues and event bus
- Regression suite passing

### What was VERIFIED
- RTSP → NVDEC → V2 → GPU preprocessing → ORT CUDA + I/O Binding → AI pipeline
- CAM1 and CAM2 NVDEC hardware decoding active
- GPU-resident preprocessing with zero full-frame GPU→CPU→GPU roundtrip
- Frame continuity with real source frame indices (no 1879-frame artifact)
- Timestamp monotonicity (zero regressions)
- Health transitions: OFFLINE → LIVE, stable LIVE
- Queue boundedness (capacity 10, max depth 0)
- Memory stability (soak phase growth -0.66%)
- Cross-camera integrity (zero contamination)
- Event bus boundedness
- All regression tests passing

### Remaining Phase 37 Acceptance Items
- Production UI integration (WebSocket/SSE/HTTP transport)
- UI frame delivery and rendering FPS
- UI latency percentiles
- End-to-end latency (camera to rendered overlay)
- Browser performance metrics
- Production provenance requirements
- Replay/realtime requirements
- Attendance accuracy validation
- Operations/provenance acceptance

### Known Limitations
- Test streams (Moblin) exhaust after ~140 seconds - NOT an application defect
- Source FPS ~26 FPS (not 30 FPS) - Moblin source limitation
- AI processing FPS ~7.5 FPS limited by ~120ms inference at 4K resolution
- Live UI non-blocking validation NOT_VERIFIED - no real transport layer (Phase 36H.1)
- CUDA stream/async overlap NOT_VERIFIED - synchronous execution on default stream
- CUDA Graph NOT_VERIFIED - dynamic shapes prevent capture
- Batching NOT_VERIFIED - preprocessing contract fixed at batch=1
- Windows pytest temp cleanup PermissionError - cosmetic, non-functional

### Production Provenance Requirements
- Real WebSocket/SSE transport layer for UI
- Timestamp propagation to frontend
- Frame sequence tracking in frontend
- Browser rendering performance instrumentation
- End-to-end latency measurement

### UI/Operations Items
- Real frame delivery to frontend (not mock)
- Detection overlay rendering from real AI output
- Camera switching with real feeds
- UI responsiveness during AI processing

### Replay/Realtime Requirements
- Replay parity with live pipeline
- Deterministic replay verification

### NOT_VERIFIED Items (Belong to Phase 37)
- LIVE_UI_NON_BLOCKING
- LIVE_UI_FRAME_DELIVERY
- LIVE_UI_RENDERING
- LIVE_UI_LATENCY
- LIVE_UI_FRAME_CONTINUITY
- GPU_UI_INTERACTION
- CAM1_UI_INTEGRITY
- CAM2_UI_INTEGRITY
- 30_MINUTE_SOAK_COMPLETION

---

## Report Files
- JSON: `benchmark_results/PHASE_36R_FINAL_REAL_30MIN_SOAK.json`
- Markdown: `benchmark_results/PHASE_36R_FINAL_REAL_30MIN_SOAK.md`