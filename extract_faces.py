#!/usr/bin/env python3
"""
Auto-extract 50 face crops from test video for embedding parity benchmark.
Simple version - process frames directly at native resolution.
"""

import cv2
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.vision.detection import create_face_detector
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType


def extract_faces_from_video(video_path: str, output_dir: str, max_faces: int = 50, confidence_threshold: float = 0.5):
    """Extract face crops from video using SCRFD."""
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    detector = create_face_detector(
        model_id='scrfd',
        confidence_threshold=confidence_threshold,
        nms_threshold=0.4,
        providers=['CPUExecutionProvider']
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
    
    # Process every frame (only 150 frames total)
    frame_step = 1
    
    while face_count < max_faces and cap.isOpened():
        ret, frame_bgr = cap.read()
        if not ret:
            break
            
        frame_idx += 1
        
        if frame_idx % frame_step != 0:
            continue
            
        # Convert to RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w = frame_rgb.shape[:2]
        
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO_FILE,
            source_id=os.path.basename(video_path),
            frame_index=frame_idx,
            timestamp=frame_idx / fps,
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
                
            x1 = int(det.bbox[0])
            y1 = int(det.bbox[1])
            x2 = int(det.bbox[2])
            y2 = int(det.bbox[3])
            
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
                
            face_crop = frame_rgb[y1:y2, x1:x2]
            
            face_filename = f"auto_face_{face_count:03d}_frame{frame_idx}.jpg"
            face_path = output_path / face_filename
            cv2.imwrite(str(face_path), cv2.cvtColor(face_crop, cv2.COLOR_RGB2BGR))
            
            print(f"  [{face_count+1}/{max_faces}] {face_filename} (conf={det.confidence:.3f}, bbox=({x1},{y1},{x2},{y2}))")
            face_count += 1
            
        if face_count % 10 == 0 and face_count > 0:
            print(f"Progress: {face_count}/{max_faces}")
            
    cap.release()
    print(f"\nDone! Extracted {face_count} faces to {output_dir}")
    return face_count


def main():
    video_path = "test_video.mp4"
    if not os.path.exists(video_path):
        print(f"ERROR: No test video found")
        sys.exit(1)
    
    print(f"Extracting faces from {video_path}")
    print(f"Target: 50 faces")
    
    count = extract_faces_from_video(video_path, "data/enrollment_test", max_faces=50)
    
    if count >= 50:
        print("SUCCESS: Extracted 50+ faces")
        sys.exit(0)
    else:
        print(f"WARNING: Only extracted {count} faces")
        sys.exit(1)


if __name__ == "__main__":
    main()