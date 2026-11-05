"""
SCRFD Face Detector - GPU-accelerated face detection with 5-point landmarks.

Runs SCRFD 10G entirely on GPU using TensorRT (.engine) or ONNX Runtime (.onnx) with IO Binding.
Input: GPUFrame (NV12) → Preprocessed tensor → SCRFD → Face detections.
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
class SCRFDConfig:
    """Configuration for SCRFD detector."""
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.4
    input_size: Tuple[int, int] = (640, 640)
    strides: Tuple[int, ...] = (8, 16, 32)
    anchor_scales: Dict[int, List[int]] = None
    
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


class SCRFDDetector:
    """
    SCRFD Face Detector running on GPU.
    
    Pipeline:
        GPUFrame (NV12) 
            → NV12→BGR conversion (GPU)
            → Letterbox resize to 640x640 (GPU)
            → Normalize (GPU)
            → SCRFD TensorRT/ONNX (GPU, IO Binding)
            → Parse outputs → NMS → FaceDetection list
    
    Supports both .engine (TensorRT) and .onnx (ONNX Runtime) model formats.
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[SCRFDConfig] = None,
        device_id: int = 0,
        cuda_stream: Optional[torch.cuda.Stream] = None,
    ):
        self.cuda_stream = cuda_stream
        self.scrfd_config = config or SCRFDConfig()
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
        
        # Backend selection based on model extension
        self._model_path = model_path
        self._use_tensorrt = model_path.endswith('.engine')
        
        # TensorRT executor (for .engine)
        self._trt_executor: Optional[TensorRTExecutor] = None
        
        # ONNX Runtime session (for .onnx)
        self._session = None
        self._io_binding: Optional[Any] = None
        self._input_name: str = ""
        self._output_names: List[str] = []
        
        # Preprocessing parameters
        self.input_h, self.input_w = self.scrfd_config.input_size
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)
        
        # Generate anchors once
        self._anchors: Dict[int, torch.Tensor] = {}
        self._anchor_scales: Dict[int, torch.Tensor] = {}
        self._generate_anchors()
        
        # Stats
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_error: Optional[str] = None
        self._initialized = False
    
    def _generate_anchors(self) -> None:
        """Pre-generate anchor centers and scales for each stride level."""
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
            
            self._anchors[stride] = torch.tensor(anchors, dtype=torch.float32, device=self.device)
            self._anchor_scales[stride] = torch.tensor(anchor_scales_list, dtype=torch.float32, device=self.device)
        
        logger.debug(f"SCRFDDetector: Generated anchors for strides {self.scrfd_config.strides}")
    
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
            logger.error(f"SCRFDDetector: Initialization failed: {e}")
            return False
    
    def _initialize_tensorrt(self) -> bool:
        """Initialize TensorRT executor for .engine file."""
        try:
            self._trt_executor = create_tensorrt_executor(self._model_path, self.device_id, self.cuda_stream)
            if not self._trt_executor.initialize():
                return False
            
            # Verify CUDA execution
            binding_info = self._trt_executor.get_binding_info()
            logger.info(f"SCRFDDetector: Using TensorRT engine - {len(binding_info['inputs'])} inputs, {len(binding_info['outputs'])} outputs")
            
            self._initialized = True
            logger.info(f"SCRFDDetector: Initialized TensorRT on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"SCRFDDetector: TensorRT initialization failed: {e}")
            return False
    
    def _initialize_onnx(self) -> bool:
        """Initialize ONNX Runtime session for .onnx file."""
        try:
            import onnxruntime as ort
        except ImportError:
            self._last_error = "onnxruntime not available"
            logger.error(f"SCRFDDetector: {self._last_error}")
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
                logger.info(f"SCRFDDetector: Using CUDAExecutionProvider")
            else:
                logger.warning(f"SCRFDDetector: CUDA not available, using {providers[0]}")
            
            self._initialized = True
            logger.info(f"SCRFDDetector: Initialized ONNX Runtime on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"SCRFDDetector: ONNX Runtime initialization failed: {e}")
            return False
    
    def preprocess(self, frame: GPUFrame) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """
        Preprocess GPUFrame NV12 tensor to SCRFD input format.
        
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
        
        # Normalize: (x - mean) / std
        normalized = (resized - self.mean) / self.std
        
        return normalized.contiguous(), padding_info
    
    def infer(self, input_tensor: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Run inference with TensorRT or ONNX Runtime."""
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError("SCRFDDetector not initialized")
        
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
    
    def _infer_tensorrt(self, input_tensor: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Run inference with TensorRT engine."""
        # TensorRT expects input name from engine bindings
        input_tensors = {self._trt_executor._input_names[0]: input_tensor}
        return self._trt_executor.infer(input_tensors)
    
    def _infer_onnx(self, input_tensor: torch.Tensor) -> Dict[str, torch.Tensor]:
        """Run inference with ONNX Runtime."""
        # Clear previous bindings
        self._io_binding.clear_binding_inputs()
        self._io_binding.clear_binding_outputs()
        
        # Bind input
        self._io_binding.bind_input(
            name=self._input_name,
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=tuple(input_tensor.shape),
            buffer_ptr=input_tensor.data_ptr(),
        )
        
        # Bind outputs
        output_tensors = {}
        output_infos = self._session.get_outputs()
        
        for out_info in output_infos:
            name = out_info.name
            shape = list(out_info.shape)
            if shape[0] == -1 or shape[0] == 1:
                shape[0] = 1
            
            out_tensor = torch.empty(
                shape,
                dtype=torch.float32,
                device=self.device
            )
            
            self._io_binding.bind_output(
                name=name,
                device_type='cuda',
                device_id=self.device_id,
                element_type=np.float32,
                shape=tuple(shape),
                buffer_ptr=out_tensor.data_ptr(),
            )
            
            output_tensors[name] = out_tensor
        
        # Run inference
        start = time.perf_counter()
        self._session.run_with_iobinding(self._io_binding)
        
        # CRITICAL: Synchronize stream BEFORE returning output tensors
        # Prevents CPU from reading outputs while GPU is still writing
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            stream.synchronize()
        else:
            torch.cuda.synchronize(self.device_id)
            
        inference_ms = (time.perf_counter() - start) * 1000
        
        # Update stats
        self._inference_count += 1
        self._total_inference_time += inference_ms
        
        return output_tensors
    
    def detect(self, frame: GPUFrame) -> List[FaceDetection]:
        """
        Run face detection on a GPUFrame.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            
        Returns:
            List of FaceDetection in ORIGINAL_FRAME coordinates
        """
        # Preprocess
        preprocess_start = time.perf_counter()
        input_tensor, padding_info = self.preprocess(frame)
        preprocess_ms = (time.perf_counter() - preprocess_start) * 1000
        
        # Inference
        outputs = self.infer(input_tensor)
        
        # Parse outputs
        detections = self._parse_outputs(
            outputs=outputs,
            original_width=frame.width,
            original_height=frame.height,
            padding_info=padding_info,
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
        padding_info: Dict[str, Any],
    ) -> List[FaceDetection]:
        """Parse SCRFD raw outputs into FaceDetection objects."""
        detections = []
        
        # Extract padding info
        scale = padding_info["scale"]
        pad_left = padding_info["pad_left"]
        pad_top = padding_info["pad_top"]
        new_W = padding_info["new_width"]
        new_H = padding_info["new_height"]
        
        strides = self.scrfd_config.strides
        
        for stride in strides:
            score_key = f"score_{stride}"
            bbox_key = f"bbox_{stride}"
            kps_key = f"kps_{stride}"
            
            # Find matching output keys (ONNX may have different naming)
            score_tensor = None
            bbox_tensor = None
            kps_tensor = None
            
            for key, tensor in outputs.items():
                if f"score_{stride}" in key or key.endswith(f"_{stride}"):
                    if "score" in key or "cls" in key:
                        score_tensor = tensor
                elif f"bbox_{stride}" in key or "bbox" in key:
                    bbox_tensor = tensor
                elif f"kps_{stride}" in key or "landmark" in key or "kps" in key:
                    kps_tensor = tensor
            
            if score_tensor is None or bbox_tensor is None:
                continue
            
            # Reshape scores if needed: (1, 2, H, W) -> (1, num_anchors, 2)
            if score_tensor.dim() == 4:
                score_tensor = score_tensor.permute(0, 2, 3, 1).reshape(1, -1, 2)
            
            if score_tensor.dim() == 3 and score_tensor.shape[0] == 1:
                score_tensor = score_tensor.squeeze(0)  # (num_anchors, 2)
            
            # Get max score across anchors per location
            max_scores, _ = score_tensor.max(dim=1)  # (num_anchors,)
            
            # Filter by confidence
            conf_mask = max_scores >= self.scrfd_config.confidence_threshold
            if not conf_mask.any():
                continue
            
            valid_indices = torch.where(conf_mask)[0]
            
            anchors = self._anchors[stride]
            anchor_scales = self._anchor_scales[stride]
            
            # Valid region in model input space
            valid_x1 = pad_left
            valid_y1 = pad_top
            valid_x2 = self.input_w - (self.input_w - new_W - pad_left)
            valid_y2 = self.input_h - (self.input_h - new_H - pad_top)
            
            for idx in valid_indices:
                idx = idx.item()
                confidence = float(max_scores[idx])
                
                # Decode bbox: in SCRFD 10G, bboxes are distance offsets (dl, dt, dr, db)
                anchor_cx, anchor_cy = anchors[idx]
                
                dl, dt, dr, db = bbox_tensor[0, idx]
                
                x1 = anchor_cx - dl * stride
                y1 = anchor_cy - dt * stride
                x2 = anchor_cx + dr * stride
                y2 = anchor_cy + db * stride
                
                # Check if center is in valid (non-padded) region
                center_x = (x1 + x2) / 2.0
                center_y = (y1 + y2) / 2.0
                if center_x < valid_x1 or center_x > valid_x2 or center_y < valid_y1 or center_y > valid_y2:
                    continue
                
                x1 = torch.clamp(x1, min=valid_x1, max=valid_x2)
                y1 = torch.clamp(y1, min=valid_y1, max=valid_y2)
                x2 = torch.clamp(x2, min=valid_x1, max=valid_x2)
                y2 = torch.clamp(y2, min=valid_y1, max=valid_y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                
                # Convert to original frame coordinates
                bbox_original = self._convert_bbox_to_original(
                    x1, y1, x2, y2, scale, pad_left, pad_top, original_width, original_height
                )
                
                # Decode keypoints if available
                kps_original = []
                if kps_tensor is not None:
                    kps_model = kps_tensor[0, idx].reshape(5, 2)
                    for kp_idx in range(5):
                        kp_dx, kp_dy = kps_model[kp_idx]
                        kp_x = anchor_cx + kp_dx * stride
                        kp_y = anchor_cy + kp_dy * stride
                        kp_orig = self._convert_point_to_original(
                            kp_x, kp_y, scale, pad_left, pad_top, original_width, original_height
                        )
                        kps_original.append(kp_orig)
                else:
                    # Default 5 points at face center/corners (fallback)
                    cx_orig, cy_orig = self._convert_point_to_original(
                        cx, cy, scale, pad_left, pad_top, original_width, original_height
                    )
                    w_orig = (x2 - x1) / scale
                    h_orig = (y2 - y1) / scale
                    kps_original = [
                        (cx_orig - w_orig/3, cy_orig - h_orig/3),  # left eye
                        (cx_orig + w_orig/3, cy_orig - h_orig/3),  # right eye
                        (cx_orig, cy_orig),                          # nose
                        (cx_orig - w_orig/4, cy_orig + h_orig/3),   # left mouth
                        (cx_orig + w_orig/4, cy_orig + h_orig/3),   # right mouth
                    ]
                
                detection = FaceDetection(
                    bbox=bbox_original,
                    confidence=confidence,
                    landmarks5=kps_original,
                    detection_id=str(uuid.uuid4())[:8],
                    frame_index=frame.frame_id,
                    source_id=frame.camera_id,
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
    
    def get_stats(self) -> Dict[str, Any]:
        backend = "tensorrt" if self._use_tensorrt else "onnxruntime"
        stats = {
            "model": "scrfd",
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


def create_scrfd_detector(
    model_path: Optional[str] = None,
    device_id: int = 0,
) -> SCRFDDetector:
    """Factory function to create SCRFD detector."""
    if model_path is None:
        config = get_config()
        model_config = get_model_config(config, "scrfd")
        model_path = model_config.get("path", "models/scrfd/scrfd_10g_bnkps.onnx")
    
    # Prefer .engine if available
    path = Path(model_path)
    if path.suffix == '.onnx':
        engine_path = path.with_suffix('.engine')
        if engine_path.exists():
            model_path = str(engine_path)
            logger.info(f"SCRFDDetector: Using TensorRT engine at {engine_path}")
    
    config = SCRFDConfig()
    return SCRFDDetector(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/scrfd/scrfd_10g_bnkps.onnx"
    detector = create_scrfd_detector(model_path)
    
    if detector.initialize():
        print("SCRFD detector initialized successfully!")
        print(f"Stats: {detector.get_stats()}")
    else:
        print("SCRFD detector initialization failed")