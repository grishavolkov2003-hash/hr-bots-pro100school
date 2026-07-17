import sqlite3

DB_PATH = "/opt/hr-bot/candidates.db"
conn = sqlite3.connect(DB_PATH)
r = conn.execute("DELETE FROM candidates WHERE username = ?", ("@ooot345266",))
print(f"Deleted @ooot345266: {r.rowcount}")

r2 = conn.execute("DELETE FROM candidates WHERE username = ?", ("@tutor_zelimhan",))
print(f"Deleted @tutor_zelimhan: {r2.rowcount}")

conn.commit()
conn.close()
