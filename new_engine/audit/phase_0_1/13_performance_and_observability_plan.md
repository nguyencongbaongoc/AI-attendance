# Performance and Observability Plan

## Performance Requirements (Architecture A)

### Target Specification
- **Two cameras** @ 4K (3840×2160) 30 FPS
- **Original video path**: MediaMTX passthrough (no AI processing)
- **Independent AI path**: PyAV → Decode → Inference → Tracking → Attendance
- **Existing AI models**: SCRFD 10G, ArcFace (GlintR100), YOLO11n
- **No silent frame dropping**
- **No automatic resolution reduction**
- **No automatic FPS reduction**
- **No disabling models to hide overload**
- **No silent CPU fallback**

### Hardware Constraints
- **GPU**: NVIDIA GTX 1660 Ti (6GB VRAM, Turing, no true NVDEC on Windows)
- **CPU**: Intel Core i7-10700K (8 cores, 16 threads)
- **RAM**: 16GB DDR4
- **Storage**: NVMe SSD

---

## Required Measurements

### Per-Camera Metrics (Continuous)

| Metric | Target | Alert Threshold | Measurement Method |
|--------|--------|-----------------|-------------------|
| **Input FPS** | 30.0 | < 25 | RTSP packet rate |
| **Decode FPS** | ≥ 25 | < 20 | FramePool acquisition rate |
| **AI Inference FPS** | ≥ 20 | < 15 | Inference completion rate |
| **Tracking FPS** | ≥ 25 | < 20 | Tracker process_frame rate |
| **Attendance Latency** | < 100ms | > 500ms | Event timestamp vs capture_timestamp |
| **End-to-End AI Latency** | < 200ms | > 500ms | capture_timestamp → event POST |
| **Queue Depth** | < 5 | > 10 | FramePool + inference queue |
| **Frame Age** | < 100ms | > 500ms | capture_timestamp vs now |
| **Dropped Frames** | 0 | > 0 | FramePool exhaustion count |
| **Reconnect Count** | 0 | > 0 | RTSP source reconnects |
| **Decode Errors** | 0 | > 0 | NVDEC error counter |

### System-Level Metrics

| Metric | Target | Alert Threshold | Measurement Method |
|--------|--------|-----------------|-------------------|
| **GPU Utilization** | 60-80% | > 95% | nvidia-smi / torch.cuda |
| **VRAM Usage** | < 4.5GB | > 5.5GB | torch.cuda.memory_reserved |
| **CPU Utilization** | < 70% | > 90% | psutil |
| **System RAM** | < 12GB | > 14GB | psutil |
| **Disk I/O** | < 50MB/s | > 200MB/s | psutil |
| **Network I/O** | < 100Mbps | > 500Mbps | psutil |

### AI Model Performance (Per Inference)

| Model | Target Latency | Max Latency | Batch Size |
|-------|----------------|-------------|------------|
| SCRFD (640×640) | 8ms | 20ms | 1-4 |
| YOLO11n (640×640) | 8ms | 20ms | 1-4 |
| ArcFace (112×112) | 3ms/face | 10ms/face | 1-16 |

---

## Observability Architecture

### Metrics Collection

#### 1. AI Worker Metrics (Prometheus Format)
```
/metrics endpoint on each AI Worker (port 9090+)

# HELP ai_input_fps Frames per second received from RTSP
# TYPE ai_input_fps gauge
ai_input_fps{camera_id="cam1",stream_epoch="3"} 29.8

# HELP ai_decode_fps Frames per second decoded
# TYPE ai_decode_fps gauge
ai_decode_fps{camera_id="cam1",stream_epoch="3"} 29.5

# HELP ai_inference_fps Inferences per second
# TYPE ai_inference_fps gauge
ai_inference_fps{camera_id="cam1",model="scrfd"} 28.0

# HELP ai_tracking_fps Tracks processed per second
# TYPE ai_tracking_fps gauge
ai_tracking_fps{camera_id="cam1"} 28.0

# HELP ai_attendance_events_total Total attendance events
# TYPE ai_attendance_events_total counter
ai_attendance_events_total{camera_id="cam1",direction="in"} 142

# HELP ai_latency_seconds End-to-end latency
# TYPE ai_latency_seconds histogram
ai_latency_seconds_bucket{camera_id="cam1",le="0.1"} 1200
ai_latency_seconds_bucket{camera_id="cam1",le="0.2"} 1350
ai_latency_seconds_bucket{camera_id="cam1",le="0.5"} 1420

# HELP ai_queue_depth Frames waiting in pipeline
# TYPE ai_queue_depth gauge
ai_queue_depth{camera_id="cam1",stage="inference"} 3

# HELP ai_gpu_memory_bytes VRAM usage
# TYPE ai_gpu_memory_bytes gauge
ai_gpu_memory_bytes{worker="ai_worker_cam1"} 3523215360

# HELP ai_dropped_frames_total Frames dropped due to backpressure
# TYPE ai_dropped_frames_total counter
ai_dropped_frames_total{camera_id="cam1"} 0
```

