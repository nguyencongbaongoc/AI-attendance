# Phase 36D — NVDEC Integration Architecture Design

**Date:** 2026-08-25  
**Status:** DESIGN PHASE - Before Implementation

---

## 1. Current Architecture Analysis

### 1.1 Current Pipeline (Software Decode)

```
RTSP/TCP (MediaMTX)
    ↓
OpenCV VideoCapture (cv2.VideoCapture)
    ↓
CPU H.264 decode (FFmpeg backend, software)
    ↓
numpy uint8 BGR frames
    ↓
VideoFrameIterator (app/data/input_adapter.py)
    ↓
CanonicalFrame (BGR, CPU memory)
    ↓
RTSPSource / ReplaySource (app/streaming/rtsp_source.py, app/replay/source.py)
    ↓
V2 Ingestion → AI Pipeline
```

### 1.2 Key Components

| Component | File | Role |
|-----------|------|------|
| VideoFrameIterator | app/data/input_adapter.py | Streaming video frame iterator using OpenCV |
| RTSPSource | app/streaming/rtsp_source.py | RTSP adapter with camera_id, wall-clock timestamps |
| ReplaySource | app/replay/source.py | Offline replay source with ReplayClock |
| CanonicalFrame | app/data/frame.py | Immutable frame contract (data + metadata) |
| FrameMetadata | app/data/frame.py | Frame metadata (pixel_format=BGR, dtype=uint8) |

### 1.3 Frame Contract (V2)

```python
CanonicalFrame:
  data: np.ndarray (HWC, BGR, uint8)
  metadata:
    source_type: VIDEO
    source_id: str (RTSP URL)
    frame_index: int
    timestamp: float (wall-clock for live)
    original_width: 3840
    original_height: 2160
    pixel_format: PixelFormat.BGR
    dtype: "uint8"
    extra: {camera_id, replay_timestamp, wall_clock_receive_time}
```

---

## 2. NVDEC Target Architecture

### 2.1 Proposed Pipeline (NVDEC Decode)

```
RTSP/TCP (MediaMTX)
    ↓
FFmpeg subprocess (h264_cuvid / NVDEC)
    ↓
GPU decoded frames (NV12 / P010)
    ↓
GPU→CPU transfer (sws_scale / cuvidMapVideoFrame)
    ↓
numpy uint8 BGR frames (CPU memory)
    ↓
VideoFrameIterator (unchanged interface)
    ↓
CanonicalFrame (BGR, CPU memory) ← SAME CONTRACT
    ↓
RTSPSource / ReplaySource (unchanged)
    ↓
V2 Ingestion → AI Pipeline
```

### 2.2 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **NOT zero-copy** | CanonicalFrame requires CPU numpy arrays; GPU→CPU transfer required |
| **FFmpeg subprocess** | Reuses existing FFmpeg binary; no new Python dependencies |
| **Decoder selection via config** | Explicit, observable, no silent switching |
| **Software fallback preserved** | Controlled baseline for A/B comparison |
| **Single ingestion path** | RTSPSource/ReplaySource unchanged; only VideoFrameIterator backend changes |

### 2.3 FFmpeg NVDEC Command Template

```bash
ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp \
  -hwaccel cuda \
  -hwaccel_output_format cuda \
  -c:v h264_cuvid \
  -i "rtsp://127.0.0.1:8554/live/cam1" \
  -f rawvideo \
  -pix_fmt bgr24 \
  -vsync 0 \
  -an \
  pipe:1
```

**Output:** Raw BGR24 frames to stdout (no container overhead)

---

## 3. Integration Points

### 3.1 VideoFrameIterator Modification

**Current:** Uses `cv2.VideoCapture` directly  
**New:** Add `decoder` parameter ("software" | "nvdec")

```python
class VideoFrameIterator:
    def __init__(self, video_path: Union[str, Path], decoder: str = "software"):
        self._decoder = decoder  # "software" or "nvdec"
        # ... existing init ...
    
    def _open(self):
        if self._decoder == "nvdec" and self._is_rtsp:
            self._open_nvdec()
        else:
            self._open_software()  # existing cv2.VideoCapture path
```

### 3.2 NVDEC Frame Reader

