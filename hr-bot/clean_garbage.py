import sqlite3, json

markers = ["Thinking Process", "Let me analyze", "pre-flight", "I am Claude",
           "As an AI", "Analyze the Request", "Formulate the Response",
           "conversation history:", "coding-focused", "I can only help with software",
           "getSchedule()", "ПРЕДПОЛЁТНАЯ ПРОВЕРКА"]

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT user_id, username, name, conversation FROM candidates WHERE conversation IS NOT NULL").fetchall()

total_removed = 0
for r in rows:
    conv = json.loads(r["conversation"]) if r["conversation"] else []
    cleaned = []
    removed = 0
    for m in conv:
        if m.get("role") != "bot":
            cleaned.append(m)
            continue
        text = m.get("content") or m.get("text", "")
        is_garbage = False
        for mk in markers:
            if mk in text:
                is_garbage = True
                break
        if is_garbage:
            removed += 1
            print(f"  Removed from @{r['username']}: {text[:80]}...")
        else:
            cleaned.append(m)
    if removed > 0:
        conn.execute("UPDATE candidates SET conversation = ? WHERE user_id = ?",
                     (json.dumps(cleaned, ensure_ascii=False), r["user_id"]))
        total_removed += removed

conn.commit()
conn.close()
print(f"\nTotal removed: {total_removed}")
