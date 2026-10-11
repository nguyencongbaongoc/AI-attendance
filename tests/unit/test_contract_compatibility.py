"""
Phase 9.3 — Unit Tests for GPUFrameContract Compatibility.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

import torch
import numpy as np
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract, nv12_cuda_to_bgr_cuda


class TestGPUFrameContract:
    """Tests for GPUFrameContract structure and interface."""
    
    def test_contract_required_fields(self):
        """Contract should have all required fields."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        # Required fields
        assert contract.frame_id == 1
        assert contract.camera_id == "CAM1"
        assert contract.timestamp == 1000.0
        assert contract.pts == 100
        assert contract.width == 3840
        assert contract.height == 2160
        assert contract.pixel_format == "NV12"
        assert contract.cuda_stream == 0
    
    def test_contract_methods(self):
        """Contract should have all required methods."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        # get_gpu_pointers
        y_ptr, uv_ptr = contract.get_gpu_pointers()
        assert isinstance(y_ptr, int)
        assert isinstance(uv_ptr, int)
        assert y_ptr != 0
        assert uv_ptr != 0
        
        # get_tensors
        y_t, uv_t = contract.get_tensors()
        assert y_t is y_tensor
        assert uv_t is uv_tensor
        
        # nbytes
        nbytes = contract.nbytes
        assert nbytes == 3840 * 2160 * 1.5  # NV12 size
        
        # is_device_memory
        assert contract.is_device_memory() is True
        
        # release
        contract.release()
        assert contract.released is True
        assert contract._y_tensor is None
        assert contract._uv_tensor is None
    
    def test_contract_validation(self):
        """Contract should validate tensor properties."""
        # CPU tensor should fail
        y_cpu = torch.zeros(2160, 3840, dtype=torch.uint8)
        uv_cpu = torch.zeros(1080, 1920, 2, dtype=torch.uint8)
        
        with pytest.raises(AssertionError, match="must be on CUDA"):
            GPUFrameContract.from_pyav_frame_data(
                frame_data={
                    "y_plane": y_cpu,
                    "uv_plane": uv_cpu,
                    "width": 3840,
                    "height": 2160,
                    "format": "nv12_cuda",
                    "pts": 100,
                },
                frame_id=1,
                camera_id="CAM1",
                timestamp=1000.0,
                pts=100,
                cuda_stream=0,
            )
        
        # Wrong dtype should fail
        y_wrong = torch.zeros(2160, 3840, dtype=torch.float32, device='cuda')
        uv_wrong = torch.zeros(1080, 1920, 2, dtype=torch.float32, device='cuda')
        
        with pytest.raises(AssertionError, match="must be uint8"):
            GPUFrameContract.from_pyav_frame_data(
                frame_data={
                    "y_plane": y_wrong,
                    "uv_plane": uv_wrong,
                    "width": 3840,
                    "height": 2160,
                    "format": "nv12_cuda",
                    "pts": 100,
                },
                frame_id=1,
                camera_id="CAM1",
                timestamp=1000.0,
                pts=100,
                cuda_stream=0,
            )
    
    def test_zero_copy_pointers(self):
        """Contract should provide zero-copy GPU pointers."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        # Store original pointers
        y_ptr_orig = y_tensor.data_ptr()
        uv_ptr_orig = uv_tensor.data_ptr()
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        # Pointers should match original tensors
        y_ptr, uv_ptr = contract.get_gpu_pointers()
        assert y_ptr == y_ptr_orig
        assert uv_ptr == uv_ptr_orig
        
        # Tensors should be same objects
        y_t, uv_t = contract.get_tensors()
        assert y_t.data_ptr() == y_ptr_orig
        assert uv_t.data_ptr() == uv_ptr_orig