```python
def _open_nvdec(self):
    """Open FFmpeg subprocess with NVDEC decoder."""
    cmd = [
        "ffmpeg",
        "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-c:v", "h264_cuvid",
        "-i", self._path_str,
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-vsync", "0",
        "-an",
        "pipe:1"
    ]
    self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    self._frame_size = self._info.width * self._info.height * 3  # BGR24
    self._stdout = self._proc.stdout
```

### 3.3 Frame Reading (NVDEC)

```python
def __next__(self):
    if self._decoder == "nvdec":
        return self._read_nvdec_frame()
    else:
        return self._read_software_frame()  # existing

def _read_nvdec_frame(self):
    """Read one raw BGR24 frame from FFmpeg stdout."""
    frame_data = self._stdout.read(self._frame_size)
    if len(frame_data) < self._frame_size:
        self.close()
        raise StopIteration
    
    frame = np.frombuffer(frame_data, dtype=np.uint8).reshape(
        self._info.height, self._info.width, 3
    )
    # Create CanonicalFrame (same as software path)
    ...
```

---

## 4. Configuration System

### 4.1 Settings Extension (app/config/settings.py)

```python
class MediaConfig(BaseModel):
    """Media configuration section."""
    ffmpeg_path: Optional[str] = Field(default=None, description="Explicit FFmpeg path")
    
    # NVDEC Configuration (Phase 36D)
    nvdec_enabled: bool = Field(default=False, description="Enable NVDEC hardware decoding")
    nvdec_gpu_device: int = Field(default=0, description="GPU device ordinal for NVDEC")
    nvdec_surfaces: int = Field(default=32, description="NVDEC decode surfaces")
```

### 4.2 RTSPSourceConfig Extension (app/streaming/rtsp_source.py)

```python
@dataclass(frozen=True)
class RTSPSourceConfig:
    # ... existing fields ...
    decoder: str = "software"  # "software" | "nvdec"
    nvdec_gpu_device: int = 0
```

---

## 5. Decoder Selection & Observability

### 5.1 Explicit Selection

- **Configuration-driven:** `decoder` field in RTSPSourceConfig
- **No auto-detection:** Must be explicitly set
- **Per-camera:** CAM1 and CAM2 can use different decoders

### 5.2 Runtime Logging

```python
logger.info(f"RTSP source opened: camera_id={self.camera_id}, decoder={self.config.decoder}")
```

### 5.3 Telemetry

- Decoder type reported in health snapshots
- GPU memory tracked via pynvml
- CPU utilization comparison (A/B)

---

## 6. Frame Contract Preservation

### 6.1 Verification Checklist

| Property | Software | NVDEC | Must Match |
|----------|----------|-------|------------|
| dtype | uint8 | uint8 | ✅ |
| shape | (2160, 3840, 3) | (2160, 3840, 3) | ✅ |
| pixel_format | BGR | BGR | ✅ |
| channels | 3 | 3 | ✅ |
| frame_index | monotonic | monotonic | ✅ |
| timestamp | wall-clock | wall-clock | ✅ |
| camera_id | preserved | preserved | ✅ |

### 6.2 Conversion Pipeline

NVDEC outputs NV12 (YUV 4:2:0) → FFmpeg sws_scale → BGR24 → numpy

This is **explicit conversion**, tracked in `conversions_applied`.

---

## 7. Bounded Queue / Latest-Frame Policy

### 7.1 Current Behavior

- `max_queue_size=10` in RTSPSourceConfig
- RTSPSource uses blocking `get_next_frame()` 
- Queue managed by caller (FrameRingBuffer in pipeline)

### 7.2 NVDEC Impact

- FFmpeg subprocess produces frames at decode speed
- If consumer slower, FFmpeg stdout buffer fills → backpressure
- Must ensure `-vsync 0` (no frame duplication/dropping by FFmpeg)
- Application-level queue policy unchanged

---

## 8. GPU Memory Safety (GTX 1660 Ti, 6 GB)

### 8.1 Expected Allocations

| Component | VRAM Estimate |
|-----------|---------------|
| NVDEC CAM1 (4K, 32 surfaces) | ~200 MB |
| NVDEC CAM2 (4K, 32 surfaces) | ~200 MB |
| ArcFace ONNX (CUDA EP) | ~500 MB |
| SCRFD ONNX (CUDA EP) | ~300 MB |
| PyTorch overhead | ~200 MB |
| **Total** | **~1.4 GB** |