#### 2. Legacy Backend Metrics (Existing + Extended)
```
# Existing health metrics + new AI worker metrics
ai_worker_health{worker_id="ai_worker_cam1",camera_id="cam1"} 1
ai_worker_events_total{worker_id="ai_worker_cam1"} 142
ai_worker_last_event_timestamp{worker_id="ai_worker_cam1"} 1234567890.123
```

### Logging Structure

#### Structured JSON Logs (AI Worker)
```json
{
  "timestamp": "2026-10-04T08:15:30.123Z",
  "level": "INFO",
  "worker_id": "ai_worker_cam1",
  "camera_id": "cam1",
  "stream_epoch": 3,
  "event": "frame_processed",
  "frame_index": 12345,
  "frame_pts": 2700000,
  "latency_ms": {
    "decode": 8.2,
    "preprocess": 2.1,
    "scrfd": 7.8,
    "yolo": 8.5,
    "arcface": 3.2,
    "tracking": 1.1,
    "attendance": 0.8,
    "total": 31.5
  },
  "queue_depth": {
    "decode": 2,
    "inference": 3,
    "tracking": 1
  },
  "gpu": {
    "memory_mb": 3420,
    "utilization_pct": 68
  }
}
```

#### 3. Event Logs (Attendance)
```json
{
  "timestamp": "2026-10-04T08:15:30.123Z",
  "level": "INFO",
  "worker_id": "ai_worker_cam1",
  "camera_id": "cam1",
  "event": "attendance_crossing",
  "crossing": {
    "event_id": "CE-42-12345-1234567890123",
    "track_id": "track_42",
    "direction": "IN",
    "crossing_point": [1500, 1080],
    "identity": {
      "person_id": "NV001",
      "confidence": 0.94,
      "certainty": "KNOWN"
    }
  },
  "latency_ms": {
    "capture_to_event": 45.2,
    "event_to_post": 12.3
  }
}
```

### Health States

| State | Criteria | Action |
|-------|----------|--------|
| **HEALTHY** | All metrics within targets | Normal operation |
| **DEGRADED** | Any metric at alert threshold | Alert, investigate, continue |
| **UNHEALTHY** | Any metric at critical threshold OR 3+ degraded | Alert, attempt recovery, page on-call |
| **CRITICAL** | GPU OOM, decode failure, Legacy Backend unreachable | Emergency restart, page on-call |

### Alerting Rules

| Alert | Condition | Severity | Notification |
|-------|-----------|----------|--------------|
| `AIWorkerDown` | No health report for 30s | CRITICAL | Page |
| `GPUMemoryCritical` | VRAM > 5.5GB | CRITICAL | Page |
| `InputFPSLow` | Input FPS < 25 for 60s | WARNING | Alert |
| `DecodeFPSLow` | Decode FPS < 20 for 60s | WARNING | Alert |
| `InferenceFPSLow` | Inference FPS < 15 for 60s | WARNING | Alert |
| `EndToEndLatencyHigh` | P99 latency > 500ms for 5min | WARNING | Alert |
| `FrameDropped` | Any frames dropped | WARNING | Alert |
| `ReconnectStorm` | > 3 reconnects in 60s | WARNING | Alert |
| `EventPostFail` | Event POST fails > 5 consecutive | CRITICAL | Page |
| `NPYReloadFailed` | NPY reload fails | WARNING | Alert |

### Dashboard Panels (Grafana)

