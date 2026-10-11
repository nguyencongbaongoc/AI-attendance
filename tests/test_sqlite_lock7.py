import sqlite3
import tempfile
import os
import time
import glob
import uuid

# Test with explicit connection management
db_path = os.path.join(tempfile.gettempdir(), f'test_{uuid.uuid4().hex}.db')
print(f'DB path: {db_path}')

# Create directory
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Test with explicit connection management
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=DELETE')
conn.execute("""
    CREATE TABLE IF NOT EXISTS parents (
        parent_id TEXT PRIMARY KEY,
        parent_name TEXT NOT NULL,
        telegram_chat_id TEXT,
        telegram_enabled INTEGER DEFAULT 1,
        notification_preferences TEXT DEFAULT 'all',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
conn.commit()
conn.close()

import secrets
from datetime import datetime
parent_id = f"PAR-{secrets.token_urlsafe(8)}"
now = datetime.utcnow().isoformat() + "Z"

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=DELETE')
conn.execute("""
    INSERT INTO parents (parent_id, parent_name, telegram_chat_id, telegram_enabled, notification_preferences, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", (parent_id, "Test Parent", None, 1, 'all', now, now))
conn.commit()
conn.close()

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=DELETE')
conn.row_factory = sqlite3.Row
cursor = conn.execute("SELECT * FROM parents WHERE parent_id = ?", (parent_id,))
row = cursor.fetchone()
parent = dict(row) if row else None
print(f"Created parent: {parent}")
cursor.close()
conn.close()

# Check for WAL files
wal_files = glob.glob(db_path + '*')
print(f'WAL files after operations: {wal_files}')

# Try to delete immediately
try:
    os.unlink(db_path)
    print('SUCCESS: File deleted immediately')
except PermissionError as e:
    print(f'FAILED immediately: {e}')
    for f in wal_files:
        try:
            os.unlink(f)
        except:
            pass

# Wait and try again
time.sleep(0.5)
wal_files = glob.glob(db_path + '*')
print(f'WAL files after wait: {wal_files}')

try:
    os.unlink(db_path)
    print('SUCCESS: File deleted after wait')
except PermissionError as e:
    print(f'FAILED after wait: {e}')
    for f in wal_files:
        try:
            os.unlink(f)
            print(f'Deleted WAL file: {f}')
        except:
            pass