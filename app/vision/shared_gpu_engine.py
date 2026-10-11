"""
Phase 11 WP1 — Shared GPU Singleton Inference Engine.

Provides a single shared instance of all 4 AI models loaded into GPU VRAM once.
Both CAM1 and CAM2 frame workers feed frames into the same shared model instances.

Total static VRAM for all loaded models combined MUST be <= 1.8 GB.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import tensorrt as trt
import torch

from app.models.registry import get_model_registry

logger = logging.getLogger(__name__)


@dataclass
class TensorRTModelSession:
    """TensorRT engine session with I/O bindings."""
    model_id: str
    engine: trt.ICudaEngine
    context: trt.IExecutionContext
    input_name: str
    output_names: List[str]
    input_shape: Tuple[int, ...]
    output_shapes: Dict[str, Tuple[int, ...]]
    device_id: int
    cuda_ep_used: bool = True

    def infer(self, input_tensor: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Run inference with zero-copy GPU tensors."""
        # Set dynamic input shape if needed
        if any(d == -1 for d in self.input_shape):
            self.context.set_input_shape(self.input_name, tuple(input_tensor.shape))
        
        # Get output shapes
        output_shapes = {}
        for name in self.output_names:
            output_shapes[name] = tuple(self.context.get_tensor_shape(name))
        
        # Allocate output tensors
        d_outputs = {}
        for name, shape in output_shapes.items():
            d_outputs[name] = torch.empty(shape, dtype=torch.float32, device=f'cuda:{self.device_id}')
        
        # Execute
        bindings = [input_tensor.data_ptr()] + [d_outputs[name].data_ptr() for name in self.output_names]
        self.context.execute_v2(bindings)
        torch.cuda.synchronize(self.device_id)
        
        return d_outputs


class SharedGPUEngine:
    """
    Singleton GPU Inference Engine.
    
    All models are loaded ONCE into GPU VRAM.
    Multiple cameras share the same model instances.
    Thread-safe via locks.
    """
    
    _instance: Optional["SharedGPUEngine"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        device_id: int = 0,
        enable_trt: bool = True,
    ):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.device_id = device_id
        self.enable_trt = enable_trt
        self._models: Dict[str, TensorRTModelSession] = {}
        self._model_locks: Dict[str, threading.Lock] = {}
        self._initialized = False
        self._trt_logger = trt.Logger(trt.Logger.WARNING)
        self._runtime = trt.Runtime(self._trt_logger)
        
    def initialize(self) -> bool:
        """Load all models into GPU VRAM."""
        if self._initialized:
            return True
        
        try:
            # Verify CUDA
            if not torch.cuda.is_available():
                logger.error("CUDA not available")
                return False
            
            # Clear cache
            torch.cuda.empty_cache()
            
            # Load models in order of VRAM usage (largest first for better fragmentation)
            model_order = [
                ("arcface", "models/arcface/glintr100_fp16.engine", (1, 3, 112, 112)),
                ("reid", "models/reid/resnet50_reid_fp16.engine", (1, 3, 256, 128)),
                ("scrfd", "models/scrfd/scrfd_10g_bnkps_fp16.engine", (1, 3, 640, 640)),
                ("yolo_person", "models/yolo/yolo11n_fp16.engine", (1, 3, 640, 640)),
            ]
            
            for model_id, engine_path, input_shape in model_order:
                if not self._load_model(model_id, engine_path, input_shape):
                    logger.error(f"Failed to load {model_id}")
                    return False
            
            # Verify total VRAM
            total_vram = self.get_vram_report()
            logger.info(f"Shared GPU Engine initialized. Total VRAM: {total_vram['allocated_mb']} MB allocated, {total_vram['reserved_mb']} MB reserved")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Shared GPU Engine: {e}")
            self._cleanup()
            return False
    
    def _load_model(self, model_id: str, engine_path: str, input_shape: Tuple[int, ...]) -> bool:
        """Load a single TensorRT engine."""
        try:
            import os
            if not os.path.exists(engine_path):
                logger.error(f"Engine not found: {engine_path}")
                return False
            
            # Deserialize engine
            with open(engine_path, 'rb') as f:
                engine = self._runtime.deserialize_cuda_engine(f.read())
            
            # Create context
            context = engine.create_execution_context()
            
            # Set input shape for dynamic models
            context.set_input_shape(engine.get_tensor_name(0), input_shape)
            
            # Get I/O info
            input_name = engine.get_tensor_name(0)
            output_names = []
            output_shapes = {}
            for i in range(engine.num_io_tensors):
                name = engine.get_tensor_name(i)
                if engine.get_tensor_mode(name) == trt.TensorIOMode.OUTPUT:
                    output_names.append(name)
                    output_shapes[name] = tuple(context.get_tensor_shape(name))
            
            session = TensorRTModelSession(
                model_id=model_id,
                engine=engine,
                context=context,
                input_name=input_name,
                output_names=output_names,
                input_shape=input_shape,
                output_shapes=output_shapes,
                device_id=self.device_id,
                cuda_ep_used=True,
            )
            
            self._models[model_id] = session
            self._model_locks[model_id] = threading.Lock()
            
            logger.info(f"Loaded {model_id} TensorRT engine: input={input_shape}, outputs={output_shapes}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load {model_id}: {e}")
            return False
    
    def infer(self, model_id: str, input_tensor: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Run inference on a shared model.
        
        Thread-safe: uses per-model lock to serialize access.
        """
        if model_id not in self._models:
            raise ValueError(f"Model {model_id} not loaded")
        
        lock = self._model_locks[model_id]
        with lock:
            session = self._models[model_id]
            return session.infer(input_tensor)
    
    def get_vram_report(self) -> Dict[str, Any]:
        """Get current VRAM usage."""
        if not torch.cuda.is_available():
            return {"error": "CUDA not available"}
        
        allocated = torch.cuda.memory_allocated(self.device_id) // (1024 * 1024)
        reserved = torch.cuda.memory_reserved(self.device_id) // (1024 * 1024)
        total = 6144  # GTX 1660 Ti
        
        return {
            "device_id": self.device_id,
            "allocated_mb": allocated,
            "reserved_mb": reserved,
            "free_mb": total - reserved,
            "total_mb": total,
            "usage_percent": round(reserved / total * 100, 1),
        }
    
    def is_loaded(self, model_id: str) -> bool:
        """Check if a model is loaded."""
        return model_id in self._models
    
    def get_loaded_models(self) -> List[str]:
        """Get list of loaded model IDs."""
        return list(self._models.keys())
    
    def _cleanup(self):
        """Clean up GPU resources."""
        for model_id in list(self._models.keys()):
            try:
                del self._models[model_id]
            except Exception:
                pass
        self._models.clear()
        self._model_locks.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._initialized = False
    
    def close(self):
        """Release all GPU resources."""
        self._cleanup()


def create_shared_gpu_engine(device_id: int = 0) -> SharedGPUEngine:
    """Factory function to create/get the shared GPU engine singleton."""
    return SharedGPUEngine(device_id=device_id)