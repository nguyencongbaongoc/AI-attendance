import sqlite3
import os

# Create online backup of authoritative attendance.db
src_db = r'app\data\attendance.db'
dst_db = r'C:\temp\rollback_test\sqlite\attendance_backup.db'

# Use SQLite online backup API
src_conn = sqlite3.connect('file:' + src_db + '?mode=ro', uri=True)
dst_conn = sqlite3.connect(dst_db)
try:
    src_conn.backup(dst_conn)
    print('Backup completed successfully')
finally:
    src_conn.close()
    dst_conn.close()

# Verify backup
conn = sqlite3.connect(dst_db)
cursor = conn.cursor()
cursor.execute('PRAGMA integrity_check')
integrity = cursor.fetchone()[0]
print('Integrity check: ' + integrity)

cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('Tables: ' + str(tables))

for table in tables:
    cursor.execute('SELECT COUNT(*) FROM ' + table[0])
    count = cursor.fetchone()[0]
    print('  ' + table[0] + ': ' + str(count) + ' records')

conn.close()

# Check file size
size = os.path.getsize(r'C:\temp\rollback_test\sqlite\attendance_backup.db')
print('Backup size: ' + str(size) + ' bytes')