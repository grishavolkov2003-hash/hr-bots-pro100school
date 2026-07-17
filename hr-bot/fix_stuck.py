import sqlite3, json
from storage import get_candidate, get_conversation, add_message, update_candidate
from llm import get_response
import asyncio, re
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

# Fix statuses
conn = sqlite3.connect("candidates.db")

# Egor - already answered, fix status
conn.execute("UPDATE candidates SET status = 'ТЕСТОВОЕ_ОТПРАВЛЕНО' WHERE username LIKE '%always_on_chill%'")
print("Fixed @always_on_chill -> ТЕСТОВОЕ_ОТПРАВЛЕНО")

# Смирнова - has 9 bot messages, clearly past НОВЫЙ
conn.execute("UPDATE candidates SET status = 'АККАУНТ_ПОЛУЧЕН' WHERE username LIKE '%smirnovaanna%'")
print("Fixed @smirnovaannaaleksandrovna -> АККАУНТ_ПОЛУЧЕН")

conn.commit()
conn.close()

# Reply to unanswered ones
async def main():
    await client.start()

    need_reply = [
        {"username": "medoed0904", "uid": 398793884},
        {"username": "vaexxi", "uid": 779349641},
        {"username": "Alena_Vasilch", "uid": None},
    ]

    conn2 = sqlite3.connect("candidates.db")
    conn2.row_factory = sqlite3.Row

    for u in need_reply:
        if u["uid"]:
            r = conn2.execute("SELECT * FROM candidates WHERE user_id = ?", (u["uid"],)).fetchone()
        else:
            r = conn2.execute("SELECT * FROM candidates WHERE username LIKE ?", (f"%{u['username']}%",)).fetchone()

        if not r:
            print(f"  @{u['username']}: not found")
            continue

        d = dict(r)
        conv = json.loads(d["conversation"]) if d["conversation"] else []
        candidate = d

        response = get_response(conv, candidate)
        if not response:
            print(f"  @{u['username']}: no LLM response")
            continue

        clean = re.sub(r'>>>.*?<<<', '', response).strip()
        if not clean:
            print(f"  @{u['username']}: empty after cleanup")
            continue

        try:
            await client.send_message(u["username"], clean)
            add_message(d["user_id"], "bot", clean)
            update_candidate(d["user_id"], status="ТЕСТОВОЕ_ОТПРАВЛЕНО")
            print(f"  @{u['username']}: replied + ТЕСТОВОЕ_ОТПРАВЛЕНО | {clean[:80]}")
        except Exception as e:
            print(f"  @{u['username']}: send error: {e}")

    conn2.close()
    await client.disconnect()

asyncio.run(main())