**Well within 6 GB limit.**

### 8.2 Monitoring

- pynvml memory tracking before/after NVDEC init
- Alert if VRAM > 5 GB sustained

---

## 9. Failure / Fallback Behavior

### 9.1 NVDEC Failure Modes

| Failure | Detection | Behavior |
|---------|-----------|----------|
| Invalid GPU device | FFmpeg stderr | Explicit error, no retry |
| h264_cuvid unavailable | FFmpeg stderr | Explicit error |
| CUDA OOM | FFmpeg stderr | Explicit error |
| Decoder context leak | VRAM growth | Monitor, alert |

### 9.2 Fallback Strategy

**Phase 36D: NO automatic fallback**

- NVDEC failure = explicit error
- Operator must manually switch config to "software"
- Prevents silent degradation

---

## 10. Performance A/B Test Plan

### 10.1 Test Matrix

| Test | Decoder | Duration | Metrics |
|------|---------|----------|---------|
| A | software | 60s | CPU%, GPU%, VRAM, decode FPS, process FPS, latency |
| B | nvdec | 60s | CPU%, GPU%, VRAM, decode FPS, process FPS, latency |

### 10.2 Metrics to Capture

- **Source FPS:** Frames received from RTSP
- **Decode FPS:** Frames decoded (may differ from source)
- **Processing FPS:** Frames through AI pipeline
- **Inference Latency:** End-to-end per frame
- **CPU Utilization:** Process + system
- **GPU Utilization:** pynvml aggregate
- **VRAM:** Peak and sustained
- **Dropped Frames:** Queue overflow count
- **Frame Continuity:** Max gap, discontinuities

---

## 11. Timestamp Validation

### 11.1 Current Behavior (Phase 36C Verified)

- Wall-clock receive time for live streams
- Monotonic at application boundary
- Upstream DTS defects do NOT propagate

### 11.2 NVDEC Must Preserve

- Same wall-clock timestamp logic in RTSPSource
- No PTS/DTS from NVDEC used for application timestamps
- ReplayClock unchanged for offline replay

---

## 12. Implementation Files to Modify

| File | Change |
|------|--------|
| `app/config/settings.py` | Add NVDEC config to MediaConfig |
| `app/streaming/rtsp_source.py` | Add decoder field to RTSPSourceConfig |
| `app/data/input_adapter.py` | Add decoder parameter to VideoFrameIterator |
| `app/data/input_adapter.py` | Implement NVDEC frame reading path |
| `tests/unit/test_phase36d_nvdec_integration.py` | Unit tests |
| `tests/integration/test_phase36d_nvdec_integration.py` | Integration tests |

---

## 13. Acceptance Criteria (from Phase 36D spec)

| Criterion | Verification Method |
|-----------|---------------------|
| Real CAM1 + CAM2 | Live test with MediaMTX |
| Real NVDEC | FFmpeg h264_cuvid selected |
| Canonical V2 ingestion | RTSPSource unchanged |
| Frame contract preserved | Unit test CanonicalFrame fields |
| Timestamp monotonicity | Live test 60s, 0 regressions |
| Camera ID integrity | Cross-camera isolation test |
| Bounded queues | Queue depth ≤ 10 |
| VRAM bounded | pynvml monitoring |
| No decoder instability | 60s continuous decode |
| CPU/GPU metrics honest | A/B comparison |
| Regression tests pass | Phase 32-36C test suites |

---

## 14. Known Limitations (Pre-Documented)

1. **NOT zero-copy** — GPU→CPU transfer required for CanonicalFrame contract
2. **No automatic fallback** — NVDEC failure = explicit error
3. **GTX 1660 Ti NVDEC limit** — 4K H.264 supported, HEVC 4K not supported
4. **Single GPU** — Both cameras share GPU decode contexts
5. **FFmpeg subprocess overhead** — Process management vs in-process OpenCV

---

## 15. Next Steps

1. ✅ Architecture documented
2. ⏳ Implement NVDEC in VideoFrameIterator
3. ⏳ Add config to Settings
4. ⏳ Update RTSPSourceConfig
5. ⏳ Create unit/integration tests
6. ⏳ Run A/B performance tests
7. ⏳ Generate PHASE_36D_NVDEC_INTEGRATION.json/.md reports