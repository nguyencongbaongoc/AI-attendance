#!/usr/bin/env python3
"""
Create real ArcFace R100 embeddings (.npy) directly from images.
Uses production ArcFaceInference with manual preprocessing/alignment
if face detector finds no detections (manual crop + resize to 112x112).
This avoids dependency on SCRFD for synthetic/simple images,
but still uses the real glintr100.onnx model.
"""
import sys
import numpy as np
from pathlib import Path
sys.path.insert(0, '.')
import cv2
from app.vision.arcface_inference import ArcFaceInference

def generate_embedding(image_path: str) -> np.ndarray:
    arcface = ArcFaceInference()
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise ValueError(f"Cannot read {image_path}")
    # Resize and center-crop to 112x112 (standard ArcFace input size)
    # Convert BGR -> RGB for consistency with backend contracts
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    aligned = cv2.resize(img_rgb, (112, 112), interpolation=cv2.INTER_LINEAR)
    # ArcFace expects BGR per contract
    aligned_bgr = cv2.cvtColor(aligned, cv2.COLOR_RGB2BGR)
    tensor = arcface.preprocess(aligned_bgr)
    raw_embedding, _ = arcface.infer_raw(tensor)
    normalized, norm = arcface.l2_normalize(raw_embedding)
    return normalized.flatten()

def main():
    for jpg_path in Path('.').glob('Person*.jpg'):
        name = jpg_path.stem
        embedding = generate_embedding(str(jpg_path))
        out_path = Path(f"{name}.npy")
        np.save(str(out_path), embedding)
        print(f"Saved {out_path} shape={embedding.shape} norm={float(np.linalg.norm(embedding)):.4f}")

if __name__ == '__main__':
    main()
