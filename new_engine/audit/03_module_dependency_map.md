# Module Dependency Map

## Dependency Graph (Internal)

```
config/__init__.py (PipelineConfig, get_config)
    │
    ├── core/engine.py (PipelineEngine)
    │       │
    │       ├── ingestion/camera_manager.py (CameraManager)
    │       │       │
    │       │       ├── ingestion/rtsp_source.py (RTSPSource)
    │       │       │       └── av (PyAV)
    │       │       │
    │       │       ├── decode/nvdec_decoder.py (NVDECDecoder)
    │       │       │       ├── av (PyAV)
    │       │       │       ├── torch (CUDA tensors)
    │       │       │       └── memory/frame_pool.py (FramePool)
    │       │       │
    │       │       ├── inference/face_detection.py (SCRFDDetector)
    │       │       │       ├── onnxruntime (CUDA EP)
    │       │       │       ├── torch (GPU preprocessing)
    │       │       │       └── memory/gpu_frame.py (GPUFrame, nv12_to_bgr_cuda, letterbox_resize_cuda)
    │       │       │
    │       │       ├── inference/face_recognition.py (ArcFaceRecognizer)
    │       │       │       ├── onnxruntime (CUDA EP)
    │       │       │       ├── torch
    │       │       │       └── memory/gpu_frame.py
    │       │       │
    │       │       ├── inference/person_detection.py (YOLOPersonDetector)
    │       │       │       ├── onnxruntime (CUDA EP)
    │       │       │       ├── torch
    │       │       │       └── memory/gpu_frame.py
    │       │       │
    │       │       ├── tracking/tracker.py (Tracker)
    │       │       │       ├── numpy
    │       │       │       └── inference/face_recognition.py (ArcFaceRecognizer for ID)
    │       │       │
    │       │       ├── attendance/attendance_engine.py (AttendanceEngine)
    │       │       │       └── tracking/tracker.py (Track, TrackingResult)
    │       │       │
    │       │       ├── annotation/overlay.py (GPUAnnotator)
    │       │       │       ├── torch
    │       │       │       ├── memory/gpu_frame.py (nv12_to_bgr_cuda, bgr_to_nv12_cuda)
    │       │       │       └── tracking/tracker.py (Track)
    │       │       │
    │       │       ├── encode/nvenc_encoder.py (NVENCEncoder)
    │       │       │       ├── av (PyAV NVENC)
    │       │       │       ├── torch (CUDA)
    │       │       │       └── memory/frame_pool.py (FramePool)
    │       │       │
    │       │       └── output/publisher.py (MediaMTXPublisher)
    │       │               ├── av (PyAV RTSP muxer)
    │       │               └── subprocess (FFmpeg fallback)
    │       │
    │       ├── memory/frame_pool.py (FramePoolManager)
    │       │       └── memory/gpu_frame.py (GPUFrame)
    │       │
    │       └── memory/memory_monitor.py (GPUMemoryMonitor)
    │               └── torch (CUDA memory API)
    │
    ├── backend/app.py (FastAPI)
    │       └── core/engine.py (PipelineEngine, get_engine)
    │
    └── All modules import config via: from pipeline_engine.config import get_config
```

## External Dependencies

| Module | External Dependencies | Purpose |
|--------|----------------------|---------|
| All | `pydantic`, `pyyaml` | Configuration |
| `rtsp_source.py`, `nvdec_decoder.py`, `nvenc_encoder.py`, `publisher.py` | `av` (PyAV) | FFmpeg wrapper for stream I/O, decode, encode |
| `face_detection.py`, `face_recognition.py`, `person_detection.py`, `reid.py` | `onnxruntime-gpu` (CUDA EP) | ONNX model inference |
| `face_detection.py`, `face_recognition.py`, `person_detection.py`, `tracker.py`, `overlay.py`, `nvdec_decoder.py`, `nvenc_encoder.py`, `gpu_frame.py`, `frame_pool.py`, `memory_monitor.py` | `torch` (CUDA) | GPU tensor ops, CUDA memory management |
| `tracker.py`, `attendance_engine.py` | `numpy` | Geometry calculations |
| `attendance_engine.py` | `sqlite3` | Event persistence |
| `backend/app.py` | `fastapi`, `uvicorn`, `websockets` | REST + WebSocket API |
| `rtsp_source.py` | `socket` | TCP connectivity check |
| `publisher.py` | `subprocess` | FFmpeg fallback publisher |
| `memory_monitor.py` | `nvidia-ml-py` (optional) | GPU utilization (not used currently) |

