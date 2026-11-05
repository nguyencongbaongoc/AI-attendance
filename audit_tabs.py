import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('frontend/index.html', encoding='utf-8') as f:
    content = f.read()

m = re.search(r'function\s+updateDashboardMetrics[\s\S]*?\n\}', content)
if m:
    print("updateDashboardMetrics:")
    print(m.group(0))

print("\n--- check-ins table / recentAttendanceList ---")
m2 = re.search(r'function\s+renderRecentAttendance[\s\S]*?\n\}', content)
if m2:
    print("renderRecentAttendance:")
    print(m2.group(0))
else:
    # search where recentAttendanceList is used
    for line in content.splitlines():
        if 'recentAttendanceList' in line:
            print(line.strip())

