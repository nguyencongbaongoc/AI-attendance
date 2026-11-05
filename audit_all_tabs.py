import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('frontend/index.html', encoding='utf-8') as f:
    content = f.read()

for m in re.finditer(r'<([a-zA-Z0-9]+)[^>]*id=["\'](page-[^"\']+)["\']', content):
    tag = m.group(1)
    page_id = m.group(2)
    start = m.start()
    print(f"Tag: <{tag}> id='{page_id}' at pos {start}")

