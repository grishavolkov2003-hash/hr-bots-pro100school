import sqlite3, json, time
from sheets import _get_sheet, sync_kanban
from datetime import datetime

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row

time.sleep(20)  # переждать 429 от прошлого запуска

sh = _get_sheet()
ws = sh.sheet1
existing = ws.get_all_values()
existing_unames = set()
for row in existing[1:]:
    if len(row) >= 3 and row[2]:
        existing_unames.add(row[2].lstrip("@").lower())

print(f"Existing in Sheets: {len(existing_unames)}")

rows = conn.execute("SELECT * FROM candidates").fetchall()
to_add = []
for r in rows:
    d = dict(r)
    uname = (d.get("username") or "").lstrip("@").lower()
    if uname and uname not in existing_unames:
        to_add.append([
            d.get("created_at", datetime.now().isoformat())[:10],
            d.get("name", ""),
            d.get("username", ""),
            d.get("subject", ""),
            "",  # source
            "",  # students_count
            "",  # profi account
            d.get("status", "НОВЫЙ"),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            "",  # comment
        ])

print(f"To add: {len(to_add)}")

if to_add:
    # Один API-запрос на батч (append_rows, не append_row по одной - экономит квоту)
    for i in range(0, len(to_add), 20):
        batch = to_add[i:i+20]
        for attempt in range(5):
            try:
                ws.append_rows(batch)
                break
            except Exception as e:
                wait = 15 * (attempt + 1)
                print(f"  Ошибка на батче {i}: {e} - жду {wait}с и пробую снова")
                time.sleep(wait)
        else:
            raise RuntimeError(f"Не удалось записать батч начиная с {i} после 5 попыток")
        print(f"  Added {i+len(batch)}/{len(to_add)}")
        if i + 20 < len(to_add):
            time.sleep(3)

print("Sheets done!")

time.sleep(5)
candidates = [dict(r) for r in rows]
sync_kanban(candidates)
conn.close()
