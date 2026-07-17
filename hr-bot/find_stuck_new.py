import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT user_id, username, name, status, conversation FROM candidates WHERE status = 'НОВЫЙ'").fetchall()

print(f"=== ЗАСТРЯЛИ В НОВЫЙ ({len(rows)}) ===\n")
for r in rows:
    d = dict(r)
    conv = json.loads(d["conversation"]) if d["conversation"] else []
    bot_msgs = [m for m in conv if m.get("role") == "bot"]
    cand_msgs = [m for m in conv if m.get("role") == "candidate"]

    has_anketa = any("анкет" in (m.get("content") or m.get("text", "")).lower() for m in bot_msgs)

    print(f"@{d['username']} ({d['name']}) | msgs: {len(conv)} (bot: {len(bot_msgs)}, cand: {len(cand_msgs)}) | anketa sent: {has_anketa}")
    if cand_msgs:
        last = (cand_msgs[-1].get("content") or cand_msgs[-1].get("text", ""))[:100]
        print(f"  Последнее от кандидата: {last}")
    if bot_msgs:
        last = (bot_msgs[-1].get("content") or bot_msgs[-1].get("text", ""))[:100]
        print(f"  Последнее от бота: {last}")
    if not conv:
        print(f"  ПУСТАЯ ПЕРЕПИСКА")
    print()

conn.close()
