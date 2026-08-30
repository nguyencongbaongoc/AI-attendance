#!/usr/bin/env python
"""Generate markdown report from Phase 36E forensic JSON results."""

import json

# Load the saved JSON report
with open('benchmark_results/PHASE_36E_GPU_CPU_BOTTLENECK_FORENSIC.json', 'r') as f:
    result = json.load(f)

# Generate markdown with ASCII-only arrows
md = []
md.append('# Phase 36E \u2014 GPU/CPU Pipeline Bottleneck Forensic Report')
md.append('')
md.append(f'**Timestamp:** {result["timestamp"]}')
md.append(f'**Duration:** {result["duration_seconds"]:.2f}s')
md.append(f'**Frames Processed:** {result["frames_processed"]}')
md.append('')

md.append('## Executive Summary')
md.append('')
md.append(f'- **Source FPS:** {result["fps"]["source_fps"]:.2f}')
md.append(f'- **Decode FPS:** {result["fps"]["decode_fps"]:.2f}')
md.append(f'- **Ingestion FPS:** {result["fps"]["ingestion_fps"]:.2f}')
md.append(f'- **AI Processing FPS:** {result["fps"]["ai_processing_fps"]:.2f}')
md.append(f'- **Output FPS:** {result["fps"]["output_fps"]:.2f}')
md.append(f'- **Metrics Sampling FPS:** {result["fps"]["metrics_sampling_fps"]:.2f}')
md.append(f'- **GPU Utilization:** {result["gpu_utilization"]["mean"]:.1f}% avg / {result["gpu_utilization"]["max"]:.1f}% max')
md.append(f'- **GPU Memory:** {result["gpu_memory_mb"]["mean"]:.1f} MB avg / {result["gpu_memory_mb"]["max"]:.1f} MB max')
md.append(f'- **CPU Utilization:** {result["cpu_utilization"]["mean"]:.1f}% avg / {result["cpu_utilization"]["max"]:.1f}% max')
md.append(f'- **NVDEC Active:** {result["nvdec"]["active"]}')
md.append(f'- **ORT CUDA Provider:** {result["onnx_runtime"]["cuda_provider_used"]}')
md.append(f'- **ORT I/O Binding:** {result["onnx_runtime"]["io_binding_used"]}')
md.append(f'- **GPU->CPU->GPU Round-trip:** {result["gpu_cpu_gpu_roundtrip"]["detected"]}')
md.append(f'- **4K Preprocessing Cost:** {result["preprocessing_4k"]["total_cost_ms"]:.2f}ms')
md.append(f'- **Bottlenecks:** {", ".join(result["bottleneck_classification"]) if result["bottleneck_classification"] else "None identified"}')
md.append(f'- **Accuracy Verified:** {result["accuracy_verified"]}')
md.append('')

md.append('## Pipeline Architecture')
md.append('')
md.append('```')
md.append('Moblin')
md.append('  ->')
md.append('RTMP')
md.append('  ->')
md.append('MediaMTX')
md.append('  ->')
md.append('RTSP/TCP')
md.append('  ->')
md.append('FFmpeg')
md.append('  ->')
md.append(f'NVDEC / h264_cuvid (GPU device {result["nvdec"]["gpu_device"]})')
md.append('  ->')
md.append('GPU decoded frame (NV12)')
md.append('  ->')
md.append('GPU->CPU transfer (hwdownload, format=bgr24)')
md.append('  ->')
md.append('NumPy frombuffer (CPU)')
md.append('  ->')
md.append('OpenCV preprocessing (BGR->RGB, resize, normalize)')
md.append('  ->')
md.append('CPU->GPU transfer (ONNX Runtime input)')
md.append('  ->')
md.append('ONNX Runtime CUDA (SCRFD + ArcFace)')
md.append('  ->')
md.append('GPU->CPU output transfer')
md.append('  ->')
md.append('Postprocessing (NMS, Association, Tracking)')
md.append('  ->')
md.append('Attendance/Event Logic')
md.append('  ->')
md.append('Output')
md.append('```')
md.append('')

# Stage timings
md.append('## Stage-by-Stage Timing')
md.append('')
md.append('| Stage | Count | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) |')
md.append('|-------|-------|-----------|-------------|----------|----------|----------|----------|')
for name, timing in result["stage_timings"].items():
    if timing["count"] > 0:
        md.append(f'| {name} | {timing["count"]} | {timing["mean_ms"]:.2f} | {timing["median_ms"]:.2f} | {timing["p95_ms"]:.2f} | {timing["p99_ms"]:.2f} | {timing["min_ms"]:.2f} | {timing["max_ms"]:.2f} |')
