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

# Get all sheet data
all_data = ws.get_all_values()
headers = all_data[0] if all_data else []

# Find column indexes
status_col = None
username_col = None
score_col = None
for i, h in enumerate(headers):
    if h == 'Статус':
        status_col = i
    elif h == 'Username':
        username_col = i
    elif h == 'Скор':
        score_col = i

if status_col is None or username_col is None:
    print("Columns not found! Headers: %s" % headers)
    exit(1)

print("Status col: %d, Username col: %d" % (status_col, username_col))

# Get DB data
conn = sqlite3.connect('candidates.db')
conn.row_factory = sqlite3.Row
db_rows = conn.execute('SELECT username, name, status, score FROM candidates').fetchall()
db_map = {}
for r in db_rows:
    uname = r['username'].lstrip('@').lower() if r['username'] else ''
    if uname:
        db_map[uname] = {'status': r['status'], 'score': r['score'] or 0}

# Update sheets
updates = []
for row_idx, row in enumerate(all_data[1:], start=2):
    if username_col >= len(row):
        continue
    sheet_uname = row[username_col].lstrip('@').lower()
    if not sheet_uname:
        continue
    db = db_map.get(sheet_uname)
    if not db:
        continue

    current_status = row[status_col] if status_col < len(row) else ''
    if current_status != db['status']:
        updates.append({
            'range': '%s%d' % (chr(65 + status_col), row_idx),
            'values': [[db['status']]]
        })

    if score_col is not None:
        current_score = row[score_col] if score_col < len(row) else ''
        if str(current_score) != str(db['score']):
            updates.append({
                'range': '%s%d' % (chr(65 + score_col), row_idx),
                'values': [[db['score']]]
            })

print("Updates to make: %d" % len(updates))

if updates:
    ws.batch_update(updates)
    print("DONE - updated %d cells" % len(updates))
else:
    print("Nothing to update")

conn.close()
