#!/usr/bin/env python3
"""
Enrollment Authorization Regression Tests

Tests the enrollment reload endpoints for proper authorization and behavior.
"""

import os
import sys
import tempfile
import numpy as np
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
print("ENROLLMENT AUTHORIZATION REGRESSION TESTS")
print("=" * 60)

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

# Create test enrollment data
def create_test_enrollment():
    """Create minimal valid enrollment database for testing."""
    enrollment_dir = Path("app/data/enrollment")
    enrollment_dir.mkdir(parents=True, exist_ok=True)
    
    embeddings_path = enrollment_dir / "embeddings.npy"
    metadata_path = enrollment_dir / "embeddings.npy.metadata.json"
    
    # Create dummy embeddings (10 vectors, 512 dim)
    embeddings = np.random.randn(10, 512).astype(np.float32)
    # Normalize
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / norms
    
    np.save(embeddings_path, embeddings)
    
    # Create metadata
    import json
    from datetime import datetime
    
    metadata = {
        "schema_version": "1.0",
        "embedding_dimension": 512,
        "dtype": "float32",
        "normalization": "L2",
        "model_id": "arcface",
        "model_filename": "glintr100.onnx",
        "model_sha256": "test_sha256_123",
        "enrollment_contract_version": "1.0",
        "embedding_count": 10,
        "person_ids": ["person_1", "person_2", "person_3"],
        "sample_provenance": [
            {"person_id": "person_1", "sample_index": i, "quality": 0.9} for i in range(4)
        ] + [
            {"person_id": "person_2", "sample_index": i, "quality": 0.85} for i in range(3)
        ] + [
            {"person_id": "person_3", "sample_index": i, "quality": 0.95} for i in range(3)
        ],
        "creation_timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Created test enrollment: {embeddings_path}, {metadata_path}")

# Clean up test enrollment
def cleanup_test_enrollment():
    enrollment_dir = Path("app/data/enrollment")
    embeddings_path = enrollment_dir / "embeddings.npy"
    metadata_path = enrollment_dir / "embeddings.npy.metadata.json"
    for p in [embeddings_path, metadata_path]:
        if p.exists():
            p.unlink()

# Setup
print("\n--- SETUP ---")
cleanup_test_enrollment()
create_test_enrollment()

print("\n--- AUTHORIZATION TESTS ---")

# Test 1: Missing admin key
test("Missing admin key returns 422", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}).status_code == 422)

# Test 2: Invalid admin key
test("Invalid admin key returns 401", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "wrong"}).status_code == 401)

# Test 3: Valid admin key
test("Valid admin key returns 200", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).status_code == 200)

# Test 4: Worker key rejected
test("Worker key rejected (401)", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-worker-key-123"}).status_code == 401)

# Test 5: Control key rejected
test("Control key rejected (401)", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-control-key-456"}).status_code == 401)

print("\n--- FUNCTIONAL TESTS ---")

# Test 6: Reload success response structure
def test_reload_structure():
    r = test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"})
    if r.status_code != 200:
        return False
    data = r.json()
    required = ["success", "previous_version", "new_version", "persons_loaded", "vectors_loaded", "embedding_dimension", "model_sha256", "error", "preserved_previous", "timestamp"]
    return all(k in data for k in required)

test("Reload response has all required fields", test_reload_structure)

# Test 7: Reload success=True
test("Reload returns success=True", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["success"] == True)

# Test 8: Persons loaded = 3
test("Reload reports 3 persons", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["persons_loaded"] == 3)

# Test 9: Vectors loaded = 10
test("Reload reports 10 vectors", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["vectors_loaded"] == 10)

# Test 10: Embedding dimension = 512
test("Reload reports 512 dimension", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["embedding_dimension"] == 512)

# Test 11: Model SHA256 matches
test("Reload reports correct model_sha256", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["model_sha256"] == "test_sha256_123")

# Test 12: Preserved_previous = False on success
test("Reload preserved_previous=False on success", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["preserved_previous"] == False)

# Test 13: Status endpoint
test("Status endpoint returns 200", lambda: 
    test_client.get("/api/v1/enrollment/reload/status", headers={"X-API-Key": "test-admin-key-789"}).status_code == 200)

# Test 14: Status matches reload
def test_status_matches():
    r1 = test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"})
    r2 = test_client.get("/api/v1/enrollment/reload/status", headers={"X-API-Key": "test-admin-key-789"})
    return r1.json()["new_version"] == r2.json()["new_version"]

test("Status version matches reload version", test_status_matches)

print("\n--- FAILURE BEHAVIOR TESTS ---")

# Test 15: Missing NPY files returns error
cleanup_test_enrollment()
test("Missing NPY returns success=False", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["success"] == False)

test("Missing NPY returns error message", lambda: 
    "not found" in test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["error"].lower())

test("Missing NPY preserved_previous=True", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["preserved_previous"] == True)

# Recreate for remaining tests
create_test_enrollment()

# Test 16: Corrupted metadata
metadata_path = Path("app/data/enrollment/embeddings.npy.metadata.json")
with open(metadata_path, "w") as f:
    f.write("{ invalid json }")

test("Corrupted metadata returns success=False", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["success"] == False)

test("Corrupted metadata preserved_previous=True", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["preserved_previous"] == True)

# Restore valid metadata
create_test_enrollment()

# Test 17: Dimension mismatch
metadata_path = Path("app/data/enrollment/embeddings.npy.metadata.json")
import json
with open(metadata_path, "r") as f:
    meta = json.load(f)
meta["embedding_dimension"] = 256  # Wrong
with open(metadata_path, "w") as f:
    json.dump(meta, f)

test("Dimension mismatch returns success=False", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["success"] == False)

test("Dimension mismatch preserved_previous=True", lambda: 
    test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"}).json()["preserved_previous"] == True)

# Restore
create_test_enrollment()

# Test 18: Expected version check
r = test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual", "expected_version": "wrong_version"}, headers={"X-API-Key": "test-admin-key-789"})
test("Expected version mismatch logs warning (success still True)", lambda: r.json()["success"] == True)

# Test 19: No partial activation on failure
cleanup_test_enrollment()
r = test_client.post("/api/v1/enrollment/reload", json={"trigger": "manual"}, headers={"X-API-Key": "test-admin-key-789"})
test("Failure returns success=False (no partial)", lambda: r.json()["success"] == False)

# Test 20: Status endpoint follows access policy
test("Status requires admin key (401 for worker)", lambda: 
    test_client.get("/api/v1/enrollment/reload/status", headers={"X-API-Key": "test-worker-key-123"}).status_code == 401)

test("Status requires admin key (401 for control)", lambda: 
    test_client.get("/api/v1/enrollment/reload/status", headers={"X-API-Key": "test-control-key-456"}).status_code == 401)

# Cleanup
cleanup_test_enrollment()

print("\n" + "=" * 60)
print("ENROLLMENT REGRESSION TEST SUMMARY")
print("=" * 60)

passed = sum(1 for _, s in results if s == "PASS")
failed = sum(1 for _, s in results if s == "FAIL")
errors = sum(1 for _, s in results if s.startswith("ERROR"))

for name, status in results:
    print(f"  [{status}] {name}")

print(f"\nTotal: {len(results)} | PASS: {passed} | FAIL: {failed} | ERROR: {errors}")

if failed == 0 and errors == 0:
    print("\n✅ ALL TESTS PASSED - Enrollment authorization regression VERIFIED")
else:
    print(f"\n❌ {failed + errors} TESTS FAILED")