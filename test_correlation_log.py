#!/usr/bin/env python
"""Test correlation ID appears in logs."""

import json
from app.main import create_app
from fastapi.testclient import TestClient
from app.logging.logger import setup_logging, get_logger
import sys
from io import StringIO

# Capture log output
old_stdout = sys.stdout
sys.stdout = captured = StringIO()

# Setup logging with JSON format
setup_logging(log_level="INFO", json_format=True, console=True)

app = create_app()
client = TestClient(app)

# Make a request with correlation ID
response = client.get('/api/v1/health/live', headers={'X-Request-ID': 'test-correlation-123'})

# Check response
print(f"Status: {response.status_code}")
print(f"X-Request-ID: {response.headers.get('X-Request-ID')}")

# Restore stdout
sys.stdout = old_stdout

# Check captured logs for correlation_id
output = captured.getvalue()
print("\n--- Captured Logs ---")
for line in output.strip().split('\n'):
    if line:
        try:
            log_entry = json.loads(line)
            if 'request_id' in log_entry:
                print(f"Found request_id in log: {log_entry['request_id']}")
            if 'correlation_id' in log_entry:
                print(f"Found correlation_id in log: {log_entry['correlation_id']}")
        except:
            pass

print("\nDone")