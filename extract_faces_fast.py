#!/usr/bin/env python3
"""
Ultra-fast face extraction - uses GPU SCRFD, heavy downsampling.
"""

import cv2
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.vision.detection import create_face_detector
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType


def extract_faces_fast(video_path: str, output_dir: str, max_faces: int = 50):
    """Ultra-fast extraction with aggressive downsampling."""
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Use GPU detector for speed
    detector = create_face_detector(
        model_id='scrfd',
        confidence_threshold=0.4,
        nms_threshold=0.4,
        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
    )
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open video {video_path}")
        return 0
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Video: {total_frames} frames at {fps:.1f} FPS, {orig_w}x{orig_h}")
    
    face_count = 0
    frame_idx = 0
    
    # Heavy downsample: 4K -> 640x360 for ultra-fast detection
    det_w, det_h = 640, 360
    scale_x = orig_w / det_w
    scale_y = orig_h / det_h
    
    print(f"Downsample: {orig_w}x{orig_h} -> {det_w}x{det_h} (scale: {scale_x:.2f}x{scale_y:.2f})")
    
    # Process every 3rd frame
    frame_step = 3
    
    while face_count < max_faces and cap.isOpened():
        ret, frame_bgr = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        
        if frame_idx % frame_step != 0:
            continue
            
        # Resize to small for ultra-fast detection
        frame_small = cv2.resize(frame_bgr, (det_w, det_h))
        frame_rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        
        from app.data.frame import FrameMetadata, PixelFormat, SourceType, CanonicalFrame
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO_FILE,
            source_id=os.path.basename(video_path),
            frame_index=frame_idx,
            timestamp=frame_idx / 30.0,
            original_width=w,
            original_height=h,
            pixel_format=PixelFormat.RGB,
            dtype='uint8',
        )
        frame = CanonicalFrame(data=frame_rgb, metadata=metadata)
        
        detections = detector.detect(frame)
        
        for det in detections:
            if face_count >= max_faces:
                break
                
            # Scale bbox back to original
            x1 = int(det.bbox[0] * scale_x)
            y1 = int(det.bbox[1] * scale_y)
            x2 = int(det.bbox[2] * scale_x)
            y2 = int(det.bbox[3] * scale_y)
            
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(orig_w, x2)
            y2 = min(orig_h, y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
                
            # Extract from original frame at original position
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx - 1)
            ret, orig_frame = cap.read()
            if not ret:
                continue
            orig_rgb = cv2.cvtColor(orig_frame, cv2.COLOR_BGR2RGB)
            face_crop = orig_rgb[y1:y2, x1:x2]
            
            face_filename = f"auto_face_{face_count:03d}_frame{frame_idx}.jpg"
            face_path = output_path / face_filename
            cv2.imwrite(str(face_path), cv2.cvtColor(face_crop, cv2.COLOR_RGB2BGR))
            
            print(f"  [{face_count+1}/{max_faces}] {face_filename} (conf={det.confidence:.3f})")
            face_count += 1
            
        if face_count % 5 == 0 and face_count > 0:
            print(f"Progress: {face_count}/{max_faces}")
            
    cap.release()
    print(f"\nDone! Extracted {face_count} faces to {output_dir}")
    return face_count


def main():
    video_path = "test_video.mp4"
    if not os.path.exists(video_path):
        print(f"ERROR: No test video found")
        sys.exit(1)
    
    print(f"Fast extracting faces from {video_path}")
    print(f"Target: 50 faces")
    
    count = extract_faces_fast(video_path, "data/enrollment_test", max_faces=50)
    
    if count >= 50:
        print("SUCCESS: Extracted 50+ faces")
        sys.exit(0)
    else:
        print(f"WARNING: Only extracted {count} faces")
        sys.exit(1)


if __name__ == "__main__":
    main()