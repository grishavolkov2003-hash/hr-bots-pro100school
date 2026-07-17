import sqlite3
conn = sqlite3.connect("/opt/hr-bot/candidates.db")
r1 = conn.execute("DELETE FROM candidates WHERE username = ?", ("@ooot345266",))
r2 = conn.execute("DELETE FROM manager_decisions WHERE candidate_user_id = 864104662")
r3 = conn.execute("DELETE FROM pending_slots WHERE candidate_username = ?", ("@ooot345266",))
conn.commit()
print(f"candidates: {r1.rowcount}, decisions: {r2.rowcount}, slots: {r3.rowcount}")
conn.close()
