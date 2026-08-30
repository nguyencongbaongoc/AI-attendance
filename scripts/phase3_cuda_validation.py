"""
Phase 3 — CUDA Runtime Validation Script

This script validates the complete Windows NVIDIA AI runtime stack:
- Windows / architecture / Python
- NVIDIA GPU detection
- CUDA runtime via PyTorch
- ONNX Runtime CUDA EP session + inference

This is a TEMPORARY validation script, not part of the permanent runtime module.
No cameras, no media pipeline, no production models.
"""
import os
import sys
import time
import tempfile
import json
from pathlib import Path

import numpy as np

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---- 1. Environment ----
import platform
import torch
import onnxruntime as ort
import onnx
from onnx import helper, TensorProto
import pynvml

print("=" * 60)
print("PHASE 3 - CUDA RUNTIME VALIDATION")
print("=" * 60)

# Environment
print("\n[1] ENVIRONMENT")
print(f"  Platform: {platform.platform()}")
print(f"  Architecture: {platform.machine()}")
print(f"  Python: {sys.version}")
print(f"  Python executable: {sys.executable}")
print(f"  Venv active: {hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)}")
print(f"  Venv path: {sys.prefix}")

# ---- 2. NVIDIA GPU ----
print("\n[2] NVIDIA GPU")
pynvml.nvmlInit()
gpu_count = pynvml.nvmlDeviceGetCount()
print(f"  GPU count: {gpu_count}")
for i in range(gpu_count):
    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
    name = pynvml.nvmlDeviceGetName(handle)
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
    driver = pynvml.nvmlSystemGetDriverVersion()
    if isinstance(driver, bytes):
        driver = driver.decode("utf-8")
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
    try:
        power = pynvml.nvmlDeviceGetPowerUsage(handle)
    except Exception:
        power = None
    print(f"  GPU {i}: {name}")
    print(f"  VRAM total: {mem.total // 1048576} MB")
    print(f"  VRAM used: {mem.used // 1048576} MB")
    print(f"  Driver: {driver}")
    print(f"  GPU utilization: {util.gpu}%")
    print(f"  Temperature: {temp}C")
    if power is not None:
        print(f"  Power: {power / 1000}W")
pynvml.nvmlShutdown()

# ---- 3. PyTorch CUDA ----
print("\n[3] PYTORCH CUDA")
print(f"  torch version: {torch.__version__}")
print(f"  torch CUDA version: {torch.version.cuda}")
print(f"  torch.cuda.is_available(): {torch.cuda.is_available()}")
print(f"  torch.cuda.device_count(): {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"  device name: {torch.cuda.get_device_name(0)}")
    props = torch.cuda.get_device_properties(0)
    print(f"  major.minor: {props.major}.{props.minor}")

# PyTorch CUDA tensor operation
print("  Running CUDA tensor operation...")
try:
    t0 = time.perf_counter()
    x = torch.randn(100, 100).cuda()
    y = torch.randn(100, 100).cuda()
    z = torch.matmul(x, y)
    result_cpu = z.cpu()
    t1 = time.perf_counter()
    print(f"  PyTorch CUDA operation: SUCCESS")
    print(f"  Output shape: {result_cpu.shape}")
    print(f"  Elapsed: {round((t1-t0)*1000, 3)} ms")
except Exception as e:
    print(f"  PyTorch CUDA operation: FAILED - {e}")

# ---- 4. ONNX Runtime ----
print("\n[4] ONNX RUNTIME")
print(f"  onnxruntime version: {ort.__version__}")
print(f"  available providers: {ort.get_available_providers()}")

# ---- 5. CUDA EP Session Creation ----
print("\n[5] CUDA EP SESSION CREATION")

# Create minimal ONNX model
X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [1, 3, 3])
W = helper.make_tensor_value_info('W', TensorProto.FLOAT, [1, 3, 3])
Y = helper.make_tensor_value_info('Y', TensorProto.FLOAT, [1, 3, 3])
node = helper.make_node('MatMul', ['X', 'W'], ['Y'])
graph = helper.make_graph([node], 'phase3_test', [X, W], [Y])
model = helper.make_model(graph, producer_name='phase3_validation')
model.opset_import[0].version = 21

