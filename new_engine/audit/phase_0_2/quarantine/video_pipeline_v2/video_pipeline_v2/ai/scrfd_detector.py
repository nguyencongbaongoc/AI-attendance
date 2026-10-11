"""
SCRFD GPU Face Detector - V2 GPU-first video pipeline.

Runs SCRFD 10G face detection entirely on GPU using ONNX Runtime
with zero-copy IO Binding. Input: NV12 GPUFrame → Preprocessed tensor → SCRFD → Detections.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

import torch
import torch.nn.functional as F
import numpy as np

from video_pipeline_v2.core.gpu_frame import GPUFrame, nv12_to_bgr_cuda
from video_pipeline_v2.ai.gpu_inference import GPUInferenceEngine, InferenceConfig, InferenceResult
from video_pipeline_v2.ai.model_contracts import ModelContractRegistry

logger = logging.getLogger(__name__)


@dataclass
class SCRFDConfig:
    """Configuration for SCRFD detector."""
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.4
    input_size: Tuple[int, int] = (640, 640)
    # SCRFD 10G anchor config
    strides: Tuple[int, ...] = (8, 16, 32)
    anchor_scales: Dict[int, List[int]] = None  # Set in __post_init__
    
    def __post_init__(self):
        if self.anchor_scales is None:
            self.anchor_scales = {
                8: [16, 32],
                16: [64, 128],
                32: [256, 512],
            }


@dataclass
class FaceDetection:
    """Face detection result in ORIGINAL_FRAME coordinates."""
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    landmarks5: List[Tuple[float, float]]  # 5 keypoints
    detection_id: str
    coordinate_space: str = "original_frame"
    model_id: str = "scrfd"
    model_sha256: str = ""
    frame_index: int = 0
    source_id: str = ""
    
    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]
    
    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)


class SCRFDDetector(GPUInferenceEngine):
    """
    SCRFD Face Detector running on GPU.
    
    Pipeline:
        GPUFrame (NV12) 
            → NV12→BGR conversion (GPU)
            → Letterbox resize to 640x640 (GPU)
            → Normalize (GPU)
            → SCRFD ONNX (GPU, IO Binding)
            → Parse outputs → NMS → FaceDetection list
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[SCRFDConfig] = None,
        device_id: int = 0,
    ):
        self.scrfd_config = config or SCRFDConfig()
        
        inference_config = InferenceConfig(
            model_path=model_path,
            model_name="scrfd",
            device_id=device_id,
            backend="onnxruntime",
            providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            use_io_binding=True,
            validate_input=True,
            validate_output=True,
        )
        
        super().__init__(inference_config)
        
        # Preprocessing parameters
        self.input_h, self.input_w = self.scrfd_config.input_size
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=f'cuda:{device_id}').view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=f'cuda:{device_id}').view(1, 3, 1, 1)
        
        # Generate anchors once
        self._anchors: Dict[int, torch.Tensor] = {}
        self._anchor_scales: Dict[int, torch.Tensor] = {}
        self._generate_anchors()
    
    def _generate_anchors(self) -> None:
        """Pre-generate anchor centers and scales for each stride level."""
        device = f'cuda:{self.device_id}'
        
        for stride in self.scrfd_config.strides:
            fm_h = self.input_h // stride
            fm_w = self.input_w // stride
            scales = self.scrfd_config.anchor_scales[stride]
            
            anchors = []
            anchor_scales_list = []
            
            for y in range(fm_h):
                for x in range(fm_w):
                    cx = (x + 0.5) * stride
                    cy = (y + 0.5) * stride
                    for scale in scales:
                        anchors.append([cx, cy])
                        anchor_scales_list.append(scale)
            
            self._anchors[stride] = torch.tensor(anchors, dtype=torch.float32, device=device)
            self._anchor_scales[stride] = torch.tensor(anchor_scales_list, dtype=torch.float32, device=device)
        
        logger.debug(f"SCRFDDetector: Generated anchors for strides {self.scrfd_config.strides}")
    
    def preprocess(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """
        Preprocess GPUFrame NV12 tensor to SCRFD input format.
        
        Args:
            input_tensor: Can be either:
                - GPUFrame (will extract tensors and convert)
                - BGR tensor (H, W, 3) or (1, 3, H, W)
                - Preprocessed tensor (1, 3, 640, 640)
        
        Returns:
            Preprocessed tensor: (1, 3, 640, 640) float32 on CUDA
        """
        # Handle GPUFrame input
        if isinstance(input_tensor, GPUFrame):
            return self._preprocess_gpuframe(input_tensor)
        
        # Handle BGR tensor input
        if input_tensor.dim() == 3 and input_tensor.shape[-1] == 3:
            # (H, W, 3) -> (1, 3, H, W)
            input_tensor = input_tensor.permute(2, 0, 1).unsqueeze(0).float()
        elif input_tensor.dim() == 4 and input_tensor.shape[1] == 3:
            # Already (1, 3, H, W)
            input_tensor = input_tensor.float()
        else:
            raise ValueError(f"Unexpected input shape: {input_tensor.shape}")
        
        # Letterbox resize to 640x640
        return self._letterbox_resize(input_tensor)
    
    def _preprocess_gpuframe(self, frame: GPUFrame) -> torch.Tensor:
        """Preprocess GPUFrame (NV12) to SCRFD input."""
        # Convert NV12 to BGR on GPU
        y_tensor, uv_tensor = frame.get_tensors()
        bgr_tensor = nv12_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) uint8
        
        # Convert to float and normalize: (H, W, 3) -> (1, 3, H, W) float32 [0,1]
        bgr_float = bgr_tensor.permute(2, 0, 1).unsqueeze(0).float() / 255.0
        
        # Letterbox resize
        return self._letterbox_resize(bgr_float)
    
    def _letterbox_resize(self, tensor: torch.Tensor) -> torch.Tensor:
        """Letterbox resize to input size preserving aspect ratio."""
        # tensor: (1, 3, H, W) float32 [0,1]
        _, _, H, W = tensor.shape
        
        # Calculate scale
        scale = min(self.input_w / W, self.input_h / H)
        new_W = int(W * scale)
        new_H = int(H * scale)
        
        # Resize
        resized = F.interpolate(
            tensor,
            size=(new_H, new_W),
            mode='bilinear',
            align_corners=False
        )
        
        # Create padded tensor
        padded = torch.zeros(
            (1, 3, self.input_h, self.input_w),
            dtype=torch.float32,
            device=tensor.device
        )
        
        # Calculate padding
        pad_top = (self.input_h - new_H) // 2
        pad_left = (self.input_w - new_W) // 2
        
        # Place resized image in center
        padded[:, :, pad_top:pad_top+new_H, pad_left:pad_left+new_W] = resized
        
        # Normalize
        normalized = (padded - self.mean) / self.std
        
        return normalized.contiguous()
    
    def postprocess(self, outputs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Postprocess SCRFD outputs - just return raw outputs for parsing."""
        return outputs
    
    def get_output_shapes(self, batch_size: int) -> Dict[str, Tuple[int, ...]]:
        """Get output shapes for SCRFD 10G."""
        shapes = {}
        for stride in self.scrfd_config.strides:
            fm_h = self.input_h // stride
            fm_w = self.input_w // stride
            num_anchors = fm_h * fm_w * 2  # 2 anchors per location
            
            shapes[f"score_{stride}"] = (batch_size, 2, fm_h, fm_w)
            shapes[f"bbox_{stride}"] = (batch_size, num_anchors, 4)
            shapes[f"kps_{stride}"] = (batch_size, num_anchors, 10)
        
        return shapes
    
    def detect(self, frame: GPUFrame) -> List[FaceDetection]:
        """
        Run face detection on a GPUFrame.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            
        Returns:
            List of FaceDetection in ORIGINAL_FRAME coordinates
        """
        # Run inference
        result = self.infer(frame)
        
        # Parse outputs
        detections = self._parse_outputs(
            outputs=result.outputs,
            original_width=frame.width,
            original_height=frame.height,
        )
        
        # Apply NMS
        detections = self._apply_nms(detections)
        
        # Filter by confidence
        detections = [d for d in detections if d.confidence >= self.scrfd_config.confidence_threshold]
        
        return detections
    
    def _parse_outputs(
        self,
        outputs: Dict[str, torch.Tensor],
        original_width: int,
        original_height: int,
    ) -> List[FaceDetection]:
        """Parse SCRFD raw outputs into FaceDetection objects."""
        detections = []
        
        # Get preprocessing info (we need to know padding from letterbox)
        # For now, assume input was letterboxed to 640x640
        # We'll need to track padding from preprocess
        scale = min(self.input_w / original_width, self.input_h / original_height)
        new_W = int(original_width * scale)
        new_H = int(original_height * scale)
        pad_top = (self.input_h - new_H) // 2
        pad_left = (self.input_w - new_W) // 2
        
        strides = self.scrfd_config.strides
        
        for stride in strides:
            # Get outputs for this stride
            score_key = f"score_{stride}"
            bbox_key = f"bbox_{stride}"
            kps_key = f"kps_{stride}"
            
            if score_key not in outputs:
                continue
            
            scores = outputs[score_key]  # (1, 2, H, W) or (1, num_anchors)
            bboxes = outputs[bbox_key]    # (1, num_anchors, 4)
            keypoints = outputs[kps_key]  # (1, num_anchors, 10)
            
            # Reshape scores if needed
            if scores.dim() == 4:
                scores = scores.permute(0, 2, 3, 1).reshape(1, -1, 2)  # (1, num_anchors, 2)
            
            if scores.dim() == 3 and scores.shape[0] == 1:
                scores = scores.squeeze(0)  # (num_anchors, 2)
            
            # Get max score across 2 anchors per location
            max_scores, _ = scores.max(dim=1)  # (num_anchors,)
            
            # Filter by confidence
            conf_mask = max_scores >= self.scrfd_config.confidence_threshold
            if not conf_mask.any():
                continue
            
            # Get valid indices
            valid_indices = torch.where(conf_mask)[0]
            
            anchors = self._anchors[stride]
            anchor_scales = self._anchor_scales[stride]
            
            for idx in valid_indices:
                idx = idx.item()
                confidence = float(max_scores[idx])
                
                # Decode bbox
                anchor_cx, anchor_cy = anchors[idx]
                anchor_scale = anchor_scales[idx]
                
                dx, dy, dw, dh = bboxes[0, idx]
                
                cx = anchor_cx + dx * stride
                cy = anchor_cy + dy * stride
                w = torch.exp(dw) * anchor_scale
                h = torch.exp(dh) * anchor_scale
                
                # Bbox in model input space
                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                
                # Check if in valid (non-padded) region
                valid_x1 = pad_left
                valid_y1 = pad_top
                valid_x2 = self.input_w - (self.input_w - new_W - pad_left)
                valid_y2 = self.input_h - (self.input_h - new_H - pad_top)
                
                if x1 < valid_x1 or x2 > valid_x2 or y1 < valid_y1 or y2 > valid_y2:
                    continue
                
                # Convert to original frame coordinates
                bbox_original = self._convert_bbox_to_original(
                    x1, y1, x2, y2, scale, pad_left, pad_top, original_width, original_height
                )
                
                # Decode keypoints
                kps_model = keypoints[0, idx].reshape(5, 2)
                kps_original = []
                for kp_idx in range(5):
                    kp_dx, kp_dy = kps_model[kp_idx]
                    kp_x = anchor_cx + kp_dx * stride
                    kp_y = anchor_cy + kp_dy * stride
                    kp_orig = self._convert_point_to_original(
                        kp_x, kp_y, scale, pad_left, pad_top, original_width, original_height
                    )
                    kps_original.append(kp_orig)
                
                detection = FaceDetection(
                    bbox=bbox_original,
                    confidence=confidence,
                    landmarks5=kps_original,
                    detection_id=str(uuid.uuid4())[:8],
                    frame_index=frame.frame_id,
                    source_id=frame.camera_id,
                    model_sha256="",  # Would be filled from model registry
                )
                
                detections.append(detection)
        
        return detections
    
    def _convert_bbox_to_original(
        self,
        x1: float, y1: float, x2: float, y2: float,
        scale: float, pad_left: int, pad_top: int,
        orig_w: int, orig_h: int
    ) -> Tuple[float, float, float, float]:
        """Convert bbox from model input space to original frame space."""
        # Remove padding
        x1 = (x1 - pad_left) / scale
        y1 = (y1 - pad_top) / scale
        x2 = (x2 - pad_left) / scale
        y2 = (y2 - pad_top) / scale
        
        # Clip to frame boundaries
        x1 = max(0.0, min(x1, orig_w - 1))
        y1 = max(0.0, min(y1, orig_h - 1))
        x2 = max(0.0, min(x2, orig_w))
        y2 = max(0.0, min(y2, orig_h))
        
        return (float(x1), float(y1), float(x2), float(y2))
    
    def _convert_point_to_original(
        self,
        x: float, y: float,
        scale: float, pad_left: int, pad_top: int,
        orig_w: int, orig_h: int
    ) -> Tuple[float, float]:
        """Convert point from model input space to original frame space."""
        x = (x - pad_left) / scale
        y = (y - pad_top) / scale
        
        x = max(0.0, min(x, orig_w - 1))
        y = max(0.0, min(y, orig_h - 1))
        
        return (float(x), float(y))
    
    def _apply_nms(self, detections: List[FaceDetection]) -> List[FaceDetection]:
        """Apply Non-Maximum Suppression."""
        if len(detections) <= 1:
            return detections
        
        # Sort by confidence
        detections = sorted(detections, key=lambda d: d.confidence, reverse=True)
        
        keep = []
        suppressed = [False] * len(detections)
        
        for i in range(len(detections)):
            if suppressed[i]:
                continue
            
            keep.append(detections[i])
            
            for j in range(i + 1, len(detections)):
                if suppressed[j]:
                    continue
                
                iou = self._compute_iou(detections[i].bbox, detections[j].bbox)
                if iou > self.scrfd_config.nms_threshold:
                    suppressed[j] = True
        
        return keep
    
    def _compute_iou(
        self,
        bbox1: Tuple[float, float, float, float],
        bbox2: Tuple[float, float, float, float]
    ) -> float:
        """Compute IoU of two bboxes."""
        x1_1, y1_1, x2_1, y2_1 = bbox1
        x1_2, y1_2, x2_2, y2_2 = bbox2
        
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0


def create_scrfd_detector(
    model_path: str = "models/scrfd/scrfd_10g_bnkps.onnx",
    confidence_threshold: float = 0.5,
    nms_threshold: float = 0.4,
    device_id: int = 0,
) -> SCRFDDetector:
    """Factory function to create SCRFD detector."""
    config = SCRFDConfig(
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    return SCRFDDetector(model_path, config, device_id)


if __name__ == "__main__":
    # Test initialization
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/scrfd/scrfd_10g_bnkps.onnx"
    detector = create_scrfd_detector(model_path)
    
    if detector.initialize():
        print("SCRFD detector initialized successfully!")
        print(f"Stats: {detector.get_stats()}")
    else:
        print("SCRFD detector initialization failed")