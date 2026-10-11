"""
Phase 9.1 — Observability Tests.

Tests for failure/recovery observability implementation.
Covers correlation_id propagation, secret redaction, retry_state transitions.
"""

from __future__ import annotations

import logging
import re
from unittest.mock import Mock, patch

import pytest

from app.logging.logger import log_failure, get_logger, setup_logging, log_with_context, log_duration
from app.middleware.correlation_id import get_correlation_id, set_correlation_id, clear_correlation_id


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)


def _get_record_fields(record: logging.LogRecord) -> dict:
    """Extract structured fields from a log record's message."""
    msg = _strip_ansi(record.message)
    fields = {}
    # Parse key=value pairs
    for part in msg.split():
        if '=' in part and not part.startswith('[') and not part.endswith(']'):
            # Find the last = to handle values with =
            idx = part.rfind('=')
            key = part[:idx]
            value = part[idx+1:]
            fields[key] = value
    return fields


class TestLogFailureHelper:
    """Tests for log_failure() helper function."""

    @pytest.fixture(autouse=True)
    def setup_logging_config(self):
        """Configure logging for tests."""
        setup_logging(log_level="DEBUG", console=True, json_format=False)
        yield
        # Clear correlation ID after each test
        clear_correlation_id()

    def test_log_failure_basic_fields(self, caplog):
        """Test log_failure includes all required schema fields."""
        logger = get_logger("test.failure")
        set_correlation_id("test-correlation-123")

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Test failure",
                component="test_component",
                action="test_action",
                failure_class="TestError",
                failure_reason="test_reason",
                retry_state="none",
            )

        # Find the log record
        assert len(caplog.records) >= 1
        record = caplog.records[-1]
        fields = _get_record_fields(record)
        
        # Check structured fields are present in the log message
        assert "Test failure" in _strip_ansi(record.message)
        assert fields.get("component") == "test_component"
        assert fields.get("action") == "test_action"
        assert fields.get("result") == "failure"
        assert fields.get("failure_class") == "TestError"
        assert fields.get("failure_reason") == "test_reason"
        assert fields.get("retry_state") == "none"
        assert fields.get("request_id") == "test-correlation-123"

    def test_log_failure_retry_states(self, caplog):
        """Test log_failure with different retry_state values."""
        logger = get_logger("test.failure")
        set_correlation_id("test-retry-456")

        retry_states = ["none", "retrying", "exhausted", "success"]
        
        for state in retry_states:
            caplog.clear()
            with caplog.at_level(logging.ERROR):
                log_failure(
                    logger,
                    event=f"Failure with {state}",
                    component="test",
                    action="test",
                    failure_class="TestError",
                    failure_reason="test",
                    retry_state=state,
                )
            
            record = caplog.records[-1]
            fields = _get_record_fields(record)
            assert fields.get("retry_state") == state

    def test_log_failure_without_correlation_id(self, caplog):
        """Test log_failure works without correlation_id."""
        logger = get_logger("test.failure")
        clear_correlation_id()

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Test failure",
                component="test",
                action="test",
                failure_class="TestError",
                failure_reason="test",
            )

        record = caplog.records[-1]
        fields = _get_record_fields(record)
        # Should not have correlation_id when not set (structlog uses request_id)
        assert "request_id" not in fields or fields.get("request_id") == "unknown"

    def test_log_failure_additional_kwargs(self, caplog):
        """Test log_failure passes through additional context."""
        logger = get_logger("test.failure")
        set_correlation_id("test-kwargs-789")

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Test failure",
                component="test",
                action="test",
                failure_class="TestError",
                failure_reason="test",
                camera_id="cam1",
                attempt=3,
                max_attempts=5,
            )

        record = caplog.records[-1]
        fields = _get_record_fields(record)
        assert fields.get("camera_id") == "cam1"
        assert fields.get("attempt") == "3"
        assert fields.get("max_attempts") == "5"


class TestCorrelationIdPropagation:
    """Tests for correlation_id propagation through failure events."""

    @pytest.fixture(autouse=True)
    def setup_logging_config(self):
        setup_logging(log_level="DEBUG", console=True, json_format=False)
        yield
        clear_correlation_id()

    def test_correlation_id_in_failure_logs(self, caplog):
        """Test correlation_id flows from context to failure logs."""
        logger = get_logger("test.correlation")
        test_cid = "corr-abc-123"
        set_correlation_id(test_cid)

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Correlation test",
                component="test",
                action="test",
                failure_class="TestError",
                failure_reason="test",
            )

        record = caplog.records[-1]
        fields = _get_record_fields(record)
        assert fields.get("request_id") == test_cid

    def test_different_correlation_ids_isolated(self, caplog):
        """Test different correlation IDs don't leak between requests."""
        logger = get_logger("test.isolation")

        # First request
        set_correlation_id("req-1")
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Event 1", "test", "test", "Error", "reason1")
        record1 = caplog.records[-1]
        fields1 = _get_record_fields(record1)
        assert fields1.get("request_id") == "req-1"

        # Second request
        caplog.clear()
        set_correlation_id("req-2")
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Event 2", "test", "test", "Error", "reason2")
        record2 = caplog.records[-1]
        fields2 = _get_record_fields(record2)
        assert fields2.get("request_id") == "req-2"
        assert fields2.get("request_id") != "req-1"


