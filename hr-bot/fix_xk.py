import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, conversation FROM candidates WHERE username LIKE '%XKsesss%'").fetchone()
conv = json.loads(r["conversation"])

print(f"Before: {len(conv)} messages")

# Remove messages after "всё согласовано" (index 21) - indices 22-27
cleaned = conv[:22]  # keep 0-21

removed = conv[22:]
for m in removed:
    role = m.get("role", "?")
    t = (m.get("content") or m.get("text", ""))[:80]
    print(f"  Removed [{role}]: {t}")

print(f"After: {len(cleaned)} messages")

conn.execute("UPDATE candidates SET conversation = ? WHERE user_id = ?",
             (json.dumps(cleaned, ensure_ascii=False), r["user_id"]))
conn.commit()
conn.close()
print("Done!")
