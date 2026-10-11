# GPU Memory and Frame Ownership Audit

## GPUFrame Contract (`memory/gpu_frame.py`)

**Status: IMPLEMENTED, DESIGN COMPLETE**

### Core Design
```python
@dataclass
class GPUFrame:
    # Identity
    camera_id: str
    frame_id: int                    # Monotonic per-camera counter
    global_frame_id: str             # UUID for cross-stage tracking
    source_provenance: str           # "rtsp", "rtmp", "file", "synthetic"
    
    # Media Timing
    timestamp: float                 # Wall-clock (time.time())
    pts: Optional[int]               # Presentation timestamp from stream
    dts: Optional[int]               # Decode timestamp from stream
    time_base: Optional[float]       # Stream time base (e.g., 1/90000)
    
    # Dimensions
    width: int
    height: int
    actual_width: Optional[int]
    actual_height: Optional[int]
    pixel_format: PixelFormat        # NV12, NV16, BGR, RGB
    
    # CUDA Context
    cuda_context: CUDAContext        # device_id, stream_ptr, stream
    
    # GPU Memory (NV12 two-plane)
    y_tensor: torch.Tensor           # (H, W) uint8 on CUDA
    uv_tensor: torch.Tensor          # (H/2, W/2, 2) uint8 on CUDA
    _y_ptr: int                      # Cached data_ptr()
    _uv_ptr: int                     # Cached data_ptr()
    
    # Ownership / Lifetime
    memory_owner: FrameOwnership     # DECODER, PREPROCESS, INFERENCE, TRACKING, ANNOTATION, ENCODER, PUBLISHER, EXTERNAL
    status: FrameStatus              # NEW, DECODING, DECODED, PREPROCESSING, INFERRING, TRACKING, ANNOTATING, ENCODING, ENCODED, PUBLISHING, COMPLETED, DROPPED, ERROR
    released: bool
    ref_count: int                   # Reference counting
    _encoder_ref: Any                # Encoder holds extra ref during async encode
    
    # Annotation
    _annotation_tensor: torch.Tensor # BGR overlay tensor
    
    # Processing Metadata
    decode_time_ms: float
    preprocess_time_ms: float
    inference_time_ms: float
    tracking_time_ms: float
    annotation_time_ms: float
    encode_time_ms: float
    
    # Error Tracking
    error: Optional[str]
    error_stage: Optional[str]
```

### Key Methods
| Method | Purpose |
|--------|---------|
| `from_pyav_nvdec()` | Factory from PyAV NVDEC output (UNUSED) |
| `create_empty()` | Factory for testing/synthetic frames |
| `get_tensors()` | Returns (y_tensor, uv_tensor) |
| `get_gpu_pointers()` | Returns (y_ptr, uv_ptr) for NVENC |
| `get_annotation_tensor()` | Returns BGR overlay tensor |
| `set_annotation_tensor()` | Sets BGR overlay tensor |
| `add_ref()` / `release()` | Reference counting |
| `transfer_ownership()` | Transfers to next pipeline stage |
| `set_status()` | Updates processing status |
| `validate()` | Checks tensor integrity |
| `to_dict()` | Serialization for logging |
| `get_latency_breakdown()` | Per-stage timing |

### GPU Conversion Utilities
| Function | Purpose | Implementation |
|----------|---------|----------------|
| `nv12_to_bgr_cuda()` | NV12 → BGR (GPU) | PyTorch interpolate + BT.601 matrix |
| `bgr_to_nv12_cuda()` | BGR → NV12 (GPU) | BT.601 + interpolate downsample UV |
| `letterbox_resize_cuda()` | Aspect-preserving resize | PyTorch interpolate + padding |

## Frame Pool (`memory/frame_pool.py`)

**Status: IMPLEMENTED**

### FramePool (per camera)
```python
FramePoolConfig:
    camera_id: str
    width: 3840
    height: 2160
    pixel_format: NV12
    min_size: 8        # Pre-allocated (HYBRID strategy)
    max_size: 32       # Hard limit
    strategy: HYBRID   # FIXED, DYNAMIC, HYBRID
    device_id: 0
```

### Pool Behavior
1. **Pre-allocation**: Creates `min_size` frames at init (HYBRID)
2. **Acquisition**: 
   - Reuses available frame from `_available` deque
   - Creates new if `< max_size`
   - Raises `RuntimeError` if exhausted