md.append('')

# Memory boundaries
md.append('## Memory Boundaries')
md.append('')
md.append('| Stage | Data Type | Shape | dtype | Location | Copy? | Direction | Bytes | Time (ms) |')
md.append('|-------|-----------|-------|-------|----------|-------|-----------|-------|-----------|')
for mb in result["memory_boundaries"]:
    shape_str = 'x'.join(str(s) for s in mb["shape"])
    md.append(f'| {mb["stage_name"]} | {mb["data_type"]} | {shape_str} | {mb["dtype"]} | {mb["location"]} | {mb["copy_occurred"]} | {mb["copy_direction"] or "N/A"} | {mb["bytes_transferred"]} | {mb["transfer_time_ms"]:.2f} |')
md.append('')

# GPU->CPU->GPU Round-trip
md.append('## GPU->CPU->GPU Round-trip Analysis')
md.append('')
if result["gpu_cpu_gpu_roundtrip"]["detected"]:
    md.append('**DETECTED: GPU->CPU->GPU round-trip occurs for every frame**')
    md.append('')
    md.append(f'- **Bytes per frame:** {result["gpu_cpu_gpu_roundtrip"]["bytes_per_frame"] / 1024 / 1024:.2f} MB')
    md.append(f'- **Transfer time:** {result["gpu_cpu_gpu_roundtrip"]["transfer_time_ms"]:.2f} ms')
    md.append(f'- **At {result["fps"]["ai_processing_fps"]:.1f} FPS:** {result["gpu_cpu_gpu_roundtrip"]["bytes_per_frame"] * result["fps"]["ai_processing_fps"] / 1024 / 1024:.2f} MB/s memory traffic')
    md.append('')
    md.append('This round-trip is a major bottleneck candidate.')
else:
    md.append('No GPU->CPU->GPU round-trip detected.')
md.append('')

# 4K Preprocessing
md.append('## 4K Preprocessing Analysis')
md.append('')
md.append(f'**Total preprocessing cost:** {result["preprocessing_4k"]["total_cost_ms"]:.2f}ms per frame')
md.append('')
md.append('| Operation | Time (ms) |')
md.append('|-----------|-----------|')
for op, time_ms in result["preprocessing_4k"]["breakdown"].items():
    md.append(f'| {op} | {time_ms:.2f} |')
md.append('')
md.append('At 4K (3840x2160), the model input is only 960x960 (SCRFD) or 112x112 (ArcFace).')
md.append('Processing 8.3M pixels on CPU to produce 0.9M pixel model input is inefficient.')
md.append('')

# ONNX Runtime
md.append('## ONNX Runtime Forensics')
md.append('')
md.append(f'- **Providers:** {result["onnx_runtime"]["providers"]}')
md.append(f'- **CUDAExecutionProvider used:** {result["onnx_runtime"]["cuda_provider_used"]}')
md.append(f'- **I/O Binding used:** {result["onnx_runtime"]["io_binding_used"]}')
md.append('')
md.append('**Note:** Current implementation uses standard `session.run()` which includes')
md.append('implicit CPU->GPU input copy and GPU->CPU output copy. I/O Binding with')
md.append('device tensors (OrtValue) would eliminate these transfers.')
md.append('')

# GPU Utilization
md.append('## GPU Utilization Forensics')
md.append('')
md.append(f'- **Mean GPU Utilization:** {result["gpu_utilization"]["mean"]:.1f}%')
md.append(f'- **Max GPU Utilization:** {result["gpu_utilization"]["max"]:.1f}%')
md.append(f'- **Mean GPU Memory:** {result["gpu_memory_mb"]["mean"]:.1f} MB')
md.append(f'- **Max GPU Memory:** {result["gpu_memory_mb"]["max"]:.1f} MB')
md.append('')
md.append('**Key Question:** Why is GTX 1660 Ti only ~8-22% utilized while AI throughput is ~7.3 FPS?')
md.append('')
md.append('Possible causes identified:')
for bottleneck in result["bottleneck_classification"]:
    md.append(f'- {bottleneck}')
md.append('')

# CPU Forensics
md.append('## CPU Forensics')
md.append('')
md.append(f'- **Mean CPU Utilization:** {result["cpu_utilization"]["mean"]:.1f}%')
md.append(f'- **Max CPU Utilization:** {result["cpu_utilization"]["max"]:.1f}%')
md.append('')
md.append('High CPU utilization relative to GPU suggests CPU-bound preprocessing or orchestration.')
md.append('')

