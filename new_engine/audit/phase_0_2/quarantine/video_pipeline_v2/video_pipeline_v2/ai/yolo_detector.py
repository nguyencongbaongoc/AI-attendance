"""
YOLO GPU Person Detector - V2 GPU-first video pipeline.

Runs YOLOv8/v11 person detection entirely on GPU.
Input: GPUFrame (NV12) → Preprocess → YOLO ONNX → Person detections.
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
class YOLOConfig:
    """Configuration for YOLO person detector."""
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.45
    input_size: Tuple[int, int] = (640, 640)
    person_class_id: int = 0  # COCO person class
    max_detections: int = 100


@dataclass
class PersonDetection:
    """Person detection result in ORIGINAL_FRAME coordinates."""
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    detection_id: str
    coordinate_space: str = "original_frame"
    model_id: str = "yolo"
    model_sha256: str = ""
    frame_index: int = 0
    source_id: str = ""
    class_id: int = 0
    
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


class YOLOPersonDetector(GPUInferenceEngine):
    """
    YOLO Person Detector running on GPU.
    
    Pipeline:
        GPUFrame (NV12) 
            → NV12→BGR conversion (GPU)
            → Letterbox resize to 640x640 (GPU)
            → Normalize [0,1] (GPU)
            → YOLO ONNX (GPU, IO Binding)
            → Parse outputs → NMS → PersonDetection list
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[YOLOConfig] = None,
        device_id: int = 0,
    ):
        self.yolo_config = config or YOLOConfig()
        
        inference_config = InferenceConfig(
            model_path=model_path,
            model_name="yolo",
            device_id=device_id,
            backend="onnxruntime",
            providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            use_io_binding=True,
            validate_input=True,
            validate_output=False,  # YOLO output format varies
        )
        
        super().__init__(inference_config)
        
        self.input_h, self.input_w = self.yolo_config.input_size
        self.device = f'cuda:{device_id}'
        
        # Normalization for YOLO (typically [0, 1])
        self.mean = torch.tensor([0.0, 0.0, 0.0], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([1.0, 1.0, 1.0], device=self.device).view(1, 3, 1, 1)
    
    def preprocess(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """
        Preprocess GPUFrame NV12 tensor to YOLO input format.
        
        Args:
            input_tensor: GPUFrame or BGR tensor
            
        Returns:
            Preprocessed tensor: (1, 3, 640, 640) float32 [0,1] on CUDA
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
        
        # Normalize to [0, 1] if needed
        if input_tensor.max() > 1.0:
            input_tensor = input_tensor / 255.0
        
        # Letterbox resize
        return self._letterbox_resize(input_tensor)
    
    def _preprocess_gpuframe(self, frame: GPUFrame) -> torch.Tensor:
        """Preprocess GPUFrame (NV12) to YOLO input."""
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
        
        return padded.contiguous()
    
    def postprocess(self, outputs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Postprocess YOLO outputs - return raw for parsing."""
        return outputs
    
    def get_output_shapes(self, batch_size: int) -> Dict[str, Tuple[int, ...]]:
        """YOLO output shape varies by model. Use dynamic."""
        # Typical YOLOv8/v11: (batch, num_boxes, 85) where 85 = 4 bbox + 1 obj + 80 classes
        # Or (batch, 84, 8400) transposed
        return {"default": (batch_size, -1, -1)}
    
    def detect(self, frame: GPUFrame) -> List[PersonDetection]:
        """
        Run person detection on a GPUFrame.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            
        Returns:
            List of PersonDetection in ORIGINAL_FRAME coordinates
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
        
        # Filter by confidence and class
        detections = [
            d for d in detections 
            if d.confidence >= self.yolo_config.confidence_threshold and d.class_id == self.yolo_config.person_class_id
        ]
        
        # Limit max detections
        detections = detections[:self.yolo_config.max_detections]
        
        return detections
    
    def _parse_outputs(
        self,
        outputs: Dict[str, torch.Tensor],
        original_width: int,
        original_height: int,
    ) -> List[PersonDetection]:
        """Parse YOLO raw outputs into PersonDetection objects."""
        detections = []
        
        # Get the output tensor
        output_tensor = list(outputs.values())[0]  # Shape varies
        
        # Handle different output formats
        # Format 1: (1, num_boxes, 85) - YOLOv8/v11
        # Format 2: (1, 85, num_boxes) - some exports
        # Format 3: (1, 84, 8400) - YOLOv8
        
        if output_tensor.dim() == 3:
            if output_tensor.shape[1] > output_tensor.shape[2]:
                # (1, 85, num_boxes) -> (1, num_boxes, 85)
                output_tensor = output_tensor.transpose(1, 2)
            
            # Now (1, num_boxes, 85)
            batch, num_boxes, _ = output_tensor.shape
            
            # Get preprocessing info
            scale = min(self.input_w / original_width, self.input_h / original_height)
            new_W = int(original_width * scale)
            new_H = int(original_height * scale)
            pad_top = (self.input_h - new_H) // 2
            pad_left = (self.input_w - new_W) // 2
            
            for i in range(num_boxes):
                box_data = output_tensor[0, i]  # (85,)
                
                # Extract bbox (cx, cy, w, h) in model input space
                cx, cy, w, h = box_data[:4]
                
                # Object confidence
                obj_conf = float(box_data[4])
                
                if obj_conf < self.yolo_config.confidence_threshold:
                    continue
                
                # Class scores
                class_scores = box_data[5:]
                class_id = int(torch.argmax(class_scores))
                class_conf = float(class_scores[class_id])
                
                confidence = obj_conf * class_conf
                
                if confidence < self.yolo_config.confidence_threshold:
                    continue
                
                # Convert bbox from center format to corners in model input space
                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                
                # Check if in valid region
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
                
                detection = PersonDetection(
                    bbox=bbox_original,
                    confidence=confidence,
                    detection_id=str(uuid.uuid4())[:8],
                    frame_index=frame.frame_id,
                    source_id=frame.camera_id,
                    class_id=class_id,
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
    
    def _apply_nms(self, detections: List[PersonDetection]) -> List[PersonDetection]:
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
                if iou > self.yolo_config.nms_threshold:
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


def create_yolo_detector(
    model_path: str = "models/yolo/yolo11n.onnx",
    confidence_threshold: float = 0.5,
    nms_threshold: float = 0.45,
    device_id: int = 0,
) -> YOLOPersonDetector:
    """Factory function to create YOLO person detector."""
    config = YOLOConfig(
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    return YOLOPersonDetector(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/yolo/yolo11n.onnx"
    detector = create_yolo_detector(model_path)
    
    if detector.initialize():
        print("YOLO person detector initialized successfully!")
        print(f"Stats: {detector.get_stats()}")
    else:
        print("YOLO person detector initialization failed")