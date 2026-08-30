"""
Phase 36A — Live Stream / CUDA Forensic Repair & Revalidation Tests.

These tests verify the concrete repairs made during Phase 36A:
1. RTSP/RTP/H.264 stability (frame continuity, no decoder errors)
2. CUDA/ONNX Runtime provider configuration
3. GPU telemetry availability
4. Dual-camera frame processing without cross-contamination
"""

import pytest
import time
from typing import List, Dict, Any

from app.streaming.rtsp_source import create_rtsp_source
from app.vision.detection import create_face_detector
from app.vision.arcface_inference import ArcFaceInference
from app.vision.association import associate_detections
from app.vision.tracker import track_frame, TrackerConfig
from app.vision.detector_contract import FaceDetectionContract
import onnxruntime as ort
import torch


class TestPhase36ACUDAEnvironment:
    """Verify CUDA/ONNX Runtime environment is correctly configured."""
    
    def test_onnxruntime_cuda_provider_available(self):
        """CUDAExecutionProvider must be available in ONNX Runtime."""
        providers = ort.get_available_providers()
        assert "CUDAExecutionProvider" in providers, \
            f"CUDAExecutionProvider not found in {providers}"
    
    def test_torch_cuda_available(self):
        """PyTorch must detect CUDA and GTX 1660 Ti."""
        assert torch.cuda.is_available(), "torch.cuda.is_available() returned False"
        device_name = torch.cuda.get_device_name(0)
        assert "1660 Ti" in device_name or "GTX 1660" in device_name, \
            f"Expected GTX 1660 Ti, got {device_name}"
    
    def test_arcface_uses_cuda_provider(self):
        """ArcFace inference session must use CUDAExecutionProvider."""
        arcface = ArcFaceInference()
        session_providers = arcface.session.get_providers()
        assert "CUDAExecutionProvider" in session_providers, \
            f"ArcFace not using CUDA: {session_providers}"


