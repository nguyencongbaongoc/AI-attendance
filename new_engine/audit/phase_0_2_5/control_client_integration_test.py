#!/usr/bin/env python3
"""
PipelineEngine Control Client Integration Test

Tests the actual PipelineEngine control_client.py against the real Legacy Backend.
"""

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

# Set up test environment
os.environ["AI_WORKER_API_KEY"] = "test-worker-key-123"
os.environ["AI_CONTROL_API_KEY"] = "test-control-key-456"
os.environ["ADMIN_API_KEY"] = "test-admin-key-789"

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Mock PipelineEngine for testing
from unittest.mock import MagicMock, AsyncMock

# Import the control client
from pipeline_engine.integration.control_client import (
    PipelineEngineControlServer, 
    ControlClientConfig,
    Action,
    ControlRequest,
    ControlResponse
)

# Import backend test client
from fastapi.testclient import TestClient
from app.main import create_app

async def test_control_client_integration():
    print("=" * 60)
    print("PIPELINEENGINE CONTROL CLIENT INTEGRATION TEST")
    print("=" * 60)
    
    # Create backend
    test_app = create_app()
    test_client = TestClient(test_app)
    
    worker_id = "pipeline_engine_1"
    
    # Create mock engine
    mock_engine = MagicMock()
    mock_engine.state = MagicMock()
    mock_engine.state.value = "RUNNING"
    mock_engine.start = MagicMock(return_value=True)
    mock_engine.stop = MagicMock()
    mock_engine.camera_manager = MagicMock()
    mock_engine.camera_manager.get_camera_list = MagicMock(return_value=[])
    
    # Create control client config pointing to test backend
    config = ControlClientConfig(
        backend_base_url="http://testserver",
        worker_id=worker_id,
        api_key="test-control-key-456",
        poll_interval=0.5,
        timeout=5.0
    )
    
    # Create control server
    control_server = PipelineEngineControlServer(mock_engine, config)
    
    # Replace the httpx client with test client adapter
    # We need to monkey-patch the _client to use TestClient
    import httpx
    
    class TestClientAdapter:
        def __init__(self, test_client):
            self.test_client = test_client
            
        async def get(self, url, params=None, headers=None):
            # Convert httpx-style call to TestClient
            h = dict(headers) if headers else {}
            h.pop("host", None)  # Remove host header
            response = self.test_client.get(url, params=params, headers=h)
            return MockResponse(response)
            
        async def post(self, url, json=None, headers=None):
            h = dict(headers) if headers else {}
            h.pop("host", None)
            response = self.test_client.post(url, json=json, headers=h)
            return MockResponse(response)
            
        async def aclose(self):
            pass
    
    class MockResponse:
        def __init__(self, response):
            self.status_code = response.status_code
            self._json = response.json()
            self.text = response.text
            
        def json(self):
            return self._json
    
    # Start the control server (which will use our test client)
    control_server._client = TestClientAdapter(test_client)
    control_server._stop_event = asyncio.Event()
    
    print("\n[1] Submitting control request via Admin API...")
    request_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())
    
    # Submit START_WORKER request
    admin_response = test_client.post(
        f"/api/v1/ai/control/START_WORKER",
        json={
            "request_id": request_id,
            "action": "START_WORKER",
            "target": "worker",
            "target_id": worker_id,
            "parameters": {},
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
            "expires_at": time.time() + 300
        },
        headers={"X-API-Key": "test-admin-key-789"}
    )
    print(f"  Admin submit: {admin_response.status_code} - {admin_response.json()['status']}")
    assert admin_response.status_code == 200
    assert admin_response.json()["status"] == "PENDING"
    
    print("\n[2] Testing client polling (will fail due to action name mismatch)...")
    try:
        # This will call _poll_commands which expects "commands" key
        await control_server._poll_commands()
        print(f"  Commands received: {len(control_server._commands)}")
        print(f"  Commands: {control_server._commands}")
        if len(control_server._commands) == 0:
            print("  WARN: Client got 0 commands (backend returns 'requests' not 'commands')")
    except Exception as e:
        print(f"  ERROR: {e}")
    
    print("\n[3] Testing action name mismatch...")
    print("  Backend action: START_WORKER")
    print(f"  Client action enum: {Action.START} ('start')")
    print(f"  Match: {'start' == 'START_WORKER'}")
    
    print("\n[4] Testing response submission endpoint mismatch...")
    print("  Client would POST to: /api/v1/ai/control/start/response")
    print("  Backend expects: /api/v1/ai/control/START_WORKER/response")
    
    # Test what happens if client submits with wrong action name
    response = test_client.post(
        f"/api/v1/ai/control/start/response",  # Client action name
        json={
            "success": True,
            "action": "START_WORKER",
            "worker_id": worker_id,
            "status": "COMPLETED",
            "request_id": request_id,
            "timestamp": time.time(),
            "details": {},
            "error": None
        },
        headers={"X-API-Key": "test-control-key-456"}
    )
    print(f"  Response to 'start': {response.status_code} - {response.json().get('detail', 'OK')}")
    
    # Test with correct action name
    response2 = test_client.post(
        f"/api/v1/ai/control/START_WORKER/response",
        json={
            "success": True,
            "action": "START_WORKER",
            "worker_id": worker_id,
            "status": "COMPLETED",
            "request_id": request_id,
            "timestamp": time.time(),
            "details": {},
            "error": None
        },
        headers={"X-API-Key": "test-control-key-456"}
    )
    print(f"  Response to 'START_WORKER': {response2.status_code} - {response2.json()}")
    
    print("\n[5] Testing GET_STATUS (not implemented in client)...")
    request_id2 = str(uuid.uuid4())
    test_client.post(
        f"/api/v1/ai/control/GET_STATUS",
        json={
            "request_id": request_id2,
            "action": "GET_STATUS",
            "target": "worker",
            "target_id": worker_id,
            "parameters": {},
            "idempotency_key": str(uuid.uuid4()),
            "created_at": time.time(),
            "expires_at": time.time() + 300
        },
        headers={"X-API-Key": "test-admin-key-789"}
    )
    
    await control_server._poll_commands()
    print(f"  Commands after GET_STATUS: {len(control_server._commands)}")
    
    print("\n" + "=" * 60)
    print("CONTROL CLIENT INTEGRATION SUMMARY")
    print("=" * 60)
    print("""
CRITICAL MISMATCHES FOUND:

1. ACTION NAME MISMATCH
   - Backend: START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS
   - Client:  start, stop, restart, reconfig, pause_camera, resume_camera
   - Result: Client cannot execute ANY backend action

2. POLLING RESPONSE KEY MISMATCH
   - Backend returns: {"worker_id": "...", "requests": [...]}
   - Client expects:  {"commands": [...]}
   - Result: Client always gets empty command list

3. RESPONSE ENDPOINT MISMATCH
   - Client posts to: /api/v1/ai/control/start/response
   - Backend expects: /api/v1/ai/control/START_WORKER/response
   - Result: 400 Invalid Action

4. MISSING ACTIONS IN CLIENT
   - GET_STATUS not implemented in client
   - ENABLE_CAMERA/DISABLE_CAMERA map to pause/resume (semantic mismatch)

CONCLUSION: PipelineEngine control client is NOT COMPATIBLE with backend.
End-to-end control flow BLOCKED until client is fixed.
""")

if __name__ == "__main__":
    asyncio.run(test_control_client_integration())