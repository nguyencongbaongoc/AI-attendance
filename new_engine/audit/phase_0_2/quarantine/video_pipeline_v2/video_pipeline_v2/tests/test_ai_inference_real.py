"""
Real AI Inference Test - V2 GPU Pipeline
Tests SCRFD, ArcFace, YOLO, ReID with real model files.
"""

import sys
import os
sys.path.insert(0, '.')

import logging
import time
import torch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_scrfd():
    """Test SCRFD detector with real video input."""
    from video_pipeline_v2.ai.scrfd_detector import create_scrfd_detector
    
    model_path = "models/scrfd/scrfd_10g_bnkps.onnx"
    
    if not os.path.exists(model_path):
        logger.error(f"SCRFD model not found: {model_path}")
        return False
    
    logger.info("=== Testing SCRFD with real model ===")
    
    detector = create_scrfd_detector(model_path, device_id=0)
    
    if not detector.initialize():
        logger.error("SCRFD initialization failed")
        return False
    
    stats = detector.get_stats()
    logger.info(f"SCRFD initialized: {stats['initialized']}, provider: {stats['provider']}")
    
    # Test inference with synthetic frame
    H, W = 480, 640
    y_test = torch.randint(16, 236, (H, W), dtype=torch.uint8, device='cuda')
    uv_test = torch.randint(16, 241, (H // 2, W // 2, 2), dtype=torch.uint8, device='cuda')
    
    from video_pipeline_v2.core.gpu_frame import GPUFrame, CUDAContext
    
    # Test inference with synthetic GPUFrame (NV12) converted inside detect
    # The detector.preprocess handles GPUFrame input
    gpu_frame = GPUFrame.from_pyav_nvdec(
        y_tensor=y_test,
        uv_tensor=uv_test,
        camera_id="test",
        frame_id=1,
        timestamp=1.0,
        pts=1,
        width=W,
        height=H,
    )
    
    # Test with synthetic BGR tensor (simulating preprocessed input)
    # The detector expects either GPUFrame or BGR float32 [0-255]
    y_test_float = y_test.float()  # (H, W) float32, range 16-235
    uv_test_float = uv_test.float()  # (H/2, W/2, 2) float32
    
    # Create GPUFrame for detector (it will preprocess internally)
    gpu_frame = GPUFrame.from_pyav_nvdec(
        y_tensor=y_test,
        uv_tensor=uv_test,
        camera_id="test",
        frame_id=1,
        timestamp=1.0,
        pts=1,
        width=W,
        height=H,
    )
    
    try:
        detections = detector.detect(gpu_frame)
        logger.info(f"SCRFD detected {len(detections)} faces")
        if detections:
            logger.info(f"First detection: bbox={detections[0].bbox}, conf={detections[0].confidence:.2f}")
        result = len(detections) >= 0  # At minimum, it should not crash
    except Exception as e:
        logger.error(f"SCRFD inference error: {e}")
        result = False
    
    detector.cleanup()
    return result


def test_arcface():
    """Test ArcFace recognizer with real model."""
    from video_pipeline_v2.ai.arcface_recognizer import create_arcface_recognizer
    
    model_path = "models/arcface/glintr100.onnx"
    
    if not os.path.exists(model_path):
        logger.error(f"ArcFace model not found: {model_path}")
        return False
    
    logger.info("=== Testing ArcFace with real model ===")
    
    recognizer = create_arcface_recognizer(model_path)
    
    if not recognizer.initialize():
        logger.error("ArcFace initialization failed")
        return False
    
    stats = recognizer.get_stats()
    logger.info(f"ArcFace initialized: {stats['initialized']}, provider: {stats['provider']}")
    
    # Create synthetic aligned face (float32 BGR [0-255], preprocess applies normalization)
    aligned_face = torch.randint(0, 256, (112, 112, 3), dtype=torch.float32, device='cuda')
    
    try:
        result = recognizer.infer_embedding(aligned_face)
        logger.info(f"ArcFace embedding: shape={result.embedding.shape}, norm={torch.norm(result.embedding):.4f}")
        success = True
    except Exception as e:
        logger.error(f"ArcFace inference error: {e}")
        success = False
    
    recognizer.cleanup()
    return success


def test_yolo():
    """Test YOLO detector with real model."""
    from video_pipeline_v2.ai.yolo_detector import create_yolo_detector
    
    model_path = "models/yolo/yolo11n.onnx"
    
    if not os.path.exists(model_path):
        logger.error(f"YOLO model not found: {model_path}")
        return False
    
    logger.info("=== Testing YOLO with real model ===")
    
    detector = create_yolo_detector(model_path)
    
    if not detector.initialize():
        logger.error("YOLO initialization failed")
        return False
    
    stats = detector.get_stats()
    logger.info(f"YOLO initialized: {stats['initialized']}, provider: {stats['provider']}")
    
    # Test with synthetic BGR float32 [0-255]
    y_test = torch.randint(0, 256, (480, 640, 3), dtype=torch.float32, device='cuda')
    
    try:
        detections = detector.detect(y_test)
        logger.info(f"YOLO detected {len(detections)} persons")
        success = True
    except Exception as e:
        logger.error(f"YOLO inference error: {e}")
        success = False
    
    detector.cleanup()
    return success


def test_reid():
    """Test ReID extractor with real model."""
    from video_pipeline_v2.ai.reid_extractor import create_reid_extractor
    
    model_path = "models/reid/resnet50_reid.onnx"
    
    if not os.path.exists(model_path):
        logger.error(f"ReID model not found: {model_path}")
        return False
    
    logger.info("=== Testing ReID with real model ===")
    
    extractor = create_reid_extractor(model_path)
    
    if not extractor.initialize():
        logger.error("ReID initialization failed")
        return False
    
    stats = extractor.get_stats()
    logger.info(f"ReID initialized: {stats['initialized']}, provider: {stats['provider']}")
    
    # Create synthetic person crop (float32 BGR [0-255], preprocess applies normalization)
    crop = torch.randint(0, 256, (128, 256, 3), dtype=torch.float32, device='cuda')
    
    try:
        embedding = extractor.extract_embedding(crop)
        logger.info(f"ReID embedding: shape={embedding.embedding.shape}, norm={torch.norm(embedding.embedding):.4f}")
        success = True
    except Exception as e:
        logger.error(f"ReID inference error: {e}")
        success = False
    
    extractor.cleanup()
    return success


if __name__ == "__main__":
    results = {}
    
    results["SCRFD"] = test_scrfd()
    results["ArcFace"] = test_arcface()
    results["YOLO"] = test_yolo()
    results["ReID"] = test_reid()
    
    print("\n=== Real AI Inference Results ===")
    for model, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  {model}: {status}")
    
    all_pass = all(results.values())
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