class TestPhase36ARTSPStreamStability:
    """Verify RTSP streams are stable with TCP transport and no H.264 corruption."""
    
    @pytest.fixture(scope="class")
    def cam1_source(self):
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        info = src.open()
        yield src, info
        src.close()
    
    @pytest.fixture(scope="class")
    def cam2_source(self):
        src = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        info = src.open()
        yield src, info
        src.close()
    
    def test_cam1_stream_opens_4k30(self, cam1_source):
        """CAM1 must open at 3840x2160 @ 30 FPS."""
        src, info = cam1_source
        assert info.width == 3840, f"CAM1 width: {info.width}"
        assert info.height == 2160, f"CAM1 height: {info.height}"
        assert abs(info.fps - 30.0) < 1.0, f"CAM1 FPS: {info.fps}"
    
    def test_cam2_stream_opens_4k30(self, cam2_source):
        """CAM2 must open at 3840x2160 @ 30 FPS."""
        src, info = cam2_source
        assert info.width == 3840, f"CAM2 width: {info.width}"
        assert info.height == 2160, f"CAM2 height: {info.height}"
        assert abs(info.fps - 30.0) < 1.0, f"CAM2 FPS: {info.fps}"
    
    def test_cam1_frame_continuity_30_seconds(self, cam1_source):
        """CAM1 must maintain frame continuity for 30 seconds."""
        src, _ = cam1_source
        
        frame_count = 0
        last_frame_index = -1
        discontinuities = 0
        max_gap = 0
        errors = 0
        start = time.time()
        
        while time.time() - start < 30:
            try:
                frame = src.get_next_frame()
                if frame:
                    frame_count += 1
                    if frame.metadata.frame_index <= last_frame_index:
                        if frame.metadata.frame_index == last_frame_index:
                            pass  # duplicate
                        else:
                            discontinuities += 1
                            gap = last_frame_index - frame.metadata.frame_index
                            max_gap = max(max_gap, gap)
                    else:
                        gap = frame.metadata.frame_index - last_frame_index - 1
                        if gap > 0:
                            max_gap = max(max_gap, gap)
                    last_frame_index = frame.metadata.frame_index
            except Exception as e:
                errors += 1
                pytest.fail(f"CAM1 frame read error: {e}")
            time.sleep(0.01)
        
        # Allow small number of discontinuities due to network conditions
        # but max_gap should be small (not 89 as seen in Phase 36-R)
        assert errors == 0, f"CAM1 had {errors} errors"
        assert frame_count > 800, f"CAM1 too few frames: {frame_count} (expected ~900)"
        assert max_gap <= 5, f"CAM1 max frame gap too large: {max_gap}"
        assert discontinuities <= 2, f"CAM1 too many discontinuities: {discontinuities}"
    
    def test_cam2_frame_continuity_30_seconds(self, cam2_source):
        """CAM2 must maintain frame continuity for 30 seconds."""
        src, _ = cam2_source
        
        frame_count = 0
        last_frame_index = -1
        discontinuities = 0
        max_gap = 0
        errors = 0
        start = time.time()
        
        while time.time() - start < 30:
            try:
                frame = src.get_next_frame()
                if frame:
                    frame_count += 1
                    if frame.metadata.frame_index <= last_frame_index:
                        if frame.metadata.frame_index == last_frame_index:
                            pass  # duplicate
                        else:
                            discontinuities += 1
                            gap = last_frame_index - frame.metadata.frame_index
                            max_gap = max(max_gap, gap)
                    else:
                        gap = frame.metadata.frame_index - last_frame_index - 1
                        if gap > 0:
                            max_gap = max(max_gap, gap)
                    last_frame_index = frame.metadata.frame_index
            except Exception as e:
                errors += 1
                pytest.fail(f"CAM2 frame read error: {e}")
            time.sleep(0.01)
        
        assert errors == 0, f"CAM2 had {errors} errors"
        assert frame_count > 800, f"CAM2 too few frames: {frame_count} (expected ~900)"
        assert max_gap <= 5, f"CAM2 max frame gap too large: {max_gap}"
        assert discontinuities <= 2, f"CAM2 too many discontinuities: {discontinuities}"
    
    def test_cam1_timestamp_monotonicity(self, cam1_source):
        """CAM1 timestamps must be monotonically increasing."""
        src, _ = cam1_source
        
        last_timestamp = -1.0
        regressions = 0
        start = time.time()
        
        while time.time() - start < 10:
            frame = src.get_next_frame()
            if frame:
                if frame.metadata.timestamp < last_timestamp:
                    regressions += 1
                last_timestamp = frame.metadata.timestamp
            time.sleep(0.01)
        
        assert regressions == 0, f"CAM1 timestamp regressions: {regressions}"
    
    def test_cam2_timestamp_monotonicity(self, cam2_source):
        """CAM2 timestamps must be monotonically increasing."""
        src, _ = cam2_source
        
        last_timestamp = -1.0
        regressions = 0
        start = time.time()
        
        while time.time() - start < 10:
            frame = src.get_next_frame()
            if frame:
                if frame.metadata.timestamp < last_timestamp:
                    regressions += 1
                last_timestamp = frame.metadata.timestamp
            time.sleep(0.01)
        
        assert regressions == 0, f"CAM2 timestamp regressions: {regressions}"


class TestPhase36AAIPipelineIntegration:
    """Verify AI pipeline works end-to-end with CUDA acceleration."""
    
    @pytest.fixture(scope="class")
    def pipeline_components(self):
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        info1 = src1.open()
        info2 = src2.open()
        
        face_detector = create_face_detector()
        arcface = ArcFaceInference()
        tracker_config = TrackerConfig()
        
        yield {
            "src1": src1, "src2": src2,
            "info1": info1, "info2": info2,
            "face_detector": face_detector,
            "arcface": arcface,
            "tracker_config": tracker_config,
        }
        
        src1.close()
        src2.close()
    
    def test_face_detection_returns_valid_contracts(self, pipeline_components):
        """Face detector must return valid FaceDetectionContract-compatible objects."""
        src1 = pipeline_components["src1"]
        face_detector = pipeline_components["face_detector"]
        
        frame = src1.get_next_frame()
        assert frame is not None
        
        detections = face_detector.detect(frame)
        
        # Each detection must have required attributes for FaceDetectionContract
        for det in detections:
            assert hasattr(det, 'bbox'), "Missing bbox"
            assert hasattr(det, 'confidence'), "Missing confidence"
            assert hasattr(det, 'landmarks5'), "Missing landmarks5"
            assert hasattr(det, 'detector_model_id'), "Missing detector_model_id"
            assert hasattr(det, 'detector_model_sha256'), "Missing detector_model_sha256"
            assert hasattr(det, 'provenance'), "Missing provenance"
            assert det.detector_model_id == "scrfd"
            assert det.detector_model_sha256 != ""
    
    def test_association_works_with_face_detections(self, pipeline_components):
        """associate_detections must work with FaceDetection objects."""
        src1 = pipeline_components["src1"]
        face_detector = pipeline_components["face_detector"]
        
        frame = src1.get_next_frame()
        assert frame is not None
        
        faces = face_detector.detect(frame)
        
        # Should not raise AttributeError about detector_model_id
        result = associate_detections([], faces, frame)
        
        assert result is not None
        assert hasattr(result, 'associations')
        assert hasattr(result, 'unmatched_persons')
        assert hasattr(result, 'unmatched_faces')
    
    def test_tracking_works_with_associations(self, pipeline_components):
        """track_frame must work with association results."""
        src1 = pipeline_components["src1"]
        face_detector = pipeline_components["face_detector"]
        tracker_config = pipeline_components["tracker_config"]
        
        frame = src1.get_next_frame()
        assert frame is not None
        
        faces = face_detector.detect(frame)
        associations = associate_detections([], faces, frame)
        
        prev_tracks = []
        result = track_frame([], faces, associations, frame, prev_tracks, tracker_config)
        
        assert result is not None
        assert hasattr(result, 'tracks')
    
    def test_dual_camera_no_cross_contamination(self, pipeline_components):
        """CAM1 and CAM2 must maintain camera ID isolation."""
        src1 = pipeline_components["src1"]
        src2 = pipeline_components["src2"]
        
        frame1 = src1.get_next_frame()
        frame2 = src2.get_next_frame()
        
        assert frame1 is not None
        assert frame2 is not None
        
        # Check camera_id in metadata extra
        cam1_id = frame1.metadata.extra.get("camera_id", "UNKNOWN")
        cam2_id = frame2.metadata.extra.get("camera_id", "UNKNOWN")
        
        assert cam1_id == "CAM1", f"CAM1 frame has camera_id={cam1_id}"
        assert cam2_id == "CAM2", f"CAM2 frame has camera_id={cam2_id}"
        assert cam1_id != cam2_id, "Cross-camera contamination detected"


