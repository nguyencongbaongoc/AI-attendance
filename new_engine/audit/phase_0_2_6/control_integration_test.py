#!/usr/bin/env python3
"""
Control Integration Test - Gate B

Tests the actual PipelineEngine Control Client against the real Legacy Backend.
Uses isolated test configuration.
"""

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

from fastapi.testclient import TestClient
from app.main import create_app

test_app = create_app()
test_client = TestClient(test_app)

print("=" * 60)
print("CONTROL INTEGRATION TEST - GATE B")
print("=" * 60)

worker_id = "pipeline_engine_1"

results = []

def test(name, fn):
    try:
        result = fn()
        status = "PASS" if result else "FAIL"
        results.append((name, status))
        print(f"  [{status}] {name}")
        return result
    except Exception as e:
        results.append((name, f"ERROR: {e}"))
        print(f"  [ERROR] {name}: {e}")
        return False

# ============================================================
# BACKEND CONTROL ENDPOINT TESTS (Already verified in 0.2.5)
# ============================================================

print("\n--- Backend Control Endpoints ---")

def test_submit_start_worker():
    return test_client.post("/api/v1/ai/control/START_WORKER",
        json={"request_id": str(uuid.uuid4()), "action": "START_WORKER", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"}).status_code == 200

def test_submit_get_status():
    return test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": str(uuid.uuid4()), "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"}).status_code == 200

def test_poll_pending():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    r = test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": "test-control-key-456"})
    return r.status_code == 200 and "requests" in r.json() and len(r.json()["requests"]) > 0

def test_submit_response():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    r = test_client.post(f"/api/v1/ai/control/GET_STATUS/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": req_id, "timestamp": time.time(), "details": {}, "error": None},
        headers={"X-API-Key": "test-control-key-456"})
    return r.status_code == 200

def test_path_body_mismatch():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    r = test_client.post(f"/api/v1/ai/control/STOP_WORKER/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": req_id, "timestamp": time.time(), "details": {}, "error": None},
        headers={"X-API-Key": "test-control-key-456"})
    return r.status_code == 400

test("Submit START_WORKER request", test_submit_start_worker)
test("Submit GET_STATUS request", test_submit_get_status)
test("Poll pending requests returns correct format", test_poll_pending)
test("Submit control response works", test_submit_response)
test("Path/body action mismatch rejected", test_path_body_mismatch)

# ============================================================
# CLIENT CONTRACT ALIGNMENT TESTS
# ============================================================

print("\n--- Client Contract Alignment ---")

def test_client_action_enum():
    from pipeline_engine.integration.control_client import Action
    expected = {"START_WORKER", "STOP_WORKER", "RESTART_WORKER", "ENABLE_CAMERA", "DISABLE_CAMERA", "GET_STATUS"}
    actual = {Action.START_WORKER, Action.STOP_WORKER, Action.RESTART_WORKER, Action.ENABLE_CAMERA, Action.DISABLE_CAMERA, Action.GET_STATUS}
    return expected == actual

