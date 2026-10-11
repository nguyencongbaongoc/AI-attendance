# Repository Inventory

## Top-Level Directory Structure
```
AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE/
├── benchmark_results/         # Benchmark output files
├── build/                     # CMake build artifacts
├── CMakeFiles/                # CMake configuration
├── config/                    # Legacy configuration
│   ├── geometry/              # Geometry configurations
│   ├── default.yaml           # Main legacy config
│   └── runtime-ports.json     # Port assignments
├── data/                      # Runtime data (SQLite, NPY files)
├── docs/                      # Documentation
├── isolated_src/              # Isolated source code
├── isolated_tests/            # Isolated tests
├── live/                      # Live streaming artifacts
├── logs/                      # Application logs
├── mediamtx/                  # MediaMTX server
│   ├── mediamtx.exe           # MediaMTX binary
│   ├── mediamtx.yml           # MediaMTX configuration
│   ├── auto.crt, auto.key     # TLS certificates
│   └── LICENSE
├── models/                    # ONNX model files
│   ├── scrfd/                 # SCRFD face detection
│   ├── arcface/               # ArcFace face recognition
│   ├── yolo/                  # YOLO person/pose detection
│   ├── reid/                  # ReID person re-identification
│   └── landmark/              # Facial landmarks
├── New folder/                # Empty directory
├── phase7_runtime_diagnostic/ # Phase 7 diagnostic artifacts
├── pipeline_engine/           # NEW: Core pipeline engine (untracked)
├── recordings/                # Video recordings
├── reports/                   # Generated reports
├── requirements/              # Python requirements
│   ├── base.txt               # Cross-platform deps
│   └── windows.txt            # Windows/CUDA deps
├── scripts/                   # Utility scripts
├── TensorRT-11.3.0.99/        # TensorRT SDK
├── test_data/                 # Test data files
├── tests/                     # Test directory (empty test files)
├── tools/                     # Development tools
├── UI/                        # Frontend (single HTML file)
│   └── index.html             # Control center UI
├── Video_Codec_SDK_13.0.37/   # NVIDIA Video Codec SDK
├── video_pipeline_v2/         # Previous pipeline version
├── bootstrap.py               # Main bootstrap script
├── bootstrap.bat              # Windows bootstrap batch
├── Makefile                   # Build configuration
├── pytest.ini                 # Pytest configuration
├── patch_submit.py            # Patch submission utility
├── .gitignore                 # Git ignore rules
└── Various test video files   # .mp4, .h264 test files
```

## Pipeline Engine Directory Structure
```
pipeline_engine/
├── __init__.py                # Package exports
├── config/                    # Configuration loading
│   ├── __init__.py            # Config models + loader
│   ├── __pycache__/
│   └── pipeline.yaml          # Main pipeline config
├── core/                      # Core orchestration
│   ├── __init__.py
│   ├── __pycache__/
│   └── engine.py              # PipelineEngine main class
├── ingestion/                 # Stream ingestion
│   ├── __init__.py
│   ├── __pycache__/
│   ├── camera_manager.py      # Multi-camera lifecycle
│   ├── rtsp_source.py         # RTSP packet source
│   ├── rtmp_source.py         # RTMP source (stub)
│   └── packet_source.py       # Base packet source
├── decode/                    # Video decoding
│   ├── __init__.py
│   ├── __pycache__/
│   ├── nvdec_decoder.py       # NVDEC decoder (software fallback)
│   └── pyav_decoder.py        # PyAV decoder wrapper
├── encode/                    # Video encoding
│   ├── __init__.py
│   ├── __pycache__/
│   ├── nvenc_encoder.py       # NVENC encoder
│   └── pyav_encoder.py        # PyAV encoder wrapper
├── inference/                 # AI inference
│   ├── __init__.py
│   ├── __pycache__/
│   ├── face_detection.py      # SCRFD face detector
│   ├── face_recognition.py    # ArcFace recognizer
│   ├── person_detection.py    # YOLO person detector
│   ├── reid.py                # ReID embeddings
│   ├── base.py                # Base inference class
│   └── preprocessing.py       # Preprocessing utilities
├── tracking/                  # Object tracking
│   ├── __init__.py
│   ├── __pycache__/
│   ├── tracker.py             # Main tracker + geometry
│   └── association.py         # Track-detection association
├── attendance/                # Attendance events
│   ├── __init__.py
│   ├── __pycache__/
│   └── attendance_engine.py   # Line crossing + event store
├── annotation/                # GPU annotation overlay
│   ├── __init__.py
│   ├── __pycache__/
│   └── overlay.py             # GPUAnnotator
├── memory/                    # GPU memory management
│   ├── __init__.py
│   ├── __pycache__/
│   ├── gpu_frame.py           # GPUFrame contract
│   ├── frame_pool.py          # FramePool + Manager
│   ├── ownership.py           # Ownership tracking
│   ├── memory_monitor.py      # VRAM monitoring
│   └── synchronization.py     # CUDA sync utilities
├── output/                    # Output publishing
│   ├── __init__.py
│   ├── __pycache__/
│   └── publisher.py           # MediaMTX publisher
├── backend/                   # FastAPI backend
│   ├── __init__.py
│   ├── __pycache__/
│   └── app.py                 # API endpoints
├── monitoring/                # Health/metrics
│   ├── __init__.py
│   └── __pycache__/
├── integration/               # Legacy adapters
│   ├── __init__.py
│   └── __pycache__/
├── tests/                     # Test directories (empty)
│   ├── hardware/
│   ├── integration/
│   ├── runtime/
│   └── unit/
└── __pycache__/
```

