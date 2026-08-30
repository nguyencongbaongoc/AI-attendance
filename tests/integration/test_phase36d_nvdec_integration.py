"""
Phase 36D — NVDEC Integration Tests.

These tests verify the NVDEC integration in a live dual-camera environment:
1. Real CAM1 + CAM2 with NVDEC
2. Performance A/B comparison (software vs NVDEC)
3. Timestamp validation
4. GPU memory safety
5. Longer live validation
"""

import pytest
import time
import psutil
import os
import logging
from typing import Dict, List, Any

from app.streaming.rtsp_source import create_rtsp_source
from app.data.frame import CanonicalFrame, PixelFormat
from app.runtime.gpu import get_gpu_count, is_cuda_available, get_gpu_memory_info


class TestPhase36DLiveDualCamera:
    """Live dual-camera NVDEC integration tests."""
    
    @pytest.fixture(scope="class")
    def nvdec_sources(self):
        """Create NVDEC sources for both cameras."""
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2", decoder="nvdec")
        
        info1 = src1.open()
        info2 = src2.open()
        
        yield {"src1": src1, "src2": src2, "info1": info1, "info2": info2}
        
        src1.close()
        src2.close()
    
    def test_both_cameras_open_4k30(self, nvdec_sources):
        """Both cameras must open at 3840x2160 @ 30 FPS with NVDEC."""
        assert nvdec_sources["info1"].width == 3840
        assert nvdec_sources["info1"].height == 2160
        assert abs(nvdec_sources["info1"].fps - 30.0) < 1.0
        
        assert nvdec_sources["info2"].width == 3840
        assert nvdec_sources["info2"].height == 2160
        assert abs(nvdec_sources["info2"].fps - 30.0) < 1.0
    
    def test_dual_camera_frame_continuity_30_seconds(self, nvdec_sources):
        """Both cameras must maintain frame continuity for 30 seconds."""
        src1 = nvdec_sources["src1"]
        src2 = nvdec_sources["src2"]
        
        frame_count1 = 0
        frame_count2 = 0
        last_idx1 = -1
        last_idx2 = -1
        discontinuities1 = 0
        discontinuities2 = 0
        max_gap1 = 0
        max_gap2 = 0
        errors1 = 0
        errors2 = 0
        
        start = time.time()
        while time.time() - start < 30:
            try:
                frame1 = next(src1)
                frame_count1 += 1
                if frame1.metadata.frame_index <= last_idx1:
                    if frame1.metadata.frame_index != last_idx1:
                        discontinuities1 += 1
                        gap = last_idx1 - frame1.metadata.frame_index
                        max_gap1 = max(max_gap1, gap)
                else:
                    gap = frame1.metadata.frame_index - last_idx1 - 1
                    if gap > 0:
                        max_gap1 = max(max_gap1, gap)
                last_idx1 = frame1.metadata.frame_index
            except Exception as e:
                errors1 += 1
            
            try:
                frame2 = next(src2)
                frame_count2 += 1
                if frame2.metadata.frame_index <= last_idx2:
                    if frame2.metadata.frame_index != last_idx2:
                        discontinuities2 += 1
                        gap = last_idx2 - frame2.metadata.frame_index
                        max_gap2 = max(max_gap2, gap)
                else:
                    gap = frame2.metadata.frame_index - last_idx2 - 1
                    if gap > 0:
                        max_gap2 = max(max_gap2, gap)
                last_idx2 = frame2.metadata.frame_index
            except Exception as e:
                errors2 += 1
            
            time.sleep(0.01)
        
        assert errors1 == 0, f"CAM1 had {errors1} errors"
        assert errors2 == 0, f"CAM2 had {errors2} errors"
        # Observed: ~340 frames in 30s with dual-camera sequential reading + sleep
        # This is ~11 FPS per camera due to test overhead (sequential reads + sleep)
        assert frame_count1 > 300, f"CAM1 too few frames: {frame_count1}"
        assert frame_count2 > 300, f"CAM2 too few frames: {frame_count2}"
        assert max_gap1 <= 5, f"CAM1 max frame gap too large: {max_gap1}"
        assert max_gap2 <= 5, f"CAM2 max frame gap too large: {max_gap2}"
        assert discontinuities1 <= 2, f"CAM1 too many discontinuities: {discontinuities1}"
        assert discontinuities2 <= 2, f"CAM2 too many discontinuities: {discontinuities2}"
    
    def test_dual_camera_timestamp_monotonicity(self, nvdec_sources):
        """Both cameras must have monotonic timestamps."""
        src1 = nvdec_sources["src1"]
        src2 = nvdec_sources["src2"]
        
        regressions1 = 0
        regressions2 = 0
        last_ts1 = -1.0
        last_ts2 = -1.0
        
        start = time.time()
        while time.time() - start < 10:
            frame1 = next(src1)
            frame2 = next(src2)
            
            if frame1.metadata.timestamp < last_ts1:
                regressions1 += 1
            last_ts1 = frame1.metadata.timestamp
            
            if frame2.metadata.timestamp < last_ts2:
                regressions2 += 1
            last_ts2 = frame2.metadata.timestamp
            
            time.sleep(0.01)
        
        assert regressions1 == 0, f"CAM1 timestamp regressions: {regressions1}"
        assert regressions2 == 0, f"CAM2 timestamp regressions: {regressions2}"
    
    def test_dual_camera_no_cross_contamination(self, nvdec_sources):
        """CAM1 and CAM2 must maintain camera ID isolation."""
        src1 = nvdec_sources["src1"]
        src2 = nvdec_sources["src2"]
        
        frame1 = next(src1)
        frame2 = next(src2)
        
        cam1_id = frame1.metadata.extra.get("camera_id")
        cam2_id = frame2.metadata.extra.get("camera_id")
        
        assert cam1_id == "CAM1"
        assert cam2_id == "CAM2"
        assert cam1_id != cam2_id


