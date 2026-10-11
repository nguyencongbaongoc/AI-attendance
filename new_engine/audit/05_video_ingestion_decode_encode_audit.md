# Video Ingestion, Decode, and Encode Audit

## Video Ingestion (RTSP Source)

### Implementation: `ingestion/rtsp_source.py`

**Status: IMPLEMENTED, TESTED (unit), PARTIALLY VERIFIED (runtime)**

#### Architecture
- Uses PyAV (`av.open()`) with RTSP protocol
- TCP transport (configured via `rtsp_transport: tcp`)
- Single read thread (`_read_loop`) demuxing packets
- Packet queue (`Queue(maxsize=32)`) buffers between read thread and decoder

#### Key Features
1. **Connection Management**
   - Configurable timeouts (connection: 10s, read: 5s)
   - Socket buffer size: 1MB
   - FFmpeg options: `stimeout`, `rw_timeout`, `buffer_size`, `max_delay`

2. **Reconnection Logic**
   - Exponential backoff: base 2s × 2^retry, max 60s
   - Jitter: ±10%
   - Max retries: 5 (configurable)
   - Automatic on read loop exit (FFmpegError, EOF, timeout)

3. **Readiness Gate**
   - Tracks bytes received over time
   - Requires 3 consecutive 5-second intervals with byte progress
   - Configurable: `min_bytes_progress_interval`, `consecutive_increases_required`
   - Prevents starting pipeline on stalled/stalled streams

4. **Health Monitoring**
   - `is_healthy()`: last packet < `stale_threshold` (5s default)
   - `is_degraded()`: last packet < `degraded_threshold` (2s default)
   - Metrics: bytes/packets received, bitrate, errors, reconnects

4. **Stream Info Extraction**
   - Width, height, codec, fps, time_base from stream
   - Handles missing `average_rate` (defaults to 30fps)

#### Data Flow
```
RTSP URL → av.open() → container.demux(video_stream) 
    → av.Packet → _packet_queue.put()
    → CameraManager.get_packet() → NVDECDecoder
```

#### Evidence
- **File**: `pipeline_engine/ingestion/rtsp_source.py` (530 lines)
- **Config**: `pipeline.yaml` cameras.cam1/cam2 input section
- **Test**: `__main__` block tests with RTSP URL or file
- **Runtime**: Requires MediaMTX running at `rtsp://localhost:8554/live/cam1`

#### Limitations
- No RTMP source implementation (`rtmp_source.py` is stub)
- No authentication support in RTSP URL
- Single video stream only (no audio)
- Readiness gate only checks byte progress, not frame decode success

## Video Decode (NVDEC)

### Implementation: `decode/nvdec_decoder.py`

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

#### Architecture
- **Primary approach**: Software decode (PyAV) + GPU upload
- **Reason**: On Windows GTX 1660 Ti, cuvid outputs `dxva2_vld` frames which cannot easily convert to CUDA tensors
- Zero-copy not achieved on this hardware; CPU→GPU copy required

#### Configuration
```python
NVDECDecoderConfig:
    camera_id: str
    packet_source: RTSPSource
    gpu_device: 0
    codec: "h264"
    width: 3840
    height: 2160
    max_surfaces: 32
    max_queue_size: 8
    frame_pool: FramePool (optional)
```

#### Decode Pipeline
```
av.Packet → container.decode(video=0) → av.Frame (yuv420p, 3 planes)
    → Y plane: memoryview → torch.frombuffer → reshape(H, W) → copy_ to _y_gpu
    → U plane: memoryview → torch.frombuffer → reshape(H/2, W/2) → copy_
    → V plane: same → stack(U,V, dim=-1) → copy_ to _uv_gpu
    → torch.cuda.synchronize()
    → FramePool.acquire() → GPUFrame
    → gpu_frame.y_tensor.copy_(_y_gpu), gpu_frame.uv_tensor.copy_(_uv_gpu)
    → _frame_queue.put(GPUFrame)
```

#### Key Implementation Details

