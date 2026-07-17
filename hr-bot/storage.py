import sqlite3
import json
from datetime import datetime
from config import DB_PATH

ALLOWED_COLUMNS = {
    "username", "name", "subject", "status", "source", "students_count",
    "has_profi_account", "conversation", "created_at", "updated_at",
    "comment", "score", "reminder_count", "last_reminder", "slots", "access_hash", "conversation_bot",
    "auto_qualified", "video_received_at",
}


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT,
            subject TEXT,
            status TEXT DEFAULT 'НОВЫЙ',
            source TEXT,
            students_count TEXT,
            has_profi_account TEXT,
            conversation TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT,
            comment TEXT DEFAULT '',
            score INTEGER DEFAULT 0,
            reminder_count INTEGER DEFAULT 0,
            last_reminder TEXT,
            slots TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_user_id INTEGER,
            candidate_name TEXT,
            candidate_username TEXT,
            slots TEXT,
            created_at TEXT,
            resolved INTEGER DEFAULT 0
        )
    """)
    for col in ["chosen_time TEXT", "notified INTEGER DEFAULT 0"]:
        try:
            conn.execute(f"ALTER TABLE pending_slots ADD COLUMN {col}")
        except:
            pass
    for col_def in ["score INTEGER DEFAULT 0", "reminder_count INTEGER DEFAULT 0", "last_reminder TEXT", "slots TEXT", "source TEXT", "conversation_bot TEXT DEFAULT 'hr'", "access_hash INTEGER DEFAULT 0", "auto_qualified INTEGER DEFAULT 0", "video_received_at TEXT"]:
        try:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {col_def}")
        except:
            pass
    conn.commit()
    conn.close()


def get_candidate(user_id):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def create_candidate(user_id, username, name):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "INSERT OR IGNORE INTO candidates (user_id, username, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, name, now, now)
    )
    conn.commit()
    conn.close()


def update_candidate(user_id, **kwargs):
    kwargs["updated_at"] = datetime.now().isoformat()
    safe_kwargs = {k: v for k, v in kwargs.items() if k in ALLOWED_COLUMNS}
    if not safe_kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in safe_kwargs)
    vals = list(safe_kwargs.values()) + [user_id]
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(f"UPDATE candidates SET {sets} WHERE user_id = ?", vals)
    conn.commit()
    conn.close()


def add_message(user_id, role, text):
    candidate = get_candidate(user_id)
    if not candidate:
        return
    history = json.loads(candidate["conversation"] or "[]")
    history.append({"role": role, "text": text, "time": datetime.now().isoformat()})
    # Было 30 - реальные данные показали, что 4.45% диалогов уже упирались
    # в этот лимит и теряли историю необратимо (max в базе точно == 30).
    # 300 - с большим запасом выше p99 (упирался в старый капped p99=30).
    if len(history) > 300:
        history = history[-300:]
    update_candidate(user_id, conversation=json.dumps(history, ensure_ascii=False))


def get_conversation(user_id):
    candidate = get_candidate(user_id)
    if not candidate:
        return []
    return json.loads(candidate["conversation"] or "[]")


def get_all_candidates():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stale_candidates(hours=24):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT * FROM candidates
        WHERE status IN ('ТЕСТОВОЕ_ОТПРАВЛЕНО')
        AND reminder_count < 3
        ORDER BY updated_at ASC
    """).fetchall()
    conn.close()

    result = []
    now = datetime.now()
    for r in rows:
        d = dict(r)
        updated = datetime.fromisoformat(d["updated_at"]) if d["updated_at"] else now
        hours_since = (now - updated).total_seconds() / 3600
        d["hours_since_update"] = hours_since
        if hours_since >= hours:
            result.append(d)
    return result


def update_conversation_bot(user_id, bot_name):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("UPDATE candidates SET conversation_bot=? WHERE user_id=?", (bot_name, user_id))
    conn.commit()
    conn.close()

def update_access_hash(user_id, access_hash):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("UPDATE candidates SET access_hash=? WHERE user_id=?", (access_hash, user_id))
    conn.commit()
    conn.close()
