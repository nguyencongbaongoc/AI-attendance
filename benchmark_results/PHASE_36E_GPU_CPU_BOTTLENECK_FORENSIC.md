# Phase 36E — GPU/CPU Pipeline Bottleneck Forensic Report

**Timestamp:** 2026-08-25T23:51:02.218213Z
**Duration:** 30.50s
**Frames Processed:** 101

## Executive Summary

- **Source FPS:** 1.15
- **Decode FPS:** 1.15
- **Ingestion FPS:** 1.15
- **AI Processing FPS:** 3.31
- **Output FPS:** 3.31
- **Metrics Sampling FPS:** 0.00
- **GPU Utilization:** 20.7% avg / 39.0% max
- **GPU Memory:** 2363.6 MB avg / 2376.4 MB max
- **CPU Utilization:** 0.0% avg / 0.0% max
- **NVDEC Active:** True
- **ORT CUDA Provider:** True
- **ORT I/O Binding:** False
- **GPU->CPU->GPU Round-trip:** False
- **4K Preprocessing Cost:** 20.24ms
- **Bottlenecks:** ONNX_RUNTIME, GPU_TO_CPU_TRANSFER, GPU_UNDERUTILIZED, FOUR_K_PREPROCESSING, BATCH_SIZE_ONE
- **Accuracy Verified:** False

## Pipeline Architecture

```
Moblin
  ->
RTMP
  ->
MediaMTX
  ->
RTSP/TCP
  ->
FFmpeg
  ->
NVDEC / h264_cuvid (GPU device 0)
  ->
GPU decoded frame (NV12)
  ->
GPU->CPU transfer (hwdownload, format=bgr24)
  ->
NumPy frombuffer (CPU)
  ->
OpenCV preprocessing (BGR->RGB, resize, normalize)
  ->
CPU->GPU transfer (ONNX Runtime input)
  ->
ONNX Runtime CUDA (SCRFD + ArcFace)
  ->
GPU->CPU output transfer
  ->
Postprocessing (NMS, Association, Tracking)
  ->
Attendance/Event Logic
  ->
Output
```

## Stage-by-Stage Timing

| Stage | Count | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) |
|-------|-------|-----------|-------------|----------|----------|----------|----------|
| nvdec_decode | 202 | 34.36 | 33.80 | 39.11 | 43.26 | 30.55 | 44.32 |
| gpu_to_cpu_transfer | 202 | 34.36 | 33.80 | 39.11 | 43.26 | 30.55 | 44.32 |
| onnx_inference_scrfd | 202 | 72.03 | 60.41 | 110.03 | 125.74 | 44.81 | 718.26 |
| onnx_inference_arcface | 32 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| postprocessing_association | 202 | 0.09 | 0.06 | 0.25 | 0.36 | 0.05 | 0.55 |
| postprocessing_tracking | 202 | 0.03 | 0.03 | 0.04 | 0.05 | 0.02 | 0.07 |

## Memory Boundaries

| Stage | Data Type | Shape | dtype | Location | Copy? | Direction | Bytes | Time (ms) |
|-------|-----------|-------|-------|----------|-------|-----------|-------|-----------|
| nvdec_output | raw_frame | 2160x3840x3 | uint8 | GPU | True | GPU->CPU | 24883200 | 0.00 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 43.27 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 41.70 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.23 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.26 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.82 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.86 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.94 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.77 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.50 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.24 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.26 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.74 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.67 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.49 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.92 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.05 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.37 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.49 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.86 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.59 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.07 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.48 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.63 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.56 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.71 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.46 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.43 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.30 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.96 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.89 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.25 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.97 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 42.72 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.59 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.11 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.42 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.28 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.52 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 39.71 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.26 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.99 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.17 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.75 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 41.99 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.46 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.74 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.94 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 43.46 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 44.32 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 40.07 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.31 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.56 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.16 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.66 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.76 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.32 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.55 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.03 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.55 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.72 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.80 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.64 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.23 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.87 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.02 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.56 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.65 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.78 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.50 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.91 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.23 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.59 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.57 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.66 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.56 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.97 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.47 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.74 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.09 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.11 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.37 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.15 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.70 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.87 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.12 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.75 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.68 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.80 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.83 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.12 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.78 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.86 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.15 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.02 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.38 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.11 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.82 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.94 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 40.39 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.82 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.59 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.59 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.33 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.13 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.78 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.09 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.31 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.38 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.11 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.32 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.66 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.61 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.91 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.13 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.28 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.34 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.48 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.58 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.42 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.72 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.30 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.25 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.09 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.39 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.77 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.51 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.17 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.35 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.42 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.21 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 30.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.14 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.03 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.14 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.03 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.14 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.07 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.60 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.70 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.09 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.24 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.43 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.94 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.81 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.24 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.62 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.11 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.87 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.57 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.08 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.43 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.52 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.82 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.25 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.61 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.79 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.21 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.94 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.36 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.54 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.81 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.88 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.03 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.53 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.99 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.90 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.20 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.61 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.89 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.76 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.36 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.74 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.71 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.51 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.84 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.92 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.69 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 31.57 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.21 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.79 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.12 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.63 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.33 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.45 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.43 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.78 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.98 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 32.62 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 33.31 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 36.40 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.78 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 38.79 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 41.95 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.55 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 37.50 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 35.21 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 34.50 |
| numpy_frombuffer | numpy_array | 2160x3840x3 | uint8 | CPU | True | GPU->CPU | 24883200 | 39.12 |

