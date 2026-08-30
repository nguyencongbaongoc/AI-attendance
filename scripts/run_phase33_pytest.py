import sys
import os
import subprocess

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Run the unit tests directly
result = subprocess.run(
    [sys.executable, "-m", "pytest", 
     "tests/unit/test_streaming_health.py",
     "tests/unit/test_streaming_health_events.py",
     "tests/unit/test_streaming_contracts.py",
     "tests/unit/test_streaming_mediamtx.py",
     "-v", "--tb=short"],
    capture_output=True,
    text=True,
    timeout=300,
)

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nExit code: {result.returncode}")
print(f"PASSED: {result.returncode == 0}")