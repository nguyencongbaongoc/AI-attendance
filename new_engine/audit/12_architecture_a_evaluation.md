# Architecture A Evaluation

## Architecture A Definition

### Video Path (Passthrough)
```
Camera 1 + Camera 2
    → MediaMTX / FFmpeg (stream copy where compatible)
    → Original live video
    → UI video player (hls.js/WebRTC)
```

### AI Path (Independent)
```
Camera RTSP
    → PyAV reader (separate process)
    → Decode (GPU)
    → Existing AI inference (SCRFD + YOLO + ArcFace)
    → Tracking
    → Attendance
    → Existing Backend (sole API gateway)
    → UI metadata overlay (WebSocket + Canvas)
```

---

## Component-by-Component Evaluation

### 1. FFmpeg Stream Copy Compatibility

| Aspect | Camera Stream | AI Annotated Stream | Stream Copy Feasible? |
|--------|---------------|---------------------|----------------------|
| Codec | H.264 | H.264 | ✅ Same |
| Resolution | 3840×2160 | 3840×2160 | ✅ Same |
| FPS | 30 | 30 | ✅ Same |
| Container | RTMP → RTSP (MediaMTX) | RTSP | ✅ MediaMTX remux |
| GOP Structure | Camera-dependent | Fixed GOP=30 | ⚠️ May differ |
| Bitrate | Variable | 8000 kbps CBR | ❌ Different |
| Annotation | None | GPU overlay | ❌ Requires re-encode |

**Verdict**: Stream copy (`-c copy`) **NOT feasible for AI path** because:
- Annotation requires decode → modify → re-encode
- Bitrate control requires re-encode
- GOP alignment for low-latency streaming

**Verdict**: Stream copy **IS feasible for video path** (camera → MediaMTX → UI) since MediaMTX already remuxes RTMP→RTSP→HLS/WebRTC without re-encoding.

### 2. MediaMTX Relay Capability

**Current MediaMTX Config** (`mediamtx/mediamtx.yml`):
```yaml
paths:
  live/cam1:        # Camera 1 input (RTMP publisher)
    source: publisher
  live/cam2:        # Camera 2 input (RTMP publisher)
    source: publisher
  live/cam1-ai:     # AI annotated output
    source: publisher
  live/cam2-ai:     # AI annotated output
    source: publisher
```

**MediaMTX Already Provides**:
- ✅ RTMP ingest from cameras (ports 1935)
- ✅ RTSP re-stream (port 8554) 
- ✅ HLS low-latency (port 8888) for UI
- ✅ WebRTC (port 8889) for UI
- ✅ Recording to fMP4 (configurable)
- ✅ Authentication, API, metrics

**Architecture A Video Path**: Use existing `live/cam1`, `live/cam2` paths directly for UI. No PipelineEngine involvement.

### 3. PyAV as AI Reader

**Current Implementation**: `ingestion/rtsp_source.py` uses PyAV to read from `rtsp://localhost:8554/live/cam1`

**Architecture A**: Same PyAV reader, but:
- Runs in separate process (not in CameraManager thread)
- Outputs GPUFrame to AI pipeline only
- No encoder, no publisher, no annotation
- Can use `nvdec_decoder.py` (software decode + GPU upload) or true NVDEC if available

**Feasibility**: ✅ **PyAV already works as independent reader**

### 4. NVDEC Necessity and Functionality

**Current State**: 
- GTX 1660 Ti on Windows: cuvid outputs `dxva2_vld`, not CUDA
- Pipeline uses **software decode + GPU upload** (not true NVDEC)
- `nvdec_decoder.py` lines 164-171, 188-230 confirm this

**Architecture A Options**:
| Option | Pros | Cons |
|--------|------|------|
| Keep software decode + upload | Works reliably | CPU bottleneck at 4K30 |
| Use nvcv_bridge (custom) | True zero-copy decode | `.pyd` exists but untested |
| FFmpeg hwaccel (cuvid) → CPU → GPU | May work | Complex |
| Downgrade to 1080p for AI | 4× faster decode | Loses detail |

**Recommendation**: 
- **Short term**: Keep software decode + GPU upload (proven)
- **Long term**: Test `nvcv_bridge.pyd` for true NVDEC
- **Architecture A**: Decode in separate process, won't block video path

### 5. CPU-to-GPU Transfer

**Current**: Software decode produces CPU frames → `torch.frombuffer()` → `.copy_()` to pre-allocated GPU tensors → `torch.cuda.synchronize()`

**Cost**: ~5-10ms per 4K frame (measured in decoder)

**Architecture A**: Same transfer, but:
- Only for AI path (not video path)
- Can batch multiple frames
- Separate process isolates CPU load

**Verdict**: ✅ **Acceptable for AI path**, not needed for video path

### 6. NVENC Necessity in Architecture A

**Video Path**: No NVENC needed - MediaMTX stream copy / remux
**AI Path**: No NVENC needed - metadata only, no video output

