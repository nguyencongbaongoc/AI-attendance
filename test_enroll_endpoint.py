import urllib.request
import uuid
import json

boundary = uuid.uuid4().hex
with open('photo_realistic_face.jpg', 'rb') as f:
    img_data = f.read()

def form_field(name, val):
    return (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f'{val}\r\n'
    ).encode('utf-8')

body = (
    form_field('student_id', 'TEST001') +
    form_field('person_id', 'TEST001') +
    form_field('name', 'Test Student') +
    form_field('student_class', '10A1') +
    form_field('role', 'student') +
    f'--{boundary}\r\n'
    'Content-Disposition: form-data; name="image"; filename="photo_realistic_face.jpg"\r\n'
    'Content-Type: image/jpeg\r\n\r\n'.encode('utf-8') +
    img_data +
    f'\r\n--{boundary}--\r\n'.encode('utf-8')
)

req = urllib.request.Request(
    'http://localhost:8000/api/v1/enrollment/persons',
    data=body,
    headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'X-API-Key': 'dev_admin_key_2026'
    },
    method='POST'
)

try:
    with urllib.request.urlopen(req) as resp:
        print('HTTP', resp.status)
        data = json.loads(resp.read().decode('utf-8'))
        print('Response:', data)
except urllib.error.HTTPError as e:
    print('HTTP Error', e.code, e.read().decode('utf-8'))

