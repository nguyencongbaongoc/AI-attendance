# AI Inference and Tracking Audit

## SCRFD Face Detector (`inference/face_detection.py`)

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

### Architecture
- ONNX Runtime with CUDA Execution Provider
- IO Binding for zero-copy GPU inference
- SCRFD 10G model (10M params, BN + KPS)
- Input: 640×640, Output: scores, bboxes, keypoints per stride (8, 16, 32)

### Configuration
```python
SCRFDConfig:
    confidence_threshold: 0.5
    nms_threshold: 0.4
    input_size: (640, 640)
    strides: (8, 16, 32)
    anchor_scales:
        8: [16, 32]
        16: [64, 128]
        32: [256, 512]
```

### Preprocessing Pipeline (GPU)
```python
GPUFrame (NV12, 3840×2160)
    → nv12_to_bgr_cuda() → BGR (H, W, 3) uint8
    → permute(2,0,1).unsqueeze(0).float() / 255.0 → (1, 3, H, W) float32
    → letterbox_resize_cuda(640, 640) → (1, 3, 640, 640) + padding_info
    → (x - mean) / std → normalized tensor
```

### Inference
```python
# IO Binding setup (once at init)
io_binding.bind_input(name, 'cuda', device_id, np.float32, shape, buffer_ptr)
for output in outputs:
    io_binding.bind_output(name, 'cuda', device_id, np.float32, shape, buffer_ptr)

# Run
session.run_with_iobinding(io_binding)
torch.cuda.synchronize()
```

### Post-processing
1. **Output parsing**: Multi-stride outputs (score_8, bbox_8, kps_8, etc.)
2. **Anchor decoding**: Center + scale → bbox
3. **Coordinate mapping**: Model space (640×640 + padding) → Original frame (3840×2160)
4. **NMS**: GPU tensor operations, IoU threshold 0.4
5. **Output**: `List[FaceDetection]` with bbox, confidence, landmarks5 in original coordinates

### Model File
- Path: `models/scrfd/scrfd_10g_bnkps.onnx` (~5.6 MB)
- Expected in config: `models.scrfd.path`

### Performance
- **Inference time**: ~5-10ms @ 640×640 on GTX 1660 Ti
- **Preprocessing**: ~2-3ms (NV12→BGR + letterbox + normalize)
- **Total per frame**: ~8-15ms

### Evidence
- File: `pipeline_engine/inference/face_detection.py` (585 lines)
- Test: `__main__` block loads model, runs initialize()
- Runtime: BLOCKED - needs CUDA + model file

---

## ArcFace Face Recognizer (`inference/face_recognition.py`)

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

### Architecture
- ONNX Runtime CUDA EP with IO Binding
- GlintR100 (ResNet100) → 512-D normalized embeddings
- Cosine similarity search against enrollment database

### Configuration
```python
ArcFaceConfig:
    similarity_threshold: 0.6
    # Input: 112×112 aligned face crop
    # Normalization: mean=127.5, std=128.0
```

### Enrollment Database
```python
load_enrollment_database(
    embeddings_path: "data/embeddings.npy",      # (N, 512) float32
    metadata_path: "data/embeddings.npy.metadata.json"  # List[dict]
)

# Metadata format:
[
    {"id": "person_001", "name": "John Doe", "camera": "cam1", ...},
    ...
]
```

### Inference
```python
# Input: 112×112 BGR tensor (aligned face)
# Preprocess: (x - 127.5) / 128.0
# IO Binding inference
# Output: 512-D embedding (already L2-normalized by model)
# Returns: FaceEmbedding(embedding, raw_embedding, raw_norm, inference_time_ms, ...)
```

### Identification
```python
identify(embedding, top_k=1) → List[(person_id, similarity)]
# Cosine similarity: embedding @ enrolled_embeddings.T
# Filter by similarity_threshold (0.6)
```

