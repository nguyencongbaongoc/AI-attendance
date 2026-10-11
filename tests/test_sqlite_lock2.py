import sqlite3
import tempfile
import os
import time
import glob

# Test with WAL mode - check for -wal and -shm files
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path = f.name

conn = sqlite3.connect(db_path)
conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
conn.commit()

# Check for WAL files
wal_files = glob.glob(db_path + '*')
print(f'WAL files after commit: {wal_files}')

conn.close()

time.sleep(0.1)

# Check for WAL files after close
wal_files = glob.glob(db_path + '*')
print(f'WAL files after close: {wal_files}')

try:
    os.unlink(db_path)
    print('SUCCESS: File deleted')
except PermissionError as e:
    print(f'FAILED: {e}')
    # Try to delete WAL files too
    for f in wal_files:
        try:
            os.unlink(f)
            print(f'Deleted WAL file: {f}')
        except:
            pass

# Test with multiple connections
with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
    db_path2 = f.name

conn1 = sqlite3.connect(db_path2)
conn1.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
conn1.commit()

conn2 = sqlite3.connect(db_path2)
conn2.execute('INSERT INTO test (id) VALUES (1)')
conn2.commit()

conn1.close()
conn2.close()

time.sleep(0.1)

wal_files = glob.glob(db_path2 + '*')
print(f'WAL files after multiple connections: {wal_files}')

try:
    os.unlink(db_path2)
    print('SUCCESS: File deleted after multiple connections')
except PermissionError as e:
    print(f'FAILED: {e}')
    for f in wal_files:
        try:
            os.unlink(f)
        except:
            pass