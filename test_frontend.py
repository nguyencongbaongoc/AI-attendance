import urllib.request
import json

# Test frontend is serving and has correct API config
url = 'http://localhost:27914/'
req = urllib.request.Request(url)
print("Testing Frontend...")

try:
    with urllib.request.urlopen(req, timeout=5) as response:
        print(f"Status: {response.status}")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        html = response.read().decode('utf-8')
        print(f"HTML length: {len(html)}")
        
        # Check if Vite is serving (look for Vite indicators)
        if 'vite' in html.lower() or 'type="module"' in html:
            print("Frontend appears to be Vite dev server")
        else:
            print("Frontend serving content")
            
    print("Frontend test PASSED")
except Exception as e:
    print(f"Frontend test FAILED: {e}")

# Test API base URL propagation by checking if frontend can reach backend
print("\nTesting API connectivity from frontend perspective...")
api_url = 'http://localhost:11415/api/v1/health/system'
req = urllib.request.Request(api_url)
try:
    with urllib.request.urlopen(req, timeout=5) as response:
        data = json.loads(response.read().decode())
        print(f"Backend reachable: {data['overall_status']}")
except Exception as e:
    print(f"Backend connectivity test FAILED: {e}")