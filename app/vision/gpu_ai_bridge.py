"""
Phase 11 WP1 — GPU AI Bridge: Zero-Copy Path from GPUFrameContract to All AI Models.

Provides a unified bridge from pynvvideocodec GPUFrameContract output
through GPU preprocessing to TensorRT Shared Singleton for all 4 models:
- SCRFD Face Detection (640x640)
- ArcFace Recognition (112x112) 
- YOLO Person Detection (640x640)
- ResNet50 ReID (256x128)

All operations stay on cuda:0 end-to-end with zero CPU memory copies.
Models are loaded ONCE into GPU VRAM and shared across cameras.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract, nv12_cuda_to_bgr_cuda, nv12_cuda_to_rgb_cuda
from app.vision.gpu_preprocessing import GPUPreprocessor, GPUPreprocessingResult, create_gpu_preprocessor, align_face_gpu_5pt
from app.vision.shared_gpu_engine import SharedGPUEngine, create_shared_gpu_engine
from app.vision.yolo_person_detector import get_person_detector, PersonDetection

logger = logging.getLogger(__name__)


@dataclass
class GPUAIInput:
    """Input to the GPU AI Bridge."""
    gpu_frame: GPUFrameContract
    camera_id: str
    frame_index: int
    timestamp: float


@dataclass
class GPUAIOutput:
    """Output from the GPU AI Bridge - all tensors on GPU as torch.Tensor."""
    # SCRFD outputs (face boxes, landmarks, scores)
    scrfd_outputs: Dict[str, torch.Tensor]
    scrfd_inference_ms: float
    
    # ArcFace outputs (512D embeddings)
    arcface_outputs: List[torch.Tensor]
    arcface_inference_ms: float
    
    # YOLO outputs (person boxes)
    yolo_outputs: List[PersonDetection]
    yolo_inference_ms: float
    
    # ReID outputs (2048D embeddings)
    reid_outputs: List[torch.Tensor]
    reid_inference_ms: float
    
    # Preprocessing results (for coordinate mapping)
    scrfd_prep: Optional[GPUPreprocessingResult] = None
    arcface_prep: Optional[GPUPreprocessingResult] = None
    yolo_prep: Optional[GPUPreprocessingResult] = None
    reid_prep: Optional[GPUPreprocessingResult] = None
    
    # Total pipeline timing
    total_preprocessing_ms: float = 0.0
    total_inference_ms: float = 0.0
    pipeline_id: str = ""
    
    # Timestamp tracking (nanoseconds)
    t_ai_preprocess_start_ns: int = 0
    t_ai_inference_start_ns: int = 0
    t_ai_inference_done_ns: int = 0
    
    def __post_init__(self):
        if not self.pipeline_id:
            self.pipeline_id = str(uuid.uuid4())[:8]


class GPUAIBridge:
    """
    Zero-Copy GPU AI Bridge with Shared Singleton Models.
    
    Takes GPUFrameContract (NV12 CUDA tensors from pynvvideocodec)
    and runs all 4 AI models entirely on GPU via TensorRT.
    
    Models are loaded ONCE via SharedGPUEngine singleton.
    """

    def __init__(
        self,
        device_id: int = 0,
    ):
        self.device_id = device_id
        self.device = torch.device(f"cuda:{device_id}")
        self._shared_engine = create_shared_gpu_engine(device_id=device_id)
        self._initialized = False
        
        # Preprocessors (one per model)
        self.scrfd_preprocessor: Optional[GPUPreprocessor] = None
        self.arcface_preprocessor: Optional[GPUPreprocessor] = None
        self.yolo_preprocessor: Optional[GPUPreprocessor] = None
        self.reid_preprocessor: Optional[GPUPreprocessor] = None
        
        # YOLO detector (uses ultralytics)
        self.yolo_detector = None
        
        # Timing instrumentation (nanoseconds)
        self.t_ai_preprocess_start_ns: int = 0
        self.t_ai_inference_start_ns: int = 0
        self.t_ai_inference_done_ns: int = 0

    def initialize(self) -> bool:
        """Initialize shared engine and preprocessors."""
        if self._initialized:
            return True
        
        try:
            # Initialize shared GPU engine (loads all models once)
            logger.info("Initializing Shared GPU Engine...")
            if not self._shared_engine.initialize():
                logger.error("Shared GPU Engine initialization failed")
                return False
            
            # Initialize preprocessors
            logger.info("Initializing preprocessors...")
            self.scrfd_preprocessor = create_gpu_preprocessor(
                model_id="scrfd",
                device=torch.device(f"cuda:{self.device_id}"),
                reuse_buffers=True,
                full_gpu=True,
            )
            
            self.arcface_preprocessor = create_gpu_preprocessor(
                model_id="arcface",
                device=torch.device(f"cuda:{self.device_id}"),
                reuse_buffers=True,
                full_gpu=True,
            )
            
            self.yolo_preprocessor = create_gpu_preprocessor(
                model_id="yolo_person",
                device=torch.device(f"cuda:{self.device_id}"),
                reuse_buffers=True,
                full_gpu=True,
            )
            
            self.reid_preprocessor = create_gpu_preprocessor(
                model_id="reid",
                device=torch.device(f"cuda:{self.device_id}"),
                reuse_buffers=True,
                full_gpu=True,
            )
            
            # Initialize YOLO detector
            self._init_yolo_detector()
            
            self._initialized = True
            logger.info("GPU AI Bridge initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize GPU AI Bridge: {e}")
            self._cleanup()
            return False

    def _init_yolo_detector(self):
        """Initialize YOLO person detector with GPU path."""
        try:
            self.yolo_detector = get_person_detector(
                model_id="yolo_person",
                confidence_threshold=0.5,
                allow_fallback=False,
            )
            logger.info("YOLO person detector initialized")
        except Exception as e:
            logger.warning(f"YOLO GPU init warning: {e}")

    def _cleanup(self):
        """Clean up GPU resources."""
        if self._shared_engine:
            self._shared_engine.close()
        self._initialized = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def process_frame(self, input_data: GPUAIInput) -> GPUAIOutput:
        """
        Process a single frame through all 4 AI models on GPU.
        
        Pipeline:
        1. NV12 -> BGR (GPU)
        2. Preprocess for each model (GPU, parallel where possible)
        3. Inference with TensorRT shared engine (GPU, sequential)
        4. Return GPU-resident torch.Tensor outputs
        """
        if not self._initialized:
            if not self.initialize():
                raise RuntimeError("GPU AI Bridge not initialized")
        
        gpu_frame = input_data.gpu_frame
        pipeline_id = str(uuid.uuid4())[:8]
        
        logger.debug(f"[GPU_BRIDGE {pipeline_id}] Processing frame {input_data.frame_index} from {input_data.camera_id}")
        
        # ===== TIMING: Preprocess Start =====
        self.t_ai_preprocess_start_ns = time.time_ns()
        t_preprocess_start = time.perf_counter()
        
        # Step 1: Create CanonicalFrame wrappers with GPUFrameContract for each model
        from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
        
        base_metadata = FrameMetadata(
            source_type=SourceType.RTSP,
            source_id=input_data.camera_id,
            frame_index=input_data.frame_index,
            timestamp=input_data.timestamp,
            original_width=gpu_frame.width,
            original_height=gpu_frame.height,
            pixel_format=PixelFormat.NV12,
            source_fps=30.0,
        )
        
        canonical_frame = CanonicalFrame(
            data=gpu_frame,
            metadata=base_metadata
        )
        
        # Step 2: Preprocess for each model (GPU-resident)
        prep_results = {}
        
        # SCRFD: expects RGB, 640x640 letterbox
        t0 = time.perf_counter()
        prep_results['scrfd'] = self.scrfd_preprocessor.preprocess(canonical_frame)
        logger.debug(f"[GPU_BRIDGE {pipeline_id}] SCRFD preprocess: {(time.perf_counter()-t0)*1000:.1f}ms")
        
        # ArcFace: expects RGB, 112x112 crop (will be done per face)
        prep_results['arcface'] = self.arcface_preprocessor
        
        # YOLO: expects CanonicalFrame with GPUFrameContract data
        prep_results['yolo'] = canonical_frame
        
        # ReID: expects RGB, 256x128 fit (crop per person)
        prep_results['reid'] = self.reid_preprocessor
        
        total_preprocess_ms = (time.perf_counter() - t_preprocess_start) * 1000
        self.t_ai_inference_start_ns = time.time_ns()
        
        # ===== TIMING: Inference Start =====
        t_inference_start = time.perf_counter()
        
        # 3a. SCRFD Face Detection (TensorRT shared)
        t0 = time.perf_counter()
        scrfd_input = prep_results['scrfd'].tensor
        scrfd_result = self._shared_engine.infer("scrfd", scrfd_input)
        scrfd_inference_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"[GPU_BRIDGE {pipeline_id}] SCRFD inference: {scrfd_inference_ms:.1f}ms")
        
        # 3b. YOLO Person Detection (ultralytics on GPU)
        t0 = time.perf_counter()
        yolo_detections: List[PersonDetection] = self.yolo_detector.detect(canonical_frame)
        yolo_inference_ms = (time.perf_counter() - t0) * 1000
        logger.debug(f"[GPU_BRIDGE {pipeline_id}] YOLO inference: {yolo_inference_ms:.1f}ms ({len(yolo_detections)} persons)")
        
        # 3c. ArcFace Recognition (per face detection from SCRFD)
        arcface_outputs = []
        arcface_inference_ms = 0.0
        scrfd_prep = prep_results['scrfd']
        
        face_crops = self._extract_face_crops(scrfd_result, scrfd_prep, canonical_frame)
        
        if face_crops:
            t0 = time.perf_counter()
            arcface_outputs, arcface_inference_ms = self._run_arcface_batch(face_crops)
            logger.debug(f"[GPU_BRIDGE {pipeline_id}] ArcFace inference: {arcface_inference_ms:.1f}ms ({len(face_crops)} faces)")
        
        # 3d. ReID Person Embedding (per person detection from YOLO)
        reid_outputs = []
        reid_inference_ms = 0.0
        
        if yolo_detections:
            t0 = time.perf_counter()
            reid_outputs, reid_inference_ms = self._run_reid_batch(yolo_detections, canonical_frame)
            logger.debug(f"[GPU_BRIDGE {pipeline_id}] ReID inference: {reid_inference_ms:.1f}ms ({len(yolo_detections)} persons)")
        
        total_inference_ms = (time.perf_counter() - t_inference_start) * 1000
        self.t_ai_inference_done_ns = time.time_ns()
        
        return GPUAIOutput(
            scrfd_outputs=scrfd_result,
            scrfd_inference_ms=scrfd_inference_ms,
            arcface_outputs=arcface_outputs,
            arcface_inference_ms=arcface_inference_ms,
            yolo_outputs=yolo_detections,
            yolo_inference_ms=yolo_inference_ms,
            reid_outputs=reid_outputs,
            reid_inference_ms=reid_inference_ms,
            scrfd_prep=prep_results['scrfd'],
            arcface_prep=None,
            yolo_prep=None,
            reid_prep=None,
            total_preprocessing_ms=total_preprocess_ms,
            total_inference_ms=total_inference_ms,
            pipeline_id=pipeline_id,
        )

    def _extract_face_crops(
        self,
        scrfd_result: Dict[str, torch.Tensor],
        scrfd_prep: GPUPreprocessingResult,
        canonical_frame: CanonicalFrame,
    ) -> List[torch.Tensor]:
        """
        Extract face crops from SCRFD outputs for ArcFace.
        Uses GPU 5-point landmark alignment to match Backend enrollment pipeline.
        Returns list of GPU tensors (112x112 RGB) ready for ArcFace.
        """
        # Import here to avoid circular dependency
        from app.vision.gpu_preprocessing import align_face_gpu_5pt, get_canonical_landmarks_112
        
        face_crops = []
        
        # Get SCRFD outputs - 9 tensors
        # Keys from model: scores (3), bboxes (3), kps (3)
        outputs_list = list(scrfd_result.values())
        
        if len(outputs_list) != 9:
            logger.warning(f"Expected 9 SCRFD outputs, got {len(outputs_list)}")
            return face_crops
        
        # Get preprocessing info
        scale_factor = scrfd_prep.scale_factor or 1.0
        padding = scrfd_prep.padding_applied or (0, 0, 0, 0)
        pad_top, pad_bottom, pad_left, pad_right = padding
        
        input_height = self.scrfd_preprocessor.contract.input_height  # 640
        input_width = self.scrfd_preprocessor.contract.input_width    # 640
        
        # Parse SCRFD outputs
        score_outputs = outputs_list[:3]    # score_8, score_16, score_32
        bbox_outputs = outputs_list[3:6]    # bbox_8, bbox_16, bbox_32
        kps_outputs = outputs_list[6:]      # kps_8, kps_16, kps_32
        strides = [8, 16, 32]
        
        # Get original frame dimensions
        original_width = canonical_frame.metadata.original_width
        original_height = canonical_frame.metadata.original_height
        
        # Get RGB tensor from NV12 frame
        y_tensor, uv_tensor = canonical_frame.data.get_tensors()
        rgb_tensor = nv12_cuda_to_rgb_cuda(y_tensor, uv_tensor)  # (H, W, 3) on GPU
        
        # Process each feature map level
        for level_idx in range(3):
            stride = strides[level_idx]
            scores = score_outputs[level_idx].squeeze() if score_outputs[level_idx].ndim > 1 else score_outputs[level_idx]
            bboxes = bbox_outputs[level_idx].squeeze() if bbox_outputs[level_idx].ndim > 1 else bbox_outputs[level_idx]
            keypoints = kps_outputs[level_idx].squeeze() if kps_outputs[level_idx].ndim > 1 else kps_outputs[level_idx]
            
            if scores.ndim > 1:
                scores = scores.squeeze()
            if bboxes.ndim > 2:
                bboxes = bboxes.squeeze(0)
            if keypoints.ndim > 2:
                keypoints = keypoints.squeeze(0)
            
            num_anchors = scores.shape[0]
            
            # Generate anchors for this level
            anchors, anchor_scales = self._generate_anchors_gpu(stride, input_height, input_width)
            
            # Filter by confidence threshold
            conf_mask = scores >= 0.5  # SCRFD default threshold
            if not conf_mask.any():
                continue
            
            valid_indices = torch.where(conf_mask)[0]
            
            # Process each valid detection
            for idx in valid_indices[:5]:  # Limit to top 5 faces per level
                i = idx.item()
                confidence = scores[i].item()
                
                # Decode bbox
                dx, dy, dw, dh = bboxes[i]
                anchor_cx, anchor_cy = anchors[i]
                
                cx = anchor_cx + dx * stride
                cy = anchor_cy + dy * stride
                w = torch.exp(dw) * anchor_scales[i]
                h = torch.exp(dh) * anchor_scales[i]
                
                x1 = cx - w / 2
                y1 = cy - h / 2
                x2 = cx + w / 2
                y2 = cy + h / 2
                
                # Check padding
                if x1 < pad_left or x2 > (input_width - pad_right) or y1 < pad_top or y2 > (input_height - pad_bottom):
                    continue
                
                # Convert to original frame coordinates
                bbox_orig_x1 = (x1 - pad_left) / scale_factor
                bbox_orig_y1 = (y1 - pad_top) / scale_factor
                bbox_orig_x2 = (x2 - pad_left) / scale_factor
                bbox_orig_y2 = (y2 - pad_top) / scale_factor
                
                # Decode 5 keypoints
                kps = keypoints[i].reshape(5, 2)
                landmarks_5pt = torch.zeros((5, 2), device=kps.device, dtype=kps.dtype)
                for kp_idx in range(5):
                    kp_dx, kp_dy = kps[kp_idx]
                    landmarks_5pt[kp_idx, 0] = (anchor_cx + kp_dx * stride - pad_left) / scale_factor
                    landmarks_5pt[kp_idx, 1] = (anchor_cy + kp_dy * stride - pad_top) / scale_factor
                
                # Crop face from original RGB frame
                x1_int = int(torch.clamp(bbox_orig_x1, 0, original_width - 1).item())
                y1_int = int(torch.clamp(bbox_orig_y1, 0, original_height - 1).item())
                x2_int = int(torch.clamp(bbox_orig_x2, 0, original_width).item())
                y2_int = int(torch.clamp(bbox_orig_y2, 0, original_height).item())
                
                if x2_int <= x1_int or y2_int <= y1_int:
                    continue
                
                face_crop = rgb_tensor[y1_int:y2_int, x1_int:x2_int]
                
                # Apply 5-point alignment on GPU
                try:
                    aligned_face = align_face_gpu_5pt(
                        face_crop,
                        landmarks_5pt,
                        target_size=(112, 112),
                        pixel_format="rgb",
                    )
                    
                    # Ensure output is RGB float32 in [0, 255] range for ArcFace preprocessor
                    # align_face_gpu_5pt returns HWC float32 in [0, 255] if input was uint8
                    # ArcFace preprocessor expects RGB and handles normalization
                    
                    face_crops.append(aligned_face)
                    
                except Exception as e:
                    logger.warning(f"5-pt alignment failed for face: {e}")
                    continue
        
        return face_crops
    
    def _generate_anchors_gpu(self, stride: int, input_height: int, input_width: int):
        """Generate anchor centers on GPU for a given stride."""
        fm_h = input_height // stride
        fm_w = input_width // stride
        
        # Generate anchor centers (cx, cy) and scales
        shift_x = torch.arange(fm_w, device=self.device) * stride + stride // 2
        shift_y = torch.arange(fm_h, device=self.device) * stride + stride // 2
        
        shift_y, shift_x = torch.meshgrid(shift_y, shift_x, indexing='ij')
        anchors = torch.stack([shift_x.flatten(), shift_y.flatten()], dim=1).float()
        anchor_scales = torch.full((anchors.shape[0],), float(stride * 4), device=self.device, dtype=torch.float32)
        
        return anchors, anchor_scales

    def _run_arcface_batch(self, face_crops: List[torch.Tensor]) -> Tuple[List[torch.Tensor], float]:
        """Run ArcFace inference on batch of face crops via shared engine."""
        if not face_crops:
            return [], 0.0
        
        # Stack into batch
        batch_tensor = torch.stack(face_crops)
        
        # Ensure NCHW format
        if batch_tensor.dim() == 4 and batch_tensor.shape[1] == 3:
            pass
        elif batch_tensor.dim() == 4 and batch_tensor.shape[3] == 3:
            batch_tensor = batch_tensor.permute(0, 3, 1, 2).contiguous()
        
        # Run ArcFace via shared engine
        outputs = self._shared_engine.infer("arcface", batch_tensor)
        output_tensor = outputs[list(outputs.keys())[0]]
        
        # Return list of individual embeddings
        return [output_tensor[i] for i in range(output_tensor.shape[0])], 0.0  # timing handled in caller

    def _run_reid_batch(
        self,
        person_detections: List[PersonDetection],
        canonical_frame: CanonicalFrame,
    ) -> Tuple[List[torch.Tensor], float]:
        """Run ReID inference on batch of person crops via shared engine."""
        if not person_detections:
            return [], 0.0
        
        # Extract person crops from 4K frame
        person_crops = []
        rgb_tensor = nv12_cuda_to_rgb_cuda(canonical_frame.data.get_tensors()[0], canonical_frame.data.get_tensors()[1])
        
        for det in person_detections:
            x1, y1, x2, y2 = map(int, det.bbox)
            crop = rgb_tensor[y1:y2, x1:x2]
            if crop.numel() > 0:
                import torch.nn.functional as F
                crop_resized = F.interpolate(
                    crop.permute(2, 0, 1).unsqueeze(0).float(),
                    size=(256, 128),
                    mode='bilinear',
                    align_corners=False,
                ).squeeze(0).permute(1, 2, 0)
                
                crop_normalized = (crop_resized.float() / 255.0 - 0.5) / 0.5
                crop_chw = crop_normalized.permute(2, 0, 1).unsqueeze(0)
                person_crops.append(crop_chw)
        
        if not person_crops:
            return [], 0.0
        
        batch_tensor = torch.cat(person_crops, dim=0)
        
        # Run ReID via shared engine
        outputs = self._shared_engine.infer("reid", batch_tensor)
        output_tensor = outputs[list(outputs.keys())[0]]
        
        return [output_tensor[i] for i in range(output_tensor.shape[0])], 0.0

    def get_vram_report(self) -> Dict[str, Any]:
        """Get current VRAM usage."""
        return self._shared_engine.get_vram_report()

    def close(self):
        """Release all GPU resources."""
        self._cleanup()


def create_gpu_ai_bridge(device_id: int = 0) -> GPUAIBridge:
    """Factory function to create GPU AI Bridge."""
    return GPUAIBridge(device_id=device_id)