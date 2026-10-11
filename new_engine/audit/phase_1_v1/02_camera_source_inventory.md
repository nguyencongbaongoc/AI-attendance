# Phase 1.V1 Camera Source Inventory

**Date**: 2026-10-04
**Phase**: 1.V1 - Environment and Camera Source Recovery

---

## 1. MediaMTX Path Inventory

### Active Paths (from `/v3/paths/list` API)

| Path | Conf Name | Ready | Available | Online | Source Type | Source ID |
|------|-----------|-------|-----------|--------|-------------|-----------|
| live/cam1 | live/cam1 | ✅ true | ✅ true | ✅ true | rtmpConn | b8fe2427-9b3f-4062-b5dc-14aef7d47bbc |
| live/cam1-ai | live/cam1-ai | ❌ false | ❌ false | ❌ false | - | - |
| live/cam2 | live/cam2 | ✅ true | ✅ true | ✅ true | rtmpConn | a51e51e5-ca05-419a-8c01-92e295025301 |
| live/cam2-ai | live/cam2-ai | ❌ false | ❌ false | ❌ false | - | - |

### Stream Properties (cam1)
- **Video Codec**: H264
- **Profile**: Main
- **Level**: 5.1
- **Resolution**: 3840 × 2160 (4K)
- **Audio Codec**: MPEG-4 Audio (AAC)
- **Sample Rate**: 44100 Hz
- **Channels**: 1 (mono)
- **Inbound Bytes**: 56,193,396 (at query time)
- **Readers**: 0

### Stream Properties (cam2)
- **Video Codec**: H264
- **Profile**: Main
- **Level**: 5.1
- **Resolution**: 3840 × 2160 (4K)
- **Audio Codec**: MPEG-4 Audio (AAC)
- **Sample Rate**: 44100 Hz
- **Channels**: 1 (mono)
- **Inbound Bytes**: 50,193,903 (at query time)
- **Readers**: 0

---

## 2. FFprobe Validation

### cam1
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt -of csv=p=0 rtsp://localhost:8554/live/cam1
```
**Output**: `h264,3840,2160,yuv420p,30/1`

| Parameter | Value |
|-----------|-------|
| Codec | h264 |
| Width | 3840 |
| Height | 2160 |
| Pixel Format | yuv420p |
| Frame Rate | 30/1 = 30 fps |

### cam2
```bash
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt -of csv=p=0 rtsp://localhost:8554/live/cam2
```
**Output**: `h264,3840,2160,yuv420p,30/1`

| Parameter | Value |
|-----------|-------|
| Codec | h264 |
| Width | 3840 |
| Height | 2160 |
| Pixel Format | yuv420p |
| Frame Rate | 30/1 = 30 fps |

---

## 3. PyAV Decode Validation

### cam1 Decode Test
```python
import av
container = av.open('rtsp://localhost:8554/live/cam1', options={'rtsp_transport': 'tcp'})
stream = container.streams.video[0]
# stream.time_base = 1/90000
```

| Metric | Value |
|--------|-------|
| Stream | av.VideoStream #0 h264, yuv420p 3840x2160 |
| Codec | h264 |
| Width | 3840 |
| Height | 2160 |
| Time Base | 1/90000 |
| FPS (average_rate) | None (variable) |
| Frames Decoded | 100 |
| Duration | 2.56 seconds |
| Decode Rate | 39.1 fps |
| Frame 30 PTS | 9727 (time=0.108s) |
| Frame 60 PTS | 99727 (time=1.108s) |
| Frame 90 PTS | 189727 (time=2.108s) |
| Format | yuv420p |

**PTS Behavior**: Sequential increments of ~3000 per frame (3000 = 90000/30), consistent with 30fps at 90kHz timebase.

### cam2 Decode Test
```python
container = av.open('rtsp://localhost:8554/live/cam2', options={'rtsp_transport': 'tcp'})
```

| Metric | Value |
|--------|-------|
| Stream | av.VideoStream #0 h264, yuv420p 3840x2160 |
| Codec | h264 |
| Width | 3840 |
| Height | 2160 |
| Time Base | 1/90000 |
| FPS (average_rate) | None (variable) |
| Frames Decoded | 100 |
| Duration | 2.56 seconds |
| Decode Rate | 39.0 fps |
| Frame 30 PTS | -131298 (time=-1.459s) |
| Frame 60 PTS | -41298 (time=-0.459s) |
| Frame 90 PTS | 48702 (time=0.541s) |
| Format | yuv420p |

**PTS Behavior**: Negative PTS initially, crossing zero around frame 60-90. Indicates stream start offset or random access point alignment issue. **Critical**: PTS does NOT equal wall-clock time.

---

## 4. Camera Configuration (pipeline.yaml)

### cam1
```yaml
cam1:
  enabled: true
  name: "Camera 1"
  input:
    protocol: "rtsp"
    url: "rtsp://localhost:8554/live/cam1"
    transport: "tcp"
    timeout_seconds: 10
  output:
    protocol: "rtsp"
    path: "live/cam1-ai"
    transport: "tcp"
  expected:
    codec: "h264"
    width: 3840
    height: 2160
    fps: 30
  decode:
    backend: "pyav_nvdec"
    gpu_device: 0
    surfaces: 32
    allow_software_fallback: false
  geometry:
    line_start: [0, 1080]
    line_end: [3840, 1080]
    direction_semantics: "side_a_to_b_in"
  crossing_policy:
    min_crossing_distance: 50.0
    temporal_debounce_seconds: 2.0
    side_confirmation_frames: 3
    max_trajectory_gap_frames: 5
