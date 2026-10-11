# Phase 0.2 — MediaMTX Runtime Baseline

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up (Test 2)

---

## 1. MediaMTX Binary & Configuration

| Property | Value |
|----------|-------|
| **Binary** | `mediamtx/mediamtx.exe` (54 MB) |
| **Config** | `mediamtx/mediamtx.yml` (719 lines) |
| **TLS Cert** | `mediamtx/auto.crt` |
| **TLS Key** | `mediamtx/auto.key` |
| **License** | `mediamtx/LICENSE` |

---

## 2. Configured Ports

| Protocol | Port | Status |
|----------|------|--------|
| RTSP | 8554 | ✅ LISTENING |
| RTMP | 1935 | ✅ LISTENING |
| HLS | 8888 | ✅ LISTENING |
| WebRTC | 8889 | ✅ LISTENING |
| Control API | 9997 | ✅ LISTENING |
| RTSPS | 8322 | ❌ Not enabled |
| RTMPS | 1936 | ❌ Not enabled |
| SRT | 8890 | ✅ LISTENING |

---

## 3. Configured Paths (from mediamtx.yml)

| Path | Source | RTSP Transport | Ready | Notes |
|------|--------|----------------|-------|-------|
| `live/cam1` | publisher (RTMP) | tcp | ✅ TRUE | RTMP stream key: cam1 |
| `live/cam1-ai` | publisher (RTMP) | tcp | ❌ FALSE | AI-annotated output |
| `live/cam2` | publisher (RTMP) | tcp | ✅ TRUE | RTMP stream key: cam2 |
| `live/cam2-ai` | publisher (RTMP) | tcp | ❌ FALSE | AI-annotated output |

**Path defaults:**
- `source: publisher` — Streams pushed via RTMP/RTSP/WebRTC
- `overridePublisher: yes` — Allow publisher replacement
- `hlsVariant: lowLatency` — Low-Latency HLS for UI
- `record: no` — Recording disabled by default

---

## 4. Runtime Verification

### 4.1 Process Start
```powershell
cd mediamtx
.\mediamtx.exe .\mediamtx.yml
```
- **PID:** Started via background process
- **Startup time:** ~2 seconds
- **Logs:** Output to stdout (logLevel: info, logDestinations: [stdout])

### 4.2 API Health Check
```
GET http://localhost:9997/v3/paths/list
```
```json
{
  "itemCount": 4,
  "pageCount": 1,
  "items": [
    {"name": "live/cam1", "ready": true, "readyTime": "10/4/2026 8:53:18 AM", "source": {"type": "rtmpConn", "id": "b01cb254-d0cb-48c4-aeca-c328d3ec0882"}},
    {"name": "live/cam1-ai", "ready": false, "source": null},
    {"name": "live/cam2", "ready": true, "readyTime": "10/4/2026 8:53:20 AM", "source": {"type": "rtmpConn", "id": "6bd5c87d-6299-4856-9f62-5994550af8a3"}},
    {"name": "live/cam2-ai", "ready": false, "source": null}
  ]
}
```

### 4.3 Camera Publishers Status
Both `live/cam1` and `live/cam2` show **ready: true** with active RTMP connections, indicating camera publishers are successfully pushing streams to MediaMTX.

---

## 5. Stream Verification (PyAV)

### 5.1 Camera 1 — `rtsp://localhost:8554/live/cam1`
- **Codec:** h264
- **Resolution:** 3840×2160 (4K)
- **Time base:** 1/90000
- **Decoded FPS:** 29.3 fps (10 frames in 0.34s)
- **Status:** ✅ ACTIVE, DECODING

### 5.2 Camera 2 — `rtsp://localhost:8554/live/cam2`
- **Codec:** h264
- **Resolution:** 3840×2160 (4K)
- **Time base:** 1/90000
- **Decoded FPS:** 47.1 fps (10 frames in 0.21s)
- **Status:** ✅ ACTIVE, DECODING

### 5.3 Dual-Camera Simultaneous Decode
- **Cam1:** 30 frames at 97.3 fps
- **Cam2:** 30 frames at 100.4 fps
- **Status:** ✅ BOTH STREAMS DECODING CONCURRENTLY

---

## 6. Resource Usage

| Metric | Value |
|--------|-------|
| **Process Memory** | ~50-80 MB (estimated) |
| **CPU Usage** | Low (idle with publishers connected) |
| **Network** | RTMP in, RTSP/HLS/WebRTC out |
| **Disk** | No recording active |

---

## 7. Configuration Compliance with Architecture A

| Architecture A Requirement | MediaMTX Config | Status |
|----------------------------|-----------------|--------|
| Video path: Camera → MediaMTX → Original video → UI | `live/cam1`, `live/cam2` via HLS/WebRTC | ✅ Configured |
| AI path: Camera → PyAV Decode → AI → Legacy Backend | `live/cam1`, `live/cam2` RTSP input | ✅ Configured |
| AI annotated output (NOT in Phase 0.2) | `live/cam1-ai`, `live/cam2-ai` | ✅ Configured but not used |
| No second attendance DB | N/A | ✅ N/A |
| No NVENC annotated output in this phase | Paths exist but not activated | ✅ Compliant |

---

## 8. Verdict

**TEST 2 — MEDIAMTX: PASS**

MediaMTX is running, both camera input paths (`live/cam1`, `live/cam2`) are active and receiving RTMP publisher streams. RTSP endpoints are accessible and decoding at expected 4K resolution and ~30 FPS. Control API responding on port 9997.

---

## 9. Evidence Commands

```bash
# Start MediaMTX
cd mediamtx
.\mediamtx.exe .\mediamtx.yml

# Check ports
netstat -an | findstr "8554 8888 8889 9997 1935"

# Check API paths
curl http://localhost:9997/v3/paths/list

# Test RTSP decode
.venv2\Scripts\python.exe -c "
import av
for url in ['rtsp://localhost:8554/live/cam1', 'rtsp://localhost:8554/live/cam2']:
    c = av.open(url)
    for s in c.streams.video:
        print(s.codec_context.name, s.width, s.height, s.time_base)
    c.close()
"
```