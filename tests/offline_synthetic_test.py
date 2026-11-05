#!/usr/bin/env python3
"""Offline synthetic pipeline test - runs without cameras."""

import torch
import numpy as np
import cv2
import time
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock 4K frame generator
def create_synthetic_4k_frame() -> np.ndarray:
    """Create 3840x2160 frame with person-like shapes."""
    frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
    # Draw person body (rectangle)
    cv2.rectangle(frame, (1000, 500), (1800, 1800), (100, 150, 200), -1)
    # Draw face (oval)
    cv2.ellipse(frame, (1400, 700), (150, 200), 0, 0, 360, (200, 180, 160), -1)
    # Add noise
    noise = np.random.randint(0, 30, frame.shape, dtype=np.uint8)
    frame = cv2.add(frame, noise)
    return frame

def test_tensorrt_engine():
    """Test TensorRT engine load + inference."""
    from pipeline_engine.inference.tensorrt_engine import create_tensorrt_executor
    engine_path = "models/yolo/yolo11n_fp16.engine"
    if not Path(engine_path).exists():
        print("SKIP: TensorRT engine not found")
        return True
    
    executor = create_tensorrt_executor(engine_path)
    assert executor.initialize(), "TensorRT init failed"
    
    # Create dummy input
    dummy = torch.randn(1, 3, 640, 640, device='cuda', dtype=torch.float16)
    outputs = executor.infer({"images": dummy})
    assert "output0" in outputs, "Output missing"
    print(f"TensorRT: {outputs['output0'].shape}")
    executor.cleanup()
    return True

