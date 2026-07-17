import sqlite3
conn = sqlite3.connect("/opt/hr-bot/candidates.db")

# Показать все необработанные решения
rows = conn.execute("SELECT * FROM manager_decisions WHERE processed = 0 OR processed IS NULL").fetchall()
print(f"Необработанных решений: {len(rows)}")
for r in rows:
    print(f"  id={r[0]} user_id={r[1]} decision={r[2]} created={r[3]}")

# Пометить все как обработанные кроме ooot345266 (864104662)
conn.execute("UPDATE manager_decisions SET processed = 1 WHERE candidate_user_id != 864104662")

# Проверить что осталось
rows2 = conn.execute("SELECT * FROM manager_decisions WHERE processed = 0 OR processed IS NULL").fetchall()
print(f"Осталось: {len(rows2)}")
for r in rows2:
    print(f"  id={r[0]} user_id={r[1]} decision={r[2]}")

conn.commit()
conn.close()
