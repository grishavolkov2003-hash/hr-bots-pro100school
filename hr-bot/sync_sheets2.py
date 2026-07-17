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
headers = all_data[0] if all_data else []
print("Headers: %s" % headers)
print("Rows: %d" % len(all_data))

# Columns: Дата(A), Имя(B), Username(C), Предмет(D), Источник(E), Учеников(F), Аккаунт Профи(G), Статус(H), Последнее(I), Комментарий(J), Скор(K)
USERNAME_COL = 2  # C
STATUS_COL = 7    # H
SCORE_COL = 10    # K

# Fix header if needed
if headers[STATUS_COL] != 'Статус':
    ws.update_cell(1, STATUS_COL + 1, 'Статус')
    print("Fixed header H -> Статус")

# Get DB data
conn = sqlite3.connect('candidates.db')
conn.row_factory = sqlite3.Row
db_rows = conn.execute('SELECT username, name, status, score FROM candidates').fetchall()
db_map = {}
for r in db_rows:
    uname = r['username'].lstrip('@').lower() if r['username'] else ''
    if uname:
        db_map[uname] = {'status': r['status'], 'score': r['score'] or 0}

# Update
updates = []
for row_idx, row in enumerate(all_data[1:], start=2):
    if USERNAME_COL >= len(row):
        continue
    sheet_uname = row[USERNAME_COL].lstrip('@').lower()
    if not sheet_uname:
        continue
    db = db_map.get(sheet_uname)
    if not db:
        continue

    current_status = row[STATUS_COL] if STATUS_COL < len(row) else ''
    if current_status != db['status']:
        updates.append({'range': 'H%d' % row_idx, 'values': [[db['status']]]})

    if SCORE_COL < len(row):
        current_score = row[SCORE_COL]
        if str(current_score) != str(db['score']):
            updates.append({'range': 'K%d' % row_idx, 'values': [[db['score']]]})

print("Updates: %d" % len(updates))
if updates:
    ws.batch_update(updates)
    print("SYNCED")
else:
    print("Already in sync")

conn.close()
