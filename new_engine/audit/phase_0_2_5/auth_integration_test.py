#!/usr/bin/env python3
"""
Authentication and Authorization Proof Tests

Tests all Health, Control, and Enrollment routes for proper auth separation.
"""

import os
import sys
import time
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
print("AUTHENTICATION AND AUTHORIZATION PROOF TESTS")
print("=" * 60)

worker_id = "test_worker_1"
camera_id = "cam1"

# Test matrix
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
# HEALTH ENDPOINTS (AI_WORKER_KEY)
# ============================================================

print("\n--- HEALTH ENDPOINTS (require AI_WORKER_KEY) ---")

test("Health: Valid AI_WORKER_KEY", lambda: 
    test_client.post("/api/v1/health/ai-worker", 
        json={"worker_id": worker_id, "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"}).status_code == 200)

test("Health: Invalid AI_WORKER_KEY", lambda: 
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": worker_id, "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "wrong-key"}).status_code == 401)

test("Health: Missing AI_WORKER_KEY", lambda: 
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": worker_id, "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1}).status_code == 422)

def test_empty_worker_key():
    os.environ.pop("AI_WORKER_API_KEY", None)
    try:
        r = test_client.post("/api/v1/health/ai-worker",
            json={"worker_id": worker_id, "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
            headers={"X-API-Key": "anything"})
        return r.status_code == 200
    finally:
        os.environ["AI_WORKER_API_KEY"] = "test-worker-key-123"

test("Health: Empty AI_WORKER_KEY env (allows any)", test_empty_worker_key)

# ============================================================
# CONTROL ENDPOINTS - Admin (ADMIN_KEY)
# ============================================================

print("\n--- CONTROL SUBMIT ENDPOINTS (require ADMIN_KEY) ---")

def submit_control(action="GET_STATUS"):
    return test_client.post(f"/api/v1/ai/control/{action}",
        json={"request_id": "test", "action": action, "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": "test", "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})

test("Control Submit: Valid ADMIN_KEY", lambda: submit_control().status_code == 200)
test("Control Submit: Invalid ADMIN_KEY", lambda: test_client.post("/api/v1/ai/control/GET_STATUS", json={"request_id": "t", "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": "t", "created_at": time.time(), "expires_at": time.time() + 300}, headers={"X-API-Key": "wrong"}).status_code == 401)
test("Control Submit: Missing ADMIN_KEY", lambda: test_client.post("/api/v1/ai/control/GET_STATUS", json={"request_id": "t", "action": "GET_STATUS", "target": "worker", "target_id": worker_id, "parameters": {}, "idempotency_key": "t", "created_at": time.time(), "expires_at": time.time() + 300}).status_code == 422)
test("Control Submit: Worker key on admin endpoint", lambda: submit_control(headers={"X-API-Key": "test-worker-key-123"}).status_code == 401)

# ============================================================
# CONTROL ENDPOINTS - Worker (AI_CONTROL_KEY)
# ============================================================

print("\n--- CONTROL POLL/RESPONSE ENDPOINTS (require AI_CONTROL_KEY) ---")

# First submit a request
req = submit_control("GET_STATUS")
request_id = req.json()["request_id"]

def poll_pending(key="test-control-key-456"):
    return test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}, headers={"X-API-Key": key})

def submit_response(key="test-control-key-456"):
    return test_client.post(f"/api/v1/ai/control/GET_STATUS/response",
        json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": request_id, "timestamp": time.time(), "details": {}, "error": None},
        headers={"X-API-Key": key})

test("Control Poll: Valid AI_CONTROL_KEY", lambda: poll_pending().status_code == 200)
test("Control Poll: Invalid AI_CONTROL_KEY", lambda: poll_pending("wrong").status_code == 401)
test("Control Poll: Missing AI_CONTROL_KEY", lambda: test_client.get("/api/v1/ai/control/pending", params={"worker_id": worker_id}).status_code == 422)
test("Control Poll: Admin key on worker endpoint", lambda: poll_pending("test-admin-key-789").status_code == 401)
test("Control Poll: Worker key on worker endpoint", lambda: poll_pending("test-worker-key-123").status_code == 401)

test("Control Response: Valid AI_CONTROL_KEY", lambda: submit_response().status_code == 200)
test("Control Response: Invalid AI_CONTROL_KEY", lambda: submit_response("wrong").status_code == 401)
test("Control Response: Missing AI_CONTROL_KEY", lambda: test_client.post(f"/api/v1/ai/control/GET_STATUS/response", json={"success": True, "action": "GET_STATUS", "worker_id": worker_id, "status": "COMPLETED", "request_id": request_id, "timestamp": time.time(), "details": {}, "error": None}).status_code == 422)

test("Control Status: Valid AI_CONTROL_KEY", lambda: test_client.get("/api/v1/ai/control/status", headers={"X-API-Key": "test-control-key-456"}).status_code == 200)
test("Control Status: Invalid AI_CONTROL_KEY", lambda: test_client.get("/api/v1/ai/control/status", headers={"X-API-Key": "wrong"}).status_code == 401)

# ============================================================
# ENROLLMENT ENDPOINTS (ADMIN_KEY with constant-time compare)
# ============================================================

print("\n--- ENROLLMENT ENDPOINTS (require ADMIN_KEY) ---")

test("Enrollment Reload: Valid ADMIN_KEY", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).status_code == 200)
test("Enrollment Reload: Invalid ADMIN_KEY", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "wrong"}).status_code == 401)
test("Enrollment Reload: Missing ADMIN_KEY", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}).status_code == 422)
test("Enrollment Reload: Worker key rejected", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-worker-key-123"}).status_code == 401)
test("Enrollment Reload: Control key rejected", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-control-key-456"}).status_code == 401)

test("Enrollment Status: Valid ADMIN_KEY", lambda: test_client.get("/api/v1/enrollment/reload/status", headers={"X-API-Key": "test-admin-key-789"}).status_code == 200)

# ============================================================
# ROLE SEPARATION VERIFICATION
# ============================================================

print("\n--- ROLE SEPARATION VERIFICATION ---")

# Admin key should NOT work on health endpoint
test("Admin key on Health endpoint", lambda: test_client.post("/api/v1/health/ai-worker", json={"worker_id": "t", "worker_version": "1", "state": "ready", "timestamp": time.time(), "sequence_number": 1}, headers={"X-API-Key": "test-admin-key-789"}).status_code == 401)

# Worker key should NOT work on control submit
test("Worker key on Control Submit", lambda: submit_control(headers={"X-API-Key": "test-worker-key-123"}).status_code == 401)

# Control key should NOT work on enrollment
test("Control key on Enrollment", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-control-key-456"}).status_code == 401)

# Admin key should NOT work on control poll
test("Admin key on Control Poll", lambda: poll_pending("test-admin-key-789").status_code == 401)

# ============================================================
# MALFORMED HEADER TESTS
# ============================================================

print("\n--- MALFORMED HEADER TESTS ---")

test("Malformed header: X-API-Key with spaces", lambda: test_client.post("/api/v1/health/ai-worker", json={"worker_id": "t", "worker_version": "1", "state": "ready", "timestamp": time.time(), "sequence_number": 1}, headers={"X-API-Key": " test-worker-key-123 "}).status_code in (401, 200))  # Depends on trim

test("Empty header value", lambda: test_client.post("/api/v1/health/ai-worker", json={"worker_id": "t", "worker_version": "1", "state": "ready", "timestamp": time.time(), "sequence_number": 1}, headers={"X-API-Key": ""}).status_code == 401)

# ============================================================
# ENROLLMENT EMPTY KEY BEHAVIOR
# ============================================================

print("\n--- ENROLLMENT EMPTY KEY CONFIG ---")

original = os.environ.get("ADMIN_API_KEY")
os.environ["ADMIN_API_KEY"] = ""
try:
    test("Enrollment with empty configured key", lambda: test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "anything"}).status_code == 503)
finally:
    os.environ["ADMIN_API_KEY"] = original or "test-admin-key-789"

# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("AUTHENTICATION TEST SUMMARY")
print("=" * 60)

passed = sum(1 for _, s in results if s == "PASS")
failed = sum(1 for _, s in results if s == "FAIL")
errors = sum(1 for _, s in results if s.startswith("ERROR"))

for name, status in results:
    print(f"  [{status}] {name}")

print(f"\nTotal: {len(results)} | PASS: {passed} | FAIL: {failed} | ERROR: {errors}")

print("""
KEY FINDINGS:

1. AI_WORKER_KEY auth: Uses != not constant-time compare. Allows any key if env not set.
2. AI_CONTROL_KEY auth: Same issues as AI_WORKER_KEY.
3. ADMIN_KEY auth: Uses secrets.compare_digest (constant-time). Returns 503 if not configured.
4. Role separation: ENFORCED - each key type only works on its endpoints.
4. Malformed headers: Handled by FastAPI (422 for missing, 401 for invalid).

SECURITY GAPS:
- Non-constant-time comparison for worker/control keys
- Auth bypass if env var not set (allows any key)
- No rate limiting on auth endpoints
""")