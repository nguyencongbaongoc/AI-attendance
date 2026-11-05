"""
Body Re-ID Detector - GPU-accelerated body embedding extraction.

Runs ResNet50 ReID entirely on GPU using TensorRT (.engine) or ONNX Runtime (.onnx) with IO Binding.
Input: Person crop (256x128) → Normalize → ReID TensorRT/ONNX → 2048D embedding (L2 normalized).
"""

from __future__ import annotations

import logging
import time
import numpy as np
import torch
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path

from pipeline_engine.memory.gpu_frame import GPUFrame, nv12_to_bgr_cuda, letterbox_resize_cuda
from pipeline_engine.config import get_config, get_model_config
from pipeline_engine.inference.tensorrt_engine import TensorRTExecutor, create_tensorrt_executor

logger = logging.getLogger(__name__)


@dataclass
class ReIDConfig:
    """Configuration for Body ReID detector."""
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.4
    input_size: Tuple[int, int] = (128, 256)  # (width, height) = (128, 256) for ReID
    embedding_dim: int = 2048


@dataclass
class BodyEmbedding:
    """Body embedding result."""
    embedding: torch.Tensor  # (2048,) float32 on CUDA, L2 normalized
    raw_embedding: torch.Tensor  # (2048,) float32 before normalization
    raw_norm: float
    inference_time_ms: float
    detection_id: str
    frame_index: int = 0
    source_id: str = ""
    body_quality: float = 0.0
    
    def to_numpy(self) -> np.ndarray:
        """Convert to numpy array (copies to CPU)."""
        return self.embedding.cpu().numpy()
    
    def cosine_similarity(self, other: "BodyEmbedding") -> float:
        """Compute cosine similarity with another embedding."""
        return float(torch.dot(self.embedding, other.embedding))


