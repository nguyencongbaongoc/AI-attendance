from app.streaming.rtsp_source import create_rtsp_source
import time

# Test RTSPSource with NVDEC for CAM2
print('Testing RTSPSource with NVDEC for CAM2...')
try:
    src = create_rtsp_source('CAM2', 'rtsp://127.0.0.1:8554/live/cam2', decoder='nvdec', nvdec_gpu_device=0)
    info = src.open()
    print(f'Stream info: {info.width}x{info.height} @ {info.fps} fps')
    
    time.sleep(2)
    
    start = time.time()
    frame_count = 0
    for frame in src:
        frame_count += 1
        cam_id = frame.metadata.extra.get("camera_id")
        print(f'Frame {frame_count}: shape={frame.shape}, format={frame.metadata.pixel_format}, camera_id={cam_id}')
        if frame_count >= 5:
            break
    elapsed = time.time() - start
    if elapsed > 0:
        print(f'Read {frame_count} frames in {elapsed:.2f}s ({frame_count/elapsed:.1f} FPS)')
    src.close()
    print('RTSPSource NVDEC CAM2 test PASSED')
except Exception as e:
    print(f'RTSPSource NVDEC CAM2 test FAILED: {e}')
    import traceback
    traceback.print_exc()