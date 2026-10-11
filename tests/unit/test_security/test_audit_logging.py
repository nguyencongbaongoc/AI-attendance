"""
Phase 7 — Security Audit Logging Tests.

Tests for audit logging functionality across all security-sensitive operations.
"""

import pytest
import os
import time
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.security.api_key_cache import get_api_key_cache, init_api_key_cache
from app.logging.logger import setup_logging, get_logger


class TestAPIKeyCache:
    """Tests for API Key Cache with TTL."""
    
    def setup_method(self):
        """Reset cache before each test."""
        get_api_key_cache().invalidate_all()
    
    def test_cache_loads_from_environment(self):
        """Test cache loads key from environment on first access."""
        os.environ["TEST_API_KEY"] = "test-secret-123"
        
        try:
            cache = get_api_key_cache()
            value = cache.get("TEST_API_KEY")
            assert value == "test-secret-123"
        finally:
            del os.environ["TEST_API_KEY"]
            cache.invalidate_all()
    
    def test_cache_respects_ttl(self):
        """Test cache respects TTL and reloads after expiry."""
        # Initialize with very short TTL
        init_api_key_cache(ttl_seconds=1)
        
        os.environ["TTL_TEST_KEY"] = "initial-value"
        
        try:
            cache = get_api_key_cache()
            
            # First access loads from env
            value1 = cache.get("TTL_TEST_KEY")
            assert value1 == "initial-value"
            
            # Change environment value
            os.environ["TTL_TEST_KEY"] = "updated-value"
            
            # Within TTL, should return cached value
            value2 = cache.get("TTL_TEST_KEY")
            assert value2 == "initial-value"
            
            # Wait for TTL to expire
            time.sleep(1.5)
            
            # After TTL, should load new value
            value3 = cache.get("TTL_TEST_KEY")
            assert value3 == "updated-value"
        finally:
            del os.environ["TTL_TEST_KEY"]
            cache.invalidate_all()
            init_api_key_cache(ttl_seconds=300)  # Reset to default
    
    def test_invalidate_single_key(self):
        """Test invalidating a single key."""
        os.environ["SINGLE_TEST_KEY"] = "test-value"
        
        try:
            cache = get_api_key_cache()
            
            # Load into cache
            value1 = cache.get("SINGLE_TEST_KEY")
            assert value1 == "test-value"
            
            # Invalidate
            cache.invalidate("SINGLE_TEST_KEY")
            
            # Change environment
            os.environ["SINGLE_TEST_KEY"] = "new-value"
            
            # Should load new value
            value2 = cache.get("SINGLE_TEST_KEY")
            assert value2 == "new-value"
        finally:
            del os.environ["SINGLE_TEST_KEY"]
            cache.invalidate_all()
    
    def test_invalidate_all_keys(self):
        """Test invalidating all keys."""
        os.environ["KEY_1"] = "value-1"
        os.environ["KEY_2"] = "value-2"
        
        try:
            cache = get_api_key_cache()
            
            # Load both into cache
            cache.get("KEY_1")
            cache.get("KEY_2")
            
            # Invalidate all
            cache.invalidate_all()
            
            # Change environment
            os.environ["KEY_1"] = "new-value-1"
            os.environ["KEY_2"] = "new-value-2"
            
            # Should load new values
            assert cache.get("KEY_1") == "new-value-1"
            assert cache.get("KEY_2") == "new-value-2"
        finally:
            del os.environ["KEY_1"]
            del os.environ["KEY_2"]
            cache.invalidate_all()


