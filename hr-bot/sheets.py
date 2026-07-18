import gspread
from google.oauth2.credentials import Credentials
import json
import os
import logging
from datetime import datetime
from config import GOOGLE_SHEETS_CREDS

SHEET_NAME = "HR Воронка — репетиторы"
_sheet = None


def _get_sheet():
    global _sheet
    if _sheet:
        try:
            _sheet.sheet1
            return _sheet
        except Exception:
            _sheet = None

    creds_path = GOOGLE_SHEETS_CREDS
    if not os.path.exists(creds_path):
        logging.warning(f"Google creds not found: {creds_path}")
        return None

    with open(creds_path) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data.get("scopes"),
    )

    from google.auth.transport.requests import Request
    if creds.expired or not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as e:
            logging.error(f"Google Sheets creds refresh error: {e}")
            return None

    gc = gspread.authorize(creds)
    try:
        try:
            sh = gc.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(SHEET_NAME)
            sh.share(None, perm_type="anyone", role="reader")
            ws = sh.sheet1
            ws.update_title("Кандидаты")
            ws.update(
                range_name="A1:J1",
                values=[["Дата", "Имя", "Username", "Предмет", "Источник", "Учеников", "Аккаунт Профи", "Статус", "Последнее действие", "Комментарий", "Скор"]],
            )
            ws.format("A1:J1", {"textFormat": {"bold": True}})
            logging.info(f"Created sheet: {sh.url}")
    except Exception as e:
        logging.error(f"Google Sheets open/create error: {e}")
        return None

    _sheet = sh
    return sh


def add_candidate(candidate):
    sh = _get_sheet()
    if not sh:
        return
    username = candidate.get("username", "")
    try:
        ws = sh.sheet1
        try:
            if username and ws.find(username):
                return
        except gspread.exceptions.CellNotFound:
            pass
        ws.append_row([
            candidate.get("created_at", datetime.now().isoformat())[:10],
            candidate.get("name", ""),
            username,
            candidate.get("subject", ""),
            candidate.get("source", ""),
            candidate.get("students_count", ""),
            candidate.get("has_profi_account", ""),
            candidate.get("status", "НОВЫЙ"),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            candidate.get("comment", ""),
        ])
    except Exception as e:
        logging.error(f"Sheets add_candidate error: {e}")


def update_status(username, status, comment=""):
    sh = _get_sheet()
    if not sh:
        return
    try:
        ws = sh.sheet1
        cell = ws.find(username)
        if cell:
            ws.update_cell(cell.row, 8, status)
            ws.update_cell(cell.row, 9, datetime.now().strftime("%Y-%m-%d %H:%M"))
            if comment:
                ws.update_cell(cell.row, 10, comment)
    except Exception as e:
        logging.error(f"Sheets update error: {e}")


def update_anketa(username, anketa):
    sh = _get_sheet()
    if not sh:
        return
    try:
        ws = sh.sheet1
        cell = ws.find(username)
        if cell:
            row = cell.row
            if anketa.get("предмет"):
                ws.update_cell(row, 4, anketa["предмет"])
            if anketa.get("источник"):
                ws.update_cell(row, 5, anketa["источник"])
            comment = f"Обр: {anketa.get('образование', '')} | ЕГЭ: {anketa.get('егэ', '')} | Опыт: {anketa.get('опыт', '')} | Часы/нед: {anketa.get('часы', '')}"
            ws.update_cell(row, 10, comment)
            ws.update_cell(row, 9, datetime.now().strftime("%Y-%m-%d %H:%M"))
    except Exception as e:
        logging.error(f"Sheets anketa error: {e}")


def update_score(username, score):
    sh = _get_sheet()
    if not sh:
        return
    try:
        ws = sh.sheet1
        cell = ws.find(username)
        if cell:
            ws.update_cell(cell.row, 11, str(score))
    except Exception as e:
        logging.error(f"Sheets score error: {e}")


KANBAN_STATUSES = [
    "НОВЫЙ",
    "ТЕСТОВОЕ_ОТПРАВЛЕНО",
    "ТЕСТОВОЕ_ПОЛУЧЕНО",
    "ТЕСТОВОЕ_НА_ПРОВЕРКЕ",
    "ГОТОВ_К_СОЗВОНУ",
    "ПЕРЕДАН_МЕНЕДЖЕРУ",
    "СОЗВОН_НАЗНАЧЕН",
    "АККАУНТ_ПОЛУЧЕН",
    "ОТКАЗ",
    "ЗАМОРОЗКА",
]

