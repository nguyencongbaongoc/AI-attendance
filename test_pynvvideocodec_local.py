"""
Phase 9.2 — Test PyNvVideoCodec Backend with local video file.
"""

import os
import sys
import importlib

# Ensure we're running from the project root
project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)
sys.path.insert(0, project_root)

# Force reload modules to pick up new imports
modules_to_reload = [
    'app.streaming.decoder_backend',
    'app.data.input_adapter',
]
for mod_name in modules_to_reload:
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])

from app.data.input_adapter import create_video_frame_iterator
import time

def test_pynvvideocodec_local():
    """Test PyNvVideoCodec backend with local video file."""
    
    print("Testing PyNvVideoCodec backend with local video...")
    
    # Use the test video we created
    video_path = "test_video_nv12.mp4"
    
    # Create iterator with pynvvideocodec backend
    iterator = create_video_frame_iterator(
        path=video_path,
        decoder="pynvvideocodec",
        nvdec_gpu_device=0,
        expected_width=3840,
        expected_height=2160,
        expected_fps=30.0,
        camera_id="TEST_CAM",
    )
    
    try:
        # Open and get info
        info = iterator.info
        print(f"Video info: {info.width}x{info.height} @ {info.fps}fps, codec={info.codec}, format={info.pixel_format}")
        
        # Iterate frames
        frame_count = 0
        start_time = time.time()
        
        for frame in iterator:
            frame_count += 1
            if frame_count <= 5:
                print(f"Frame {frame.frame_index}: pts={frame.pts}, timestamp={frame.timestamp:.4f}, "
                      f"decoder={frame.decoder}, gpu_device={frame.nvdec_gpu_device}")
                print(f"  Data type: {type(frame.data)}")
                if hasattr(frame.data, 'width'):
                    print(f"  FrameContract: {frame.data.width}x{frame.data.height}, "
                          f"fmt={frame.data.pixel_format}, device={frame.data.device_id}")
            
            if frame_count >= 20:
                break
        
        elapsed = time.time() - start_time
        print(f"\nDecoded {frame_count} frames in {elapsed:.2f}s ({frame_count/elapsed:.1f} FPS)")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        iterator.close()
        print("Iterator closed")

if __name__ == "__main__":
    test_pynvvideocodec_local()