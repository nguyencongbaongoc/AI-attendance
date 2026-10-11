# Actual Data Flow and Call Graph

## End-to-End Data Flow (Camera → Output)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE PIPELINE DATA FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────────────┘

CAMERA RTSP                          GPU MEMORY                         MEDIAMTX
   │                                      │                                 │
   ▼                                      │                                 │
┌─────────┐                              │                                 │
│RTSP     │                              │                                 │
│Source   │────av.Packet (H.264)────────►│                                 │
│(PyAV)   │                              │                                 │
└────┬────┘                              │                                 │
     │                                   │                                 │
     │         ┌─────────────────────────┼────────────────────────────────┐│
     │         │      DECODER            │                                ││
     │         │    (NVDECDecoder)       │                                ││
     │         │                         │                                ││
     │         │  FramePool.acquire()    │                                ││
     │         │       │                 │                                ││
     │         │       ▼                 │                                ││
     │         │  ┌──────────┐           │                                ││
     │         │  │ GPUFrame │           │                                ││
     │         │  │ (NV12)   │           │                                ││
     │         │  │ y_tensor │           │                                ││
     │         │  │ uv_tensor│           │                                ││
     │         │  │ ref=1    │           │                                ││
     │         │  └────┬─────┘           │                                ││
     │         │       │                 │                                ││
     │         │       ▼                 │                                ││
     │         │  decoder.get_frame()    │                                ││
     │         │       │                 │                                ││
     │         │       ▼                 │                                ││
     │         │  ┌──────────┐           │                                ││
     │         │  │ GPUFrame │           │                                ││
     │         │  │ status=  │           │                                ││
     │         │  │ DECODED  │           │                                ││
     │         │  │ owner=   │           │                                ││
     │         │  │ DECODER  │           │                                ││
     │         │  └────┬─────┘           │                                ││
     │         │       │                 │                                ││
     │         └───────┼─────────────────┼────────────────────────────────┘│
     │                 │                 │                                 │
     ▼                 ▼                 ▼                                 ▼
┌─────────┐    ┌─────────────┐    ┌─────────────┐                     ┌─────────┐
│SCRFD    │    │YOLO Person  │    │  (other     │                     │         │
│Detector │    │Detector     │    │   models)   │                     │         │
│(ONNX)   │    │(ONNX)       │    │             │                     │         │
└────┬────┘    └──────┬──────┘    └─────────────┘                     │         │
     │                │                                             │         │
     ▼                ▼                                             │         │
┌─────────────────────────────┐                                    │         │
│FaceDetection[]              │                                    │         │
│PersonDetection[]            │                                    │         │
└──────────────┬──────────────┘                                    │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌───────────────┐                                           │         │
       │ArcFace        │                                           │         │
       │Recognizer     │                                           │         │
       │(ONNX)         │                                           │         │
       │               │                                           │         │
       │FaceEmbedding  │                                           │         │
       └───────┬───────┘                                           │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │Tracker          │                                         │         │
       │                 │                                         │         │
       │update_tracks()  │                                         │         │
       │                 │                                         │         │
       │Track[]          │                                         │         │
       └───────┬─────────┘                                         │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │AttendanceEngine │                                         │         │
       │                 │                                         │         │
       │process_tracks() │                                         │         │
       │                 │                                         │         │
       │CrossingEvent[]  │                                         │         │
       │  (SQLite store) │                                         │         │
       └───────┬─────────┘                                         │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │GPUAnnotator     │                                         │         │
       │                 │                                         │         │
       │annotate()       │                                         │         │
       │                 │                                         │         │
       │GPUFrame         │                                         │         │
       │(annotated NV12) │                                         │         │
       └───────┬─────────┘                                         │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │NVENCEncoder     │                                         │         │
       │                 │                                         │         │
       │submit_frame()   │                                         │         │
       │                 │                                         │         │
       │H.264 packets    │                                         │         │
       └───────┬─────────┘                                         │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │MediaMTXPublisher│                                         │         │
       │                 │                                         │         │
       │submit_av_packet()                                       │         │
       │                 │                                         │         │
       └───────┬─────────┘                                         │         │
               │                                                   │         │
               ▼                                                   │         │
       ┌─────────────────┐                                         │         │
       │MediaMTX Server  │◄────────────────────────────────────────┘         │
       │(External proc)  │                                                │
       │                 │                                                │
       │RTSP: live/      │                                                │
       │cam1-ai, cam2-ai │                                                │
       │HLS: /hls/...    │                                                │
       │WebRTC: :8889    │                                                │
       └─────────────────┘                                                │
