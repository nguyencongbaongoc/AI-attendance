import sqlite3

conn = sqlite3.connect('app/data/attendance.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('Tables:', tables)
for table in tables:
    cursor.execute('PRAGMA table_info(' + table[0] + ')')
    cols = cursor.fetchall()
    print(table[0] + ' columns:', [c[1] for c in cols])