class ReIDDetector:
    """
    Body ReID Detector running on GPU.
    
    Pipeline:
        Person crop from GPUFrame (NV12) 
            → NV12→BGR conversion (GPU)
            → Crop person bbox
            → Letterbox resize to 256x128 (GPU)
            → Normalize [0,1] (GPU)
            → ReID TensorRT/ONNX (GPU, IO Binding)
            → L2 normalize embedding (GPU)
            → BodyEmbedding
    
    Supports both .engine (TensorRT) and .onnx (ONNX Runtime) model formats.
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[ReIDConfig] = None,
        device_id: int = 0,
        cuda_stream: Optional[torch.cuda.Stream] = None,
    ):
        self.reid_config = config or ReIDConfig()
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
        
        # Preprocessing parameters
        self.input_w, self.input_h = self.reid_config.input_size  # (128, 256)
        self.mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self.std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)
        
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
            logger.error(f"ReIDDetector: Initialization failed: {e}")
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
            logger.info(f"ReIDDetector: Using TensorRT engine - {len(binding_info['inputs'])} inputs, {len(binding_info['outputs'])} outputs")
            
            self._initialized = True
            logger.info(f"ReIDDetector: Initialized TensorRT on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ReIDDetector: TensorRT initialization failed: {e}")
            return False
    
    def _initialize_onnx(self) -> bool:
        """Initialize ONNX Runtime session for .onnx file."""
        try:
            import onnxruntime as ort
        except ImportError:
            self._last_error = "onnxruntime not available"
            logger.error(f"ReIDDetector: {self._last_error}")
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
                logger.info(f"ReIDDetector: Using CUDAExecutionProvider")
            else:
                logger.warning(f"ReIDDetector: CUDA not available, using {providers[0]}")
            
            self._initialized = True
            logger.info(f"ReIDDetector: Initialized ONNX Runtime on device {self.device_id}")
            return True
            
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"ReIDDetector: ONNX Runtime initialization failed: {e}")
            return False
    
    def preprocess(self, frame: GPUFrame, person_bbox: Tuple[float, float, float, float]) -> torch.Tensor:
        """
        Preprocess person crop from GPUFrame to ReID input format.
        
        Args:
            frame: GPUFrame with NV12 tensors on GPU
            person_bbox: Person bounding box (x1, y1, x2, y2) in original frame coordinates
            
        Returns:
            Preprocessed tensor: (1, 3, 256, 128) float32 normalized
        """
        # Convert NV12 to BGR on GPU
        y_tensor, uv_tensor = frame.get_tensors()
        bgr_tensor = nv12_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) uint8
        
        # Crop person bbox
        x1, y1, x2, y2 = [int(c) for c in person_bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(bgr_tensor.shape[1], x2), min(bgr_tensor.shape[0], y2)
        
        if x2 <= x1 or y2 <= y1:
            # Invalid bbox - return zero tensor
            return torch.zeros(1, 3, self.input_h, self.input_w, device=self.device, dtype=torch.float32)
        
        person_crop = bgr_tensor[y1:y2, x1:x2]
        
        # Convert to float and normalize: (H, W, 3) -> (1, 3, H, W) float32 [0,1]
        bgr_float = person_crop.permute(2, 0, 1).unsqueeze(0).float() / 255.0
        
        # Letterbox resize to ReID input size (128x256)
        resized, _ = letterbox_resize_cuda(bgr_float, (self.input_w, self.input_h))
        
        # Normalize: (x - mean) / std
        normalized = (resized - self.mean) / self.std
        
        return normalized.contiguous()
    
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
        out_tensor = torch.empty(
            (1, self.reid_config.embedding_dim),
            dtype=torch.float32,
            device=self.device
        )
        
        self._io_binding.bind_output(
            name=self._output_names[0],
            device_type='cuda',
            device_id=self.device_id,
            element_type=np.float32,
            shape=(1, self.reid_config.embedding_dim),
            buffer_ptr=out_tensor.data_ptr(),
        )
        
        return out_tensor
    
    def infer_raw(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference (without L2 normalization) with TensorRT or ONNX Runtime."""
        if not self._initialized:
            self.initialize()
        
        if not self._initialized:
            raise RuntimeError("ReIDDetector not initialized")
        
        # Run inference within the camera's CUDA stream if provided
        stream = getattr(self, "cuda_stream", None)
        if stream is not None:
            with torch.cuda.stream(stream):
                if self._use_tensorrt:
                    return self._infer_raw_tensorrt(input_tensor)
                else:
                    return self._infer_raw_onnx(input_tensor)
        else:
            if self._use_tensorrt:
                return self._infer_raw_tensorrt(input_tensor)
            else:
                return self._infer_raw_onnx(input_tensor)
    
    def _infer_raw_tensorrt(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference with TensorRT engine."""
        input_tensors = {self._trt_executor._input_names[0]: input_tensor}
        outputs = self._trt_executor.infer(input_tensors)
        output_name = self._trt_executor._output_names[0]
        output_tensor = outputs[output_name].squeeze(0)
        return output_tensor, 0.0  # timing handled by TensorRTExecutor
    
    def _infer_raw_onnx(self, input_tensor: torch.Tensor) -> Tuple[torch.Tensor, float]:
        """Run raw inference with ONNX Runtime."""
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
        
        return output_tensor.squeeze(0), inference_ms  # (2048,), ms
    
    def infer_embedding(self, frame: GPUFrame, person_bbox: Tuple[float, float, float, float], detection_id: str, frame_index: int, source_id: str) -> BodyEmbedding:
        """
        Run inference on person crop and return L2-normalized embedding.
        
        Args:
            frame: GPUFrame with NV12 tensors
            person_bbox: Person bounding box in original frame coordinates
            detection_id: Person detection ID
            frame_index: Frame index
            source_id: Camera/source ID
            
        Returns:
            BodyEmbedding with L2 normalized embedding
        """
        # Preprocess
        preprocessed = self.preprocess(frame, person_bbox)
        
        # Raw inference
        raw_embedding, inference_ms = self.infer_raw(preprocessed)
        
        # L2 normalize
        raw_norm = float(torch.norm(raw_embedding))
        if raw_norm > 0:
            normalized_embedding = raw_embedding / raw_norm
        else:
            normalized_embedding = raw_embedding
            raw_norm = 0.0
        
        return BodyEmbedding(
            embedding=normalized_embedding,
            raw_embedding=raw_embedding,
            raw_norm=raw_norm,
            inference_time_ms=inference_ms,
            detection_id=detection_id,
            frame_index=frame_index,
            source_id=source_id,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        backend = "tensorrt" if self._use_tensorrt else "onnxruntime"
        stats = {
            "model": "reid",
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


def create_reid_detector(
    model_path: Optional[str] = None,
    device_id: int = 0,
) -> ReIDDetector:
    """Factory function to create ReID detector."""
    if model_path is None:
        config = get_config()
        model_config = get_model_config(config, "reid")
        model_path = model_config.get("path", "models/reid/resnet50_reid.onnx")
    
    # Prefer .engine if available
    path = Path(model_path)
    if path.suffix == '.onnx':
        engine_path = path.with_suffix('.engine')
        if engine_path.exists():
            model_path = str(engine_path)
            logger.info(f"ReIDDetector: Using TensorRT engine at {engine_path}")
    
    config = ReIDConfig()
    return ReIDDetector(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/reid/resnet50_reid.onnx"
    detector = create_reid_detector(model_path)
    
    if detector.initialize():
        print("ReID detector initialized successfully!")
        print(f"Stats: {detector.get_stats()}")
    else:
        print("ReID detector initialization failed")