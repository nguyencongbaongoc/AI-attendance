from pipeline_engine.ingestion.rtsp_source import create_rtsp_source
from pipeline_engine.decode.nvdec_decoder import create_nvdec_decoder
import time
import threading
import queue

# Test dual-camera concurrent NVDEC
print('Testing Dual-Camera Concurrent NVDEC...')

results = queue.Queue()

def test_camera(camera_id):
    try:
        # Create RTSP source
        src = create_rtsp_source(camera_id)
        if not src.start():
            raise RuntimeError(f"Failed to start RTSP source for {camera_id}")
        
        # Create NVDEC decoder
        decoder = create_nvdec_decoder(camera_id, src)
        if not decoder.start():
            raise RuntimeError(f"Failed to start NVDEC decoder for {camera_id}")
        
        start = time.time()
        frame_count = 0
        for frame in decoder.iter_frames():
            frame_count += 1
            if frame_count >= 10:
                break
        elapsed = time.time() - start
        fps = frame_count / elapsed if elapsed > 0 else 0
        
        decoder.stop()
        src.stop()
        
        results.put((camera_id, True, fps, frame_count, None))
        print(f'{camera_id}: {frame_count} frames in {elapsed:.2f}s ({fps:.1f} FPS) - PASSED')
    except Exception as e:
        results.put((camera_id, False, 0, 0, str(e)))
        print(f'{camera_id}: FAILED - {e}')

# Start both cameras concurrently
threads = []
for cam_id in ['cam1', 'cam2']:
    t = threading.Thread(target=test_camera, args=(cam_id,))
    threads.append(t)
    t.start()

# Wait for completion
for t in threads:
    t.join(timeout=30)

# Collect results
all_passed = True
total_fps = 0
while not results.empty():
    camera_id, passed, fps, frame_count, error = results.get()
    if passed:
        total_fps += fps
    else:
        all_passed = False

print(f'Dual-camera concurrent test: {"PASSED" if all_passed else "FAILED"}')
print(f'Total combined FPS: {total_fps:.1f}')