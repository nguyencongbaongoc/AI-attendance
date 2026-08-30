"""
Phase 36G - GPU-Resident Face Detector Integration.

This module integrates Phase 36F GPU-resident preprocessing + ONNX Runtime I/O Binding
into the canonical V2 FaceDetector pipeline for OFFLINE processing only.

Preserves the exact same FaceDetection output contract as the CPU path.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.contracts import get_model_contract
from app.data.frame import CanonicalFrame
from app.data.preprocessing import PreprocessingResult
from app.models.registry import get_model_registry
from app.models.hashing import verify_sha256
from app.vision.detection import (
    FaceDetection,
    FaceDetector,
    CoordinateSpace,
    DetectionError,
    create_face_detector,
)
from app.vision.gpu_preprocessing import GPUPreprocessor, GPUPreprocessingResult
from app.vision.gpu_inference import GPUInferenceEngine, GPUInferenceResult

logger = logging.getLogger(__name__)


@dataclass
class GPUFaceDetectorConfig:
    """Configuration for GPU Face Detector."""
    model_id: str = "scrfd"
    confidence_threshold: Optional[float] = None
    nms_threshold: Optional[float] = None
    providers: Optional[List[str]] = None
    device_id: int = 0
    enable_gpu_path: bool = True
    fallback_to_cpu: bool = True
    # Optimization flags
    precompute_anchors: bool = False
    vectorized_decode: bool = False
    reuse_ortvalues: bool = False
    reuse_io_binding: bool = False
    no_unnecessary_sync: bool = False


class GPUFaceDetector:
    """
    GPU-Resident Face Detector for OFFLINE processing.
    
    Integrates Phase 36F GPU preprocessing + I/O Binding inference
    while preserving the canonical FaceDetection output contract.
    
    Falls back to CPU path on any GPU failure.
    """
    
    def __init__(self, config: GPUFaceDetectorConfig):
        """
        Initialize GPU Face Detector.
        
        Args:
            config: GPUFaceDetectorConfig with GPU/CPU settings.
        """
        self.config = config
        self.model_id = config.model_id
        
        if self.model_id != "scrfd":
            raise ValueError(f"GPUFaceDetector only supports 'scrfd', got '{self.model_id}'")
        
        self.registry = get_model_registry()
        self.model = self.registry.get(self.model_id)
        
        # Verify model integrity
        hash_result = verify_sha256(
            self.registry.get_model_path(self.model_id),
            self.model.expected_sha256,
        )
        if not hash_result.is_verified():
            raise DetectionError(
                f"Model SHA256 verification failed for {self.model_id}: {hash_result.status.value}",
                model_id=self.model_id,
            )
        
        self.model_sha256 = hash_result.actual_hash or self.model.expected_sha256
        
        # Get preprocessing contract
        self.contract = get_model_contract(self.model_id)
        
        # Use contract thresholds unless overridden
        self.confidence_threshold = (
            config.confidence_threshold 
            if config.confidence_threshold is not None 
            else self.model.thresholds.confidence_threshold
        )
        self.nms_threshold = (
            config.nms_threshold 
            if config.nms_threshold is not None 
            else self.model.thresholds.nms_threshold
        )
        
        # Initialize GPU components if enabled
        self.gpu_preprocessor: Optional[GPUPreprocessor] = None
        self.gpu_inference_engine: Optional[GPUInferenceEngine] = None
        self.gpu_available = False
        
        if config.enable_gpu_path:
            self._init_gpu_components(config.device_id, config.providers)
        
        # Always initialize CPU fallback
        self.cpu_detector = create_face_detector(
            model_id=self.model_id,
            confidence_threshold=self.confidence_threshold,
            nms_threshold=self.nms_threshold,
            providers=config.providers or ["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        
        logger.info(
            f"GPUFaceDetector initialized: gpu_path={'enabled' if self.gpu_available else 'disabled'}, "
            f"cpu_fallback={'enabled' if config.fallback_to_cpu else 'disabled'}"
        )
    
    def _init_gpu_components(self, device_id: int, providers: Optional[List[str]]) -> None:
        """Initialize GPU preprocessing and inference components."""
        try:
            # Check CUDA availability
            import torch
            if not torch.cuda.is_available():
                logger.warning("CUDA not available, GPU path disabled")
                return
            
            # Initialize GPU preprocessor
            self.gpu_preprocessor = GPUPreprocessor(self.model_id, device=torch.device(f"cuda:{device_id}"))
            
            # Initialize GPU inference engine with optimization flags
            gpu_providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
            self.gpu_inference_engine = GPUInferenceEngine(
                model_id=self.model_id,
                providers=gpu_providers,
                device_id=device_id,
                reuse_ortvalues=self.config.reuse_ortvalues,
                reuse_io_binding=self.config.reuse_io_binding,
                no_unnecessary_sync=self.config.no_unnecessary_sync,
            )
            
            # Verify CUDA EP is actually being used
            if not self.gpu_inference_engine.cuda_ep_used:
                logger.warning("CUDAExecutionProvider not active, GPU path disabled")
                self.gpu_preprocessor = None
                self.gpu_inference_engine = None
                self.gpu_available = False
                return
            
            # Precompute anchors if enabled
            if self.config.precompute_anchors:
                self._precompute_anchors()
            
            self.gpu_available = True
            logger.info(
                "GPU components initialized successfully: "
                f"cuda_ep_used={self.gpu_inference_engine.cuda_ep_used}, "
                f"io_binding_active=True, "
                f"precompute_anchors={self.config.precompute_anchors}, "
                f"vectorized_decode={self.config.vectorized_decode}, "
                f"reuse_ortvalues={self.config.reuse_ortvalues}, "
                f"reuse_io_binding={self.config.reuse_io_binding}, "
                f"no_unnecessary_sync={self.config.no_unnecessary_sync}"
            )
            
        except Exception as e:
            logger.warning(f"Failed to initialize GPU components: {e}")
            self.gpu_preprocessor = None
            self.gpu_inference_engine = None
            self.gpu_available = False
    
    def _precompute_anchors(self):
        """Precompute SCRFD anchors for all stride levels."""
        input_height = self.contract.input_height  # 640
        input_width = self.contract.input_width    # 640
        strides = [8, 16, 32]
        
        self._precomputed_anchors = {}
        self._precomputed_anchor_scales = {}
        
        for stride in strides:
            anchors, anchor_scales = self._generate_anchors(stride, input_height, input_width)
            self._precomputed_anchors[stride] = anchors
            self._precomputed_anchor_scales[stride] = anchor_scales
        
        logger.info(f"Precomputed anchors for strides {strides}: "
                    f"8={len(self._precomputed_anchors[8])}, "
                    f"16={len(self._precomputed_anchors[16])}, "
                    f"32={len(self._precomputed_anchors[32])}")
    
    def detect(self, frame: CanonicalFrame) -> List[FaceDetection]:
        """
        Detect faces in a canonical frame using GPU path with CPU fallback.
        
        Args:
            frame: CanonicalFrame to process.
            
        Returns:
            List of FaceDetection objects in ORIGINAL_FRAME coordinates.
            
        Raises:
            DetectionError: If both GPU and CPU paths fail.
        """
        # Try GPU path first if available
        if self.gpu_available and self.config.enable_gpu_path:
            try:
                return self._detect_gpu(frame)
            except Exception as e:
                logger.warning(f"GPU detection failed, falling back to CPU: {e}")
                if not self.config.fallback_to_cpu:
                    raise DetectionError(
                        f"GPU detection failed and CPU fallback disabled: {e}",
                        model_id=self.model_id,
                        frame_index=frame.metadata.frame_index,
                    )
        
        # CPU fallback
        logger.debug("Using CPU detection path")
        return self.cpu_detector.detect(frame)
    
    def _detect_gpu(self, frame: CanonicalFrame) -> List[FaceDetection]:
        """
        Detect faces using GPU-resident preprocessing and inference.
        
        This is the core GPU path that:
        1. Uploads frame to GPU once
        2. Runs preprocessing on GPU (PyTorch CUDA)
        3. Runs inference with I/O Binding (ORT CUDA EP)
        4. Parses outputs on CPU (minimal transfer)
        5. Returns canonical FaceDetection objects
        """
        # Step 1: GPU Preprocessing
        gpu_prep_result = self.gpu_preprocessor.preprocess(frame)
        
        # Step 2: GPU Inference with I/O Binding
        gpu_infer_result = self.gpu_inference_engine.infer_gpu(gpu_prep_result.tensor)
        
        # Step 3: Parse outputs (move minimal data to CPU for parsing)
        # Get outputs as numpy arrays for parsing
        outputs = [out.numpy() for out in gpu_infer_result.outputs]
        
        # Step 4: Parse SCRFD outputs using existing logic (adapted for GPU path)
        detections = self._parse_outputs_gpu(
            outputs=outputs,
            gpu_prep_result=gpu_prep_result,
            original_width=frame.metadata.original_width,
            original_height=frame.metadata.original_height,
        )
        
        # Step 5: Apply NMS
        detections = self._apply_nms(detections)
        
        # Step 6: Check for NaN confidences before filtering
        nan_confidences = [d for d in detections if np.isnan(d.confidence)]
        if len(nan_confidences) > 0:
            logger.warning(f"Found {len(nan_confidences)} detections with NaN confidence, triggering CPU fallback")
            raise DetectionError(
                f"GPU detections contain NaN confidence values, triggering CPU fallback",
                model_id=self.model_id,
                frame_index=frame.metadata.frame_index,
            )
        
        # Step 7: Filter by confidence
        detections = [
            d for d in detections 
            if d.confidence >= self.confidence_threshold
        ]
        
        # Step 8: Validate each detection
        validated = []
        for det in detections:
            try:
                validated.append(det)
            except ValueError as e:
                logger.debug(f"Skipping invalid detection: {e}")
                continue
        
        return validated
    
    def _parse_outputs_gpu(
        self,
        outputs: List[np.ndarray],
        gpu_prep_result: GPUPreprocessingResult,
        original_width: int,
        original_height: int,
    ) -> List[FaceDetection]:
        """
        Parse SCRFD model outputs into FaceDetection objects.
        
        Adapted from FaceDetector._parse_outputs to work with GPUPreprocessingResult.
        Supports vectorized decode and precomputed anchors.
        """
        detections = []
        
        # SCRFD 10G has 9 outputs (3 levels × 3 outputs each)
        if len(outputs) != 9:
            raise DetectionError(
                f"Expected 9 outputs from SCRFD 10G, got {len(outputs)}",
                model_id=self.model_id,
            )
        
        # Get scale factor and padding from GPU preprocessing result
        scale_factor = gpu_prep_result.scale_factor or 1.0
        padding = gpu_prep_result.padding_applied or (0, 0, 0, 0)
        pad_top, pad_bottom, pad_left, pad_right = padding
        
        # Model input size (from preprocessing contract)
        input_height = self.contract.input_height  # 640
        input_width = self.contract.input_width    # 640
        
        # Output order from model: scores (8,16,32), bboxes (8,16,32), keypoints (8,16,32)
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
            
            # Get anchors (precomputed or generated)
            if self.config.precompute_anchors and hasattr(self, '_precomputed_anchors'):
                anchors = self._precomputed_anchors[stride]
                anchor_scales = self._precomputed_anchor_scales[stride]
            else:
                anchors, anchor_scales = self._generate_anchors(stride, input_height, input_width)
            
            if anchors.shape[0] != num_anchors:
                # Handle case where model output doesn't match expected anchor count
                if anchors.shape[0] > num_anchors:
                    anchors = anchors[:num_anchors]
                    anchor_scales = anchor_scales[:num_anchors]
                else:
                    # Pad anchors (shouldn't happen in practice)
                    pass
            
            if self.config.vectorized_decode:
                # Vectorized decode for all anchors at this level
                detections.extend(self._parse_outputs_vectorized(
                    stride=stride,
                    scores=scores,
                    bboxes=bboxes,
                    keypoints=keypoints,
                    anchors=anchors,
                    anchor_scales=anchor_scales,
                    pad_left=pad_left,
                    pad_top=pad_top,
                    pad_right=pad_right,
                    pad_bottom=pad_bottom,
                    input_width=input_width,
                    input_height=input_height,
                    scale_factor=scale_factor,
                    original_width=original_width,
                    original_height=original_height,
                    gpu_prep_result=gpu_prep_result,
                ))
            else:
                # Original per-anchor loop
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
                    valid_x1 = pad_left
                    valid_y1 = pad_top
                    valid_x2 = input_width - pad_right
                    valid_y2 = input_height - pad_bottom
                    
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
                    
                    # Create detection with canonical contract
                    detection = FaceDetection(
                        bbox=bbox_original,
                        confidence=confidence,
                        landmarks5=kps_original,
                        detection_id=str(uuid.uuid4())[:8],
                        coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
                        model_id=self.model_id,
                        model_sha256=self.model_sha256,
                        frame_index=gpu_prep_result.frame_index,
                        source_id=gpu_prep_result.source_id,
                    )
                    
                    detections.append(detection)
        
        return detections
    
    def _parse_outputs_vectorized(
        self,
        stride: int,
        scores: np.ndarray,
        bboxes: np.ndarray,
        keypoints: np.ndarray,
        anchors: np.ndarray,
        anchor_scales: np.ndarray,
        pad_left: int,
        pad_top: int,
        pad_right: int,
        pad_bottom: int,
        input_width: int,
        input_height: int,
        scale_factor: float,
        original_width: int,
        original_height: int,
        gpu_prep_result: GPUPreprocessingResult,
    ) -> List[FaceDetection]:
        """
        Vectorized SCRFD output parsing using NumPy operations.
        
        Replaces the per-anchor Python loop with vectorized operations
        for significant speedup.
        """
        detections = []
        num_anchors = scores.shape[0]
        
        # Check for NaN confidences BEFORE filtering
        nan_mask = np.isnan(scores)
        if np.any(nan_mask):
            logger.warning(f"Found {np.sum(nan_mask)} NaN confidences in scores, triggering CPU fallback")
            raise DetectionError(
                f"GPU detections contain NaN confidence values, triggering CPU fallback",
                model_id=self.model_id,
                frame_index=gpu_prep_result.frame_index,
            )
        
        # Vectorized confidence filtering
        conf_mask = scores >= self.confidence_threshold
        if not np.any(conf_mask):
            return detections
        
        # Get indices of valid detections
        valid_indices = np.where(conf_mask)[0]
        valid_scores = scores[valid_indices]
        valid_bboxes = bboxes[valid_indices]
        valid_keypoints = keypoints[valid_indices]
        valid_anchors = anchors[valid_indices]
        valid_anchor_scales = anchor_scales[valid_indices]
        
        # Vectorized bbox decoding
        dx = valid_bboxes[:, 0]
        dy = valid_bboxes[:, 1]
        dw = valid_bboxes[:, 2]
        dh = valid_bboxes[:, 3]
        
        anchor_cx = valid_anchors[:, 0]
        anchor_cy = valid_anchors[:, 1]
        
        # Decode center and size
        cx = anchor_cx + dx * stride
        cy = anchor_cy + dy * stride
        w = np.exp(dw) * valid_anchor_scales
        h = np.exp(dh) * valid_anchor_scales
        
        # Convert to (x1, y1, x2, y2) in model input space
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2
        
        # Vectorized padding filter
        valid_x1 = pad_left
        valid_y1 = pad_top
        valid_x2 = input_width - pad_right
        valid_y2 = input_height - pad_bottom
        
        pad_mask = (x1 >= valid_x1) & (x2 <= valid_x2) & (y1 >= valid_y1) & (y2 <= valid_y2)
        if not np.any(pad_mask):
            return detections
        
        # Apply padding filter
        final_indices = valid_indices[pad_mask]
        final_scores = valid_scores[pad_mask]
        final_x1 = x1[pad_mask]
        final_y1 = y1[pad_mask]
        final_x2 = x2[pad_mask]
        final_y2 = y2[pad_mask]
        final_cx = cx[pad_mask]
        final_cy = cy[pad_mask]
        final_anchor_cx = anchor_cx[pad_mask]
        final_anchor_cy = anchor_cy[pad_mask]
        final_keypoints = valid_keypoints[pad_mask]
        
        # Vectorized keypoint decoding
        # keypoints shape: [num_valid, 10] -> reshape to [num_valid, 5, 2]
        kps = final_keypoints.reshape(-1, 5, 2)
        kps[:, :, 0] = final_anchor_cx[:, np.newaxis] + kps[:, :, 0] * stride
        kps[:, :, 1] = final_anchor_cy[:, np.newaxis] + kps[:, :, 1] * stride
        
        # Vectorized coordinate conversion to original frame space
        # bbox: [x1, y1, x2, y2]
        bbox_model = np.stack([final_x1, final_y1, final_x2, final_y2], axis=1)
        
        # Remove padding and scale
        bbox_original = bbox_model.copy()
        bbox_original[:, 0] = (bbox_original[:, 0] - pad_left) / scale_factor
        bbox_original[:, 1] = (bbox_original[:, 1] - pad_top) / scale_factor
        bbox_original[:, 2] = (bbox_original[:, 2] - pad_left) / scale_factor
        bbox_original[:, 3] = (bbox_original[:, 3] - pad_top) / scale_factor
        
        # Clip to original frame boundaries
        bbox_original[:, 0] = np.clip(bbox_original[:, 0], 0, original_width - 1)
        bbox_original[:, 1] = np.clip(bbox_original[:, 1], 0, original_height - 1)
        bbox_original[:, 2] = np.clip(bbox_original[:, 2], 0, original_width)
        bbox_original[:, 3] = np.clip(bbox_original[:, 3], 0, original_height)
        
        # Keypoints conversion
        kps_original = kps.copy()
        kps_original[:, :, 0] = (kps_original[:, :, 0] - pad_left) / scale_factor
        kps_original[:, :, 1] = (kps_original[:, :, 1] - pad_top) / scale_factor
        kps_original[:, :, 0] = np.clip(kps_original[:, :, 0], 0, original_width - 1)
        kps_original[:, :, 1] = np.clip(kps_original[:, :, 1], 0, original_height - 1)
        
        # Create FaceDetection objects
        for i in range(len(final_scores)):
            detection = FaceDetection(
                bbox=tuple(bbox_original[i].astype(float)),
                confidence=float(final_scores[i]),
                landmarks5=[tuple(kps_original[i, j].astype(float)) for j in range(5)],
                detection_id=str(uuid.uuid4())[:8],
                coordinate_space=CoordinateSpace.ORIGINAL_FRAME,
                model_id=self.model_id,
                model_sha256=self.model_sha256,
                frame_index=gpu_prep_result.frame_index,
                source_id=gpu_prep_result.source_id,
            )
            detections.append(detection)
        
        return detections
    
    def _generate_anchors(self, stride: int, input_height: int, input_width: int) -> Tuple[np.ndarray, np.ndarray]:
        """Generate anchor centers for a given stride (copied from FaceDetector)."""
        fm_h = input_height // stride
        fm_w = input_width // stride
        
        if stride == 8:
            anchor_scales = [16, 32]
        elif stride == 16:
            anchor_scales = [64, 128]
        elif stride == 32:
            anchor_scales = [256, 512]
        else:
            raise ValueError(f"Unsupported stride: {stride}")
        
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
    
    def close(self) -> None:
        """Clean up GPU resources."""
        if self.gpu_preprocessor:
            # GPUPreprocessor doesn't have explicit cleanup
            pass
        if self.gpu_inference_engine:
            # GPUInferenceEngine doesn't have explicit cleanup
            pass
        logger.info("GPUFaceDetector closed")


def create_gpu_face_detector(
    model_id: str = "scrfd",
    confidence_threshold: Optional[float] = None,
    nms_threshold: Optional[float] = None,
    providers: Optional[List[str]] = None,
    device_id: int = 0,
    enable_gpu_path: bool = True,
    fallback_to_cpu: bool = True,
    # Optimization flags
    precompute_anchors: bool = False,
    vectorized_decode: bool = False,
    reuse_ortvalues: bool = False,
    reuse_io_binding: bool = False,
    no_unnecessary_sync: bool = False,
) -> GPUFaceDetector:
    """
    Factory function to create a GPUFaceDetector.
    
    Args:
        model_id: Model identifier (must be "scrfd").
        confidence_threshold: Override confidence threshold.
        nms_threshold: Override NMS threshold.
        providers: ONNX Runtime providers.
        device_id: CUDA device ID.
        enable_gpu_path: Enable GPU-resident path.
        fallback_to_cpu: Fall back to CPU on GPU failure.
        precompute_anchors: Precompute SCRFD anchors once during initialization.
        vectorized_decode: Use vectorized NumPy postprocessing instead of Python loops.
        reuse_ortvalues: Pre-allocate and reuse input/output OrtValues across frames.
        reuse_io_binding: Bind inputs/outputs once, update data pointers only.
        no_unnecessary_sync: Remove redundant torch.cuda.synchronize() calls.
        
    Returns:
        GPUFaceDetector instance.
    """
    config = GPUFaceDetectorConfig(
        model_id=model_id,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        providers=providers,
        device_id=device_id,
        enable_gpu_path=enable_gpu_path,
        fallback_to_cpu=fallback_to_cpu,
        precompute_anchors=precompute_anchors,
        vectorized_decode=vectorized_decode,
        reuse_ortvalues=reuse_ortvalues,
        reuse_io_binding=reuse_io_binding,
        no_unnecessary_sync=no_unnecessary_sync,
    )
    return GPUFaceDetector(config)
