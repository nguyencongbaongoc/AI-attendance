import sqlite3
conn = sqlite3.connect('data/attendance_events.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())
cursor.execute('SELECT COUNT(*) FROM attendance_events')
print('Attendance events:', cursor.fetchone())
conn.close()