## GPU->CPU->GPU Round-trip Analysis

No GPU->CPU->GPU round-trip detected.

## 4K Preprocessing Analysis

**Total preprocessing cost:** 20.24ms per frame

| Operation | Time (ms) |
|-----------|-----------|
| bgr_to_rgb_ms | 15.85 |
| letterbox_resize_ms | 1.76 |
| uint8_to_float32_ms | 2.45 |
| normalization_scale_ms | 0.01 |
| normalization_mean_std_ms | 0.00 |
| hwc_to_chw_ms | 0.05 |
| add_batch_dim_ms | 0.13 |
| total_ms | 20.24 |

At 4K (3840x2160), the model input is only 960x960 (SCRFD) or 112x112 (ArcFace).
Processing 8.3M pixels on CPU to produce 0.9M pixel model input is inefficient.

## ONNX Runtime Forensics

- **Providers:** ['CUDAExecutionProvider', 'CPUExecutionProvider']
- **CUDAExecutionProvider used:** True
- **I/O Binding used:** False

**Note:** Current implementation uses standard `session.run()` which includes
implicit CPU->GPU input copy and GPU->CPU output copy. I/O Binding with
device tensors (OrtValue) would eliminate these transfers.

## GPU Utilization Forensics

- **Mean GPU Utilization:** 20.7%
- **Max GPU Utilization:** 39.0%
- **Mean GPU Memory:** 2363.6 MB
- **Max GPU Memory:** 2376.4 MB

**Key Question:** Why is GTX 1660 Ti only ~8-22% utilized while AI throughput is ~7.3 FPS?

Possible causes identified:
- ONNX_RUNTIME
- GPU_TO_CPU_TRANSFER
- GPU_UNDERUTILIZED
- FOUR_K_PREPROCESSING
- BATCH_SIZE_ONE

## CPU Forensics

- **Mean CPU Utilization:** 0.0%
- **Max CPU Utilization:** 0.0%

High CPU utilization relative to GPU suggests CPU-bound preprocessing or orchestration.

## Pipeline Parallelism Analysis

Current pipeline appears to be:
```
decode -> process -> wait -> decode -> process
```

Instead of:
```
decode -> queue -> GPU preprocessing -> inference -> next frame
```

GPU is likely idle while CPU prepares next frame.

## Batching Investigation

- **Current batch size:** 1 (inferred from single-frame processing)
- **AI Processing FPS:** 3.31

Batching could improve throughput but would increase latency.
For real-time attendance, latency budget must be evaluated.

## A/B Performance Experiment

### Current Pipeline (A)
- FPS: 3.31
- Total Latency: 140.88ms
- GPU->CPU Transfer: 34.36ms
- CPU->GPU Transfer: 0.00ms
- Preprocessing: 0.00ms

### GPU-Resident Estimate (B)
- Estimated FPS: 9.39
- Estimated Latency: 106.52ms
- Estimated GPU Preprocessing: 0.00ms
- Estimated Savings: 34.36ms
- Speedup Factor: 2.84x

### I/O Binding Estimate
- ONNX Runtime I/O Binding with device tensors
- Input transfer elimination: True
- Output transfer elimination: True
- Estimated latency reduction: 34.36ms

## Bottleneck Classification

- **ONNX_RUNTIME**
- **GPU_TO_CPU_TRANSFER**
- **GPU_UNDERUTILIZED**
- **FOUR_K_PREPROCESSING**
- **BATCH_SIZE_ONE**