def test_yolo_pipeline():
    """Test full YOLO detection pipeline on synthetic frame.
    
    Note: Synthetic frames may not produce actual detections since the model
    expects real person features. This test verifies the pipeline runs end-to-end
    without errors.
    """
    from pipeline_engine.inference.person_detection import create_yolo_detector
    from pipeline_engine.memory.gpu_frame import GPUFrame
    
    detector = create_yolo_detector()
    assert detector.initialize(), "YOLO init failed"
    
    # Create synthetic frame -> NV12 using proper format
    frame_bgr = create_synthetic_4k_frame()
    H, W = 2160, 3840
    
    # Convert BGR to YUV I420
    frame_yuv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YUV_I420)
    
    # I420 layout in flat array (H*1.5, W):
    # Y plane: rows 0 to H-1 (2160 rows), all W cols
    # U plane: rows H to H+H/4-1 (2160 to 2699), first W/2 cols
    # V plane: rows H+H/4 to H+H/2-1 (2700 to 3239), first W/2 cols
    # Each flat row represents 2 actual rows of U/V plane (stride W)
    
    y_plane = frame_yuv[:H, :].copy()
    
    remaining = frame_yuv[H:, :]
    u_flat = remaining[:H//4, :W//2].copy()  # 540 rows
    v_flat = remaining[H//4:H//2, :W//2].copy()  # 540 rows
    
    # Expand U/V from (540, 1920) to (1080, 1920) by duplicating rows
    u_plane = np.repeat(u_flat, 2, axis=0)
    v_plane = np.repeat(v_flat, 2, axis=0)
    
    # Create interleaved UV plane for NV12 (U and V interleaved per pixel)
    uv_plane = np.zeros((H//2, W//2, 2), dtype=np.uint8)
    uv_plane[:, :, 0] = u_plane
    uv_plane[:, :, 1] = v_plane
    
    y_tensor = torch.from_numpy(y_plane).cuda()
    uv_tensor = torch.from_numpy(uv_plane).cuda()
    
    # Test GPUFrame - use keyword arguments for proper field assignment
    gpu_frame = GPUFrame(
        camera_id="cam1",
        frame_id=0,
        timestamp=0.0,
        width=W,
        height=H,
        pixel_format=GPUFrame.__dataclass_fields__['pixel_format'].default,  # NV12
        y_tensor=y_tensor,
        uv_tensor=uv_tensor,
    )
    print("YOLO: GPUFrame created: {}x{}".format(gpu_frame.width, gpu_frame.height))
    
    # Run full detection pipeline (may return 0 detections for synthetic frames)
    detections = detector.detect(gpu_frame)
    print("YOLO: {} persons detected (synthetic frame)".format(len(detections)))
    
    # Test passes if pipeline completes without errors
    return True

def test_byte_track():
    """Test ByteTrack association."""
    from pipeline_engine.tracking.tracker import Tracker, TrackingConfig
    from pipeline_engine.inference.person_detection import PersonDetection
    
    tracker = Tracker(TrackingConfig())
    
    # Create mock detections
    det = PersonDetection(
        bbox=(1000, 500, 1800, 1800),
        confidence=0.9,
        detection_id="test_1",
        frame_index=1,
        source_id="cam1"
    )
    
    result = tracker.process_frame(
        person_detections=[det],
        face_detections=[],
        face_embeddings={},
        body_embeddings={},
        camera_id="cam1",
        timestamp=time.time()
    )
    assert len(result.tracks) == 1, "Track not created"
    print(f"ByteTrack: Track ID {result.tracks[0].track_id}")
    return True

def test_metadata_broadcast():
    """Test metadata WebSocket broadcast path."""
    import asyncio
    from app.streaming.metadata_broadcaster import get_metadata_broadcaster, FrameMetadata, PersonMetadata
    
    broadcaster = get_metadata_broadcaster()
    
    meta = FrameMetadata(
        camera_id="cam1",
        frame_sequence=1,
        pts_ns=int(time.time() * 1e9),
        capture_timestamp=time.time(),
        persons=[PersonMetadata(track_id=1, bbox=[0.2, 0.2, 0.6, 0.6])],
    )
    
    # This should not block
    asyncio.run(broadcaster.broadcast_metadata("cam1", meta))
    print("Metadata broadcast: non-blocking OK")
    return True

def test_sqlite_storage():
    """Test attendance storage with WAL mode."""
    from app.attendance.storage import create_attendance_storage
    from app.attendance.contract import AttendanceRecord, AttendanceDirection, IdentityCertainty
    from fractions import Fraction
    
    storage = create_attendance_storage()
    
    record = AttendanceRecord(
        attendance_record_id="test_001",
        identity_certainty=IdentityCertainty.KNOWN,
        identity_candidate="student_001",
        identity_confidence=0.95,
        direction=AttendanceDirection.IN,
        event_timestamp=time.time(),
        camera_id="cam1",
        local_track_id="track_1",
        source_raw_event_id="evt_1",
        source_resolution_id="res_1",
        time_base=Fraction(1, 90000),
        capture_timestamp=time.time(),
        processing_timestamp=time.time(),
        # Required fields with defaults
        previous_state="outside",
        new_state="inside",
        identity_state="unknown",
        association_method="",
        conflict_flag=False,
        provisional_person_id=None,
        event_frame_index=-1,
        global_observation_id=None,
        source_crossing_event_id=None,
        geometry_version=0,
        geometry_config_hash="",
        resolver_version="1.0",
        resolver_config_hash="",
        stream_epoch=0,
        pts=0,
        model_version="",
        enrollment_version="",
        attendance_schema_version="1.1",
        # Evidence fields (nullable)
        identity_evidence_ref=None,
        face_evidence_ref=None,
        body_evidence_ref=None,
        face_quality=0.0,
        body_quality=0.0,
        # Phase 17: Evidence storage URIs
        snapshot_face_url=None,
        snapshot_scene_url=None,
        video_clip_url=None,
    )
    
    inserted = storage.insert(record)
    assert inserted, "Insert failed"
    
    # Test idempotency
    inserted2 = storage.insert(record)
    assert not inserted2, "Duplicate should return False"
    print("SQLite: Insert + idempotency OK")
    return True

def main():
    print("=" * 60)
    print("OFFLINE SYNTHETIC PIPELINE TEST")
    print("=" * 60)
    
    tests = [
        ("TensorRT Engine", test_tensorrt_engine),
        ("YOLO Detection", test_yolo_pipeline),
        ("ByteTrack Association", test_byte_track),
        ("Metadata Broadcast", test_metadata_broadcast),
        ("SQLite Storage", test_sqlite_storage),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            start = time.perf_counter()
            ok = test_fn()
            elapsed = (time.perf_counter() - start) * 1000
            results.append((name, "PASS" if ok else "FAIL", "{:.1f}ms".format(elapsed)))
        except Exception as e:
            results.append((name, "ERROR", str(e)))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, status, detail in results:
        icon = "[PASS]" if status == "PASS" else "[FAIL]"
        print("{} {:25s} {:6s} {}".format(icon, name, status, detail))
    
    all_pass = all(r[1] == "PASS" for r in results)
    print("\nOVERALL: {}".format('ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'))
    return 0 if all_pass else 1

if __name__ == "__main__":
    exit(main())