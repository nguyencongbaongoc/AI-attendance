import sqlite3
from pathlib import Path

# Test the path resolution
repo_root = Path(__file__).resolve().parent.parent.parent
db_path = repo_root / "app" / "data" / "attendance.db"
print("db_path:", db_path)
print("exists:", db_path.exists())

# Test connection
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print("Tables:", cursor.fetchall())

# Check table
cursor.execute('SELECT * FROM attendance_records LIMIT 1')
print("Sample:", cursor.fetchone())