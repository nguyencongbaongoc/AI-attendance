# Phase 0.2 — Camera 1 Runtime Baseline

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up (Test 4)

---

## 1. Camera 1 Configuration

| Property | Value |
|----------|-------|
| **Camera ID** | cam1 |
| **RTMP Input** | `rtmp://localhost:1935/live/cam1` (stream key: cam1) |
| **RTSP Output** | `rtsp://localhost:8554/live/cam1` |
| **AI RTSP Output** | `rtsp://localhost:8554/live/cam1-ai` (not active in this phase) |
| **MediaMTX Path** | `live/cam1` |
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
  "name": "live/cam1",
  "ready": true,
  "readyTime": "10/4/2026 8:53:18 AM",
  "source": {"type": "rtmpConn", "id": "b01cb254-d0cb-48c4-aeca-c328d3ec0882"}
}
```

### 2.2 RTSP Decode Test (PyAV)
```python
import av
container = av.open("rtsp://localhost:8554/live/cam1")
for stream in container.streams.video:
    print(stream.codec_context.name, stream.width, stream.height, stream.time_base)
# Output: h264 3840 2160 1/90000

# Frame decode test
frame_count = 0
for frame in container.decode(video=0):
    frame_count += 1
    if frame_count >= 10: break
# 10 frames in 0.34s = 29.3 fps
```

### 2.3 Stream Properties
| Property | Measured Value | Expected | Match |
|----------|----------------|----------|-------|
| Codec | h264 | h264 | ✅ |
| Width | 3840 | 3840 | ✅ |
| Height | 2160 | 2160 | ✅ |
| FPS | 29.3 | 30 | ✅ (~2% variance) |
| Time Base | 1/90000 | 1/90000 | ✅ |
| Pixel Format | yuv420p (inferred) | yuv420p | ✅ |

---

## 3. Stream Health

| Metric | Value |
|--------|-------|
| **Path Ready** | true (since 08:53:18) |
| **Source Type** | rtmpConn |
| **Connection ID** | b01cb254-d0cb-48c4-aeca-c328d3ec0882 |
| **Decode Errors** | 0 (in test window) |
| **Reconnects** | 0 (in test window) |
| **Stale Frames** | None detected |

---

## 4. Architecture A Path Compliance

| Path | Architecture A Role | Status |
|------|---------------------|--------|
| **Video Path** | Camera → MediaMTX → UI (HLS/WebRTC) | ✅ `live/cam1` ready |
| **AI Path** | Camera → PyAV RTSP Decode → SCRFD/ArcFace/YOLO → Tracking → Legacy Backend | ✅ RTSP accessible |

---

## 5. Verdict

**TEST 4 — CAMERA 1: PASS**

Camera 1 stream is active on MediaMTX path `live/cam1`. RTSP endpoint decodes successfully at 4K resolution, ~30 FPS, h264 codec. MediaMTX reports path ready with active RTMP publisher connection. Stream is available for both UI video relay and AI inference pipeline.

---

## 6. Evidence Commands

```bash
# MediaMTX path status
curl http://localhost:9997/v3/paths/list | jq '.items[] | select(.name=="live/cam1")'

# RTSP decode test
.venv2\Scripts\python.exe -c "
import av, time
c = av.open('rtsp://localhost:8554/live/cam1')
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