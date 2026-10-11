"""
Phase 12 — ArcFace Normal Face Recognition Inference.

Implements model-independent ArcFace inference using ONNX Runtime.
Resolves glintr100.onnx exclusively through ModelRegistry.

This module does NOT implement identity matching.
This module does NOT access cameras.
This module does NOT implement attendance or IN/OUT.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import onnxruntime as ort

from app.models.registry import get_model_registry, ModelRegistry
from app.vision.recognition_contract import (
    ArcFaceInputContract,
    ArcFaceOutputContract,
    ArcFaceInferenceResult,
    get_arcface_input_contract,
    get_arcface_output_contract,
)


@dataclass(frozen=True)
class ArcFaceInferenceConfig:
    """Configuration for ArcFace inference."""
    
    # Model registry
    registry: ModelRegistry
    
    # Execution providers (in order of preference)
    providers: Tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider")
    
    # Session options
    enable_mem_pattern: bool = True
    enable_cpu_mem_arena: bool = True
    graph_optimization_level: int = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    # Validation
    validate_input: bool = True
    validate_output: bool = True


class ArcFaceInference:
    """
    ArcFace face recognition inference engine.
    
    Uses ModelRegistry to resolve glintr100.onnx.
    Provides deterministic, validated inference with CUDA/CPU support.
    """
    
    def __init__(self, config: Optional[ArcFaceInferenceConfig] = None):
        """
        Initialize ArcFace inference engine.
        
        Args:
            config: Inference configuration. If None, uses defaults with global registry.
        """
        if config is None:
            config = ArcFaceInferenceConfig(registry=get_model_registry())
        
        self.config = config
        self.registry = config.registry
        self.input_contract = get_arcface_input_contract()
        self.output_contract = get_arcface_output_contract()
        
        # Resolve model through registry
        self.model_def = self.registry.get("arcface")
        self.model_path = self.registry.get_model_path("arcface")
        
        # Verify model exists
        if not self.model_path.exists():
            raise FileNotFoundError(f"ArcFace model not found at {self.model_path}")
        
        # Verify SHA256
        hash_result = self.registry.verify_model("arcface")
        if not hash_result.is_verified():
            raise ValueError(f"ArcFace model SHA256 verification failed: {hash_result.status}")
        
        # Create ONNX Runtime session
        self.session = self._create_session()
        self.provider_used = self._get_provider_used()
        
        # Get input/output names
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
    
    def _create_session(self) -> ort.InferenceSession:
        """Create ONNX Runtime inference session."""
        session_options = ort.SessionOptions()
        session_options.enable_mem_pattern = self.config.enable_mem_pattern
        session_options.enable_cpu_mem_arena = self.config.enable_cpu_mem_arena
        session_options.graph_optimization_level = self.config.graph_optimization_level
        
        session = ort.InferenceSession(
            str(self.model_path),
            sess_options=session_options,
            providers=list(self.config.providers),
        )
        
        return session
    
    def _get_provider_used(self) -> str:
        """Get the actual provider being used by the session."""
        providers = self.session.get_providers()
        if "CUDAExecutionProvider" in providers:
            return "CUDAExecutionProvider"
        elif "CPUExecutionProvider" in providers:
            return "CPUExecutionProvider"
        else:
            return providers[0] if providers else "Unknown"
    
    def preprocess(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        """
        Preprocess aligned face image to ArcFace input tensor.
        
        Args:
            aligned_face_bgr: Aligned face image in BGR format, shape (112, 112, 3), uint8
            
        Returns:
            Preprocessed tensor of shape (1, 3, 112, 112), float32
        """
        return self.input_contract.preprocess(aligned_face_bgr)
    
    def infer_raw(self, preprocessed_tensor: np.ndarray) -> np.ndarray:
        """
        Run raw ArcFace inference (without L2 normalization).
        
        Args:
            preprocessed_tensor: Preprocessed input tensor of shape (1, 3, 112, 112), float32
            
        Returns:
            Raw embedding of shape (1, 512) or (512,), float32
        """
        # Validate input if enabled
        if self.config.validate_input:
            is_valid, error = self.input_contract.validate_input(preprocessed_tensor)
            if not is_valid:
                raise ValueError(f"Input validation failed: {error}")
        
        # Run inference
        t0 = time.perf_counter()
        outputs = self.session.run(self.output_names, {self.input_name: preprocessed_tensor})
        t1 = time.perf_counter()
        
        inference_time_ms = (t1 - t0) * 1000
        
        # Get raw embedding (first output)
        raw_embedding = outputs[0]
        
        # Ensure shape is (1, 512)
        if raw_embedding.ndim == 1:
            raw_embedding = raw_embedding.reshape(1, -1)
        
        # Validate output if enabled
        if self.config.validate_output:
            is_valid, error = self.output_contract.validate_output(raw_embedding)
            if not is_valid:
                raise ValueError(f"Output validation failed: {error}")
        
        return raw_embedding, inference_time_ms
    
    def l2_normalize(self, embedding: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Apply L2 normalization to embedding.
        
        Args:
            embedding: Raw embedding of shape (1, 512) or (512,)
            
        Returns:
            Tuple of (normalized_embedding, raw_norm)
        """
        # Flatten to 1D for norm calculation
        flat_embedding = embedding.flatten()
        
        # Compute L2 norm
        raw_norm = float(np.linalg.norm(flat_embedding))
        
        # Avoid division by zero
        if raw_norm == 0.0:
            raise ValueError("Cannot normalize zero-norm embedding")
        
        # Normalize
        normalized = flat_embedding / raw_norm
        
        # Reshape to (1, 512)
        normalized = normalized.reshape(1, -1)
        
        return normalized, raw_norm
    
    def infer(self, aligned_face_bgr: np.ndarray) -> ArcFaceInferenceResult:
        """
        Complete ArcFace inference pipeline: preprocess -> infer -> L2 normalize.
        
        Args:
            aligned_face_bgr: Aligned face image in BGR format, shape (112, 112, 3), uint8
            
        Returns:
            ArcFaceInferenceResult with raw and normalized embeddings
        """
        # Preprocess
        preprocessed = self.preprocess(aligned_face_bgr)
        
        # Raw inference
        raw_embedding, inference_time_ms = self.infer_raw(preprocessed)
        
        # L2 normalize
        normalized_embedding, raw_norm = self.l2_normalize(raw_embedding)
        
        # Validate normalized output
        if self.config.validate_output:
            is_valid, error = self.output_contract.validate_output(normalized_embedding)
            if not is_valid:
                raise ValueError(f"Normalized output validation failed: {error}")
            
            # Verify norm ≈ 1.0
            norm_check = np.linalg.norm(normalized_embedding.flatten())
            if not np.isclose(norm_check, 1.0, rtol=1e-5):
                raise ValueError(f"L2 normalization failed: norm = {norm_check}, expected ≈ 1.0")
        
        return ArcFaceInferenceResult(
            raw_embedding=raw_embedding,
            normalized_embedding=normalized_embedding,
            raw_norm=raw_norm,
            input_shape=preprocessed.shape,
            output_shape=normalized_embedding.shape,
            inference_time_ms=inference_time_ms,
            provider=self.provider_used,
        )
    
    def infer_batch(self, aligned_faces_bgr: List[np.ndarray]) -> List[ArcFaceInferenceResult]:
        """
        Run inference on a batch of aligned faces.
        
        Args:
            aligned_faces_bgr: List of aligned face images in BGR format
            
        Returns:
            List of ArcFaceInferenceResult
        """
        results = []
        for face in aligned_faces_bgr:
            result = self.infer(face)
            results.append(result)
        return results


