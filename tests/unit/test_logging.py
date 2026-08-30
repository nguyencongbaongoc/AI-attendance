"""
Unit tests for logging module.

Tests MUST NOT:
- start cameras
- connect to RTMP
- connect to RTSP
- start MediaMTX
- start FFmpeg against a camera
- load AI models
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.logging.logger import get_logger, setup_logging, quick_setup
import app.logging.logger as logger_module


class TestLogging:
    """Tests for logging module."""

    def setup_method(self):
        """Reset logging configuration before each test."""
        logger_module._logging_configured = False
        # Shutdown logging to release file handles
        logging.shutdown()

    def teardown_method(self):
        """Clean up logging after each test."""
        logging.shutdown()
        logger_module._logging_configured = False

    def test_setup_logging_console_only(self):
        """setup_logging should work with console only."""
        setup_logging(log_level="DEBUG", log_file=None, console=True)

        logger = get_logger("test")
        assert logger is not None

        # Should not raise
        logger.info("Test message")
        logger.debug("Debug message")
        logger.warning("Warning message")
        logger.error("Error message")

    def test_setup_logging_with_file(self):
        """setup_logging should work with file output."""
        tmpdir = tempfile.mkdtemp()
        log_file = Path(tmpdir) / "test.log"

        try:
            setup_logging(log_level="INFO", log_file=log_file, console=False)

            logger = get_logger("test_file")
            logger.info("Test file message")

            # Flush and shutdown to release file handle
            logging.shutdown()

            # Check file was created and has content
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8")
            assert "Test file message" in content
        finally:
            # Clean up
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_setup_logging_idempotent(self):
        """setup_logging should be idempotent (safe to call multiple times)."""
        setup_logging(log_level="INFO", console=True)
        setup_logging(log_level="DEBUG", console=True)  # Should not raise

        logger = get_logger("test_idempotent")
        logger.info("Test after reconfig")

    def test_get_logger_returns_bound_logger(self):
        """get_logger should return a structlog BoundLogger."""
        setup_logging(log_level="INFO", console=True)

        logger = get_logger("test_module")
        assert logger is not None
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_get_logger_auto_configures(self):
        """get_logger should auto-configure if not already configured."""
        # This test verifies the auto-configuration behavior
        logger = get_logger("test_auto")
        assert logger is not None
        logger.info("Auto-configured logger works")

    def test_quick_setup(self):
        """quick_setup should work with defaults."""
        tmpdir = tempfile.mkdtemp()
        log_dir = Path(tmpdir)

        try:
            quick_setup(log_level="INFO", log_dir=log_dir)

            logger = get_logger("test_quick")
            logger.info("Quick setup test")

            # Flush and shutdown to release file handle
            logging.shutdown()

            # Check log file was created
            log_files = list(log_dir.glob("app_*.log"))
            assert len(log_files) == 1

            content = log_files[0].read_text(encoding="utf-8")
            assert "Quick setup test" in content
        finally:
            # Clean up
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_log_levels(self):
        """All log levels should work."""
        setup_logging(log_level="DEBUG", console=True)

        logger = get_logger("test_levels")
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")

    def test_structured_logging(self):
        """Structured logging with key-value pairs should work."""
        setup_logging(log_level="INFO", console=True)

        logger = get_logger("test_structured")
        logger.info("Structured message", user_id=123, action="login", success=True)

    def test_logger_with_context(self):
        """Logger with bound context should work."""
        setup_logging(log_level="INFO", console=True)

        from app.logging.logger import get_logger_with_context

        logger = get_logger_with_context("test_context", request_id="abc123")
        logger.info("Message with context")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
