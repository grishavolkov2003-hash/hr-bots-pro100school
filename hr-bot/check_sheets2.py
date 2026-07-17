import gspread, sqlite3, json, os
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
rows = ws.get_all_records()

conn = sqlite3.connect('candidates.db')
conn.row_factory = sqlite3.Row
db_rows = conn.execute('SELECT username, name, status, score FROM candidates ORDER BY updated_at DESC').fetchall()
db_map = {}
for r in db_rows:
    uname = r['username'].lstrip('@') if r['username'] else ''
    if uname:
        db_map[uname.lower()] = {'name': r['name'], 'status': r['status'], 'score': r['score']}

print("Sheets: %d rows | DB: %d candidates\n" % (len(rows), len(db_rows)))

mismatches = []
for row in rows:
    sheet_uname = str(row.get('Username', '')).lstrip('@').lower()
    sheet_status = str(row.get('Статус', ''))
    if not sheet_uname:
        continue
    db = db_map.get(sheet_uname)
    if db and db['status'] != sheet_status:
        mismatches.append((sheet_uname, db['name'], sheet_status, db['status']))

print("=== РАСХОЖДЕНИЯ (%d) ===" % len(mismatches))
for u, n, ss, ds in mismatches:
    print("  @%s | %s | Sheets: %s | DB: %s" % (u, n, ss, ds))

sheet_unames = set()
for row in rows:
    u = str(row.get('Username', '')).lstrip('@').lower()
    if u:
        sheet_unames.add(u)

missing = []
for uname, data in db_map.items():
    if uname and uname not in sheet_unames and data['status'] not in ('ИМПОРТ', 'КВАЛИФИКАЦИЯ'):
        missing.append((uname, data['name'], data['status']))

print("\n=== В БД НО НЕТ В ТАБЛИЦЕ (%d) ===" % len(missing))
for u, n, s in missing[:25]:
    print("  @%s | %s | %s" % (u, n, s))

conn.close()
