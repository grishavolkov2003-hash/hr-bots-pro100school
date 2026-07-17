import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, conversation FROM candidates WHERE username LIKE '%baket%'").fetchone()
conv = json.loads(r["conversation"])

print(f"Before: {len(conv)} messages")

cleaned = []
for m in conv:
    t = (m.get("content") or m.get("text", "")).lower()
    if "логин:" in t and "пароль:" in t:
        print(f"  Removed: {(m.get('content') or m.get('text', ''))[:80]}")
        continue
    if "не отправляйте логин и пароль" in t:
        print(f"  Removed: {(m.get('content') or m.get('text', ''))[:80]}")
        continue
    cleaned.append(m)

print(f"After: {len(cleaned)} messages")

conn.execute("UPDATE candidates SET conversation = ? WHERE user_id = ?",
             (json.dumps(cleaned, ensure_ascii=False), r["user_id"]))
conn.commit()
conn.close()
print("Done!")