KANBAN_HEADERS = {
    "НОВЫЙ": "Новые",
    "ТЕСТОВОЕ_ОТПРАВЛЕНО": "Тестовое отпр.",
    "ТЕСТОВОЕ_ПОЛУЧЕНО": "Тестовое получ.",
    "ТЕСТОВОЕ_НА_ПРОВЕРКЕ": "На проверке",
    "ГОТОВ_К_СОЗВОНУ": "Готов к созвону",
    "ПЕРЕДАН_МЕНЕДЖЕРУ": "Передан менедж.",
    "СОЗВОН_НАЗНАЧЕН": "Созвон назначен",
    "АККАУНТ_ПОЛУЧЕН": "Акк получен",
    "ОТКАЗ": "Отказ",
    "ЗАМОРОЗКА": "Заморозка",
}


def sync_kanban(all_candidates):
    sh = _get_sheet()
    if not sh:
        return

    try:
        ws = sh.worksheet("Канбан")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Канбан", rows=200, cols=len(KANBAN_STATUSES) * 2)

    by_status = {s: [] for s in KANBAN_STATUSES}
    for c in all_candidates:
        st = c.get("status", "НОВЫЙ")
        if st in by_status:
            name = c.get("name", "—")
            uname = c.get("username", "")
            if uname:
                uname = f"@{uname.lstrip('@')}"
            by_status[st].append(f"{name}\n{uname}" if uname else name)

    max_rows = max((len(v) for v in by_status.values()), default=0)

    data = []
    header = []
    counts = []
    for s in KANBAN_STATUSES:
        header.append(f"{KANBAN_HEADERS[s]} ({len(by_status[s])})")
    data.append(header)

    for i in range(max_rows):
        row = []
        for s in KANBAN_STATUSES:
            people = by_status[s]
            row.append(people[i] if i < len(people) else "")
        data.append(row)

    chart_labels = [KANBAN_HEADERS[s] for s in KANBAN_STATUSES]
    chart_values = [len(by_status[s]) for s in KANBAN_STATUSES]

    chart_row = len(data) + 2
    data_with_chart = list(data)
    data_with_chart.append([])
    data_with_chart.append(chart_labels)
    data_with_chart.append(chart_values)

    last_col = chr(64 + len(KANBAN_STATUSES))
    ws.clear()
    ws.update(range_name=f"A1:{last_col}{len(data_with_chart)}", values=data_with_chart)

    ws.format(f"A1:{last_col}1", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
        "horizontalAlignment": "CENTER",
        "wrapStrategy": "WRAP",
    })

    ws.format(f"A2:{last_col}{max(len(data), 2)}", {
        "wrapStrategy": "WRAP",
        "verticalAlignment": "TOP",
    })

    _sync_chart(sh, ws, chart_row, len(KANBAN_STATUSES))

    logging.info(f"[sheets] Kanban synced: {sum(len(v) for v in by_status.values())} candidates")


def _sync_chart(spreadsheet, worksheet, chart_row, num_cols):
    sheet_id = worksheet.id
    labels_row = chart_row
    values_row = chart_row + 1

    existing_charts = worksheet.list_charts() if hasattr(worksheet, 'list_charts') else []

    chart_spec = {
        "title": "Воронка найма",
        "basicChart": {
            "chartType": "COLUMN",
            "legendPosition": "NO_LEGEND",
            "axis": [
                {"position": "BOTTOM_AXIS", "title": "Статус"},
                {"position": "LEFT_AXIS", "title": "Кандидатов"},
            ],
            "domains": [{
                "domain": {
                    "sourceRange": {
                        "sources": [{
                            "sheetId": sheet_id,
                            "startRowIndex": labels_row - 1,
                            "endRowIndex": labels_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_cols,
                        }]
                    }
                }
            }],
            "series": [{
                "series": {
                    "sourceRange": {
                        "sources": [{
                            "sheetId": sheet_id,
                            "startRowIndex": values_row - 1,
                            "endRowIndex": values_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_cols,
                        }]
                    }
                },
                "targetAxis": "LEFT_AXIS",
                "color": {"red": 0.26, "green": 0.52, "blue": 0.96},
                "dataLabel": {
                    "type": "DATA",
                    "textFormat": {"bold": True},
                },
            }],
        },
    }

    requests = []

    if existing_charts:
        for chart in existing_charts:
            requests.append({"deleteEmbeddedObject": {"objectId": chart.id}})

    requests.append({
        "addChart": {
            "chart": {
                "spec": chart_spec,
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": values_row,
                            "columnIndex": 0,
                        },
                        "offsetXPixels": 0,
                        "offsetYPixels": 20,
                        "widthPixels": 900,
                        "heightPixels": 400,
                    }
                },
            }
        }
    })

    spreadsheet.batch_update({"requests": requests})


FUNNEL_ORDER = [
    "НОВЫЙ", "ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_ПОЛУЧЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ",
    "ГОТОВ_К_СОЗВОНУ", "ПЕРЕДАН_МЕНЕДЖЕРУ", "СОЗВОН_НАЗНАЧЕН",
    "АККАУНТ_ПОЛУЧЕН", "ОТКРЫТ",
]

