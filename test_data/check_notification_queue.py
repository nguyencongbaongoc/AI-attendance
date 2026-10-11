import sqlite3
conn = sqlite3.connect('data/notification_queue.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
print('Tables:', cursor.fetchall())
cursor.execute('SELECT * FROM notifications')
print('Notifications:', cursor.fetchall())
conn.close()