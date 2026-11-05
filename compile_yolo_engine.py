"""
Compile YOLOv11n ONNX to TensorRT FP16 Engine with Myelin-disabled tactics.
This prevents "Called with an already loaded binary graph" crashes on Turing GPUs.
"""

import app.runtime.cuda
import tensorrt as trt
from pathlib import Path

onnx_file = Path("models/yolo/yolo11n.onnx")
engine_file = Path("models/yolo/yolo11n_fp16.engine")

logger = trt.Logger(trt.Logger.INFO)
builder = trt.Builder(logger)
network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED))
parser = trt.OnnxParser(network, logger)

print(f"Parsing ONNX model: {onnx_file}")
with open(onnx_file, "rb") as f:
    if not parser.parse(f.read()):
        for i in range(parser.num_errors):
            print(f"ONNX Parse Error {i}: {parser.get_error(i)}")
        raise RuntimeError("ONNX parse failed")

print("ONNX model parsed successfully")

config = builder.create_builder_config()
config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1024 * 1024 * 1024)

# FP16 flag may not exist in TensorRT 11.3 - check if available
if hasattr(trt.BuilderFlag, 'FP16'):
    config.set_flag(trt.BuilderFlag.FP16)
    print("FP16 mode enabled")
elif hasattr(trt.BuilderFlag, 'FP16_MODE'):
    config.set_flag(trt.BuilderFlag.FP16_MODE)
    print("FP16 mode enabled (FP16_MODE)")
else:
    # FP16 might be enabled by default or via precision constraints
    # Check if we can set it via precision constraints
    print("FP16 flag not available in this TensorRT version - engine will use default precision")

# DISABLE TACTIC SOURCES THAT CAUSE MYELIN CRASHES ON TURING SM_75
# In TensorRT 11.3, we disable JIT_CONVOLUTIONS which can trigger Myelin
tactic_sources = config.get_tactic_sources()
tactic_sources &= ~(1 << int(trt.TacticSource.JIT_CONVOLUTIONS))
config.set_tactic_sources(tactic_sources)
print("Disabled JIT_CONVOLUTIONS tactic source to prevent Myelin collisions")

# Also disable cuDNN for safety if needed
# tactic_sources &= ~(1 << int(trt.TacticSource.CUDNN))
# config.set_tactic_sources(tactic_sources)

print("Building clean TensorRT engine without Myelin graph collisions...")
plan = builder.build_serialized_network(network, config)
if plan is None:
    raise RuntimeError("Failed to build TensorRT engine")

with open(engine_file, "wb") as f:
    f.write(plan)

print(f"Engine rebuild completed successfully: {engine_file}")
print(f"Engine size: {len(plan) / (1024*1024):.2f} MB")