"""
Integration tests for V2 GPU-first pipeline.
Runs component-level verification without requiring full runtime.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_gpu_frame_contract():
    """Test GPUFrame contract creation and validation."""
    import torch
    from video_pipeline_v2.core.gpu_frame import GPUFrame, CUDAContext, PixelFormat, FrameOwnership
    
    # Create fake CUDA tensors (skip if no CUDA)
    if torch.cuda.is_available():
        y = torch.empty((480, 640), dtype=torch.uint8, device='cuda')
        uv = torch.empty((240, 320, 2), dtype=torch.uint8, device='cuda')
        
        frame = GPUFrame.from_pyav_nvdec(
            y_tensor=y,
            uv_tensor=uv,
            camera_id="test",
            frame_id=1,
            timestamp=1.0,
            pts=1,
            width=640,
            height=480,
        )
        
        assert frame.validate()
        assert frame.width == 640
        assert frame.height == 480
        assert frame.pixel_format == PixelFormat.NV12
        assert frame.memory_owner == FrameOwnership.DECODER
        
        ptrs = frame.get_gpu_pointers()
        assert ptrs[0] != 0  # y_ptr
        assert ptrs[1] != 0  # uv_ptr
        
        print("PASS: GPUFrame contract validated")
    else:
        print("SKIP: GPUFrame contract (no CUDA available)")


def test_packet_input():
    """Test packet input structure."""
    from video_pipeline_v2.input.packet_input import CompressedPacket, PacketType, create_packet_source
    
    # Create test packet
    packet = CompressedPacket(
        data=b"\x01\x02\x03",
        pts=100,
        packet_type=PacketType.H264_NAL,
        is_keyframe=True,
        camera_id="cam1",
    )
    
    assert len(packet) == 3
    assert packet.is_keyframe
    assert packet.camera_id == "cam1"
    
    print("PASS: Packet input validated")


def test_model_contracts():
    """Test model contracts."""
    from video_pipeline_v2.ai.model_contracts import (
        SCRFD_INPUT, ARCFACE_INPUT, YOLO_INPUT, REID_INPUT,
        ModelContractRegistry
    )
    
    # Test contract definitions
    assert SCRFD_INPUT.shape == (1, 3, 640, 640)
    assert ARCFACE_INPUT.shape == (1, 3, 112, 112)
    assert YOLO_INPUT.shape == (1, 3, 640, 640)
    assert REID_INPUT.shape == (1, 3, 256, 128)
    
    # Test registry
    contracts = ModelContractRegistry.get("scrfd")
    assert "input" in contracts
    
    print("PASS: Model contracts validated")


def test_gpus_inference_base():
    """Test GPU inference base class structure."""
    from video_pipeline_v2.ai.gpu_inference import GPUInferenceEngine, InferenceConfig, InferenceBackend
    
    # Test config
    config = InferenceConfig(
        model_path="dummy_path",
        model_name="test_model",
        backend=InferenceBackend.ONNX_RUNTIME,
    )
    assert config.backend == InferenceBackend.ONNX_RUNTIME
    
    print("PASS: GPU inference base validated")


def test_line_crossing():
    """Test line crossing engine."""
    from video_pipeline_v2.ai.line_crossing import (
        LineGeometry, CrossingEngine, CrossingPolicyConfig,
        CameraGeometryConfig, create_crossing_engine
    )
    
    # Create line
    line = LineGeometry(
        p1=(0, 1000),
        p2=(3840, 1000),
        direction_semantics="side_a_to_b_in"
    )
    
    # Test side detection
    assert line.side_of_point((1000, 1100)) == 1  # Side A (positive cross product for this orientation)
    
    # Create engine
    config = CameraGeometryConfig(
        camera_id="test",
        line=line,
        crossing_policy=CrossingPolicyConfig(),
    )
    engine = CrossingEngine(config)
    
    assert engine.get_stats()["total_crossings"] == 0
    
    print("PASS: Line crossing engine validated")


def test_tracking():
    """Test tracking module."""
    from video_pipeline_v2.ai.tracking import (
        Track, TrackingConfig, compute_iou, update_tracks
    )
    
    # Create test tracks
    track = Track(
        track_id=1,
        source_frame_id="cam1",
        frame_index=1,
        timestamp=1.0,
        bbox_original_frame=(100, 200, 300, 400),
        confidence=0.9,
    )
    
    assert track.width == 200
    assert track.height == 200
    assert track.area == 40000
    
    # Test IoU computation
    bbox1 = (0, 0, 100, 100)
    bbox2 = (50, 50, 150, 150)
    iou_val = compute_iou(bbox1, bbox2)
    assert 0.0 <= iou_val <= 1.0
    
    print("PASS: Tracking module validated")


def test_annotation():
    """Test GPU annotation renderer."""
    from video_pipeline_v2.annotation.gpu_annotation import (
        GPUAnnotationRenderer, AnnotationConfig
    )
    
    renderer = GPUAnnotationRenderer(AnnotationConfig(), device_id=0)
    assert renderer.config.show_confidence == True
    
    print("PASS: GPU annotation validated")


def test_publisher():
    """Test publisher module."""
    from video_pipeline_v2.output.publisher import (
        ExternalPublisher, PublisherConfig, PublisherState,
        create_external_publisher, AttendanceEventGenerator
    )
    
    # Test attendance event generator
    attendance_gen = AttendanceEventGenerator("test")
    events = attendance_gen.process_crossing_events([], timestamp=1.0)
    assert events == []
    
    # Test publisher config
    config = PublisherConfig(camera_id="test")
    assert config.mediamtx_port == 8554
    
    print("PASS: Publisher module validated")


def test_supervisor():
    """Test supervisor module."""
    from video_pipeline_v2.workers.supervisor import (
        SupervisorConfig, CameraLifecycleState, SystemState,
        GPUWorkerSupervisor, SystemReadinessTracker
    )
    
    tracker = SystemReadinessTracker()
    tracker.set_ready("mediamtx", False)
    assert tracker.get_state("mediamtx").value == "mediamtx_not_running"
    
    tracker.set_ready("mediamtx", True)
    assert tracker.get_state("mediamtx").value == "media_server_ready"
    
    # Test lifecycle states
    assert len([s for s in CameraLifecycleState]) > 0
    assert len([s for s in SystemState]) > 0
    
    print("PASS: Supervisor module validated")


def test_camera_runtime():
    """Test camera runtime isolation."""
    from video_pipeline_v2.workers.camera_supervisor import (
        CameraRuntimeConfig, CameraRuntime, V2PipelineBridge
    )
    
    # Create bridge
    bridge = V2PipelineBridge()
    assert bridge.get_all_camera_status() == {}
    
    # Check isolation principle
    readiness = bridge.get_system_readiness()
    assert readiness.get("independent_isolation", False) == True
    
    print("PASS: Camera runtime isolation validated")


if __name__ == "__main__":
    print("=== Running V2 GPU Pipeline Component Tests ===")
    
    tests = [
        test_gpu_frame_contract,
        test_packet_input,
        test_model_contracts,
        test_gpus_inference_base,
        test_line_crossing,
        test_tracking,
        test_annotation,
        test_publisher,
        test_supervisor,
        test_camera_runtime,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {test.__name__} - {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
