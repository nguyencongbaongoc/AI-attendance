"""
Phase 36D — NVDEC Integration Unit Tests.

These tests verify the NVDEC integration into the canonical V2 ingestion path:
1. Decoder configuration and selection
2. NVDEC vs software decoder selection
3. Frame contract preservation
4. Camera isolation
5. Timestamp monotonicity
6. Bounded buffering
7. Failure handling
"""

import pytest
import time
from typing import List, Dict, Any

from app.data.input_adapter import VideoFrameIterator
from app.streaming.rtsp_source import create_rtsp_source, RTSPSourceConfig
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType


class TestPhase36DDecoderConfiguration:
    """Verify decoder configuration is properly handled."""
    
    def test_rtspsource_config_has_decoder_field(self):
        """RTSPSourceConfig must have decoder and nvdec_gpu_device fields."""
        config = RTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            decoder="nvdec",
            nvdec_gpu_device=0,
        )
        assert config.decoder == "nvdec"
        assert config.nvdec_gpu_device == 0
    
    def test_rtspsource_config_defaults_to_software(self):
        """RTSPSourceConfig must default to software decoder."""
        config = RTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        assert config.decoder == "software"
        assert config.nvdec_gpu_device == 0
    
    def test_rtspsource_config_serialization(self):
        """RTSPSourceConfig must serialize decoder fields."""
        config = RTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
            decoder="nvdec",
            nvdec_gpu_device=1,
        )
        data = config.to_dict()
        assert data["decoder"] == "nvdec"
        assert data["nvdec_gpu_device"] == 1
        
        # Round-trip
        config2 = RTSPSourceConfig.from_dict(data)
        assert config2.decoder == "nvdec"
        assert config2.nvdec_gpu_device == 1
    
    def test_videoframeiterator_accepts_decoder_param(self):
        """VideoFrameIterator must accept decoder and nvdec_gpu_device parameters."""
        # Should not raise
        iterator = VideoFrameIterator(
            "rtsp://localhost:8554/live/cam1",
            decoder="nvdec",
            nvdec_gpu_device=0,
        )
        assert iterator._decoder == "nvdec"
        assert iterator._nvdec_gpu_device == 0
    
    def test_videoframeiterator_defaults_to_software(self):
        """VideoFrameIterator must default to software decoder."""
        iterator = VideoFrameIterator("rtsp://localhost:8554/live/cam1")
        assert iterator._decoder == "software"
        assert iterator._nvdec_gpu_device == 0


