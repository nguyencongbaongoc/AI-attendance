"""
ReID GPU Person Re-identification - V2 GPU-first video pipeline.

Runs ReID (ResNet50) person re-identification entirely on GPU.
Input: Person crop (128x256) → Normalize → ReID ONNX → 2048D embedding (L2 normalized).
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

from video_pipeline_v2.core.gpu_frame import GPUFrame
from video_pipeline_v2.ai.gpu_inference import GPUInferenceEngine, InferenceConfig, InferenceResult
from video_pipeline_v2.ai.model_contracts import ModelContractRegistry

logger = logging.getLogger(__name__)


@dataclass
class ReIDConfig:
    """Configuration for ReID."""
    input_size: Tuple[int, int] = (256, 128)  # H, W
    embedding_dim: int = 2048
    # Normalization for ReID (ImageNet)
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: Tuple[float, float, float] = (0.229, 0.224, 0.225)


@dataclass
class PersonEmbedding:
    """Person ReID embedding result."""
    embedding: torch.Tensor  # (2048,) float32 on CUDA, L2 normalized
    raw_embedding: torch.Tensor
    raw_norm: float
    inference_time_ms: float
    detection_id: str
    frame_index: int = 0
    source_id: str = ""
    person_bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    
    def to_numpy(self) -> np.ndarray:
        return self.embedding.cpu().numpy()
    
    def cosine_similarity(self, other: "PersonEmbedding") -> float:
        return float(torch.dot(self.embedding, other.embedding))


class ReIDExtractor(GPUInferenceEngine):
    """
    ReID Feature Extractor running on GPU.
    
    Pipeline:
        Person crop (128x256 BGR) 
            → Resize + Normalize (GPU)
            → ReID ONNX (GPU, IO Binding)
            → L2 normalize embedding (GPU)
            → PersonEmbedding
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[ReIDConfig] = None,
        device_id: int = 0,
    ):
        self.reid_config = config or ReIDConfig()
        
        inference_config = InferenceConfig(
            model_path=model_path,
            model_name="reid",
            device_id=device_id,
            backend="onnxruntime",
            providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            use_io_binding=True,
            validate_input=True,
            validate_output=True,
        )
        
        super().__init__(inference_config)
        
        self.input_h, self.input_w = self.reid_config.input_size
        self.device = f'cuda:{device_id}'
        
        # Normalization constants
        self.mean = torch.tensor(self.reid_config.mean, device=self.device, dtype=torch.float32).view(1, 3, 1, 1)
        self.std = torch.tensor(self.reid_config.std, device=self.device, dtype=torch.float32).view(1, 3, 1, 1)
    
    def preprocess(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """
        Preprocess person crop to ReID input format.
        
        Args:
            input_tensor: BGR tensor (H, W, 3) or (1, 3, H, W)
            
        Returns:
            Preprocessed tensor: (1, 3, 256, 128) float32 normalized
        """
        # Handle different input formats
        if input_tensor.dim() == 3:
            if input_tensor.shape[-1] == 3:
                # (H, W, 3) -> (1, 3, H, W)
                input_tensor = input_tensor.permute(2, 0, 1).unsqueeze(0)
            elif input_tensor.shape[0] == 3:
                # (3, H, W) -> (1, 3, H, W)
                input_tensor = input_tensor.unsqueeze(0)
            else:
                raise ValueError(f"Unexpected 3D tensor shape: {input_tensor.shape}")
        elif input_tensor.dim() == 4:
            if input_tensor.shape[1] != 3:
                raise ValueError(f"Expected 3 channels, got {input_tensor.shape[1]}")
        else:
            raise ValueError(f"Unexpected tensor dimensions: {input_tensor.dim()}")
        
        # Ensure float32
        input_tensor = input_tensor.float()
        
        # Normalize to [0, 1] if needed
        if input_tensor.max() > 1.0:
            input_tensor = input_tensor / 255.0
        
        # Resize to input size
        if input_tensor.shape[-2:] != (self.input_h, self.input_w):
            input_tensor = F.interpolate(
                input_tensor,
                size=(self.input_h, self.input_w),
                mode='bilinear',
                align_corners=False
            )
        
        # Normalize: ImageNet stats
        normalized = (input_tensor - self.mean) / self.std
        
        return normalized.contiguous()
    
    def postprocess(self, outputs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Postprocess: L2 normalize the embedding."""
        for name, tensor in outputs.items():
            flat = tensor.flatten()
            norm = torch.norm(flat)
            if norm > 0:
                normalized = flat / norm
            else:
                normalized = flat
            outputs[name] = normalized.reshape(1, -1)
        
        return outputs
    
    def get_output_shapes(self, batch_size: int) -> Dict[str, Tuple[int, ...]]:
        return {"default": (batch_size, self.reid_config.embedding_dim)}
    
    def extract_embedding(
        self, 
        person_crop: torch.Tensor,
        detection_id: str = "",
        frame_index: int = 0,
        source_id: str = "",
        person_bbox: Tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> PersonEmbedding:
        """
        Extract ReID embedding from person crop.
        
        Args:
            person_crop: Person crop tensor (H, W, 3) BGR
            detection_id: ID for tracking
            frame_index: Frame index
            source_id: Camera/source ID
            person_bbox: Original person bbox
            
        Returns:
            PersonEmbedding with L2 normalized embedding
        """
        result = self.infer(person_crop)
        
        output_tensor = list(result.outputs.values())[0]  # (1, 2048)
        embedding = output_tensor.squeeze(0)  # (2048,)
        raw_embedding = embedding.clone()
        raw_norm = 1.0
        
        return PersonEmbedding(
            embedding=embedding,
            raw_embedding=raw_embedding,
            raw_norm=raw_norm,
            inference_time_ms=result.inference_time_ms,
            detection_id=detection_id,
            frame_index=frame_index,
            source_id=source_id,
            person_bbox=person_bbox,
        )
    
    def extract_batch(
        self, 
        person_crops: List[torch.Tensor],
        detection_ids: List[str] = None,
        frame_indices: List[int] = None,
        source_ids: List[str] = None,
        person_bboxes: List[Tuple[float, float, float, float]] = None,
    ) -> List[PersonEmbedding]:
        """Extract embeddings for batch of person crops."""
        if detection_ids is None:
            detection_ids = [str(uuid.uuid4())[:8] for _ in person_crops]
        if frame_indices is None:
            frame_indices = [0] * len(person_crops)
        if source_ids is None:
            source_ids = [""] * len(person_crops)
        if person_bboxes is None:
            person_bboxes = [(0, 0, 0, 0)] * len(person_crops)
        
        # Stack into batch
        batch = torch.stack([self.preprocess(crop) for crop in person_crops], dim=0)
        
        result = self.infer(batch)
        output_tensor = list(result.outputs.values())[0]  # (N, 2048)
        
        embeddings = []
        for i in range(output_tensor.shape[0]):
            emb = output_tensor[i]
            embeddings.append(PersonEmbedding(
                embedding=emb,
                raw_embedding=emb.clone(),
                raw_norm=1.0,
                inference_time_ms=result.inference_time_ms / len(person_crops),
                detection_id=detection_ids[i],
                frame_index=frame_indices[i],
                source_id=source_ids[i],
                person_bbox=person_bboxes[i],
            ))
        
        return embeddings
    
    @staticmethod
    def cosine_similarity(emb1: torch.Tensor, emb2: torch.Tensor) -> float:
        return float(torch.dot(emb1, emb2))
    
    @staticmethod
    def batch_cosine_similarity(embeddings: torch.Tensor, query: torch.Tensor) -> torch.Tensor:
        return torch.matmul(embeddings, query)


def create_reid_extractor(
    model_path: str = "models/reid/resnet50_reid.onnx",
    device_id: int = 0,
) -> ReIDExtractor:
    """Factory function to create ReID extractor."""
    config = ReIDConfig()
    return ReIDExtractor(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/reid/resnet50_reid.onnx"
    extractor = create_reid_extractor(model_path)
    
    if extractor.initialize():
        print("ReID extractor initialized successfully!")
        print(f"Stats: {extractor.get_stats()}")
    else:
        print("ReID extractor initialization failed")