"""
Phase 7 — SCRFD Face Detection Service.

This module provides a dedicated face detector abstraction using SCRFD.
All detection goes through the ModelRegistry for model resolution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.contracts import get_model_contract
from app.data.frame import CanonicalFrame
from app.data.preprocessing import UnifiedPreprocessor, PreprocessingResult
from app.models.registry import get_model_registry
from app.models.hashing import verify_sha256
from app.runtime.cuda import get_ort_session


class DetectionError(Exception):
    """Exception raised when face detection fails."""
    
    def __init__(
        self,
        message: str,
        model_id: Optional[str] = None,
        frame_index: Optional[int] = None,
    ):
        super().__init__(message)
        self.model_id = model_id
        self.frame_index = frame_index


class CoordinateSpace(str, Enum):
    """Coordinate space for bounding boxes."""
    
    ORIGINAL_FRAME = "original_frame"
    MODEL_INPUT = "model_input"


@dataclass(frozen=True)
class FaceDetection:
    """
    Face detection result with explicit coordinate space.
    
    CRITICAL: Coordinate space MUST be recorded. Never mix spaces.
    """
    
    # Bounding box in ORIGINAL_FRAME coordinates (x1, y1, x2, y2)
    bbox: Tuple[float, float, float, float]
    
    # Detection confidence
    confidence: float
    
    # 5 facial landmarks in ORIGINAL_FRAME coordinates
    # Format: [(x1, y1), (x2, y2), ...] for 5 keypoints
    landmarks5: List[Tuple[float, float]]
    
    # Unique detection ID
    detection_id: str
    
    # Coordinate space of bbox and landmarks
    coordinate_space: CoordinateSpace = CoordinateSpace.ORIGINAL_FRAME
    
    # Model information
    model_id: str = "scrfd"
    model_sha256: str = ""
    
    # Frame reference
    frame_index: int = 0
    source_id: str = ""
    
    # Provenance (optional, for compatibility with FaceDetectionContract)
    provenance: Optional[Any] = None
    
    # Compatibility properties for FaceDetectionContract interface
    @property
    def detector_model_id(self) -> str:
        """Alias for model_id to match FaceDetectionContract interface."""
        return self.model_id
    
    @property
    def detector_model_sha256(self) -> str:
        """Alias for model_sha256 to match FaceDetectionContract interface."""
        return self.model_sha256
    
    def __post_init__(self):
        """Validate detection data."""
        x1, y1, x2, y2 = self.bbox
        
        # Validate bbox - allow negative and zero-area for clipping in safe_crop_face
        # Only validate that coordinates are finite
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise ValueError(f"Invalid bbox: non-finite coordinates ({x1}, {y1}, {x2}, {y2})")
        
        # Validate confidence
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Invalid confidence: {self.confidence}")
        
        # Validate landmarks
        if len(self.landmarks5) != 5:
            raise ValueError(f"Expected 5 landmarks, got {len(self.landmarks5)}")
        
        for i, (lx, ly) in enumerate(self.landmarks5):
            if not (np.isfinite(lx) and np.isfinite(ly)):
                raise ValueError(f"Landmark {i} has non-finite coordinates: ({lx}, {ly})")
    
    @property
    def width(self) -> float:
        """Get bbox width."""
        return self.bbox[2] - self.bbox[0]
    
    @property
    def height(self) -> float:
        """Get bbox height."""
        return self.bbox[3] - self.bbox[1]
    
    @property
    def area(self) -> float:
        """Get bbox area."""
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        """Get bbox center."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "landmarks5": self.landmarks5,
            "detection_id": self.detection_id,
            "coordinate_space": self.coordinate_space.value,
            "model_id": self.model_id,
            "model_sha256": self.model_sha256,
            "frame_index": self.frame_index,
            "source_id": self.source_id,
            "width": self.width,
            "height": self.height,
            "area": self.area,
        }


