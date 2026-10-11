#!/usr/bin/env python
"""Test observability features - request timing, structured logs."""

from app.main import create_app
from fastapi.testclient import TestClient
from app.logging.logger import setup_logging, get_logger, log_with_context, log_duration, log_error, TimedOperation
import json
import sys
from io import StringIO

# Capture log output
old_stdout = sys.stdout
sys.stdout = captured = StringIO()

# Setup logging with JSON format
setup_logging(log_level="INFO", json_format=True, console=True)

app = create_app()
client = TestClient(app)

# Test 1: Request timing header
print("=== Test 1: Request Timing Header ===")
response = client.get('/api/v1/health/live')
print(f"Status: {response.status_code}")
print(f"X-Response-Time-ms: {response.headers.get('X-Response-Time-ms')}")

# Test 2: Structured logging helpers
print("\n=== Test 2: Structured Logging Helpers ===")
logger = get_logger("test.observability")

# Test log_with_context
log_with_context(logger, "info", "Test event", "test_component", "test_action", "success", camera_id="cam1", worker_id="worker-1")

# Test log_duration
log_duration(logger, "info", "Operation completed", "test_component", "test_action", 123.45, camera_id="cam1")

# Test log_error
try:
    raise ValueError("Test error")
except ValueError as e:
    log_error(logger, "Operation failed", "test_component", "test_action", e, camera_id="cam1")

# Test TimedOperation context manager
with TimedOperation(logger, "Timed operation", "test_component", "timed_action", camera_id="cam1") as op:
    pass  # Simulate work

# Test 3: Request with correlation ID
print("\n=== Test 3: Request with Correlation ID ===")
response2 = client.get('/api/v1/health/live', headers={'X-Request-ID': 'test-observability-123'})
print(f"Status: {response2.status_code}")
print(f"X-Request-ID: {response2.headers.get('X-Request-ID')}")
print(f"X-Response-Time-ms: {response2.headers.get('X-Response-Time-ms')}")

# Restore stdout
sys.stdout = old_stdout

# Check captured logs
output = captured.getvalue()
print("\n=== Captured Logs ===")
for line in output.strip().split('\n'):
    if line and not line.startswith('2026-10-') and not 'httpx' in line:
        try:
            log_entry = json.loads(line)
            # Print key fields
            fields = []
            for k in ['timestamp', 'level', 'logger', 'event', 'component', 'action', 'result', 'correlation_id', 'request_id', 'duration_ms', 'error_class', 'error_message', 'camera_id', 'worker_id']:
                if k in log_entry:
                    fields.append(f"{k}={log_entry[k]}")
            if fields:
                print(" | ".join(fields))
        except:
            pass

print("\nDone")