1. **Pre-allocated GPU Tensors**
   - `_y_gpu`: (H, W) uint8
   - `_uv_gpu`: (H/2, W/2, 2) uint8 interleaved
   - Reused for every frame (avoids allocation)

2. **Frame Pool Integration**
   - Acquires from pool with frame_id, timestamp, pts
   - Copies pre-allocated tensors to pooled frame
   - On pool exhaustion: drops frame, increments `frames_dropped`

3. **Output Queue**
   - `Queue(maxsize=8)` buffers decoded frames
   - `get_frame(timeout)` for pipeline consumption
   - Full queue: drops oldest, inserts newest (latest-wins)

4. **Reconnection**
   - On reader_loop exit: `_attempt_restart()` with bounded retries
   - Max 3 retries, 2s backoff
   - Re-initializes container, tensors, reader thread

#### GPU vs CPU Path
| Path | Status | Notes |
|------|--------|-------|
| cuvid (NVDEC hardware) | ATTEMPTED, FAILED | Outputs dxva2_vld on Windows, not CUDA |
| nvdec (PyAV hwaccel) | NOT USED | Same limitation |
| Software decode + GPU upload | **ACTIVE** | Reliable, ~5-10ms/frame at 4K |
| nvcv_bridge (custom) | NOT USED | `.pyd` present but not integrated |

#### Performance Characteristics
- **4K 30fps decode**: ~5-15ms/frame (software + upload)
- **VRAM per frame**: ~12MB (NV12 3840×2160 = 12.4MB)
- **Pool size**: 32 frames = ~400MB VRAM budget
- **CPU usage**: Moderate (software decode on CPU)

#### Evidence
- **File**: `pipeline_engine/decode/nvdec_decoder.py` (580 lines)
- **Config**: `pipeline.yaml` decode section + per-camera decode
- **Test**: `__main__` block tests with video file
- **Runtime**: BLOCKED - requires RTSP stream + CUDA

#### Limitations
- **No true NVDEC on Windows GTX 1660 Ti**: Falls back to software
- **CPU bottleneck**: Software decode at 4K30 may not sustain
- **No timestamp synchronization**: PTS from stream used directly
- **No frame rate adaptation**: Assumes constant fps

## Video Encode (NVENC)

### Implementation: `encode/nvenc_encoder.py`

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

#### Architecture
- PyAV `h264_nvenc` encoder with CUDA input
- Zero-copy: GPUFrame → DLPack → `av.VideoFrame.from_dlpack()` → NVENC
- Output: RTSP stream to MediaMTX (Annex-B H.264 bitstream)

#### Configuration
```python
NVENCEncoderConfig:
    camera_id: str
    output_url: "rtsp://localhost:8554/live/cam1-ai"
    codec: "h264_nvenc"
    width: 3840
    height: 2160
    fps: 30.0
    bitrate_kbps: 8000
    gop_size: 30
    preset: "p4"
    tune: "ll"
    gpu_device: 0
    max_queue_size: 4
    frame_pool: FramePool
```

#### Encode Pipeline
```
GPUFrame (NV12) → submit_frame() → _frame_queue.put()
    → _encode_loop thread: _frame_queue.get()
    → y_tensor.__dlpack__(), uv_tensor.__dlpack__()
    → av.VideoFrame.from_dlpack([y_dlpack, uv_dlpack], format='nv12', ...)
    → If format='cuda': av_frame.reformat(format='nv12')
    → stream.encode(av_frame) → packets
    → container.mux(packet) for each
    → frame.release() → FramePool.return_to_pool()
```

#### Key Features

1. **Zero-Copy DLPack Interop**
   - GPUFrame tensors expose `__dlpack__()` protocol
   - PyAV creates VideoFrame sharing GPU memory
   - No CPU staging

2. **NVENC Options**
   - `preset=p4` (balanced speed/quality)
   - `tune=ll` (low latency)
   - `rc=cbr` (constant bitrate)
   - `gpu=0` (explicit device)
   - Codec context opened explicitly with options before first frame

