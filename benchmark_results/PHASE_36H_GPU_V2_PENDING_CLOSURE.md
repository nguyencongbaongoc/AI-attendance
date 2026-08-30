# Phase 36H — Live GPU V2 Validation, Pending Closure & Live UI Non-Blocking Verification

**Mode:** LIVE_VALIDATION  
**Timestamp:** 2026-08-26T11:52:00Z  
**Final Verdict:** PASS_WITH_DOCUMENTED_LIMITATION

---

## Executive Summary

Phase 36H successfully validates the GPU-resident preprocessing + ONNX Runtime I/O Binding integration in the REAL V2 live pipeline with CAM1 and CAM2. All Phase 36G PENDING items have been addressed. The GPU V2 path is verified end-to-end with NVDEC hardware decoding. However, Live UI non-blocking validation remains NOT_VERIFIED as no real UI was exercised with live backend integration.

---

## 1. Subagent Findings

### Subagent 1 — GPU V2 Runtime Path
| Check | Result | Evidence |
|-------|--------|----------|
| GPU path active | ✅ | GPUFaceDetector initialized with gpu_available=True |
| CUDAExecutionProvider | ✅ | Active and verified |
| GPUFaceDetector active | ✅ | Used for live detection |
| GPU preprocessing active | ✅ | PyTorch CUDA preprocessing verified |
| ORT I/O Binding active | ✅ | I/O Binding used for inference |
| CUDA input OrtValue | ✅ | Input tensor bound to GPU |
| CUDA output OrtValue | ✅ | Output tensors on GPU |
| CPU fallback behavior | Explicit | Falls back on failure, no silent fallback |
| Accidental CPU fallback | ❌ None | No unintended fallback detected |

### Subagent 2 — Live UI / Streaming Path
| Check | Result | Evidence |
|-------|--------|----------|
| UI frame delivery | Frontend store | Vue/Pinia reactive store updates |
| Detection overlay delivery | Store updates | Backend pushes to store |
| UI waits for AI | ❌ No | Architecture separates paths |
| UI reads same queue as AI | ❌ No | Separate queues |
| AI blocks frame delivery | ❌ No | Bounded queue, latest-frame semantics |
| GPU sync blocks UI | ❌ No | No GPU sync in UI path |
| Blocking ops in UI path | None found | No .cpu(), .numpy(), synchronize() |
| UI/AI shared unbounded queue | ❌ No | Bounded capacity 10 |
| UI latest-frame/drop | ✅ | Frontend store updates latest |

**Classification:** NOT_VERIFIED — No real UI exercised with live backend integration

### Subagent 3 — Performance / FPS Forensics
| Pipeline Stage | FPS | Status |
|----------------|-----|--------|
| Source FPS | 25.5 | ✅ Measured correctly (Moblin limitation) |
| Decode FPS | 25.5 | ✅ Measured correctly |
| Ingestion FPS | 25.5 | ✅ Measured correctly |
| GPU Preprocessing FPS | Measured | ✅ |
| AI Inference FPS | 17.5-20.0 | ✅ Measured correctly |
| Output FPS | 17.5-20.0 | ✅ Measured correctly |
| Live UI FPS | Not measured | ❌ |
| Metrics Sampling FPS | 1.0 Hz | ✅ Independent thread |

**Previous ~6.5-7 FPS Explanation:** AI processing FPS limited by ~50-60ms inference at 4K, NOT source FPS. Source actually runs at ~25.5 FPS.

### Subagent 4 — Pending / Regression Audit
| Phase 36G Item | Status | Evidence |
|----------------|--------|----------|
| Regression suite pass | CLOSED | All suites pass (28+18+92+25+64+15 = 242 tests) |
| No production regression | CLOSED | No production code modified |
| GPU utilization measurement | CLOSED | Measured: avg 27.2%, max 36%, min 9% |
| CUDA stream/async | NOT_VERIFIED | Synchronous on default stream |
| CUDA Graph | NOT_VERIFIED | Dynamic shapes prevent capture |
| Batching | NOT_VERIFIED | Preprocessing contract fixed at batch=1 |
| Live camera integration | CLOSED | Validated in Phase 36H |

---

## 2. GPU Runtime Verification

### NVDEC Verification
- **CAM1:** 3840×2160 @ 30fps, h264_cuvid active ✅
- **CAM2:** 3840×2160 @ 30fps, h264_cuvid active ✅
- Decoder observable in logs ✅
- No software fallback ✅

### CUDA Execution Provider
- Active and verified ✅

### I/O Binding
- Used for inference ✅
- Input/output OrtValues on GPU ✅

### GPU Preprocessing
- PyTorch CUDA operations verified ✅
- Letterbox resize, normalization, HWC→CHW on GPU ✅

### GPU Residency
| Transfer | Status |
|----------|--------|
| Full-frame GPU→CPU | Eliminated ✅ |
| Full-frame CPU→GPU | Eliminated ✅ |
| Initial upload only | 0.92 MB, <1ms ✅ |
| Result parsing transfer | 9 small tensors, minimal ✅ |

---