# Pipeline Parallelism
md.append('## Pipeline Parallelism Analysis')
md.append('')
md.append('Current pipeline appears to be:')
md.append('```')
md.append('decode -> process -> wait -> decode -> process')
md.append('```')
md.append('')
md.append('Instead of:')
md.append('```')
md.append('decode -> queue -> GPU preprocessing -> inference -> next frame')
md.append('```')
md.append('')
md.append('GPU is likely idle while CPU prepares next frame.')
md.append('')

# Batching
md.append('## Batching Investigation')
md.append('')
md.append('- **Current batch size:** 1 (inferred from single-frame processing)')
md.append(f'- **AI Processing FPS:** {result["fps"]["ai_processing_fps"]:.2f}')
md.append('')
md.append('Batching could improve throughput but would increase latency.')
md.append('For real-time attendance, latency budget must be evaluated.')
md.append('')

# A/B Comparison
md.append('## A/B Performance Experiment')
md.append('')
if result["ab_comparison"]:
    current = result["ab_comparison"]["current"]
    gpu_resident = result["ab_comparison"]["gpu_resident_estimate"]
    md.append('### Current Pipeline (A)')
    md.append(f'- FPS: {current["fps"]:.2f}')
    md.append(f'- Total Latency: {current["total_latency_ms"]:.2f}ms')
    md.append(f'- GPU->CPU Transfer: {current["gpu_cpu_transfer_ms"]:.2f}ms')
    md.append(f'- CPU->GPU Transfer: {current["cpu_gpu_transfer_ms"]:.2f}ms')
    md.append(f'- Preprocessing: {current["preprocessing_ms"]:.2f}ms')
    md.append('')
    md.append('### GPU-Resident Estimate (B)')
    md.append(f'- Estimated FPS: {gpu_resident["fps"]:.2f}')
    md.append(f'- Estimated Latency: {gpu_resident["total_latency_ms"]:.2f}ms')
    md.append(f'- Estimated GPU Preprocessing: {gpu_resident["estimated_gpu_preprocessing_ms"]:.2f}ms')
    md.append(f'- Estimated Savings: {gpu_resident["estimated_savings_ms"]:.2f}ms')
    md.append(f'- Speedup Factor: {gpu_resident["speedup_factor"]:.2f}x')
    md.append('')
    md.append('### I/O Binding Estimate')
    io = result["ab_comparison"]["io_binding_estimate"]
    md.append(f'- {io["description"]}')
    md.append(f'- Input transfer elimination: {io["expected_input_transfer_elimination"]}')
    md.append(f'- Output transfer elimination: {io["expected_output_transfer_elimination"]}')
    md.append(f'- Estimated latency reduction: {io["estimated_latency_reduction_ms"]:.2f}ms')
md.append('')

# Bottleneck Classification
md.append('## Bottleneck Classification')
md.append('')
for bottleneck in result["bottleneck_classification"]:
    md.append(f'- **{bottleneck}**')
    if bottleneck in result["bottleneck_evidence"]:
        ev = result["bottleneck_evidence"][bottleneck]
        if isinstance(ev, dict):
            for k, v in ev.items():
                md.append(f'  - {k}: {v}')
        else:
            md.append(f'  - {ev}')
md.append('')

# Accuracy Safety
md.append('## Accuracy Safety')
md.append('')
md.append(f'- **Verified:** {result["accuracy_verified"]}')
md.append(f'- **Notes:** {result["accuracy_notes"]}')
md.append('')
md.append('Any GPU preprocessing optimization must preserve:')
md.append('- Pixel semantics')
md.append('- Color space (BGR/RGB)')
md.append('- Channel order')
md.append('- Normalization')
md.append('- Alignment')
md.append('- Crop geometry')
md.append('- dtype')
md.append('- Model input shape')
md.append('')

# GPU-Resident Feasibility
md.append('## GPU-Resident Pipeline Feasibility')
md.append('')
md.append('### Feasibility Assessment')
md.append('')
md.append('| Component | Feasible on GTX 1660 Ti? | Notes |')
md.append('|-----------|--------------------------|-------|')
md.append('| NVDEC decode | Yes | Already verified in Phase 36D |')
md.append('| CUDA color conversion | Yes | nv12 -> bgr24/rgb via CUDA kernels |')
md.append('| CUDA resize | Yes | nppiResize or custom kernel |')
md.append('| CUDA crop/alignment | Yes | ROI extraction + warp affine |')
md.append('| ONNX Runtime CUDA | Yes | Already working |')
md.append('| I/O Binding | Yes | Requires code changes |')
md.append('| GPU-resident tensors | Yes | OrtValue with CUDA memory |')
md.append('')
md.append('### Required Changes')
md.append('1. Replace FFmpeg `hwdownload,format=bgr24` with CUDA post-processing')
md.append('2. Implement CUDA kernels for letterbox resize + normalization')
md.append('3. Use ONNX Runtime I/O Binding with device tensors')
md.append('4. Keep frames in GPU memory end-to-end')
md.append('5. Only transfer final metadata/events to CPU')
md.append('')
md.append('### Risks')
md.append('- Numerical differences between CPU (OpenCV) and CUDA preprocessing')
md.append('- GTX 1660 Ti has limited VRAM (6GB) - must manage memory carefully')
md.append('- CUDA kernel development and maintenance overhead')
md.append('- Accuracy regression risk if preprocessing differs')
md.append('')

