"""Check SHA256 hashes of model files."""
import hashlib
import os
from pathlib import Path

# Expected hashes from registry
EXPECTED = {
    "models/scrfd/scrfd_10g_bnkps.onnx": "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
    "models/arcface/glintr100.onnx": "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf",
    "models/landmark/1k3d68.onnx": "df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc",
    "models/reid/resnet50_reid.onnx": "09d398902020205dd4aa80495b2a8fceecd64ba610e6b72afc1f93965c9613d2",
    "models/yolo/yolo11n.pt": "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1",
    "models/yolo/yolo11n-pose.pt": "869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0",
}

# Alternative paths (files may be in different locations)
ALTERNATIVE_PATHS = {
    "models/glintr100.onnx": "models/arcface/glintr100.onnx",
    "models/1k3d68.onnx": "models/landmark/1k3d68.onnx",
    "models/resnet50_reid.onnx": "models/reid/resnet50_reid.onnx",
}

def compute_sha256(filepath: str) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def main():
    print("=" * 80)
    print("MODEL FILE HASH VERIFICATION")
    print("=" * 80)
    
    results = []
    
    for registry_path, expected_hash in EXPECTED.items():
        # Check primary path
        if os.path.exists(registry_path):
            actual_hash = compute_sha256(registry_path)
            size = os.path.getsize(registry_path)
            match = actual_hash == expected_hash
            status = "VERIFIED" if match else "HASH_MISMATCH"
            results.append({
                "path": registry_path,
                "expected": expected_hash,
                "actual": actual_hash,
                "size": size,
                "status": status,
                "match": match,
            })
        else:
            # Check alternative path
            alt_path = ALTERNATIVE_PATHS.get(registry_path)
            if alt_path and os.path.exists(alt_path):
                actual_hash = compute_sha256(alt_path)
                size = os.path.getsize(alt_path)
                match = actual_hash == expected_hash
                status = "VERIFIED (alt path)" if match else "HASH_MISMATCH (alt path)"
                results.append({
                    "path": alt_path,
                    "expected": expected_hash,
                    "actual": actual_hash,
                    "size": size,
                    "status": status,
                    "match": match,
                })
            else:
                results.append({
                    "path": registry_path,
                    "expected": expected_hash,
                    "actual": None,
                    "size": None,
                    "status": "MISSING",
                    "match": False,
                })
    
    # Print results
    for r in results:
        print(f"\nPath: {r['path']}")
        print(f"Status: {r['status']}")
        print(f"Expected: {r['expected']}")
        print(f"Actual: {r['actual']}")
        print(f"Size: {r['size']}")
        print(f"Match: {r['match']}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    verified = sum(1 for r in results if r['match'])
    mismatch = sum(1 for r in results if r['status'].startswith("HASH_MISMATCH"))
    missing = sum(1 for r in results if r['status'] == "MISSING")
    
    print(f"Verified: {verified}/6")
    print(f"Mismatch: {mismatch}")
    print(f"Missing: {missing}")
    
    return results

if __name__ == "__main__":
    main()