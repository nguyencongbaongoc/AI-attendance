import sqlite3
import tempfile
import os
import time
import glob
import threading

# Test with PRAGMA journal_mode=DELETE
class TestRegistryNoWAL:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
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
    
    def create_parent(self, parent_name: str):
        import secrets
        from datetime import datetime
        parent_id = f"PAR-{secrets.token_urlsafe(8)}"
        now = datetime.utcnow().isoformat() + "Z"
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.execute("""
                INSERT INTO parents (parent_id, parent_name, telegram_chat_id, telegram_enabled, notification_preferences, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (parent_id, parent_name, None, 1, 'all', now, now))
            conn.commit()
        return parent_id
    
    def get_parent(self, parent_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('PRAGMA journal_mode=DELETE')
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM parents WHERE parent_id = ?", (parent_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def close(self):
        pass

# Test the pattern with journal_mode=DELETE
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path = f.name

registry = TestRegistryNoWAL(db_path)
parent_id = registry.create_parent("Test Parent")
parent = registry.get_parent(parent_id)
print(f"Created parent: {parent}")

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