"""
Real NVDEC Test - V2 GPU Pipeline
Tests: RTSP/Video file → Compressed Packets → NVDEC → GPUFrame
"""

import sys
import os
import time
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from video_pipeline_v2.input.packet_input import create_packet_source
from video_pipeline_v2.decoder.nvdec_decoder import NVDECDecoder, NVDECDecoderConfig
from video_pipeline_v2.core.gpu_frame import GPUFrame


def test_nvdec_with_file():
    """Test NVDEC decoder with a video file."""
    
    # Use a test video file
    test_file = "test_video.mp4"
    
    if not os.path.exists(test_file):
        logger.error(f"Test file not found: {test_file}")
        return False
    
    logger.info(f"=== Testing NVDEC with file: {test_file} ===")
    
    # Create packet source (file source)
    packet_source = create_packet_source("file", "test_cam", test_file)
    packet_source.open()
    
    # Create decoder config
    config = NVDECDecoderConfig(
        camera_id="test_cam",
        packet_source=packet_source,
        gpu_device=0,
        max_queue_size=8,
    )
    
    # Create and start decoder
    decoder = NVDECDecoder(config)
    
    if not decoder.start():
        logger.error("Failed to start decoder")
        return False
    
    # Decode frames and measure performance
    logger.info("Starting frame decode loop...")
    
    frames_decoded = 0
    frames_dropped = 0
    decode_times = []
    start_time = time.time()
    
    for i, frame in enumerate(decoder.iter_frames()):
        if not frame.validate():
            logger.warning(f"Frame {i}: Invalid GPUFrame")
            continue
        
        decode_times.append(time.time() - start_time)
        frames_decoded += 1
        
        if i % 30 == 0:
            logger.info(f"Frame {i}: {frame.width}x{frame.height}, pts={frame.pts}, format={frame.pixel_format}")
        
        # Stop after 100 frames for quick test
        if i >= 100:
            break
    
    elapsed = time.time() - start_time
    
    # Get metrics
    stats = decoder.get_stats()
    
    logger.info(f"=== NVDEC Test Results ===")
    logger.info(f"Frames decoded: {frames_decoded}")
    logger.info(f"Elapsed time: {elapsed:.2f}s")
    logger.info(f"Avg decode FPS: {frames_decoded/elapsed:.2f}")
    logger.info(f"Decoder stats: {stats}")
    
    decoder.stop()
    packet_source.close()
    
    return frames_decoded > 0


if __name__ == "__main__":
    success = test_nvdec_with_file()
if success:
    print("\nPASS: NVDEC Test PASSED")
else:
    print("\nFAIL: NVDEC Test FAILED")
    sys.exit(0 if success else 1)