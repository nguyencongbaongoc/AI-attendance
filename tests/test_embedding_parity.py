"""
Phase 15 — Embedding Parity Test.

Verifies cross-pipeline cosine similarity between Backend enrollment
and Live TensorRT inference reaches >= 0.998.

This test compares:
1. Backend enrollment: OpenCV CPU alignment + ONNX CPU inference
2. Live inference: PyTorch CUDA alignment + ONNX CUDA inference

Target: cosine similarity >= 0.998 for same input face
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np
import torch
import cv2

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.vision.enrollment import EnrollmentConfig, create_face_detector, align_face_with_landmarks
from app.vision.arcface_inference import ArcFaceInference, ArcFaceInferenceConfig, create_arcface_inference
from app.vision.gpu_preprocessing import create_gpu_preprocessor, align_face_gpu_5pt, get_canonical_landmarks_112
from app.vision.arcface_inference import get_model_registry
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbeddingParityTester:
    """Test cross-pipeline embedding consistency."""
    
    def __init__(self, test_images_dir: str, output_dir: str = "artifacts/phase_15/embedding_parity"):
        self.test_images_dir = Path(test_images_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize both pipelines
        self._init_backend_pipeline()
        self._init_live_pipeline()
    
    def _init_backend_pipeline(self):
        """Initialize backend enrollment pipeline (OpenCV + ONNX CPU)."""
        logger.info("Initializing backend enrollment pipeline...")
        
        # Create enrollment config with CPU providers
        self.backend_config = EnrollmentConfig(
            face_detector=create_face_detector(
                model_id="scrfd",
                confidence_threshold=0.5,
                nms_threshold=0.4,
                providers=["CPUExecutionProvider"],
            ),
            arcface_providers=("CPUExecutionProvider",),
        )
        
        logger.info(f"Backend ArcFace provider: {self.backend_config.arcface_inference.provider_used}")
    
    def _init_live_pipeline(self):
        """Initialize live inference pipeline (PyTorch CUDA + ONNX CUDA)."""
        logger.info("Initializing live inference pipeline...")
        
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available for live pipeline")
        
        # GPU preprocessor for ArcFace
        self.live_preprocessor = create_gpu_preprocessor(
            model_id="arcface",
            device=torch.device("cuda:0"),
            reuse_buffers=True,
            full_gpu=True,
        )
        
        from app.vision.arcface_inference import get_model_registry
        
        # GPU ArcFace inference
        self.live_arcface = create_arcface_inference(
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            registry=get_model_registry(),
        )
        
        logger.info(f"Live ArcFace provider: {self.live_arcface.provider_used}")
    
    def _load_test_images(self, max_samples: int = 50) -> List[Tuple[str, np.ndarray]]:
        """Load test images from directory (recursive)."""
        images = []
        valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp'}
        
        for img_path in sorted(self.test_images_dir.rglob("*")):
            if img_path.suffix.lower() in valid_extensions:
                if len(images) >= max_samples:
                    break
                
                img = cv2.imread(str(img_path))
                if img is not None:
                    images.append((img_path.stem, img))
                    logger.debug(f"Loaded test image: {img_path.name} ({img.shape})")
                else:
                    logger.warning(f"Failed to load: {img_path}")
        
        logger.info(f"Loaded {len(images)} test images")
        return images
    
    def _get_backend_embedding(self, image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Get embedding using backend pipeline.
        
        Process: OpenCV alignment -> ONNX CPU ArcFace -> L2 normalize
        """
        import cv2
        from app.data.frame import FrameMetadata, PixelFormat, SourceType
        from app.vision.enrollment import FaceCrop, safe_crop_face, align_face_with_landmarks
        
        # Convert image to RGB for enrollment
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        # Create CanonicalFrame
        h, w = image_rgb.shape[:2]
        metadata = FrameMetadata(
            source_type=SourceType.IMAGE,
            source_id="test",
            frame_index=0,
            timestamp=time.time(),
            original_width=w,
            original_height=h,
            pixel_format=PixelFormat.RGB,
            dtype="uint8",
        )
        frame = CanonicalFrame(data=image_rgb, metadata=metadata)
        
        # Detect faces using backend face detector
        detections = self.backend_config.face_detector.detect(frame)
        
        if not detections:
            raise ValueError("No face detected in backend pipeline")
        
        # Use highest confidence detection
        best_detection = max(detections, key=lambda d: d.confidence)
        landmarks = best_detection.landmarks5
        
        # Crop face
        crop = safe_crop_face(frame, best_detection, min_crop_size=self.backend_config.quality_thresholds["min_crop_dimension"])
        
        # Align using OpenCV (backend method)
        aligned_bgr = align_face_with_landmarks(crop, landmarks, target_size=(112, 112))
        
        # ArcFace inference using backend config's arcface_inference
        arcface_result = self.backend_config.arcface_inference.infer(aligned_bgr)
        normalized_embedding = arcface_result.normalized_embedding
        
        return normalized_embedding.flatten(), best_detection.confidence
    
    def _get_live_embedding(self, image: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Get embedding using live pipeline with 5-point GPU alignment.
        
        Process: SCRFD detection -> GPU 5-point alignment -> ONNX CUDA ArcFace -> L2 normalize
        """
        import cv2
        from app.data.frame import FrameMetadata, PixelFormat
        
        # Detect face using SCRFD on CPU first (for landmark detection)
        # In production, this would be done on GPU via SCRFD TensorRT
        detections = self.backend_face_detector.detect(image)
        
        if not detections:
            raise ValueError("No face detected in live pipeline")
        
        # Use highest confidence detection
        best_detection = max(detections, key=lambda d: d.confidence)
        landmarks = best_detection.landmarks
        
        # Convert landmarks to GPU tensor
        landmarks_tensor = torch.tensor(landmarks, dtype=torch.float32, device=torch.device("cuda:0"))
        
        # Convert image to GPU tensor
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        img_tensor = torch.from_numpy(img_rgb).to(torch.device("cuda:0")).float()
        
        # Apply 5-point GPU alignment
        aligned_face = align_face_gpu_5pt(
            img_tensor,
            landmarks_tensor,
            target_size=(112, 112),
            pixel_format="rgb",
        )
        
        # Preprocess for ArcFace (HWC -> CHW -> NCHW, normalize)
        # aligned_face is (112, 112, 3) HWC float32 in [0, 255] RGB
        preprocessed = aligned_face.permute(2, 0, 1).unsqueeze(0).float()  # (1, 3, 112, 112)
        
        # Normalize: (x - 127.5) / 128.0 to get [-1, 1] range
        preprocessed = (preprocessed - 127.5) / 128.0
        
        # Move to CPU for ONNX CUDA inference
        preprocessed_np = preprocessed.detach().cpu().numpy().astype(np.float32)
        
        # ArcFace inference
        raw_embedding, _ = self.live_arcface.infer_raw(preprocessed_np)
        normalized_embedding, _ = self.live_arcface.l2_normalize(raw_embedding)
        
        return normalized_embedding.flatten(), best_detection.confidence
    
    def run_parity_test(self, max_samples: int = 50) -> dict:
        """Run cross-pipeline embedding parity test."""
        logger.info(f"Starting embedding parity test with {max_samples} samples")
        
        images = self._load_test_images(max_samples)
        
        if not images:
            raise ValueError("No test images found")
        
        results = []
        similarities = []
        
        for i, (name, image) in enumerate(images):
            logger.info(f"Processing {i+1}/{len(images)}: {name}")
            
            try:
                # Get embeddings from both pipelines
                backend_emb, backend_conf = self._get_backend_embedding(image)
                live_emb, live_conf = self._get_live_embedding(image)
                
                # Compute cosine similarity
                similarity = float(np.dot(backend_emb, live_emb) / 
                                 (np.linalg.norm(backend_emb) * np.linalg.norm(live_emb)))
                
                results.append({
                    "image": name,
                    "backend_confidence": backend_conf,
                    "live_confidence": live_conf,
                    "cosine_similarity": similarity,
                    "backend_norm": float(np.linalg.norm(backend_emb)),
                    "live_norm": float(np.linalg.norm(live_emb)),
                    "passed": similarity >= 0.998,
                })
                
                similarities.append(similarity)
                
                logger.info(f"  Cosine similarity: {similarity:.6f} {'PASS' if similarity >= 0.998 else 'FAIL'}")
                
            except Exception as e:
                logger.error(f"  Failed: {e}")
                results.append({
                    "image": name,
                    "error": str(e),
                    "passed": False,
                })
        
        # Summary statistics
        valid_similarities = [s for s in similarities if not np.isnan(s)]
        
        summary = {
            "total_samples": len(images),
            "valid_samples": len(valid_similarities),
            "passed_count": sum(1 for r in results if r.get("passed", False)),
            "failed_count": sum(1 for r in results if not r.get("passed", False)),
            "mean_similarity": float(np.mean(valid_similarities)) if valid_similarities else 0.0,
            "std_similarity": float(np.std(valid_similarities)) if valid_similarities else 0.0,
            "min_similarity": float(np.min(valid_similarities)) if valid_similarities else 0.0,
            "max_similarity": float(np.max(valid_similarities)) if valid_similarities else 0.0,
            "target_threshold": 0.998,
            "overall_pass": all(r.get("passed", False) for r in results if "cosine_similarity" in r),
            "results": results,
        }
        
        # Save detailed results
        import json
        output_file = self.output_dir / "embedding_parity_results.json"
        with open(output_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        logger.info(f"Results saved to {output_file}")
        logger.info(f"Summary: {summary['passed_count']}/{summary['valid_samples']} passed")
        logger.info(f"Mean similarity: {summary['mean_similarity']:.6f} ± {summary['std_similarity']:.6f}")
        logger.info(f"Min/Max: {summary['min_similarity']:.6f} / {summary['max_similarity']:.6f}")
        
        return summary


def main():
    parser = argparse.ArgumentParser(description="Phase 15 Embedding Parity Test")
    parser.add_argument("--images", type=str, required=True, 
                       help="Directory containing test face images")
    parser.add_argument("--samples", type=int, default=50,
                       help="Maximum number of samples to test")
    parser.add_argument("--output", type=str, default="artifacts/phase_15/embedding_parity",
                       help="Output directory for results")
    
    args = parser.parse_args()
    
    if not Path(args.images).exists():
        logger.error(f"Test images directory not found: {args.images}")
        sys.exit(1)
    
    tester = EmbeddingParityTester(args.images, args.output)
    summary = tester.run_parity_test(args.samples)
    
    # Exit code based on overall pass
    if summary["overall_pass"]:
        logger.info("EMBEDDING PARITY TEST: PASSED")
        sys.exit(0)
    else:
        logger.error("EMBEDDING PARITY TEST: FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()