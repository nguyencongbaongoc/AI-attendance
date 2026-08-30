import urllib.request
import json

# Test SSE endpoint
url = 'http://localhost:11415/api/v1/health/stream'
req = urllib.request.Request(url, headers={'Accept': 'text/event-stream'})
print("Testing SSE endpoint...")

try:
    with urllib.request.urlopen(req, timeout=10) as response:
        print(f"Status: {response.status}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        
        # Read a few events
        data = response.read(2000).decode('utf-8')
        print("Received data:")
        print(data[:1000])
        
        # Parse events
        for line in data.split('\n'):
            if line.startswith('data: '):
                try:
                    event_data = json.loads(line[6:])
                    print(f"Event type: {event_data.get('type')}")
                    print(f"Sequence: {event_data.get('seq')}")
                    print(f"Overall: {event_data.get('overall_status')}")
                    break
                except:
                    pass
                    
    print("SSE test PASSED")
except Exception as e:
    print(f"SSE test FAILED: {e}")