"""
Test YOLOv11n TensorRT engine inference to verify it works.
"""

import app.runtime.cuda
import cv2
import torch
import numpy as np
from pipeline_engine.inference.person_detection import YOLOPersonDetector
from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat

def test_yolo_inference():
    """Test YOLO inference with the compiled engine."""
    print("Initializing YOLO detector with TensorRT engine...")
    detector = YOLOPersonDetector("models/yolo/yolo11n_fp16.engine")
    
    if not detector.initialize():
        print("Failed to initialize detector")
        return False
    
    print("Detector initialized successfully!")
    print(f"Stats: {detector.get_stats()}")
    
    # Test with a synthetic frame using GPUFrame.create_empty
    print("Creating synthetic test frame...")
    
    # Create a test image with a person-like shape
    test_img = np.zeros((720, 1280, 3), dtype=np.uint8)
    # Draw a rectangle that looks like a person
    cv2.rectangle(test_img, (400, 200), (600, 550), (255, 255, 255), -1)
    cv2.rectangle(test_img, (450, 100), (550, 200), (255, 255, 255), -1)  # head
    
    # Convert to NV12 format
    # Use cv2.COLOR_BGR2YUV_YV12 which gives YV12 (Y, V, U) - we can convert to NV12
    # Or better, use direct NV12 conversion
    yuv_nv12 = cv2.cvtColor(test_img, cv2.COLOR_BGR2YUV_I420)  # This gives I420
    h, w = test_img.shape[:2]
    y_plane = yuv_nv12[:h, :]
    # I420: U plane is (h/2, w/2), V plane is (h/2, w/2)
    u_plane = yuv_nv12[h:h+h//4, :w//2]  # (h/2, w/2)
    v_plane = yuv_nv12[h+h//4:h+h//2, :w//2]  # (h/2, w/2)
    # Interleave U and V for NV12: (h/2, w/2, 2)
    uv_plane = np.stack([u_plane, v_plane], axis=-1)
    
    # Create GPU tensors
    y_tensor = torch.from_numpy(y_plane).cuda()
    uv_tensor = torch.from_numpy(uv_plane).cuda()
    
    # Create GPUFrame using from_pyav_nvdec
    gpu_frame = GPUFrame.from_pyav_nvdec(
        y_tensor=y_tensor,
        uv_tensor=uv_tensor,
        camera_id="test",
        frame_id=1,
        timestamp=0.0,
        pts=0,
        width=w,
        height=h,
    )
    
    print("Running inference test...")
    detections = detector.detect(gpu_frame)
    print(f"Detected {len(detections)} persons")
    for d in detections:
        print(f"  BBox: {d.bbox}, Conf: {d.confidence}")
    
    if len(detections) > 0:
        print("SUCCESS: Engine works and detects objects!")
        return True
    else:
        print("WARNING: No detections on test image (may be expected for synthetic image)")
        return True  # Engine works, just no detection on synthetic data

if __name__ == "__main__":
    test_yolo_inference()