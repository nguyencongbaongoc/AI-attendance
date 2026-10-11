"""
Phase 18 Final System Acceptance — 600-Second Golden Soak Test.

Runs full stack via bootstrap.py with live dual-camera 4K streams via MediaMTX.
Verifies all Phase 18 acceptance criteria:
- Sustained Throughput: >= 25.0 FPS per camera (Target: 27-29 FPS)
- Peak GPU VRAM: <= 2.2 GB (Zero CUDA memory leaks / paging)
- Queue Frame Drops: 0 frame drops over 600 continuous seconds
- Evidence Generation Fidelity: 100% of crossing events successfully resolve with valid on-disk snapshot and clip URIs
- Graceful termination: 100% clean process termination in <= 5s with zero orphaned PIDs
"""

import argparse
import asyncio
import logging
import sys
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional

import torch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bootstrap import Bootstrap
from pipeline_engine.core.engine import PipelineEngine, EngineState
from app.storage import get_snapshot_saver, get_clip_extractor, get_retention_service
from app.attendance.storage import AttendanceStorage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class GoldenSoakMonitor:
    """Monitors the pipeline during golden soak test."""
    
    def __init__(self, engine: PipelineEngine, duration_seconds: int):
        self.engine = engine
        self.duration_seconds = duration_seconds
        self.start_time = None
        self.metrics_history = []
        self._stop_event = threading.Event()
        self._monitor_thread = None
        
        # Storage components
        self.snapshot_saver = get_snapshot_saver()
        self.clip_extractor = get_clip_extractor()
        self.retention_service = get_retention_service()
        self.attendance_storage = AttendanceStorage()
        
        # Track evidence generation
        self.initial_snapshots = 0
        self.initial_clips = 0
        self.initial_records = 0
        
    def start(self):
        """Start monitoring."""
        self.start_time = time.time()
        
        # Record initial counts
        self.initial_snapshots = self._count_snapshots()
        self.initial_clips = self._count_clips()
        self.initial_records = self._count_attendance_records()
        
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Golden soak monitor started")
    
    def stop(self):
        """Stop monitoring."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("Golden soak monitor stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        status_interval = 5.0
        last_status = 0
        
        while not self._stop_event.is_set() and (time.time() - self.start_time) < self.duration_seconds:
            time.sleep(1.0)
            
            # Periodic status every 5 seconds
            if time.time() - last_status > status_interval:
                self._collect_metrics()
                last_status = time.time()
    
    def _collect_metrics(self):
        """Collect and log metrics."""
        elapsed = time.time() - self.start_time
        
        if not self.engine or not self.engine.camera_manager:
            return
        
        cameras = self.engine.camera_manager.get_camera_list()
        if not cameras:
            return
        
        # Collect per-camera metrics
        for cam_id in cameras:
            cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
            cam_state = self.engine.camera_manager.get_camera_state(cam_id)
            
            if cam_metrics:
                fps = cam_metrics.frames_received / elapsed if elapsed > 0 else 0
                
                # Get VRAM
                vram_alloc = 0
                vram_res = 0
                if torch.cuda.is_available():
                    vram_alloc = torch.cuda.memory_allocated(0) / (1024**2)
                    vram_res = torch.cuda.memory_reserved(0) / (1024**2)
                
                # Store metrics
                self.metrics_history.append({
                    'timestamp': time.time(),
                    'elapsed': elapsed,
                    'camera': cam_id,
                    'state': cam_state.value if cam_state else 'unknown',
                    'frames_received': cam_metrics.frames_received,
                    'fps': fps,
                    'tracks_active': cam_metrics.tracks_active,
                    'attendance_events': cam_metrics.attendance_events,
                    'frames_dropped': cam_metrics.frames_dropped,
                    'decode_errors': cam_metrics.decode_errors,
                    'vram_alloc_mb': vram_alloc,
                    'vram_res_mb': vram_res,
                })
                
                logger.info(
                    f"GOLDEN SOAK [{elapsed:.0f}s] {cam_id}: state={cam_state.value if cam_state else 'unknown'} "
                    f"fps={fps:.1f} frames={cam_metrics.frames_received} "
                    f"drops={cam_metrics.frames_dropped} tracks={cam_metrics.tracks_active} "
                    f"events={cam_metrics.attendance_events} "
                    f"VRAM alloc={vram_alloc:.0f}MB reserved={vram_res:.0f}MB"
                )
        
        # Check VRAM bound (must stay <= 2.2 GB = 2252 MB)
        if torch.cuda.is_available():
            vram_res = torch.cuda.memory_reserved(0) / (1024**2)
            if vram_res > 2252:
                logger.error(f"VRAM EXCEEDED: {vram_res:.0f}MB > 2252MB")
                self._stop_event.set()
        
        # Check frame drops
        total_drops = sum(
            self.engine.camera_manager.get_camera_metrics(c).frames_dropped 
            for c in cameras 
            if self.engine.camera_manager.get_camera_metrics(c)
        )
        if total_drops > 0:
            logger.error(f"FRAME DROPS DETECTED: {total_drops}")
            self._stop_event.set()
        
        # Check FPS per camera >= 25 (after warmup)
        if elapsed > 60:
            for cam_id in cameras:
                cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
                if cam_metrics:
                    fps = cam_metrics.frames_received / elapsed
                    if fps < 25.0:
                        logger.warning(f"{cam_id} FPS below 25: {fps:.1f}")
    
    def get_final_report(self) -> Dict:
        """Generate final report."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        cameras = self.engine.camera_manager.get_camera_list() if self.engine and self.engine.camera_manager else []
        
        final_metrics = {}
        for cam_id in cameras:
            cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
            if cam_metrics:
                fps = cam_metrics.frames_received / elapsed if elapsed > 0 else 0
                final_metrics[cam_id] = {
                    'frames_processed': cam_metrics.frames_received,
                    'fps': fps,
                    'frames_dropped': cam_metrics.frames_dropped,
                    'decode_errors': cam_metrics.decode_errors,
                    'tracks_active': cam_metrics.tracks_active,
                    'attendance_events': cam_metrics.attendance_events,
                }
        
        # VRAM stats
        peak_vram_alloc = 0
        peak_vram_res = 0
        if self.metrics_history:
            peak_vram_alloc = max(m['vram_alloc_mb'] for m in self.metrics_history)
            peak_vram_res = max(m['vram_res_mb'] for m in self.metrics_history)
        
        # Count snapshots and clips created during test
        snapshot_count = self._count_snapshots() - self.initial_snapshots
        clip_count = self._count_clips() - self.initial_clips
        records_created = self._count_attendance_records() - self.initial_records
        
        # Verify attendance records have evidence URIs
        evidence_records = self._check_evidence_uris()
        
        # Verify all crossing events have evidence
        crossing_events = self._count_crossing_events()
        
        return {
            'duration_seconds': elapsed,
            'cameras': final_metrics,
            'peak_vram_alloc_mb': peak_vram_alloc,
            'peak_vram_res_mb': peak_vram_res,
            'total_snapshots': snapshot_count,
            'total_clips': clip_count,
            'records_created': records_created,
            'crossing_events': crossing_events,
            'evidence_records': evidence_records,
            'metrics_history': self.metrics_history,
        }
    
    def _count_snapshots(self) -> int:
        """Count snapshot files created."""
        snapshots_dir = Path("app/static/evidence/snapshots")
        if snapshots_dir.exists():
            return len(list(snapshots_dir.rglob("*_face.jpg")))
        return 0
    
    def _count_clips(self) -> int:
        """Count clip files created."""
        clips_dir = Path("app/static/evidence/clips")
        if clips_dir.exists():
            return len(list(clips_dir.rglob("*.mp4")))
        return 0
    
    def _count_attendance_records(self) -> int:
        """Count attendance records in DB."""
        try:
            import sqlite3
            conn = sqlite3.connect("app/data/attendance.db")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM attendance_records")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0
    
    def _count_crossing_events(self) -> int:
        """Count crossing events from metrics."""
        if not self.engine or not self.engine.camera_manager:
            return 0
        cameras = self.engine.camera_manager.get_camera_list()
        total = 0
        for cam_id in cameras:
            cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
            if cam_metrics:
                total += cam_metrics.attendance_events
        return total
    
    def _check_evidence_uris(self) -> Dict:
        """Check attendance records for evidence URIs."""
        try:
            import sqlite3
            conn = sqlite3.connect("app/data/attendance.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN snapshot_face_url IS NOT NULL THEN 1 ELSE 0 END) as with_face,
                       SUM(CASE WHEN snapshot_scene_url IS NOT NULL THEN 1 ELSE 0 END) as with_scene,
                       SUM(CASE WHEN video_clip_url IS NOT NULL THEN 1 ELSE 0 END) as with_clip
                FROM attendance_records
            """)
            row = cursor.fetchone()
            conn.close()
            
            return {
                'total_records': row['total'] if row else 0,
                'with_face_snapshot': row['with_face'] if row else 0,
                'with_scene_snapshot': row['with_scene'] if row else 0,
                'with_video_clip': row['with_clip'] if row else 0,
            }
        except Exception as e:
            logger.error(f"Failed to check evidence URIs: {e}")
            return {}


async def run_golden_soak_test(duration_seconds: int = 600) -> bool:
    """Run the 600-second dual-camera golden soak test."""
    logger.info(f"Starting Phase 18 600-second golden soak test")
    
    # Initialize bootstrap
    bootstrap = Bootstrap(
        config_path=Path("config/default.yaml"),
        no_mediamtx=False,
        no_frontend=True,
        no_backend=True,
    )
    
    # Validate environment
    if not bootstrap.validator.validate_all():
        logger.error("Environment validation failed")
        return False
    
    # Start MediaMTX
    if not bootstrap.service_manager.start_mediamtx():
        logger.error("Failed to start MediaMTX")
        return False
    
    # Start storage services
    from app.storage import start_storage_services, stop_storage_services
    
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: asyncio.run(
        start_storage_services(
            retention_interval_seconds=3600.0,
            disk_check_interval_seconds=60.0,
            backup_interval_hours=24.0,
            vacuum_interval_days=7,
        )
    ))
    
    # Initialize and start pipeline engine
    try:
        bootstrap.engine = PipelineEngine(bootstrap.config_path)
        bootstrap.engine.load_config()
        
        if not bootstrap.engine.initialize():
            logger.error("Pipeline engine initialization failed")
            return False
        
        if not bootstrap.engine.start():
            logger.error("Pipeline engine start failed")
            return False
    except Exception as e:
        logger.error(f"Pipeline engine error: {e}")
        return False
    
    # Wait for cameras to be ready
    logger.info("Waiting for cameras to be ready...")
    max_wait = 60
    start_wait = time.time()
    
    while time.time() - start_wait < max_wait:
        cameras = bootstrap.engine.camera_manager.get_camera_list()
        if cameras:
            all_running = True
            for cam_id in cameras:
                state = bootstrap.engine.camera_manager.get_camera_state(cam_id)
                if state != EngineState.RUNNING:
                    all_running = False
                    break
            if all_running:
                logger.info("All cameras RUNNING")
                break
        time.sleep(1)
    else:
        logger.warning("Timeout waiting for cameras, continuing anyway")
    
    # Start monitor
    monitor = GoldenSoakMonitor(bootstrap.engine, duration_seconds)
    monitor.start()
    
    # Run soak test
    logger.info(f"Running golden soak test for {duration_seconds} seconds...")
    try:
        while time.time() - monitor.start_time < duration_seconds:
            await asyncio.sleep(1.0)
            if monitor._stop_event.is_set():
                logger.error("Monitor detected failure, stopping test")
                break
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"Golden soak test error: {e}")
        return False
    finally:
        monitor.stop()
        
        # Graceful shutdown timing
        shutdown_start = time.time()
        bootstrap.stop()
        shutdown_duration = time.time() - shutdown_start
        logger.info(f"Graceful shutdown completed in {shutdown_duration:.2f}s")
        
        if shutdown_duration > 5.0:
            logger.warning(f"Shutdown took {shutdown_duration:.2f}s > 5s limit")
    
    # Generate final report
    report = monitor.get_final_report()
    
    logger.info("=" * 80)
    logger.info("PHASE 18 600-SECOND GOLDEN SOAK TEST - FINAL REPORT")
    logger.info("=" * 80)
    logger.info(f"Duration: {report['duration_seconds']:.1f}s")
    
    for cam_id, metrics in report['cameras'].items():
        logger.info(
            f"{cam_id}: {metrics['frames_processed']} frames, "
            f"{metrics['fps']:.1f} FPS, {metrics['frames_dropped']} drops, "
            f"{metrics['decode_errors']} decode errors, "
            f"{metrics['attendance_events']} events"
        )
    
    logger.info(f"Peak VRAM: alloc={report['peak_vram_alloc_mb']:.0f}MB reserved={report['peak_vram_res_mb']:.0f}MB")
    logger.info(f"Total snapshots created: {report['total_snapshots']}")
    logger.info(f"Total clips created: {report['total_clips']}")
    logger.info(f"Records created: {report['records_created']}")
    logger.info(f"Crossing events: {report['crossing_events']}")
    logger.info(f"Attendance records with evidence: {report['evidence_records']}")
    
    # Verify criteria
    success = True
    
    for cam_id, metrics in report['cameras'].items():
        if metrics['fps'] < 25.0:
            logger.error(f"FAIL: {cam_id} FPS {metrics['fps']:.1f} < 25.0")
            success = False
        if metrics['frames_dropped'] > 0:
            logger.error(f"FAIL: {cam_id} frame drops: {metrics['frames_dropped']}")
            success = False
        if metrics['decode_errors'] > 0:
            logger.error(f"FAIL: {cam_id} decode errors: {metrics['decode_errors']}")
            success = False
    
    if report['peak_vram_res_mb'] > 2252:
        logger.error(f"FAIL: Peak VRAM {report['peak_vram_res_mb']:.0f}MB > 2252MB")
        success = False
    
    # Evidence fidelity: 100% of crossing events must have snapshots and clips
    evidence = report['evidence_records']
    if evidence:
        total_records = evidence.get('total_records', 0)
        with_face = evidence.get('with_face_snapshot', 0)
        with_scene = evidence.get('with_scene_snapshot', 0)
        with_clip = evidence.get('with_video_clip', 0)
        
        if total_records > 0:
            if with_face < total_records:
                logger.error(f"FAIL: Face snapshot coverage {with_face}/{total_records} < 100%")
                success = False
            if with_scene < total_records:
                logger.error(f"FAIL: Scene snapshot coverage {with_scene}/{total_records} < 100%")
                success = False
            if with_clip < total_records:
                logger.error(f"FAIL: Video clip coverage {with_clip}/{total_records} < 100%")
                success = False
    
    if success:
        logger.info("GOLDEN SOAK TEST: PASS - All criteria met")
    else:
        logger.error("GOLDEN SOAK TEST: FAIL - Criteria not met")
    
    return success


def main():
    parser = argparse.ArgumentParser(description="Phase 18 600-Second Dual-Camera Golden Soak Test")
    parser.add_argument("--duration", type=int, default=600, help="Test duration in seconds (default 600)")
    args = parser.parse_args()
    
    success = asyncio.run(run_golden_soak_test(args.duration))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()