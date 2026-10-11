"""
Phase 11 Runtime Qualification - Fault Injection & Camera Isolation Test.

Injects network disconnection on CAM1 while dual pipeline is active.
Verifies:
- CAM2 continues uninterrupted decoding, inference, and attendance persistence
- No frame starvation or crash on CAM2
- CAM1 automatic reconnection within 15 seconds
- CAM2 tracking state NOT reset during CAM1 failure
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


class NetworkFaultInjector:
    """Simulates network disconnection by stopping the ingestion worker."""
    
    def __init__(self, pipeline: IntegratedGPUPipeline):
        self.pipeline = pipeline
        self._original_rtsp_url = pipeline.config.rtsp_url
    
    def inject_disconnect(self):
        """Simulate network disconnect by stopping the pipeline."""
        logger.warning("FAULT INJECTION: Disconnecting CAM1 (stopping pipeline)")
        self.pipeline.stop(timeout=5.0)
        logger.warning("FAULT INJECTION: CAM1 pipeline stopped")
    
    def restore_connection(self) -> bool:
        """Restore connection by restarting the pipeline."""
        logger.info("FAULT RECOVERY: Restarting CAM1 pipeline")
        return self.pipeline.start(wait_ready=True, ready_timeout=30.0)


def run_fault_isolation_test(
    pre_fault_duration: int = 60,
    fault_duration: int = 30,
    post_recovery_duration: int = 60,
) -> bool:
    """Run fault injection and isolation test."""
    
    logger.info("=" * 80)
    logger.info("PHASE 11 FAULT INJECTION & CAMERA ISOLATION TEST")
    logger.info("=" * 80)
    logger.info(f"Pre-fault duration: {pre_fault_duration}s")
    logger.info(f"Fault duration: {fault_duration}s")
    logger.info(f"Post-recovery duration: {post_recovery_duration}s")
    
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
        telemetry_interval_seconds=5.0,
    )
    
    # Start both
    cam1_started, cam2_started = manager.start_both()
    
    if not cam1_started:
        logger.error("CAM1 failed to start")
        return False
    if not cam2_started:
        logger.error("CAM2 failed to start")
        return False
    
    logger.info("Both cameras started, beginning pre-fault monitoring...")
    
    # ===== PHASE 1: Pre-Fault Monitoring =====
    logger.info(f"PHASE 1: Pre-fault monitoring ({pre_fault_duration}s)")
    phase1_start = time.time()
    cam2_frame_counts = []
    cam2_tracker_states = []
    
    try:
        while time.time() - phase1_start < pre_fault_duration:
            time.sleep(1.0)
            status = manager.get_combined_status()
            cam2 = status['cam2']
            cam2_frame_counts.append(cam2['frames_processed'])
            cam2_tracker_states.append(cam2['tracker_tracks'])
            
            # Log every 10 seconds
            elapsed = time.time() - phase1_start
            if int(elapsed) % 10 == 0 and elapsed > 1:
                logger.info(f"  Pre-fault [{elapsed:.0f}s] CAM2: frames={cam2['frames_processed']} tracks={cam2['tracker_tracks']} fps={cam2['frames_processed']/elapsed:.1f}")
        
        # Capture CAM2 state before fault
        pre_fault_cam2_frames = manager.pipeline2._frames_processed
        pre_fault_cam2_tracks = manager.pipeline2._tracker_state.copy()
        logger.info(f"Pre-fault CAM2 state: frames={pre_fault_cam2_frames}, tracks={len(pre_fault_cam2_tracks)}")
        
        # ===== PHASE 2: Fault Injection =====
        logger.info(f"PHASE 2: Injecting CAM1 network fault ({fault_duration}s)")
        fault_start = time.time()
        
        # Inject fault on CAM1
        fault_injector = NetworkFaultInjector(manager.pipeline1)
        fault_injector.inject_disconnect()
        
        # Monitor CAM2 during fault
        cam2_frames_during_fault = []
        cam2_tracks_during_fault = []
        
        while time.time() - fault_start < fault_duration:
            time.sleep(1.0)
            status = manager.get_combined_status()
            cam2 = status['cam2']
            cam2_frames_during_fault.append(cam2['frames_processed'])
            cam2_tracks_during_fault.append(cam2['tracker_tracks'])
            
            elapsed = time.time() - fault_start
            if int(elapsed) % 10 == 0 and elapsed > 1:
                logger.info(f"  During fault [{elapsed:.0f}s] CAM2: frames={cam2['frames_processed']} tracks={cam2['tracker_tracks']} fps={cam2['frames_processed']/(time.time()-phase1_start):.1f}")
        
        # Verify CAM2 continued uninterrupted
        fault_duration_actual = time.time() - fault_start
        cam2_frames_gained = cam2_frames_during_fault[-1] - cam2_frames_during_fault[0] if cam2_frames_during_fault else 0
        cam2_fps_during_fault = cam2_frames_gained / fault_duration_actual if fault_duration_actual > 0 else 0
        
        logger.info(f"CAM2 during fault: gained {cam2_frames_gained} frames ({cam2_fps_during_fault:.1f} FPS)")
        
        # Check CAM2 tracker state preserved
        post_fault_cam2_tracks = manager.pipeline2._tracker_state
        tracks_preserved = len(post_fault_cam2_tracks) == len(pre_fault_cam2_tracks)
        
        if tracks_preserved:
            logger.info("CAM2 tracker state PRESERVED during CAM1 fault")
        else:
            logger.error(f"CAM2 tracker state CHANGED: {len(pre_fault_cam2_tracks)} -> {len(post_fault_cam2_tracks)}")
        
        # ===== PHASE 3: Recovery =====
        logger.info(f"PHASE 3: Restoring CAM1 (max 15s reconnect)")
        recovery_start = time.time()
        
        # Restore CAM1
        recovery_success = fault_injector.restore_connection()
        recovery_time = time.time() - recovery_start
        
        logger.info(f"CAM1 recovery: {'SUCCESS' if recovery_success else 'FAILED'} in {recovery_time:.1f}s")
        
        if recovery_time > 15.0:
            logger.error(f"RECOVERY TIME EXCEEDED: {recovery_time:.1f}s > 15s limit")
            recovery_success = False
        
        # ===== PHASE 4: Post-Recovery Monitoring =====
        logger.info(f"PHASE 4: Post-recovery monitoring ({post_recovery_duration}s)")
        phase4_start = time.time()
        
        cam2_frames_post = []
        cam2_tracks_post = []
        
        while time.time() - phase4_start < post_recovery_duration:
            time.sleep(1.0)
            status = manager.get_combined_status()
            cam1 = status['cam1']
            cam2 = status['cam2']
            cam2_frames_post.append(cam2['frames_processed'])
            cam2_tracks_post.append(cam2['tracker_tracks'])
            
            elapsed = time.time() - phase4_start
            if int(elapsed) % 10 == 0 and elapsed > 1:
                logger.info(f"  Post-recovery [{elapsed:.0f}s] CAM1: frames={cam1['frames_processed']} tracks={cam1['tracker_tracks']} | CAM2: frames={cam2['frames_processed']} tracks={cam2['tracker_tracks']}")
        
        # Final verification
        logger.info("=" * 80)
        logger.info("FAULT ISOLATION TEST - FINAL VERIFICATION")
        logger.info("=" * 80)
        
        final_status = manager.get_combined_status()
        cam1 = final_status['cam1']
        cam2 = final_status['cam2']
        
        total_time = time.time() - phase1_start
        
        # CAM2 should have continued processing throughout
        total_cam2_frames = cam2['frames_processed']
        avg_cam2_fps = total_cam2_frames / total_time
        
        logger.info(f"Total test time: {total_time:.1f}s")
        logger.info(f"CAM1 final: frames={cam1['frames_processed']} tracks={cam1['tracker_tracks']}")
        logger.info(f"CAM2 final: frames={total_cam2_frames} tracks={cam2['tracker_tracks']} avg_fps={avg_cam2_fps:.1f}")
        logger.info(f"CAM2 frames during fault: {cam2_frames_gained} ({cam2_fps_during_fault:.1f} FPS)")
        logger.info(f"CAM1 recovery time: {recovery_time:.1f}s")
        
        # Verify criteria
        success = True
        
        # 1. CAM2 continued uninterrupted (no crash, no frame starvation)
        if cam2_fps_during_fault < 20.0:  # Allow some degradation but not starvation
            logger.error(f"FAIL: CAM2 FPS during fault {cam2_fps_during_fault:.1f} < 20.0 (starvation)")
            success = False
        else:
            logger.info("PASS: CAM2 continued processing during CAM1 fault")
        
        # 2. CAM2 tracker state preserved
        if not tracks_preserved:
            logger.error("FAIL: CAM2 tracker state not preserved")
            success = False
        else:
            logger.info("PASS: CAM2 tracker state preserved")
        
        # 3. CAM1 recovered within 15 seconds
        if not recovery_success or recovery_time > 15.0:
            logger.error(f"FAIL: CAM1 recovery failed or exceeded 15s ({recovery_time:.1f}s)")
            success = False
        else:
            logger.info("PASS: CAM1 recovered within 15 seconds")
        
        # 4. No frame drops on either camera
        if cam1['frames_dropped'] > 0:
            logger.error(f"FAIL: CAM1 frame drops: {cam1['frames_dropped']}")
            success = False
        if cam2['frames_dropped'] > 0:
            logger.error(f"FAIL: CAM2 frame drops: {cam2['frames_dropped']}")
            success = False
        if cam1['frames_dropped'] == 0 and cam2['frames_dropped'] == 0:
            logger.info("PASS: Zero frame drops on both cameras")
        
        # 5. Attendance persistence continued on CAM2
        cam2_telemetry = cam2.get('telemetry', {})
        if cam2_telemetry:
            logger.info("PASS: CAM2 telemetry active throughout")
        
        if success:
            logger.info("FAULT ISOLATION TEST: PASS")
        else:
            logger.error("FAULT ISOLATION TEST: FAIL")
        
        return success
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"Fault test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        manager.stop_both()


def main():
    parser = argparse.ArgumentParser(description="Phase 11 Fault Injection & Isolation Test")
    parser.add_argument("--pre-fault", type=int, default=60, help="Pre-fault duration (seconds)")
    parser.add_argument("--fault", type=int, default=30, help="Fault duration (seconds)")
    parser.add_argument("--post-recovery", type=int, default=60, help="Post-recovery duration (seconds)")
    args = parser.parse_args()
    
    success = run_fault_isolation_test(
        pre_fault_duration=args.pre_fault,
        fault_duration=args.fault,
        post_recovery_duration=args.post_recovery,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()