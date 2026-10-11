import httpx
import time
time.sleep(3)
try:
    resp = httpx.get('http://localhost:9997/api/paths', timeout=3.0)
    print(f'MediaMTX API: {resp.status_code}')
    data = resp.json()
    for item in data.get('items', []):
        print(f'  Path: {item.get("name")}, Readers: {item.get("readers", 0)}')
except Exception as e:
    print(f'Error: {e}')