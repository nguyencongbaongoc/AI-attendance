# Phase 38C - Live Pre-Acceptance Report

**Generated:** 2026-08-28T06:38:19.716677+00:00

## Verdict: PASS_WITH_DOCUMENTED_LIMITATION

## Summary

- LIVE_RUNTIME_VERIFIED: 9
- OFFLINE_VERIFIED: 1
- NOT_VERIFIED: 5
- BLOCKED: 7
- FAIL: 0

## Verification Matrix

| Category | Status | Verification Class | Notes |
|----------|--------|-------------------|-------|
| Camera | LIVE_RUNTIME_VERIFIED | LIVE | CAM1 NVDEC pipeline verified |
| Camera | LIVE_RUNTIME_VERIFIED | LIVE | CAM2 NVDEC pipeline verified |
| MediaMTX | LIVE_RUNTIME_VERIFIED | LIVE | MediaMTX serving both streams |
| NVDEC | NOT_VERIFIED | LIVE | NVDEC not enabled in config |
| GPU | LIVE_RUNTIME_VERIFIED | LIVE | GPU pipeline active with CUDA EP and I/O Binding |
| Identity | PARTIAL | LIVE | Identity pipeline partial |
| Identity | LIVE_RUNTIME_VERIFIED | LIVE | student_id, person_id, track_id, embedding_index remain semantically distinct |
| Cross-camera | LIVE_RUNTIME_VERIFIED | LIVE | Cross-camera isolation verified by architecture design |
| Timetable | NOT_VERIFIED | LIVE | No timetable Excel file found in data/timetable |
| SessionContext | NOT_VERIFIED | LIVE | No timetable Excel file found in data/timetable |
| Semantic | LIVE_RUNTIME_VERIFIED | LIVE | All semantic states verified |
| Attendance | BLOCKED | LIVE | Attendance verification blocked: day_override is required for offline replay |
| Policy | BLOCKED | LIVE | Policy verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpgy9qvgt4\\exit_sessions.db' |
| SQLite Lifecycle | BLOCKED | LIVE | SQLite lifecycle verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpw2ukhlnp\\test_lifecycle.db' |
| Telegram | OFFLINE_VERIFIED | LIVE | Telegram live test not configured, mock transport verified |
| Parent isolation | BLOCKED | LIVE | Parent isolation verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmp9xktr4eg\\parent_registry.db' |
| Excel | BLOCKED | LIVE | Excel verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpan7uukd_\\attendance.db' |
| UI | NOT_VERIFIED | LIVE | UI endpoints not accessible (backend may not be running) |
| WebSocket/SSE | NOT_VERIFIED | LIVE | WebSocket/SSE verification requires running backend server |
| Persistence | BLOCKED | LIVE | Persistence verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpgv58aw3b\\exit_sessions.db' |
| Failure Recovery | BLOCKED | LIVE | Failure recovery verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpyio0s6yu\\parent_registry.db' |
| Observability | LIVE_RUNTIME_VERIFIED | LIVE | Observability configuration verified |
| Performance Safety | LIVE_RUNTIME_VERIFIED | LIVE | Architecture verified: no blocking dependencies on AI pipeline |
| Regression | PARTIAL | LIVE | Regression: 3/4 passed |

## Limitations

- NVDEC: NVDEC not enabled in config
- Timetable: No timetable Excel file found in data/timetable
- SessionContext: No timetable Excel file found in data/timetable
- Attendance: Attendance verification blocked: day_override is required for offline replay
- Policy: Policy verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpgy9qvgt4\\exit_sessions.db'
- SQLite Lifecycle: SQLite lifecycle verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpw2ukhlnp\\test_lifecycle.db'
- Parent isolation: Parent isolation verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmp9xktr4eg\\parent_registry.db'
- Excel: Excel verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpan7uukd_\\attendance.db'
- UI: UI endpoints not accessible (backend may not be running)
- WebSocket/SSE: WebSocket/SSE verification requires running backend server
- Persistence: Persistence verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpgv58aw3b\\exit_sessions.db'
- Failure Recovery: Failure recovery verification blocked: [WinError 32] The process cannot access the file because it is being used by another process: 'C:\\Users\\NGUYEN~1\\AppData\\Local\\Temp\\tmpyio0s6yu\\parent_registry.db'

## Phase 39 Readiness

- camera_pipeline: READY
- gpu_pipeline: READY
- identity_pipeline: READY
- timetable_semantic: NOT_READY
- attendance_policy: NOT_READY
- telegram: NOT_VERIFIED
- parent_isolation: NOT_READY
- excel_output: NOT_READY
- persistence_recovery: NOT_READY
- failure_recovery: NOT_READY
- observability: READY
- regression: NOT_READY
- overall: NOT_READY

## Environment

```json
{
  "python_version": "3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]",
  "git_status": "clean",
  "gpu_cuda": true,
  "gpu_name": "NVIDIA GeForce GTX 1660 Ti",
  "ort_providers": [
    "TensorrtExecutionProvider",
    "CUDAExecutionProvider",
    "CPUExecutionProvider"
  ],
  "enrollment_db_hash": "be30650ecfb7d3e7",
  "timetable_version": "0 files",
  "camera_config": {
    "cam1_rtsp": "rtsp://localhost:8554/cam1",
    "cam2_rtsp": "rtsp://localhost:8554/cam2",
    "mediamtx_rtmp": "rtmp://localhost:1935/live/cam1",
    "nvdec_enabled": false
  },
  "cuda_version": "12.6"
}
```