### Face Alignment (Missing)
- **Current**: `_extract_aligned_face()` in CameraManager does simple bbox crop + resize
- **Required**: 5-point landmark alignment (similarity transform to 112×112 reference)
- **Gap**: Landmarks from SCRFD not used for alignment

### Performance
- **Inference time**: ~2-5ms @ 112×112
- **Identification**: <1ms (matrix multiply N×512 @ 512)
- **Database load**: ~100ms for 1000 faces

### Evidence
- File: `pipeline_engine/inference/face_recognition.py` (~500 lines)
- Model: `models/arcface/glintr100.onnx` (~220 MB)
- Database: `data/embeddings.npy` + `.metadata.json`
- Runtime: BLOCKED - needs CUDA + model + database

---

## YOLO Person Detector (`inference/person_detection.py`)

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

### Architecture
- ONNX Runtime CUDA EP
- YOLO11n (nano) - person class only (class_id=0)
- Input: 640×640, Output: bboxes, scores

### Configuration
```python
YOLOConfig:
    confidence_threshold: 0.5
    nms_threshold: 0.45
    max_detections: 100
    person_class_id: 0
```

### Preprocessing (Shared)
- Same letterbox pipeline as SCRFD
- GPU: NV12→BGR→letterbox→normalize

### Output
```python
@dataclass
class PersonDetection:
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 (original coords)
    confidence: float
    detection_id: str
    frame_index: int
    source_id: str
    coordinate_space: str = "original_frame"
```

### Performance
- **Inference time**: ~5-10ms @ 640×640
- **Detections/frame**: Typically 0-10 persons

### Evidence
- File: `pipeline_engine/inference/person_detection.py` (~400 lines)
- Model: `models/yolo/yolo11n.onnx` (~5 MB)
- Runtime: BLOCKED - needs CUDA + model

---

## ReID (`inference/reid.py`)

**Status: DISABLED IN CONFIG**

### Configuration
```yaml
models:
  reid:
    path: "models/reid/resnet50_reid.onnx"
    enabled: false  # ← DISABLED
```

### Implementation
- ResNet50 ReID → 2048-D embeddings
- Code exists but not instantiated in CameraManager
- Would be used for tracking fallback when face recognition fails

---

## Tracker (`tracking/tracker.py`)

**Status: IMPLEMENTED, PARTIALLY VERIFIED (runtime)**

### Architecture
- Geometry-based tracking (IoU + center distance + area ratio)
- Face association bonus for identity fusion
- Greedy assignment (deterministic by track_id)
- Face recognition identity resolution integrated
- ReID fallback (disabled)

### Track State Machine
```
NEW → ACTIVE → LOST → CLOSED
     ↑    ↓
     └────┘ (re-detection)
```

### Configuration
```python
TrackingConfig:
    min_iou_threshold: 0.3
    max_age: 30
    max_lost_frames: 10
    max_active_tracks: 50
    max_lost_tracks: 30
    max_new_tracks: 10
    use_face_association: true
    face_center_weight: 0.5
    reid_fallback_enabled: false
    reid_similarity_threshold: 0.7
    identity_confidence_threshold: 0.5
```

### Association Score
```python
score = 0.35 * IoU + 0.20 * center_dist + 0.15 * area_ratio + 0.30 * face_bonus
# face_bonus = 0.5 if face center in both track and detection bbox
```

### Identity Resolution
```python
# For each matched track with face embedding:
matches = recognizer.identify(face_embedding, top_k=1)
if matches and similarity >= 0.5:
    track.person_id = person_id
    track.person_name = metadata.name
    track.identity_confidence = similarity
    track.identity_source = "face_recognition"
    track.embedding = face_embedding.cpu().numpy()
```

### Track Management
- **Active tracks**: `hits++`, `missed_frames=0`, `age++`
- **Unmatched tracks**: `missed_frames++`, LOST if >= max_lost_frames
- **New tracks**: Created for unmatched detections, immediate face ID attempt
- **Memory bounds**: Enforces max_active, max_lost, max_new

