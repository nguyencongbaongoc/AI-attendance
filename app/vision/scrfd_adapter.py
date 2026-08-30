"""
Phase 8 — SCRFD Face Detector Adapter.

This adapter wraps the existing SCRFD FaceDetector implementation behind
the model-independent FaceDetectorInterface.

IMPORTANT:
- This does NOT rewrite SCRFD inference.
- This does NOT fix Phase 7R.3 SCRFD technical debt.
- Only minimum changes to expose SCRFD through the common interface.
- SCRFD remains configured at 640x640.
- Existing ModelRegistry identity and SHA256 verification are preserved.
"""

from __future__ import annotations

from typing import List, Optional

from app.data.frame import CanonicalFrame
from app.data.contracts import ModelPreprocessingContract, get_model_contract
from app.vision.detector_contract import (
    FaceDetectionContract,
    FaceDetectorInterface,
    DetectorModelId,
    DetectorStatus,
    DetectorProvenance,
    create_detector_provenance,
)
from app.vision.detection import FaceDetector as SCRFDCoreDetector, FaceDetection


class SCRFDAdapter(FaceDetectorInterface):
    """
    SCRFD detector adapter implementing FaceDetectorInterface.
    
    This adapter wraps the existing SCRFD FaceDetector (app.vision.detection.FaceDetector)
    and converts its SCRFD-specific FaceDetection outputs into the model-independent
    FaceDetectionContract format.
    
    The adapter preserves:
    - bbox (in original frame coordinates)
    - confidence
    - 5-point landmarks (in original frame coordinates)
    - coordinate space (always original_frame)
    - provenance (source frame, detector model identity)
    - model identity (model_id, version, sha256)
    """
    
    def __init__(
        self,
        confidence_threshold: Optional[float] = None,
        nms_threshold: Optional[float] = None,
        providers: Optional[List[str]] = None,
    ):
        """
        Initialize the SCRFD adapter.
        
        Args:
            confidence_threshold: Override confidence threshold (uses contract default if None).
            nms_threshold: Override NMS threshold (uses contract default if None).
            providers: ONNX Runtime providers (default: CUDA then CPU).
        """
        self._core_detector = SCRFDCoreDetector(
            model_id="scrfd",
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            providers=providers,
        )
        self._preprocessing_contract = get_model_contract("scrfd")
    
    @property
    def model_id(self) -> str:
        """Get the detector model identifier."""
        return self._core_detector.model_id
    
    @property
    def model_version(self) -> str:
        """Get the detector model version."""
        return self._core_detector.model.version.version
    
    @property
    def model_sha256(self) -> str:
        """Get the detector model SHA256 hash."""
        return self._core_detector.model_sha256
    
    @property
    def status(self) -> DetectorStatus:
        """Get the detector implementation status."""
        return DetectorStatus.ACTIVE
    
    @property
    def preprocessing_contract(self) -> ModelPreprocessingContract:
        """Get the SCRFD 640x640 preprocessing contract."""
        return self._preprocessing_contract
    
    def detect(self, frame: CanonicalFrame) -> List[FaceDetectionContract]:
        """
        Detect faces using SCRFD and return model-independent results.
        
        Args:
            frame: CanonicalFrame to process.
            
        Returns:
            List of FaceDetectionContract objects in ORIGINAL_FRAME coordinates.
        """
        # Run SCRFD detection (returns SCRFD-specific FaceDetection objects)
        scrfd_detections: List[FaceDetection] = self._core_detector.detect(frame)
        
        # Convert to model-independent FaceDetectionContract
        results: List[FaceDetectionContract] = []
        for det in scrfd_detections:
            detection_id = det.detection_id
            
            # Build provenance
            provenance = create_detector_provenance(
                frame=frame,
                detector_model_id=self.model_id,
                detector_model_version=self.model_version,
                detector_model_sha256=self.model_sha256,
                detection_id=detection_id,
            )
            
            # Create model-independent detection contract
            contract_det = FaceDetectionContract(
                bbox=det.bbox,
                confidence=det.confidence,
                landmarks5=det.landmarks5,
                coordinate_space="original_frame",
                source_frame_id=det.source_id,
                detector_model_id=det.model_id,
                detector_model_version=self.model_version,
                detector_model_sha256=det.model_sha256,
                provenance=provenance,
                detection_id=detection_id,
            )
            results.append(contract_det)
        
        return results
    
    def cleanup(self) -> None:
        """Release SCRFD detector resources."""
        # The core detector holds the ONNX session
        # Clear the session reference to allow garbage collection
        if hasattr(self._core_detector, 'session'):
            del self._core_detector.session


def create_scrfd_adapter(
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
) -> SCRFDAdapter:
    """
    Factory function to create a SCRFD adapter.
    
    Args:
        confidence_threshold: Override confidence threshold.
        nms_threshold: Override NMS threshold.
        providers: ONNX Runtime providers.
        
    Returns:
        SCRFDAdapter instance implementing FaceDetectorInterface.
    """
    return SCRFDAdapter(
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        providers=providers,
    )