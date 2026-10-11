import sqlite3
conn = sqlite3.connect('data/attendance.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())
cursor.execute('SELECT COUNT(*) FROM attendance_records')
print('Attendance records:', cursor.fetchone())
conn.close()