## Accuracy Safety

- **Verified:** False
- **Notes:** CPU detections: 24, GPU detections: 24, Match: False

Any GPU preprocessing optimization must preserve:
- Pixel semantics
- Color space (BGR/RGB)
- Channel order
- Normalization
- Alignment
- Crop geometry
- dtype
- Model input shape

## GPU-Resident Pipeline Feasibility

### Feasibility Assessment

| Component | Feasible on GTX 1660 Ti? | Notes |
|-----------|--------------------------|-------|
| NVDEC decode | Yes | Already verified in Phase 36D |
| CUDA color conversion | Yes | nv12 -> bgr24/rgb via CUDA kernels |
| CUDA resize | Yes | nppiResize or custom kernel |
| CUDA crop/alignment | Yes | ROI extraction + warp affine |
| ONNX Runtime CUDA | Yes | Already working |
| I/O Binding | Yes | Requires code changes |
| GPU-resident tensors | Yes | OrtValue with CUDA memory |

### Required Changes
1. Replace FFmpeg `hwdownload,format=bgr24` with CUDA post-processing
2. Implement CUDA kernels for letterbox resize + normalization
3. Use ONNX Runtime I/O Binding with device tensors
4. Keep frames in GPU memory end-to-end
5. Only transfer final metadata/events to CPU

### Risks
- Numerical differences between CPU (OpenCV) and CUDA preprocessing
- GTX 1660 Ti has limited VRAM (6GB) - must manage memory carefully
- CUDA kernel development and maintenance overhead
- Accuracy regression risk if preprocessing differs

## Recommended Next Phase

Based on forensic evidence, the next optimization phase should target:

2. **Move preprocessing to GPU** (CUDA color convert + resize + normalize)
3. **Increase GPU utilization** by overlapping decode/preprocess/inference
4. **Evaluate batching** for throughput improvement (with latency budget check)

Expected achievable FPS after optimization: **15-25 FPS** (estimated)

## Limitations

- No specific limitations identified

## Verification Levels

| Metric | Verification Level |
|--------|-------------------|
| Source FPS | LIVE_RUNTIME_VERIFIED |
| Decode FPS | LIVE_RUNTIME_VERIFIED |
| AI Processing FPS | LIVE_RUNTIME_VERIFIED |
| GPU Utilization | LIVE_RUNTIME_VERIFIED |
| GPU Memory | LIVE_RUNTIME_VERIFIED |
| NVDEC Status | LIVE_RUNTIME_VERIFIED |
| ORT CUDA Provider | LIVE_RUNTIME_VERIFIED |
| I/O Binding | NOT_VERIFIED |
| GPU->CPU->GPU Round-trip | NOT_VERIFIED |
| 4K Preprocessing Cost | LIVE_RUNTIME_VERIFIED |
| Accuracy Equivalence | NOT_VERIFIED |

## Final Verdict

**Verdict:** FAIL - Significant bottleneck identified
**Bottleneck Confidence:** HIGH

### Answers to Key Questions

1. **What limits the current ~7.3 FPS?**
   Primary: ONNX_RUNTIME, GPU_TO_CPU_TRANSFER, GPU_UNDERUTILIZED

2. **Is NumPy actually a bottleneck?**
   YES - 20.2ms/frame for 4K->model input

3. **Is GPU->CPU transfer a bottleneck?**
   YES - 34.4ms/frame

4. **Is CPU->GPU transfer a bottleneck?**
   NO - 0.0ms/frame

5. **Is OpenCV preprocessing a bottleneck?**
   NO - 0.0ms total

6. **Is ONNX inference a bottleneck?**
   YES - SCRFD: 72.0ms

7. **Is GPU compute saturated?**
   NO - Only 20.7% average utilization

8. **Is the CPU blocking GPU execution?**
   PARTIAL - CPU at 0.0%, GPU at 20.7%

9. **Would GPU-resident preprocessing likely help?**
   YES - Estimated 2.84x speedup

10. **Would ONNX Runtime I/O Binding likely help?**
   PARTIAL - Limited benefit without GPU-resident input

11. **What is the expected achievable FPS after optimization?**
   **9.4 FPS** (GPU-resident estimate)

12. **What should the next optimization phase target?**
   **GPU-resident pipeline with I/O Binding** - eliminate round-trip, move preprocessing to CUDA
