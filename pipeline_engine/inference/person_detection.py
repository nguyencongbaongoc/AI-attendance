"""
YOLO Person Detector - GPU-accelerated person detection.

Runs YOLO11n entirely on GPU using TensorRT (.engine) or ONNX Runtime (.onnx) with IO Binding.
Input: GPUFrame (NV12) → Preprocess → YOLO TensorRT/ONNX → Person detections.
"""

from __future__ import annotations

import logging
import threading
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
    confidence_threshold: float = 0.40
    nms_threshold: float = 0.45
    input_size: Tuple[int, int] = (640, 640)
    person_class_id: int = 0
    max_detections: int = 100
    # Geometric sanity filters
    max_aspect_ratio: float = 2.5  # Reject boxes with w/h > 2.5 (horizontal artifacts)
    min_box_area: float = 400.0    # Min area in original frame (20x20)


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
        cuda_stream: Optional[torch.cuda.Stream] = None,
    ):
        self.yolo_config = config or YOLOConfig()
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # Store CUDA stream for parallel execution
        self.cuda_stream = cuda_stream
        
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
        
        # Thread safety lock for concurrent access
        self._lock = threading.RLock()
    
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
            self._trt_executor = create_tensorrt_executor(self._model_path, self.device_id, self.cuda_stream)
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
        
        # Run inference within the camera's CUDA stream if provided
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            with torch.cuda.stream(stream):
                if self._use_tensorrt:
                    return self._infer_tensorrt(input_tensor)
                else:
                    return self._infer_onnx(input_tensor)
        else:
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
        
        # CRITICAL: Synchronize stream BEFORE returning output tensor
        # Prevents CPU from reading output while GPU is still writing
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            stream.synchronize()
        else:
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
        with self._lock:
            # Debug: Log input frame format
            try:
                y_tensor, uv_tensor = frame.get_tensors()
                logger.debug(f"[YOLO_IN] shape=({y_tensor.shape}, {uv_tensor.shape}), dtype={y_tensor.dtype}, min={y_tensor.min().item()}, max={y_tensor.max().item()}")
            except Exception as e:
                logger.debug(f"[YOLO_IN] Could not log frame format: {e}")
            
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
            
            # Log detection count
            logger.info(f"[YOLO_RESULT] Detected {len(detections)} persons")
            
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
        # Format 1: (1, 84, 8400) - YOLOv8/v11 raw TensorRT output
        # Format 2: (1, 8400, 84) - transposed
        # Format 3: (1, num_boxes, 85) - YOLOv5 style
        
        # DEBUG: Log output tensor shape
        logger.debug(f"[YOLO_PARSE] Raw output shape: {output_tensor.shape}")
        
        if output_tensor.dim() == 3:
            # YOLOv11 TensorRT raw output is typically (1, 84, 8400) where 84 = 4 box coords + 80 classes
            if output_tensor.shape[1] < output_tensor.shape[2]:
                # (1, 84, 8400) -> transpose to (1, 8400, 84)
                output_tensor = output_tensor.transpose(1, 2)
                logger.debug(f"[YOLO_PARSE] Transposed to: {output_tensor.shape}")
            
            # Now (1, num_boxes, 84) or (1, num_boxes, 85)
            batch, num_boxes, dims = output_tensor.shape
            
            # Get preprocessing info
            scale = padding_info["scale"]
            pad_top = padding_info["pad_top"]
            pad_left = padding_info["pad_left"]
            new_W = padding_info["new_width"]
            new_H = padding_info["new_height"]
            
            # Valid region - the image is placed at (pad_left, pad_top) with size (new_W, new_H)
            valid_x1 = pad_left
            valid_y1 = pad_top
            valid_x2 = pad_left + new_W
            valid_y2 = pad_top + new_H
            
            # Extract box coordinates (channels 0-3): [cx, cy, w, h] in letterboxed input space [0..640]
            box_coords = output_tensor[:, :, :4]
            
            # Extract class scores (channels 4-83): 80 classes
            class_scores_raw = output_tensor[:, :, 4:4+80]
            
            # Ultralytics YOLOv11 ONNX export already applies sigmoid in the Detect head.
            # The output channels 4:84 are already probabilities in [0.0, 1.0].
            # Only apply sigmoid if model outputs raw logits (values outside [0, 1]).
            person_scores = class_scores_raw[0, :, 0]  # Class 0: person
            if person_scores.min() < -0.01 or person_scores.max() > 1.01:
                class_probs = torch.sigmoid(torch.clamp(class_scores_raw, -50.0, 50.0))
                logger.debug("[YOLO_PARSE] Applied sigmoid to class scores (raw logits detected)")
            else:
                class_probs = class_scores_raw
                logger.debug("[YOLO_PARSE] Class scores already in [0,1] range (no sigmoid applied)")
            
            for i in range(num_boxes):
                # Get box coordinates [cx, cy, w, h] in model input space [0..640]
                cx = float(box_coords[0, i, 0])
                cy = float(box_coords[0, i, 1])
                w = float(box_coords[0, i, 2])
                h = float(box_coords[0, i, 3])
                
                # Convert center format to corners in model input space
                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                
                # Get class probabilities
                class_scores = class_probs[0, i]
                
                class_id = int(torch.argmax(class_scores))
                class_conf = float(class_scores[class_id])
                
                # YOLOv8/v11 uses class confidence directly (no separate object confidence)
                confidence = class_conf
                
                if confidence < self.yolo_config.confidence_threshold:
                    continue
                
                # Only keep person class (class_id == 0)
                if class_id != self.yolo_config.person_class_id:
                    continue
                
                # Check if in valid region (remove padding)
                if x1 < valid_x1 or x2 > valid_x2 or y1 < valid_y1 or y2 > valid_y2:
                    continue
                
                # Convert to original frame coordinates
                bbox_original = self._convert_bbox_to_original(
                    x1, y1, x2, y2, scale, pad_left, pad_top, new_W, new_H, original_width, original_height
                )
                
                # Filter out absurdly small boxes (likely false positives)
                box_w = bbox_original[2] - bbox_original[0]
                box_h = bbox_original[3] - bbox_original[1]
                if box_w < 20.0 or box_h < 20.0:
                    continue
                
                # Geometric sanity filter: reject boxes with extreme aspect ratio (horizontal artifacts/desk edges)
                # Guard against division by zero
                if box_h <= 1.0:
                    continue  # Discard degenerate zero-height box
                aspect_ratio = box_w / box_h
                if aspect_ratio > self.yolo_config.max_aspect_ratio:
                    continue
                
                # Filter by minimum area
                box_area = box_w * box_h
                if box_area < self.yolo_config.min_box_area:
                    continue
                
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
        new_W: int, new_H: int,
        orig_w: int, orig_h: int
    ) -> Tuple[float, float, float, float]:
        """Convert bbox from model input space to original frame space.
        
        Correctly accounts for asymmetric letterbox padding:
        - Image is resized to (new_W, new_H) maintaining aspect ratio
        - Then placed at (pad_left, pad_top) in the 640x640 canvas
        - scale = new_W / orig_w = new_H / orig_h
        """
        # Remove padding offset and scale back to original coordinates in one step
        # (x - pad) / scale = x * (orig_w / new_W) - pad * (orig_w / new_W)
        # This correctly handles asymmetric padding
        inv_scale = 1.0 / scale
        
        x1 = (x1 - pad_left) * inv_scale
        y1 = (y1 - pad_top) * inv_scale
        x2 = (x2 - pad_left) * inv_scale
        y2 = (y2 - pad_top) * inv_scale
        
        # Final clamp to original frame
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