### Output
```python
@dataclass
class TrackingResult:
    source_frame_id: str
    frame_index: int
    timestamp: float
    tracks: List[Track]
    new_tracks: List[Track]
    closed_tracks: List[Track]
    
    def get_active_tracks() → List[Track]
    def get_identified_tracks() → List[Track]
```

### Evidence
- File: `pipeline_engine/tracking/tracker.py` (685 lines)
- Test: `__main__` creates mock detections, runs process_frame()
- Runtime: BLOCKED - needs full pipeline

---

## Inference Integration in Camera Pipeline

### Initialization (per camera)
```python
# CameraManager._initialize_camera():
scrfd = SCRFDDetector(model_path="models/scrfd/scrfd_10g_bnkps.onnx", ...)
arcface = ArcFaceRecognizer(model_path="models/arcface/glintr100.onnx", ...)
yolo = YOLOPersonDetector(model_path="models/yolo/yolo11n.onnx", ...)

arcface.load_enrollment_database("data/embeddings.npy", "data/embeddings.npy.metadata.json")

tracker = Tracker(config, recognizer=arcface)
```

### Per-Frame Processing
```python
# _camera_pipeline_loop():

# 1. Face detection
face_detections = scrfd.detect(gpu_frame)

# 2. Person detection  
person_detections = yolo.detect(gpu_frame)

# 3. Face recognition (for each face)
face_embeddings = {}
for face_det in face_detections:
    aligned_face = _extract_aligned_face(gpu_frame, face_det)  # Simple crop+resize
    if aligned_face is not None:
        embedding = arcface.infer_embedding(aligned_face)
        face_embeddings[face_det.detection_id] = embedding

# 4. Tracking
tracking_result = tracker.process_frame(
    person_detections=person_detections,
    face_detections=face_detections,
    face_embeddings=face_embeddings,
    camera_id=camera_id,
    timestamp=gpu_frame.timestamp,
)
```

### Issues

1. **Duplicate model instances**: Each camera creates own SCRFD, ArcFace, YOLO instances (~500MB VRAM each)
2. **No shared inference**: Could share models across cameras (same GPU)
3. **Face alignment**: `_extract_aligned_face()` uses simple crop, not landmark alignment
4. **Batch inference**: Processes one frame at a time (batch_size=1)
4. **No inference queuing**: Blocking calls in pipeline loop

---

## AI Pipeline Latency Breakdown

| Stage | Estimated Time (GTX 1660 Ti) | Notes |
|-------|------------------------------|-------|
| NV12→BGR (SCRFD) | 1.5ms | 3840×2160 → BGR |
| Letterbox 640×640 | 0.5ms | Interpolate |
| Normalize | 0.2ms | Tensor ops |
| SCRFD inference | 8ms | IO Binding |
| SCRFD post-process | 1ms | NMS, coordinate mapping |
| NV12→BGR (YOLO) | 1.5ms | Reuses or recomputes |
| Letterbox 640×640 | 0.5ms | |
| Normalize | 0.2ms | |
| YOLO inference | 8ms | IO Binding |
| YOLO post-process | 1ms | NMS |
| Face crops + ArcFace | 3ms/face | 112×112 per face |
| ArcFace identify | 0.5ms | Matrix multiply |
| Tracking | 1ms | Geometry + assignment |
| **Total AI** | **~25-40ms** | Per frame, 1-3 faces |

**Target**: <33ms for 30 FPS
**Risk**: May exceed at 4K with multiple faces

---

## Model File Verification

| Model | Path | Size | Exists | Format |
|-------|------|------|--------|--------|
| SCRFD 10G | `models/scrfd/scrfd_10g_bnkps.onnx` | 5.6 MB | ✅ | ONNX |
| ArcFace | `models/arcface/glintr100.onnx` | 220 MB | ✅ | ONNX |
| YOLO11n | `models/yolo/yolo11n.onnx` | 5 MB | ✅ | ONNX |
| YOLO11n-pose | `models/yolo/yolo11n-pose.pt` | 5 MB | ✅ | PyTorch |
| ReID | `models/reid/resnet50_reid.onnx` | 100 MB | ✅ | ONNX |
| Landmarks | `models/landmark/1k3d68.onnx` | 50 MB | ✅ | ONNX |

