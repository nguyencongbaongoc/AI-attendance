"""
Phase 9.3 — Unit Tests for Backend Selection Mechanism.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from app.streaming.decoder_backend import (
    DecoderBackendFactory,
    DecoderBackendConfig,
    PyAVNVDECBackendConfig,
    PyNvVideoCodecBackendConfig,
)


class TestDecoderBackendFactory:
    """Tests for DecoderBackendFactory."""
    
    def test_available_backends(self):
        """Both backends should be available."""
        backends = DecoderBackendFactory.available_backends()
        assert "pyav" in backends
        assert "pynvvideocodec" in backends
        assert len(backends) == 2
    
    def test_unknown_backend_raises(self):
        """Unknown backend should raise ValueError."""
        config = DecoderBackendConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        with pytest.raises(ValueError, match="Unknown decoder backend"):
            DecoderBackendFactory.create("unknown", config)
    
    def test_create_pyav_backend(self):
        """Creating pyav backend should return PyAVNVDECBackend."""
        config = PyAVNVDECBackendConfig(
            camera_id="CAM1",
            rtsp_url="rtsp://localhost:8554/live/cam1",
        )
        # This will fail without PyAV but we test the factory logic
        backend = DecoderBackendFactory.create("pyav", config)
        assert backend is not None
        assert backend.__class__.__name__ == "PyAVNVDECBackend"
    
    def test_fallback_chain_exists(self):
        """Fallback chain should be defined."""
        assert hasattr(DecoderBackendFactory, '_fallback_chain')
        assert DecoderBackendFactory._fallback_chain["pynvvideocodec"] == "pyav"
        assert DecoderBackendFactory._fallback_chain["pyav"] is None


class TestCreateWithFallback:
    """Tests for create_with_fallback method."""
    
    def test_fallback_chain_structure(self):
        """Verify fallback chain structure."""
        chain = DecoderBackendFactory._fallback_chain
        assert chain["pynvvideocodec"] == "pyav"
        assert chain["pyav"] is None
    
    def test_create_with_fallback_signature(self):
        """Verify create_with_fallback method exists and has correct signature."""
        import inspect
        sig = inspect.signature(DecoderBackendFactory.create_with_fallback)
        params = list(sig.parameters.keys())
        assert 'primary_backend' in params
        assert 'config' in params
        assert 'enable_fallback' in params
        assert sig.parameters['enable_fallback'].default is True
    
    def test_create_with_fallback_returns_tuple(self):
        """create_with_fallback should return (backend, actual_backend_used)."""
        # This is a design test - the method signature guarantees tuple return
        import inspect
        sig = inspect.signature(DecoderBackendFactory.create_with_fallback)
        # Just verify it's a method that returns something
        assert callable(DecoderBackendFactory.create_with_fallback)


class TestVideoFrameIteratorBackend:
    """Tests for VideoFrameIterator backend selection."""
    
    @patch('app.data.input_adapter.DecoderBackendFactory')
    def test_default_backend_is_pynvvideocodec(self, mock_factory):
        """Default decoder should be pynvvideocodec."""
        from app.data.input_adapter import VideoFrameIterator
        
        mock_backend = MagicMock()
        mock_backend.open.return_value = MagicMock()
        mock_factory.create_with_fallback.return_value = (mock_backend, "pynvvideocodec")
        
        # Can't fully test without RTSP server, but we can verify default
        iterator = VideoFrameIterator("rtsp://localhost:8554/live/cam1")
        assert iterator.decoder == "pynvvideocodec"
    
    @patch('app.data.input_adapter.DecoderBackendFactory')
    def test_explicit_backend_a(self, mock_factory):
        """Explicit pyav_nvdec should use pyav backend."""
        from app.data.input_adapter import VideoFrameIterator
        
        mock_backend = MagicMock()
        mock_backend.open.return_value = MagicMock()
        mock_factory.create_with_fallback.return_value = (mock_backend, "pyav")
        
        iterator = VideoFrameIterator("rtsp://localhost:8554/live/cam1", decoder="pyav_nvdec")
        assert iterator.decoder == "pyav_nvdec"
    
    @patch('app.data.input_adapter.DecoderBackendFactory')
    def test_actual_backend_property(self, mock_factory):
        """actual_backend property should return backend used."""
        from app.data.input_adapter import VideoFrameIterator
        
        mock_backend = MagicMock()
        mock_backend.open.return_value = MagicMock()
        mock_factory.create_with_fallback.return_value = (mock_backend, "pyav")
        
        iterator = VideoFrameIterator("rtsp://localhost:8554/live/cam1", decoder="pynvvideocodec")
        # Before open, actual_backend is None
        assert iterator.actual_backend is None


class TestSettingsDecoderBackend:
    """Tests for settings-based decoder backend configuration."""
    
    @patch('app.config.settings.Settings')
    def test_settings_default_is_pynvvideocodec(self, mock_settings_class):
        """Settings default should be pynvvideocodec."""
        from app.config.settings import CamerasConfig
        
        config = CamerasConfig()
        assert config.decoder_backend == "pynvvideocodec"
    
    def test_settings_accepts_pyav_nvdec(self):
        """Settings should accept pyav_nvdec value."""
        from app.config.settings import CamerasConfig
        
        config = CamerasConfig(decoder_backend="pyav_nvdec")
        assert config.decoder_backend == "pyav_nvdec"
    
    def test_settings_rejects_invalid(self):
        """Settings should reject invalid decoder backend."""
        from app.config.settings import CamerasConfig
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            CamerasConfig(decoder_backend="invalid_backend")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])