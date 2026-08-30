#!/usr/bin/env python
"""Test RTSPSource with real MediaMTX streams."""

import sys
sys.path.insert(0, r"C:\Users\Nguyen Cong Thong\Desktop\AI attendance")

from app.streaming.rtsp_source import create_rtsp_source

def test_camera(camera_id, rtsp_url):
    print(f"\nTesting {camera_id} at {rtsp_url}")
    src = create_rtsp_source(camera_id, rtsp_url)
    src.open()
    print(f"  Opened: resolution={src.resolution}, fps={src.fps}")
    
    frames = 0
    for i in range(10):
        f = src.get_next_frame()
        if f:
            frames += 1
            print(f"  Frame {frames}: idx={f.metadata.frame_index}, ts={f.metadata.timestamp}, shape={f.data.shape}, camera_id={f.metadata.extra.get('camera_id')}")
    
    src.close()
    print(f"  Total frames received: {frames}")
    return frames

if __name__ == "__main__":
    cam1_frames = test_camera("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
    cam2_frames = test_camera("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
    
    print(f"\n=== SUMMARY ===")
    print(f"CAM1 frames: {cam1_frames}")
    print(f"CAM2 frames: {cam2_frames}")
    print(f"Both cameras working: {cam1_frames > 0 and cam2_frames > 0}")