**Verdict**: ❌ **NVENC NOT needed in Architecture A initial version**

**Removed Components**:
- `nvenc_encoder.py` 
- `publisher.py` (MediaMTXPublisher)
- `annotation/overlay.py` (GPUAnnotator)
- FramePool for encoder (reduced size)

### 7. Timestamp Synchronization (Critical for Architecture A)

**Current State**: 
- `GPUFrame` has `pts`, `dts`, `time_base`, `timestamp`, `stream_epoch`
- No correlation between AI metadata timestamps and video playback position
- UI plays HLS from MediaMTX, receives WebSocket from Legacy Backend

**Architecture A Requirements**:
```
Video: MediaMTX HLS segment #N (timestamp T)
AI:    CrossingEvent at wall-clock T + processing_latency
Sync:  UI must overlay event at video.currentTime ≈ T
```

**Gap Analysis**:
| Sync Element | Current | Required for Arch A |
|--------------|---------|---------------------|
| PTS preservation | ✅ In GPUFrame | ✅ Pass through to metadata |
| Wall-clock timestamp | ✅ `time.time()` | ✅ Include in metadata |
| Stream epoch | ✅ `stream_epoch` | ✅ Include for reconnection sync |
| Camera ID | ✅ In GPUFrame | ✅ Include in metadata |
| Processing latency | ✅ Per-stage timing | ✅ Report for compensation |

**Proposed Metadata Schema**:
```json
{
    "camera_id": "cam1",
    "stream_epoch": 3,
    "frame_pts": 2700000,
    "time_base": 1/90000,
    "wall_clock_timestamp": 1234567890.123,
    "processing_latency_ms": 142,
    "tracks": [...],
    "events": [...]
}
```

**UI Sync Logic**:
```javascript
// Video plays HLS, WebSocket receives metadata
video.addEventListener('timeupdate', () => {
    const videoTime = video.currentTime;
    // Find metadata with closest (wall_clock_timestamp - processing_latency/1000)
    // Render overlay for that metadata
});
```

**Verdict**: ⚠️ **Feasible but requires implementation** - PTS + wall-clock + latency in metadata, UI correlates with video.currentTime

### 8. UI Display: Original Stream + AI Overlay

**Current UI**: Static images with canvas line drawing tool

**Architecture A UI**:
```
<video id="video" src="http://localhost:8888/live/cam1/index.m3u8"></video>
<canvas id="overlay" style="position:absolute;top:0;left:0;"></canvas>
```

**Implementation**:
1. hls.js plays raw camera stream (`live/cam1`, not `live/cam1-ai`)
2. WebSocket receives AI metadata (tracks, events, geometry)
3. requestAnimationFrame draws boxes/labels/lines on canvas
4. Coordinate transform: video 3840×2160 → canvas display size

**Feasibility**: ✅ **Standard pattern, hls.js + canvas overlay well-established**

### 9. Video Recording Separation

**Current**: MediaMTX records `live/cam1-ai` (annotated) to fMP4

**Architecture A**: 
- MediaMTX records `live/cam1` (raw) → separate storage
- AI events in Legacy Backend DB → separate storage
- **Linkage**: Event timestamp + camera_id → video segment lookup

**Verdict**: ✅ **Already separated** - MediaMTX handles video, Legacy Backend handles events
**Gap**: Need correlation ID (timestamp + camera) for replay

---

## Architecture A Component Mapping

| Current PipelineEngine | Architecture A | Action |
|------------------------|----------------|--------|
| `RTSPSource` | ✅ KEEP | Separate process, AI path only |
| `NVDECDecoder` | ✅ ADAPT | Separate process, software decode OK |
| `SCRFDDetector` | ✅ KEEP | Shared instance, batch support |
| `ArcFaceRecognizer` | ✅ KEEP | Shared instance, batch identify |
| `YOLOPersonDetector` | ✅ KEEP | Shared instance, batch support |
| `Tracker` | ✅ ADAPT | Stateless, shared instance |
| `AttendanceEngine` | ✅ ADAPT | Push events to Legacy Backend |
| `GPUAnnotator` | ❌ REMOVE | No GPU annotation |
| `NVENCEncoder` | ❌ REMOVE | No re-encode for AI path |
| `MediaMTXPublisher` | ❌ REMOVE | No video publish for AI path |
| `CameraManager` | ❌ REPLACE | New AI pipeline orchestrator |
| `PipelineEngine` | ❌ REPLACE | New AI-only orchestrator |
| `PipelineEngine Backend` | ❌ REPLACE | Internal service only |
| `FramePool` | ✅ ADAPT | Shared, smaller (no encoder) |
| `GPUMemoryMonitor` | ✅ KEEP | Monitor AI process |

---

