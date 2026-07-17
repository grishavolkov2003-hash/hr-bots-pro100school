import sqlite3, time
from sheets import _get_sheet

time.sleep(5)

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT username, source FROM candidates WHERE source IS NOT NULL AND source != ''").fetchall()
db_map = {}
for r in rows:
    u = (r["username"] or "").lstrip("@").lower()
    if u:
        db_map[u] = r["source"]

sh = _get_sheet()
ws = sh.sheet1
all_data = ws.get_all_values()

updates = []
for idx, row in enumerate(all_data[1:], start=2):
    if len(row) < 5 or not row[2]:
        continue
    u = row[2].lstrip("@").lower()
    src = db_map.get(u)
    if src and (len(row) < 5 or row[4] != src):
        updates.append({"range": f"E{idx}", "values": [[src]]})

print(f"Source updates: {len(updates)}")
if updates:
    for i in range(0, len(updates), 50):
        batch = updates[i:i+50]
        ws.batch_update(batch)
        if i + 50 < len(updates):
            time.sleep(5)
    print("Done!")

conn.close()