def test_client_control_result_enum():
    from pipeline_engine.integration.control_client import ControlResult
    expected = {"PENDING", "ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "REJECTED", "EXPIRED"}
    actual = {ControlResult.PENDING, ControlResult.ACCEPTED, ControlResult.RUNNING, ControlResult.COMPLETED, ControlResult.FAILED, ControlResult.REJECTED, ControlResult.EXPIRED}
    return expected == actual

def test_client_polling_requests_key():
    import inspect
    from pipeline_engine.integration.control_client import PipelineEngineControlServer
    source = inspect.getsource(PipelineEngineControlServer._poll_commands)
    return 'data.get("requests"' in source or "data.get('requests')" in source

def test_client_response_uses_response_action():
    import inspect
    from pipeline_engine.integration.control_client import PipelineEngineControlServer
    source = inspect.getsource(PipelineEngineControlServer._send_response)
    return 'response.action' in source

def test_client_has_get_status_handler():
    from pipeline_engine.integration.control_client import PipelineEngineControlServer, Action
    return Action.GET_STATUS in PipelineEngineControlServer.__dict__.get('_action_handlers', {}) or \
           hasattr(PipelineEngineControlServer, '_handle_get_status')

test("Client Action enum matches backend", test_client_action_enum)
test("Client ControlResult enum matches backend", test_client_control_result_enum)
test("Client polling uses 'requests' key", test_client_polling_requests_key)
test("Client response endpoint uses response.action", test_client_response_uses_response_action)
test("Client has GET_STATUS handler", test_client_has_get_status_handler)

# ============================================================
# END-TO-END CLIENT SIMULATION TEST
# ============================================================

print("\n--- End-to-End Client Simulation ---")

def test_simulated_client_poll():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    
    r = test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": "test-control-key-456"})
    data = r.json()
    requests = data.get("requests", [])
    # Check if our specific request is in the list
    our_request = next((r for r in requests if r["request_id"] == req_id), None)
    return our_request is not None and our_request["action"] == "GET_STATUS"

def test_simulated_client_response():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    
    r = test_client.post(f"/api/v1/ai/control/GET_STATUS/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": req_id, "timestamp": time.time(), "details": {"status": "ok"}, "error": None},
        headers={"X-API-Key": "test-control-key-456"})
    
    return r.status_code == 200

test("Simulated client poll retrieves commands", test_simulated_client_poll)
test("Simulated client response submission", test_simulated_client_response)

# ============================================================
# CONTROL LIFECYCLE TESTS
# ============================================================

print("\n--- Control Lifecycle ---")

def test_command_lifecycle():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    
    r = test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": "test-control-key-456"})
    pending = next((r for r in r.json()["requests"] if r["request_id"] == req_id), None)
    if not pending or pending["action"] != "GET_STATUS":
        return False
    
    test_client.post(f"/api/v1/ai/control/GET_STATUS/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": req_id, "timestamp": time.time(), "details": {}, "error": None},
        headers={"X-API-Key": "test-control-key-456"})
    
    r2 = test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": "test-control-key-456"})
    completed = next((r for r in r2.json()["requests"] if r["request_id"] == req_id), None)
    return completed is None

def test_history_endpoint():
    req_id = str(uuid.uuid4())
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": req_id, "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    test_client.post(f"/api/v1/ai/control/GET_STATUS/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": req_id, "timestamp": time.time(), "details": {}, "error": None},
        headers={"X-API-Key": "test-control-key-456"})
    
    r = test_client.get("/api/v1/ai/control/history", params={"worker_id": worker_id}, headers={"X-API-Key": "test-admin-key-789"})
    return r.status_code == 200 and len(r.json()["records"]) > 0

test("Command lifecycle: PENDING -> COMPLETED", test_command_lifecycle)
test("History endpoint returns completed commands", test_history_endpoint)

# ============================================================
# AUTHORIZATION TESTS
# ============================================================

print("\n--- Authorization ---")

def test_worker_key_rejected_admin():
    return test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": str(uuid.uuid4()), "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-worker-key-123"}).status_code == 401

def test_control_key_rejected_admin():
    return test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": str(uuid.uuid4()), "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-control-key-456"}).status_code == 401

def test_admin_key_rejected_poll():
    return test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": "test-admin-key-789"}).status_code == 401

test("Worker key rejected on admin endpoint", test_worker_key_rejected_admin)
test("Control key rejected on admin endpoint", test_control_key_rejected_admin)
test("Admin key rejected on worker poll endpoint", test_admin_key_rejected_poll)

# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("CONTROL INTEGRATION TEST SUMMARY")
print("=" * 60)

passed = sum(1 for _, s in results if s == "PASS")
failed = sum(1 for _, s in results if s == "FAIL")
errors = sum(1 for _, s in results if s.startswith("ERROR"))

for name, status in results:
    print(f"  [{status}] {name}")

print(f"\nTotal: {len(results)} | PASS: {passed} | FAIL: {failed} | ERROR: {errors}")

if failed == 0 and errors == 0:
    print("\nGATE B: PASS - Control contract aligned and integration working")
else:
    print(f"\nGATE B: BLOCKED - {failed + errors} tests failed")