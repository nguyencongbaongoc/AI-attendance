import sqlite3
import glob

for db in glob.glob('**/*.db', recursive=True):
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"DB: {db}")
        for t in tables:
            cur.execute(f"SELECT count(*) FROM {t}")
            cnt = cur.fetchone()[0]
            print(f"  {t}: {cnt} rows")
    except Exception as e:
        print(f"Error on {db}: {e}")

