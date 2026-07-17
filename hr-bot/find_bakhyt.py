import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, conversation FROM candidates WHERE username LIKE '%baket%'").fetchone()
if not r:
    r = conn.execute("SELECT user_id, conversation FROM candidates WHERE name LIKE '%ахыт%'").fetchone()

conv = json.loads(r["conversation"]) if r["conversation"] else []

for i, m in enumerate(conv):
    role = m.get("role", "?")
    t = (m.get("content") or m.get("text", ""))[:150]
    flag = ""
    lower = t.lower()
    if "парол" in lower or "password" in lower or "кидай" in lower or "логин" in lower or "login" in lower:
        flag = " <--- !!!"
    print(f"  [{i}] [{role}] {t}{flag}")

conn.close()