## File Count Summary
| Category | Files | Lines (approx) |
|----------|-------|----------------|
| Config | 3 | 550 |
| Core Engine | 1 | 591 |
| Ingestion | 4 | ~2000 |
| Decode | 2 | ~1000 |
| Encode | 2 | ~1000 |
| Inference | 6 | ~3000 |
| Tracking | 2 | ~1000 |
| Attendance | 1 | 644 |
| Annotation | 1 | 365 |
| Memory | 6 | ~2000 |
| Output | 1 | 532 |
| Backend | 1 | 602 |
| Monitoring | 1 | ~100 |
| Integration | 1 | ~100 |
| **Total** | **32** | **~13,500** |

## Key Configuration Files
| File | Purpose |
|------|---------|
| `pipeline_engine/config/pipeline.yaml` | Complete pipeline configuration (434 lines) |
| `mediamtx/mediamtx.yml` | MediaMTX server configuration (719 lines) |
| `config/default.yaml` | Legacy system configuration |
| `requirements/base.txt` | Cross-platform Python dependencies |
| `requirements/windows.txt` | Windows/CUDA Python dependencies |
| `pytest.ini` | Pytest configuration |

## Model Files (in models/)
| Model | Path | Size | Purpose |
|-------|------|------|---------|
| SCRFD 10G | `models/scrfd/scrfd_10g_bnkps.onnx` | ~5.6MB | Face detection + 5-point landmarks |
| ArcFace | `models/arcface/glintr100.onnx` | ~220MB | Face recognition (512-D embeddings) |
| YOLO11n | `models/yolo/yolo11n.onnx` | ~5MB | Person detection |
| YOLO11n-pose | `models/yolo/yolo11n-pose.pt` | ~5MB | Pose estimation (unused) |
| ReID | `models/reid/resnet50_reid.onnx` | ~100MB | Person re-identification (disabled) |
| Landmarks | `models/landmark/1k3d68.onnx` | ~50MB | 68-point facial landmarks (unused) |

## External Dependencies
| Component | Version/Location | Role |
|-----------|------------------|------|
| MediaMTX | `mediamtx/mediamtx.exe` | RTSP/RTMP/HLS/WebRTC media server |
| FFmpeg | System/Video_Codec_SDK | Video encode/decode (via PyAV) |
| CUDA Toolkit | 13.3 (system) | GPU compute |
| cuDNN | 9.10.2 (bundled) | Deep learning primitives |
| TensorRT | 11.3.0.99 (local) | Inference optimization (unused) |
| ONNX Runtime | 1.28.0 (pip) | Model inference execution |
| PyTorch | 2.13.0+cu126 (pip) | Tensor operations, CUDA management |