## Data Flow Dependencies

### Camera Pipeline (per camera)
```
RTSPSource (ingestion)
    → produces: av.Packet (H.264 NAL units)
    → consumes: config (URL, transport, timeouts)
    
NVDECDecoder (decode)
    → consumes: av.Packet from RTSPSource
    → produces: GPUFrame (NV12, CUDA tensors via DLPack)
    → consumes: FramePool for allocation
    → config: codec, width, height, gpu_device, surfaces
    
SCRFDDetector (inference)
    → consumes: GPUFrame
    → produces: List[FaceDetection] (original frame coords)
    → GPU preprocessing: NV12→BGR→letterbox→normalize
    → config: model_path, confidence_threshold, input_size
    
YOLOPersonDetector (inference)
    → consumes: GPUFrame
    → produces: List[PersonDetection] (original frame coords)
    → GPU preprocessing: NV12→BGR→letterbox→normalize
    → config: model_path, confidence_threshold, input_size
    
ArcFaceRecognizer (inference)
    → consumes: aligned face crops (112x112) from FaceDetection landmarks
    → produces: FaceEmbedding (512-D, normalized)
    → config: model_path, similarity_threshold
    → loads: enrollment DB (embeddings.npy + metadata.json)
    
Tracker (tracking)
    → consumes: PersonDetection, FaceDetection, FaceEmbedding
    → produces: TrackingResult (List[Track] with identity)
    → association: IoU + center dist + face center bonus
    → identity: ArcFaceRecognizer.identify() for face embeddings
    → config: min_iou, max_age, max_lost_frames
    
AttendanceEngine (attendance)
    → consumes: TrackingResult
    → produces: CrossingEvent (IN/OUT)
    → stores: SQLite (attendance_events.db)
    → geometry: LineGeometry from camera config
    → policy: debounce, min_distance, side_confirmation
    
GPUAnnotator (annotation)
    → consumes: GPUFrame, Tracks
    → produces: Annotated GPUFrame (NV12, annotation tensor set)
    → GPU ops: NV12→BGR, draw boxes/labels/line, BGR→NV12
    → config: show elements, colors, thickness
    
NVENCEncoder (encode)
    → consumes: Annotated GPUFrame
    → produces: H.264 packets (av.Packet)
    → zero-copy: GPUFrame DLPack → PyAV CUDA VideoFrame → NVENC
    → config: codec, bitrate, gop, preset, tune, gpu_device
    → output: RTSP URL (MediaMTX)
    
MediaMTXPublisher (output)
    → consumes: H.264 packets from encoder
    → publishes: RTSP to MediaMTX (live/camX-ai)
    → fallback: FFmpeg subprocess for stream copy
```

## Configuration Dependencies

### Pipeline Config → Module Config Mapping

| Pipeline Config Section | Consuming Modules |
|------------------------|-------------------|
| `runtime` | `core/engine.py` (EngineState, timeouts) |
| `gpu` | `core/engine.py`, `memory/memory_monitor.py`, all CUDA modules |
| `cameras` | `ingestion/camera_manager.py` (per-camera everything) |
| `decode` | `decode/nvdec_decoder.py` |
| `inference` | `inference/*.py` (batch_size, providers, warmup) |
| `models` | `inference/*.py` (model paths, thresholds) |
| `tracking` | `tracking/tracker.py` |
| `attendance` | `attendance/attendance_engine.py` |
| `annotation` | `annotation/overlay.py` |
| `encode` | `encode/nvenc_encoder.py` |
| `output` | `output/publisher.py` |
| `backend` | `backend/app.py` |
| `frontend` | `backend/app.py` (static mounts) |
| `monitoring` | `monitoring/__init__.py`, `memory/memory_monitor.py` |
| `integration` | `integration/__init__.py` |

### Per-Camera Config Keys Used

| Config Key | Used By |
|------------|---------|
| `input.url`, `input.transport`, `input.timeout_seconds` | `RTSPSource` |
| `output.path`, `output.protocol` | `NVENCEncoder`, `MediaMTXPublisher` |
| `expected.width`, `expected.height`, `expected.fps` | `NVDECDecoder`, `NVENCEncoder`, `GPUAnnotator` |
| `decode.backend`, `decode.gpu_device`, `decode.surfaces` | `NVDECDecoder`, `FramePool` |
| `encode.codec`, `encode.bitrate_kbps`, `encode.gop_size`, `encode.preset`, `encode.tune`, `encode.rc` | `NVENCEncoder` |
| `reconnect.*` | `RTSPSource`, `NVDECDecoder`, `NVENCEncoder` |
| `health.*` | `RTSPSource`, `CameraManager` |
| `readiness.*` | `RTSPSource` |
| `geometry.line_start`, `geometry.line_end`, `geometry.direction_semantics` | `AttendanceEngine`, `GPUAnnotator` |
| `crossing_policy.*` | `AttendanceEngine` |

