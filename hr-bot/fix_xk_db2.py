import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
r = conn.execute("SELECT user_id, conversation FROM candidates WHERE username LIKE '%XKsesss%'").fetchone()
conv = json.loads(r["conversation"])

cleaned = [m for m in conv if "коллега подтвердит" not in (m.get("content") or m.get("text", ""))]

removed = len(conv) - len(cleaned)
print(f"Removed {removed} from DB conversation")

if removed:
    conn.execute("UPDATE candidates SET conversation = ? WHERE user_id = ?",
                 (json.dumps(cleaned, ensure_ascii=False), r["user_id"]))
    conn.commit()

conn.close()
