import httpx
resp = httpx.get('http://localhost:9997/v3/paths/list', timeout=3.0)
data = resp.json()
for item in data.get('items', []):
    print(f'{item["name"]}: ready={item["ready"]}, online={item["online"]}')