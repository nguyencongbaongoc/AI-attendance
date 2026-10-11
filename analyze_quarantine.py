import csv
from pathlib import Path
from collections import defaultdict

csv_path = Path(r'new_engine/audit/phase_0_2_2/05_quarantine_sha256_manifest.csv')

# Read manifest
categories = defaultdict(lambda: {'count': 0, 'size': 0, 'extensions': set()})
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        cat = row['category']
        categories[cat]['count'] += 1
        categories[cat]['size'] += int(row['size_bytes'])
        categories[cat]['extensions'].add(row['extension'])

# Print summary
print('QUARANTINE CLASSIFICATION SUMMARY')
print('=' * 60)
print('Total categories: {}'.format(len(categories)))
print()

for cat in sorted(categories.keys()):
    info = categories[cat]
    size_gb = info['size'] / (1024**3)
    print('{}:'.format(cat))
    print('  Files: {}'.format(info['count']))
    print('  Size: {:.2f} GB'.format(size_gb))
    print('  Extensions: {}'.format(sorted(info['extensions'])))
    print()

# Check specific categories
critical_categories = ['generated_live', 'root_model_duplicates', 'video_pipeline_v2', 'root_test_videos']
print('CRITICAL CATEGORY INSPECTION:')
print('=' * 60)
for cat in critical_categories:
    if cat in categories:
        info = categories[cat]
        print('{}: {} files, {:.2f} GB'.format(cat, info['count'], info['size']/(1024**3)))
    else:
        print('{}: NOT FOUND'.format(cat))

# Check Agent Manager worktree in generated_live
print()
print('AGENT MANAGER WORKTREE CHECK:')
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'worktree' in row['relative_path'].lower() or 'kilo' in row['relative_path'].lower():
            print('  Found: {} ({} bytes)'.format(row['relative_path'], row['size_bytes']))