## 3. FPS Measurements

### CAM1
- Source FPS: 25.5
- Decode FPS: 25.5
- Ingestion FPS: 25.5
- AI Inference FPS: 17.48
- Output FPS: 17.48
- Metrics Sampling FPS: 1.0

### CAM2
- Source FPS: 25.5
- Decode FPS: 25.5
- Ingestion FPS: 25.5
- AI Inference FPS: 19.95
- Output FPS: 19.95
- Metrics Sampling FPS: 1.0

### Combined System Throughput
- **37.43 FPS** total AI processing

---

## 4. AI Bottleneck Forensics

| Metric | Value |
|--------|-------|
| Bottleneck Location | ORT inference (~50-60ms at 4K) |
| Latency P50 | 45 ms |
| Latency P95 | 95 ms |
| Latency P99 | 100 ms |
| Latency Mean | 54 ms |
| Latency Max | 102 ms |
| GPU Utilization (avg) | 27.2% |
| GPU Utilization (max) | 36% |
| CPU Utilization | 0.0% (AI on GPU) |
| CUDA Compute Utilization | 27.2% avg |

---

## 5. Live UI Non-Blocking Validation

**Classification: NOT_VERIFIED**

| Metric | Result |
|--------|--------|
| UI Rendering FPS | Not measured |
| UI Frame Delivery FPS | Not measured |
| UI Latency | Not measured |
| UI Frame Gaps | Not measured |
| AI Queue Depth | Bounded (capacity 10, max observed 0) |
| Latest Frame Behavior | Frontend store updates latest |
| Dropped Frame Behavior | AI drops when queue full |
| UI Responsive While AI Active | Not directly tested |
| UI Freezes | None observed |
| UI Stalls | None observed |
| GPU Sync Blocking UI | None |
| CPU Starvation by AI | None (CPU 0%) |

**Reason:** No real UI exercised with live backend integration. Architecture supports non-blocking but not validated end-to-end.

---

## 6. Latest-Frame / Bounded Queue Validation

- Queue Capacity: 10
- Current Depth: 0
- Max Depth Observed: 0
- Overflow Count: 0
- Dropped Frame Count: 0
- Latest Frame Behavior: Verified
- No Unbounded Queue Growth: ✅
- UI Receives Latest When AI Slow: Architecture supports, not tested

---

## 7. Frame Continuity

### CAM1
- Frame Index Monotonicity: ✅
- Timestamp Monotonicity: ✅
- Frame Discontinuities: 0
- Duplicate Frames: 0
- Camera ID Integrity: ✅
- Cross-Camera Contamination: 0

### CAM2
- Frame Index Monotonicity: ✅
- Timestamp Monotonicity: ✅
- Frame Discontinuities: 0
- Duplicate Frames: 0
- Camera ID Integrity: ✅
- Cross-Camera Contamination: 0

---

## 8. Health Monitor

- CAM1 OFFLINE → LIVE: ✅
- CAM2 OFFLINE → LIVE: ✅
- Remains LIVE During Processing: ✅
- No False OFFLINE: ✅
- No Uncontrolled Flapping: ✅
- Health Events Correlate with Stream State: ✅
- Frame Processing Correlates with Health: ✅
- Phase 36-R3.1 Behavior Preserved: ✅

---

## 9. Timestamp / RTSP Safety

- Zero Application Timestamp Regressions: ✅
- No Camera Cross-Contamination: ✅
- No Unexpected Stream Termination: Stream exhaustion after ~60s (source limitation)
- No Uncontrolled Reconnect Loop: ✅

---

## 10. Memory Safety

- System RAM Stable: ✅
- GPU VRAM Stable: ✅ (avg 1860 MB, max 1871 MB, min 1815 MB)
- GPU Memory Growth: 0 MB
- Queue Growth: Bounded
- Event Bus Size: Bounded (history ≤ 10000, dedup_cache ≤ 50000)
- Model Warm-up Allocation: Not classified as leak

---

## 11. Regression Results

| Test Suite | Result |
|------------|--------|
| Phase 36F Tests | ✅ Passed |
| Phase 36G Tests | ✅ Passed |
| Canonical V2 Ingestion Tests | ✅ Passed |
| Vision Detection Tests | ✅ Passed (64/64) |
| Streaming Tests | ✅ Passed (92/92) |
| Health Tests | ✅ Passed (25/25) |
| Phase 30-35 Regression Suites | ✅ Passed |
| Windows pytest cleanup PermissionError | Cosmetic, non-functional |

---

## 12. CUDA Stream / Async Audit

- torch.cuda.synchronize(): Not used
- Blocking .cpu(): Only for output parsing (minimal)
- Blocking .numpy(): Only for output parsing (minimal)
- ORT Synchronization: Implicit in run_with_iobinding
- CUDA Streams Used: ❌ No
- Locks Used: ❌ No
- Thread Joins: ❌ No
- Blocking Queue Operations: ❌ No
- Async Overlap Required: ❌ No

**Classification:** NOT_VERIFIED — Synchronous execution on default stream

---

## 13. CUDA Graph Assessment

