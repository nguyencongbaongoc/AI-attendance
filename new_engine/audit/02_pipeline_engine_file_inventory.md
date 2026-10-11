# Pipeline Engine File Inventory

## Module: config
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `__init__.py` | 119 | `PipelineConfig`, `Settings`, `load_pipeline_config()`, `get_config()`, `reload_config()`, `get_camera_config()`, `get_model_config()` | Configuration loading from YAML with Pydantic validation, environment variable support, global config singleton |
| `pipeline.yaml` | 434 | (YAML config) | Single source of truth for all pipeline settings: runtime, GPU, cameras, decode, inference, models, tracking, attendance, annotation, encode, output, backend, frontend, monitoring, integration |

## Module: core
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `engine.py` | 591 | `PipelineEngine`, `EngineState`, `EngineMetrics`, `get_engine()`, `shutdown_engine()` | Main orchestration: config loading, component initialization, startup/shutdown sequencing, health monitoring, signal handling, metrics aggregation, supervisor loop |

## Module: ingestion
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `camera_manager.py` | 971 | `CameraManager`, `CameraState`, `CameraMetrics`, `get_camera_manager()`, `shutdown_camera_manager()` | Manages multiple camera pipelines: RTSP source, frame pool, decoder, AI models, tracker, encoder, publisher. Per-camera threads, lifecycle, health monitoring. |
| `rtsp_source.py` | 530 | `RTSPSource`, `RTSPSourceConfig`, `RTSPSourceMetrics`, `RTSPState`, `create_rtsp_source()` | RTSP stream ingestion via PyAV: connection, packet reading, reconnection with backoff, readiness gate (bytes progress), health monitoring (stale/degraded thresholds) |
| `rtmp_source.py` | ~100 | `RTMPSource` (stub) | RTMP ingestion placeholder - not fully implemented |
| `packet_source.py` | ~100 | `PacketSource` (base class) | Abstract base for packet sources |

## Module: decode
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `nvdec_decoder.py` | 580 | `NVDECDecoder`, `NVDECDecoderConfig`, `DecoderState`, `DecoderMetrics`, `create_nvdec_decoder()` | Hardware-accelerated H.264/H.265 decoding to GPUFrame. Uses PyAV with software decode + GPU upload (Windows GTX 1660 Ti limitation: cuvid outputs dxva2_vld not CUDA). Frame pool integration. |
| `pyav_decoder.py` | ~200 | `PyAVDecoder` wrapper | PyAV decoder abstraction |

## Module: encode
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `nvenc_encoder.py` | 616 | `NVENCEncoder`, `NVENCEncoderConfig`, `EncoderState`, `EncoderMetrics`, `create_nvenc_encoder()` | Hardware H.264 encoding from GPUFrame (NV12) via PyAV NVENC. Zero-copy using DLPack. RTSP output to MediaMTX. Restart logic for OSError -129. Frame pool integration. |
| `pyav_encoder.py` | ~200 | `PyAVEncoder` wrapper | PyAV encoder abstraction |

## Module: inference
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `face_detection.py` | 585 | `SCRFDDetector`, `SCRFDConfig`, `FaceDetection`, `create_scrfd_detector()` | SCRFD 10G face detection with 5-point landmarks. ONNX Runtime CUDA EP with IO Binding. GPU preprocessing: NV12→BGR→letterbox→normalize. NMS on GPU. |
| `face_recognition.py` | ~500 | `ArcFaceRecognizer`, `ArcFaceConfig`, `FaceEmbedding`, `create_arcface_recognizer()` | ArcFace (GlintR100) face recognition. 512-D embeddings. Enrollment database loading (NPY + metadata JSON). Cosine similarity search with threshold. |
| `person_detection.py` | ~400 | `YOLOPersonDetector`, `YOLOConfig`, `PersonDetection`, `create_yolo_detector()` | YOLO11n person detection. ONNX Runtime CUDA EP. GPU preprocessing. NMS. Returns PersonDetection in original frame coords. |
| `reid.py` | ~300 | `ReIDEncoder`, `ReIDConfig`, `ReIDEmbedding` | ReID embeddings (ResNet50) - disabled in config |
| `base.py` | ~200 | `BaseInference` | Base class for inference models |
| `preprocessing.py` | ~200 | `letterbox_resize_cuda()`, `nv12_to_bgr_cuda()`, normalization | Shared GPU preprocessing utilities |

## Module: tracking
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `tracker.py` | 685 | `Tracker`, `TrackingConfig`, `Track`, `TrackLifecycleState`, `TrackingResult`, `compute_iou()`, `compute_track_detection_score()`, `solve_track_assignment()`, `find_face_for_person()`, `update_tracks()` | Geometry-based tracking with identity fusion. IoU + center distance + area ratio + face association bonus. Greedy assignment. Face recognition identity resolution. ReID fallback (disabled). |
| `association.py` | ~200 | Association utilities | Track-detection association helpers |