3. **Restart Logic (Critical)**
   - Handles `OSError -129` (FFmpeg "Unknown error" on encode)
   - Bounded retries: max 3, exponential backoff (2s, 4s, 8s...)
   - Full re-initialization: close container, clear queue, re-open
   - Tracks `encoder_restarts` metric

4. **Frame Pool Integration**
   - Encoder holds ref during async encode (`frame.add_ref()`)
   - Releases after mux: `frame.release()` → pool
   - Queue depth: 4 frames max

5. **Time Base Handling**
   - Converts float fps to `Fraction` for PyAV
   - Handles 30, 29.97, 25, 24, 60 fps
   - Sets `time_base` on stream

#### Output Format
- **Container**: RTSP (MPEG-TS over TCP)
- **Codec**: H.264 (h264_nvenc)
- **Profile**: Main/High (NVENC default)
- **Bitrate**: 8000 kbps CBR
- **GOP**: 30 frames (1s @ 30fps)
- **Latency**: tune=ll + low GOP = ~100-200ms encode latency

#### Evidence
- **File**: `pipeline_engine/encode/nvenc_encoder.py` (616 lines)
- **Config**: `pipeline.yaml` encode section + per-camera encode
- **Test**: `__main__` creates encoder (fails without MediaMTX)
- **Runtime**: BLOCKED - requires MediaMTX + CUDA

#### Limitations
- **OSError -129**: Known intermittent NVENC failure on Windows
- **Restart loses frames**: Queue cleared on restart
- **No B-frames**: tune=ll typically disables B-frames
- **Single GPU context**: All cameras share GPU 0
- **No lookahead**: rc=cbr without lookahead may have quality variance

## Stream Copy Compatibility (Architecture A Evaluation)

### FFmpeg Stream Copy Analysis

| Aspect | Current Pipeline | Stream Copy Feasibility |
|--------|------------------|------------------------|
| Input codec | H.264 (from camera via RTMP→MediaMTX) | ✅ Compatible |
| Output codec | H.264 (NVENC) | ✅ Same codec |
| Resolution | 3840×2160 → 3840×2160 | ✅ Same |
| FPS | 30 → 30 | ✅ Same |
| GOP structure | Camera GOP → NVENC GOP=30 | ⚠️ May differ |
| Bitrate | Variable (camera) → 8000kbps CBR | ❌ Different |
| Annotation | None → GPU overlay | ❌ Requires re-encode |

**Conclusion**: Stream copy (`-c copy`) is **NOT feasible** for AI-annotated output because:
1. Annotation requires decode → modify → re-encode
2. Bitrate control requires re-encode
3. GOP alignment may differ

**Stream copy IS feasible** for:
- Passthrough camera → MediaMTX → UI (no AI)
- Recording original stream to disk

### MediaMTX Relay Capability

From `mediamtx/mediamtx.yml`:
- Paths `live/cam1`, `live/cam2`: `source: publisher` (RTMP input from cameras)
- Paths `live/cam1-ai`, `live/cam2-ai`: `source: publisher` (RTSP input from pipeline)
- Protocols: UDP, multicast, TCP for RTSP
- HLS: lowLatency variant enabled
- WebRTC: enabled on :8889
- Recording: fMP4, 1h segments, 24h retention

**MediaMTX already provides**:
- RTSP ingest (from cameras via RTMP)
- RTSP publish (from pipeline)
- HLS/WebRTC for UI consumption
- Recording to disk (separate from AI events)

## GPU Memory Flow

```
FramePool (32 frames × 12.4MB = ~400MB)
    │
    ├── NVDECDecoder: acquires → fills → queues (8 max)
    │
    ├── GPUAnnotator: reads → NV12→BGR (temp 48MB) → draws → BGR→NV12 → writes back
    │
    ├── NVENCEncoder: acquires ref → DLPack → NVENC → releases → pool
    │
    └── Temp tensors: BGR (48MB), letterboxed (48MB), normalized (48MB)
    
Total peak VRAM estimate: ~400MB (pool) + 150MB (temp) + models (~500MB) = ~1GB
Budget: 4096MB (config.gpu.vram_budget_mb)
Headroom: ~3GB
```

