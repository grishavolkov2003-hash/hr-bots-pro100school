import sqlite3, json
from datetime import datetime, timedelta

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT user_id, username, name, status, conversation, updated_at FROM candidates").fetchall()

now = datetime.now()
stale_24 = []
stale_48 = []
stale_72 = []

for r in rows:
    d = dict(r)
    status = d["status"]
    if status in ("ОТКАЗ", "ЗАМОРОЗКА", "АККАУНТ_ПОЛУЧЕН", "ОТКРЫТ", "ИМПОРТ"):
        continue

    conv = json.loads(d["conversation"]) if d["conversation"] else []
    if not conv:
        continue

    last_msg = conv[-1]
    role = last_msg.get("role", "?")

    # Only care if WE sent last message (candidate hasn't replied)
    if role != "bot":
        continue

    updated = d.get("updated_at", "")
    if not updated:
        continue

    try:
        updated_dt = datetime.fromisoformat(updated.replace("Z", ""))
    except:
        continue

    hours = (now - updated_dt).total_seconds() / 3600
    name = d["name"] or "?"
    uname = d["username"] or "?"
    last_bot = (last_msg.get("content") or last_msg.get("text", ""))[:80]

    entry = f"@{uname} ({name}) | {status} | {hours:.0f}ч | Посл: {last_bot}"

    if hours >= 72:
        stale_72.append(entry)
    elif hours >= 48:
        stale_48.append(entry)
    elif hours >= 24:
        stale_24.append(entry)

print(f"=== НЕ ОТВЕЧАЮТ 72+ часов ({len(stale_72)}) ===")
for e in stale_72:
    print(f"  🔴 {e}")

print(f"\n=== НЕ ОТВЕЧАЮТ 48-72 часа ({len(stale_48)}) ===")
for e in stale_48:
    print(f"  🟡 {e}")

print(f"\n=== НЕ ОТВЕЧАЮТ 24-48 часов ({len(stale_24)}) ===")
for e in stale_24:
    print(f"  🟠 {e}")

print(f"\nИтого: {len(stale_24) + len(stale_48) + len(stale_72)} молчунов")
conn.close()