3. **Release**:
   - `release()`: Decrements ref_count, returns to pool if ref_count=0
   - `return_to_pool()`: Explicit return (for completed frames)
   - Pool full on return: destroys frame (`_release_internal()`)
4. **Stats Tracking**:
   - `total_allocated`, `current_available`, `current_in_use`, `peak_in_use`
   - `allocations`, `releases`, `exhaustion_events`, `allocation_failures`

### FramePoolManager (global)
- Manages pools for all cameras
- `get_total_vram_mb()`: Estimates VRAM across all pools
- `handle_memory_pressure()`: Shrinks available pools to `min_size` at 90% budget
- `shutdown()`: Clears all pools

### VRAM Calculation
```
Per frame (NV12 3840×2160):
  Y plane: 3840 × 2160 × 1 byte = 8,294,400 bytes
  UV plane: 1920 × 1080 × 2 bytes = 4,147,200 bytes
  Total: 12,441,600 bytes ≈ 11.87 MB

Pool (32 frames): ~380 MB
2 cameras: ~760 MB
+ Temp tensors (BGR, letterbox, normalized): ~150 MB/camera
+ Models (SCRFD, ArcFace, YOLO): ~500 MB
Total: ~1.5 GB / 4096 MB budget (37%)
```

## Memory Monitor (`memory/memory_monitor.py`)

**Status: IMPLEMENTED**

### GPUMemoryMonitor
```python
MemoryThresholds:
    normal_pct: 0.60      # < 60% of budget
    elevated_pct: 0.75    # 60-75%
    high_pct: 0.90        # 75-90%
    critical_pct: 0.95    # > 90%
```

### Monitoring Loop (1s interval)
```python
_take_snapshot():
    allocated = torch.cuda.memory_allocated()
    reserved = torch.cuda.memory_reserved()
    total = torch.cuda.get_device_properties().total_memory
    
    utilization_pct = reserved_mb / vram_budget_mb
    pressure_level = determine from thresholds
```

### Pressure Callbacks
```python
register_callback(level, callback)
# Levels: NORMAL, ELEVATED, HIGH, CRITICAL, OOM
# Triggers callbacks for level AND all higher levels
```

### PipelineEngine Integration
```python
# In engine.py initialize():
self.memory_monitor.register_callback(MemoryPressureLevel.HIGH, self._on_memory_pressure)
self.memory_monitor.register_callback(MemoryPressureLevel.CRITICAL, self._on_memory_critical)

def _on_memory_pressure(self, snapshot):
    logger.warning(f"HIGH memory pressure - {snapshot.utilization_pct:.1f}%")
    # Could trigger frame dropping, reduce batch size

def _on_memory_critical(self, snapshot):
    logger.error(f"CRITICAL memory pressure - {snapshot.utilization_pct:.1f}%")
    self.memory_monitor.empty_cache()
```

### FramePoolManager Integration
```python
def handle_memory_pressure(self):
    current_vram = self.get_total_vram_mb()
    if current_vram > self.vram_budget_mb * 0.9:
        # Shrink available pools to min_size
        for pool in self._pools.values():
            while pool.get_available_count() > pool.config.min_size:
                frame = pool._available.popleft()
                frame._release_internal()
```

## Ownership Transfer Protocol

### Stage Ownership Sequence
```
DECODER (ref=1)
    → acquire() from FramePool
    → decoder fills tensors
    → transfer_ownership(DECODER), set_status(DECODED)
    
INFERENCE (ref=1)
    → reads tensors (NV12→BGR creates temp tensor)
    → transfer_ownership(INFERENCE), set_status(INFERRING)
    → creates detection objects (CPU dataclasses)
    
TRACKING (ref=1)
    → reads detections
    → transfer_ownership(TRACKING), set_status(TRACKING)
    → updates Track objects (CPU)
    
ANNOTATION (ref=1)
    → NV12→BGR (GPU), draws, BGR→NV12 (GPU), copies to frame tensors
    → set_annotation_tensor(BGR) for encoder
    → transfer_ownership(ANNOTATION), set_status(ANNOTATING)
    
ENCODER (ref=2 during encode)
    → submit_frame(): frame.add_ref() (ref=2)
    → _encode_loop: from_dlpack(), encode, mux
    → frame.release() (ref=1)
    → FramePool.return_to_pool() → status=COMPLETED
```