#### Overview Dashboard
- **System Health**: Overall status, uptime
- **Camera Grid**: 2×2 panels per camera (Input FPS, Decode FPS, AI FPS, Latency)
- **GPU Panel**: VRAM, Utilization, Temperature, Power
- **Event Rate**: Attendance IN/OUT per minute
- **Queue Depths**: Decode, Inference, Tracking, Event POST
- **Error Rates**: Decode, Inference, POST errors

#### AI Worker Detail Dashboard (per worker)
- **Pipeline Stages**: Latency waterfall (decode → preprocess → scrfd → yolo → arcface → tracking → attendance)
- **Batch Efficiency**: Batch size distribution, queue wait time
- **Model Performance**: Per-model latency percentiles
- **Tracking Quality**: Active tracks, ID switches, lost tracks
- **Memory**: VRAM breakdown (models, frames, temp tensors)

---

## Performance Qualification Plan

### Phase 1: Baseline Measurement (Single Camera)
1. Start single AI Worker with Camera 1
2. Run for 30 minutes with synthetic/real stream
3. Record all metrics at 10s intervals
4. Establish baseline percentiles (P50, P90, P99, P99.9)

### Phase 2: Dual Camera Load Test
1. Start both AI Workers (cam1, cam2)
2. Run for 60 minutes
3. Measure contention: GPU memory, inference queue
4. Verify no silent frame dropping

### Phase 3: Stress Test
1. Reduce FramePool size to force pressure
2. Simulate network latency (tc qdisc)
3. Force RTSP reconnects (kill MediaMTX temporarily)
4. Measure recovery time

### Phase 4: Long-Run Stability
1. Run 24 hours continuous
2. Monitor for memory leaks, drift, degradation
3. Verify no silent degradation

### Phase 5: Architecture A Integration Test
1. Full stack: MediaMTX + 2 AI Workers + Legacy Backend + UI
2. End-to-end latency measurement (event → UI overlay)
3. Timestamp sync verification
4. Reconnect handling verification

---

## Telemetry Data Model

### Frame-Level Telemetry (Sampled 1%)
```python
@dataclass
class FrameTelemetry:
    camera_id: str
    stream_epoch: int
    frame_index: int
    frame_pts: int
    time_base_num: int
    time_base_den: int
    capture_timestamp: float
    stage_timestamps: Dict[str, float]  # stage -> wall-clock
    stage_durations_ms: Dict[str, float]  # stage -> ms
    gpu_memory_mb: float
    queue_depths: Dict[str, int]
```

### Event-Level Telemetry (100%)
```python
@dataclass
class EventTelemetry:
    event_id: str
    camera_id: str
    stream_epoch: int
    frame_pts: int
    capture_timestamp: float
    processing_timestamp: float
    post_timestamp: float
    ack_timestamp: float  # Legacy Backend ACK
    latency_breakdown_ms: Dict[str, float]
```

---

## Implementation Checklist

### AI Worker Instrumentation
- [ ] Add Prometheus metrics endpoint (`/metrics`)
- [ ] Add structured JSON logging
- [ ] Add frame-level telemetry sampling
- [ ] Add event-level telemetry
- [ ] Add health state machine
- [ ] Add `/health` endpoint for Legacy Backend polling

### Legacy Backend Instrumentation
- [ ] Add AI worker metrics aggregation
- [ ] Add AI worker health WebSocket broadcasts
- [ ] Add attendance event latency tracking
- [ ] Add dashboard panels

### Alerting
- [ ] Configure Prometheus alert rules
- [ ] Configure Alertmanager routes
- [ ] Test alert firing and resolution

---

## Evidence References

| Source | File | Relevant |
|--------|------|----------|
| PipelineEngine MemoryMonitor | `pipeline_engine/memory/memory_monitor.py` | Pressure levels, callbacks |
| PipelineEngine CameraManager | `pipeline_engine/ingestion/camera_manager.py` | Per-stage timing (lines 692-737) |
| Legacy Backend Health | `app/api/health.py` | Camera metrics, GPU status |
| Legacy Backend WebSocket | `app/api/websocket.py` | Real-time broadcasts |
| PipelineEngine GPUFrame | `pipeline_engine/memory/gpu_frame.py` | Latency breakdown fields |

---

## Status

**PLAN DOCUMENTED** - Ready for implementation in Phase 1

**Blockers for Execution**:
- No running AI Workers to instrument
- No Prometheus/Grafana stack deployed
- No Legacy Backend running to receive metrics