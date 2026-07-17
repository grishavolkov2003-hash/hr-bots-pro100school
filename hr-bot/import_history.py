import asyncio
import json
import sqlite3
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

load_dotenv("/opt/hr-bot/.env")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION_STRING")
DB_PATH = os.getenv("DB_PATH", "/opt/hr-bot/candidates.db")

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

HR_KEYWORDS = [
    "вакансия", "вакансии", "репетитор", "анкет", "задание для отбора",
    "профи.ру", "profi.ru", "видеоразбор", "видеовизитк", "hh.ru",
    "hh ", "headhunter", "тестовое", "по вакансии", "комиссия",
    "преподаватель", "ученик", "егэ", "огэ", "предмет",
    "образование", "опыт репетитор", "часов в неделю",
    "pro100school", "собеседовани", "созвон",
]


def is_hr_chat(messages):
    for msg in messages:
        text = (msg.text or "").lower()
        for kw in HR_KEYWORDS:
            if kw in text:
                return True
    return False


def init_db():
    conn = sqlite3.connect(DB_PATH)
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
            comment TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


async def main():
    await client.start()
    print("Подключен. Ищу HR-чаты...")

    dialogs = await client.get_dialogs(limit=200)
    private_chats = [d for d in dialogs if d.is_user and not d.entity.bot]

    print(f"Всего личных чатов: {len(private_chats)}")

    imported = 0
    skipped = 0

    for dialog in private_chats:
        user = dialog.entity
        user_id = user.id
        username = f"@{user.username}" if user.username else ""
        name = (user.first_name or "") + (" " + (user.last_name or "")).rstrip()

        messages = await client.get_messages(user_id, limit=50)
        if not messages:
            continue

        if not is_hr_chat(messages):
            skipped += 1
            continue

        conn = sqlite3.connect(DB_PATH)
        existing = conn.execute("SELECT user_id FROM candidates WHERE user_id = ?", (user_id,)).fetchone()

        conversation = []
        for msg in reversed(messages):
            if not msg.text:
                if msg.video or msg.video_note or msg.voice:
                    text = "[Отправлено медиа: видео/голосовое]"
                elif msg.document or msg.photo:
                    text = "[Отправлен файл/фото]"
                else:
                    continue
            else:
                text = msg.text

            role = "bot" if msg.out else "candidate"
            conversation.append({
                "role": role,
                "text": text[:500],
                "time": msg.date.isoformat() if msg.date else "",
            })

        if len(conversation) > 30:
            conversation = conversation[-30:]

        conv_json = json.dumps(conversation, ensure_ascii=False)
        now = datetime.now().isoformat()

        if existing:
            conn.execute(
                "UPDATE candidates SET conversation = ?, updated_at = ? WHERE user_id = ?",
                (conv_json, now, user_id)
            )
        else:
            first_msg_date = messages[-1].date.isoformat() if messages else now
            conn.execute(
                "INSERT INTO candidates (user_id, username, name, conversation, created_at, updated_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, username, name, conv_json, first_msg_date, now, "ИМПОРТ")
            )

        conn.commit()
        conn.close()
        imported += 1
        print(f"  ✅ {name} ({username}) — {len(conversation)} сообщений")

    print(f"\nИтого: {imported} HR-чатов импортировано, {skipped} пропущено")
    await client.disconnect()


if __name__ == "__main__":
    init_db()
    with client:
        client.loop.run_until_complete(main())
