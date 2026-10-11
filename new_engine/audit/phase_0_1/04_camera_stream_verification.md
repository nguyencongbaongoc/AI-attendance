# Camera Stream Verification

## MediaMTX Stream Paths Configuration

From `mediamtx/mediamtx.yml`:

| Path | Source | Protocol | Purpose |
|------|--------|----------|---------|
| `live/cam1` | publisher | RTMP/RTSP | Camera 1 input |
| `live/cam2` | publisher | RTMP/RTSP | Camera 2 input |
| `live/cam1-ai` | publisher | RTSP | AI annotated output |
| `live/cam2-ai` | publisher | RTSP | AI annotated output |

## Stream URL Mapping

### Camera Inputs (RTMP Ingest → MediaMTX)
| Camera | RTMP Ingest URL | Stream Key |
|--------|----------------|------------|
| Camera 1 | `rtmp://localhost:1935/live/cam1` | `cam1` |
| Camera 2 | `rtmp://localhost:1935/live/cam2` | `cam2` |

### Camera Outputs (MediaMTX → Consumers)

| Stream | RTSP | HLS (lowLatency) | WebRTC |
|--------|------|------------------|--------|
| Camera 1 Raw | `rtsp://localhost:8554/live/cam1` | `http://localhost:8888/live/cam1/index.m3u8` | `webrtc://localhost:8889/live/cam1` |
| Camera 2 Raw | `rtsp://localhost:8554/live/cam2` | `http://localhost:8888/live/cam2/index.m3u8` | `webrtc://localhost:8889/live/cam2` |
| Camera 1 AI | `rtsp://localhost:8554/live/cam1-ai` | `http://localhost:8888/live/cam1-ai/index.m3u8` | `webrtc://localhost:8889/live/cam1-ai` |
| Camera 2 AI | `rtsp://localhost:8554/live/cam2-ai` | `http://localhost:8888/live/cam2-ai/index.m3u8` | `webrtc://localhost:8889/live/cam2-ai` |

## Current Runtime Status

**MediaMTX**: NOT RUNNING (verified via `Get-Process mediamtx` and `netstat`)

**Camera Publishers**: NOT RUNNING (no connections to RTMP port 1935)

**Stream Availability**: ALL STREAMS OFFLINE

## PipelineEngine Camera Configuration

From `pipeline_engine/config/pipeline.yaml`:

### Camera 1 (`cam1`)
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
  encode:
    backend: "pyav_nvenc"
    codec: "h264_nvenc"
    gpu_device: 0
    width: 3840
    height: 2160
    fps: 30
    bitrate_kbps: 8000
    gop_size: 30
    preset: "p4"
    tune: "ll"
    rc: "cbr"
```

### Camera 2 (`cam2`)
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
  # ... same decode/encode config as cam1
```

## Stream Properties Expected

| Property | Value | Source |
|----------|-------|--------|
| Codec | H.264 | pipeline.yaml |
| Resolution | 3840×2160 (4K) | pipeline.yaml |
| FPS | 30 | pipeline.yaml |
| Transport | TCP | pipeline.yaml & mediamtx.yml |
| Pixel Format | yuv420p / nv12 | Implied by H.264 |

## Architecture A Stream Usage

### Video Path (Passthrough)
```
Camera → RTMP → MediaMTX → HLS/WebRTC → UI
```
- Uses: `live/cam1`, `live/cam2` (raw camera streams)
- No AI processing
- MediaMTX handles relay/transcoding

### AI Path (Independent)
```
Camera → RTSP (live/cam1, live/cam2) → PyAV Reader → Decode → AI → Legacy Backend → UI Overlay
```
- Uses: `live/cam1`, `live/cam2` (same raw streams)
- Independent PyAV reader per camera
- No video encoding in AI path
- Metadata only to Legacy Backend

## Verification Checklist

| Stream | Configured | MediaMTX Running | Publisher Connected | Frames Decodable |
|--------|------------|------------------|---------------------|------------------|
| live/cam1 (RTSP) | ✅ | ❌ | ❌ | ❌ |
| live/cam2 (RTSP) | ✅ | ❌ | ❌ | ❌ |
| live/cam1-ai (RTSP) | ✅ | ❌ | ❌ | ❌ |
| live/cam2-ai (RTSP) | ✅ | ❌ | ❌ | ❌ |
| live/cam1 (RTMP ingest) | ✅ | ❌ | ❌ | N/A |
| live/cam2 (RTMP ingest) | ✅ | ❌ | ❌ | N/A |
| live/cam1 (HLS) | ✅ | ❌ | N/A | ❌ |
| live/cam2 (HLS) | ✅ | ❌ | N/A | ❌ |

## Blocker Status

**CRITICAL**: MediaMTX not running → No streams available

**Required for Verification**:
1. Start MediaMTX: `.\mediamtx.exe` in `mediamtx/` directory
2. Start camera RTMP publishers to `:1935/live/cam1` and `:1935/live/cam2`
3. Verify RTSP streams accessible: `ffprobe rtsp://localhost:8554/live/cam1`
4. Verify HLS playable: `http://localhost:8888/live/cam1/index.m3u8`

## Camera Publisher Information

**Unknown**: 
- Camera IP addresses
- Camera RTMP push configuration
- Camera codec/bitrate settings
- Whether cameras push to MediaMTX or pull from cameras

**From Legacy Backend** (`app/streaming/rtmp_source.py`):
- RTMP source implementation exists
- Camera config likely in `app/config/settings.py`

**From PipelineEngine Config**:
- Expects cameras to already be publishing to MediaMTX
- No camera discovery or management in PipelineEngine

## Stream Verification Commands (When MediaMTX Running)

```bash
# Check MediaMTX API
curl http://localhost:9997/v3/paths/list

# Check RTSP stream
ffprobe -v quiet -show_streams rtsp://localhost:8554/live/cam1

# Check HLS playlist
curl http://localhost:8888/live/cam1/index.m3u8

# Test with Python/PyAV
python -c "
import av
container = av.open('rtsp://localhost:8554/live/cam1', options={'rtsp_transport': 'tcp'})
print(container.streams.video[0])
"
```

## Summary

| Aspect | Status |
|--------|--------|
| Stream Configuration | ✅ Complete (both systems) |
| MediaMTX Runtime | ❌ NOT RUNNING |
| Camera Publishers | ❌ NOT RUNNING |
| Stream Accessibility | ❌ BLOCKED |
| Frame Decodability | ❌ UNKNOWN (blocked) |

**All stream verification BLOCKED by MediaMTX not running.**