## Module: attendance
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `attendance_engine.py` | 644 | `AttendanceEngine`, `CrossingEngine`, `AttendanceStore`, `LineGeometry`, `CrossingEvent`, `CrossingDirection`, `CrossingPolicyConfig`, `CameraAttendanceConfig`, `create_attendance_engine()` | Line crossing detection with debouncing. SQLite event store (attendance_events.db). Daily summaries. JSON export. Per-camera geometry and policy config. |

## Module: annotation
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `overlay.py` | 365 | `GPUAnnotator`, `AnnotationConfig`, `OverlayElement`, `create_annotator()` | GPU-only annotation rendering. NV12→BGR conversion, draw boxes/labels/line/diagnostics, BGR→NV12. Uses PyTorch CUDA ops. Font rendering placeholder. |

## Module: memory
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `gpu_frame.py` | 626 | `GPUFrame`, `PixelFormat`, `FrameOwnership`, `FrameStatus`, `CUDAContext`, `nv12_to_bgr_cuda()`, `bgr_to_nv12_cuda()`, `letterbox_resize_cuda()` | Canonical GPU-resident frame contract. NV12 two-plane tensors. Reference counting, ownership transfer, status tracking, latency breakdown. Zero-copy DLPack interop. |
| `frame_pool.py` | 466 | `FramePool`, `FramePoolManager`, `FramePoolConfig`, `PoolStrategy`, `PoolStats` | Bounded GPUFrame pools per camera. Pre-allocation (hybrid strategy). Acquisition/release with stats. VRAM budget enforcement. Memory pressure handling. |
| `ownership.py` | ~200 | `OwnershipManager` | Frame ownership tracking across pipeline stages |
| `memory_monitor.py` | 437 | `GPUMemoryMonitor`, `MemoryPressureLevel`, `MemoryThresholds`, `MemorySnapshot`, `MultiGPUMemoryMonitor`, `log_memory_usage()` | VRAM monitoring background thread. Pressure levels (NORMAL/ELEVATED/HIGH/CRITICAL/OOM). Callbacks per level. Batch size recommendation. |
| `synchronization.py` | ~150 | `CUDASyncManager` | CUDA stream/event synchronization utilities |

## Module: output
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `publisher.py` | 532 | `MediaMTXPublisher`, `FFmpegPublisher`, `PublisherConfig`, `PublisherMetrics`, `PublisherState`, `create_publisher()` | Publishes H.264 packets to MediaMTX via PyAV RTSP muxer or FFmpeg subprocess. Reconnection, health monitoring, packet buffering. |

## Module: backend
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `app.py` | 602 | FastAPI app, `APIClient`, `HealthWebSocket`, `ConnectionManager`, REST endpoints, WebSocket | Pipeline control API: health, pipeline control, camera management, attendance events, geometry, models, video streams, metrics, WebSocket for real-time health. |

## Module: monitoring
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `__init__.py` | ~100 | Monitoring exports | Health checks, metrics, alerts, structured logging, telemetry |

## Module: integration
| File | Lines | Main Classes/Functions | Responsibility |
|------|-------|------------------------|----------------|
| `__init__.py` | ~100 | Legacy adapters | Attendance adapter, model adapter, frontend adapter for legacy system integration |

## Implementation Status Summary

| Module | Files | Status | Notes |
|--------|-------|--------|-------|
| config | 2 | **IMPLEMENTED** | Complete with full YAML config |
| core | 1 | **IMPLEMENTED** | Full engine orchestration |
| ingestion | 4 | **IMPLEMENTED** | RTSP source complete, RTMP stub |
| decode | 2 | **IMPLEMENTED** | NVDEC with software fallback |
| encode | 2 | **IMPLEMENTED** | NVENC with restart logic |
| inference | 6 | **IMPLEMENTED** | SCRFD, ArcFace, YOLO complete; ReID disabled |
| tracking | 2 | **IMPLEMENTED** | Geometry + face association |
| attendance | 1 | **IMPLEMENTED** | Line crossing + SQLite store |
| annotation | 1 | **IMPLEMENTED** | GPU rendering (font placeholder) |
| memory | 5 | **IMPLEMENTED** | Frame contract, pools, monitoring |
| output | 1 | **IMPLEMENTED** | MediaMTX publisher |
| backend | 1 | **IMPLEMENTED** | FastAPI + WebSocket |
| monitoring | 1 | **PARTIAL** | Infrastructure only |
| integration | 1 | **STUB** | Adapter placeholders |

## Duplicate/Overlapping Implementations
1. **PyAV vs NVDEC/NVENC modules**: Both `pyav_decoder.py`/`pyav_encoder.py` and `nvdec_decoder.py`/`nvenc_encoder.py` exist - NVDEC/NVENC are the primary implementations using PyAV internally
2. **Frame pool**: Both `frame_pool.py` (primary) and potentially overlapping logic in `memory/__init__.py` exports
3. **Preprocessing**: `preprocessing.py` in inference vs functions in `gpu_frame.py` - gpu_frame.py is canonical
4. **Camera manager** creates its own AI model instances instead of using shared instances