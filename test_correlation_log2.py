#!/usr/bin/env python
"""Test correlation ID appears in logs - better version."""

from app.main import create_app
from fastapi.testclient import TestClient
from app.logging.logger import setup_logging, get_logger
import structlog
import logging

# Setup logging with JSON format
setup_logging(log_level="DEBUG", json_format=True, console=True)

# Get the audit logger
audit_logger = get_logger("app.security.audit")

# Test direct logging with correlation ID
import structlog.contextvars
token = structlog.contextvars.bind_contextvars(request_id="test-correlation-123")
try:
    audit_logger.info("Test audit log with correlation ID", audit=True, event_type="test", outcome="success")
finally:
    structlog.contextvars.unbind_contextvars(token)

print("Direct log test done")