"""
ArcFace GPU Face Recognition - V2 GPU-first video pipeline.

Runs ArcFace (glintr100) face recognition entirely on GPU.
Input: Aligned face crop (112x112) → Normalize → ArcFace ONNX → 512D embedding (L2 normalized).
"""

from __future__ import annotations

import logging
import time
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
class ArcFaceConfig:
    """Configuration for ArcFace recognition."""
    input_size: Tuple[int, int] = (112, 112)
    embedding_dim: int = 512
    # Normalization: (x - 127.5) / 128.0
    mean: float = 127.5
    std: float = 128.0


@dataclass
class FaceEmbedding:
    """Face embedding result."""
    embedding: torch.Tensor  # (512,) float32 on CUDA, L2 normalized
    raw_embedding: torch.Tensor  # (512,) float32 before normalization
    raw_norm: float
    inference_time_ms: float
    detection_id: str
    frame_index: int = 0
    source_id: str = ""
    
    def to_numpy(self) -> np.ndarray:
        """Convert to numpy array (copies to CPU)."""
        return self.embedding.cpu().numpy()
    
    def cosine_similarity(self, other: "FaceEmbedding") -> float:
        """Compute cosine similarity with another embedding."""
        return float(torch.dot(self.embedding, other.embedding))


class ArcFaceRecognizer(GPUInferenceEngine):
    """
    ArcFace Face Recognizer running on GPU.
    
    Pipeline:
        Aligned face crop (112x112 BGR) 
            → Normalize: (x - 127.5) / 128.0 (GPU)
            → ArcFace ONNX (GPU, IO Binding)
            → L2 normalize embedding (GPU)
            → FaceEmbedding
    """
    
    def __init__(
        self,
        model_path: str,
        config: Optional[ArcFaceConfig] = None,
        device_id: int = 0,
    ):
        self.arcface_config = config or ArcFaceConfig()
        
        inference_config = InferenceConfig(
            model_path=model_path,
            model_name="arcface",
            device_id=device_id,
            backend="onnxruntime",
            providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
            use_io_binding=True,
            validate_input=True,
            validate_output=True,
        )
        
        super().__init__(inference_config)
        
        self.input_h, self.input_w = self.arcface_config.input_size
        self.device = f'cuda:{device_id}'
        
        # Normalization constants
        self.mean = torch.tensor(self.arcface_config.mean, device=self.device, dtype=torch.float32)
        self.std = torch.tensor(self.arcface_config.std, device=self.device, dtype=torch.float32)
    
    def preprocess(self, input_tensor: torch.Tensor) -> torch.Tensor:
        """
        Preprocess aligned face to ArcFace input format.
        
        Args:
            input_tensor: Can be:
                - BGR tensor (112, 112, 3) uint8 or float32
                - BGR tensor (1, 3, 112, 112) float32 [0, 255]
                - Already preprocessed (1, 3, 112, 112) float32 normalized
        
        Returns:
            Preprocessed tensor: (1, 3, 112, 112) float32 normalized
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
        
        # Resize if needed
        if input_tensor.shape[-2:] != (self.input_h, self.input_w):
            input_tensor = F.interpolate(
                input_tensor,
                size=(self.input_h, self.input_w),
                mode='bilinear',
                align_corners=False
            )
        
        # Normalize: (x - 127.5) / 128.0
        # Input assumed to be in [0, 255] range
        normalized = (input_tensor - self.mean) / self.std
        
        return normalized.contiguous()
    
    def postprocess(self, outputs: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """Postprocess: L2 normalize the embedding."""
        # ArcFace outputs raw embedding, need L2 normalization
        for name, tensor in outputs.items():
            # Flatten to 1D
            flat = tensor.flatten()
            
            # L2 norm
            norm = torch.norm(flat)
            if norm > 0:
                normalized = flat / norm
            else:
                normalized = flat
            
            # Reshape to (1, 512)
            outputs[name] = normalized.reshape(1, -1)
        
        return outputs
    
    def get_output_shapes(self, batch_size: int) -> Dict[str, Tuple[int, ...]]:
        return {"default": (batch_size, self.arcface_config.embedding_dim)}
    
    def infer_embedding(self, aligned_face: torch.Tensor) -> FaceEmbedding:
        """
        Run inference on aligned face and return embedding.
        
        Args:
            aligned_face: Aligned face tensor (112, 112, 3) BGR or (1, 3, 112, 112)
            
        Returns:
            FaceEmbedding with L2 normalized embedding
        """
        # Run inference
        result = self.infer(aligned_face)
        
        # Get embedding
        output_tensor = list(result.outputs.values())[0]  # (1, 512)
        embedding = output_tensor.squeeze(0)  # (512,)
        
        # Get raw embedding (before normalization) - we'd need to capture it before postprocess
        # For now, use the normalized one as both
        raw_embedding = embedding.clone()
        raw_norm = 1.0  # Already normalized
        
        return FaceEmbedding(
            embedding=embedding,
            raw_embedding=raw_embedding,
            raw_norm=raw_norm,
            inference_time_ms=result.inference_time_ms,
            detection_id="",  # Set by caller
            frame_index=0,
            source_id="",
        )
    
    def infer_batch(self, aligned_faces: List[torch.Tensor]) -> List[FaceEmbedding]:
        """Run inference on batch of aligned faces."""
        # Stack into batch
        batch = torch.stack([self.preprocess(f) for f in aligned_faces], dim=0)
        
        result = self.infer(batch)
        output_tensor = list(result.outputs.values())[0]  # (N, 512)
        
        embeddings = []
        for i in range(output_tensor.shape[0]):
            emb = output_tensor[i]  # (512,)
            embeddings.append(FaceEmbedding(
                embedding=emb,
                raw_embedding=emb.clone(),
                raw_norm=1.0,
                inference_time_ms=result.inference_time_ms / len(aligned_faces),
                detection_id="",
                frame_index=0,
                source_id="",
            ))
        
        return embeddings
    
    @staticmethod
    def cosine_similarity(emb1: torch.Tensor, emb2: torch.Tensor) -> float:
        """Compute cosine similarity between two embeddings."""
        return float(torch.dot(emb1, emb2))
    
    @staticmethod
    def batch_cosine_similarity(embeddings: torch.Tensor, query: torch.Tensor) -> torch.Tensor:
        """
        Compute cosine similarity between query and batch of embeddings.
        
        Args:
            embeddings: (N, 512) L2 normalized
            query: (512,) L2 normalized
            
        Returns:
            (N,) similarities
        """
        return torch.matmul(embeddings, query)


def create_arcface_recognizer(
    model_path: str = "models/arcface/glintr100.onnx",
    device_id: int = 0,
) -> ArcFaceRecognizer:
    """Factory function to create ArcFace recognizer."""
    config = ArcFaceConfig()
    return ArcFaceRecognizer(model_path, config, device_id)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    model_path = "models/arcface/glintr100.onnx"
    recognizer = create_arcface_recognizer(model_path)
    
    if recognizer.initialize():
        print("ArcFace recognizer initialized successfully!")
        print(f"Stats: {recognizer.get_stats()}")
    else:
        print("ArcFace recognizer initialization failed")