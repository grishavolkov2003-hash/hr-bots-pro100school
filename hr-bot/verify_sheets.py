import gspread, sqlite3, json
from google.oauth2.credentials import Credentials

with open('google_creds.json') as f:
    token_data = json.load(f)

creds = Credentials(
    token=token_data["token"],
    refresh_token=token_data["refresh_token"],
    token_uri=token_data["token_uri"],
    client_id=token_data["client_id"],
    client_secret=token_data["client_secret"],
    scopes=token_data.get("scopes"),
)

gc = gspread.authorize(creds)
sh = gc.open('HR Воронка — репетиторы')
ws = sh.sheet1
all_data = ws.get_all_values()

headers = all_data[0]
print("Headers: %s" % headers)

# Fix headers
correct_headers = ['Дата', 'Имя', 'Username', 'Предмет', 'Источник', 'Учеников', 'Аккаунт Профи', 'Статус', 'Последнее действие', 'Комментарий', 'Скор']
need_fix = False
for i, (h, ch) in enumerate(zip(headers, correct_headers)):
    if h != ch:
        need_fix = True
        break

if need_fix:
    ws.update('A1:K1', [correct_headers])
    print("Fixed headers!")

# DB
conn = sqlite3.connect('candidates.db')
conn.row_factory = sqlite3.Row
db_rows = conn.execute('SELECT username, name, status, score FROM candidates').fetchall()
db_map = {}
for r in db_rows:
    uname = r['username'].lstrip('@').lower() if r['username'] else ''
    if uname:
        db_map[uname] = {'status': r['status'], 'score': r['score'] or 0, 'name': r['name']}

# Compare - sample 15 rows
print("\n=== ПРОВЕРКА (выборка) ===")
checked = 0
mismatches = 0
for row in all_data[1:]:
    if len(row) < 8:
        continue
    uname = row[2].lstrip('@').lower()  # C = Username
    sheet_status = row[7]  # H = Статус
    if not uname:
        continue
    db = db_map.get(uname)
    if not db:
        continue
    match = "OK" if sheet_status == db['status'] else "MISMATCH"
    if match == "MISMATCH":
        mismatches += 1
        print("  MISMATCH @%s | Sheet: [%s] | DB: [%s]" % (uname, sheet_status, db['status']))
    checked += 1

print("\nChecked: %d | Mismatches: %d" % (checked, mismatches))
if mismatches == 0:
    print("ALL SYNCED!")

conn.close()