```

## Actual Call Graph (from PipelineEngine.run_forever)

```
PipelineEngine.run_forever()
├── install_signal_handlers()
├── load_config() → config.load_pipeline_config()
├── initialize()
│   ├── GPUMemoryMonitor.start() → _monitor_loop()
│   ├── CameraManager.initialize()
│   │   ├── FramePoolManager.from_config() → creates FramePool per camera
│   │   └── _initialize_camera() for each camera
│   │       ├── RTSPSource(config)
│   │       ├── FramePoolConfig
│   │       ├── SCRFDDetector(model_path, config, device_id)
│   │       ├── ArcFaceRecognizer(model_path, config, device_id)
│   │       │   └── load_enrollment_database(npy, metadata_json)
│   │       ├── YOLOPersonDetector(model_path, config, device_id)
│   │       ├── Tracker(config, recognizer=ArcFaceRecognizer)
│   │       ├── AttendanceEngine.create_attendance_engine()
│   │       ├── GPUAnnotator(config, device_id)
│   │       └── Stores in _cameras[camera_id] dict
│   ├── _validate_cameras() → cv2.VideoCapture connectivity test
│   └── _set_state(VALIDATING)
├── start()
│   ├── CameraManager.start_all()
│   │   └── start_camera(camera_id) for each
│   │       ├── rtsp_source.start() → _open_container(), _read_loop thread
│   │       ├── Wait readiness gate (RTSPSource.metrics.readiness_passed)
│   │       ├── NVDECDecoder(decoder_config, frame_pool).start()
│   │       │   ├── _open_container() → av.open() with software decode
│   │       │   ├── Pre-allocate GPU tensors (_y_gpu, _uv_gpu)
│   │       │   └── _reader_loop thread → _container.decode()
│   │       ├── AI models initialize: scrfd.initialize(), arcface.initialize(), yolo.initialize()
│   │       ├── NVENCEncoder(encoder_config, frame_pool).start()
│   │       │   ├── _init_pyav_encoder() → av.open() RTSP output, add_stream h264_nvenc
│   │       │   └── _encode_loop thread
│   │       ├── MediaMTXPublisher.create_publisher().start()
│   │       │   ├── _detect_media_server() (TCP connect to :8554)
│   │       │   ├── _connect() → av.open() RTSP output
│   │       │   └── _publish_loop thread
│   │       └── Start _camera_pipeline_loop thread
│   ├── _supervisor_thread.start() → _supervisor_loop()
│   └── _set_state(RUNNING)
└── Main loop: print status_summary() every 1s until KeyboardInterrupt
```

## Camera Pipeline Loop (per camera thread)

```
_camera_pipeline_loop(camera_id)
├── while running and camera_state == RUNNING:
│   ├── rtsp_source.get_packet(timeout=1.0) → av.Packet
│   │   └── If None: check health (stale/degraded), continue
│   │
│   ├── frame_pool.acquire(frame_id, timestamp, pts) → GPUFrame
│   │   └── If pool exhausted: frames_dropped++, continue
│   │
│   ├── Set frame metadata (camera_id, frame_id, timestamp, pts, dts, time_base)
│   │
│   ├── STAGE 1: DECODE
│   │   ├── decoder.get_frame(timeout=1.0) → GPUFrame
│   │   │   └── If None: decode_errors++, return frame to pool, continue
│   │   ├── gpu_frame.transfer_ownership(DECODER)
│   │   ├── gpu_frame.set_status(DECODED)
│   │   ├── gpu_frame.decode_time_ms = elapsed
│   │   └── frames_decoded++
│   │
│   ├── STAGE 2: AI INFERENCE
│   │   ├── scrfd.detect(gpu_frame) → List[FaceDetection]
│   │   │   ├── preprocess(): NV12→BGR→letterbox→normalize (GPU)
│   │   │   ├── infer() with IO Binding (GPU)
│   │   │   ├── _parse_outputs() → bbox, landmarks in original coords
│   │   │   └── _apply_nms()
│   │   ├── yolo.detect(gpu_frame) → List[PersonDetection]
│   │   │   ├── preprocess() similar
│   │   │   ├── infer() with IO Binding
│   │   │   └── parse + NMS
│   │   ├── For each FaceDetection:
│   │   │   ├── _extract_aligned_face() → 112x112 BGR tensor (GPU)
│   │   │   ├── arcface.infer_embedding(aligned_face) → FaceEmbedding
│   │   │   └── Store in face_embeddings dict
│   │   ├── gpu_frame.transfer_ownership(INFERENCE)
│   │   ├── gpu_frame.set_status(INFERRING)
│   │   └── inference_count += detections
│   │
│   ├── STAGE 3: TRACKING
│   │   ├── tracker.process_frame(person_detections, face_detections, face_embeddings, camera_id, timestamp)
│   │   │   ├── update_tracks(previous_tracks, person_detections, face_detections, face_embeddings, recognizer, ...)
│   │   │   │   ├── solve_track_assignment() → greedy IoU + face bonus
│   │   │   │   ├── find_face_for_person() → spatial association
│   │   │   │   ├── Identity resolution: recognizer.identify(embedding)
│   │   │   │   ├── Update matched tracks (age++, hits++, missed=0)
│   │   │   │   ├── Age unmatched tracks (missed_frames++)
│   │   │   │   ├── Create new tracks for unmatched detections
│   │   │   │   └── Enforce memory bounds (max_active, max_lost)
│   │   │   └── Returns TrackingResult(tracks, new_tracks, closed_tracks)
│   │   ├── gpu_frame.transfer_ownership(TRACKING)
│   │   ├── gpu_frame.set_status(TRACKING)
│   │   └── tracks_active = len(active_tracks)
│   │
│   ├── STAGE 4: ATTENDANCE
│   │   ├── attendance.process_tracks(tracking_result) → List[CrossingEvent]
│   │   │   ├── For each active track:
│   │   │   │   ├── engine.process_track_update(track, timestamp, frame_index)
│   │   │   │   │   ├── LineGeometry.side_of_point(current_center)
│   │   │   │   │   ├── Check crossing: prev_side != current_side
│   │   │   │   │   ├── Debounce: temporal_debounce_seconds
│   │   │   │   │   ├── Distance check: min_crossing_distance
│   │   │   │   │   ├── Determine direction (IN/OUT)
│   │   │   │   │   ├── Calculate intersection point
│   │   │   │   │   ├── Create CrossingEvent with track_id, person_id, direction
│   │   │   │   │   ├── Store in AttendanceStore (SQLite)
│   │   │   │   │   └── Trigger event callbacks
│   │   │   │   └── Returns events for this track
│   │   │   └── Returns all events
│   │   ├── attendance_events += len(events)
│   │
│   ├── STAGE 5: ANNOTATION
│   │   ├── annotator.annotate(frame, tracks, camera_id, frame_metrics)
│   │   │   ├── nv12_to_bgr_cuda() → BGR tensor
│   │   │   ├── Draw person boxes, face boxes, labels, crossing line, diagnostics
│   │   │   ├── bgr_to_nv12_cuda() → NV12 tensors
│   │   │   ├── frame.y_tensor.copy_(y_annotated)
│   │   │   ├── frame.uv_tensor.copy_(uv_annotated)
│   │   │   ├── frame.set_annotation_tensor(bgr)
│   │   │   └── Returns annotated frame
│   │   ├── annotated_frame.transfer_ownership(ANNOTATION)
│   │   ├── annotated_frame.set_status(ANNOTATING)
│   │
│   ├── STAGE 6: ENCODE
│   │   ├── encoder.submit_frame(annotated_frame) → bool
│   │   │   ├── gpu_frame.add_ref()
│   │   │   ├── _frame_queue.put_nowait(gpu_frame)
│   │   │   └── If full: drop oldest, insert newest
│   │   ├── _encode_loop (separate thread):
│   │   │   ├── _frame_queue.get() → GPUFrame
│   │   │   ├── GPUFrame → DLPack capsules → av.VideoFrame.from_dlpack()
│   │   │   │   └── If format='cuda': reformat to 'nv12'
│   │   │   ├── stream.encode(av_frame) → packets
│   │   │   ├── container.mux(packet) for each
│   │   │   ├── frames_encoded++
│   │   │   ├── gpu_frame.release() → return to pool
│   │   │   └── Handle OSError -129: _attempt_restart()
│   │   └── If submit failed: frames_dropped++, return to pool
│   │
│   ├── STAGE 7: PUBLISH (async via encoder mux)
│   │   └── MediaMTXPublisher receives packets via container.mux()
│   │
│   ├── TELEMETRY
│   │   ├── Update FPS calculations
│   │   ├── Update latency breakdown
│   │   ├── Update decoder/encoder state
│   │   ├── Update GPU memory from torch.cuda
│   │   └── Periodic metrics update (every 5s)
│   │
│   └── Small sleep to prevent CPU spinning (target ~50 FPS max)
│
├── Exception handling: set camera_state = ERROR, log traceback
└── Finally: log pipeline loop ended
```

## Data Types at Each Stage

| Stage | Input | Output | Memory Location | Ownership |
|-------|-------|--------|-----------------|-----------|
| RTSP Source | RTSP URL | `av.Packet` (H.264 NAL) | CPU (PyAV) | Source |
| Decoder | `av.Packet` | `GPUFrame` (NV12, y+uv CUDA tensors) | GPU VRAM | DECODER |
| SCRFD | `GPUFrame` | `List[FaceDetection]` (original coords) | CPU (dataclass) | INFERENCE |
| YOLO | `GPUFrame` | `List[PersonDetection]` (original coords) | CPU (dataclass) | INFERENCE |
| ArcFace | 112x112 BGR tensor | `FaceEmbedding` (512-D tensor) | GPU → CPU numpy | INFERENCE |
| Tracker | PersonDet[], FaceDet[], Embeddings | `TrackingResult` (Track[]) | CPU (dataclass) | TRACKING |
| Attendance | `TrackingResult` | `CrossingEvent[]` (stored in SQLite) | CPU (dataclass + DB) | - |
| Annotator | `GPUFrame` + Tracks | Annotated `GPUFrame` (NV12) | GPU VRAM | ANNOTATION |
| Encoder | Annotated `GPUFrame` | `av.Packet` (H.264) | GPU → CPU (packet) | ENCODER |
| Publisher | `av.Packet` | RTSP stream to MediaMTX | Network | - |

## Frame Ownership & Lifetime

```
GPUFrame created by FramePool.acquire() [ref_count=1, owner=DECODER]
    │
    ▼
