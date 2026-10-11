"""
YOLO Person Detector - GPU-accelerated person detection.

Runs YOLO11n entirely on GPU using TensorRT (.engine) or ONNX Runtime (.onnx) with IO Binding.
Input: GPUFrame (NV12) → Preprocess → YOLO TensorRT/ONNX → Person detections.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path

import torch
import torch.nn.functional as F
import numpy as np

from pipeline_engine.memory.gpu_frame import GPUFrame, nv12_to_bgr_cuda, letterbox_resize_cuda
from pipeline_engine.config import get_config, get_model_config
from pipeline_engine.inference.tensorrt_engine import TensorRTExecutor, create_tensorrt_executor

logger = logging.getLogger(__name__)


@dataclass
class YOLOConfig:
    """Configuration for YOLO person detector."""
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.45
    input_size: Tuple[int, int] = (640, 640)
    person_class_id: int = 0
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


class YOLOPersonDetector:
    """
    YOLO Person Detector running on GPU.
    
    Pipeline:
        GPUFrame (NV12) 
            → NV12→BGR conversion (GPU)
            → Letterbox resize to 640x640 (GPU)
            → Normalize [0,1] (GPU)
            → YOLO TensorRT/ONNX (GPU, IO Binding)
            → Parse outputs → NMS → PersonDetection list
    
    Supports both .engine (TensorRT) and .onnx (ONNX Runtime) model formats.
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[YOLOConfig] = None,
        device_id: int = 0,
    ):
        self.yolo_config = config or YOLOConfig()
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # Backend selection based on model extension
        self._model_path = model_path
        self._use_tensorrt = model_path.endswith('.engine')
        
        # TensorRT executor (for .engine)
        self._trt_executor: Optional[TensorRTExecutor] = None
        
        # ONNX Runtime session (for .onnx)
        self._session: Optional[ort.InferenceSession] = None
        self._io_binding: Optional[ort.IOBinding] = None
        self._input_name: str = ""
        self._output_names: List[str] = []
        
        # Normalization for YOLO (typically [0, 1])
        self.input_h, self.input_w = self.yolo_config.input_size
        self.mean = torch.tensor([0.0, 0.0, 0.0], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([1.0, 1.0, 1.0], device=self.device).view(1, 3, 1, 1)
        
        # Stats
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_error: Optional[str] = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """Initialize backend (TensorRT or ONNX Runtime) based on model file extension."""
        if self._initialized:
            return True
        
        try:
            if self._use_tensorrt:
                return self._initialize_tensorrt()
            else:
                return self._initialize_onnx()
                
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"YOLOPersonDetector: Initialization failed: {e}")
            return False
    
    def _initialize_tensorrt(self) -> bool:
        """Initialize TensorRT executor for .engine file."""
        try:
            import onnxruntime as ort
        except ImportError:
            pass  # Not needed for TensorRT
        
        try:
            self._trt_executor = create_tensorrt_executor(self._model_path, self.device_id)
            if not self._trt_executor.initialize():
                return False
            
            # Verify CUDA execution
            binding_info = self._trt_executor.get_binding_info()
            logger.info(f"YOLOPersonDetector: Using TensorRT engine - {len(binding_info['inputs'])} inputs, {len(binding_info['outputs'])} outputs")
            
            self._initialized = True
            logger.info(f"YOLOPersonDetector: Initialized TensorRT on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"YOLOPersonDetector: TensorRT initialization failed: {e}")
            return False
    
    def _initialize_onnx(self) -> bool:
        """Initialize ONNX Runtime session for .onnx file."""
        try:
            import onnxruntime as ort
        except ImportError:
            self._last_error = "onnxruntime not available"
            logger.error(f"YOLOPersonDetector: {self._last_error}")
            return False
        
        try:
            session_options = ort.SessionOptions()
            session_options.enable_mem_pattern = True
            session_options.enable_cpu_mem_arena = True
            session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session_options.intra_op_num_threads = 1
            session_options.inter_op_num_threads = 1
            
            self._session = ort.InferenceSession(
                self._model_path,
                sess_options=session_options,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            
            # Setup IO Binding for zero-copy
            self._io_binding = self._session.io_binding()
            
            # Get input/output names
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [o.name for o in self._session.get_outputs()]
            
            # Verify CUDA provider
            providers = self._session.get_providers()
            if "CUDAExecutionProvider" in providers:
                logger.info(f"YOLOPersonDetector: Using CUDAExecutionProvider")
            else:
                logger.warning(f"YOLOPersonDetector: CUDA not available, using {providers[0]}")
            
            self._initialized = True
            logger.info(f"YOLOPersonDetector: Initialized ONNX Runtime on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"YOLOPersonDetector: ONNX Runtime initialization failed: {e}")
            return False
    
    def preprocess(self, frame: GPUFrame) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """
        Preprocess GPUFrame NV12 tensor to YOLO input format.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            
        Returns:
            Tuple of (preprocessed_tensor, padding_info)
        """
        # Convert NV12 to BGR on GPU
        y_tensor, uv_tensor = frame.get_tensors()
        bgr_tensor = nv12_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) uint8
        
        # Convert to float and normalize: (H, W, 3) -> (1, 3, H, W) float32 [0,1]
        bgr_float = bgr_tensor.permute(2, 0, 1).unsqueeze(0).float() / 255.0
        
        # Letterbox resize
        resized, padding_info = letterbox_resize_cuda(bgr_float, (self.input_w, self.input_h))
        
        return resized.contiguous(), padding_info
    
    def _bind_input(self, input_tensor: torch.Tensor) -> None:
        """Bind input tensor to IO Binding (ONNX Runtime)."""
        self._io_binding.bind_input(
            name=self._input_name,
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=tuple(input_tensor.shape),
            buffer_ptr=input_tensor.data_ptr(),
        )
    
    def _bind_output(self) -> torch.Tensor:
        """Bind output tensor and return it (ONNX Runtime)."""
        # YOLO output shape varies - use dynamic shape
        out_tensor = torch.empty(
            (1, 84, 8400),  # YOLOv8/v11 typical: (batch, 84, 8400) where 84 = 4 + 80
            dtype=torch.float32,
            device=self.device
        )
        
        self._io_binding.bind_output(
            name=self._output_names[0],
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=(1, 84, 8400),
            buffer_ptr=out_tensor.data_ptr(),
        )
        
        return out_tensor
    
    def infer(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """Run inference with TensorRT or ONNX Runtime."""
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError("YOLOPersonDetector not initialized")
        
        if self._use_tensorrt:
            return self._infer_tensorrt(input_tensor)
        else:
            return self._infer_onnx(input_tensor)
    
    def _infer_tensorrt(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """Run inference with TensorRT engine."""
        input_tensors = {self._trt_executor._input_names[0]: input_tensor}
        outputs = self._trt_executor.infer(input_tensors)
        output_name = self._trt_executor._output_names[0]
        return outputs[output_name]
    
    def _infer_onnx(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """Run inference with ONNX Runtime."""
        # Clear previous bindings
        self._io_binding.clear_binding_inputs()
        self._io_binding.clear_binding_outputs()
        
        # Bind input
        self._bind_input(input_tensor)
        
        # Bind output
        output_tensor = self._bind_output()
        
        # Run inference
        start = time.perf_counter()
        self._session.run_with_iobinding(self._io_binding)
        torch.cuda.synchronize(self.device_id)
        inference_ms = (time.perf_counter() - start) * 1000
        
        # Update stats
        self._inference_count += 1
        self._total_inference_time += inference_ms
        
        return output_tensor
    
    def detect(self, frame: GPUFrame) -> List[PersonDetection]:
        """
        Run person detection on a GPUFrame.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            
        Returns:
            List of PersonDetection in ORIGINAL_FRAME coordinates
        """
        # Preprocess
        preprocess_start = time.perf_counter()
        input_tensor, padding_info = self.preprocess(frame)
        preprocess_ms = (time.perf_counter() - preprocess_start) * 1000
        
        # Inference
        output_tensor = self.infer(input_tensor)
        
        # Parse outputs
        detections = self._parse_outputs(
            output_tensor=output_tensor,
            original_width=frame.width,
            original_height=frame.height,
            padding_info=padding_info,
            frame_id=frame.frame_id,
            camera_id=frame.camera_id,
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
        output_tensor: torch.Tensor,
        original_width: int,
        original_height: int,
        padding_info: Dict[str, Any],
        frame_id: int,
        camera_id: str,
    ) -> List[PersonDetection]:
        """Parse YOLO raw outputs into PersonDetection objects."""
        detections = []
        
        # Handle different output formats
        # Format 1: (1, 84, 8400) - YOLOv8/v11
        # Format 2: (1, 8400, 84) - transposed
        # Format 3: (1, num_boxes, 85) - YOLOv5 style
        
        if output_tensor.dim() == 3:
            if output_tensor.shape[1] > output_tensor.shape[2]:
                # (1, 84, 8400) -> (1, 8400, 84)
                output_tensor = output_tensor.transpose(1, 2)
            
            # Now (1, num_boxes, 84) or (1, num_boxes, 85)
            batch, num_boxes, dims = output_tensor.shape
            
            # Get preprocessing info
            scale = padding_info["scale"]
            pad_top = padding_info["pad_top"]
            pad_left = padding_info["pad_left"]
            new_W = padding_info["new_width"]
            new_H = padding_info["new_height"]
            
            # Valid region
            valid_x1 = pad_left
            valid_y1 = pad_top
            valid_x2 = self.input_w - (self.input_w - new_W - pad_left)
            valid_y2 = self.input_h - (self.input_h - new_H - pad_top)
            
            for i in range(num_boxes):
                box_data = output_tensor[0, i]  # (84,) or (85,)
                
                # Extract bbox (cx, cy, w, h) in model input space
                cx, cy, w, h = box_data[:4]
                
                # Object confidence
                obj_conf = float(box_data[4])
                
                if obj_conf < self.yolo_config.confidence_threshold:
                    continue
                
                # Class scores
                if dims == 85:
                    class_scores = box_data[5:]
                else:
                    # YOLOv8: 80 classes starting at index 4
                    class_scores = box_data[4:]
                
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
                    frame_index=frame_id,
                    source_id=camera_id,
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
        x1 = (x1 - pad_left) / scale
        y1 = (y1 - pad_top) / scale
        x2 = (x2 - pad_left) / scale
        y2 = (y2 - pad_top) / scale
        
        x1 = max(0.0, min(x1, orig_w - 1))
        y1 = max(0.0, min(y1, orig_h - 1))
        x2 = max(0.0, min(x2, orig_w))
        y2 = max(0.0, min(y2, orig_h))
        
        return (float(x1), float(y1), float(x2), float(y2))
    
    def _apply_nms(self, detections: List[PersonDetection]) -> List[PersonDetection]:
        """Apply Non-Maximum Suppression."""
        if len(detections) <= 1:
            return detections
        
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
    
    def get_stats(self) -> Dict[str, Any]:
        backend = "tensorrt" if self._use_tensorrt else "onnxruntime"
        stats = {
            "model": "yolo",
            "backend": backend,
            "initialized": self._initialized,
            "inference_count": self._inference_count,
            "avg_inference_ms": (
                self._total_inference_time / self._inference_count 
                if self._inference_count > 0 else 0
            ),
            "last_error": self._last_error,
            "device_id": self.device_id,
        }
        
        if self._use_tensorrt and self._trt_executor:
            stats["providers"] = ["TensorRT"]
            stats["trt_stats"] = self._trt_executor.get_stats()
        elif self._session:
            stats["providers"] = self._session.get_providers()
        
        return stats
    
    def cleanup(self) -> None:
        """Release resources."""
        if self._use_tensorrt and self._trt_executor:
            self._trt_executor.cleanup()
            self._trt_executor = None
        else:
            self._session = None
            self._io_binding = None
        self._initialized = False
        torch.cuda.empty_cache()


def create_yolo_detector(
    model_path: Optional[str] = None,
    device_id: int = 0,
) -> YOLOPersonDetector:
    """Factory function to create YOLO person detector."""
    if model_path is None:
        config = get_config()
        model_config = get_model_config(config, "yolo")
        model_path = model_config.get("path", "models/yolo/yolo11n.onnx")
    
    # Prefer .engine if available
    path = Path(model_path)
    if path.suffix == '.onnx':
        engine_path = path.with_suffix('.engine')
        if engine_path.exists():
            model_path = str(engine_path)
            logger.info(f"YOLOPersonDetector: Using TensorRT engine at {engine_path}")
    
    config = YOLOConfig()
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