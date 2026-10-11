# pipeline_engine package
"""AI Attendance Pipeline Engine - Complete GPU-first video pipeline."""

__version__ = "1.0.0"
__author__ = "AI Attendance Team"

from pipeline_engine.config import load_pipeline_config, get_config, PipelineConfig
from pipeline_engine.core.engine import PipelineEngine, EngineState, get_engine, shutdown_engine
from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat, FrameOwnership, CUDAContext
from pipeline_engine.memory.frame_pool import FramePool, FramePoolManager, FramePoolConfig
from pipeline_engine.memory.ownership import OwnershipManager, get_ownership_manager
from pipeline_engine.memory.memory_monitor import GPUMemoryMonitor, MemoryPressureLevel

__all__ = [
    "load_pipeline_config",
    "get_config",
    "PipelineConfig",
    "PipelineEngine",
    "EngineState",
    "get_engine",
    "shutdown_engine",
    "GPUFrame",
    "PixelFormat",
    "FrameOwnership",
    "CUDAContext",
    "FramePool",
    "FramePoolManager",
    "FramePoolConfig",
    "OwnershipManager",
    "get_ownership_manager",
    "GPUMemoryMonitor",
    "MemoryPressureLevel",
]