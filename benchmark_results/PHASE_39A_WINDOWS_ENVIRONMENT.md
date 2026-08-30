# PHASE 39A — WINDOWS ENVIRONMENT FORENSIC REPORT

**Timestamp:** 2026-08-28T14:12:19Z
**Status:** PASS

## System Information

| Component | Version/Details |
|-----------|-----------------|
| Windows Version | 10.0.26200.9168 |
| Python Version | 3.12.10 |
| Python Executable | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance\\.venv\\Scripts\\python.exe |
| pip Version | 26.2.1 |
| FFmpeg Version | 9.0-full_build-www.gyan.dev |
| MediaMTX Path | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance\\mediamtx\\mediamtx.exe |
| MediaMTX Config | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance\\mediamtx\\mediamtx.yml |
| CUDA Version | 13.3 |
| NVIDIA Driver | 610.47 |
| GPU | NVIDIA GeForce GTX 1660 Ti |
| ONNX Runtime Version | 1.28.0 |
| ONNX Runtime Providers | TensorrtExecutionProvider, CUDAExecutionProvider, CPUExecutionProvider |

## Environment Configuration

| Item | Value |
|------|-------|
| Virtual Environment | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance\\.venv |
| Project Root | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance |
| Working Directory | C:\\Users\\Nguyen Cong Thong\\Desktop\\AI attendance |
| Frontend Dependencies | Available (node_modules present) |
| Node/npm Available | Yes |
| PATH Dependencies | CUDA, FFmpeg, Git, Node.js, Python in PATH |

## Verification Results

- [x] Windows version verified
- [x] Python version verified (3.12.10)
- [x] Virtual environment active
- [x] pip available
- [x] FFmpeg available (9.0)
- [x] MediaMTX executable present
- [x] MediaMTX config present (configured for CAM1/CAM2 RTMP->RTSP)
- [x] CUDA 13.3 available
- [x] NVIDIA driver 610.47
- [x] GPU: GTX 1660 Ti (6GB VRAM)
- [x] ONNX Runtime 1.28.0 with CUDA EP
- [x] Required Python packages installed
- [x] Frontend dependencies installed
- [x] Node/npm available
- [x] All PATH dependencies resolved

## Known Limitations

None identified for core environment.

## Conclusion

All production runtime dependencies resolve from a clean PowerShell session. Environment is READY for production bootstrap.
