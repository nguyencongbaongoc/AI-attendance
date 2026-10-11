from pipeline_engine.ingestion.rtsp_source import create_rtsp_source
from pipeline_engine.decode.nvdec_decoder import create_nvdec_decoder
import time

# Test RTSPSource with NVDEC for CAM2
print('Testing RTSPSource + NVDEC for CAM2...')
try:
    # Create RTSP source
    src = create_rtsp_source('cam2')
    if not src.start():
        raise RuntimeError("Failed to start RTSP source")
    
    print(f'Stream info: {src.get_stream_info()}')
    
    time.sleep(2)
    
    # Create NVDEC decoder
    decoder = create_nvdec_decoder('cam2', src)
    if not decoder.start():
        raise RuntimeError("Failed to start NVDEC decoder")
    
    start = time.time()
    frame_count = 0
    for frame in decoder.iter_frames():
        frame_count += 1
        print(f'Frame {frame_count}: shape={frame.width}x{frame.height}, format={frame.pixel_format.value}, pts={frame.pts}')
        if frame_count >= 5:
            break
    elapsed = time.time() - start
    if elapsed > 0:
        print(f'Read {frame_count} frames in {elapsed:.2f}s ({frame_count/elapsed:.1f} FPS)')
    
    decoder.stop()
    src.stop()
    print('RTSPSource + NVDEC CAM2 test PASSED')
except Exception as e:
    print(f'RTSPSource + NVDEC CAM2 test FAILED: {e}')
    import traceback
    traceback.print_exc()