class TestBackendContractCompatibility:
    """Tests that both backends produce compatible contracts."""
    
    def test_backend_b_contract_structure(self):
        """Backend B (PyNvVideoCodec) contract structure."""
        # This simulates what PyNvVideoCodecFrameAdapter.adapt() produces
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        # Verify memory_owner is set
        assert contract.memory_owner == "pyav_nvdec"  # From from_pyav_frame_data
        
        # The adapter would set this to "pynvvideocodec"
        contract.memory_owner = "pynvvideocodec"
        assert contract.memory_owner == "pynvvideocodec"
    
    def test_backend_a_contract_structure(self):
        """Backend A (PyAV) contract structure."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        assert contract.memory_owner == "pyav_nvdec"
    
    def test_identical_interface(self):
        """Both backends should produce contract with identical interface."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract_a = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        contract_b = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor.clone(),
                "uv_plane": uv_tensor.clone(),
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 101,
            },
            frame_id=2,
            camera_id="CAM1",
            timestamp=1000.033,
            pts=101,
            cuda_stream=0,
        )
        
        # Both should have same methods and properties
        assert hasattr(contract_a, 'get_gpu_pointers')
        assert hasattr(contract_b, 'get_gpu_pointers')
        assert hasattr(contract_a, 'get_tensors')
        assert hasattr(contract_b, 'get_tensors')
        assert hasattr(contract_a, 'nbytes')
        assert hasattr(contract_b, 'nbytes')
        assert hasattr(contract_a, 'is_device_memory')
        assert hasattr(contract_b, 'is_device_memory')
        assert hasattr(contract_a, 'release')
        assert hasattr(contract_b, 'release')
    
    def test_downstream_compatibility(self):
        """Contract should be compatible with downstream consumers (NVENC, inference)."""
        y_tensor = torch.zeros(2160, 3840, dtype=torch.uint8, device='cuda')
        uv_tensor = torch.zeros(1080, 1920, 2, dtype=torch.uint8, device='cuda')
        
        contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": 3840,
                "height": 2160,
                "format": "nv12_cuda",
                "pts": 100,
            },
            frame_id=1,
            camera_id="CAM1",
            timestamp=1000.0,
            pts=100,
            cuda_stream=0,
        )
        
        # NVENC needs get_gpu_pointers()
        y_ptr, uv_ptr = contract.get_gpu_pointers()
        assert y_ptr != 0
        assert uv_ptr != 0
        
        # Inference needs get_tensors()
        y_t, uv_t = contract.get_tensors()
        assert y_t.is_cuda
        assert uv_t.is_cuda
        assert y_t.dtype == torch.uint8
        assert uv_t.dtype == torch.uint8
        
        # Shape should be correct for NV12
        assert y_t.shape == (2160, 3840)
        assert uv_t.shape == (1080, 1920, 2)


class TestNV12Conversion:
    """Tests for NV12 to BGR/RGB conversion (used by annotation)."""
    
    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_nv12_to_bgr_cuda(self):
        """NV12 to BGR conversion should work on CUDA."""
        H, W = 480, 640
        y_tensor = torch.randint(0, 256, (H, W), dtype=torch.uint8, device='cuda')
        uv_tensor = torch.randint(0, 256, (H//2, W//2, 2), dtype=torch.uint8, device='cuda')
        
        bgr = nv12_cuda_to_bgr_cuda(y_tensor, uv_tensor)
        
        assert bgr.shape == (H, W, 3)
        assert bgr.dtype == torch.uint8
        assert bgr.is_cuda
    
    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_nv12_to_rgb_cuda(self):
        """NV12 to RGB conversion should work on CUDA."""
        from app.video.pynvcodec.gpu_frame_contract import nv12_cuda_to_rgb_cuda
        
        H, W = 480, 640
        y_tensor = torch.randint(0, 256, (H, W), dtype=torch.uint8, device='cuda')
        uv_tensor = torch.randint(0, 256, (H//2, W//2, 2), dtype=torch.uint8, device='cuda')
        
        rgb = nv12_cuda_to_rgb_cuda(y_tensor, uv_tensor)
        
        assert rgb.shape == (H, W, 3)
        assert rgb.dtype == torch.uint8
        assert rgb.is_cuda


if __name__ == "__main__":
    pytest.main([__file__, "-v"])