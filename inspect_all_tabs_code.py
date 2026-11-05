import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('frontend/index.html', encoding='utf-8') as f:
    content = f.read()

tabs = ['dashboard', 'live', 'arcface', 'video', 'health', 'records', 'worker', 'students']

sections = {}
for i in range(len(tabs)):
    tab = tabs[i]
    start_str = f'id="page-{tab}"'
    start_pos = content.find(start_str)
    if start_pos == -1:
        start_str = f"id='page-{tab}'"
        start_pos = content.find(start_str)
    
    if i < len(tabs) - 1:
        next_tab = tabs[i+1]
        next_str = f'id="page-{next_tab}"'
        end_pos = content.find(next_str)
        if end_pos == -1:
            next_str = f"id='page-{next_tab}'"
            end_pos = content.find(next_str)
    else:
        # last tab ends at </main> or <script>
        end_pos = content.find('</main>', start_pos)
        if end_pos == -1:
            end_pos = content.find('<script', start_pos)
    
    sec_html = content[start_pos:end_pos]
    sections[tab] = sec_html
    print(f"=== TAB: {tab} (length: {len(sec_html)}) ===")
    # Print headings
    h = re.findall(r'<h[1-6][^>]*>([\s\S]*?)</h[1-6]>', sec_html)
    print("  Headings:", [re.sub(r'<[^>]+>', '', x).strip() for x in h])
    # Print IDs in this section
    ids = re.findall(r'id=["\']([^"\']+)["\']', sec_html)
    print("  IDs:", ids[:25])