def create_arcface_inference(
    providers: Optional[List[str]] = None,
    registry: Optional[ModelRegistry] = None,
) -> ArcFaceInference:
    """
    Factory function to create ArcFace inference engine.
    
    Args:
        providers: Execution providers (default: CUDA then CPU)
        registry: Model registry instance (default: global registry)
        
    Returns:
        Configured ArcFaceInference instance
    """
    if registry is None:
        registry = get_model_registry()
    
    if providers is None:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    
    config = ArcFaceInferenceConfig(
        registry=registry,
        providers=tuple(providers),
    )
    
    return ArcFaceInference(config)


def run_arcface_inference_cpu_only(
    aligned_face_bgr: np.ndarray,
    registry: Optional[ModelRegistry] = None,
) -> ArcFaceInferenceResult:
    """
    Convenience function to run ArcFace inference on CPU only.
    
    Args:
        aligned_face_bgr: Aligned face image in BGR format
        registry: Model registry instance
        
    Returns:
        ArcFaceInferenceResult
    """
    inference = create_arcface_inference(providers=["CPUExecutionProvider"], registry=registry)
    return inference.infer(aligned_face_bgr)


def run_arcface_inference_cuda(
    aligned_face_bgr: np.ndarray,
    registry: Optional[ModelRegistry] = None,
) -> ArcFaceInferenceResult:
    """
    Convenience function to run ArcFace inference with CUDA (falls back to CPU).
    
    Args:
        aligned_face_bgr: Aligned face image in BGR format
        registry: Model registry instance
        
    Returns:
        ArcFaceInferenceResult
    """
    inference = create_arcface_inference(
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        registry=registry,
    )
    return inference.infer(aligned_face_bgr)