class TestPhase36DPerformanceComparison:
    """Performance A/B comparison: software vs NVDEC."""
    
    def test_software_vs_nvdec_cpu_comparison(self):
        """Compare CPU utilization between software and NVDEC."""
        # This test measures relative CPU usage
        # Software decoder
        src_sw = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="software")
        src_sw.open()
        
        process = psutil.Process(os.getpid())
        cpu_samples_sw = []
        
        start = time.time()
        frame_count_sw = 0
        while time.time() - start < 10:
            frame = next(src_sw)
            frame_count_sw += 1
            cpu_samples_sw.append(process.cpu_percent())
            time.sleep(0.01)
        
        src_sw.close()
        
        # NVDEC decoder
        src_nv = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src_nv.open()
        
        cpu_samples_nv = []
        
        start = time.time()
        frame_count_nv = 0
        while time.time() - start < 10:
            frame = next(src_nv)
            frame_count_nv += 1
            cpu_samples_nv.append(process.cpu_percent())
            time.sleep(0.01)
        
        src_nv.close()
        
        avg_cpu_sw = sum(cpu_samples_sw) / len(cpu_samples_sw) if cpu_samples_sw else 0
        avg_cpu_nv = sum(cpu_samples_nv) / len(cpu_samples_nv) if cpu_samples_nv else 0
        
        print(f"Software decoder: {frame_count_sw} frames, avg CPU: {avg_cpu_sw:.1f}%")
        print(f"NVDEC decoder: {frame_count_nv} frames, avg CPU: {avg_cpu_nv:.1f}%")
        
        # NVDEC should use less CPU for decoding
        # (but may not be dramatically less due to GPU->CPU transfer)
        assert frame_count_sw > 100
        assert frame_count_nv > 100
    
    def test_nvdec_gpu_memory_bounded(self):
        """NVDEC must not cause unbounded GPU memory growth."""
        if not is_cuda_available():
            pytest.skip("CUDA not available")
        
        from app.runtime.gpu import get_gpu_memory_info
        
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src.open()
        
        mem_samples = []
        start = time.time()
        while time.time() - start < 15:
            frame = next(src)
            mem_info = get_gpu_memory_info(0)
            if mem_info:
                mem_samples.append(mem_info.used_mb)
            time.sleep(0.05)
        
        src.close()
        
        if mem_samples:
            max_mem = max(mem_samples)
            min_mem = min(mem_samples)
            growth = max_mem - min_mem
            
            print(f"GPU memory: min={min_mem}MB, max={max_mem}MB, growth={growth}MB")
            
            # Growth should be bounded (initial allocation + small variance)
            assert growth < 500, f"GPU memory growth too large: {growth}MB"
            assert max_mem < 5000, f"GPU memory too high: {max_mem}MB (GTX 1660 Ti has 6GB)"


class TestPhase36DLongerValidation:
    """Longer live validation tests."""
    
    def test_nvdec_60_second_stability(self):
        """NVDEC must run stably for 60 seconds."""
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src.open()
        
        frame_count = 0
        errors = 0
        start = time.time()
        
        while time.time() - start < 60:
            try:
                frame = next(src)
                frame_count += 1
            except Exception as e:
                errors += 1
                print(f"Error at frame {frame_count}: {e}")
            time.sleep(0.01)
        
        src.close()
        
        assert errors == 0, f"Errors during 60s run: {errors}"
        # Observed: ~1340 frames in 60s with sleep(0.01) overhead
        # This is ~22 FPS due to test overhead, source is 30 FPS
        assert frame_count > 1200, f"Too few frames in 60s: {frame_count}"
        print(f"60s stability: {frame_count} frames, {errors} errors")


class TestPhase36DDecoderSelection:
    """Verify explicit decoder selection."""
    
    def test_decoder_selection_observable_in_logs(self, caplog):
        """Decoder selection must be observable in logs."""
        import logging
        caplog.set_level(logging.INFO)
        
        src = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src.open()
        
        # Check logs for decoder info
        log_text = caplog.text
        assert "nvdec" in log_text.lower() or "NVDEC" in log_text.upper()
        
        src.close()
    
    def test_per_camera_decoder_selection(self):
        """Each camera can use different decoder."""
        src1 = create_rtsp_source("CAM1", "rtsp://127.0.0.1:8554/live/cam1", decoder="nvdec")
        src2 = create_rtsp_source("CAM2", "rtsp://127.0.0.1:8554/live/cam2", decoder="software")
        
        src1.open()
        src2.open()
        
        frame1 = next(src1)
        frame2 = next(src2)
        
        # NVDEC frame should have decoder tag
        assert frame1.metadata.extra.get("decoder") == "nvdec"
        # Software frame should not have decoder tag
        assert frame2.metadata.extra.get("decoder") is None
        
        src1.close()
        src2.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])