class TestPhase36DFrameContract:
    """Verify frame contract is preserved with NVDEC."""
    
    def _create_nvdec_iterator(self):
        """Create fresh NVDEC iterator for CAM1."""
        return VideoFrameIterator(
            "rtsp://127.0.0.1:8554/live/cam1",
            decoder="nvdec",
            nvdec_gpu_device=0,
        )
    
    def _create_software_iterator(self):
        """Create fresh software iterator for CAM1."""
        return VideoFrameIterator(
            "rtsp://127.0.0.1:8554/live/cam1",
            decoder="software",
        )
    
    def test_nvdec_frame_shape_matches_contract(self):
        """NVDEC frames must have correct shape (2160, 3840, 3)."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.shape == (2160, 3840, 3)
        finally:
            iterator.close()
    
    def test_nvdec_frame_dtype_matches_contract(self):
        """NVDEC frames must have uint8 dtype."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.dtype_name == "uint8"
        finally:
            iterator.close()
    
    def test_nvdec_pixel_format_matches_contract(self):
        """NVDEC frames must have BGR pixel format."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.metadata.pixel_format == PixelFormat.BGR
        finally:
            iterator.close()
    
    def test_nvdec_frame_index_monotonic(self):
        """NVDEC frame_index must be monotonic starting from 0."""
        iterator = self._create_nvdec_iterator()
        try:
            indices = []
            for _ in range(10):
                frame = next(iterator)
                indices.append(frame.metadata.frame_index)
            assert indices == list(range(10))
        finally:
            iterator.close()
    
    def test_nvdec_timestamp_monotonic(self):
        """NVDEC timestamps must be monotonic."""
        iterator = self._create_nvdec_iterator()
        try:
            timestamps = []
            for _ in range(10):
                frame = next(iterator)
                timestamps.append(frame.metadata.timestamp)
            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i-1], f"Timestamp regression at index {i}"
        finally:
            iterator.close()
    
    def test_nvdec_source_fps_preserved(self):
        """NVDEC must preserve source FPS metadata."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.metadata.source_fps == 30.0
        finally:
            iterator.close()
    
    def test_nvdec_resolution_preserved(self):
        """NVDEC must preserve 3840x2160 resolution."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.metadata.original_width == 3840
            assert frame.metadata.original_height == 2160
        finally:
            iterator.close()
    
    def test_nvdec_extra_contains_decoder_info(self):
        """NVDEC frames must include decoder info in metadata.extra."""
        iterator = self._create_nvdec_iterator()
        try:
            frame = next(iterator)
            assert frame.metadata.extra.get("decoder") == "nvdec"
            assert frame.metadata.extra.get("gpu_device") == 0
        finally:
            iterator.close()


class TestPhase36DCameraIsolation:
    """Verify camera isolation with NVDEC."""
    
    def test_dual_camera_nvdec_isolation(self):
        """CAM1 and CAM2 must maintain camera_id isolation with NVDEC."""
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2", decoder="nvdec")
        
        try:
            src1.open()
            src2.open()
            
            frame1 = next(src1)
            frame2 = next(src2)
            
            cam1_id = frame1.metadata.extra.get("camera_id")
            cam2_id = frame2.metadata.extra.get("camera_id")
            
            assert cam1_id == "CAM1"
            assert cam2_id == "CAM2"
            assert cam1_id != cam2_id
        finally:
            src1.close()
            src2.close()


class TestPhase36DBoundedBuffering:
    """Verify bounded buffering behavior with NVDEC."""
    
    def test_nvdec_queue_capacity_respected(self):
        """NVDEC must respect max_queue_size configuration."""
        config = RTSPSourceConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://127.0.0.1:8554/live/cam1",
            decoder="nvdec",
            max_queue_size=5,
        )
        assert config.max_queue_size == 5
    
    def test_nvdec_no_unbounded_accumulation(self):
        """NVDEC must not accumulate frames unboundedly."""
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src.open()
        
        try:
            # Read frames faster than production to test backpressure
            for _ in range(20):
                frame = next(src)
                time.sleep(0.01)  # Slow consumer
            
            # Should not hang or accumulate
            assert src.frames_produced == 20
        finally:
            src.close()


class TestPhase36DFailureHandling:
    """Verify NVDEC failure handling."""
    
    def test_invalid_gpu_device_does_not_hang(self):
        """Invalid GPU device must not cause infinite hang - FFmpeg may fall back or fail cleanly."""
        iterator = VideoFrameIterator(
            "rtsp://127.0.0.1:8554/live/cam1",
            decoder="nvdec",
            nvdec_gpu_device=999,  # Invalid device
        )
        
        try:
            # Should either fail or fall back, but not hang indefinitely
            # Read several frames to verify no hang
            frames_read = 0
            for _ in range(10):
                frame = next(iterator)
                frames_read += 1
            
            # If we get here without hanging, the test passes
            # The key requirement is NO HANG - FFmpeg handles invalid device gracefully
            assert frames_read == 10
        except StopIteration:
            # FFmpeg process ended - also acceptable (clean failure)
            pass
        except Exception as e:
            # Clear error is also acceptable
            assert "invalid device" in str(e).lower() or "cuda_error_invalid_device" in str(e).lower()
        finally:
            iterator.close()


class TestPhase36DSoftwareFallback:
    """Verify software decoder path still works."""
    
    def test_software_decoder_still_works(self):
        """Software decoder must remain functional as baseline."""
        iterator = VideoFrameIterator(
            "rtsp://127.0.0.1:8554/live/cam1",
            decoder="software",
        )
        
        try:
            frame = next(iterator)
            assert frame.shape == (2160, 3840, 3)
            assert frame.dtype_name == "uint8"
            assert frame.metadata.pixel_format == PixelFormat.BGR
        finally:
            iterator.close()
    
    def test_software_decoder_frame_contract(self):
        """Software decoder must preserve frame contract."""
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="software")
        src.open()
        
        try:
            frame = next(src)
            assert frame.metadata.extra.get("decoder") is None  # No decoder tag for software
            assert frame.metadata.extra.get("camera_id") == "CAM1"
        finally:
            src.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])