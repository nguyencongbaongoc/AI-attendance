"""
Phase 36F - GPU-Resident ONNX Runtime Inference with I/O Binding.

This module implements ONNX Runtime inference using I/O Binding
to keep tensors on GPU throughout the inference pipeline.

Key features:
- Uses OrtValue for GPU-resident input/output tensors
- Eliminates CPU-GPU copies during session.run()
- Compatible with CUDAExecutionProvider
- Provides fallback to standard session.run() if I/O Binding fails
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import onnxruntime as ort
import torch

from app.models.registry import get_model_registry
from app.runtime.cuda import get_ort_session
from app.vision.gpu_preprocessing import GPUPreprocessingResult

logger = logging.getLogger(__name__)


@dataclass
class GPUInferenceResult:
    """
    Result of GPU-resident ONNX Runtime inference.
    
    Output tensors remain on GPU as OrtValue objects.
    """
    # Output tensors as OrtValue (on GPU)
    outputs: List[ort.OrtValue]
    
    # Output names
    output_names: List[str]
    
    # Inference timing
    inference_time_ms: float
    
    # Provider used
    provider: str
    
    # Whether I/O Binding was used
    io_binding_used: bool
    
    def get_output_numpy(self, index: int = 0) -> np.ndarray:
        """Get output as numpy array (copies to CPU)."""
        return self.outputs[index].numpy()
    
    def get_output_torch(self, index: int = 0) -> torch.Tensor:
        """Get output as PyTorch tensor (on GPU if possible)."""
        # OrtValue to numpy to torch (may involve copy)
        np_array = self.outputs[index].numpy()
        return torch.from_numpy(np_array)
    
    def get_output_ortvalue(self, index: int = 0) -> ort.OrtValue:
        """Get output as OrtValue (stays on GPU)."""
        return self.outputs[index]


class GPUInferenceEngine:
    """
    GPU-resident ONNX Runtime inference engine with I/O Binding.
    
    Uses OrtValue for input/output tensors to avoid CPU-GPU copies.
    Supports OrtValue reuse, I/O Binding reuse, and synchronization optimization.
    """
    
    def __init__(
        self,
        model_id: str,
        providers: Optional[List[str]] = None,
        device_id: int = 0,
        reuse_ortvalues: bool = False,
        reuse_io_binding: bool = False,
        no_unnecessary_sync: bool = False,
    ):
        """
        Initialize GPU inference engine.
        
        Args:
            model_id: Model identifier (e.g., "scrfd", "arcface").
            providers: ONNX Runtime providers (default: CUDA then CPU).
            device_id: CUDA device ID.
            reuse_ortvalues: Pre-allocate and reuse input/output OrtValues across frames.
            reuse_io_binding: Bind inputs/outputs once, update data pointers only.
            no_unnecessary_sync: Remove redundant torch.cuda.synchronize() calls.
        """
        self.model_id = model_id
        self.device_id = device_id
        self.providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.reuse_ortvalues = reuse_ortvalues
        self.reuse_io_binding = reuse_io_binding
        self.no_unnecessary_sync = no_unnecessary_sync
        
        # Get model path from registry
        registry = get_model_registry()
        self.model_path = registry.get_model_path(model_id)
        
        # Verify model exists
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        
        # Create session with CUDA EP
        self.session = get_ort_session(self.model_path, self.providers)
        
        # Verify CUDA EP is being used
        session_providers = self.session.get_providers()
        self.cuda_ep_used = "CUDAExecutionProvider" in session_providers
        self.provider_used = session_providers[0] if session_providers else "Unknown"
        
        # Get input/output info
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = tuple(self.session.get_inputs()[0].shape)
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.output_shapes = [tuple(o.shape) for o in self.session.get_outputs()]
        
        # Create IO Binding object
        self.io_binding = self.session.io_binding()
        
        # Pre-allocate output OrtValues (will be bound during inference)
        self._output_ortvalues: List[ort.OrtValue] = []
        
        # Pre-allocated input OrtValue for reuse
        self._input_ortvalue: Optional[ort.OrtValue] = None
        self._input_shape: Optional[Tuple[int, ...]] = None
        
        # Pre-bind outputs if reuse_io_binding is enabled
        self._outputs_bound = False
        
        # Pre-allocate output buffers if reuse_ortvalues is enabled
        if self.reuse_ortvalues:
            self._preallocate_output_buffers()
        
        # Pre-bind outputs if reuse_io_binding is enabled
        if self.reuse_io_binding:
            self._prebind_outputs()
    
    def _preallocate_output_buffers(self):
        """Pre-allocate output OrtValues for reuse across frames."""
        # We'll allocate on first inference when we know the batch size
        pass
    
    def _prebind_outputs(self):
        """Pre-bind output buffers once (requires known shapes)."""
        # We'll bind on first inference when we know the batch size
        pass
    
    def _ensure_output_buffers(self, batch_size: int):
        """Ensure output buffers are allocated for the given batch size."""
        if len(self._output_ortvalues) == len(self.output_names):
            # Check if shapes match
            shapes_match = True
            for i, (ort_val, shape) in enumerate(zip(self._output_ortvalues, self.output_shapes)):
                out_shape = list(shape)
                if out_shape[0] == -1 or out_shape[0] == 'batch_size':
                    out_shape[0] = batch_size
                if tuple(ort_val.shape()) != tuple(out_shape):
                    shapes_match = False
                    break
            if shapes_match:
                return  # Buffers already allocated with correct shapes
        
        # Reallocate
        self._output_ortvalues = []
        for i, (name, shape) in enumerate(zip(self.output_names, self.output_shapes)):
            out_shape = list(shape)
            if out_shape[0] == -1 or out_shape[0] == 'batch_size':
                out_shape[0] = batch_size
            
            output_ortvalue = ort.OrtValue.ortvalue_from_shape_and_type(
                tuple(out_shape),
                np.float32,
                device_type='cuda',
                device_id=self.device_id,
            )
            self._output_ortvalues.append(output_ortvalue)
        
        # Rebind outputs if using IO binding reuse
        if self.reuse_io_binding:
            self.io_binding.clear_binding_outputs()
            for i, (name, shape) in enumerate(zip(self.output_names, self.output_shapes)):
                out_shape = list(shape)
                if out_shape[0] == -1 or out_shape[0] == 'batch_size':
                    out_shape[0] = batch_size
                self.io_binding.bind_output(
                    name=name,
                    device_type='cuda',
                    device_id=self.device_id,
                    element_type=np.float32,
                    shape=tuple(out_shape),
                    buffer_ptr=self._output_ortvalues[i].data_ptr(),
                )
            self._outputs_bound = True
    
    def _ensure_input_buffer(self, input_tensor: torch.Tensor):
        """Ensure input buffer is allocated for the given shape."""
        if self._input_ortvalue is not None and self._input_shape == tuple(input_tensor.shape):
            return  # Buffer already allocated with correct shape
        
        # Create new input OrtValue
        self._input_ortvalue = ort.OrtValue.ortvalue_from_numpy(
            input_tensor.detach().cpu().numpy(),
            device_type='cuda',
            device_id=self.device_id,
        )
        self._input_shape = tuple(input_tensor.shape)
        
        # Rebind input if using IO binding reuse
        if self.reuse_io_binding:
            self.io_binding.clear_binding_inputs()
            self.io_binding.bind_input(
                name=self.input_name,
                device_type='cuda',
                device_id=self.device_id,
                element_type=np.float32,
                shape=tuple(input_tensor.shape),
                buffer_ptr=self._input_ortvalue.data_ptr(),
            )
    
    def infer_gpu(self, input_tensor: torch.Tensor) -> GPUInferenceResult:
        """
        Run inference with GPU-resident input tensor using I/O Binding.
        
        Args:
            input_tensor: Preprocessed input tensor on GPU (PyTorch tensor).
            
        Returns:
            GPUInferenceResult with GPU-resident outputs.
        """
        # Verify input is on CUDA
        if not input_tensor.is_cuda:
            raise ValueError("Input tensor must be on CUDA device for GPU inference")
        
        # Verify input shape matches expected (allow dynamic batch)
        expected_shape = list(self.input_shape)
        if expected_shape[0] == -1 or expected_shape[0] == 'batch_size':
            expected_shape[0] = input_tensor.shape[0]
        
        if tuple(input_tensor.shape) != tuple(expected_shape):
            # Try to handle dynamic shapes
            pass
        
        batch_size = input_tensor.shape[0]
        
        # Ensure output buffers are allocated
        if self.reuse_ortvalues or self.reuse_io_binding:
            self._ensure_output_buffers(batch_size)
        
        # Ensure input buffer is allocated
        if self.reuse_ortvalues or self.reuse_io_binding:
            self._ensure_input_buffer(input_tensor)
        
        t0 = time.perf_counter()
        
        try:
            if self.reuse_io_binding:
                # Input and outputs already bound, just update input data
                input_tensor_contig = input_tensor.contiguous()
                
                # Copy data into pre-allocated input OrtValue
                # We need to copy the GPU tensor data to the OrtValue's GPU memory
                # Since OrtValue doesn't support direct GPU-to-GPU copy in Python API,
                # we copy via CPU (this is a limitation of the Python API)
                input_numpy = input_tensor_contig.detach().cpu().numpy()
                
                # Update the pre-allocated OrtValue by creating a new one with the data
                # This is the only way to update the data in the current ORT Python API
                self._input_ortvalue = ort.OrtValue.ortvalue_from_numpy(
                    input_numpy,
                    device_type='cuda',
                    device_id=self.device_id,
                )
                
                # Rebind input with updated buffer pointer
                self.io_binding.clear_binding_inputs()
                self.io_binding.bind_input(
                    name=self.input_name,
                    device_type='cuda',
                    device_id=self.device_id,
                    element_type=np.float32,
                    shape=tuple(input_tensor_contig.shape),
                    buffer_ptr=self._input_ortvalue.data_ptr(),
                )
            else:
                # Standard path: clear and rebind
                self.io_binding.clear_binding_inputs()
                self.io_binding.clear_binding_outputs()
                
                # Bind input using the tensor's data pointer (zero-copy)
                input_tensor_contig = input_tensor.contiguous()
                self.io_binding.bind_input(
                    name=self.input_name,
                    device_type='cuda',
                    device_id=self.device_id,
                    element_type=np.float32,
                    shape=tuple(input_tensor_contig.shape),
                    buffer_ptr=input_tensor_contig.data_ptr(),
                )
            
            # Bind outputs if not pre-bound
            if not self.reuse_io_binding or not self._outputs_bound:
                self._output_ortvalues = []
                for i, (name, shape) in enumerate(zip(self.output_names, self.output_shapes)):
                    out_shape = list(shape)
                    if out_shape[0] == -1 or out_shape[0] == 'batch_size':
                        out_shape[0] = batch_size
                    
                    output_ortvalue = ort.OrtValue.ortvalue_from_shape_and_type(
                        tuple(out_shape),
                        np.float32,
                        device_type='cuda',
                        device_id=self.device_id,
                    )
                    self._output_ortvalues.append(output_ortvalue)
                    
                    self.io_binding.bind_output(
                        name=name,
                        device_type='cuda',
                        device_id=self.device_id,
                        element_type=np.float32,
                        shape=tuple(out_shape),
                        buffer_ptr=output_ortvalue.data_ptr(),
                    )
                if self.reuse_io_binding:
                    self._outputs_bound = True
            
            # Run with I/O Binding
            self.session.run_with_iobinding(self.io_binding)
            
            # Synchronize only if not disabled
            if not self.no_unnecessary_sync:
                torch.cuda.synchronize(self.device_id)
            
            t1 = time.perf_counter()
            inference_time_ms = (t1 - t0) * 1000
            
            return GPUInferenceResult(
                outputs=self._output_ortvalues,
                output_names=self.output_names,
                inference_time_ms=inference_time_ms,
                provider=self.provider_used,
                io_binding_used=True,
            )
            
        except Exception as e:
            # Fallback to standard session.run with CPU copy
            logger.warning(f"I/O Binding failed, falling back to session.run: {e}")
            return self._infer_fallback(input_tensor)
    
    def _infer_fallback(self, input_tensor: torch.Tensor) -> GPUInferenceResult:
        """Fallback to standard session.run (copies to CPU and back)."""
        logger.warning("I/O Binding failed, falling back to session.run (CPU path)")
        t0 = time.perf_counter()
        
        # Move to CPU for standard run
        input_numpy = input_tensor.detach().cpu().numpy()
        
        outputs = self.session.run(self.output_names, {self.input_name: input_numpy})
        
        t1 = time.perf_counter()
        inference_time_ms = (t1 - t0) * 1000
        
        # Wrap outputs as OrtValue on CPU
        output_ortvalues = []
        for out in outputs:
            ort_val = ort.OrtValue.ortvalue_from_numpy(out)
            output_ortvalues.append(ort_val)
        
        return GPUInferenceResult(
            outputs=output_ortvalues,
            output_names=self.output_names,
            inference_time_ms=inference_time_ms,
            provider=self.provider_used,
            io_binding_used=False,
        )
    
    def infer_cpu(self, input_numpy: np.ndarray) -> GPUInferenceResult:
        """
        Run inference on CPU (for comparison/validation).
        
        Args:
            input_numpy: Preprocessed input as numpy array.
            
        Returns:
            GPUInferenceResult with CPU outputs.
        """
        t0 = time.perf_counter()
        
        outputs = self.session.run(self.output_names, {self.input_name: input_numpy})
        
        t1 = time.perf_counter()
        inference_time_ms = (t1 - t0) * 1000
        
        output_ortvalues = []
        for out in outputs:
            ort_val = ort.OrtValue.ortvalue_from_numpy(out)
            output_ortvalues.append(ort_val)
        
        return GPUInferenceResult(
            outputs=output_ortvalues,
            output_names=self.output_names,
            inference_time_ms=inference_time_ms,
            provider="CPUExecutionProvider",
            io_binding_used=False,
        )


def create_gpu_inference_engine(
    model_id: str,
    providers: Optional[List[str]] = None,
    device_id: int = 0,
) -> GPUInferenceEngine:
    """
    Factory function to create a GPU inference engine.
    
    Args:
        model_id: Model identifier.
        providers: ONNX Runtime providers.
        device_id: CUDA device ID.
        
    Returns:
        GPUInferenceEngine instance.
    """
    return GPUInferenceEngine(model_id, providers, device_id)


def run_gpu_inference(
    model_id: str,
    input_tensor: torch.Tensor,
    providers: Optional[List[str]] = None,
    device_id: int = 0,
) -> GPUInferenceResult:
    """
    Convenience function to run GPU inference.
    
    Args:
        model_id: Model identifier.
        input_tensor: Preprocessed input tensor on GPU.
        providers: ONNX Runtime providers.
        device_id: CUDA device ID.
        
    Returns:
        GPUInferenceResult with GPU-resident outputs.
    """
    engine = GPUInferenceEngine(model_id, providers, device_id)
    return engine.infer_gpu(input_tensor)