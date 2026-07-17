import sqlite3
conn = sqlite3.connect("/opt/hr-bot/candidates.db")
r1 = conn.execute("DELETE FROM candidates WHERE username LIKE '%gorkopylov%'")
r2 = conn.execute("DELETE FROM manager_decisions WHERE candidate_user_id IN (SELECT user_id FROM candidates WHERE username LIKE '%gorkopylov%')")
conn.commit()
print(f"Deleted: {r1.rowcount}")
conn.close()