---

## Tracking Quality Metrics (Untested)

| Metric | Target | Measurement |
|--------|--------|-------------|
| MOTA | > 0.7 | Not measured |
| IDF1 | > 0.6 | Not measured |
| ID Switches | < 5/min | Not measured |
| False Positives | < 10% | Not measured |
| False Negatives | < 10% | Not measured |
| Face ID Accuracy | > 95% @ 0.6 thresh | Not measured |

---

## Runtime Verification Status

| Component | Implemented | Unit Test | Integration Test | Runtime Verified |
|-----------|-------------|-----------|------------------|------------------|
| SCRFD | ✅ | ❌ | ❌ | BLOCKED |
| ArcFace | ✅ | ❌ | ❌ | BLOCKED |
| YOLO | ✅ | ❌ | ❌ | BLOCKED |
| ReID | ✅ (disabled) | ❌ | ❌ | N/A |
| Tracker | ✅ | ❌ (mock only) | ❌ | BLOCKED |
| Full AI Pipeline | ✅ | ❌ | ❌ | BLOCKED |

---

## Architecture A Evaluation: AI Path

### Current AI Path
```
Camera RTSP → PyAV → Decode → GPUFrame 
    → SCRFD + YOLO (parallel-ish) → Face Embeddings
    → Tracker → Attendance → Annotator → NVENC → MediaMTX
```

### Proposed Architecture A AI Path
```
Camera RTSP → PyAV (separate process) → Decode → GPUFrame
    → SCRFD + YOLO (batched?) → Face Embeddings
    → Tracker → Attendance → Backend API → UI Metadata
```

### Changes Needed for Architecture A
1. **Separate decode process**: PyAV reader in separate process/thread
2. **Batch inference**: Accumulate frames, run batched inference
3. **Shared models**: Single model instance per GPU, multiple cameras
4. **Async inference**: Decouple decode from inference with queue
5. **Metadata only output**: No annotation → no NVENC needed for AI path
6. **Backend integration**: Attendance events → REST/WebSocket → UI

### Reusable Components
| Component | Reuse? | Changes |
|-----------|--------|---------|
| SCRFDDetector | ✅ KEEP | Make thread-safe, support batch |
| ArcFaceRecognizer | ✅ KEEP | Share instance, add batch identify |
| YOLOPersonDetector | ✅ KEEP | Make thread-safe, support batch |
| Tracker | ✅ ADAPT | Stateless per-frame, shared instance |
| AttendanceEngine | ✅ KEEP | Connect to backend instead of SQLite |
| GPUFrame | ✅ KEEP | Core contract unchanged |
| FramePool | ✅ ADAPT | Shared across cameras |

### Components to Replace/Remove
| Component | Action | Reason |
|-----------|--------|--------|
| GPUAnnotator | REMOVE | Architecture A: no GPU annotation |
| NVENCEncoder | REMOVE | Architecture A: no re-encode for AI path |
| MediaMTXPublisher | REMOVE | Architecture A: AI path doesn't publish video |
| CameraManager | REPLACE | New architecture: separate ingestion process |
| PipelineEngine | REPLACE | New orchestrator for AI-only pipeline |

---

## Critical Gaps

1. **No face alignment**: Landmarks detected but not used for ArcFace alignment
2. **No batch inference**: Single-frame processing limits throughput
3. **Per-camera model duplication**: 3× VRAM for 2 cameras
4. **No inference queue**: Blocking inference in pipeline loop
5. **No model warmup verification**: `warmup_enabled: true` but not validated
6. **Tracking not validated**: No MOT benchmarks run
7. **Face ID threshold tuning**: 0.6 default, not validated on dataset