import sqlite3
import os
import hashlib

def inspect_db(path, label):
    print(f'=== {label} ===')
    print(f'Path: {path}')
    print(f'Size: {os.path.getsize(path)} bytes')
    with open(path, 'rb') as f:
        print(f'SHA256: {hashlib.sha256(f.read()).hexdigest()}')
    
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    cursor = conn.cursor()
    
    # Integrity
    cursor.execute('PRAGMA integrity_check')
    print(f'Integrity: {cursor.fetchone()[0]}')
    
    # Journal mode
    cursor.execute('PRAGMA journal_mode')
    print(f'Journal mode: {cursor.fetchone()[0]}')
    
    # Tables
    cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
    tables = cursor.fetchall()
    print(f'Tables: {tables}')
    
    # Record counts
    for table in tables:
        t = table[0]
        try:
            cursor.execute(f'SELECT COUNT(*) FROM {t}')
            print(f'  {t}: {cursor.fetchone()[0]} records')
        except:
            pass
    
    # WAL/SHM info
    cursor.execute('PRAGMA wal_autocheckpoint')
    print(f'WAL autocheckpoint: {cursor.fetchone()[0]}')
    
    conn.close()
    print()

inspect_db(r'app/data/attendance.db', 'app/data/attendance.db (AUTHORITATIVE)')
inspect_db(r'data/attendance.db', 'data/attendance.db (SECONDARY)')