## Architecture A Data Flow (Revised)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Camera 1   │     │  Camera 2   │     │  MediaMTX   │
│  (RTMP)     │────►│  (RTMP)     │────►│  :8554 RTSP │
└─────────────┘     └─────────────┘     │  :8888 HLS  │
                                         │  :8889 WEBRTC│
                    ┌────────────────────┴─────────────┘
                    ▼                       ▼
            ┌───────────────┐      ┌───────────────┐
            │  UI (hls.js)  │      │  AI Pipeline  │
            │  Raw Video    │      │  (separate)   │
            └───────┬───────┘      └───────┬───────┘
                    │                      │
                    │              ┌───────┴───────┐
                    │              ▼               ▼
                    │       ┌──────────┐    ┌──────────┐
                    │       │ PyAV     │    │ PyAV     │
                    │       │ Reader   │    │ Reader   │
                    │       └────┬─────┘    └────┬─────┘
                    │            │               │
                    │       ┌────┴─────┐    ┌────┴─────┐
                    │       │ Decode   │    │ Decode   │
                    │       │ (GPU)    │    │ (GPU)    │
                    │       └────┬─────┘    └────┬─────┘
                    │            │               │
                    │       ┌────┴───────────────┴────┐
                    │       │  SHARED MODELS          │
                    │       │  SCRFD + YOLO + ArcFace │
                    │       └────┬────────────────────┘
                    │            │
                    │       ┌────┴─────┐
                    │       │ Tracker  │
                    │       └────┬─────┘
                    │            │
                    │       ┌────┴─────┐
                    │       │Attend.   │
                    │       │Engine    │
                    │       └────┬─────┘
                    │            │
                    ▼            ▼
            ┌─────────────┐ ┌─────────────┐
            │  Legacy     │ │   UI        │
            │  Backend    │ │  (WebSocket)│
            │  (Events)   │ │  (Overlay)  │
            └─────────────┘ └─────────────┘
```

---

## Performance Projection for Architecture A

### Video Path (Unchanged)
- MediaMTX stream copy: ~0ms added latency
- HLS latency: ~2-3s (lowLatency variant)
- WebRTC latency: ~500ms

### AI Path (New)
| Stage | Current | Architecture A | Change |
|-------|---------|----------------|--------|
| Decode | 10ms (in pipeline) | 10ms (separate) | Same |
| SCRFD | 8ms | 8ms (batched?) | Same/better |
| YOLO | 8ms | 8ms (batched?) | Same/better |
| ArcFace | 3ms/face | 3ms/face (batched?) | Same/better |
| Tracking | 1ms | 1ms | Same |
| Attendance | 1ms | 1ms + network | +1-2ms |
| **Total AI** | **~31ms** | **~30-35ms** | Similar |
| **End-to-end** | **~200ms** (incl encode) | **~50ms** (metadata only) | **4× faster** |

**Key Benefit**: Removing annotation + encode + publish saves ~150ms latency

---

## Migration Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Timestamp sync failure | HIGH | HIGH | Prototype metadata schema early |
| UI canvas overlay performance | MEDIUM | MEDIUM | Test at 4K, optimize draw calls |
| Shared model inference contention | MEDIUM | HIGH | Batch inference, queue management |
| Legacy Backend integration | HIGH | HIGH | Define API contract first |
| NPY hot-reload | LOW | MEDIUM | File watcher or API notification |
| MediaMTX config drift | LOW | LOW | Single config source |

---

## Recommended Phase 1 Scope for Architecture A

### Phase 1A: AI Pipeline Core (Week 1-2)
1. Extract PyAV reader + NVDECDecoder + AI models into standalone process
2. Implement batch inference queue
3. Shared model instances (single SCRFD, YOLO, ArcFace per GPU)
4. Tracker as stateless per-frame processor
5. AttendanceEngine pushes to Legacy Backend via HTTP

### Phase 1B: Legacy Backend Integration (Week 2-3)
1. Legacy Backend receives attendance events via API
2. Legacy Backend broadcasts via WebSocket
3. Legacy Backend owns attendance.db (single source)
4. Remove PipelineEngine local SQLite

### Phase 1C: UI Overlay (Week 3-4)
1. hls.js plays raw camera streams (`live/cam1`, `live/cam2`)
2. Canvas overlay renders tracks/boxes/lines from WebSocket
3. Coordinate transform video→canvas
4. Line drawing tool saves to Legacy Backend

### Phase 1D: Testing & Hardening (Week 4-5)
1. End-to-end test with 2 cameras
2. Reconnection handling
3. Load test: 4K30 dual camera sustained
4. Timestamp sync verification

---

## Conclusion

**Architecture A is feasible** with the existing codebase:

✅ **Video path**: MediaMTX already handles passthrough/recording
✅ **AI path**: PyAV + existing models work independently  
✅ **No NVENC needed**: Metadata-only output
⚠️ **Timestamp sync**: Requires careful implementation
⚠️ **UI overlay**: New canvas-based implementation needed
❌ **Legacy Backend integration**: Major gap, must be resolved first

**Recommended**: Proceed with Architecture A, starting with Legacy Backend API contract definition.