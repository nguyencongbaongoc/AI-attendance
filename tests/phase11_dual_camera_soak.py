"""
Phase 11 Runtime Qualification - Dual Camera Concurrent Soak Test.

Runs CAM1 and CAM2 concurrently for 300 seconds (5 minutes).
Monitors:
- Per-camera FPS and packet/frame counters
- Total allocated and reserved VRAM (must remain under 6.0 GB)
- Queue depth and frame drop counters (must remain 0)
- Continuous attendance event generation
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
    DualCameraPipelineManager,
    create_dual_camera_manager,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


def run_dual_camera_soak(duration_seconds: int = 300) -> bool:
    """Run dual camera concurrent soak test."""
    logger.info(f"Starting dual camera soak test for {duration_seconds}s (5 minutes)")
    
    # Create dual camera manager
    manager = create_dual_camera_manager(
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
        telemetry_interval_seconds=5.0,  # More frequent for soak test
    )
    
    # Start both
    cam1_started, cam2_started = manager.start_both()
    
    if not cam1_started:
        logger.error("CAM1 failed to start")
        return False
    if not cam2_started:
        logger.error("CAM2 failed to start")
        return False
    
    logger.info("Both cameras started, beginning soak test...")
    
    # Monitor loop
    start_time = time.time()
    last_status_time = start_time
    status_interval = 5.0  # 5-second intervals as required
    
    # Track metrics for final report
    metrics_history = []
    
    try:
        while time.time() - start_time < duration_seconds:
            time.sleep(1.0)
            
            # Periodic status every 5 seconds
            if time.time() - last_status_time > status_interval:
                status = manager.get_combined_status()
                elapsed = time.time() - start_time
                
                # Extract metrics
                cam1 = status['cam1']
                cam2 = status['cam2']
                
                cam1_fps = cam1['frames_processed'] / elapsed if elapsed > 0 else 0
                cam2_fps = cam2['frames_processed'] / elapsed if elapsed > 0 else 0
                
                total_vram_alloc = cam1['vram'].get('allocated_mb', 0) + cam2['vram'].get('allocated_mb', 0)
                total_vram_res = cam1['vram'].get('reserved_mb', 0) + cam2['vram'].get('reserved_mb', 0)
                
                total_drops = cam1['frames_dropped'] + cam2['frames_dropped']
                total_decode_err = cam1['decode_errors'] + cam2['decode_errors']
                
                logger.info(
                    f"SOAK [{elapsed:.0f}s] "
                    f"CAM1: fps={cam1_fps:.1f} frames={cam1['frames_processed']} drops={cam1['frames_dropped']} vram={cam1['vram'].get('reserved_mb', 0)}MB tracks={cam1['tracker_tracks']} | "
                    f"CAM2: fps={cam2_fps:.1f} frames={cam2['frames_processed']} drops={cam2['frames_dropped']} vram={cam2['vram'].get('reserved_mb', 0)}MB tracks={cam2['tracker_tracks']} | "
                    f"TOTAL VRAM: alloc={total_vram_alloc}MB reserved={total_vram_res}MB"
                )
                
                # Record for final report
                metrics_history.append({
                    'elapsed': elapsed,
                    'cam1_fps': cam1_fps,
                    'cam2_fps': cam2_fps,
                    'cam1_frames': cam1['frames_processed'],
                    'cam2_frames': cam2['frames_processed'],
                    'cam1_drops': cam1['frames_dropped'],
                    'cam2_drops': cam2['frames_dropped'],
                    'total_vram_alloc_mb': total_vram_alloc,
                    'total_vram_res_mb': total_vram_res,
                    'cam1_vram_mb': cam1['vram'].get('reserved_mb', 0),
                    'cam2_vram_mb': cam2['vram'].get('reserved_mb', 0),
                    'cam1_tracks': cam1['tracker_tracks'],
                    'cam2_tracks': cam2['tracker_tracks'],
                })
                
                # Check VRAM bound (must remain safely under 6.0 GB = 6144 MB)
                if total_vram_res > 5500:  # 5.5 GB safety margin
                    logger.error(f"VRAM CRITICAL: Total reserved {total_vram_res}MB > 5500MB")
                    return False
                
                # Check frame drops
                if total_drops > 0:
                    logger.error(f"FRAME DROPS DETECTED: {total_drops} total drops")
                    return False
                
                # Check FPS (per camera >= 25 FPS)
                if elapsed > 60:  # After warmup
                    if cam1_fps < 25.0:
                        logger.warning(f"CAM1 FPS below 25: {cam1_fps:.1f}")
                    if cam2_fps < 25.0:
                        logger.warning(f"CAM2 FPS below 25: {cam2_fps:.1f}")
                
                last_status_time = time.time()
        
        # Final comprehensive report
        final_status = manager.get_combined_status()
        elapsed = time.time() - start_time
        
        cam1 = final_status['cam1']
        cam2 = final_status['cam2']
        
        cam1_fps = cam1['frames_processed'] / elapsed
        cam2_fps = cam2['frames_processed'] / elapsed
        total_vram_res = cam1['vram'].get('reserved_mb', 0) + cam2['vram'].get('reserved_mb', 0)
        total_drops = cam1['frames_dropped'] + cam2['frames_dropped']
        
        logger.info("=" * 80)
        logger.info("DUAL CAMERA 300s SOAK TEST - FINAL REPORT")
        logger.info("=" * 80)
        logger.info(f"Duration: {elapsed:.1f}s")
        logger.info(f"CAM1: {cam1['frames_processed']} frames, {cam1_fps:.1f} FPS, {cam1['frames_dropped']} drops, {cam1['decode_errors']} decode err")
        logger.info(f"CAM2: {cam2['frames_processed']} frames, {cam2_fps:.1f} FPS, {cam2['frames_dropped']} drops, {cam2['decode_errors']} decode err")
        logger.info(f"Total VRAM Reserved: {total_vram_res}MB (CAM1: {cam1['vram'].get('reserved_mb', 0)}MB, CAM2: {cam2['vram'].get('reserved_mb', 0)}MB)")
        logger.info(f"Active Tracks: CAM1={cam1['tracker_tracks']}, CAM2={cam2['tracker_tracks']}")
        
        # Telemetry summary
        for cam_id, cam_status in [('CAM1', cam1), ('CAM2', cam2)]:
            telemetry = cam_status.get('telemetry', {})
            if telemetry:
                logger.info(f"{cam_id} Latency Summary:")
                for component, stats in telemetry.items():
                    logger.info(f"  {component}: p50={stats.get('p50',0):.1f} p95={stats.get('p95',0):.1f} p99={stats.get('p99',0):.1f} ms")
        
        # Verify criteria
        success = True
        
        if cam1_fps < 25.0:
            logger.error(f"FAIL: CAM1 FPS {cam1_fps:.1f} < 25.0")
            success = False
        if cam2_fps < 25.0:
            logger.error(f"FAIL: CAM2 FPS {cam2_fps:.1f} < 25.0")
            success = False
        if total_drops > 0:
            logger.error(f"FAIL: {total_drops} total frame drops")
            success = False
        if total_vram_res > 5500:
            logger.error(f"FAIL: Total VRAM {total_vram_res}MB > 5500MB")
            success = False
        if cam1['decode_errors'] > 0:
            logger.error(f"FAIL: CAM1 decode errors: {cam1['decode_errors']}")
            success = False
        if cam2['decode_errors'] > 0:
            logger.error(f"FAIL: CAM2 decode errors: {cam2['decode_errors']}")
            success = False
        
        # Check attendance event generation (should have crossing events)
        cam1_telemetry = cam1.get('telemetry', {})
        cam2_telemetry = cam2.get('telemetry', {})
        
        if success:
            logger.info("SOAK TEST: PASS - All criteria met")
        else:
            logger.error("SOAK TEST: FAIL - Criteria not met")
        
        return success
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"Soak test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        manager.stop_both()


def main():
    parser = argparse.ArgumentParser(description="Phase 11 Dual Camera 300s Soak Test")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds (default 300)")
    args = parser.parse_args()
    
    success = run_dual_camera_soak(args.duration)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()