```

### cam2
```yaml
cam2:
  enabled: true
  name: "Camera 2"
  input:
    protocol: "rtsp"
    url: "rtsp://localhost:8554/live/cam2"
    transport: "tcp"
    timeout_seconds: 10
  output:
    protocol: "rtsp"
    path: "live/cam2-ai"
    transport: "tcp"
  expected:
    codec: "h264"
    width: 3840
    height: 2160
    fps: 30
  decode:
    backend: "pyav_nvdec"
    gpu_device: 0
    surfaces: 32
    allow_software_fallback: false
  geometry:
    line_start: [0, 1080]
    line_end: [3840, 1080]
    direction_semantics: "side_a_to_b_in"
  crossing_policy:
    min_crossing_distance: 50.0
    temporal_debounce_seconds: 2.0
    side_confirmation_frames: 3
    max_trajectory_gap_frames: 5
```

---

## 5. Camera Mapping Summary

| Camera ID | MediaMTX Input Path | MediaMTX Output Path | RTSP URL | Resolution | FPS | Codec | Line Y |
|-----------|---------------------|----------------------|----------|------------|-----|-------|--------|
| cam1 | live/cam1 | live/cam1-ai | rtsp://localhost:8554/live/cam1 | 3840×2160 | 30 | h264 | 1080 |
| cam2 | live/cam2 | live/cam2-ai | rtsp://localhost:8554/live/cam2 | 3840×2160 | 30 | h264 | 1080 |

---

## 6. Stream Validation Results

### Decode Capability
| Camera | FFprobe | PyAV Decode | Frames Tested | Decode FPS | Status |
|--------|---------|-------------|---------------|------------|--------|
| cam1 | ✅ h264/3840×2160/yuv420p/30fps | ✅ 100 frames | 100 | 39.1 | **PASS** |
| cam2 | ✅ h264/3840×2160/yuv420p/30fps | ✅ 100 frames | 100 | 39.0 | **PASS** |

### PTS/Timebase Analysis
| Camera | Time Base | PTS Behavior | Notes |
|--------|-----------|--------------|-------|
| cam1 | 1/90000 | Sequential, positive | Starts at ~9727, increments ~3000/frame |
| cam2 | 1/90000 | Sequential, negative→positive | Starts negative, crosses zero ~frame 60 |

**Critical Finding**: RTSP PTS ≠ Browser `video.currentTime`. Must track:
- `stream_epoch` (increments on reconnect)
- `frame_sequence` (monotonic per epoch)
- `PTS` (container timestamp, 90kHz)
- `time_base` (1/90000)
- `capture_timestamp` (wall-clock at frame acquisition)
- `processing_timestamp` (wall-clock at AI complete)

---

## 7. Reconnection Behavior (Not Yet Tested)

### Expected (from pipeline.yaml)
```yaml
reconnect:
  enabled: true
  max_retries: 5
  base_interval_seconds: 2.0
  max_interval_seconds: 60.0
  backoff_multiplier: 2.0
  jitter: 0.1
```

### Readiness Gate
```yaml
readiness:
  enabled: true
  timeout_seconds: 30.0
  poll_interval_seconds: 1.0
  min_bytes_progress_interval: 5.0
  consecutive_increases_required: 3
```

---

## 8. Health Monitoring Thresholds

```yaml
health:
  stale_threshold_seconds: 5.0
  degraded_threshold_seconds: 2.0
```

---

## 9. Camera Source Inventory Verdict

**CAM1**: ✅ **DISCOVERED & VALIDATED**
- MediaMTX path: `live/cam1` (ready, online)
- RTSP URL: `rtsp://localhost:8554/live/cam1`
- Decode: Verified 100 frames at 39 fps via PyAV
- Properties: 3840×2160, h264, yuv420p, 30fps, 90kHz timebase
- Audio: AAC 44.1kHz mono

**CAM2**: ✅ **DISCOVERED & VALIDATED**
- MediaMTX path: `live/cam2` (ready, online)
- RTSP URL: `rtsp://localhost:8554/live/cam2`
- Decode: Verified 100 frames at 39 fps via PyAV
- Properties: 3840×2160, h264, yuv420p, 30fps, 90kHz timebase
- Audio: AAC 44.1kHz mono
- **Note**: Initial negative PTS values (stream offset)

**AI Output Paths**: ⚠️ **NOT ACTIVE** (live/cam1-ai, live/cam2-ai) - Will be activated when CameraManager starts encoders/publishers

**V1 Gate Requirement**: ✅ **MET** - At least one real stream decoded into usable frames (BOTH cameras validated)