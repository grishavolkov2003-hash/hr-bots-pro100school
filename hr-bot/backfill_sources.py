import sqlite3, json, re

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT user_id, username, name, conversation FROM candidates").fetchall()

hh_keywords = ["hh.ru", "hh ", "хэдхантер", "headhunter", "резюме на hh", "вакансию на hh", "откликал", "с hh"]
rec_keywords = ["игорь", "копылов", "попросили написать", "рекомендовал", "рекомендовали", "посоветовал", "сказали написать", "направили"]

sources = {"hh.ru": 0, "рекомендация": 0, "telegram": 0}
updates = []

for r in rows:
    d = dict(r)
    conv = json.loads(d["conversation"]) if d["conversation"] else []
    all_text = " ".join([(m.get("content") or m.get("text", "")).lower() for m in conv if m.get("role") == "candidate"])

    source = "telegram"
    for kw in hh_keywords:
        if kw in all_text:
            source = "hh.ru"
            break
    if source == "telegram":
        for kw in rec_keywords:
            if kw in all_text:
                source = "рекомендация"
                break

    sources[source] = sources.get(source, 0) + 1
    updates.append((source, d["user_id"]))

# Update DB - add source column if not exists
try:
    conn.execute("ALTER TABLE candidates ADD COLUMN source TEXT DEFAULT 'telegram'")
except:
    pass

for source, uid in updates:
    conn.execute("UPDATE candidates SET source = ? WHERE user_id = ?", (source, uid))

conn.commit()
conn.close()

print("Источники:")
for s, c in sorted(sources.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")
print(f"  Всего: {sum(sources.values())}")