Decoder fills tensors, sets status=DECODED
    │
    ▼
Inference reads tensors (NV12→BGR conversion creates temp BGR tensor)
    │   Sets owner=INFERENCE, status=INFERRING
    │
    ▼
Tracker reads detections (no frame modification)
    │   Sets owner=TRACKING, status=TRACKING
    │
    ▼
Attendance reads tracks (no frame modification)
    │
    ▼
Annotator: NV12→BGR (GPU), draws, BGR→NV12 (GPU), copies back to frame tensors
    │   Sets owner=ANNOTATION, status=ANNOTATING
    │   Sets _annotation_tensor (BGR) for encoder
    │
    ▼
Encoder.submit_frame(): frame.add_ref() [ref_count=2]
    │   Encoder thread: from_dlpack(), encode, mux
    │   After encode: frame.release() [ref_count=1]
    │   FramePool.return_to_pool() → available for reuse
    │
    ▼
FramePool: frame.status=COMPLETED, available for next acquire()
```

## Synchronization Points

| Location | Mechanism | Purpose |
|----------|-----------|---------|
| `RTSPSource._packet_queue` | `queue.Queue(maxsize=32)` | Buffer packets between read_loop and decoder |
| `NVDECDecoder._frame_queue` | `queue.Queue(maxsize=8)` | Buffer decoded frames between reader_loop and pipeline |
| `NVENCEncoder._frame_queue` | `queue.Queue(maxsize=4)` | Buffer frames between pipeline and encode_loop |
| `MediaMTXPublisher._packet_queue` | `queue.Queue(maxsize=50)` | Buffer packets between encoder and publish_loop |
| `GPUFrame.ref_count` | Atomic int (thread-safe via GIL) | Reference counting for zero-copy lifetime |
| `CUDA streams` | Per-camera stream (config: `cuda_stream_per_camera: true`) | Overlap decode/inference/encode |
| `torch.cuda.synchronize()` | Explicit sync after DLPack conversions | Ensure GPU ops complete before next stage |

## Error Handling Flow

```
RTSPSource read_loop error
    │
    ├── av.error.FFmpegError → _handle_read_loop_exit()
    │   └── If reconnect_enabled & retries < max: _schedule_reconnect()
    │       └── Delayed reconnect thread → _reconnect() → _open_container() → new read_loop
    │   └── Else: state = ERROR
    │
