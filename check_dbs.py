import sqlite3
import hashlib
import os

def check_db(db_path):
    print(f"=== {db_path} ===")
    print(f"Size: {os.path.getsize(db_path)} bytes")
    with open(db_path, 'rb') as f:
        print(f"SHA256: {hashlib.sha256(f.read()).hexdigest()}")
    
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        cursor = conn.cursor()
        cursor.execute('PRAGMA integrity_check')
        print('Integrity:', cursor.fetchone())
        cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
        tables = cursor.fetchall()
        print('Tables:', tables)
        for table in tables:
            table_name = table[0]
            try:
                cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
                print(f'  {table_name} count:', cursor.fetchone())
            except Exception as e:
                print(f'  {table_name} count error:', e)
        conn.close()
    except Exception as e:
        print('Error:', e)
    print()

# Check active databases
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\app\data\attendance.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\data\attendance.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\data\attendance_events.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\app\data\exit_sessions.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\data\exit_sessions.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\app\data\parent_registry.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\data\parent_registry.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\app\data\notification_queue.db")
check_db(r"C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\data\notification_queue.db")