import urllib.request
import json

# Test backend health
url = 'http://localhost:11415/api/v1/health/system'
req = urllib.request.Request(url)
with urllib.request.urlopen(req, timeout=5) as response:
    data = json.loads(response.read().decode())
    print('=== SYSTEM HEALTH ===')
    print(f'Overall: {data["overall_status"]}')
    print(f'Components: {len(data["components"])}')
    for c in data['components']:
        print(f'  {c["component"]}: {c["status"]} - {c["message"]}')
    print(f'Cameras: {list(data["cameras"].keys())}')
    print(f'GPU: {data["gpu"]["gpu_name"]}')
    print(f'CUDA Available: {data["gpu"]["torch_cuda_available"]}')