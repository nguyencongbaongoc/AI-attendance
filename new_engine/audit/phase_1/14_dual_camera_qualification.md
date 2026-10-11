# Gate G — Dual-Camera Qualification Design

**Date:** 2026-10-04  
**Phase:** 1  
**Gate:** G  
**Status:** DESIGN PHASE — Requires camera streams and backend  

---

## 1. Objective

Test CAM1 and CAM2 separately, then concurrently with sustained runtime evidence.

---

## 2. Qualification Stages

| Stage | Description | Duration | Target |
|-------|-------------|----------|--------|
| 1 | CAM1 startup and inference | 10 min | RUNNING state, healthy |
| 2 | CAM2 startup and inference | 10 min | RUNNING state, healthy |
| 3 | Dual-camera concurrent | 30 min | Both RUNNING, no interference |
| 4 | Reconnect test | 5 min | Graceful recovery |
| 5 | Sustained runtime | 30 min concurrent | Stable metrics |
| 6 | Event delivery test | During above | Events → Backend → AttendanceRecord |
| 7 | Worker shutdown/restart | 2 min | Clean stop/start |

---

## 3. Measured Metrics (Per Camera)

| Metric | Source | Target |
|--------|--------|--------|
| Received FPS | RTSPSource | ~30 |
| Decoded FPS | NVDECDecoder | ~30 |
| Inference FPS | Pipeline loop | ~15-30 |
| Detection latency | SCRFD.infer | < 50ms |
| ArcFace latency | ArcFace.infer | < 30ms |
| Tracking latency | Tracker | < 10ms |
| End-to-end event latency | Event timestamp → Backend ack | < 2s |
| GPU utilization | nvidia-smi / torch | < 90% |
| VRAM usage | torch.cuda.memory_reserved | < 5.5GB |
| CPU utilization | psutil | < 80% |
| RAM usage | psutil | < 8GB |
| Queue depth | Decoder + Encoder | < 8 |
| Dropped frames | CameraMetrics | 0 |
| Reconnect count | RTSPSource | 0 (ideal) |
| Failed events | EventDeliveryClient | 0 |
| Worker health state | Health reports | RUNNING |

---

## 4. Test Environment Requirements

### 4.1 Hardware
- GPU: GTX 1660 Ti (6GB VRAM) or better
- CPU: 6+ cores
- RAM: 16GB+
- Network: Gigabit for camera streams

### 4.2 Services
- MediaMTX running on localhost:1935/8554/9997
- Camera streams publishing to MediaMTX (RTMP)
- Legacy Backend API running on dynamic port
- API keys configured:
  - AI_WORKER_API_KEY
  - AI_CONTROL_API_KEY
  - ADMIN_API_KEY

### 4.3 Camera Streams
- Two RTMP streams to MediaMTX:
  - `rtmp://localhost:1935/live/cam1`
  - `rtmp://localhost:1935/live/cam2`
- 3840×2160 @ 30fps H.264 (or available resolution)
- Stable stream for test duration

---

## 5. Test Procedures

### Stage 1: CAM1 Only
1. Start MediaMTX
2. Start CAM1 stream only
3. Start Backend
4. Start Worker
5. Verify: Worker → RUNNING, CAM1 healthy
6. Run for 10 min
7. Collect metrics every 30s
8. Verify no memory leaks, stable FPS

### Stage 2: CAM2 Only
1. Stop Worker
2. Switch to CAM2 stream only
3. Start Worker
4. Verify: Worker → RUNNING, CAM2 healthy
5. Run for 10 min
6. Collect metrics

### Stage 3: Dual Camera
1. Start both CAM1 and CAM2 streams
2. Start Worker
3. Verify: Worker → RUNNING, both cameras healthy
4. Run for 30 min
5. Collect metrics for both cameras
5. Verify no cross-camera interference

### Stage 4: Reconnect Test
1. With Worker running dual-camera
2. Stop CAM1 stream at MediaMTX
3. Verify: CAM1 → UNHEALTHY → RECONNECTING → RUNNING
4. Restart CAM1 stream
5. Verify recovery within reconnect timeout

### Stage 5: Event Delivery
1. During Stage 3, have person cross line
2. Verify CrossingEvent generated
3. Verify EventDeliveryClient delivers
4. Verify Backend accepts (source_resolution_id)
5. Verify AttendanceRecord in database

### Stage 6: Shutdown/Restart
1. Send STOP_WORKER via Backend control API
2. Verify Worker → STOPPED cleanly
3. Send START_WORKER
4. Verify Worker → RUNNING
5. Verify state preserved (enrollment, config)

---

## 6. Acceptance Criteria

### PASS Requirements
- All 3 stages complete without Worker crash
- Both cameras maintain RUNNING for full duration
- Zero failed event deliveries
- Zero frame drops (or documented acceptable rate)
- GPU VRAM < 5.5GB sustained
- No memory growth > 100MB over 30 min
- All events traceable to AttendanceRecord

### PARTIAL If
- Single camera passes but dual fails
- Duration reduced due to environment
- Minor metric deviations documented

### BLOCKED If
- Worker crashes
- Camera streams unavailable
- Backend unavailable
- GPU OOM

---

## 7. Evidence Collection

For each stage, collect:
- Worker status logs (every 30s)
- Camera metrics (from health endpoint)
- Event delivery stats
- GPU/CPU/RAM snapshots (nvidia-smi, psutil)
- Backend attendance records count
- AttendanceRecord provenance verification

---

## 8. Gate G Verdict

**DESIGN COMPLETE** — Test plan defined, metrics specified.

**BLOCKED BY:** Camera streams, MediaMTX, Backend not running in test environment.

**Ready for Gate H** — Failure & Recovery