## Caller/Consumer Relationships

| Producer | Consumer | Data Type |
|----------|----------|-----------|
| `RTSPSource` | `NVDECDecoder` | `av.Packet` |
| `NVDECDecoder` | `SCRFDDetector`, `YOLOPersonDetector`, `GPUAnnotator`, `NVENCEncoder` | `GPUFrame` |
| `SCRFDDetector` | `Tracker` | `List[FaceDetection]` |
| `YOLOPersonDetector` | `Tracker` | `List[PersonDetection]` |
| `ArcFaceRecognizer` | `Tracker` | `Dict[detection_id, FaceEmbedding]` |
| `Tracker` | `AttendanceEngine`, `GPUAnnotator` | `TrackingResult` |
| `AttendanceEngine` | `backend/app.py` (via callbacks) | `CrossingEvent` |
| `GPUAnnotator` | `NVENCEncoder` | `GPUFrame` (annotated) |
| `NVENCEncoder` | `MediaMTXPublisher` | `av.Packet` (H.264) |
| `CameraManager` | `PipelineEngine` | `CameraMetrics`, health status |
| `GPUMemoryMonitor` | `PipelineEngine` (callbacks) | `MemorySnapshot` |

## Circular Dependencies

None detected. The dependency graph is a DAG (Directed Acyclic Graph) flowing from:
`config → core → ingestion → decode → inference → tracking → attendance/annotation → encode → output`

With `memory` and `monitoring` as cross-cutting concerns used by multiple layers.

## Configuration Singleton Pattern

All modules access configuration via:
```python
from pipeline_engine.config import get_config, get_camera_config, get_model_config

config = get_config()  # Global singleton, loads pipeline.yaml on first call
cam_config = get_camera_config(config, camera_id)
model_config = get_model_config(config, model_name)
```

This creates implicit coupling - modules cannot be easily tested with different configs without monkeypatching the global `_config` variable.

## Shared State

| State | Location | Access Pattern |
|-------|----------|----------------|
| Global config | `config/__init__.py:_config` | `get_config()` singleton |
| Global engine | `core/engine.py:_engine` | `get_engine()` singleton |
| Global camera manager | `ingestion/camera_manager.py:_camera_manager` | `get_camera_manager()` singleton |
| Frame pools | `memory/frame_pool.py:FramePoolManager` | Per-camera, via manager |
| CUDA context | `memory/gpu_frame.py:CUDAContext.current()` | Per-thread, per-device |
| Enrollment DB | `inference/face_recognition.py:ArcFaceRecognizer._enrollment_*` | Loaded once per camera in CameraManager |

## Critical Path Dependencies

1. **CameraManager.initialize()** must complete before **CameraManager.start_camera()**
2. **RTSPSource.start()** must pass readiness gate before **NVDECDecoder.start()**
3. **NVDECDecoder** must produce frames before **inference models** can run
4. **Tracker** requires both person and face detections + embeddings
5. **AttendanceEngine** requires Track with person_id for identified events
6. **GPUAnnotator** runs after tracking, before encoding
7. **NVENCEncoder** must start before **MediaMTXPublisher** can accept packets
8. **MediaMTX** must be running before **MediaMTXPublisher.connect()** succeeds

## Initialization Order (from PipelineEngine.initialize())

1. `GPUMemoryMonitor.start()` 
2. `CameraManager.initialize()` → creates all per-camera components (models, tracker, attendance, annotator)
3. `CameraManager.start_all()` → for each camera:
   - `RTSPSource.start()` 
   - Wait readiness gate
   - `NVDECDecoder.start()`
   - AI models `.initialize()`
   - `NVENCEncoder.start()`
   - `MediaMTXPublisher.start()`
   - Start pipeline thread

## Shutdown Order (from PipelineEngine.stop())

1. `CameraManager.stop_all()` → for each camera:
   - `MediaMTXPublisher.stop()`
   - `NVENCEncoder.stop()`
   - `NVDECDecoder.stop()`
   - AI models `.cleanup()`
   - `RTSPSource.stop()`
   - Join pipeline thread
2. `FramePoolManager.shutdown()`
3. `GPUMemoryMonitor.stop()`