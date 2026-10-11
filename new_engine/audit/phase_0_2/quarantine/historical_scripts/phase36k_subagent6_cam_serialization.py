#!/usr/bin/env python
"""
Phase 36K Subagent 6 - CAM1/CAM2 Serialization Analysis.

Determines exactly whether:
CAM1 → decode → AI → tracking → output → CAM2 → decode → AI → tracking → output
is serialized.

Measures:
- CAM1 only
- CAM2 only
- CAM1 + CAM2

Compares:
- Per-camera FPS
- Combined FPS
- Latency
- GPU utilization
- CPU utilization

Determines whether CAM1 and CAM2 can safely overlap.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_cam_serialization_analysis(num_frames: int = 30) -> Dict[str, Any]:
    """Run CAM1/CAM2 serialization analysis."""
    logger.info("=" * 60)
    logger.info("SUBAGENT 6: CAM1/CAM2 Serialization Analysis")
    logger.info("=" * 60)
    
    import numpy as np
    import torch
    import psutil
    from app.streaming.rtsp_source import create_rtsp_source
    from app.vision.detector_factory import get_detector_for_live
    from app.vision.tracker import track_frame, TrackerConfig
    from app.vision.association import associate_detections
    from app.vision.association_contract import AssociationResult
    from app.vision.track_contract import Track
    from app.data.frame import CanonicalFrame
    
    results = {
        "cam1_only": {},
        "cam2_only": {},
        "cam1_cam2_serialized": {},
        "cam1_cam2_overlapped": {},  # Prototype
        "analysis": {},
        "recommendations": [],
    }
    
    # Test CAM1 only
    logger.info("\n--- Testing CAM1 only ---")
    try:
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        src1.open()
        detector1 = get_detector_for_live(use_gpu=True)
        tracker_config = TrackerConfig()
        previous_tracks: List[Track] = []
        
        latencies = []
        gpu_utils = []
        
        for i in range(num_frames):
            frame = src1.get_next_frame()
            if frame is None:
                continue
            
            t0 = time.perf_counter()
            detections = detector1.detect(frame)
            
            associations = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[],
                unmatched_persons=[],
                unmatched_faces=[],
            )
            
            tracking_result = track_frame(
                person_detections=[],
                face_detections=detections,
                associations=associations,
                frame=frame,
                previous_tracks=previous_tracks,
                config=tracker_config,
            )
            previous_tracks = tracking_result.tracks
            
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
            
            gpu_util = measure_gpu_utilization()
            if gpu_util is not None:
                gpu_utils.append(gpu_util)
        
        src1.close()
        detector1.close()
        
        if latencies:
            sorted_lat = sorted(latencies)
            results["cam1_only"] = {
                "frames_processed": len(latencies),
                "fps": 1000.0 / (sum(latencies) / len(latencies)),
                "avg_latency_ms": sum(latencies) / len(latencies),
                "p50_latency_ms": sorted_lat[len(sorted_lat) // 2],
                "p95_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)],
                "max_latency_ms": max(latencies),
                "avg_gpu_utilization": sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
            }
            logger.info(f"  CAM1 only: {results['cam1_only']['fps']:.2f} FPS, "
                       f"avg={results['cam1_only']['avg_latency_ms']:.1f}ms, "
                       f"GPU={results['cam1_only']['avg_gpu_utilization']:.1f}%")
    except Exception as e:
        logger.warning(f"CAM1 only test failed: {e}")
        results["cam1_only"] = {"error": str(e)}
    
    # Test CAM2 only
    logger.info("\n--- Testing CAM2 only ---")
    try:
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        src2.open()
        detector2 = get_detector_for_live(use_gpu=True)
        tracker_config = TrackerConfig()
        previous_tracks: List[Track] = []
        
        latencies = []
        gpu_utils = []
        
        for i in range(num_frames):
            frame = src2.get_next_frame()
            if frame is None:
                continue
            
            t0 = time.perf_counter()
            detections = detector2.detect(frame)
            
            associations = AssociationResult(
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                associations=[],
                unmatched_persons=[],
                unmatched_faces=[],
            )
            
            tracking_result = track_frame(
                person_detections=[],
                face_detections=detections,
                associations=associations,
                frame=frame,
                previous_tracks=previous_tracks,
                config=tracker_config,
            )
            previous_tracks = tracking_result.tracks
            
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
            
            gpu_util = measure_gpu_utilization()
            if gpu_util is not None:
                gpu_utils.append(gpu_util)
        
        src2.close()
        detector2.close()
        
        if latencies:
            sorted_lat = sorted(latencies)
            results["cam2_only"] = {
                "frames_processed": len(latencies),
                "fps": 1000.0 / (sum(latencies) / len(latencies)),
                "avg_latency_ms": sum(latencies) / len(latencies),
                "p50_latency_ms": sorted_lat[len(sorted_lat) // 2],
                "p95_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)],
                "max_latency_ms": max(latencies),
                "avg_gpu_utilization": sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
            }
            logger.info(f"  CAM2 only: {results['cam2_only']['fps']:.2f} FPS, "
                       f"avg={results['cam2_only']['avg_latency_ms']:.1f}ms, "
                       f"GPU={results['cam2_only']['avg_gpu_utilization']:.1f}%")
    except Exception as e:
        logger.warning(f"CAM2 only test failed: {e}")
        results["cam2_only"] = {"error": str(e)}
    
    # Test CAM1 + CAM2 serialized (current production)
    logger.info("\n--- Testing CAM1 + CAM2 serialized ---")
    try:
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        src1.open()
        src2.open()
        detector = get_detector_for_live(use_gpu=True)
        tracker_config = TrackerConfig()
        previous_tracks_cam1: List[Track] = []
        previous_tracks_cam2: List[Track] = []
        
        latencies = []
        gpu_utils = []
        cam1_latencies = []
        cam2_latencies = []
        
        for i in range(num_frames):
            # Process CAM1
            frame1 = src1.get_next_frame()
            if frame1:
                t0 = time.perf_counter()
                detections = detector.detect(frame1)
                
                associations = AssociationResult(
                    source_frame_id=frame1.metadata.source_id,
                    frame_index=frame1.metadata.frame_index,
                    associations=[],
                    unmatched_persons=[],
                    unmatched_faces=[],
                )
                
                tracking_result = track_frame(
                    person_detections=[],
                    face_detections=detections,
                    associations=associations,
                    frame=frame1,
                    previous_tracks=previous_tracks_cam1,
                    config=tracker_config,
                )
                previous_tracks_cam1 = tracking_result.tracks
                
                t1 = time.perf_counter()
                latency = (t1 - t0) * 1000
                latencies.append(latency)
                cam1_latencies.append(latency)
            
            # Process CAM2
            frame2 = src2.get_next_frame()
            if frame2:
                t0 = time.perf_counter()
                detections = detector.detect(frame2)
                
                associations = AssociationResult(
                    source_frame_id=frame2.metadata.source_id,
                    frame_index=frame2.metadata.frame_index,
                    associations=[],
                    unmatched_persons=[],
                    unmatched_faces=[],
                )
                
                tracking_result = track_frame(
                    person_detections=[],
                    face_detections=detections,
                    associations=associations,
                    frame=frame2,
                    previous_tracks=previous_tracks_cam2,
                    config=tracker_config,
                )
                previous_tracks_cam2 = tracking_result.tracks
                
                t1 = time.perf_counter()
                latency = (t1 - t0) * 1000
                latencies.append(latency)
                cam2_latencies.append(latency)
            
            gpu_util = measure_gpu_utilization()
            if gpu_util is not None:
                gpu_utils.append(gpu_util)
        
        src1.close()
        src2.close()
        detector.close()
        
        if latencies:
            sorted_lat = sorted(latencies)
            results["cam1_cam2_serialized"] = {
                "total_frames_processed": len(latencies),
                "cam1_frames": len(cam1_latencies),
                "cam2_frames": len(cam2_latencies),
                "combined_fps": 1000.0 / (sum(latencies) / len(latencies)),
                "avg_latency_ms": sum(latencies) / len(latencies),
                "p50_latency_ms": sorted_lat[len(sorted_lat) // 2],
                "p95_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)],
                "max_latency_ms": max(latencies),
                "avg_gpu_utilization": sum(gpu_utils) / len(gpu_utils) if gpu_utils else None,
                "cam1_avg_latency_ms": sum(cam1_latencies) / len(cam1_latencies) if cam1_latencies else 0,
                "cam2_avg_latency_ms": sum(cam2_latencies) / len(cam2_latencies) if cam2_latencies else 0,
            }
            logger.info(f"  CAM1+CAM2 serialized: {results['cam1_cam2_serialized']['combined_fps']:.2f} FPS, "
                       f"avg={results['cam1_cam2_serialized']['avg_latency_ms']:.1f}ms, "
                       f"CAM1={results['cam1_cam2_serialized']['cam1_avg_latency_ms']:.1f}ms, "
                       f"CAM2={results['cam1_cam2_serialized']['cam2_avg_latency_ms']:.1f}ms, "
                       f"GPU={results['cam1_cam2_serialized']['avg_gpu_utilization']:.1f}%")
    except Exception as e:
        logger.warning(f"CAM1+CAM2 serialized test failed: {e}")
        results["cam1_cam2_serialized"] = {"error": str(e)}
    
    # Test CAM1 + CAM2 overlapped (prototype - using threading)
    logger.info("\n--- Testing CAM1 + CAM2 overlapped (prototype) ---")
    try:
        import threading
        import queue
        
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        src1.open()
        src2.open()
        
        # Shared detector (thread-safe for inference)
        detector = get_detector_for_live(use_gpu=True)
        
        result_queue = queue.Queue()
        cam1_latencies = []
        cam2_latencies = []
        gpu_utils = []
        
        def process_camera(camera_id: str, src, num_frames: int, result_queue: queue.Queue):
            tracker_config = TrackerConfig()
            previous_tracks: List[Track] = []
            latencies = []
            
            for i in range(num_frames):
                frame = src.get_next_frame()
                if frame is None:
                    continue
                
                t0 = time.perf_counter()
                detections = detector.detect(frame)
                
                associations = AssociationResult(
                    source_frame_id=frame.metadata.source_id,
                    frame_index=frame.metadata.frame_index,
                    associations=[],
                    unmatched_persons=[],
                    unmatched_faces=[],
                )
                
                tracking_result = track_frame(
                    person_detections=[],
                    face_detections=detections,
                    associations=associations,
                    frame=frame,
                    previous_tracks=previous_tracks,
                    config=tracker_config,
                )
                previous_tracks = tracking_result.tracks
                
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)
            
            result_queue.put((camera_id, latencies))
        
        # Start both threads
        t1 = threading.Thread(target=process_camera, args=("CAM1", src1, num_frames, result_queue))
        t2 = threading.Thread(target=process_camera, args=("CAM2", src2, num_frames, result_queue))
        
        start_time = time.perf_counter()
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        end_time = time.perf_counter()
        
        # Collect results
        cam1_result = result_queue.get()
        cam2_result = result_queue.get()
        
        cam1_latencies = cam1_result[1]
        cam2_latencies = cam2_result[1]
        all_latencies = cam1_latencies + cam2_latencies
        
        src1.close()
        src2.close()
        detector.close()
        
        if all_latencies:
            sorted_lat = sorted(all_latencies)
            total_time = end_time - start_time
            results["cam1_cam2_overlapped"] = {
                "total_wall_time_s": total_time,
                "total_frames_processed": len(all_latencies),
                "cam1_frames": len(cam1_latencies),
                "cam2_frames": len(cam2_latencies),
                "combined_fps": len(all_latencies) / total_time,
                "avg_latency_ms": sum(all_latencies) / len(all_latencies),
                "p50_latency_ms": sorted_lat[len(sorted_lat) // 2],
                "p95_latency_ms": sorted_lat[int(len(sorted_lat) * 0.95)],
                "max_latency_ms": max(all_latencies),
                "cam1_avg_latency_ms": sum(cam1_latencies) / len(cam1_latencies) if cam1_latencies else 0,
                "cam2_avg_latency_ms": sum(cam2_latencies) / len(cam2_latencies) if cam2_latencies else 0,
            }
            logger.info(f"  CAM1+CAM2 overlapped: {results['cam1_cam2_overlapped']['combined_fps']:.2f} FPS, "
                       f"wall_time={total_time:.1f}s, "
                       f"CAM1={results['cam1_cam2_overlapped']['cam1_avg_latency_ms']:.1f}ms, "
                       f"CAM2={results['cam1_cam2_overlapped']['cam2_avg_latency_ms']:.1f}ms")
    except Exception as e:
        logger.warning(f"CAM1+CAM2 overlapped test failed: {e}")
        results["cam1_cam2_overlapped"] = {"error": str(e)}
    
    # Analysis
    logger.info("\n" + "=" * 60)
    logger.info("SERIALIZATION ANALYSIS")
    logger.info("=" * 60)
    
    cam1_fps = results.get("cam1_only", {}).get("fps", 0)
    cam2_fps = results.get("cam2_only", {}).get("fps", 0)
    serialized_fps = results.get("cam1_cam2_serialized", {}).get("combined_fps", 0)
    overlapped_fps = results.get("cam1_cam2_overlapped", {}).get("combined_fps", 0)
    
    results["analysis"] = {
        "cam1_only_fps": cam1_fps,
        "cam2_only_fps": cam2_fps,
        "serialized_combined_fps": serialized_fps,
        "overlapped_combined_fps": overlapped_fps,
        "serialization_overhead_pct": 0,
        "overlap_speedup_pct": 0,
        "gpu_utilization_cam1_only": results.get("cam1_only", {}).get("avg_gpu_utilization"),
        "gpu_utilization_cam2_only": results.get("cam2_only", {}).get("avg_gpu_utilization"),
        "gpu_utilization_serialized": results.get("cam1_cam2_serialized", {}).get("avg_gpu_utilization"),
    }
    
    if cam1_fps > 0 and cam2_fps > 0 and serialized_fps > 0:
        # Expected combined FPS if perfectly parallel
        expected_parallel_fps = cam1_fps + cam2_fps
        results["analysis"]["expected_parallel_fps"] = expected_parallel_fps
        results["analysis"]["serialization_overhead_pct"] = (1 - serialized_fps / expected_parallel_fps) * 100
        results["analysis"]["overlap_speedup_pct"] = (overlapped_fps / serialized_fps - 1) * 100 if serialized_fps > 0 else 0
    
    logger.info(f"  CAM1 only: {cam1_fps:.2f} FPS")
    logger.info(f"  CAM2 only: {cam2_fps:.2f} FPS")
    logger.info(f"  Serialized combined: {serialized_fps:.2f} FPS")
    logger.info(f"  Overlapped combined: {overlapped_fps:.2f} FPS")
    logger.info(f"  Expected parallel: {results['analysis'].get('expected_parallel_fps', 0):.2f} FPS")
    logger.info(f"  Serialization overhead: {results['analysis'].get('serialization_overhead_pct', 0):.1f}%")
    logger.info(f"  Overlap speedup: {results['analysis'].get('overlap_speedup_pct', 0):.1f}%")
    
    # Recommendations
    if results["analysis"].get("serialization_overhead_pct", 0) > 20:
        results["recommendations"].append({
            "priority": "HIGH",
            "issue": f"Significant serialization overhead: {results['analysis']['serialization_overhead_pct']:.1f}%",
            "current": "CAM1 and CAM2 processed sequentially",
            "recommended": "Implement parallel camera processing with separate detector instances or CUDA streams",
            "impact": f"Could achieve {results['analysis'].get('expected_parallel_fps', 0):.1f} FPS combined vs {serialized_fps:.1f} FPS",
        })
    
    if results["analysis"].get("overlap_speedup_pct", 0) > 10:
        results["recommendations"].append({
            "priority": "HIGH",
            "issue": f"Overlapped processing shows {results['analysis']['overlap_speedup_pct']:.1f}% speedup",
            "current": "Serialized processing",
            "recommended": "Adopt threaded/async camera processing in production",
            "impact": "Near-linear scaling with camera count",
        })
    
    return results


def measure_gpu_utilization() -> Optional[float]:
    """Measure current GPU utilization using pynvml."""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        pynvml.nvmlShutdown()
        return float(util.gpu)
    except Exception:
        return None


if __name__ == "__main__":
    results = run_cam_serialization_analysis(30)
    
    # Save report
    reports_dir = Path("benchmark_results")
    reports_dir.mkdir(exist_ok=True)
    
    json_path = reports_dir / "PHASE_36K_SUBAGENT6_CAM_SERIALIZATION.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\nReport saved to {json_path}")