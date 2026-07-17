import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row

# Fix ش
rows = conn.execute("SELECT user_id, name, username, status FROM candidates WHERE status = 'НОВЫЙ'").fetchall()
for r in rows:
    d = dict(r)
    conv = json.loads(conn.execute("SELECT conversation FROM candidates WHERE user_id = ?", (d["user_id"],)).fetchone()["conversation"] or "[]")
    has_anketa = any("анкет" in (m.get("content") or m.get("text", "")).lower() for m in conv if m.get("role") == "bot")
    if has_anketa:
        conn.execute("UPDATE candidates SET status = ? WHERE user_id = ?", ("ТЕСТОВОЕ_ОТПРАВЛЕНО", d["user_id"]))
        print(f"  Fixed {d['name']} @{d['username']} -> ТЕСТОВОЕ_ОТПРАВЛЕНО")

conn.commit()

# Check Milady
print("\n=== @nst_420 (Milady) ===")
r = conn.execute("SELECT status, conversation FROM candidates WHERE username LIKE '%nst_420%'").fetchone()
if r:
    print(f"Status: {r['status']}")
    conv = json.loads(r["conversation"]) if r["conversation"] else []
    for m in conv[-8:]:
        role = m.get("role", "?")
        t = (m.get("content") or m.get("text", ""))[:120]
        print(f"  [{role}] {t}")

# Check Тима
print("\n=== @timoxa_0603 (Тима) ===")
r = conn.execute("SELECT status, conversation FROM candidates WHERE username LIKE '%timoxa_0603%'").fetchone()
if r:
    print(f"Status: {r['status']}")
    conv = json.loads(r["conversation"]) if r["conversation"] else []
    for m in conv:
        role = m.get("role", "?")
        t = (m.get("content") or m.get("text", ""))[:120]
        print(f"  [{role}] {t}")

conn.close()
