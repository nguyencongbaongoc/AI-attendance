#!/usr/bin/env python
"""Test correlation ID in audit logs through middleware."""

from app.main import create_app
from fastapi.testclient import TestClient
from app.logging.logger import setup_logging, get_logger

# Setup logging with JSON format
setup_logging(log_level="INFO", json_format=True, console=True)

app = create_app()
client = TestClient(app)

# Make a request that triggers audit logging (auth endpoint)
import os
os.environ['AI_WORKER_API_KEY'] = 'test-worker-key'

# First request - should generate correlation ID and log auth failure
response = client.post(
    '/api/v1/attendance/events',
    headers={'X-API-Key': 'wrong-key'},
    json={}
)
print(f"Auth failure response: {response.status_code}")

# Check if we can see correlation ID in the logs (this would be in the actual log output)
# The middleware should have added it to contextvars

# Second request - provide our own correlation ID
response2 = client.post(
    '/api/v1/attendance/events',
    headers={
        'X-API-Key': 'wrong-key',
        'X-Request-ID': 'custom-correlation-id-456'
    },
    json={}
)
print(f"Auth failure with custom ID response: {response2.status_code}")
print(f"X-Request-ID echoed: {response2.headers.get('X-Request-ID')}")

print("Test complete")