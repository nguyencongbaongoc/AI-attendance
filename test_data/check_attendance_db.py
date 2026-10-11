import sqlite3
conn = sqlite3.connect('data/attendance.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())
cursor.execute('SELECT * FROM attendance_records')
print('Attendance Records:', cursor.fetchall())
conn.close()