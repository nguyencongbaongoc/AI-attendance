import re

source = open('scripts/phase32_rtmp_mediamtx.py', 'rb').read()
matches = list(re.finditer(b'def _check_', source))
for m in matches:
    line_start = source.rfind(b'\n', 0, m.start()) + 1
    line_end = source.find(b'\n', m.start())
    line = source[line_start:line_end]
    print(repr(line))
    print([hex(b) for b in line[:10]])