### Reference Counting Rules
1. **FramePool.acquire()**: Sets `ref_count=1`, owner=DECODER
2. **Encoder.submit_frame()**: `frame.add_ref()` → `ref_count=2`
3. **Encoder after mux**: `frame.release()` → `ref_count=1`
4. **FramePool.return_to_pool()**: `frame.release()` → `ref_count=0` → `_release_internal()`
5. **Early drop**: `frame.release()` → `_release_internal()` if ref_count reaches 0

### Zero-Copy Guarantees
| Transfer | Mechanism | Copy? |
|----------|-----------|-------|
| Decoder → Pool | Pre-allocated tensors, `copy_()` | ❌ (GPU→GPU) |
| Pool → Inference | Same tensors, `nv12_to_bgr_cuda()` | ✅ (creates temp BGR) |
| Inference → Tracking | Detection objects (CPU) | N/A |
| Tracking → Annotation | Same frame tensors | ❌ |
| Annotation → Encoder | Same frame tensors + DLPack | ❌ (zero-copy) |
| Encoder → NVENC | `VideoFrame.from_dlpack()` | ❌ (zero-copy) |

**Only GPU memory copy**: NV12↔BGR conversions for annotation (2× per frame)

## CUDA Stream Management

### Current Implementation
```python
# config.yaml
cuda_stream_per_camera: true
synchronize_on_decode: true
synchronize_on_encode: true

# In NVDECDecoder:
self._cuda_stream = config.cuda_stream or torch.cuda.current_stream()
self._sync = CUDASyncManager(device_id=config.gpu_device)

# In CameraManager._initialize_camera():
cuda_stream = torch.cuda.Stream(device=device_id) if config.get("cuda_stream_per_camera") else None
```

### Synchronization Points
| Location | Sync Type | Purpose |
|----------|-----------|---------|
| `nv12_to_bgr_cuda()` | Implicit (PyTorch ops) | Kernel completion |
| `bgr_to_nv12_cuda()` | Implicit | Kernel completion |
| `torch.cuda.synchronize()` | Explicit | After DLPack tensor creation in decoder |
| `DLPack → VideoFrame` | Implicit (PyAV) | Ensures tensors ready for NVENC |
| `stream.encode()` | Implicit (NVENC) | Encode completion |

### Stream Per Camera
- Each camera gets dedicated `torch.cuda.Stream`
- Allows overlap: Camera 1 decode || Camera 2 inference || Camera 1 encode
- Not fully utilized: Pipeline loop is sequential per camera

## Memory Pressure Handling

### Current Response
| Pressure Level | Action |
|----------------|--------|
| NORMAL | None |
| ELEVATED | Log warning |
| HIGH | `PipelineEngine._on_memory_pressure()` - logs, could reduce batch size |
| CRITICAL | `PipelineEngine._on_memory_critical()` - `empty_cache()`, `FramePoolManager.handle_memory_pressure()` |
| OOM | Not explicitly handled |

### Gaps
1. **No automatic batch size reduction**: `get_recommended_batch_size()` exists but not called
2. **No frame dropping under pressure**: FramePool only drops on exhaustion, not pressure
3. **No inference quality scaling**: Could reduce input resolution under pressure
4. **No encoder bitrate reduction**: Could lower bitrate under pressure

## Frame Ownership Bugs / Risks

### 1. Double Release Risk
```python
# In CameraManager._camera_pipeline_loop():
if encoder.submit_frame(annotated_frame):
    # encoder holds ref (ref=2)
else:
    frame_pool.return_to_pool(annotated_frame)  # ref=1 → release → ref=0 → destroyed
    continue

# In NVENCEncoder._encode_loop():
frame.release()  # ref=2 → ref=1
frame_pool.return_to_pool(frame)  # ref=1 → release → ref=0 → destroyed

# If encoder fails after submit but before encode_loop processes:
# Frame has ref=2, pool has no reference → leak until encoder processes or stops
```

### 2. Annotation Tensor Lifetime
```python
# GPUAnnotator.annotate():
frame.set_annotation_tensor(bgr)  # Stores reference to BGR tensor
# BGR tensor is local variable, but frame holds reference
# When frame returned to pool: _annotation_tensor not cleared in return_to_pool()
# Next acquire(): _annotation_tensor cleared in acquire() reset
```