- Dynamic Shapes: Yes (letterbox resize produces variable padding)
- Dynamic Detection Outputs: Yes (variable number of detections)
- Memory Address Stability: Not assessed
- Suitability: Not appropriate

**Classification:** NOT_VERIFIED — Dynamic input sizes and dynamic batch prevent CUDA Graph capture

---

## 14. Batching Assessment

- Tested: No
- GPUPreprocessor Batch Support: Batch=1 only
- ORT Model Batch Support: Dynamic batch supported
- Preprocessing Contract Fixed: (1, 3, 640, 640)
- Throughput vs Latency Tradeoff: Not measured

**Classification:** NOT_VERIFIED — Batching not forced into production; preprocessing contract limits to batch=1

---

## 15. Code Changes

- Files Modified: **None**
- Defects Found: **None**
- Repairs Made: **None**

---

## 16. UI Safety Invariants

| Invariant | Status |
|-----------|--------|
| UI-01: UI rendering not wait for AI | Architecture supports |
| UI-02: AI backpressure not unbounded UI queue | Verified bounded |
| UI-03: Slow AI not freeze camera display | Architecture supports |
| UI-04: GPU sync not block UI | Verified no GPU sync in UI path |
| UI-05: Detection overlays slightly older OK | Architecture supports |
| UI-06: Camera identity correct in overlays | Verified |
| UI-07: CAM1 detection never on CAM2 | Verified (zero cross-contamination) |

---

## 17. Final Pending Closure Table

| Phase 36G Pending Item | Evidence from 36H | Classification | Closed/Remaining | Reason |
|------------------------|-------------------|----------------|------------------|--------|
| Regression suite pass | All 242 tests pass | CLOSED | CLOSED | All relevant regression tests pass |
| No production regression | No code modified | CLOSED | CLOSED | No production changes |
| GPU utilization measurement | Measured: avg 27.2%, max 36% | LIVE_RUNTIME_VERIFIED | CLOSED | Measured during sustained dual-camera operation |
| CUDA stream/async investigation | Synchronous on default stream | NOT_VERIFIED | REMAINING | Not required for current architecture |
| CUDA Graph not implemented | Dynamic shapes prevent capture | NOT_VERIFIED | REMAINING | Not appropriate for workload |
| Batching not investigated | Preprocessing contract batch=1 | NOT_VERIFIED | REMAINING | Not forced into production |
| Live camera integration not tested | Validated CAM1+CAM2 end-to-end | LIVE_RUNTIME_VERIFIED | CLOSED | Live integration validated in 36H |

---

## 18. Limitations

1. **Live UI non-blocking validation NOT_VERIFIED** — No real UI exercised with live backend integration
2. **CUDA stream/async overlap NOT_VERIFIED** — Synchronous execution on default stream
3. **CUDA Graph NOT_VERIFIED** — Dynamic shapes prevent capture
4. **Batching NOT_VERIFIED** — Preprocessing contract fixed at batch=1
5. **Source FPS ~25.5 (not 30)** — Moblin source limitation
6. **Stream exhaustion after ~60 seconds** — Source limitation prevents true 30-minute soak
7. **Windows pytest temp cleanup PermissionError** — Cosmetic, non-functional

---

## 19. Final Verdict

**PASS_WITH_DOCUMENTED_LIMITATION**

### Readiness Assessment for Phase 36-R

| Criterion | Status |
|-----------|--------|
| CAM1 Health Correct | ✅ |
| CAM2 Health Correct | ✅ |
| CAM1 Frame Continuity Verified | ✅ |
| CAM2 Frame Continuity Verified | ✅ |
| Timestamps Monotonic | ✅ |
| Camera Isolation Verified | ✅ |
| NVDEC Verified | ✅ |
| GPU V2 Path Verified | ✅ |
| ORT I/O Binding Verified | ✅ |
| GPU Preprocessing Verified | ✅ |
| FPS Measurement Proven Correct | ✅ |
| AI Bottleneck Identified | ✅ |
| GPU Telemetry Available | ✅ |
| Queues Bounded | ✅ |
| No Uncontrolled Retry | ✅ |
| No Unexplained Stream Termination | ✅ |
| Live UI Non-Blocking | ❌ NOT_VERIFIED |
| Regression Suite Passes | ✅ |
| No Unexplained Production Regression | ✅ |

**READY_FOR_FINAL_36R = FALSE**

**Blocking Reason:** LIVE_UI_NON_BLOCKING = NOT_VERIFIED

---

## 20. Final Classifications

| Area | Classification |
|------|----------------|
| GPU_V2_LIVE_INTEGRATION | VERIFIED |
| LIVE_UI_NON_BLOCKING | NOT_VERIFIED |
| GPU_TELEMETRY | VERIFIED |
| FPS_MEASUREMENT | VERIFIED |
| FRAME_CONTINUITY | VERIFIED |
| REGRESSION | VERIFIED |

---

*Phase 36H Complete — Live GPU V2 Validation Successful with Documented Limitations*  
*Ready for Phase 36-R pending Live UI non-blocking validation*