from pathlib import Path
import sqlite3

# Test the path resolution
repo_root = Path(__file__).resolve().parent.parent.parent
print('repo_root:', repo_root)
db_path = repo_root / 'app' / 'data' / 'attendance.db'
print('db_path:', db_path)
print('exists:', db_path.exists())

# Actual correct path
actual_root = Path(r'C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE')
print('actual_root:', actual_root)
actual_db = actual_root / 'app' / 'data' / 'attendance.db'
print('actual_db:', actual_db)
print('exists:', actual_db.exists())

conn = sqlite3.connect(str(actual_db))
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())