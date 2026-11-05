"""
TensorRT Engine Wrapper - Load and execute .engine files directly via TensorRT Python bindings.

Provides zero-copy GPU inference for TensorRT engines with IO binding support.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


@dataclass
class TensorRTBinding:
    """Represents a TensorRT engine binding."""
    name: str
    dtype: np.dtype
    shape: Tuple[int, ...]
    is_input: bool
    buffer_ptr: int = 0


class TensorRTExecutor:
    """
    TensorRT Engine Executor for .engine files.
    
    Loads TensorRT engine from file and provides inference execution
    with CUDA stream and zero-copy IO binding.
    """
    
    def __init__(self, engine_path: str, device_id: int = 0, cuda_stream: Optional[torch.cuda.Stream] = None):
        self.engine_path = engine_path
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # TensorRT runtime objects
        self._runtime = None
        self._engine = None
        self._context = None
        self._stream = cuda_stream if cuda_stream is not None else torch.cuda.Stream(device=device_id)
        
        # Binding info
        self._bindings: List[TensorRTBinding] = []
        self._input_names: List[str] = []
        self._output_names: List[str] = []
        self._binding_ptrs: List[int] = []
        
        # Pre-allocated output tensors
        self._output_tensors: Dict[str, torch.Tensor] = {}
        
        # Stats
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_error: Optional[str] = None
        self._initialized = False
        
        # Thread safety lock for concurrent access
        self._lock = threading.RLock()
    
    def _cleanup_partial(self) -> None:
        """Clean up any partially initialized TensorRT resources.
        
        Called when initialization fails mid-way to prevent VRAM leaks.
        """
        # TensorRT Python bindings use reference counting - just clear references
        self._context = None
        self._engine = None
        self._runtime = None
        self._output_tensors.clear()
        self._initialized = False
        torch.cuda.empty_cache()
    
    def initialize(self) -> bool:
        """Initialize TensorRT engine and context."""
        if self._initialized:
            return True
        
        try:
            import tensorrt as trt
        except ImportError:
            self._last_error = "TensorRT Python bindings not available"
            logger.error(f"TensorRTExecutor: {self._last_error}")
            return False
        
        try:
            # Create TensorRT logger
            trt_logger = trt.Logger(trt.Logger.WARNING)
            
            # Load engine from file
            with open(self.engine_path, 'rb') as f:
                engine_data = f.read()
            
            self._runtime = trt.Runtime(trt_logger)
            self._engine = self._runtime.deserialize_cuda_engine(engine_data)
            
            if self._engine is None:
                self._last_error = "Failed to deserialize engine"
                logger.error(f"TensorRTExecutor: {self._last_error}")
                self._cleanup_partial()
                return False
            
            # Create execution context
            self._context = self._engine.create_execution_context()
            
            # Use provided CUDA stream (do not create a new one if already provided)
            if self._stream is None:
                self._stream = torch.cuda.Stream(device=self.device_id)
            
            # Setup bindings
            self._setup_bindings()
            
            self._initialized = True
            logger.info(f"TensorRTExecutor: Initialized engine from {self.engine_path}")
            logger.info(f"  Bindings: {len(self._bindings)} ({len(self._input_names)} inputs, {len(self._output_names)} outputs)")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"TensorRTExecutor: Initialization failed: {e}")
            self._cleanup_partial()
            return False
    
    def _setup_bindings(self) -> None:
        """Setup binding information and pre-allocate output tensors."""
        import tensorrt as trt
        
        self._bindings.clear()
        self._input_names.clear()
        self._output_names.clear()
        self._binding_ptrs.clear()
        self._output_tensors.clear()
        
        # Iterate over engine bindings
        for i in range(self._engine.num_io_tensors):
            name = self._engine.get_tensor_name(i)
            dtype = self._engine.get_tensor_dtype(name)
            shape = self._engine.get_tensor_shape(name)
            is_input = self._engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT
            
            # Convert TensorRT dtype to numpy
            trt_to_numpy = {
                trt.DataType.FLOAT: np.float32,
                trt.DataType.HALF: np.float16,
                trt.DataType.INT32: np.int32,
                trt.DataType.INT8: np.int8,
                trt.DataType.BOOL: np.bool_,
            }
            np_dtype = trt_to_numpy.get(dtype, np.float32)
            
            binding = TensorRTBinding(
                name=name,
                dtype=np_dtype,
                shape=tuple(shape),
                is_input=is_input
            )
            self._bindings.append(binding)
            
            if is_input:
                self._input_names.append(name)
            else:
                self._output_names.append(name)
                # Pre-allocate output tensor with shape (replace -1 with 1 for dynamic batch)
                out_shape = tuple(1 if s == -1 else s for s in binding.shape)
                out_tensor = torch.empty(
                    out_shape,
                    dtype=torch.float32 if np_dtype == np.float32 else torch.float16,
                    device=self.device
                )
                self._output_tensors[name] = out_tensor
        
        # Initialize binding pointers array
        self._binding_ptrs = [0] * len(self._bindings)
    
    def _bind_input(self, name: str, tensor: torch.Tensor) -> bool:
        """Bind input tensor to TensorRT binding."""
        try:
            # Find binding index
            binding_idx = -1
            for i, b in enumerate(self._bindings):
                if b.name == name:
                    binding_idx = i
                    break
            
            if binding_idx == -1:
                logger.error(f"TensorRTExecutor: Input binding '{name}' not found")
                return False
            
            # Verify tensor is on correct device and contiguous
            if not tensor.is_cuda:
                tensor = tensor.to(self.device)
            if not tensor.is_contiguous():
                tensor = tensor.contiguous()
            
            # Set binding address
            self._context.set_tensor_address(name, tensor.data_ptr())
            self._binding_ptrs[binding_idx] = tensor.data_ptr()
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"TensorRTExecutor: Failed to bind input '{name}': {e}")
            return False
    
    def _bind_outputs(self) -> bool:
        """Bind pre-allocated output tensors."""
        try:
            for name in self._output_names:
                tensor = self._output_tensors[name]
                self._context.set_tensor_address(name, tensor.data_ptr())
            return True
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"TensorRTExecutor: Failed to bind outputs: {e}")
            return False
    
    def infer(self, input_tensors: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        Run inference with TensorRT engine.
        
        Args:
            input_tensors: Dict of input_name -> tensor (on GPU)
            
        Returns:
            Dict of output_name -> tensor (on GPU)
        """
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError("TensorRTExecutor not initialized")
        
        with self._lock:
            try:
                # Bind inputs and set shapes for dynamic inputs
                for name, tensor in input_tensors.items():
                    if not self._bind_input(name, tensor):
                        raise RuntimeError(f"Failed to bind input: {name}")
                    # Set input shape for dynamic inputs (required for execute_async_v3)
                    if hasattr(self._context, 'set_input_shape'):
                        self._context.set_input_shape(name, tensor.shape)
                
                # Bind outputs
                if not self._bind_outputs():
                    raise RuntimeError("Failed to bind outputs")
                
                # Execute
                start = time.perf_counter()
                
                # Use execute_async_v3 for TensorRT 8.5+
                if hasattr(self._context, 'execute_async_v3'):
                    self._context.execute_async_v3(stream_handle=self._stream.cuda_stream)
                else:
                    # Legacy execute_async_v2
                    self._context.execute_async_v2(
                        bindings=self._binding_ptrs,
                        stream_handle=self._stream.cuda_stream
                    )
                
                # CRITICAL: Synchronize stream BEFORE reading output tensors
                # Prevents host/device race condition where CPU reads while GPU is still writing
                self._stream.synchronize()
                inference_ms = (time.perf_counter() - start) * 1000
                
                # Update stats
                self._inference_count += 1
                self._total_inference_time += inference_ms
                
                # Return cloned output tensors to prevent aliasing issues
                return {k: v.clone() if hasattr(v, 'clone') else v.copy() for k, v in self._output_tensors.items()}
                
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"TensorRTExecutor: Inference failed: {e}")
                raise
    
    def get_binding_info(self) -> Dict[str, Any]:
        """Get binding information for debugging."""
        info = {
            "engine_path": self.engine_path,
            "initialized": self._initialized,
            "num_bindings": len(self._bindings),
            "inputs": [],
            "outputs": []
        }
        
        for b in self._bindings:
            binding_info = {
                "name": b.name,
                "dtype": str(b.dtype),
                "shape": b.shape,
                "is_input": b.is_input
            }
            if b.is_input:
                info["inputs"].append(binding_info)
            else:
                info["outputs"].append(binding_info)
        
        return info
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "engine_path": self.engine_path,
            "initialized": self._initialized,
            "inference_count": self._inference_count,
            "avg_inference_ms": (
                self._total_inference_time / self._inference_count 
                if self._inference_count > 0 else 0
            ),
            "last_error": self._last_error,
            "device_id": self.device_id,
            "bindings": self.get_binding_info()
        }
    
    def cleanup(self) -> None:
        """Release TensorRT resources.
        
        TensorRT Python bindings use reference counting - clearing references
        allows garbage collection to free the underlying C++ objects.
        Explicitly call destroy() on context, engine, and runtime to ensure
        proper cleanup of CUDA resources.
        """
        with self._lock:
            if self._context:
                try:
                    self._context.destroy()
                except Exception:
                    pass
                self._context = None
            if self._engine:
                try:
                    self._engine.destroy()
                except Exception:
                    pass
                self._engine = None
            if self._runtime:
                try:
                    self._runtime.destroy()
                except Exception:
                    pass
                self._runtime = None
            self._stream = None
            self._output_tensors.clear()
            self._initialized = False
            torch.cuda.empty_cache()
    
    def __enter__(self) -> "TensorRTExecutor":
        """Context manager entry - initialize if needed."""
        if not self._initialized:
            if not self.initialize():
                raise RuntimeError(f"Failed to initialize TensorRTExecutor: {self._last_error}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.cleanup()
        return False  # Don't suppress exceptions


def create_tensorrt_executor(engine_path: str, device_id: int = 0, cuda_stream: Optional[torch.cuda.Stream] = None) -> TensorRTExecutor:
    """Factory function to create TensorRT executor."""
    return TensorRTExecutor(engine_path, device_id, cuda_stream)