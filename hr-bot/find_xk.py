import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, name, status, conversation FROM candidates WHERE username LIKE '%XKsesss%'").fetchone()
print(f"Name: {r['name']} | Status: {r['status']}")
conv = json.loads(r["conversation"]) if r["conversation"] else []
for i, m in enumerate(conv):
    role = m.get("role", "?")
    t = (m.get("content") or m.get("text", ""))[:150]
    print(f"  [{i}] [{role}] {t}")
conn.close()
