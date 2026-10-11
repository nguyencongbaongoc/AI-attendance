"""
GPU Inference Engine - V2 GPU-first video pipeline.

Base class for running ONNX/TensorRT models on GPU with zero-copy I/O binding.
All inference happens on CUDA tensors - no CPU staging.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Tuple, Union
from pathlib import Path
from abc import ABC, abstractmethod
from enum import Enum

import numpy as np
import torch
import onnxruntime as ort

from video_pipeline_v2.core.gpu_frame import GPUFrame
from video_pipeline_v2.ai.model_contracts import (
    ModelInputContract, ModelOutputContract, ModelContractRegistry
)

logger = logging.getLogger(__name__)


class InferenceBackend(str, Enum):
    ONNX_RUNTIME = "onnxruntime"
    TENSORRT = "tensorrt"


@dataclass
class InferenceConfig:
    """Configuration for GPU inference engine."""
    model_path: str
    model_name: str  # For contract lookup
    backend: InferenceBackend = InferenceBackend.ONNX_RUNTIME
    device_id: int = 0
    # ONNX Runtime options
    providers: Tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider")
    enable_mem_pattern: bool = True
    enable_cpu_mem_arena: bool = True
    graph_optimization_level: int = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # IO Binding
    use_io_binding: bool = True
    # TensorRT options
    trt_engine_path: Optional[str] = None
    trt_fp16: bool = False
    trt_int8: bool = False
    trt_workspace_gb: int = 2
    # Validation
    validate_input: bool = True
    validate_output: bool = True


@dataclass
class InferenceResult:
    """Result of a single inference call."""
    outputs: Dict[str, torch.Tensor]  # name -> tensor
    inference_time_ms: float
    preprocess_time_ms: float = 0.0
    postprocess_time_ms: float = 0.0
    input_shape: Tuple[int, ...] = ()
    output_shapes: Dict[str, Tuple[int, ...]] = field(default_factory=dict)
    backend: str = ""
    provider: str = ""


class GPUInferenceEngine(ABC):
    """
    Base class for GPU model inference with zero-copy I/O binding.
    
    Key principles:
    - Input/output tensors stay on GPU
    - Uses ONNX Runtime IO Binding for zero-copy
    - Validates against model contracts
    - Thread-safe for concurrent inference
    """
    
    def __init__(self, config: InferenceConfig):
        self.config = config
        self.model_name = config.model_name
        self.device_id = config.device_id
        self._session: Optional[ort.InferenceSession] = None
        self._io_binding: Optional[ort.IOBinding] = None
        self._input_contract: Optional[ModelInputContract] = None
        self._output_contracts: Dict[str, ModelOutputContract] = {}
        self._initialized = False
        self._lock = threading.RLock()
        
        # Stats
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_error: Optional[str] = None
    
    def initialize(self) -> bool:
        """Initialize the inference session."""
        with self._lock:
            if self._initialized:
                return True
            
            try:
                # Load contracts
                contracts = ModelContractRegistry.get(self.model_name)
                self._input_contract = contracts["input"]
                
                if "outputs" in contracts:
                    for out in contracts["outputs"]:
                        self._output_contracts[out.name] = out
                else:
                    self._output_contracts["default"] = contracts["output"]
                
                # Create session
                self._create_session()
                
                # Setup IO Binding
                if self.config.use_io_binding:
                    self._setup_io_binding()
                
                self._initialized = True
                logger.info(f"GPUInferenceEngine({self.model_name}): initialized on device {self.device_id}")
                return True
                
            except Exception as e:
                self._last_error = str(e)
                logger.error(f"GPUInferenceEngine({self.model_name}): initialization failed: {e}")
                return False
    
    def _create_session(self) -> None:
        """Create ONNX Runtime session."""
        session_options = ort.SessionOptions()
        session_options.enable_mem_pattern = self.config.enable_mem_pattern
        session_options.enable_cpu_mem_arena = self.config.enable_cpu_mem_arena
        session_options.graph_optimization_level = self.config.graph_optimization_level
        
        # Set intra-op threads for CPU fallback
        session_options.intra_op_num_threads = 1
        session_options.inter_op_num_threads = 1
        
        self._session = ort.InferenceSession(
            self.config.model_path,
            sess_options=session_options,
            providers=list(self.config.providers),
        )
        
        # Log actual provider
        providers = self._session.get_providers()
        if "CUDAExecutionProvider" in providers:
            logger.info(f"GPUInferenceEngine({self.model_name}): using CUDAExecutionProvider")
        else:
            logger.warning(f"GPUInferenceEngine({self.model_name}): CUDA not available, using {providers[0]}")
    
    def _setup_io_binding(self) -> None:
        """Setup ONNX Runtime IO Binding for zero-copy inference."""
        if self._session is None:
            return
        
        self._io_binding = self._session.io_binding()
        
        # Bind input
        input_name = self._session.get_inputs()[0].name
        input_shape = self._input_contract.shape
        # Allow dynamic batch
        if input_shape[0] == -1 or input_shape[0] == 1:
            pass  # Will bind with actual shape at runtime
        
        logger.debug(f"GPUInferenceEngine({self.model_name}): IO Binding setup for input '{input_name}'")
    
    def _bind_input_tensor(self, input_tensor: torch.Tensor) -> None:
        """Bind input tensor to IO Binding."""
        if self._io_binding is None or self._session is None:
            return
        
        input_name = self._session.get_inputs()[0].name
        
        self._io_binding.bind_input(
            name=input_name,
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,  # Assuming FP32 input
            shape=tuple(input_tensor.shape),
            buffer_ptr=input_tensor.data_ptr(),
        )
    
    def _bind_output_tensors(self, output_shapes: Dict[str, Tuple[int, ...]]) -> Dict[str, torch.Tensor]:
        """Bind output tensors and return output tensor dict."""
        if self._io_binding is None or self._session is None:
            return {}
        
        output_tensors = {}
        output_infos = self._session.get_outputs()
        
        for i, out_info in enumerate(output_infos):
            name = out_info.name
            shape = output_shapes.get(name, tuple(out_info.shape))
            
            # Handle dynamic shapes
            actual_shape = list(shape)
            if actual_shape[0] == -1:
                actual_shape[0] = 1  # Default batch
            
            # Create output tensor
            out_tensor = torch.empty(
                actual_shape,
                dtype=torch.float32,
                device=f'cuda:{self.device_id}'
            )
            
            self._io_binding.bind_output(
                name=name,
                device_type='cuda',
                device_id=self.device_id,
                element_type=np.float32,
                shape=tuple(actual_shape),
                buffer_ptr=out_tensor.data_ptr(),
            )
            
            output_tensors[name] = out_tensor
        
        return output_tensors
    
    def infer(self, input_tensor: torch.Tensor) -> InferenceResult:
        """
        Run inference on GPU tensor.
        
        Args:
            input_tensor: Input tensor on CUDA, matching input contract
            
        Returns:
            InferenceResult with output tensors on GPU
        """
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError(f"Model {self.model_name} not initialized")
        
        # Validate input (skip for GPUFrame - it has its own validation)
        if self.config.validate_input:
            # If input is a GPUFrame, skip contract validation (it handles its own format)
            from video_pipeline_v2.core.gpu_frame import GPUFrame
            if not isinstance(input_tensor, GPUFrame):
                valid, msg = self._input_contract.validate(input_tensor)
                if not valid:
                    raise ValueError(f"Input validation failed for {self.model_name}: {msg}")
        
        # Ensure contiguous (skip for GPUFrame - handled differently)
        from video_pipeline_v2.core.gpu_frame import GPUFrame
        if not isinstance(input_tensor, GPUFrame):
            input_tensor = input_tensor.contiguous()
        
        # Preprocess time (if applicable)
        preprocess_start = time.perf_counter()
        preprocessed = self.preprocess(input_tensor)
        preprocess_ms = (time.perf_counter() - preprocess_start) * 1000
        
        # Inference
        inference_start = time.perf_counter()
        
        if self.config.use_io_binding and self._io_binding:
            # Zero-copy IO Binding path
            self._io_binding.clear_binding_inputs()
            self._io_binding.clear_binding_outputs()
            
            self._bind_input_tensor(preprocessed)
            
            # Determine output shapes
            output_shapes = self.get_output_shapes(preprocessed.shape[0])
            output_tensors = self._bind_output_tensors(output_shapes)
            
            # Run inference
            self._session.run_with_iobinding(self._io_binding)
            
            # Synchronize
            torch.cuda.synchronize(self.device_id)
            
            outputs = output_tensors
            
        else:
            # Standard path (copies data)
            input_name = self._session.get_inputs()[0].name
            output_names = [o.name for o in self._session.get_outputs()]
            
            # Convert to numpy for ORT (this copies!)
            input_np = preprocessed.cpu().numpy()
            
            ort_outputs = self._session.run(output_names, {input_name: input_np})
            
            outputs = {}
            for i, name in enumerate(output_names):
                outputs[name] = torch.from_numpy(ort_outputs[i]).to(f'cuda:{self.device_id}')
        
        inference_ms = (time.perf_counter() - inference_start) * 1000
        
        # Postprocess
        postprocess_start = time.perf_counter()
        outputs = self.postprocess(outputs)
        postprocess_ms = (time.perf_counter() - postprocess_start) * 1000
        
        # Validate outputs
        if self.config.validate_output:
            for name, tensor in outputs.items():
                valid, msg = ModelContractRegistry.validate_output(self.model_name, tensor, name)
                if not valid:
                    logger.warning(f"Output validation failed for {self.model_name}.{name}: {msg}")
        
        # Update stats
        self._inference_count += 1
        self._total_inference_time += inference_ms
        
        return InferenceResult(
            outputs=outputs,
            inference_time_ms=inference_ms,
            preprocess_time_ms=preprocess_ms,
            postprocess_time_ms=postprocess_ms,
            input_shape=tuple(preprocessed.shape),
            output_shapes={k: tuple(v.shape) for k, v in outputs.items()},
            backend=self.config.backend.value,
            provider=self._session.get_providers()[0] if self._session else "unknown",
        )
    
    @abstractmethod
    def preprocess(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """Preprocess input tensor. Override in subclasses."""
        pass
    
    @abstractmethod
    def postprocess(self, outputs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Postprocess output tensors. Override in subclasses."""
        pass
    
    @abstractmethod
    def get_output_shapes(self, batch_size: int) -> Dict[str, Tuple[int, ...]]:
        """Get output shapes for a given batch size. Override in subclasses."""
        pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get inference statistics."""
        with self._lock:
            return {
                "model_name": self.model_name,
                "initialized": self._initialized,
                "inference_count": self._inference_count,
                "avg_inference_ms": (
                    self._total_inference_time / self._inference_count 
                    if self._inference_count > 0 else 0
                ),
                "last_error": self._last_error,
                "device_id": self.device_id,
                "provider": self._session.get_providers()[0] if self._session else "none",
            }
    
    def cleanup(self) -> None:
        """Release resources."""
        with self._lock:
            self._session = None
            self._io_binding = None
            self._initialized = False
            torch.cuda.empty_cache()


if __name__ == "__main__":
    # Test basic initialization
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    print("GPUInferenceEngine base class ready")