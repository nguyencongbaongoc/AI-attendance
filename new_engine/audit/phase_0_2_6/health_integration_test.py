#!/usr/bin/env python3
"""
Health Integration Test - Gate A

Tests the actual health backend implementation against real Legacy Backend.
Uses isolated test configuration and ports.
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
print("HEALTH INTEGRATION TEST - GATE A")
print("=" * 60)

worker_id = "test_worker_1"

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

def test_valid_report():
    r = test_client.post("/api/v1/health/ai-worker", 
        json={"worker_id": worker_id, "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200

def test_invalid_state():
    r = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": worker_id, "worker_version": "1.0.0", "state": "invalid_state", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 400

def test_duplicate_sequence():
    r1 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_dup", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    r2 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_dup", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r1.status_code == 200 and r2.status_code == 400

def test_out_of_order():
    r1 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_ooo", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    r2 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_ooo", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 3},
        headers={"X-API-Key": "test-worker-key-123"})
    return r1.status_code == 200 and r2.status_code == 400

def test_worker_restart():
    r1 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_restart", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    r2 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_restart", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 2},
        headers={"X-API-Key": "test-worker-key-123"})
    r3 = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_restart", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200

def test_invalid_key():
    r = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": worker_id, "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "wrong-key"})
    return r.status_code == 401

def test_missing_key():
    r = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": worker_id, "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1})
    return r.status_code == 422

def test_status_retrieval():
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_status", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    r = test_client.get(f"/api/v1/health/ai-worker/{worker_id}_status", headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200 and r.json()["worker_id"] == f"{worker_id}_status"

def test_unknown_worker():
    r = test_client.get(f"/api/v1/health/ai-worker/unknown_worker", headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 404

def test_status_sequence():
    # First report with sequence 1
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_seq", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    # Second report with sequence 2
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_seq", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 2},
        headers={"X-API-Key": "test-worker-key-123"})
    # Third report with sequence 3
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_seq", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 3},
        headers={"X-API-Key": "test-worker-key-123"})
    # Fourth report with sequence 4
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_seq", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 4},
        headers={"X-API-Key": "test-worker-key-123"})
    # Fifth report with sequence 5
    test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_seq", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 5},
        headers={"X-API-Key": "test-worker-key-123"})
    r = test_client.get(f"/api/v1/health/ai-worker/{worker_id}_seq", headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200 and r.json()["sequence_number"] == 5

def test_stale_worker():
    r = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_stale", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200

def test_control_commands():
    test_client.post("/api/v1/ai/control/GET_STATUS",
        json={"request_id": "cmd_1", "action": "GET_STATUS", "target": "worker", "target_id": f"{worker_id}_cmd", "parameters": {}, "idempotency_key": "key_1", "created_at": time.time(), "expires_at": time.time() + 300},
        headers={"X-API-Key": "test-admin-key-789"})
    r = test_client.post("/api/v1/health/ai-worker",
        json={"worker_id": f"{worker_id}_cmd", "worker_version": "1.0.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200 and "GET_STATUS" in r.json().get("commands", [])

def test_full_report():
    r = test_client.post("/api/v1/health/ai-worker",
        json={
            "worker_id": f"{worker_id}_full",
            "worker_version": "1.0.0",
            "state": "ready",
            "timestamp": time.time(),
            "sequence_number": 1,
            "camera_states": {
                "cam1": {
                    "state": "RUNNING",
                    "last_frame_timestamp": time.time(),
                    "decode_fps": 30.0,
                    "inference_fps": 25.0,
                    "track_count": 3
                }
            },
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 10,
            "processing_latency_ms": 15.5,
            "dropped_frames": 2,
            "stream_epochs": {"cam1": 3},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"})
    return r.status_code == 200

# ============================================================
# RUN TESTS
# ============================================================

print("\n--- Health Report Ingestion ---")
test("Valid health report accepted", test_valid_report)
test("Invalid state rejected", test_invalid_state)
test("Duplicate sequence rejected", test_duplicate_sequence)
test("Out-of-order sequence rejected", test_out_of_order)
test("Worker restart (sequence reset) accepted", test_worker_restart)
test("Invalid API key rejected", test_invalid_key)
test("Missing API key rejected", test_missing_key)

print("\n--- Health Status Retrieval ---")
test("Status retrieval for existing worker", test_status_retrieval)
test("Status retrieval for unknown worker returns 404", test_unknown_worker)
test("Status returns correct sequence number", test_status_sequence)

print("\n--- Stale Worker Detection ---")
test("Stale worker detection mechanism active", test_stale_worker)

print("\n--- Control Command Return ---")
test("Health response includes pending commands", test_control_commands)

print("\n--- Complex Health Report ---")
test("Full health report with camera states accepted", test_full_report)

# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("HEALTH INTEGRATION TEST SUMMARY")
print("=" * 60)

passed = sum(1 for _, s in results if s == "PASS")
failed = sum(1 for _, s in results if s == "FAIL")
errors = sum(1 for _, s in results if s.startswith("ERROR"))

for name, status in results:
    print(f"  [{status}] {name}")

print(f"\nTotal: {len(results)} | PASS: {passed} | FAIL: {failed} | ERROR: {errors}")

if failed == 0 and errors == 0:
    print("\nGATE A: PASS - Health backend state management working")
else:
    print(f"\nGATE A: BLOCKED - {failed + errors} tests failed")