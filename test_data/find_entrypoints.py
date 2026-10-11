import ast
from pathlib import Path

# Find entrypoints - files with if __name__ == '__main__' or CLI entrypoints
app_files = list(Path('app').rglob('*.py'))
script_files = list(Path('scripts').rglob('*.py'))
root_files = list(Path('.').glob('*.py'))

all_files = app_files + script_files + root_files

entrypoints = []
for f in all_files:
    try:
        content = f.read_text(encoding='utf-8')
        if '__name__ == "__main__"' in content or "__name__ == '__main__'" in content:
            entrypoints.append(str(f))
    except:
        pass

print('=== ENTRYPOINTS (if __name__ == "__main__") ===')
for ep in entrypoints:
    print(f'  {ep}')

# Also check for CLI entrypoints in setup.py/pyproject.toml
print()
print('=== Checking for CLI entrypoints in config ===')
for config_file in ['pyproject.toml', 'setup.py', 'setup.cfg']:
    p = Path(config_file)
    if p.exists():
        print(f'{config_file}:')
        print(p.read_text(encoding='utf-8')[:2000])