class FaceDetector:
    """
    SCRFD Face Detector.
    
    Uses the ModelRegistry to resolve model path and preprocessing contract.
    Runs inference via ONNX Runtime with CUDA/CPU providers.
    """
    
    def __init__(
        self,
        model_id: str = "scrfd",
        confidence_threshold: Optional[float] = None,
        nms_threshold: Optional[float] = None,
        providers: Optional[List[str]] = None,
    ):
        """
        Initialize the face detector.
        
        Args:
            model_id: Model identifier (must be "scrfd").
            confidence_threshold: Override confidence threshold (uses contract default if None).
            nms_threshold: Override NMS threshold (uses contract default if None).
            providers: ONNX Runtime providers (default: CUDA then CPU).
        """
        if model_id != "scrfd":
            raise ValueError(f"FaceDetector only supports 'scrfd', got '{model_id}'")
        
        self.model_id = model_id
        self.registry = get_model_registry()
        self.model = self.registry.get(model_id)
        
        # Verify model integrity
        hash_result = verify_sha256(
            self.registry.get_model_path(model_id),
            self.model.expected_sha256,
        )
        if not hash_result.is_verified():
            raise DetectionError(
                f"Model SHA256 verification failed for {model_id}: {hash_result.status.value}",
                model_id=model_id,
            )
        
        self.model_sha256 = hash_result.actual_hash or self.model.expected_sha256
        
        # Get preprocessing contract
        self.contract = get_model_contract(model_id)
        
        # Use contract thresholds unless overridden
        self.confidence_threshold = (
            confidence_threshold 
            if confidence_threshold is not None 
            else self.model.thresholds.confidence_threshold
        )
        self.nms_threshold = (
            nms_threshold 
            if nms_threshold is not None 
            else self.model.thresholds.nms_threshold
        )
        
        # Setup ONNX Runtime session
        self.providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.session = get_ort_session(
            self.registry.get_model_path(model_id),
            self.providers,
        )
        
        # Get input/output names
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        
        # Preprocessor
        self.preprocessor = UnifiedPreprocessor(model_id)
    
    def detect(self, frame: CanonicalFrame) -> List[FaceDetection]:
        """
        Detect faces in a canonical frame.
        
        Args:
            frame: CanonicalFrame to process.
            
        Returns:
            List of FaceDetection objects in ORIGINAL_FRAME coordinates.
            
        Raises:
            DetectionError: If detection fails.
        """
        try:
            # Preprocess frame
            prep_result = self.preprocessor.preprocess(frame)
            
            # Run inference
            outputs = self.session.run(
                self.output_names,
                {self.input_name: prep_result.tensor},
            )
            
            # Parse SCRFD outputs
            detections = self._parse_outputs(
                outputs=outputs,
                prep_result=prep_result,
                original_width=frame.metadata.original_width,
                original_height=frame.metadata.original_height,
            )
            
            # Apply NMS
            detections = self._apply_nms(detections)
            
            # Filter by confidence
            detections = [
                d for d in detections 
                if d.confidence >= self.confidence_threshold
            ]
            
            # Validate each detection
            validated = []
            for det in detections:
                try:
                    validated.append(det)
                except ValueError as e:
                    # Skip invalid detections
                    continue
            
            return validated
            
        except Exception as e:
            raise DetectionError(
                f"Face detection failed: {e}",
                model_id=self.model_id,
                frame_index=frame.metadata.frame_index,
            )
    
    def _generate_anchors(self, stride: int, input_height: int, input_width: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate anchor centers for a given stride.
        
        SCRFD 10G uses 2 anchors per location with different scales.
        For stride 8: 80x80 feature map (640/8), 2 anchors per location = 12800 anchors
        For stride 16: 40x40 feature map (640/16), 2 anchors per location = 3200 anchors
        For stride 32: 20x20 feature map (640/32), 2 anchors per location = 800 anchors
        
        IMPORTANT: Model outputs are ordered spatially first, then by scale:
        for y in range(fm_h):
            for x in range(fm_w):
                for scale in anchor_scales:
                    output anchor
        
        Args:
            stride: Feature map stride (8, 16, or 32)
            input_height: Model input height (from contract, e.g., 640)
            input_width: Model input width (from contract, e.g., 640)
            
        Returns:
            Anchor centers array of shape [num_anchors, 2] (cx, cy)
            Anchor scales array of shape [num_anchors] matching each anchor
        """
        # Feature map dimensions
        fm_h = input_height // stride
        fm_w = input_width // stride
        
        # SCRFD 10G anchor scales per stride
        # These are the base anchor sizes for each stride level
        if stride == 8:
            anchor_scales = [16, 32]  # 2 anchors per location
        elif stride == 16:
            anchor_scales = [64, 128]
        elif stride == 32:
            anchor_scales = [256, 512]
        else:
            raise ValueError(f"Unsupported stride: {stride}")
        
        # Generate grid of anchor centers matching model output order:
        # Spatial first (y, x), then scale
        anchors = []
        anchor_scales_list = []
        for y in range(fm_h):
            for x in range(fm_w):
                cx = (x + 0.5) * stride
                cy = (y + 0.5) * stride
                for scale in anchor_scales:
                    anchors.append([cx, cy])
                    anchor_scales_list.append(scale)
        
        return np.array(anchors, dtype=np.float32), np.array(anchor_scales_list, dtype=np.float32)

    def _parse_outputs(
        self,
        outputs: List[np.ndarray],
        prep_result: PreprocessingResult,
        original_width: int,
        original_height: int,
    ) -> List[FaceDetection]:
        """
        Parse SCRFD model outputs into FaceDetection objects.
        
        SCRFD 10G output format (9 outputs, 3 feature map levels):
        - Level 1 (stride 8):  scores [num_anchors_1], bboxes [num_anchors_1, 4], keypoints [num_anchors_1, 10]
        - Level 2 (stride 16): scores [num_anchors_2], bboxes [num_anchors_2, 4], keypoints [num_anchors_2, 10]
        - Level 3 (stride 32): scores [num_anchors_3], bboxes [num_anchors_3, 4], keypoints [num_anchors_3, 10]
        
        Bbox outputs are (dx, dy, dw, dh) offsets from anchor centers:
        - cx = anchor_cx + dx * stride
        - cy = anchor_cy + dy * stride
        - w = exp(dw) * anchor_scale
        - h = exp(dh) * anchor_scale
        
        Keypoint outputs are (dx, dy) offsets from anchor centers for 5 keypoints.
        
        Actual output order from model (stride order: 8, 16, 32):
        [score_8, score_16, score_32, bbox_8, bbox_16, bbox_32, kps_8, kps_16, kps_32]
        """
        detections = []
        
        # SCRFD 10G has 9 outputs (3 levels × 3 outputs each)
        if len(outputs) != 9:
            raise DetectionError(
                f"Expected 9 outputs from SCRFD 10G, got {len(outputs)}",
                model_id=self.model_id,
            )
        
        # Get scale factor and padding from preprocessing
        scale_factor = prep_result.scale_factor or 1.0
        padding = prep_result.padding_applied or (0, 0, 0, 0)
        pad_top, pad_bottom, pad_left, pad_right = padding
        
        # Model input size (from preprocessing contract)
        input_height = self.contract.input_height  # 640 (from SCRFD contract)
        input_width = self.contract.input_width    # 640 (from SCRFD contract)
        
        # Output order from model: scores (8,16,32), bboxes (8,16,32), keypoints (8,16,32)
        # Indices: 0,1,2 = scores; 3,4,5 = bboxes; 6,7,8 = keypoints
        # Level 0 = stride 8, Level 1 = stride 16, Level 2 = stride 32
        score_outputs = [outputs[0], outputs[1], outputs[2]]      # [score_8, score_16, score_32]
        bbox_outputs = [outputs[3], outputs[4], outputs[5]]       # [bbox_8, bbox_16, bbox_32]
        kps_outputs = [outputs[6], outputs[7], outputs[8]]        # [kps_8, kps_16, kps_32]
        strides = [8, 16, 32]
        
        # Process each feature map level (3 levels: stride 8, 16, 32)
        for level_idx in range(3):
            stride = strides[level_idx]
            scores = score_outputs[level_idx]   # [num_anchors]
            bboxes = bbox_outputs[level_idx]    # [num_anchors, 4] - (dx, dy, dw, dh)
            keypoints = kps_outputs[level_idx]  # [num_anchors, 10] - 5 keypoints * (dx, dy)
            
            # Ensure correct shapes (squeeze if needed)
            if scores.ndim > 1:
                scores = scores.squeeze()
            if bboxes.ndim > 2:
                bboxes = bboxes.squeeze(0)
            if keypoints.ndim > 2:
                keypoints = keypoints.squeeze(0)
            
            num_anchors = scores.shape[0]
            
            # Generate anchor centers and scales for this stride level
            anchors, anchor_scales = self._generate_anchors(stride, input_height, input_width)
            
            if anchors.shape[0] != num_anchors:
                # Handle case where model output doesn't match expected anchor count
                # This can happen with dynamic shapes - truncate or pad
                if anchors.shape[0] > num_anchors:
                    anchors = anchors[:num_anchors]
                    anchor_scales = anchor_scales[:num_anchors]
                else:
                    # Pad anchors (shouldn't happen in practice)
                    pass
            
            # Process each anchor at this level
            for i in range(num_anchors):
                confidence = float(scores[i])
                
                if confidence < self.confidence_threshold:
                    continue
                
                # Get anchor center and scale
                anchor_cx, anchor_cy = anchors[i]
                anchor_scale = anchor_scales[i]
                
                # Decode bbox: (dx, dy, dw, dh) -> (x1, y1, x2, y2)
                dx, dy, dw, dh = bboxes[i]
                
                # Decode center and size
                cx = anchor_cx + dx * stride
                cy = anchor_cy + dy * stride
                w = np.exp(dw) * anchor_scale
                h = np.exp(dh) * anchor_scale
                
                # Convert to (x1, y1, x2, y2) in model input space
                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                
                bbox_model = np.array([x1, y1, x2, y2], dtype=np.float32)
                
                # Decode keypoints: 5 keypoints * (dx, dy) offsets from anchor center
                kps_model = keypoints[i].reshape(5, 2)
                for kp_idx in range(5):
                    kp_dx, kp_dy = kps_model[kp_idx]
                    kps_model[kp_idx, 0] = anchor_cx + kp_dx * stride
                    kps_model[kp_idx, 1] = anchor_cy + kp_dy * stride
                
                # Filter out detections in padded regions
                # Check if bbox (in model input space) is fully within valid (non-padded) region
                # Valid region in model input space: x=[pad_left, input_width-pad_right], y=[pad_top, input_height-pad_bottom]
                valid_x1 = pad_left
                valid_y1 = pad_top
                valid_x2 = input_width - pad_right
                valid_y2 = input_height - pad_bottom
                
                # Check bbox is fully within valid region
                if x1 < valid_x1 or x2 > valid_x2 or y1 < valid_y1 or y2 > valid_y2:
                    continue  # Skip detections that extend into padded regions
                
                # Convert from model input space to original frame space
                bbox_original = self._convert_bbox_model_to_original(
                    bbox_model, scale_factor, pad_left, pad_top,
                    original_width, original_height
                )
                
                kps_original = self._convert_keypoints_model_to_original(
                    kps_model, scale_factor, pad_left, pad_top,
                    original_width, original_height
                )
                
                # Create detection
                detection = FaceDetection(
                    bbox=bbox_original,
                    confidence=confidence,
                    landmarks5=kps_original,
                    detection_id=str(uuid.uuid4())[:8],
                    coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
                    model_id=self.model_id,
                    model_sha256=self.model_sha256,
                    frame_index=prep_result.frame_index,
                    source_id=prep_result.source_id,
                )
                
                detections.append(detection)
        
        return detections
    
    def _convert_bbox_model_to_original(
        self,
        bbox_model: np.ndarray,
        scale_factor: float,
        pad_left: int,
        pad_top: int,
        original_width: int,
        original_height: int,
    ) -> Tuple[float, float, float, float]:
        """Convert bbox from model input space to original frame space."""
        x1, y1, x2, y2 = bbox_model
        
        # Remove padding
        x1 = (x1 - pad_left) / scale_factor
        y1 = (y1 - pad_top) / scale_factor
        x2 = (x2 - pad_left) / scale_factor
        y2 = (y2 - pad_top) / scale_factor
        
        # Clip to original frame boundaries
        x1 = max(0.0, min(x1, original_width - 1))
        y1 = max(0.0, min(y1, original_height - 1))
        x2 = max(0.0, min(x2, original_width))
        y2 = max(0.0, min(y2, original_height))
        
        return (float(x1), float(y1), float(x2), float(y2))
    
    def _convert_keypoints_model_to_original(
        self,
        keypoints_model: np.ndarray,
        scale_factor: float,
        pad_left: int,
        pad_top: int,
        original_width: int,
        original_height: int,
    ) -> List[Tuple[float, float]]:
        """Convert keypoints from model input space to original frame space."""
        kps_original = []
        
        for kp in keypoints_model:
            x, y = kp
            
            # Remove padding and scale
            x = (x - pad_left) / scale_factor
            y = (y - pad_top) / scale_factor
            
            # Clip to original frame boundaries
            x = max(0.0, min(x, original_width - 1))
            y = max(0.0, min(y, original_height - 1))
            
            kps_original.append((float(x), float(y)))
        
        return kps_original
    
    def _apply_nms(self, detections: List[FaceDetection]) -> List[FaceDetection]:
        """Apply Non-Maximum Suppression to detections."""
        if len(detections) <= 1:
            return detections
        
        # Sort by confidence descending
        detections = sorted(detections, key=lambda d: d.confidence, reverse=True)
        
        keep = []
        suppressed = [False] * len(detections)
        
        for i in range(len(detections)):
            if suppressed[i]:
                continue
            
            keep.append(detections[i])
            
            # Suppress overlapping detections
            for j in range(i + 1, len(detections)):
                if suppressed[j]:
                    continue
                
                iou = self._compute_iou(detections[i].bbox, detections[j].bbox)
                if iou > self.nms_threshold:
                    suppressed[j] = True
        
        return keep
    
    def _compute_iou(self, bbox1: Tuple[float, float, float, float], 
                     bbox2: Tuple[float, float, float, float]) -> float:
        """Compute Intersection over Union of two bboxes."""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        # Intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        if union <= 0:
            return 0.0
        
        return intersection / union


def create_face_detector(
    model_id: str = "scrfd",
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
) -> FaceDetector:
    """
    Factory function to create a FaceDetector.
    
    Args:
        model_id: Model identifier.
        confidence_threshold: Override confidence threshold.
        nms_threshold: Override NMS threshold.
        providers: ONNX Runtime providers.
        
    Returns:
        FaceDetector instance.
    """
    return FaceDetector(
        model_id=model_id,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        providers=providers,
    )