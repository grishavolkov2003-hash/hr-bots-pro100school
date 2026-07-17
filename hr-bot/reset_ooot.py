import sqlite3
conn = sqlite3.connect("/opt/hr-bot/candidates.db")
conn.execute("DELETE FROM candidates WHERE username = ?", ("@ooot345266",))
conn.execute("DELETE FROM manager_decisions WHERE candidate_user_id = 864104662")
conn.commit()
print("Deleted")
conn.close()
