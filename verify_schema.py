import sqlite3
from pathlib import Path

# Use the actual database path
actual_root = Path(r'C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE')
actual_db = actual_root / 'app' / 'data' / 'attendance.db'

conn = sqlite3.connect(str(actual_db))
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('Tables:', tables)
for table in tables:
    cursor.execute('PRAGMA table_info(' + table[0] + ')')
    cols = cursor.fetchall()
    print(table[0] + ' columns:', [c[1] for c in cols])