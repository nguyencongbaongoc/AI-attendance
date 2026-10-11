import httpx
import time
time.sleep(2)
try:
    resp = httpx.get('http://localhost:9997/v3/paths/list', timeout=3.0)
    data = resp.json()
    for item in data.get('items', []):
        print(f'Path: {item.get("name")}')
        print(f'  Ready: {item.get("ready")}')
        print(f'  Available: {item.get("available")}')
        print(f'  Online: {item.get("online")}')
        source = item.get('source', {})
        print(f'  Source: {source.get("type")} ({source.get("id")})')
        tracks = item.get('tracks', [])
        print(f'  Tracks: {tracks}')
        tracks2 = item.get('tracks2', [])
        for t in tracks2:
            print(f'    Codec: {t.get("codec")}, Props: {t.get("codecProps")}')
        print()
except Exception as e:
    print(f'Error: {e}')