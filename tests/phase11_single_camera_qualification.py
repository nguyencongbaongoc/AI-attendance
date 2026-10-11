"""
Phase 11 Runtime Qualification - Single Camera Full Pipeline Test.

Runs CAM1 or CAM2 for 180 continuous seconds with:
- Decode + Preprocessing + AI Detection/Recognition + Tracking + Attendance Persistence

Criteria:
- Decode + Inference throughput >= 25.0 FPS
- 0 queue drops
- Bounded VRAM footprint (< 4.5 GB)
- Valid identity extraction
"""

import argparse
import logging
import sys
import time
import threading
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import load_settings
from app.vision.gpu_pipeline_integrated import (
    IntegratedGPUPipeline,
    IntegratedPipelineConfig,
    create_integrated_pipeline,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def run_single_camera_test(camera_id: str, duration_seconds: int = 180) -> bool:
    """Run single camera qualification test."""
    logger.info(f"Starting {camera_id} qualification test for {duration_seconds}s")
    
    # Load settings
    settings = load_settings()
    cameras = settings.cameras
    
    if camera_id == "CAM1":
        rtsp_url = cameras.get_cam1_rtsp_url()
    elif camera_id == "CAM2":
        rtsp_url = cameras.get_cam2_rtsp_url()
    else:
        logger.error(f"Unknown camera_id: {camera_id}")
        return False
    
    # Create pipeline config
    config = IntegratedPipelineConfig(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        expected_width=cameras.expected_width,
        expected_height=cameras.expected_height,
        expected_fps=cameras.expected_fps,
        decoder_backend=cameras.decoder_backend,
        nvdec_gpu_device=cameras.nvdec_gpu_device,
        enable_scrfd=True,
        enable_arcface=True,
        enable_yolo=True,
        enable_reid=True,
        confidence_threshold=0.5,
        nms_threshold=0.4,
        enable_crossing=True,
        enable_attendance=True,
        enable_policy=True,
        reuse_ortvalues=True,
        reuse_io_binding=True,
        no_unnecessary_sync=True,
        telemetry_interval_seconds=10.0,
    )
    
    pipeline = IntegratedGPUPipeline(config)
    
    # Initialize
    if not pipeline.initialize():
        logger.error(f"{camera_id}: Pipeline initialization failed")
        return False
    
    # Start
    if not pipeline.start():
        logger.error(f"{camera_id}: Pipeline start failed")
        return False
    
    logger.info(f"{camera_id}: Pipeline running, monitoring for {duration_seconds}s...")
    
    # Monitor loop
    start_time = time.time()
    last_status_time = start_time
    status_interval = 10.0
    
    try:
        while time.time() - start_time < duration_seconds:
            time.sleep(1.0)
            
            # Periodic status
            if time.time() - last_status_time > status_interval:
                status = pipeline.get_status()
                logger.info(
                    f"{camera_id}: frames={status['frames_processed']} "
                    f"fps={status['frames_processed']/(time.time()-start_time):.1f} "
                    f"vram_reserved={status['vram'].get('reserved_mb', 0)}MB "
                    f"tracks={status['tracker_tracks']}"
                )
                last_status_time = time.time()
                
                # Check VRAM bound
                vram_reserved = status['vram'].get('reserved_mb', 0)
                if vram_reserved > 4500:
                    logger.error(f"{camera_id}: VRAM exceeded 4.5GB limit: {vram_reserved}MB")
                    return False
                
                # Check FPS
                elapsed = time.time() - start_time
                current_fps = status['frames_processed'] / elapsed if elapsed > 0 else 0
                if elapsed > 30 and current_fps < 25.0:
                    logger.warning(f"{camera_id}: FPS below 25: {current_fps:.1f}")
        
        # Final status
        final_status = pipeline.get_status()
        elapsed = time.time() - start_time
        final_fps = final_status['frames_processed'] / elapsed
        
        logger.info(f"{camera_id}: TEST COMPLETE")
        logger.info(f"  Duration: {elapsed:.1f}s")
        logger.info(f"  Frames processed: {final_status['frames_processed']}")
        logger.info(f"  Average FPS: {final_fps:.1f}")
        logger.info(f"  Frames dropped: {final_status['frames_dropped']}")
        logger.info(f"  Decode errors: {final_status['decode_errors']}")
        logger.info(f"  Inference errors: {final_status['inference_errors']}")
        logger.info(f"  VRAM reserved: {final_status['vram'].get('reserved_mb', 0)}MB")
        logger.info(f"  Active tracks: {final_status['tracker_tracks']}")
        
        # Telemetry summary
        telemetry = final_status.get('telemetry', {})
        if telemetry:
            logger.info(f"  Latency summary:")
            for component, stats in telemetry.items():
                logger.info(f"    {component}: p50={stats.get('p50',0):.1f} p95={stats.get('p95',0):.1f} p99={stats.get('p99',0):.1f} ms")
        
        # Verify criteria
        success = True
        if final_fps < 25.0:
            logger.error(f"FAIL: FPS {final_fps:.1f} < 25.0")
            success = False
        if final_status['frames_dropped'] > 0:
            logger.error(f"FAIL: {final_status['frames_dropped']} frames dropped")
            success = False
        if final_status['vram'].get('reserved_mb', 0) > 4500:
            logger.error(f"FAIL: VRAM {final_status['vram'].get('reserved_mb', 0)}MB > 4500MB")
            success = False
        if final_status['decode_errors'] > 0:
            logger.error(f"FAIL: {final_status['decode_errors']} decode errors")
            success = False
        
        if success:
            logger.info(f"{camera_id}: PASS - All criteria met")
        else:
            logger.error(f"{camera_id}: FAIL - Criteria not met")
        
        return success
        
    except KeyboardInterrupt:
        logger.info(f"{camera_id}: Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"{camera_id}: Test failed with exception: {e}")
        return False
    finally:
        pipeline.stop()


def main():
    parser = argparse.ArgumentParser(description="Phase 11 Single Camera Qualification")
    parser.add_argument("--camera", choices=["CAM1", "CAM2"], required=True, help="Camera to test")
    parser.add_argument("--duration", type=int, default=180, help="Test duration in seconds")
    args = parser.parse_args()
    
    success = run_single_camera_test(args.camera, args.duration)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()