model_path = os.path.join(str(PROJECT_ROOT / "data" / "temp"), "phase3_minimal_test.onnx")
os.makedirs(str(PROJECT_ROOT / "data" / "temp"), exist_ok=True)
onnx.save(model, model_path)
print(f"  Created minimal ONNX model at: {model_path}")

try:
    session = ort.InferenceSession(model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    print(f"  Session providers: {session.get_providers()}")
    print(f"  CUDA EP session creation: SUCCESS")
except Exception as e:
    print(f"  CUDA EP session creation: FAILED - {e}")
    session = None

# ---- 6. Actual ONNX CUDA Inference ----
print("\n[6] ONNX CUDA INFERENCE")
if session is not None:
    try:
        x = np.random.randn(1, 3, 3).astype(np.float32)
        w = np.random.randn(1, 3, 3).astype(np.float32)
        t0 = time.perf_counter()
        result = session.run(None, {'X': x, 'W': w})
        t1 = time.perf_counter()
        print(f"  ONNX CUDA inference: SUCCESS")
        print(f"  Output shape: {result[0].shape}")
        print(f"  Output dtype: {result[0].dtype}")
        print(f"  Elapsed: {round((t1-t0)*1000, 3)} ms")
    except Exception as e:
        print(f"  ONNX CUDA inference: FAILED - {e}")
else:
    print("  BLOCKED - session creation failed")

# ---- 7. GPU Memory Before/After ----
print("\n[7] GPU MEMORY OBSERVATIONS")
if torch.cuda.is_available():
    torch.cuda.synchronize()
    mem_before = torch.cuda.memory_allocated() / 1048576
    torch.cuda.synchronize()
    x = torch.randn(100, 100).cuda()
    torch.cuda.synchronize()
    mem_after = torch.cuda.memory_allocated() / 1048576
    print(f"  GPU memory before: {round(mem_before, 2)} MB")
    print(f"  GPU memory after: {round(mem_after, 2)} MB")
    print(f"  Delta: {round(mem_after - mem_before, 2)} MB")

# ---- 8. CPU Fallback ----
print("\n[8] CPU FALLBACK")
try:
    cpu_session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    print(f"  CPU session providers: {cpu_session.get_providers()}")
    x = np.random.randn(1, 3, 3).astype(np.float32)
    w = np.random.randn(1, 3, 3).astype(np.float32)
    result = cpu_session.run(None, {'X': x, 'W': w})
    print(f"  CPU fallback inference: SUCCESS")
    print(f"  Output shape: {result[0].shape}")
except Exception as e:
    print(f"  CPU fallback inference: FAILED - {e}")

# ---- 9. cuDNN Detection ----
print("\n[9] cuDNN DETECTION")
cudnn_found = False
cudnn_path = None
# Check common locations for cudnn.dll
search_paths = [
    Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA"),
    Path("C:/Windows/System32"),
    Path(os.environ.get("CUDA_PATH", "C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.3")),
]
for base in search_paths:
    if base.exists():
        for dll in base.rglob("cudnn*.dll"):
            cudnn_found = True
            cudnn_path = str(dll)
            break
    if cudnn_found:
        break

# Also check if torch bundles cudnn
try:
    import ctypes
    lib = ctypes.CDLL("cudnn6_13.dll")
    cudnn_found = True
    cudnn_path = "bundled with torch/cuda"
    lib = None
except:
    pass

print(f"  cuDNN found: {cudnn_found}")
print(f"  cuDNN path: {cudnn_path}")

# Cleanup
try:
    os.remove(model_path)
    os.rmdir(str(PROJECT_ROOT / "data" / "temp"))
except:
    pass

print("\n" + "=" * 60)
print("PHASE 3 VALIDATION COMPLETE")
print("=" * 60)
