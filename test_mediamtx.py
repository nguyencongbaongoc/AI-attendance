import urllib.request
import json

# Test MediaMTX API
url = 'http://localhost:9997/v3/paths/list'
req = urllib.request.Request(url)
print("Testing MediaMTX API...")

try:
    with urllib.request.urlopen(req, timeout=5) as response:
        print(f"Status: {response.status}")
        data = json.loads(response.read().decode())
        print(f"Paths: {len(data.get('items', []))}")
        for item in data.get('items', []):
            print(f"  {item.get('name')}: {item.get('ready', False)}")
    print("MediaMTX API test PASSED")
except Exception as e:
    print(f"MediaMTX API test FAILED: {e}")

# Test RTMP port
import socket
print("\nTesting RTMP port 1935...")
try:
    sock = socket.create_connection(('localhost', 1935), timeout=3)
    sock.close()
    print("RTMP port 1935: OPEN")
except Exception as e:
    print(f"RTMP port 1935: CLOSED - {e}")

# Test RTSP port
print("\nTesting RTSP port 8554...")
try:
    sock = socket.create_connection(('localhost', 8554), timeout=3)
    sock.close()
    print("RTSP port 8554: OPEN")
except Exception as e:
    print(f"RTSP port 8554: CLOSED - {e}")