class TestSecretRedactionInFailureLogs:
    """Tests for secret redaction in failure logs."""

    @pytest.fixture(autouse=True)
    def setup_logging_config(self):
        setup_logging(log_level="DEBUG", console=True, json_format=False)
        yield
        clear_correlation_id()

    def test_api_key_redacted_in_failure_log(self, caplog):
        """Test API keys are redacted in failure log context."""
        logger = get_logger("test.secret")

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Auth failure",
                component="auth",
                action="verify",
                failure_class="AuthenticationError",
                failure_reason="invalid_key",
                api_key="secret-key-12345",
            )

        record = caplog.records[-1]
        msg = _strip_ansi(record.message)
        # API key should be redacted
        assert "secret-key-12345" not in msg
        assert "***REDACTED***" in msg

    def test_token_redacted_in_failure_log(self, caplog):
        """Test tokens are redacted in failure log context."""
        logger = get_logger("test.secret")

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="Token failure",
                component="auth",
                action="verify",
                failure_class="AuthenticationError",
                failure_reason="invalid_token",
                token="bot123:ABC-DEF",
            )

        record = caplog.records[-1]
        msg = _strip_ansi(record.message)
        assert "bot123:ABC-DEF" not in msg
        assert "***REDACTED***" in msg

    def test_password_redacted_in_failure_log(self, caplog):
        """Test passwords are redacted in failure log context."""
        logger = get_logger("test.secret")

        with caplog.at_level(logging.ERROR):
            log_failure(
                logger,
                event="DB failure",
                component="db",
                action="connect",
                failure_class="ConnectionError",
                failure_reason="auth_failed",
                password="super-secret-pw",
            )

        record = caplog.records[-1]
        msg = _strip_ansi(record.message)
        assert "super-secret-pw" not in msg
        assert "***REDACTED***" in msg


class TestFailureRecoveryLifecycle:
    """Tests for failure/recovery retry_state transitions."""

    @pytest.fixture(autouse=True)
    def setup_logging_config(self):
        setup_logging(log_level="DEBUG", console=True, json_format=False)
        yield
        clear_correlation_id()

    def test_retry_state_transitions(self, caplog):
        """Test retry_state transitions: none -> retrying -> success/exhausted."""
        logger = get_logger("test.lifecycle")
        set_correlation_id("lifecycle-test")

        # Initial failure (none)
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Initial failure", "svc", "op", "Error", "reason", retry_state="none")
        fields = _get_record_fields(caplog.records[-1])
        assert fields.get("retry_state") == "none"

        # Retry attempt (retrying)
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Retry attempt", "svc", "op", "Error", "reason", retry_state="retrying")
        fields = _get_record_fields(caplog.records[-1])
        assert fields.get("retry_state") == "retrying"

        # Retry success (success)
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Retry succeeded", "svc", "op", "Error", "reason", retry_state="success")
        fields = _get_record_fields(caplog.records[-1])
        assert fields.get("retry_state") == "success"

        # Retry exhausted (exhausted)
        caplog.clear()
        with caplog.at_level(logging.ERROR):
            log_failure(logger, "Retries exhausted", "svc", "op", "Error", "reason", retry_state="exhausted")
        fields = _get_record_fields(caplog.records[-1])
        assert fields.get("retry_state") == "exhausted"


class TestStructuredLoggingIntegration:
    """Tests for integration with existing structured logging."""

    @pytest.fixture(autouse=True)
    def setup_logging_config(self):
        setup_logging(log_level="DEBUG", console=True, json_format=False)
        yield
        clear_correlation_id()

    def test_log_with_context_still_works(self, caplog):
        """Test log_with_context still works for non-failure logging."""
        logger = get_logger("test.integration")

        with caplog.at_level(logging.INFO):
            log_with_context(
                logger, "info", "Test event", "component", "action", "success",
                custom_field="value"
            )

        record = caplog.records[-1]
        fields = _get_record_fields(record)
        assert "Test event" in _strip_ansi(record.message)
        assert fields.get("component") == "component"
        assert fields.get("action") == "action"
        assert fields.get("result") == "success"
        assert fields.get("custom_field") == "value"

    def test_log_duration_works(self, caplog):
        """Test log_duration helper works."""
        logger = get_logger("test.integration")

        with caplog.at_level(logging.INFO):
            log_duration(
                logger, "info", "Operation completed", "component", "action",
                duration_ms=123.45, result="success"
            )

        record = caplog.records[-1]
        fields = _get_record_fields(record)
        assert fields.get("duration_ms") == "123.45"


class TestLoggerSwitchToStructlog:
    """Tests verifying loggers switched from stdlib to structlog."""

    def test_ai_worker_uses_structlog(self):
        """Verify ai_worker uses structlog logger."""
        from app.api.ai_worker import logger
        from structlog._config import BoundLoggerLazyProxy
        assert isinstance(logger, BoundLoggerLazyProxy)

    def test_attendance_ws_uses_structlog(self):
        """Verify attendance_ws uses structlog logger."""
        from app.api.attendance_ws import logger
        from structlog._config import BoundLoggerLazyProxy
        assert isinstance(logger, BoundLoggerLazyProxy)

    def test_health_monitor_uses_structlog(self):
        """Verify health monitor uses structlog logger."""
        from app.streaming.health import logger
        from structlog._config import BoundLoggerLazyProxy
        assert isinstance(logger, BoundLoggerLazyProxy)

    def test_resolver_uses_structlog(self):
        """Verify resolver uses structlog logger."""
        from app.in_out.resolver import logger
        from structlog._config import BoundLoggerLazyProxy
        assert isinstance(logger, BoundLoggerLazyProxy)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])