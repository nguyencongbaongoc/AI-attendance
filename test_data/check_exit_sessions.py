import sqlite3
conn = sqlite3.connect('data/exit_sessions.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())
cursor.execute('SELECT * FROM exit_sessions')
print('Exit Sessions:', cursor.fetchall())
conn.close()