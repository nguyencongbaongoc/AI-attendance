"""
Phase 12 — ArcFace Normal Face Recognition Contract.

Defines the model-independent contract for ArcFace face recognition inference.
This module does NOT perform inference.
This module does NOT access cameras.
This module does NOT implement identity matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class ArcFaceInputContract:
    """
    ArcFace input contract - explicit and deterministic.
    
    Shape: (1, 3, 112, 112) - NCHW format
    Dtype: float32
    Color: RGB (explicit convention)
    Normalization: (x - 127.5) / 128.0  ->  [-1, 1] range
    """
    
    # Input tensor specification
    batch_size: int = 1
    channels: int = 3
    height: int = 112
    width: int = 112
    
    # Data specification
    dtype: np.dtype = np.float32
    channel_order: str = "RGB"  # Explicit: RGB, not BGR
    
    # Normalization: explicit and deterministic
    # ArcFace standard: (pixel - 127.5) / 128.0
    normalization_mean: Tuple[float, float, float] = (127.5, 127.5, 127.5)
    normalization_std: Tuple[float, float, float] = (128.0, 128.0, 128.0)
    
    def get_input_shape(self) -> Tuple[int, int, int, int]:
        """Get input shape as (N, C, H, W)."""
        return (self.batch_size, self.channels, self.height, self.width)
    
    def validate_input(self, tensor: np.ndarray) -> Tuple[bool, Optional[str]]:
        """
        Validate input tensor against contract.
        
        Returns:
            (is_valid, error_message)
        """
        # Check shape
        expected_shape = self.get_input_shape()
        if tensor.shape != expected_shape:
            return False, f"Shape mismatch: expected {expected_shape}, got {tensor.shape}"
        
        # Check dtype
        if tensor.dtype != self.dtype:
            return False, f"Dtype mismatch: expected {self.dtype}, got {tensor.dtype}"
        
        # Check for NaN/Inf
        if np.isnan(tensor).any():
            return False, "Input contains NaN values"
        if np.isinf(tensor).any():
            return False, "Input contains Inf values"
        
        # Check finite
        if not np.isfinite(tensor).all():
            return False, "Input contains non-finite values"
        
        return True, None
    
    def preprocess(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        """
        Preprocess aligned face image to ArcFace input tensor.
        
        Args:
            aligned_face_bgr: Aligned face image in BGR format, shape (112, 112, 3), uint8
            
        Returns:
            Preprocessed tensor of shape (1, 3, 112, 112), float32, normalized to [-1, 1]
        """
        # Validate input image
        if aligned_face_bgr.shape != (self.height, self.width, self.channels):
            raise ValueError(f"Expected aligned face shape (112, 112, 3), got {aligned_face_bgr.shape}")
        
        if aligned_face_bgr.dtype != np.uint8:
            raise ValueError(f"Expected uint8 input, got {aligned_face_bgr.dtype}")
        
        # Convert BGR to RGB (explicit convention)
        aligned_face_rgb = aligned_face_bgr[:, :, ::-1].copy()
        
        # Convert to float32
        tensor = aligned_face_rgb.astype(np.float32)
        
        # Normalize: (x - 127.5) / 128.0 -> [-1, 1]
        mean = np.array(self.normalization_mean, dtype=np.float32).reshape(1, 1, 3)
        std = np.array(self.normalization_std, dtype=np.float32).reshape(1, 1, 3)
        tensor = (tensor - mean) / std
        
        # Transpose to NCHW: (H, W, C) -> (1, C, H, W)
        tensor = np.transpose(tensor, (2, 0, 1))  # (C, H, W)
        tensor = np.expand_dims(tensor, axis=0)    # (1, C, H, W)
        
        # Final validation
        is_valid, error = self.validate_input(tensor)
        if not is_valid:
            raise ValueError(f"Preprocessed tensor validation failed: {error}")
        
        return tensor


@dataclass(frozen=True)
class ArcFaceOutputContract:
    """
    ArcFace output contract.
    
    Output: 512D embedding vector
    Shape: (1, 512) or (512,)
    Dtype: float32
    Post-processing: L2 normalization (norm ≈ 1.0)
    """
    
    embedding_dimension: int = 512
    output_dtype: np.dtype = np.float32
    
    def get_output_shape(self, batch_size: int = 1) -> Tuple[int, ...]:
        """Get expected output shape."""
        return (batch_size, self.embedding_dimension)
    
    def validate_output(self, embedding: np.ndarray) -> Tuple[bool, Optional[str]]:
        """
        Validate output embedding against contract.
        
        Returns:
            (is_valid, error_message)
        """
        # Check shape - accept both (1, 512) and (512,)
        if embedding.ndim == 2:
            if embedding.shape != (1, self.embedding_dimension):
                return False, f"Shape mismatch: expected (1, 512), got {embedding.shape}"
        elif embedding.ndim == 1:
            if embedding.shape != (self.embedding_dimension,):
                return False, f"Shape mismatch: expected (512,), got {embedding.shape}"
        else:
            return False, f"Unexpected embedding dimensions: {embedding.ndim}"
        
        # Check dtype
        if embedding.dtype != self.output_dtype:
            return False, f"Dtype mismatch: expected {self.output_dtype}, got {embedding.dtype}"
        
        # Check for NaN/Inf
        if np.isnan(embedding).any():
            return False, "Embedding contains NaN values"
        if np.isinf(embedding).any():
            return False, "Embedding contains Inf values"
        
        # Check finite
        if not np.isfinite(embedding).all():
            return False, "Embedding contains non-finite values"
        
        return True, None


@dataclass(frozen=True)
class ArcFaceInferenceResult:
    """Result of ArcFace inference."""
    
    # Raw embedding from model (before L2 norm)
    raw_embedding: np.ndarray
    
    # L2 normalized embedding
    normalized_embedding: np.ndarray
    
    # L2 norm of raw embedding
    raw_norm: float
    
    # Inference metadata
    input_shape: Tuple[int, ...]
    output_shape: Tuple[int, ...]
    inference_time_ms: float
    provider: str  # "CUDAExecutionProvider" or "CPUExecutionProvider"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "raw_embedding": self.raw_embedding.tolist(),
            "normalized_embedding": self.normalized_embedding.tolist(),
            "raw_norm": self.raw_norm,
            "input_shape": self.input_shape,
            "output_shape": self.output_shape,
            "inference_time_ms": self.inference_time_ms,
            "provider": self.provider,
        }


# Global contract instances (singleton pattern for consistency)
ARC_FACE_INPUT_CONTRACT = ArcFaceInputContract()
ARC_FACE_OUTPUT_CONTRACT = ArcFaceOutputContract()


def get_arcface_input_contract() -> ArcFaceInputContract:
    """Get the global ArcFace input contract."""
    return ARC_FACE_INPUT_CONTRACT


def get_arcface_output_contract() -> ArcFaceOutputContract:
    """Get the global ArcFace output contract."""
    return ARC_FACE_OUTPUT_CONTRACT