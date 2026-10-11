"""
Phase 8 — RetinaFace Detector Placeholder.

This module defines the adapter boundary for RetinaFace so that it can
be added later without changing downstream code.

IMPORTANT:
- This is a PLACEHOLDER only.
- It does NOT perform detection.
- It fails explicitly with a clear "not implemented" state.
- It does NOT silently fall back to SCRFD.
"""

from __future__ import annotations

from typing import List, Optional

from app.data.frame import CanonicalFrame
from app.data.contracts import ModelPreprocessingContract
from app.vision.detector_contract import (
    FaceDetectionContract,
    FaceDetectorInterface,
    DetectorModelId,
    DetectorStatus,
)


class RetinaFaceNotImplementedError(NotImplementedError):
    """Raised when RetinaFace detection is attempted but not yet implemented."""
    
    def __init__(self, message: str = "RetinaFace detector is not yet implemented"):
        super().__init__(message)


class RetinaFaceAdapter(FaceDetectorInterface):
    """
    RetinaFace detector placeholder implementing FaceDetectorInterface.
    
    This adapter defines the boundary for future RetinaFace integration.
    It does NOT perform any detection and will raise
    RetinaFaceNotImplementedError if detect() is called.
    
    Future implementation will:
    - Define its own preprocessing contract (may differ from SCRFD 640x640)
    - Implement detect() to return FaceDetectionContract objects
    - Preserve bbox, confidence, 5-point landmarks, coordinate space, provenance
    """
    
    # Placeholder model identity
    _PLACEHOLDER_MODEL_ID = "retinaface"
    _PLACEHOLDER_MODEL_VERSION = "0.0.0-placeholder"
    _PLACEHOLDER_MODEL_SHA256 = ""
    
    def __init__(
        self,
        confidence_threshold: Optional[float] = None,
        nms_threshold: Optional[float] = None,
        providers: Optional[List[str]] = None,
    ):
        """
        Initialize the RetinaFace placeholder.
        
        This does NOT load any model or create any session.
        It only stores configuration for future use.
        
        Args:
            confidence_threshold: Future confidence threshold override.
            nms_threshold: Future NMS threshold override.
            providers: Future ONNX Runtime providers.
        """
        self._confidence_threshold = confidence_threshold
        self._nms_threshold = nms_threshold
        self._providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
    
    @property
    def model_id(self) -> str:
        """Get the detector model identifier."""
        return self._PLACEHOLDER_MODEL_ID
    
    @property
    def model_version(self) -> str:
        """Get the detector model version."""
        return self._PLACEHOLDER_MODEL_VERSION
    
    @property
    def model_sha256(self) -> str:
        """Get the detector model SHA256 hash."""
        return self._PLACEHOLDER_MODEL_SHA256
    
    @property
    def status(self) -> DetectorStatus:
        """Get the detector implementation status."""
        return DetectorStatus.NOT_IMPLEMENTED
    
    @property
    def preprocessing_contract(self) -> ModelPreprocessingContract:
        """
        Get the RetinaFace preprocessing contract.
        
        Raises:
            RetinaFaceNotImplementedError: RetinaFace contract not yet defined.
        """
        raise RetinaFaceNotImplementedError(
            "RetinaFace preprocessing contract is not yet defined. "
            "Future implementation will define its own input size and preprocessing."
        )
    
    def detect(self, frame: CanonicalFrame) -> List[FaceDetectionContract]:
        """
        Detect faces using RetinaFace.
        
        This is a placeholder and does NOT perform detection.
        
        Raises:
            RetinaFaceNotImplementedError: Always raised - RetinaFace not yet implemented.
        """
        raise RetinaFaceNotImplementedError(
            "RetinaFace detect() is not implemented. "
            "Use SCRFDAdapter for active face detection. "
            "RetinaFace will be implemented in a future phase."
        )
    
    def cleanup(self) -> None:
        """Release RetinaFace resources (no-op for placeholder)."""
        pass


def create_retinaface_adapter(
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
) -> RetinaFaceAdapter:
    """
    Factory function to create a RetinaFace placeholder adapter.
    
    Args:
        confidence_threshold: Future confidence threshold override.
        nms_threshold: Future NMS threshold override.
        providers: Future ONNX Runtime providers.
        
    Returns:
        RetinaFaceAdapter placeholder instance.
    """
    return RetinaFaceAdapter(
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        providers=providers,
    )