FUNNEL_LABELS = {
    "НОВЫЙ": "Новые",
    "ТЕСТОВОЕ_ОТПРАВЛЕНО": "Анкета отпр.",
    "ТЕСТОВОЕ_ПОЛУЧЕНО": "Видео получ.",
    "ТЕСТОВОЕ_НА_ПРОВЕРКЕ": "На проверке",
    "ГОТОВ_К_СОЗВОНУ": "Одобрены",
    "ПЕРЕДАН_МЕНЕДЖЕРУ": "Переданы",
    "СОЗВОН_НАЗНАЧЕН": "Созвон назн.",
    "АККАУНТ_ПОЛУЧЕН": "Акк получен",
    "ОТКРЫТ": "Работают",
}


def sync_dashboard(all_candidates):
    sh = _get_sheet()
    if not sh:
        return

    try:
        ws = sh.worksheet("Дашборд")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Дашборд", rows=50, cols=10)

    total = len(all_candidates)
    by_status = {}
    by_source = {}
    by_source_status = {}

    for c in all_candidates:
        st = c.get("status", "НОВЫЙ")
        src = c.get("source", "telegram") or "telegram"
        by_status[st] = by_status.get(st, 0) + 1
        by_source[src] = by_source.get(src, 0) + 1
        key = (src, st)
        by_source_status[key] = by_source_status.get(key, 0) + 1

    lost = by_status.get("ОТКАЗ", 0) + by_status.get("ЗАМОРОЗКА", 0)

    data = []
    data.append(["ДАШБОРД HR-ВОРОНКИ", "", "", f"Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}"])
    data.append([])

    # Funnel conversion
    data.append(["ВОРОНКА КОНВЕРСИИ", "Кол-во", "% от всех", "% от предыд."])
    prev = total
    for st in FUNNEL_ORDER:
        count = by_status.get(st, 0)
        reached = sum(by_status.get(s, 0) for s in FUNNEL_ORDER[FUNNEL_ORDER.index(st):])
        pct_total = round(reached / total * 100) if total else 0
        pct_prev = round(reached / prev * 100) if prev else 0
        data.append([FUNNEL_LABELS.get(st, st), reached, f"{pct_total}%", f"{pct_prev}%"])
        prev = reached
    data.append(["Отказ + Заморозка", lost, f"{round(lost/total*100)}%" if total else "0%", ""])
    data.append([])

    # Source breakdown
    data.append(["ИСТОЧНИКИ", "Кол-во", "% от всех", ""])
    for src in sorted(by_source.keys(), key=lambda x: -by_source[x]):
        count = by_source[src]
        pct = round(count / total * 100) if total else 0
        data.append([src, count, f"{pct}%", ""])
    data.append([])

    # Source x Status matrix
    sources = sorted(by_source.keys(), key=lambda x: -by_source[x])
    matrix_header = ["ИСТОЧНИК \\ СТАТУС"] + [FUNNEL_LABELS.get(s, s) for s in FUNNEL_ORDER] + ["Отказ", "Замор."]
    data.append(matrix_header)
    for src in sources:
        row = [src]
        for st in FUNNEL_ORDER:
            row.append(by_source_status.get((src, st), 0))
        row.append(by_source_status.get((src, "ОТКАЗ"), 0))
        row.append(by_source_status.get((src, "ЗАМОРОЗКА"), 0))
        data.append(row)
    data.append([])

    # Key metrics
    data.append(["КЛЮЧЕВЫЕ МЕТРИКИ", "", "", ""])
    data.append(["Всего кандидатов", total, "", ""])
    active = sum(1 for c in all_candidates if c.get("status") not in ("ОТКАЗ", "ЗАМОРОЗКА"))
    data.append(["Активных", active, "", ""])
    data.append(["Конверсия в созвон", f"{round(sum(by_status.get(s,0) for s in ('СОЗВОН_НАЗНАЧЕН','АККАУНТ_ПОЛУЧЕН','ОТКРЫТ'))/total*100)}%" if total else "0%", "", ""])
    data.append(["Конверсия в акк", f"{round(sum(by_status.get(s,0) for s in ('АККАУНТ_ПОЛУЧЕН','ОТКРЫТ'))/total*100)}%" if total else "0%", "", ""])
    data.append(["Потери (отказ+замор.)", lost, f"{round(lost/total*100)}%" if total else "0%", ""])

    last_col = chr(64 + max(len(r) for r in data))
    ws.clear()
    ws.update(range_name=f"A1:{last_col}{len(data)}", values=data)

    ws.format("A1:D1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A3:D3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0}})
    funnel_end = 3 + len(FUNNEL_ORDER) + 1
    ws.format(f"A{funnel_end+2}:D{funnel_end+2}", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}})

    logging.info(f"[sheets] Dashboard synced: {total} candidates")
