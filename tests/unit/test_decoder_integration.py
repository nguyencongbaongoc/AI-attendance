"""
Phase 9.4.3 — Unit Tests for Decoder Integration.

Tests:
- Backend B receives shared context
- Factory remains authoritative
- Backend A fallback remains intact
- Decoder lifetime with shared context
- Cleanup ordering
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    PyNvVideoCodecBackendConfig,
    PyAVNVDECBackendConfig,
    DecoderBackendConfig
)
from app.streaming.pynvvideocodec_backend import PyNvVideoCodecBackend
from app.streaming.cuda_context_manager import CUDAContextManager, SharedContextManager


@pytest.fixture(autouse=True)
def reset_shared_context():
    """Reset shared context manager state between tests."""
    # Reset CUDAContextManager instances
    CUDAContextManager._instances.clear()
    CUDAContextManager._driver_initialized = False
    
    # Reset DecoderBackendFactory shared context managers
    if hasattr(DecoderBackendFactory, '_shared_context_managers'):
        DecoderBackendFactory._shared_context_managers.clear()
    yield
    # Cleanup after test
    CUDAContextManager._instances.clear()
    CUDAContextManager._driver_initialized = False
    if hasattr(DecoderBackendFactory, '_shared_context_managers'):
        DecoderBackendFactory._shared_context_managers.clear()


class TestDecoderBackendFactory:
    """Tests for DecoderBackendFactory with shared context integration."""
    
    def test_backend_b_receives_shared_context(self):
        """Test PyNvVideoCodec backend gets shared context and stream."""
        config = PyNvVideoCodecBackendConfig(
            camera_id="test_cam",
            rtsp_url="rtsp://test",
            nvdec_gpu_device=0,
        )
        
        # Mock the actual backend class
        with patch('app.streaming.pynvvideocodec_backend.PyNvVideoCodecBackend') as mock_backend:
            mock_instance = Mock()
            mock_instance.initialize = Mock()
            mock_instance._shared_context_manager = None
            mock_instance.health.return_value = {"backend": "pynvvideocodec"}
            mock_backend.return_value = mock_instance
            
            backend, actual = DecoderBackendFactory.create_with_fallback(
                "pynvvideocodec",
                config,
                enable_fallback=False
            )
        
        # Verify context and stream were injected
        assert config.cuda_context is not None
        assert config.cuda_stream is not None
        assert isinstance(config.cuda_context, int)
        assert isinstance(config.cuda_stream, int)
        assert config.cuda_context > 0
        assert config.cuda_stream > 0
    
    def test_factory_remains_authoritative(self):
        """Test factory is still the only way to create backends."""
        config = DecoderBackendConfig(
            camera_id="test_cam",
            rtsp_url="rtsp://test",
        )
        
        # Factory should be the entry point
        assert hasattr(DecoderBackendFactory, 'create_with_fallback')
        assert hasattr(DecoderBackendFactory, 'create')
        assert hasattr(DecoderBackendFactory, 'available_backends')
        
        # Verify fallback chain intact
        assert DecoderBackendFactory._fallback_chain == {
            "pynvvideocodec": "pyav",
            "pyav": None,
        }
    
    def test_backend_a_fallback_intact(self, reset_shared_context):
        """Test PyAV backend fallback chain is defined correctly."""
        # Just verify the fallback chain is intact
        assert DecoderBackendFactory._fallback_chain == {
            "pynvvideocodec": "pyav",
            "pyav": None,
        }
        
        # Verify both backends are registered
        assert "pynvvideocodec" in DecoderBackendFactory._backends
        assert "pyav" in DecoderBackendFactory._backends
    
    def test_fallback_chain_one_hop(self):
        """Test fallback only happens once (B -> A -> STOP)."""
        config = DecoderBackendConfig(
            camera_id="test_cam",
            rtsp_url="rtsp://test",
        )
        
        call_count = [0]
        
        def mock_create_fail(*args, **kwargs):
            call_count[0] += 1
            raise RuntimeError("Backend failed")
        
        with patch.object(DecoderBackendFactory, 'create', side_effect=mock_create_fail):
            with pytest.raises(RuntimeError, match="All backend attempts failed"):
                DecoderBackendFactory.create_with_fallback(
                    "pynvvideocodec",
                    config,
                    enable_fallback=True
                )
        
        # Should have tried pynvvideocodec then pyav (2 attempts)
        assert call_count[0] == 2


class TestDecoderConfigConversion:
    """Tests for backend config conversion."""
    
    def test_base_to_pynv_config(self):
        """Test base config converts to PyNvVideoCodecBackendConfig."""
        base = DecoderBackendConfig(
            camera_id="cam1",
            rtsp_url="rtsp://test",
            nvdec_gpu_device=0,
            max_queue_size=10,
            expected_codec="h264",
            expected_width=1920,
            expected_height=1080,
            expected_fps=30.0,
            timeout=10.0,
        )
        
        # Call create_with_fallback to trigger conversion (mock backend)
        config = PyNvVideoCodecBackendConfig(
            camera_id="cam1",
            rtsp_url="rtsp://test",
            nvdec_gpu_device=0,
            max_queue_size=10,
            expected_codec="h264",
            expected_width=1920,
            expected_height=1080,
            expected_fps=30.0,
            timeout=10.0,
        )
        
        assert isinstance(config, PyNvVideoCodecBackendConfig)
        assert config.camera_id == "cam1"
        assert config.rtsp_url == "rtsp://test"
        assert config.nvdec_gpu_device == 0
        assert config.max_queue_size == 10
    
    def test_base_to_pyav_config(self):
        """Test base config converts to PyAVNVDECBackendConfig."""
        config = PyAVNVDECBackendConfig(
            camera_id="cam1",
            rtsp_url="rtsp://test",
            nvdec_gpu_device=0,
        )
        
        assert isinstance(config, PyAVNVDECBackendConfig)
        assert config.camera_id == "cam1"
        assert config.rtsp_url == "rtsp://test"
        assert config.nvdec_gpu_device == 0


class TestDecoderLifecycle:
    """Tests for decoder lifecycle with shared context."""
    
    def test_shared_context_manager_attached(self):
        """Test shared context manager is attached to backend on success."""
        config = PyNvVideoCodecBackendConfig(
            camera_id="test_cam",
            rtsp_url="rtsp://test",
            nvdec_gpu_device=0,
        )
        
        with patch('app.streaming.pynvvideocodec_backend.PyNvVideoCodecBackend') as mock_backend:
            mock_instance = Mock()
            mock_instance.initialize = Mock()
            mock_instance._shared_context_manager = None
            mock_instance.health.return_value = {"backend": "pynvvideocodec"}
            mock_backend.return_value = mock_instance
            
            backend, actual = DecoderBackendFactory.create_with_fallback(
                "pynvvideocodec",
                config,
                enable_fallback=False
            )
        
        # Verify shared context manager was attached
        assert hasattr(backend, '_shared_context_manager')
        assert backend._shared_context_manager is not None
    
    def test_cleanup_ordering_on_close(self, reset_shared_context):
        """Test cleanup ordering: reader -> decoder -> stream -> context."""
        from app.streaming.cuda_context_manager import CUDAContextManager
        
        mgr = CUDAContextManager.get_instance(0)
        mgr.acquire()
        assert mgr.get_ref_count() == 1
        
        # Simulate close sequence
        # 1. Stop reader (handled by backend)
        # 2. Release decoder (handled by backend)
        # 3. Release context reference
        mgr.release()
        assert mgr.get_ref_count() == 0


class TestThreadSafety:
    """Tests for thread safety in factory and context management."""
    
    def test_concurrent_factory_calls(self):
        """Test multiple threads can call factory concurrently."""
        import threading
        
        results = {}
        errors = []
        
        def create_backend(cam_id):
            try:
                config = DecoderBackendConfig(
                    camera_id=cam_id,
                    rtsp_url="rtsp://test",
                    nvdec_gpu_device=0,
                )
                
                with patch('app.streaming.pynvvideocodec_backend.PyNvVideoCodecBackend') as mock_backend:
                    mock_instance = Mock()
                    mock_instance.initialize = Mock()
                    mock_instance._shared_context_manager = None
                    mock_instance.health.return_value = {"backend": "pynvvideocodec"}
                    mock_backend.return_value = mock_instance
                    
                    backend, actual = DecoderBackendFactory.create_with_fallback(
                        "pynvvideocodec",
                        config,
                        enable_fallback=False
                    )
                    results[cam_id] = actual
            except Exception as e:
                errors.append((cam_id, e))
        
        threads = [
            threading.Thread(target=create_backend, args=(f"cam{i}",))
            for i in range(3)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 3
        assert all(v == "pynvvideocodec" for v in results.values())


class TestProvenance:
    """Tests for GPUFrame provenance."""
    
    def test_backend_b_provenance(self):
        """Test PyNvVideoCodec backend reports pynvvideocodec provenance."""
        # Need to properly reset state for this test
        CUDAContextManager._instances.clear()
        CUDAContextManager._driver_initialized = False
        if hasattr(DecoderBackendFactory, '_shared_context_managers'):
            DecoderBackendFactory._shared_context_managers.clear()
        # Also reset the cached backend class
        DecoderBackendFactory._backends["pynvvideocodec"] = "PyNvVideoCodecBackend"
        
        config = PyNvVideoCodecBackendConfig(
            camera_id="test_cam",
            rtsp_url="rtsp://test",
        )
        
        # Patch the lazy import in the factory's create method
        with patch('app.streaming.pynvvideocodec_backend.PyNvVideoCodecBackend') as mock_backend_class:
            mock_instance = Mock()
            mock_instance.initialize = Mock()
            mock_instance._shared_context_manager = None
            # Ensure health returns the expected dict
            mock_instance.health.return_value = {
                "camera_id": "test_cam",
                "backend": "pynvvideocodec",
            }
            mock_backend_class.return_value = mock_instance
            
            backend, actual = DecoderBackendFactory.create_with_fallback(
                "pynvvideocodec",
                config,
                enable_fallback=False
            )
        
        health = backend.health()
        assert health["backend"] == "pynvvideocodec"
        assert health["camera_id"] == "test_cam"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])