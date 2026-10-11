import sqlite3
import tempfile
import os
import time

# Test with WAL mode disabled
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path = f.name

conn = sqlite3.connect(db_path)
conn.execute('PRAGMA journal_mode=DELETE')
conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
conn.commit()
conn.close()

time.sleep(0.1)

try:
    os.unlink(db_path)
    print('SUCCESS: File deleted with journal_mode=DELETE')
except PermissionError as e:
    print(f'FAILED: {e}')

# Test with explicit cursor close
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path2 = f.name

conn2 = sqlite3.connect(db_path2)
cursor = conn2.cursor()
cursor.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
cursor.close()
conn2.commit()
conn2.close()

time.sleep(0.1)

try:
    os.unlink(db_path2)
    print('SUCCESS: File deleted with explicit cursor close')
except PermissionError as e:
    print(f'FAILED: {e}')

# Test default (WAL mode)
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path3 = f.name

conn3 = sqlite3.connect(db_path3)
conn3.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
conn3.commit()
conn3.close()

time.sleep(0.1)

try:
    os.unlink(db_path3)
    print('SUCCESS: File deleted with default WAL mode')
except PermissionError as e:
    print(f'FAILED: {e}')