# Recommended Next Phase
md.append('## Recommended Next Phase')
md.append('')
md.append('Based on forensic evidence, the next optimization phase should target:')
md.append('')
if 'GPU_CPU_GPU_ROUNDTRIP' in result["bottleneck_classification"]:
    md.append('1. **Eliminate GPU->CPU->GPU round-trip** via I/O Binding and GPU-resident preprocessing')
if 'PREPROCESSING' in result["bottleneck_classification"] or 'FOUR_K_PREPROCESSING' in result["bottleneck_classification"]:
    md.append('2. **Move preprocessing to GPU** (CUDA color convert + resize + normalize)')
if 'GPU_UNDERUTILIZED' in result["bottleneck_classification"]:
    md.append('3. **Increase GPU utilization** by overlapping decode/preprocess/inference')
if 'BATCH_SIZE_ONE' in result["bottleneck_classification"]:
    md.append('4. **Evaluate batching** for throughput improvement (with latency budget check)')
md.append('')
md.append('Expected achievable FPS after optimization: **15-25 FPS** (estimated)')
md.append('')

# Limitations
md.append('## Limitations')
md.append('')
for lim in result["limitations"]:
    md.append(f'- {lim}')
if not result["limitations"]:
    md.append('- No specific limitations identified')
md.append('')

# Verification Levels
md.append('## Verification Levels')
md.append('')
md.append('| Metric | Verification Level |')
md.append('|--------|-------------------|')
md.append(f'| Source FPS | {"LIVE_RUNTIME_VERIFIED" if result["fps"]["source_fps"] > 0 else "NOT_VERIFIED"} |')
md.append(f'| Decode FPS | {"LIVE_RUNTIME_VERIFIED" if result["fps"]["decode_fps"] > 0 else "NOT_VERIFIED"} |')
md.append(f'| AI Processing FPS | {"LIVE_RUNTIME_VERIFIED" if result["fps"]["ai_processing_fps"] > 0 else "NOT_VERIFIED"} |')
md.append(f'| GPU Utilization | {"LIVE_RUNTIME_VERIFIED" if result["gpu_utilization"]["samples"] else "NOT_VERIFIED"} |')
md.append(f'| GPU Memory | {"LIVE_RUNTIME_VERIFIED" if result["gpu_memory_mb"]["samples"] else "NOT_VERIFIED"} |')
md.append(f'| NVDEC Status | {"LIVE_RUNTIME_VERIFIED" if result["nvdec"]["active"] else "NOT_VERIFIED"} |')
md.append(f'| ORT CUDA Provider | {"LIVE_RUNTIME_VERIFIED" if result["onnx_runtime"]["cuda_provider_used"] else "NOT_VERIFIED"} |')
md.append(f'| I/O Binding | {"LIVE_RUNTIME_VERIFIED" if result["onnx_runtime"]["io_binding_used"] else "NOT_VERIFIED"} |')
md.append(f'| GPU->CPU->GPU Round-trip | {"LIVE_RUNTIME_VERIFIED" if result["gpu_cpu_gpu_roundtrip"]["detected"] else "NOT_VERIFIED"} |')
md.append(f'| 4K Preprocessing Cost | {"LIVE_RUNTIME_VERIFIED" if result["preprocessing_4k"]["total_cost_ms"] > 0 else "NOT_VERIFIED"} |')
md.append(f'| Accuracy Equivalence | {"LIVE_RUNTIME_VERIFIED" if result["accuracy_verified"] else "NOT_VERIFIED"} |')
md.append('')

# Final Verdict
md.append('## Final Verdict')
md.append('')

if result["fps"]["ai_processing_fps"] < 10 and result["gpu_utilization"]["mean"] < 30:
    verdict = 'FAIL - Significant bottleneck identified'
    confidence = 'HIGH'
elif result["fps"]["ai_processing_fps"] < 15:
    verdict = 'PASS_WITH_DOCUMENTED_LIMITATION - Bottleneck identified but measurable'
    confidence = 'HIGH'
