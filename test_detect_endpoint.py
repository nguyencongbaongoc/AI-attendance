import urllib.request
import uuid
import json

boundary = uuid.uuid4().hex
with open('photo_realistic_face.jpg', 'rb') as f:
    img_data = f.read()

part1 = (
    f'--{boundary}\r\n'
    'Content-Disposition: form-data; name="image"; filename="photo_realistic_face.jpg"\r\n'
    'Content-Type: image/jpeg\r\n\r\n'
).encode('utf-8')
part2 = f'\r\n--{boundary}--\r\n'.encode('utf-8')
body = part1 + img_data + part2

req = urllib.request.Request(
    'http://localhost:8000/api/v1/enrollment/detect',
    data=body,
    headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'X-API-Key': 'dev_admin_key_2026'
    },
    method='POST'
)

with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    print('HTTP', resp.status)
    print('detected:', data.get('detected'))
    print('confidence:', data.get('confidence'))
    print('crop_data_url length:', len(data.get('crop_data_url', '')))
    print('embedding length:', len(data.get('embedding', [])))