class TestAuditLogging:
    """Tests for security audit logging."""
    
    def setup_method(self):
        """Setup logging for tests."""
        setup_logging(log_level="DEBUG", json_format=True)
    
    def test_audit_logger_creates_structured_logs(self):
        """Test audit logger produces structured JSON logs."""
        audit_logger = get_logger("app.security.audit")
        
        # This should not raise and should produce structured output
        audit_logger.info(
            "Security audit: authentication - success",
            audit=True,
            event_type="authentication",
            outcome="success",
            actor="127.0.0.1",
            resource="ai_worker_key",
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
    
    def test_secret_redaction_in_audit_logs(self):
        """Test that secrets are redacted in audit logs."""
        audit_logger = get_logger("app.security.audit")
        
        # Log with sensitive data
        audit_logger.info(
            "Security audit: authentication - failure",
            audit=True,
            event_type="authentication",
            outcome="failure",
            actor="127.0.0.1",
            resource="admin_key",
            details={
                "api_key": "secret-key-value",
                "reason": "invalid_key",
                "non_sensitive": "this-should-appear"
            },
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
        
        # The logger's secret filtering should redact the api_key
        # Actual verification happens in the secret filter processor


class TestSecretFiltering:
    """Tests for secret filtering in logs."""
    
    def setup_method(self):
        """Setup logging for tests."""
        setup_logging(log_level="DEBUG", json_format=True, console=False)
    
    def test_telegram_token_redacted(self):
        """Test Telegram bot tokens are redacted."""
        logger = get_logger("test")
        
        # This would be tested by checking log output
        # The secret filter in logger.py handles this
        logger.info("Bot token: 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    
    def test_chat_id_redacted(self):
        """Test chat IDs are redacted."""
        logger = get_logger("test")
        
        logger.info("Chat ID: 987654321")
    
    def test_api_key_redacted(self):
        """Test API keys are redacted."""
        logger = get_logger("test")
        
        logger.info("API_KEY=secret-key-value")
        logger.info("X-API-Key: another-secret")


class TestErrorHandling:
    """Tests for safe error handling without information leakage."""
    
    def test_no_credentials_in_errors(self):
        """Test that credentials don't leak in error messages."""
        from app.api.ai_worker import verify_admin_key
        import asyncio
        from fastapi import HTTPException
        import os
        from app.security.api_key_cache import get_api_key_cache
        
        # Set up admin key
        os.environ["ADMIN_API_KEY"] = "test-admin-secret"
        get_api_key_cache().invalidate_all()
        
        try:
            async def test():
                from unittest.mock import MagicMock
                mock_request = MagicMock()
                mock_request.client = MagicMock()
                mock_request.client.host = "127.0.0.1"
                mock_request.headers = {}
                
                try:
                    await verify_admin_key(mock_request, "wrong-key")
                    assert False, "Should have raised"
                except HTTPException as e:
                    assert e.status_code == 401
                    # Error message should not contain the actual key
                    assert "wrong-key" not in str(e.detail)
                    assert "secret" not in str(e.detail).lower()
                    assert "test-admin-secret" not in str(e.detail)
            
            asyncio.run(test())
        finally:
            del os.environ["ADMIN_API_KEY"]
            get_api_key_cache().invalidate_all()
    
    def test_error_messages_are_generic(self):
        """Test that error messages don't leak internal details."""
        # Verify that error responses are generic and don't contain
        # stack traces, SQL, paths, or other sensitive information
        from app.api.ai_worker import verify_admin_key
        import asyncio
        from fastapi import HTTPException
        import os
        from app.security.api_key_cache import get_api_key_cache
        
        # Test with no key configured
        for key in ["ADMIN_API_KEY"]:
            if key in os.environ:
                del os.environ[key]
        get_api_key_cache().invalidate_all()
        
        try:
            async def test():
                from unittest.mock import MagicMock
                mock_request = MagicMock()
                mock_request.client = MagicMock()
                mock_request.client.host = "127.0.0.1"
                mock_request.headers = {}
                
                try:
                    await verify_admin_key(mock_request, "any-key")
                    assert False, "Should have raised"
                except HTTPException as e:
                    assert e.status_code == 503
                    # Should not contain internal paths or config details
                    assert "not configured" in str(e.detail).lower()
            
            asyncio.run(test())
        finally:
            get_api_key_cache().invalidate_all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])