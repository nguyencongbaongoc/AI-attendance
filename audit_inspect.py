import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
with open('frontend/index.html', encoding='utf-8') as f:
    c = f.read()

print("--- NAV BUTTONS ---")
for m in re.finditer(r'<button[^>]*nav-btn[^>]*>[\s\S]*?</button>', c):
    tag = m.group(0)
    # print tag attributes and inner text
    dp = re.search(r'data-page="([^"]*)"', tag)
    text = re.sub(r'<[^>]+>', ' ', tag).strip()
    print(f"data-page: {dp.group(1) if dp else 'NONE'} | text: {text}")

print("\n--- ONPAGE SWITCH CASES ---")
switch_block = re.search(r'async function onPageSwitch\([\s\S]*?switch\s*\([^\)]+\)\s*\{([\s\S]*?)\}\s*\}', c)
if switch_block:
    cases = re.findall(r'case\s+["\']([^"\']+)["\']', switch_block.group(1))
    print("onPageSwitch cases:", cases)
else:
    print("Could not find onPageSwitch cases")