NVDECDecoder reader_loop error
    │
    ├── av.error.FFmpegError / Exception → state = ERROR
    │   └── Pipeline loop: get_frame() returns None
    │       └── CameraManager._camera_pipeline_loop: catches, sets camera_state=ERROR
    │           └── PipelineEngine._health_check(): camera_manager.restart_camera()
    │
NVENCEncoder encode_loop error
    │
    ├── av.error.OSError (errno=-129) → _attempt_restart()
    │   │   ├── Close container, clear queue
    │   │   ├── Exponential backoff (2s, 4s, 8s... max 30s)
    │   │   ├── _init_pyav_encoder() retry
    │   │   └── Max 3 restarts, then stop_event.set()
    │   └── Other exceptions → same restart logic
    │
AI Model inference error
    │
    ├── onnxruntime exception → logged, empty detections returned
    │   └── Pipeline continues with empty detections (track ages, no new tracks)
    │
GPU OOM / Memory pressure
    │
    ├── GPUMemoryMonitor: pressure_level = CRITICAL
    │   ├── Callback: PipelineEngine._on_memory_critical() → empty_cache()
    │   ├── FramePoolManager.handle_memory_pressure() → shrink available pools
    │   └── Tracker: max_active_tracks enforcement
```

## Disconnected / Incomplete Components

| Component | Status | Issue |
|-----------|--------|-------|
| `RTMPSource` (ingestion/rtmp_source.py) | STUB | Only skeleton, not integrated |
| `PyAVDecoder` / `PyAVEncoder` (decode/pyav_decoder.py, encode/pyav_encoder.py) | DUPLICATE | Wrapper classes, not used by CameraManager |
| `ReIDEncoder` (inference/reid.py) | DISABLED | Config has `enabled: false`, not wired in CameraManager |
| `Pose` model (YOLO11n-pose) | DISABLED | Config has `enabled: false`, not instantiated |
| `Monitoring` module | SKELETON | Only exports, no implementation |
| `Integration` module | STUB | Adapter placeholders only |
| `Font rendering` in GPUAnnotator | PLACEHOLDER | Draws colored rects instead of text |
| `WebSocket health broadcasts` | PARTIAL | Backend has handler but PipelineEngine doesn't connect |
| `Tests` directory | EMPTY | All subdirs (unit, integration, hardware, runtime) have no test files |

## Dead Code / Unused Exports

| Item | Location | Reason |
|------|----------|--------|
| `RTSPSource.iter_packets()` | rtsp_source.py | Not used, `get_packet()` used instead |
| `NVDECDecoder.iter_frames()` | nvdec_decoder.py | Not used, `get_frame()` used instead |
| `GPUFrame.from_pyav_nvdec()` | gpu_frame.py | Not used, frames created manually in decoder |
| `OwnershipManager` | memory/ownership.py | Exported but not used in CameraManager |
| `CUDASyncManager` | memory/synchronization.py | Instantiated in decoder but not actively used |
| `MultiGPUMemoryMonitor` | memory/memory_monitor.py | Not used (single GPU) |
| `FFmpegPublisher` | output/publisher.py | Created but `use_ffmpeg=False` by default |

## Incomplete Loops

1. **Attendance → Backend → UI**: AttendanceEngine stores events in SQLite and triggers callbacks, but PipelineEngine doesn't connect these to backend WebSocket broadcasts
2. **Health monitoring → WebSocket**: PipelineEngine has health_callback registration but backend doesn't wire it to HealthWebSocket
3. **Geometry updates**: Backend has PUT /geometry/lines endpoint that updates CameraManager config, but requires camera restart to take effect
4. **Model hot-reload**: No mechanism to reload ONNX models without restart
5. **FramePool exhaustion**: When pool exhausted, frames are dropped but no backpressure to RTSP source