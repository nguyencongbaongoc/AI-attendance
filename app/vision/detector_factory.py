"""
Phase 8 — Face Detector Factory.

Provides a single entry point to create face detector adapters.
Downstream code uses this factory, not specific adapter classes.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from app.vision.detector_contract import (
    FaceDetectorInterface,
    DetectorModelId,
    DetectorStatus,
)
from app.vision.scrfd_adapter import SCRFDAdapter, create_scrfd_adapter
from app.vision.retinaface_adapter import RetinaFaceAdapter, create_retinaface_adapter, RetinaFaceNotImplementedError
from app.vision.detection import create_face_detector as create_cpu_face_detector
from app.vision.gpu_face_detector import create_gpu_face_detector, GPUFaceDetectorConfig

logger = logging.getLogger(__name__)


def get_detector(
    model_id: str = "scrfd",
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
) -> FaceDetectorInterface:
    """
    Get a face detector adapter by model ID.
    
    This is the single entry point for creating face detectors.
    Downstream code should use this function, not import specific adapters.
    
    Args:
        model_id: Detector model identifier ("scrfd" or "retinaface").
        confidence_threshold: Override confidence threshold.
        nms_threshold: Override NMS threshold.
        providers: ONNX Runtime providers.
        
    Returns:
        FaceDetectorInterface implementation.
        
    Raises:
        ValueError: If model_id is not supported.
        RetinaFaceNotImplementedError: If RetinaFace is requested (not yet implemented).
    """
    if model_id == DetectorModelId.SCRFD.value:
        return create_scrfd_adapter(
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            providers=providers,
        )
    elif model_id == DetectorModelId.RETINAFACE.value:
        # Fail explicitly - do not return a placeholder that silently fails later
        raise RetinaFaceNotImplementedError(
            "RetinaFace detector is not yet implemented. "
            "Use 'scrfd' for active face detection. "
            "RetinaFace will be implemented in a future phase."
        )
    else:
        raise ValueError(
            f"Unsupported detector model_id: '{model_id}'. "
            f"Supported: {[m.value for m in DetectorModelId]}"
        )


def get_detector_for_live(
    model_id: str = "scrfd",
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
    use_gpu: Optional[bool] = None,
):
    """
    Get a face detector for LIVE production processing.
    
    Automatically selects GPU or CPU path based on:
    1. use_gpu parameter (if explicitly set)
    2. CLINE_USE_GPU_DETECTOR environment variable
    3. Default: GPU if available, else CPU
    
    Args:
        model_id: Detector model identifier.
        confidence_threshold: Override confidence threshold.
        nms_threshold: Override NMS threshold.
        providers: ONNX Runtime providers.
        use_gpu: Force GPU (True) or CPU (False). If None, detect automatically.
        
    Returns:
        GPU or CPU face detector implementation.
    """
    # Determine whether to use GPU
    if use_gpu is None:
        use_gpu = os.getenv("CLINE_USE_GPU_DETECTOR", "true").lower() == "true"
    
    if use_gpu:
        try:
            logger.info("Attempting GPU detector initialization for live path (Phase 36L optimized)")
            detector = create_gpu_face_detector(
                model_id=model_id,
                confidence_threshold=confidence_threshold,
                nms_threshold=nms_threshold,
                providers=providers,
                device_id=0,
                enable_gpu_path=True,
                fallback_to_cpu=True,
                # Phase 36L optimizations (validated in accuracy/performance tests)
                precompute_anchors=True,
                vectorized_decode=True,
                reuse_ortvalues=True,
                reuse_io_binding=True,
                no_unnecessary_sync=True,
            )
            logger.info(f"GPU detector initialized (gpu_available={detector.gpu_available})")
            return detector
        except Exception as e:
            logger.warning(f"GPU detector initialization failed, falling back to CPU: {e}")
            # Fall through to CPU detector
    
    # CPU fallback or explicit CPU request
    logger.info("Using CPU detector for live path")
    return create_cpu_face_detector(
        model_id=model_id,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        providers=providers,
    )


def list_available_detectors() -> List[dict]:
    """
    List all available detector backends with their status.
    
    Returns:
        List of dicts with model_id, status, and description.
    """
    return [
        {
            "model_id": DetectorModelId.SCRFD.value,
            "status": DetectorStatus.ACTIVE.value,
            "description": "SCRFD 10G face detector (640x640 input, 5 keypoints)",
            "input_size": "640x640",
        },
        {
            "model_id": DetectorModelId.RETINAFACE.value,
            "status": DetectorStatus.NOT_IMPLEMENTED.value,
            "description": "RetinaFace detector (placeholder - not yet implemented)",
            "input_size": "TBD",
        },
    ]


def get_detector_status(model_id: str) -> DetectorStatus:
    """
    Get the implementation status of a detector.
    
    Args:
        model_id: Detector model identifier.
        
    Returns:
        DetectorStatus enum value.
    """
    if model_id == DetectorModelId.SCRFD.value:
        return DetectorStatus.ACTIVE
    elif model_id == DetectorModelId.RETINAFACE.value:
        return DetectorStatus.NOT_IMPLEMENTED
    else:
        raise ValueError(f"Unknown detector model_id: '{model_id}'")