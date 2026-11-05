"""
Phase 20 — Unified Preprocessing Pipeline.

Provides standardized preprocessing for model inputs across the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import cv2

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.data.contracts import ModelPreprocessingContract, get_model_contract


@dataclass
class PreprocessingResult:
    """Result of preprocessing operation."""
    # Preprocessed tensor ready for model input
    tensor: np.ndarray  # Shape: (C, H, W) or (1, C, H, W) for batched
    
    # Original frame info
    original_shape: Tuple[int, int]  # (H, W)
    original_dtype: str
    
    # Preprocessing parameters applied
    scale: float = 1.0
    padding: Tuple[int, int, int, int] = (0, 0, 0, 0)  # top, bottom, left, right
    crop_box: Optional[Tuple[int, int, int, int]] = None  # x, y, w, h
    
    # Metadata
    model_id: str = ""
    preprocessing_time_ms: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)
    
    # Compatibility aliases for GPU preprocessing result interface
    @property
    def scale_factor(self) -> float:
        """Alias for scale (GPU compatibility)."""
        return self.scale
    
    @property
    def padding_applied(self) -> Tuple[int, int, int, int]:
        """Alias for padding (GPU compatibility)."""
        return self.padding
    
    @property
    def frame_index(self) -> int:
        """Get frame_index from extra (GPU compatibility)."""
        return self.extra.get("frame_index", 0)
    
    @property
    def source_id(self) -> str:
        """Get source_id from extra (GPU compatibility)."""
        return self.extra.get("source_id", "")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes tensor data)."""
        return {
            "tensor_shape": self.tensor.shape,
            "tensor_dtype": str(self.tensor.dtype),
            "original_shape": self.original_shape,
            "original_dtype": self.original_dtype,
            "scale": self.scale,
            "padding": self.padding,
            "crop_box": self.crop_box,
            "model_id": self.model_id,
            "preprocessing_time_ms": self.preprocessing_time_ms,
            "extra": self.extra,
            "conversions": {},
        }