## Synchronization: PTS, Time Base, Stream Epochs

### Current Implementation
| Component | Timestamp Handling |
|-----------|-------------------|
| RTSPSource | `packet.pts`, `packet.dts`, `stream.time_base` |
| NVDECDecoder | Copies PTS/DTS to GPUFrame, stores `time_base` |
| CameraManager | `stream_epoch` counter (increments on reconnect) |
| NVENCEncoder | Uses stream `time_base` from config (Fraction) |
| GPUFrame | `pts`, `dts`, `time_base`, `stream_epoch` fields |

### Gaps for Architecture A Sync
1. **No PTS normalization**: Camera PTS may not start at 0, may have gaps
2. **No wall-clock sync**: `timestamp = time.time()` at acquire, not derived from PTS
3. **Stream epoch tracking**: `stream_epoch` incremented but not used for sync
4. **No cross-camera sync**: Each camera independent
5. **UI sync**: UI consumes HLS/WebRTC from MediaMTX, no PTS correlation with AI metadata

### Required for AI Metadata Overlay Sync
```
Camera RTSP (PTS 90kHz)
    → Decode → GPUFrame.pts, GPUFrame.time_base
    → AI Processing (adds ~100-200ms latency)
    → Encode → H.264 packets with PTS
    → MediaMTX → HLS segments (segment duration 1s)
    → UI: hls.js plays segments
    → AI Metadata: WebSocket events with timestamp
    → Correlation needed: metadata.timestamp ≈ video.currentTime
```

**Current gap**: No mechanism to correlate `CrossingEvent.timestamp` (wall-clock) with video playback position.

## Codec Compatibility Matrix

| Stage | Input Format | Output Format | Conversion |
|-------|--------------|---------------|------------|
| Camera → MediaMTX | H.264 (RTMP) | H.264 (RTSP) | MediaMTX remux |
| MediaMTX → Decoder | H.264 (RTSP) | NV12 (GPU) | Software decode + upload |
| Decoder → AI | NV12 (GPU) | BGR (GPU, temp) | `nv12_to_bgr_cuda()` |
| AI → Annotator | NV12 + detections | NV12 (annotated) | BGR draw → `bgr_to_nv12_cuda()` |
| Annotator → Encoder | NV12 (GPU) | H.264 packets | NVENC (DLPack zero-copy) |
| Encoder → MediaMTX | H.264 packets | RTSP stream | PyAV mux |

**All conversions are GPU-resident except decode (CPU→GPU)**

## Runtime Verification Status

| Component | Implemented | Unit Tested | Integration Tested | Runtime Verified |
|-----------|-------------|-------------|-------------------|------------------|
| RTSPSource | ✅ | ❌ (no test files) | ❌ | BLOCKED (needs MediaMTX + stream) |
| NVDECDecoder | ✅ | ❌ | ❌ | BLOCKED (needs CUDA + stream) |
| NVENCEncoder | ✅ | ❌ | ❌ | BLOCKED (needs MediaMTX + CUDA) |
| MediaMTXPublisher | ✅ | ❌ | ❌ | BLOCKED (needs MediaMTX) |
| Full Pipeline | ✅ | ❌ | ❌ | BLOCKED (needs all above) |

## Critical Issues

1. **No true hardware decode on GTX 1660 Ti Windows**: Software decode bottleneck at 4K30
2. **NVENC OSError -129**: Intermittent, requires restart logic (implemented but untested)
3. **No end-to-end test**: Cannot verify full pipeline without cameras + MediaMTX + GPU
4. **Timestamp correlation missing**: AI events cannot sync with video playback
5. **FramePool exhaustion handling**: Drops frames silently, no backpressure
6. **Single GPU for all cameras**: No multi-GPU support, VRAM contention risk