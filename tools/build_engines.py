"""
tools/build_engines.py
Bien dich tu dong cac file ONNX sang TensorRT Engine (FP16) toi uu cho phan cung hien tai.
"""
import os
import subprocess
import sys
from pathlib import Path

TRTEXEC_CMD = "trtexec"

ENGINES_TO_BUILD = [
    {
        "name": "YOLO11n Person Detection",
        "onnx": "models/yolo/yolo11n.onnx",
        "engine": "models/yolo/yolo11n_fp16.engine",
        "args": ["--fp16"]
    },
    {
        "name": "SCRFD / Landmark Detection",
        "onnx": "models/landmark/1k3d68.onnx",
        "engine": "models/landmark/1k3d68_fp16.engine",
        "args": ["--fp16"]
    },
    {
        "name": "ArcFace GlintR100",
        "onnx": "models/arcface/glintr100.onnx",
        "engine": "models/arcface/glintr100_fp16.engine",
        "args": ["--fp16"]
    },
    {
        "name": "ResNet50 ReID",
        "onnx": "models/reid/resnet50_reid.onnx",
        "engine": "models/reid/resnet50_reid_fp16.engine",
        "args": ["--fp16"]
    }
]

def build_all():
    print("=== BAT DAU BIEN DICH TENSORRT ENGINES (FP16) ===")
    for item in ENGINES_TO_BUILD:
        onnx_path = Path(item["onnx"])
        engine_path = Path(item["engine"])
        
        if not onnx_path.exists():
            print(f"[SKIP] {item['name']}: Khong tim thay file {onnx_path}")
            continue
            
        print(f"\n[BUILD] Dang bien dich: {item['name']} -> {engine_path} ...")
        cmd = [
            TRTEXEC_CMD,
            f"--onnx={onnx_path}",
            f"--saveEngine={engine_path}"
        ] + item["args"]
        
        try:
            res = subprocess.run(cmd, check=True)
            print(f"[DONE] Hoan tat bien dich: {engine_path}")
        except FileNotFoundError:
            print(f"[ERROR] Khong tim thay lenh 'trtexec'. Vui long them thu muc TensorRT/bin vao PATH he thong!")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Loi khi bien dich {item['name']}: {e}")

if __name__ == "__main__":
    build_all()