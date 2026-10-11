#!/usr/bin/env python
"""Test correlation ID middleware."""

from app.main import create_app
from fastapi.testclient import TestClient

app = create_app()
client = TestClient(app)

# Test correlation ID is generated
response = client.get('/api/v1/health/live')
print(f"Status: {response.status_code}")
print(f"X-Request-ID in response: {response.headers.get('X-Request-ID')}")

# Test correlation ID is accepted
response2 = client.get('/api/v1/health/live', headers={'X-Request-ID': 'test-correlation-id-123'})
print(f"Status: {response2.status_code}")
print(f"X-Request-ID echoed: {response2.headers.get('X-Request-ID')}")

# Test invalid correlation ID is rejected (new one generated)
response3 = client.get('/api/v1/health/live', headers={'X-Request-ID': 'invalid<>'})
print(f"Status: {response3.status_code}")
print(f"X-Request-ID generated (not echoed): {response3.headers.get('X-Request-ID')}")