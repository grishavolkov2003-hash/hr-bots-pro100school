import sqlite3, json

conn = sqlite3.connect("candidates.db")
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT user_id, username, name, status, conversation, score FROM candidates ORDER BY status").fetchall()

status_counts = {}
issues = []

for r in rows:
    d = dict(r)
    status = d["status"]
    name = d["name"] or "?"
    uname = d["username"] or "?"
    conv = json.loads(d["conversation"]) if d["conversation"] else []

    status_counts[status] = status_counts.get(status, 0) + 1

    bot_msgs = [m for m in conv if m.get("role") == "bot"]
    cand_msgs = [m for m in conv if m.get("role") == "candidate"]

    def has(keyword, msgs=bot_msgs):
        for m in msgs:
            t = m.get("content") or m.get("text", "")
            if keyword.lower() in t.lower():
                return True
        return False

    has_greeting = has("анкет")
    has_conditions = has("75%")
    has_compliment = has("визитк")
    has_video_ack = has("передам на проверку")
    has_transfer = has("brosky_manage")
    has_call_invite = has("созвонить")

    # Status logic checks
    if status == "НОВЫЙ" and has_greeting:
        issues.append(f"@{uname} ({name}): НОВЫЙ но анкета уже отправлена -> должен быть ТЕСТОВОЕ_ОТПРАВЛЕНО")
    if status == "ТЕСТОВОЕ_ОТПРАВЛЕНО" and not has_greeting:
        issues.append(f"@{uname} ({name}): ТЕСТОВОЕ_ОТПРАВЛЕНО но анкеты нет в переписке")
    if status == "ГОТОВ_К_СОЗВОНУ" and not has_conditions and not has_compliment:
        issues.append(f"@{uname} ({name}): ГОТОВ_К_СОЗВОНУ но условия/комплимент не отправлены")
    if status == "ПЕРЕДАН_МЕНЕДЖЕРУ" and not has_transfer and not has_call_invite:
        issues.append(f"@{uname} ({name}): ПЕРЕДАН_МЕНЕДЖЕРУ но нет сообщения про brosky/созвон")
    if status in ("СОЗВОН_НАЗНАЧЕН",) and not has_call_invite and not has_transfer:
        issues.append(f"@{uname} ({name}): СОЗВОН_НАЗНАЧЕН но нет приглашения на созвон")

    # Check for garbage
    for m in bot_msgs:
        t = m.get("content") or m.get("text", "")
        markers = ["Thinking Process", "I'm a coding", "ПРЕДПОЛЁТНАЯ ПРОВЕРКА", "Let me analyze", "getSchedule()"]
        for mk in markers:
            if mk in t:
                issues.append(f"@{uname} ({name}): МУСОР [{mk}]: {t[:60]}")
                break

    # Check empty conversations
    if not conv and status not in ("ИМПОРТ",):
        issues.append(f"@{uname} ({name}): пустая переписка при статусе {status}")

print("=== СТАТУСЫ ===")
for s, c in sorted(status_counts.items(), key=lambda x: -x[1]):
    print(f"  {s}: {c}")
print(f"  ИТОГО: {sum(status_counts.values())}")

# Now compare DB vs Sheets
print("\n=== СВЕРКА БД vs SHEETS ===")
try:
    from sheets import _get_sheet
    sh = _get_sheet()
    ws = sh.sheet1
    all_data = ws.get_all_values()

    sheet_map = {}
    for row in all_data[1:]:
        if len(row) >= 8 and row[2]:
            u = row[2].lstrip("@").lower()
            sheet_map[u] = row[7]  # status column

    db_map = {}
    for r in rows:
        d = dict(r)
        u = (d["username"] or "").lstrip("@").lower()
        if u:
            db_map[u] = d["status"]

    mismatches = 0
    for u, db_st in db_map.items():
        sh_st = sheet_map.get(u)
        if sh_st and sh_st != db_st:
            mismatches += 1
            issues.append(f"@{u}: БД={db_st} vs Sheets={sh_st}")

    in_db_not_sheets = set(db_map.keys()) - set(sheet_map.keys())
    in_sheets_not_db = set(sheet_map.keys()) - set(db_map.keys())

    print(f"  В БД: {len(db_map)} | В Sheets: {len(sheet_map)}")
    print(f"  Расхождения статусов: {mismatches}")
    if in_db_not_sheets:
        print(f"  В БД но нет в Sheets ({len(in_db_not_sheets)}): {', '.join(list(in_db_not_sheets)[:10])}")
    if in_sheets_not_db:
        print(f"  В Sheets но нет в БД ({len(in_sheets_not_db)}): {', '.join(list(in_sheets_not_db)[:10])}")
except Exception as e:
    print(f"  Ошибка Sheets: {e}")

print(f"\n=== ПРОБЛЕМЫ ({len(issues)}) ===")
for i in issues:
    print(f"  ⚠️  {i}")
if not issues:
    print("  ✅ Проблем не найдено")

conn.close()
