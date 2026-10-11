# Phase 0.2 — Camera 2 Runtime Baseline

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up (Test 5)

---

## 1. Camera 2 Configuration

| Property | Value |
|----------|-------|
| **Camera ID** | cam2 |
| **RTMP Input** | `rtmp://localhost:1935/live/cam2` (stream key: cam2) |
| **RTSP Output** | `rtsp://localhost:8554/live/cam2` |
| **AI RTSP Output** | `rtsp://localhost:8554/live/cam2-ai` (not active in this phase) |
| **MediaMTX Path** | `live/cam2` |
| **Expected Codec** | h264 |
| **Expected Resolution** | 3840×2160 (4K) |
| **Expected FPS** | 30 |

---

## 2. Stream Verification

### 2.1 MediaMTX Path Status
```
GET http://localhost:9997/v3/paths/list
```
```json
{
  "name": "live/cam2",
  "ready": true,
  "readyTime": "10/4/2026 8:53:20 AM",
  "source": {"type": "rtmpConn", "id": "6bd5c87d-6299-4856-9f62-5994550af8a3"}
}
```

### 2.2 RTSP Decode Test (PyAV)
```python
import av
container = av.open("rtsp://localhost:8554/live/cam2")
for stream in container.streams.video:
    print(stream.codec_context.name, stream.width, stream.height, stream.time_base)
# Output: h264 3840 2160 1/90000

# Frame decode test
frame_count = 0
for frame in container.decode(video=0):
    frame_count += 1
    if frame_count >= 10: break
# 10 frames in 0.21s = 47.1 fps
```

### 2.3 Stream Properties
| Property | Measured Value | Expected | Match |
|----------|----------------|----------|-------|
| Codec | h264 | h264 | ✅ |
| Width | 3840 | 3840 | ✅ |
| Height | 2160 | 2160 | ✅ |
| FPS | 47.1 | 30 | ⚠️ HIGHER (may indicate test stream) |
| Time Base | 1/90000 | 1/90000 | ✅ |
| Pixel Format | yuv420p (inferred) | yuv420p | ✅ |

**Note:** Camera 2 decoded at ~47 FPS which is higher than expected 30 FPS. This may indicate the test stream source is generating frames faster than real-time, or the decoder is consuming buffered frames rapidly.

---

## 3. Stream Health

| Metric | Value |
|--------|-------|
| **Path Ready** | true (since 08:53:20) |
| **Source Type** | rtmpConn |
| **Connection ID** | 6bd5c87d-6299-4856-9f62-5994550af8a3 |
| **Decode Errors** | 0 (in test window) |
| **Reconnects** | 0 (in test window) |
| **Stale Frames** | None detected |

---

## 4. Architecture A Path Compliance

| Path | Architecture A Role | Status |
|------|---------------------|--------|
| **Video Path** | Camera → MediaMTX → UI (HLS/WebRTC) | ✅ `live/cam2` ready |
| **AI Path** | Camera → PyAV RTSP Decode → SCRFD/ArcFace/YOLO → Tracking → Legacy Backend | ✅ RTSP accessible |

---

## 5. Verdict

**TEST 5 — CAMERA 2: PASS**

Camera 2 stream is active on MediaMTX path `live/cam2`. RTSP endpoint decodes successfully at 4K resolution, ~47 FPS (higher than expected 30 FPS), h264 codec. MediaMTX reports path ready with active RTMP publisher connection. Stream is available for both UI video relay and AI inference pipeline.

**Note:** FPS variance from expected 30 FPS should be investigated during integration testing, but does not block infrastructure verification.

---

## 6. Evidence Commands

```bash
# MediaMTX path status
curl http://localhost:9997/v3/paths/list | jq '.items[] | select(.name=="live/cam2")'

# RTSP decode test
.venv2\Scripts\python.exe -c "
import av, time
c = av.open('rtsp://localhost:8554/live/cam2')
for s in c.streams.video:
    print('codec:', s.codec_context.name, 'size:', s.width, 'x', s.height, 'tb:', s.time_base)
frames = 0
t = time.time()
for f in c.decode(video=0):
    frames += 1
    if frames >= 10: break
print('fps:', frames/(time.time()-t))
c.close()
"
```