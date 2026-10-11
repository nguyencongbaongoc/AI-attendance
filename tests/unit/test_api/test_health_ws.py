"""
Phase 7 — Unit Tests for Health WebSocket Authentication (Isolated).

Tests for WebSocket authentication functions only - avoiding circular imports.
"""

import pytest
import os
import asyncio
from unittest.mock import MagicMock

from fastapi import HTTPException, Request
from app.security.api_key_cache import get_api_key_cache


def create_mock_request(client_host: str = "127.0.0.1", forwarded_for: str = None) -> Request:
    """Create a mock Request object for testing."""
    mock_request = MagicMock(spec=Request)
    mock_request.client = MagicMock()
    mock_request.client.host = client_host
    if forwarded_for:
        mock_request.headers = {"X-Forwarded-For": forwarded_for}
    else:
        mock_request.headers = {}
    return mock_request


# Import the verification function after setting up mocks to avoid circular imports
@pytest.fixture
def verify_health_ws_key():
    from app.api.websocket import verify_health_ws_key as _verify
    return _verify


class TestVerifyHealthWsKey:
    """Tests for Health WebSocket API key verification."""
    
    @pytest.mark.asyncio
    async def test_valid_admin_key(self, verify_health_ws_key):
        """Test valid admin API key."""
        os.environ["ADMIN_API_KEY"] = "admin-secret-123"
        
        try:
            # Need to invalidate cache first
            get_api_key_cache().invalidate_all()
            
            mock_request = create_mock_request()
            result = await verify_health_ws_key(mock_request, "admin-secret-123")
            assert result is True
        finally:
            del os.environ["ADMIN_API_KEY"]
    
    @pytest.mark.asyncio
    async def test_invalid_key(self, verify_health_ws_key):
        """Test invalid API key."""
        os.environ["ADMIN_API_KEY"] = "admin-secret"
        
        try:
            get_api_key_cache().invalidate_all()
            
            mock_request = create_mock_request()
            with pytest.raises(HTTPException) as exc_info:
                await verify_health_ws_key(mock_request, "invalid-key")
            
            assert exc_info.value.status_code == 401
        finally:
            del os.environ["ADMIN_API_KEY"]
    
    @pytest.mark.asyncio
    async def test_no_key_configured(self, verify_health_ws_key):
        """Test when no admin key is configured."""
        # Remove any existing keys
        for key in ["ADMIN_API_KEY"]:
            if key in os.environ:
                del os.environ[key]
        
        get_api_key_cache().invalidate_all()
        
        mock_request = create_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await verify_health_ws_key(mock_request, "any-key")
        
        assert exc_info.value.status_code == 503


if __name__ == "__main__":
    pytest.main([__file__, "-v"])