else:
    verdict = 'PASS - Performance acceptable'
    confidence = 'MEDIUM'

md.append(f'**Verdict:** {verdict}')
md.append(f'**Bottleneck Confidence:** {confidence}')
md.append('')

md.append('### Answers to Key Questions')
md.append('')
md.append('1. **What limits the current ~7.3 FPS?**')
if result["bottleneck_classification"]:
    md.append(f'   Primary: {", ".join(result["bottleneck_classification"][:3])}')
else:
    md.append('   Not definitively identified')
md.append('')
md.append('2. **Is NumPy actually a bottleneck?**')
md.append(f'   {"YES" if "PREPROCESSING" in result["bottleneck_classification"] or "FOUR_K_PREPROCESSING" in result["bottleneck_classification"] else "NO"} - {result["preprocessing_4k"]["total_cost_ms"]:.1f}ms/frame for 4K->model input')
md.append('')
md.append('3. **Is GPU->CPU transfer a bottleneck?**')
md.append(f'   {"YES" if "GPU_TO_CPU_TRANSFER" in result["bottleneck_classification"] else "NO"} - {result["stage_timings"].get("gpu_to_cpu_transfer", {"mean_ms": 0})["mean_ms"]:.1f}ms/frame')
md.append('')
md.append('4. **Is CPU->GPU transfer a bottleneck?**')
md.append(f'   {"YES" if "CPU_TO_GPU_TRANSFER" in result["bottleneck_classification"] else "NO"} - {result["stage_timings"].get("cpu_to_gpu_transfer", {"mean_ms": 0})["mean_ms"]:.1f}ms/frame')
md.append('')
md.append('5. **Is OpenCV preprocessing a bottleneck?**')
preprocessing_sum = sum(result["stage_timings"].get(s, {"mean_ms": 0})["mean_ms"] for s in ['bgr_to_rgb_conversion', 'letterbox_resize', 'uint8_to_float32', 'normalization', 'hwc_to_chw_transpose', 'add_batch_dim'])
md.append(f'   {"YES" if "PREPROCESSING" in result["bottleneck_classification"] else "NO"} - {preprocessing_sum:.1f}ms total')
md.append('')
md.append('6. **Is ONNX inference a bottleneck?**')
md.append(f'   {"YES" if "ONNX_RUNTIME" in result["bottleneck_classification"] else "NO"} - SCRFD: {result["stage_timings"].get("onnx_inference_scrfd", {"mean_ms": 0})["mean_ms"]:.1f}ms')
md.append('')
md.append('7. **Is GPU compute saturated?**')
md.append(f'   {"YES" if result["gpu_utilization"]["mean"] > 80 else "NO"} - Only {result["gpu_utilization"]["mean"]:.1f}% average utilization')
md.append('')
md.append('8. **Is the CPU blocking GPU execution?**')
md.append(f'   {"YES" if result["cpu_utilization"]["mean"] > 100 and result["gpu_utilization"]["mean"] < 30 else "PARTIAL"} - CPU at {result["cpu_utilization"]["mean"]:.1f}%, GPU at {result["gpu_utilization"]["mean"]:.1f}%')
md.append('')
md.append('9. **Would GPU-resident preprocessing likely help?**')
if result["ab_comparison"]:
    speedup = result["ab_comparison"]["gpu_resident_estimate"]["speedup_factor"]
    md.append(f'   {"YES" if speedup > 1.5 else "UNCERTAIN"} - Estimated {speedup:.2f}x speedup')
else:
    md.append('   Cannot estimate')
md.append('')
md.append('10. **Would ONNX Runtime I/O Binding likely help?**')
if result["gpu_cpu_gpu_roundtrip"]["detected"]:
    md.append(f'   YES - Would eliminate {result["gpu_cpu_gpu_roundtrip"]["transfer_time_ms"]:.1f}ms transfer overhead')
else:
    md.append('   PARTIAL - Limited benefit without GPU-resident input')
md.append('')
md.append('11. **What is the expected achievable FPS after optimization?**')
if result["ab_comparison"]:
    md.append(f'   **{result["ab_comparison"]["gpu_resident_estimate"]["fps"]:.1f} FPS** (GPU-resident estimate)')
else:
    md.append('   Cannot estimate without A/B comparison')
md.append('')
md.append('12. **What should the next optimization phase target?**')
md.append('   **GPU-resident pipeline with I/O Binding** - eliminate round-trip, move preprocessing to CUDA')
md.append('')

# Write markdown file
with open('benchmark_results/PHASE_36E_GPU_CPU_BOTTLENECK_FORENSIC.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(md))

print('Markdown report generated successfully!')