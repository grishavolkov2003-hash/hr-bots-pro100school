import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, username, name, status, conversation FROM candidates WHERE username LIKE '%always_on_chill%'").fetchone()
if r:
    d = dict(r)
    print(f"Name: {d['name']} | Status: {d['status']} | uid: {d['user_id']}")
    conv = json.loads(d["conversation"]) if d["conversation"] else []
    print(f"Messages: {len(conv)}")
    for m in conv:
        role = m.get("role", "?")
        t = (m.get("content") or m.get("text", ""))[:120]
        print(f"  [{role}] {t}")
else:
    print("Not found in DB!")
conn.close()
