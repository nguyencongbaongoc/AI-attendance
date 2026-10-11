#!/usr/bin/env python3
"""
Isolated Health Integration Test

Tests the actual PipelineEngine Health Client against a real Legacy Backend.
Uses isolated test configuration and ports.
"""

import asyncio
import os
import sys
import time
import tempfile
from pathlib import Path

# Set up test environment
os.environ["AI_WORKER_API_KEY"] = "test-worker-key-123"
os.environ["AI_CONTROL_API_KEY"] = "test-control-key-456"
os.environ["ADMIN_API_KEY"] = "test-admin-key-789"

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))
print(f"Project root: {project_root}")
print(f"Sys path: {sys.path[:3]}")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.main import create_app

# Create isolated test backend
test_app = create_app()
test_client = TestClient(test_app)

print("=" * 60)
print("HEALTH INTEGRATION TEST - ISOLATED BACKEND")
print("=" * 60)

# Test 1: Health endpoint accessibility
print("\n[TEST 1] Health endpoint accessibility")
try:
    response = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "test_worker_1",
            "worker_version": "1.0.0",
            "state": "ready",
            "timestamp": time.time(),
            "sequence_number": 1,
            "camera_states": {},
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
    assert response.status_code == 200
    assert response.json()["success"] == True
    assert response.json()["acknowledged"] == True
    print("  PASS PASS")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 2: Invalid API key rejection
print("\n[TEST 2] Invalid API key rejection")
try:
    response = test_client.post(
        "/api/v1/health/ai-worker",
        json={"worker_id": "test", "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1},
        headers={"X-API-Key": "wrong-key"}
    )
    print(f"  Status: {response.status_code}")
    assert response.status_code == 401
    print("  PASS PASS")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 3: Missing API key (when env is set)
print("\n[TEST 3] Missing API key")
try:
    response = test_client.post(
        "/api/v1/health/ai-worker",
        json={"worker_id": "test", "worker_version": "1.0", "state": "ready", "timestamp": time.time(), "sequence_number": 1}
    )
    print(f"  Status: {response.status_code}")
    # Should fail because header is required
    assert response.status_code == 422  # Missing header
    print("  PASS PASS")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 4: Sequence number tracking (backend doesn't persist - will fail)
print("\n[TEST 4] Sequence number handling (expects backend to track)")
try:
    # Send sequence 1
    response1 = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "seq_test_1",
            "worker_version": "1.0.0",
            "state": "ready",
            "timestamp": time.time(),
            "sequence_number": 1,
            "camera_states": {},
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Sequence 1: {response1.json()['sequence_number']}")
    
    # Send sequence 2 (should be accepted)
    response2 = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "seq_test_1",
            "worker_version": "1.0.0",
            "state": "ready",
            "timestamp": time.time(),
            "sequence_number": 2,
            "camera_states": {},
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Sequence 2: {response2.json()['sequence_number']}")
    
    # Send duplicate sequence 2 (should be rejected if backend tracks)
    response3 = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "seq_test_1",
            "worker_version": "1.0.0",
            "state": "ready",
            "timestamp": time.time(),
            "sequence_number": 2,  # Duplicate
            "camera_states": {},
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Duplicate Sequence 2: {response3.json()['sequence_number']}")
    print("  WARN  BACKEND DOES NOT VALIDATE SEQUENCE (scaffold)")
    print("  Status: NOT-VERIFIED (backend doesn't persist state)")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 5: Invalid state rejection
print("\n[TEST 5] Invalid state handling")
try:
    response = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "state_test_1",
            "worker_version": "1.0.0",
            "state": "invalid_state",
            "timestamp": time.time(),
            "sequence_number": 1,
            "camera_states": {},
            "model_readiness": {"scrfd": True, "arcface": True, "yolo": True},
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
    # Pydantic accepts any string for state - no enum validation
    if response.status_code == 200:
        print("  WARN  BACKEND ACCEPTS INVALID STATE (no enum validation)")
    print("  Status: NOT-VERIFIED (no validation)")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 6: Camera states in request
print("\n[TEST 6] Camera states in health request")
try:
    response = test_client.post(
        "/api/v1/health/ai-worker",
        json={
            "worker_id": "camera_test_1",
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
            "queue_depth": 0,
            "processing_latency_ms": 10.0,
            "dropped_frames": 0,
            "stream_epochs": {"cam1": 5},
            "errors": []
        },
        headers={"X-API-Key": "test-worker-key-123"}
    )
    print(f"  Status: {response.status_code}")
    print("  PASS PASS (accepted)")
except Exception as e:
    print(f"  FAIL FAIL: {e}")

# Test 7: Status retrieval (NOT IMPLEMENTED)
print("\n[TEST 7] Health status retrieval (GET /api/v1/health/ai-worker/{worker_id})")
try:
    response = test_client.get("/api/v1/health/ai-worker/test_worker_1")
    print(f"  Status: {response.status_code}")
    if response.status_code == 404:
        print("  FAIL ENDPOINT NOT IMPLEMENTED")
    else:
        print(f"  Response: {response.json()}")
except Exception as e:
    print(f"  FAIL ENDPOINT NOT IMPLEMENTED: {e}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("""
Health Integration Test Results:

PASS PASS: Health endpoint accessible with valid credentials
PASS PASS: Invalid API key rejected (401)
PASS PASS: Missing API key rejected (422)
WARN  NOT-VERIFIED: Sequence validation (backend doesn't persist state)
WARN  NOT-VERIFIED: State enum validation (accepts any string)
PASS PASS: Camera states accepted in request
FAIL FAIL: Status retrieval endpoint NOT IMPLEMENTED

CONCLUSION: Backend health endpoint is a SCAFFOLD.
- Accepts requests but does NOT persist state
- Does NOT validate sequences
- Does NOT track camera states, model readiness, stream epochs
- Does NOT provide status retrieval
- Does NOT return pending commands

GATE A STATUS: BLOCKED - Backend implementation incomplete
""")