### 3. FramePool Exhaustion
```python
# In CameraManager._camera_pipeline_loop():
try:
    frame = frame_pool.acquire(...)
except RuntimeError:
    camera["metrics"].frames_dropped += 1
    continue  # No backpressure to RTSP source

# In NVENCEncoder.submit_frame():
try:
    self._frame_queue.put_nowait(gpu_frame)
except Full:
    # Drop oldest, insert newest
    # But encoder may still be processing dropped frame (ref=2)
```

### 4. DLPack Capsule Lifetime
```python
# NVENCEncoder._encode_loop():
y_dlpack = gpu_frame.y_tensor.__dlpack__()
uv_dlpack = gpu_frame.uv_tensor.__dlpack__()
av_frame = av.VideoFrame.from_dlpack([y_dlpack, uv_dlpack], ...)

# DLPack capsules are consumed by from_dlpack()
# Tensors must stay alive until encode completes
# frame.add_ref() ensures this, but what if encoder restarts mid-encode?
```

## CUDA Context Management

### Current State
```python
# GPUFrame.cuda_context: CUDAContext with device_id, stream_ptr, stream
# Created via CUDAContext.current(device_id)

# In NVDECDecoder:
torch.cuda.set_device(self._cuda_device)
# Pre-allocates tensors on this device

# In CameraManager:
device_id = cam_config.get("decode", {}).get("gpu_device", 0)
# All components for camera use same device_id
```

### Issues
1. **No context isolation**: All cameras share default context on device 0
2. **No primary context**: Uses driver API primary context implicitly
3. **Stream management**: Per-camera streams created but not consistently used
4. **Multi-GPU**: Not supported (single device_id=0 everywhere)

## NVENC Zero-Copy Verification

### DLPack Path
```
GPUFrame.y_tensor (torch.Tensor, CUDA)
    → __dlpack__() → DLPack capsule (DLManagedTensor)
    → av.VideoFrame.from_dlpack([y_cap, uv_cap], format='nv12', device_id=0)
    → PyAV creates AVFrame with cuda buffer referencing same memory
    → If format='cuda': av_frame.reformat(format='nv12') → may copy
    → stream.encode(av_frame) → NVENC reads from CUDA memory
```

### Verification Needed
- [ ] Confirm `av_frame.format.name == 'nv12'` after from_dlpack
- [ ] Confirm no implicit copy in `reformat()`
- [ ] Measure GPU memory during encode (should not increase)
- [ ] Test with `nvidia-smi` during pipeline run

## Evidence Summary

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| GPUFrame contract | `memory/gpu_frame.py` | 626 | IMPLEMENTED |
| FramePool | `memory/frame_pool.py` | 466 | IMPLEMENTED |
| GPUMemoryMonitor | `memory/memory_monitor.py` | 437 | IMPLEMENTED |
| OwnershipManager | `memory/ownership.py` | ~200 | IMPLEMENTED, UNUSED |
| CUDASyncManager | `memory/synchronization.py` | ~150 | IMPLEMENTED, PARTIALLY USED |
| NVDEC integration | `decode/nvdec_decoder.py` | 580 | Uses FramePool, GPUFrame |
| NVENC integration | `encode/nvenc_encoder.py` | 616 | Uses FramePool, GPUFrame, DLPack |
| Annotator integration | `annotation/overlay.py` | 365 | Uses GPUFrame, nv12↔bgr |

## Runtime Verification

**ALL GPU MEMORY COMPONENTS: BLOCKED**

Requires:
- CUDA 12.6 + PyTorch 2.13 +cu126
- GTX 1660 Ti (6GB VRAM)
- RTSP streams at 4K30
- MediaMTX running

Cannot verify:
- Actual VRAM usage vs estimates
- FramePool exhaustion behavior under load
- Memory pressure callback effectiveness
- DLPack zero-copy correctness
- CUDA stream overlap efficiency
- Encoder restart memory cleanup

## Recommendations for Architecture A

1. **Keep GPUFrame contract**: Well-designed, supports zero-copy
2. **Adapt FramePool**: Reduce pool size if single AI path (no dual encode)
3. **Remove OwnershipManager**: Unused, adds complexity
4. **Simplify MemoryMonitor**: Keep for alerts, remove batch size recommendation
5. **Fix ownership bugs**: Ensure encoder ref handling is robust
6. **Add PTS-based sync**: For Architecture A metadata overlay sync