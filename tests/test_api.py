import asyncio
from app.main import create_app
from fastapi.testclient import TestClient

app = create_app()
client = TestClient(app)

# Test root endpoint
response = client.get('/')
print('Root:', response.status_code, response.json())

# Test liveness
response = client.get('/api/v1/health/live')
print('Liveness:', response.status_code, response.json())

# Test readiness
response = client.get('/api/v1/health/ready')
print('Readiness:', response.status_code, response.json())

# Test system health
response = client.get('/api/v1/health/system')
print('System Health:', response.status_code)
if response.status_code == 200:
    data = response.json()
    print('  Overall:', data['overall_status'])
    print('  Cameras:', list(data['cameras'].keys()))
    print('  GPU:', data['gpu']['gpu_name'])
    print('  Components:', len(data['components']))

# Test camera health
response = client.get('/api/v1/health/cameras')
print('Camera Health:', response.status_code)
if response.status_code == 200:
    data = response.json()
    for cam, info in data.items():
        print('  {}: {} - {}'.format(cam, info['state'], info['message']))

# Test GPU status
response = client.get('/api/v1/health/gpu')
print('GPU Status:', response.status_code)
if response.status_code == 200:
    data = response.json()
    print('  GPU:', data['gpu_name'])
    print('  CUDA EP:', data['cuda_ep_registered'])
    print('  NVDEC:', data['nvdec_available'])

# Test metrics
response = client.get('/api/v1/health/metrics')
print('Metrics:', response.status_code)
if response.status_code == 200:
    data = response.json()
    print('  Camera metrics:', list(data['camera_metrics'].keys()))
    print('  Queue metrics:', data['queue_metrics'])