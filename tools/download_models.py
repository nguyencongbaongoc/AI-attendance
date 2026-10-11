"""
tools/download_models.py
Tự động tải hoặc hướng dẫn đặt các mô hình ONNX chuẩn vào thư mục models/
"""
import os
import sys
from pathlib import Path

MODEL_DIR = Path("models")
REQUIRED_MODELS = {
    "yolo": {
        "filename": "yolo11n.onnx",
        "dest_dir": MODEL_DIR / "yolo",
        "description": "YOLO11n Person Detection (Ultralytics)",
        "url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
    },
    "landmark": {
        "filename": "1k3d68.onnx",
        "dest_dir": MODEL_DIR / "landmark",
        "description": "SCRFD / 1k3d68 Facial Landmark Detector (5-point)",
        "url": ""
    },
    "arcface": {
        "filename": "glintr100.onnx",
        "dest_dir": MODEL_DIR / "arcface",
        "description": "ArcFace GlintR100 512D Embedding",
        "url": ""
    },
    "reid": {
        "filename": "resnet50_reid.onnx",
        "dest_dir": MODEL_DIR / "reid",
        "description": "ResNet-50 Person Re-Identification",
        "url": ""
    }
}

def setup_model_directories():
    for key, info in REQUIRED_MODELS.items():
        info["dest_dir"].mkdir(parents=True, exist_ok=True)
        target_file = info["dest_dir"] / info["filename"]
        if target_file.exists():
            print(f"[FOUND] {info['description']} -> {target_file} ({target_file.stat().st_size / (1024*1024):.1f} MB)")
        else:
            print(f"[MISSING] {info['description']} -> Can dat file tai: {target_file}")

if __name__ == "__main__":
    print("=== KIEM TRA & THIET LAP THU MUC MO HINH AI ===")
    setup_model_directories()
    print("\nLuu y: Neu chua co file weights, vui long tai cac file ONNX tu Release Assets va dat vao dung thu muc nhu tren.")