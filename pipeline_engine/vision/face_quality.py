"""
Embedding Quality Scoring for Face and Body Embeddings.

Computes quality metrics for face and body embeddings:
- Face quality: sharpness, pose, illumination
- Body quality: crop size, visibility, occlusion
"""

from __future__ import annotations

import logging
import torch
import torch.nn.functional as F
import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class FaceQualityMetrics:
    """Face embedding quality metrics."""
    sharpness: float = 0.0      # 0.0-1.0, higher = sharper
    pose: float = 0.0           # 0.0-1.0, higher = frontal
    illumination: float = 0.0   # 0.0-1.0, higher = well lit
    overall: float = 0.0        # Weighted combination


@dataclass
class BodyQualityMetrics:
    """Body embedding quality metrics."""
    crop_size: float = 0.0      # 0.0-1.0, higher = larger crop
    visibility: float = 0.0     # 0.0-1.0, higher = more visible
    occlusion: float = 0.0      # 0.0-1.0, higher = less occluded
    overall: float = 0.0        # Weighted combination


def compute_face_quality(
    frame: torch.Tensor,
    face_bbox: Tuple[float, float, float, float],
    landmarks5: Optional[list] = None,
) -> FaceQualityMetrics:
    """
    Compute face embedding quality from frame and face detection.
    
    Args:
        frame: BGR frame tensor (H, W, 3) on GPU
        face_bbox: Face bounding box (x1, y1, x2, y2) in frame coordinates
        landmarks5: Optional 5 facial landmarks
        
    Returns:
        FaceQualityMetrics with quality scores
    """
    x1, y1, x2, y2 = [int(c) for c in face_bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    
    if x2 <= x1 or y2 <= y1:
        return FaceQualityMetrics()
    
    face_crop = frame[y1:y2, x1:x2]
    
    # 1. Sharpness - Laplacian variance
    gray = torch.mean(face_crop.float(), dim=2)  # (H, W)
    laplacian_kernel = torch.tensor([[0, 1, 0], [1, -4, 1], [0, 1, 0]], 
                                    dtype=torch.float32, device=frame.device).view(1, 1, 3, 3)
    gray_4d = gray.unsqueeze(0).unsqueeze(0)  # (1, 1, H, W)
    laplacian = F.conv2d(gray_4d, laplacian_kernel, padding=1)
    sharpness_score = torch.var(laplacian).item()
    # Normalize (empirical range)
    sharpness = min(1.0, sharpness_score / 500.0)
    
    # 2. Pose - from landmarks if available, else estimate from bbox aspect ratio
    pose = 0.0
    if landmarks5 and len(landmarks5) == 5:
        # Compute pose from landmark positions
        # Left eye, right eye, nose, left mouth, right mouth
        left_eye = landmarks5[0]
        right_eye = landmarks5[1]
        nose = landmarks5[2]
        
        # Eye distance vs nose offset
        eye_dist = abs(right_eye[0] - left_eye[0])
        nose_offset = abs(nose[0] - (left_eye[0] + right_eye[0]) / 2)
        
        if eye_dist > 0:
            pose_ratio = nose_offset / eye_dist
            # Frontal face has small nose offset
            pose = max(0.0, 1.0 - pose_ratio * 2.0)
    else:
        # Estimate from bbox aspect ratio
        w = x2 - x1
        h = y2 - y1
        if h > 0:
            aspect = w / h
            # Frontal faces typically have aspect ~0.8-1.0
            pose = max(0.0, 1.0 - abs(aspect - 0.9) * 2.0)
    
    # 3. Illumination - mean brightness and contrast
    mean_brightness = torch.mean(face_crop.float() / 255.0).item()
    contrast = torch.std(face_crop.float() / 255.0).item()
    # Good illumination: brightness ~0.3-0.7, contrast > 0.1
    brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2.0
    contrast_score = min(1.0, contrast * 5.0)
    illumination = (brightness_score + contrast_score) / 2.0
    
    # 4. Overall quality (weighted)
    overall = sharpness * 0.4 + pose * 0.3 + illumination * 0.3
    
    return FaceQualityMetrics(
        sharpness=sharpness,
        pose=pose,
        illumination=illumination,
        overall=overall,
    )


def compute_body_quality(
    frame: torch.Tensor,
    person_bbox: Tuple[float, float, float, float],
    frame_shape: Tuple[int, int],
) -> BodyQualityMetrics:
    """
    Compute body embedding quality from frame and person detection.
    
    Args:
        frame: BGR frame tensor (H, W, 3) on GPU
        person_bbox: Person bounding box (x1, y1, x2, y2) in frame coordinates
        frame_shape: (height, width) of original frame
        
    Returns:
        BodyQualityMetrics with quality scores
    """
    x1, y1, x2, y2 = [int(c) for c in person_bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
    
    if x2 <= x1 or y2 <= y1:
        return BodyQualityMetrics()
    
    crop_w = x2 - x1
    crop_h = y2 - y1
    frame_h, frame_w = frame_shape
    
    # 1. Crop size - relative to frame
    crop_area = crop_w * crop_h
    frame_area = frame_w * frame_h
    size_ratio = crop_area / frame_area
    # Good crop: 5-30% of frame
    crop_size = min(1.0, max(0.0, (size_ratio - 0.05) / 0.25))
    
    # 2. Visibility - based on crop position (not near edges)
    edge_margin = min(x1, y1, frame_w - x2, frame_h - y2)
    visibility = min(1.0, edge_margin / 50.0)  # 50 pixels from edge = full visibility
    
    # 3. Occlusion - estimated from aspect ratio and size
    # Extreme aspect ratios suggest occlusion
    aspect = crop_w / crop_h if crop_h > 0 else 0.0
    expected_aspect = 0.5  # Typical person: width/height ~ 0.5
    aspect_deviation = abs(aspect - expected_aspect) / expected_aspect
    occlusion = max(0.0, 1.0 - aspect_deviation)
    
    # 4. Overall quality (weighted)
    overall = crop_size * 0.4 + visibility * 0.3 + occlusion * 0.3
    
    return BodyQualityMetrics(
        crop_size=crop_size,
        visibility=visibility,
        occlusion=occlusion,
        overall=overall,
    )


def assess_embedding_quality(
    embedding: torch.Tensor,
    embedding_type: str = "face",
) -> float:
    """
    Assess embedding quality from embedding properties.
    
    Args:
        embedding: Raw embedding tensor (before L2 norm)
        embedding_type: "face" or "body"
        
    Returns:
        Quality score 0.0-1.0
    """
    # Norm-based quality (higher norm often = stronger signal)
    norm = torch.norm(embedding).item()
    dim = embedding.shape[0]
    expected_norm = np.sqrt(dim)
    
    # Norm should be close to sqrt(dim) for good embeddings
    norm_quality = min(1.0, norm / expected_norm) if expected_norm > 0 else 0.0
    
    # Check for NaN/Inf
    if torch.isnan(embedding).any() or torch.isinf(embedding).any():
        return 0.0
    
    # Check for very small values (degenerate)
    if norm < 1e-6:
        return 0.0
    
    # Sparsity check (good embeddings should be dense)
    nonzero_ratio = (embedding != 0).float().mean().item()
    sparsity_penalty = max(0.0, 1.0 - nonzero_ratio * 2.0)
    
    quality = norm_quality * (1.0 - sparsity_penalty * 0.3)
    
    return quality


class QualityAssessor:
    """Unified quality assessor for face and body embeddings."""
    
    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self.device = f'cuda:{device_id}'
    
    def assess_face(
        self,
        frame,
        face_bbox: Tuple[float, float, float, float],
        landmarks5: Optional[list] = None,
    ) -> FaceQualityMetrics:
        """Assess face quality from frame and detection."""
        # Convert frame to tensor if needed
        if hasattr(frame, 'get_tensors'):
            # GPUFrame - get BGR
            y_tensor, uv_tensor = frame.get_tensors()
            bgr = self._nv12_to_bgr(y_tensor, uv_tensor)
        elif isinstance(frame, torch.Tensor):
            bgr = frame
        else:
            bgr = torch.from_numpy(frame).to(self.device)
        
        return compute_face_quality(bgr, face_bbox, landmarks5)
    
    def assess_body(
        self,
        frame,
        person_bbox: Tuple[float, float, float, float],
    ) -> BodyQualityMetrics:
        """Assess body quality from frame and detection."""
        if hasattr(frame, 'get_tensors'):
            y_tensor, uv_tensor = frame.get_tensors()
            bgr = self._nv12_to_bgr(y_tensor, uv_tensor)
        elif isinstance(frame, torch.Tensor):
            bgr = frame
        else:
            bgr = torch.from_numpy(frame).to(self.device)
        
        return compute_body_quality(bgr, person_bbox, (bgr.shape[0], bgr.shape[1]))
    
    def _nv12_to_bgr(self, y_tensor: torch.Tensor, uv_tensor: torch.Tensor) -> torch.Tensor:
        """Convert NV12 to BGR on GPU."""
        # Simple conversion - in practice use the pipeline's nv12_to_bgr_cuda
        H, W = y_tensor.shape
        uv = F.interpolate(uv_tensor.unsqueeze(0).unsqueeze(0), size=(H, W), mode='bilinear', align_corners=False).squeeze(0).squeeze(0)
        U = uv[0]
        V = uv[1]
        
        Y = y_tensor.float()
        R = Y + 1.402 * (V - 128)
        G = Y - 0.344 * (U - 128) - 0.714 * (V - 128)
        B = Y + 1.772 * (U - 128)
        
        bgr = torch.stack([B, G, R], dim=2).clamp(0, 255).byte()
        return bgr


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    # Quick test
    device = 'cuda:0'
    test_frame = torch.randint(0, 255, (1080, 1920, 3), device=device, dtype=torch.uint8)
    
    face_bbox = (500, 300, 600, 450)
    face_quality = compute_face_quality(test_frame, face_bbox)
    print(f"Face Quality: {face_quality}")
    
    person_bbox = (400, 200, 800, 900)
    body_quality = compute_body_quality(test_frame, person_bbox, (1080, 1920))
    print(f"Body Quality: {body_quality}")
    
    test_embedding = torch.randn(512, device=device)
    emb_quality = assess_embedding_quality(test_embedding, "face")
    print(f"Embedding Quality: {emb_quality}")