class UnifiedPreprocessor:
    """
    Unified preprocessor for all model types.
    
    Handles:
    - Resize with aspect ratio preservation (letterbox)
    - Center crop
    - Normalization (mean/std)
    - Format conversion (BGR->RGB, HWC->CHW)
    - Batch dimension handling
    """
    
    def __init__(self, contract: Optional[ModelPreprocessingContract] = None, model_id: Optional[str] = None):
        """
        Initialize preprocessor.
        
        Args:
            contract: Explicit preprocessing contract
            model_id: Model ID to look up contract from registry
        """
        # Handle case where first positional argument is a model_id string
        if contract is not None and isinstance(contract, str):
            # First positional argument is a model_id string
            model_id = contract
            contract = None
        
        if contract is not None:
            self.contract = contract
            self.model_id = contract.model_id
        elif model_id is not None:
            model_contract = get_model_contract(model_id)
            if model_contract is None or model_contract.preprocessing is None:
                raise ValueError(f"No preprocessing contract found for model: {model_id}")
            self.contract = model_contract.preprocessing
            self.model_id = model_id
        else:
            raise ValueError("Either contract or model_id must be provided")
    
    def preprocess(self, frame: CanonicalFrame) -> PreprocessingResult:
        """
        Preprocess a frame according to the model contract.
        
        Args:
            frame: CanonicalFrame to preprocess
            
        Returns:
            PreprocessingResult with tensor and metadata
        """
        import time
        start_time = time.perf_counter()
        
        # Get frame data
        img = frame.data
        original_shape = (img.shape[0], img.shape[1])
        original_dtype = str(img.dtype)
        
        # Convert color format if needed
        img = self._convert_color_format(img, getattr(frame.metadata, "pixel_format", None))
        
        # Resize with aspect ratio preservation
        img, scale, padding = self._resize_with_padding(img)
        
        # Normalize
        img = self._normalize(img)
        
        # Convert to CHW format
        img = self._to_chw(img)
        
        # Add batch dimension
        tensor = img[np.newaxis, ...].astype(self.contract.input_dtype)
        
        preprocessing_time_ms = (time.perf_counter() - start_time) * 1000
        
        return PreprocessingResult(
            tensor=tensor,
            original_shape=original_shape,
            original_dtype=original_dtype,
            scale=scale,
            padding=padding,
            model_id=self.model_id,
            preprocessing_time_ms=preprocessing_time_ms,
            extra={
                "frame_index": frame.metadata.frame_index,
                "source_id": frame.metadata.source_id,
            }
        )
    
    def _convert_color_format(self, img: np.ndarray, source_format: Optional[Any] = None) -> np.ndarray:
        """Convert image to target color format based on source format."""
        target_format = self.contract.input_format.upper()
        source_str = (
            str(source_format.value if hasattr(source_format, "value") else source_format).upper()
            if source_format is not None
            else "BGR"
        )
        
        if "RGB" in source_str:
            if target_format == "BGR" and img.ndim == 3 and img.shape[2] == 3:
                return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif target_format == "GRAY" and img.ndim == 3:
                return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            return img
        else:
            if target_format == "RGB" and img.ndim == 3 and img.shape[2] == 3:
                return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            elif target_format == "GRAY" and img.ndim == 3:
                return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return img
    
    def _resize_with_padding(self, img: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int, int, int]]:
        """
        Resize image with aspect ratio preservation (letterbox).
        
        Returns:
            (resized_image, scale, padding)
            padding = (top, bottom, left, right)
        """
        target_h, target_w = self.contract.input_shape[1], self.contract.input_shape[2]
        h, w = img.shape[:2]
        
        if self.contract.resize_mode == "letterbox" and self.contract.keep_aspect_ratio:
            # Calculate scale to fit within target while preserving aspect ratio
            scale = min(target_w / w, target_h / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            # Resize
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            
            # Calculate padding
            pad_top = (target_h - new_h) // 2
            pad_bottom = target_h - new_h - pad_top
            pad_left = (target_w - new_w) // 2
            pad_right = target_w - new_w - pad_left
            
            # Apply padding
            padded = cv2.copyMakeBorder(
                resized, pad_top, pad_bottom, pad_left, pad_right,
                cv2.BORDER_CONSTANT, value=(114, 114, 114)  # Gray padding
            )
            
            return padded, scale, (pad_top, pad_bottom, pad_left, pad_right)
        
        elif self.contract.resize_mode == "crop":
            # Resize to cover target, then center crop
            scale = max(target_w / w, target_h / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            
            # Center crop
            start_x = (new_w - target_w) // 2
            start_y = (new_h - target_h) // 2
            cropped = resized[start_y:start_y + target_h, start_x:start_x + target_w]
            
            return cropped, scale, (0, 0, 0, 0)
        
        else:
            # Stretch to target
            resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            scale_w = target_w / w
            scale_h = target_h / h
            return resized, min(scale_w, scale_h), (0, 0, 0, 0)
    
    def _normalize(self, img: np.ndarray) -> np.ndarray:
        """
        Normalize image using mean and std.
        
        Contract: input_range describes the *expected* pixel range BEFORE
        mean/std normalization (e.g. (0.0, 1.0) for SCRFD-style ImageNet
        preprocessing). Source pixel data is always uint8 / [0, 255] when
        it comes from a video frame, so the [0, 255] -> [0, 1] conversion
        is derived from the *dtype* of the input, not from input_range.
        
        Rules:
          * integer dtype (e.g. uint8)            -> divide by 255.0 first
          * float dtype  and input_max > 1.0      -> divide by 255.0
          * float dtype  and input_max <= 1.0     -> already in [0, 1],
                                                      do NOT divide again
        This prevents the previous bug where SCRFD (input_range=(0,1))
        skipped the /255 step and produced ~500-scale inputs that caused
        garbage false-positive detections.
        """
        original_dtype = img.dtype
        # Convert to float32
        if img.dtype != np.float32:
            img = img.astype(np.float32)
        
        # Scale to [0, 1] if needed. Use dtype as the primary signal so
        # uint8 source frames are always scaled regardless of contract.
        input_min, input_max = self.contract.input_range
        is_integer_source = not np.issubdtype(original_dtype, np.floating)
        needs_scale_to_unit = is_integer_source or (input_max > 1.0)
        if needs_scale_to_unit:
            img = img / 255.0
        
        # Apply mean/std normalization
        mean = np.array(self.contract.mean, dtype=np.float32).reshape(1, 1, 3)
        std = np.array(self.contract.std, dtype=np.float32).reshape(1, 1, 3)
        
        img = (img - mean) / std
        
        return img
    
    def _to_chw(self, img: np.ndarray) -> np.ndarray:
        """Convert HWC to CHW format."""
        if img.ndim == 3:
            return np.transpose(img, (2, 0, 1))
        elif img.ndim == 2:
            # Grayscale: add channel dimension
            return img[np.newaxis, ...]
        return img
    
    def preprocess_batch(self, frames: List[CanonicalFrame]) -> List[PreprocessingResult]:
        """Preprocess a batch of frames."""
        return [self.preprocess(frame) for frame in frames]


def create_preprocessor(model_id: str) -> UnifiedPreprocessor:
    """Factory function to create a preprocessor for a model."""
    return UnifiedPreprocessor(model_id=model_id)


def preprocess_frame(frame: CanonicalFrame, model_id: str) -> PreprocessingResult:
    """Convenience function to preprocess a single frame with a model."""
    preprocessor = create_preprocessor(model_id)
    return preprocessor.preprocess(frame)