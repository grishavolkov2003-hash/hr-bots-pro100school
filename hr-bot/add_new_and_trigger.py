import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os, sqlite3, json
from datetime import datetime
from storage import init_db, create_candidate, get_candidate

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

async def main():
    await client.start()

    conn = sqlite3.connect("candidates.db")
    conn.row_factory = sqlite3.Row

    new_users = [
        {"username": "medoed0904", "name": "Роман Г."},
        {"username": "vaexxi", "name": "вовка"},
    ]

    for u in new_users:
        existing = conn.execute("SELECT user_id FROM candidates WHERE username LIKE ?",
                               (f"%{u['username']}%",)).fetchone()
        if existing:
            print(f"  @{u['username']} already in DB")
            continue

        try:
            entity = await client.get_entity(u["username"])
            uid = entity.id
            name = (entity.first_name or "") + (" " + (entity.last_name or "")).rstrip()

            conn.execute("""
                INSERT INTO candidates (user_id, username, name, status, conversation, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (uid, f"@{u['username']}", name, "НОВЫЙ", "[]",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            # Read their messages and add to conversation
            msgs = await client.get_messages(entity, limit=10)
            conv = []
            for m in reversed(msgs):
                if m.out:
                    continue
                t = m.text or ""
                if not t:
                    if m.video or m.video_note or m.voice:
                        t = "[Отправлено медиа: видео/голосовое]"
                    elif m.photo:
                        t = "[Отправлено фото]"
                    elif m.document:
                        t = "[Отправлен документ]"
                    else:
                        continue
                conv.append({"role": "candidate", "content": t})

            conn.execute("UPDATE candidates SET conversation = ? WHERE user_id = ?",
                        (json.dumps(conv, ensure_ascii=False), uid))

            print(f"  Added @{u['username']} ({name}) uid={uid} with {len(conv)} messages")

        except Exception as e:
            print(f"  Error @{u['username']}: {e}")

    conn.commit()
    conn.close()
    await client.disconnect()
    print("\nDone! Patrol will pick them up on next tick.")

asyncio.run(main())
