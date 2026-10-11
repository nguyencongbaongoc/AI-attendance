import os
import re

# Search for database connection patterns
patterns = [
    'attendance\.db',
    'sqlite3\.connect',
    'create_engine',
    'DATABASE_URL',
    'data_dir',
    'db_path',
    'Path\.cwd\(\)',
    'os\.getcwd\(\)',
    '__file__',
]

for root, dirs, files in os.walk('.'):
    # Skip virtual environments and vendor SDKs
    if any(skip in root for skip in ['.venv', 'TensorRT', 'Video_Codec_SDK', '.git', '__pycache__', '.kilo']):
        continue
    for file in files:
        if file.endswith('.py') or file.endswith('.yaml') or file.endswith('.yml') or file.endswith('.json'):
            path = os.path.join(root, file)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    for pattern in patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            print(f'{path}: MATCHES "{pattern}"')
                            break
            except:
                pass