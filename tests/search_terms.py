from pathlib import Path
import re

files = list(Path('.').rglob('*.py'))
patterns = ['student_id', 'person_id', 'parent', 'chat_id', 'telegram', 'TELEGRAM_BOT_TOKEN', 'timetable', 'DailyExcelExporter', 'DailyExportRequest', 'EXPECTED_SCHEDULE', 'POLICY_EVENTS', 'NOTIFICATION_STATUS', 'POLICY_SUMMARY']
results = {}

for f in files:
    try:
        content = f.read_text(encoding='utf-8')
        for p in patterns:
            if p.lower() in content.lower():
                if p not in results:
                    results[p] = []
                results[p].append(str(f))
    except:
        pass

for p, fs in results.items():
    print(f'{p}: {len(fs)} files')
    for f in fs[:5]:
        print(f'  {f}')
    print()