class TestPhase36AGPUTelemetry:
    """Verify GPU telemetry is available and working."""
    
    def test_pynvml_available(self):
        """pynvml must be importable and functional."""
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        assert "1660 Ti" in name or "GTX 1660" in name
    
    def test_gpu_utilization_readable(self):
        """GPU utilization must be readable and non-negative."""
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        assert util.gpu >= 0
        assert util.gpu <= 100
    
    def test_gpu_memory_readable(self):
        """GPU memory must be readable."""
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        assert mem.total > 0
        assert mem.used >= 0
        assert mem.used <= mem.total
        # GTX 1660 Ti has 6GB
        assert mem.total >= 5 * 1024 * 1024 * 1024  # At least 5GB


class TestPhase36APerformanceBaseline:
    """Establish performance baselines for Phase 36A."""
    
    @pytest.fixture(scope="class")
    def pipeline_components(self):
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2")
        info1 = src1.open()
        info2 = src2.open()
        
        face_detector = create_face_detector()
        tracker_config = TrackerConfig()
        
        yield {
            "src1": src1, "src2": src2,
            "face_detector": face_detector,
            "tracker_config": tracker_config,
        }
        
        src1.close()
        src2.close()
    
    def test_detection_latency_under_200ms(self, pipeline_components):
        """Face detection latency should be under 200ms on GTX 1660 Ti."""
        src1 = pipeline_components["src1"]
        face_detector = pipeline_components["face_detector"]
        
        latencies = []
        for _ in range(20):
            frame = src1.get_next_frame()
            if frame:
                start = time.time()
                face_detector.detect(frame)
                latencies.append((time.time() - start) * 1000)
            time.sleep(0.05)
        
        assert len(latencies) > 10, "Not enough frames for latency measurement"
        mean_latency = sum(latencies) / len(latencies)
        assert mean_latency < 200, f"Mean detection latency {mean_latency:.1f}ms exceeds 200ms"
    
    def test_processing_fps_above_1(self, pipeline_components):
        """Processing FPS should be above 1.0 FPS (limited by 30 FPS source)."""
        src1 = pipeline_components["src1"]
        face_detector = pipeline_components["face_detector"]
        tracker_config = pipeline_components["tracker_config"]
        
        frame_count = 0
        start = time.time()
        prev_tracks = []
        
        while time.time() - start < 10:
            frame = src1.get_next_frame()
            if frame:
                frame_count += 1
                faces = face_detector.detect(frame)
                associations = associate_detections([], faces, frame)
                result = track_frame([], faces, associations, frame, prev_tracks, tracker_config)
                prev_tracks = result.tracks
            time.sleep(0.01)
        
        elapsed = time.time() - start
        fps = frame_count / elapsed
        assert fps > 1.0, f"Processing FPS {fps:.2f} below 1.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])